#!/usr/bin/env python3
"""
ra_log_engine.py — Production-Grade Real-Environment `.log` Telemetry, Watchdog & Flow Auditor for RA.

Replaces "trash synthetic unit tests" and 30-minute runaway test marathons with
real-environment deployment logging that captures:
1. Full Flow Lineage (`Trace ID`, `Cycle`, `Hop Index`, `Upstream Caller -> Current Function`).
2. Functional Purpose (`role`: what this code step does in the system).
3. Complete Runtime Value Telemetry (`inputs`, `state_before`, `state_after`, `state_delta`, `output`).
4. Explicit Branch & Threshold Decisions (`condition`, `evaluated_values`, `branch_taken`).
5. Live Status Tags:
   - `[PASS]`    : Step succeeded with full functional + value proof and contract verification (`BC-xxx`).
   - `[STUCK]`   : Step exceeded `stuck_threshold_ms` or `max_iterations` polling/waiting; dumps exact
                   waiting condition and live variable state, then aborts before hanging.
   - `[FAIL]`    : Step or contract (`BC-xxx`) failed; dumps upstream caller, culprit state, and values.
   - `[DECISION]`: Branch/routing decision with exact threshold values evaluated.

Provides:
- Importable Python SDK (`RALogger`) for direct wiring into Python deployment code.
- Multi-Language SDK Generator (`inject-sdk --lang python|js|ts|php`) for any project stack.
- Watchdog Process Runner (`run --timeout-sec 60 --cmd "..."`) that prevents 30-minute hangs.
- Deep `.log` Flow & Value Auditor (`audit`) that rejects bare "ok/pass" AI slop and verifies
  every workflow hop and behavioral contract (`BC-xxx`) from real `.log` files.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="milliseconds")


def safe_serialize(val: Any, max_len: int = 400) -> Any:
    """Safely serialize arbitrary runtime objects into JSON-compatible structures for `.log` output."""
    if val is None or isinstance(val, (bool, int, float)):
        return val
    if isinstance(val, str):
        return val if len(val) <= max_len else val[:max_len] + "...<truncated>"
    if isinstance(val, (list, tuple, set)):
        seq = list(val)
        out = [safe_serialize(x, max_len=120) for x in seq[:20]]
        if len(seq) > 20:
            out.append(f"...(+{len(seq) - 20} more items)")
        return out
    if isinstance(val, dict):
        out_dict: Dict[str, Any] = {}
        for idx, (k, v) in enumerate(val.items()):
            if idx >= 25:
                out_dict["..."] = f"+{len(val) - 25} more keys"
                break
            out_dict[str(k)] = safe_serialize(v, max_len=120)
        return out_dict
    if hasattr(val, "__dict__"):
        return {
            "__type__": type(val).__name__,
            "attrs": safe_serialize(vars(val), max_len=120),
        }
    s = repr(val)
    return s if len(s) <= max_len else s[:max_len] + "...<truncated>"


def compute_state_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Compute exact before -> after value changes across state dictionaries."""
    delta: Dict[str, Any] = {}
    all_keys = set(before.keys()) | set(after.keys())
    for k in sorted(all_keys):
        b_val = before.get(k, "<UNSET>")
        a_val = after.get(k, "<DELETED>")
        if b_val != a_val:
            delta[k] = {"from": safe_serialize(b_val), "to": safe_serialize(a_val)}
    return delta


class StuckExecutionError(RuntimeError):
    """Raised when a real-environment step exceeds its watchdog time or iteration limit."""


class ContractBreachError(AssertionError):
    """Raised when an Existing Behavioral Contract (`BC-xxx`) is violated at runtime."""


class RALogger:
    """
    Production-Grade Real-Environment Flow & Value Logger.
    Writes structured human-readable + JSONL telemetry lines to `.log`.
    """

    def __init__(self, log_path: str | Path, trace_id: str = "REAL_RUN_01") -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_id = trace_id
        self.hop_counter = 0

    def _caller_chain(self, depth: int = 2) -> str:
        stack = inspect.stack()
        if len(stack) <= depth:
            return "root->entry"
        curr_frame = stack[depth]
        caller_frame = stack[depth + 1] if len(stack) > depth + 1 else curr_frame
        caller_file = Path(caller_frame.filename).name
        curr_file = Path(curr_frame.filename).name
        return f"{caller_file}:{caller_frame.function}:L{caller_frame.lineno}->{curr_file}:{curr_frame.function}:L{curr_frame.lineno}"

    def _write_record(self, status: str, payload: Dict[str, Any]) -> None:
        self.hop_counter += 1
        ts = now_iso()
        hop = payload.get("hop", self.hop_counter)
        flow = payload.get("flow", "unknown->unknown")
        role = payload.get("role", "unspecified")
        inputs = json.dumps(safe_serialize(payload.get("inputs", {})), ensure_ascii=False)
        s_before = json.dumps(safe_serialize(payload.get("state_before", {})), ensure_ascii=False)
        s_after = json.dumps(safe_serialize(payload.get("state_after", {})), ensure_ascii=False)
        delta = json.dumps(safe_serialize(payload.get("state_delta", {})), ensure_ascii=False)
        output = json.dumps(safe_serialize(payload.get("output", None)), ensure_ascii=False)
        contract = payload.get("contract", "NONE")
        elapsed_ms = payload.get("elapsed_ms", 0.0)
        reason = payload.get("reason", "")

        full_json = {
            "timestamp": ts,
            "trace_id": self.trace_id,
            "hop": hop,
            "status": status,
            "flow": flow,
            "role": role,
            "inputs": safe_serialize(payload.get("inputs", {})),
            "state_before": safe_serialize(payload.get("state_before", {})),
            "state_after": safe_serialize(payload.get("state_after", {})),
            "state_delta": safe_serialize(payload.get("state_delta", {})),
            "output": safe_serialize(payload.get("output", None)),
            "contract": contract,
            "elapsed_ms": round(float(elapsed_ms), 3),
            "reason": reason,
        }

        line = (
            f"{ts} | TRACE={self.trace_id} | HOP={hop:04d} | [{status}] "
            f"| flow={flow} | role=\"{role}\" | inputs={inputs} "
            f"| state_before={s_before} | state_after={s_after} | delta={delta} "
            f"| output={output} | contract={contract} | elapsed_ms={elapsed_ms:.3f}"
            + (f" | reason=\"{reason}\"" if reason else "")
            + f" || RA_JSON={json.dumps(full_json, ensure_ascii=False)}\n"
        )
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def log_pass(
        self,
        *,
        role: str,
        inputs: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any],
        output: Any,
        contract: str = "NONE",
        elapsed_ms: float = 0.0,
        flow: Optional[str] = None,
    ) -> None:
        delta = compute_state_delta(state_before, state_after)
        self._write_record(
            "PASS",
            {
                "flow": flow or self._caller_chain(depth=2),
                "role": role,
                "inputs": inputs,
                "state_before": state_before,
                "state_after": state_after,
                "state_delta": delta,
                "output": output,
                "contract": contract,
                "elapsed_ms": elapsed_ms,
            },
        )

    def log_decision(
        self,
        *,
        role: str,
        condition: str,
        evaluated_values: Dict[str, Any],
        branch_taken: str,
        state_snapshot: Dict[str, Any],
        flow: Optional[str] = None,
    ) -> None:
        self._write_record(
            "DECISION",
            {
                "flow": flow or self._caller_chain(depth=2),
                "role": role,
                "inputs": {"condition": condition, "evaluated_values": evaluated_values},
                "state_before": state_snapshot,
                "state_after": state_snapshot,
                "state_delta": {},
                "output": {"branch_taken": branch_taken},
                "contract": "BRANCH_TRACE",
                "elapsed_ms": 0.0,
            },
        )

    def log_stuck(
        self,
        *,
        role: str,
        waiting_on: str,
        current_values: Dict[str, Any],
        state_snapshot: Dict[str, Any],
        elapsed_ms: float,
        flow: Optional[str] = None,
    ) -> None:
        self._write_record(
            "STUCK",
            {
                "flow": flow or self._caller_chain(depth=2),
                "role": role,
                "inputs": {"waiting_on": waiting_on, "current_values": current_values},
                "state_before": state_snapshot,
                "state_after": state_snapshot,
                "state_delta": {},
                "output": "STUCK_TIMEOUT",
                "contract": "WATCHDOG_BREACH",
                "elapsed_ms": elapsed_ms,
                "reason": f"Stuck waiting on `{waiting_on}` for {elapsed_ms:.1f}ms",
            },
        )

    def log_fail(
        self,
        *,
        role: str,
        reason: str,
        inputs: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any],
        contract: str = "NONE",
        elapsed_ms: float = 0.0,
        flow: Optional[str] = None,
    ) -> None:
        delta = compute_state_delta(state_before, state_after)
        self._write_record(
            "FAIL",
            {
                "flow": flow or self._caller_chain(depth=2),
                "role": role,
                "inputs": inputs,
                "state_before": state_before,
                "state_after": state_after,
                "state_delta": delta,
                "output": "FAILED",
                "contract": contract,
                "elapsed_ms": elapsed_ms,
                "reason": reason,
            },
        )

    def assert_contract(
        self,
        contract_id: str,
        condition: bool,
        *,
        role: str,
        actual_values: Dict[str, Any],
        state_snapshot: Dict[str, Any],
    ) -> None:
        flow = self._caller_chain(depth=2)
        if not condition:
            self.log_fail(
                role=role,
                reason=f"Behavioral Contract `{contract_id}` violated! Actual values: {actual_values}",
                inputs=actual_values,
                state_before=state_snapshot,
                state_after=state_snapshot,
                contract=contract_id,
                flow=flow,
            )
            raise ContractBreachError(f"[RA CONTRACT BREACH] {contract_id}: {actual_values}")
        self.log_pass(
            role=f"Contract Verification ({contract_id}): {role}",
            inputs=actual_values,
            state_before=state_snapshot,
            state_after=state_snapshot,
            output="CONTRACT_HOLDING",
            contract=contract_id,
            elapsed_ms=0.1,
            flow=flow,
        )

    def trace_step(
        self,
        *,
        role: str,
        state_getter: Optional[Callable[[], Dict[str, Any]]] = None,
        contract: str = "NONE",
        stuck_threshold_ms: float = 5000.0,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator that automatically logs flow, inputs, state_before, state_after, output, and elapsed_ms."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                stack = inspect.stack()
                if len(stack) > 1:
                    cframe = stack[1]
                    caller_str = f"{Path(cframe.filename).name}:{cframe.function}:L{cframe.lineno}"
                else:
                    caller_str = "root"
                callee_file = Path(func.__code__.co_filename).name if hasattr(func, "__code__") else "module"
                callee_line = func.__code__.co_firstlineno if hasattr(func, "__code__") else 0
                flow = f"{caller_str}->{callee_file}:{func.__name__}:L{callee_line}"
                bound_inputs = {"args": safe_serialize(args), "kwargs": safe_serialize(kwargs)}
                s_before = copy.deepcopy(state_getter()) if state_getter else {}
                t0 = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    s_after = copy.deepcopy(state_getter()) if state_getter else s_before
                    self.log_fail(
                        role=role,
                        reason=f"{type(exc).__name__}: {exc}",
                        inputs=bound_inputs,
                        state_before=s_before,
                        state_after=s_after,
                        contract=contract,
                        elapsed_ms=elapsed,
                        flow=flow,
                    )
                    raise
                elapsed = (time.perf_counter() - t0) * 1000.0
                s_after = copy.deepcopy(state_getter()) if state_getter else s_before
                if elapsed > stuck_threshold_ms:
                    self.log_stuck(
                        role=role,
                        waiting_on=f"{func.__name__} exceeded stuck_threshold_ms ({stuck_threshold_ms}ms)",
                        current_values=bound_inputs,
                        state_snapshot=s_after,
                        elapsed_ms=elapsed,
                        flow=flow,
                    )
                else:
                    self.log_pass(
                        role=role,
                        inputs=bound_inputs,
                        state_before=s_before,
                        state_after=s_after,
                        output=result,
                        contract=contract,
                        elapsed_ms=elapsed,
                        flow=flow,
                    )
                return result

            return wrapper

        return decorator


JS_TS_LOGGER_SDK = '''/**
 * ra_logger.js — Production-Grade Real-Environment Flow & Value Logger for RA.
 * Logs [PASS], [DECISION], [STUCK], and [FAIL] with full caller->callee flow,
 * functional purpose, inputs, state_before -> state_after, delta, and elapsed_ms.
 */
const fs = require('fs');
const path = require('path');

class RALogger {
  constructor(logPath, traceId = 'REAL_RUN_01') {
    this.logPath = logPath;
    this.traceId = traceId;
    this.hopCounter = 0;
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
  }

  _write(status, payload) {
    this.hopCounter += 1;
    const ts = new Date().toISOString();
    const record = {
      timestamp: ts,
      trace_id: this.traceId,
      hop: this.hopCounter,
      status,
      flow: payload.flow || 'caller->callee',
      role: payload.role || 'unspecified',
      inputs: payload.inputs || {},
      state_before: payload.state_before || {},
      state_after: payload.state_after || {},
      state_delta: payload.state_delta || {},
      output: payload.output ?? null,
      contract: payload.contract || 'NONE',
      elapsed_ms: Number((payload.elapsed_ms || 0).toFixed(3)),
      reason: payload.reason || ''
    };
    const line = `${ts} | TRACE=${this.traceId} | HOP=${String(this.hopCounter).padStart(4, '0')} | [${status}] | flow=${record.flow} | role="${record.role}" | inputs=${JSON.stringify(record.inputs)} | state_before=${JSON.stringify(record.state_before)} | state_after=${JSON.stringify(record.state_after)} | delta=${JSON.stringify(record.state_delta)} | output=${JSON.stringify(record.output)} | contract=${record.contract} | elapsed_ms=${record.elapsed_ms}${record.reason ? ` | reason="${record.reason}"` : ''} || RA_JSON=${JSON.stringify(record)}\\n`;
    fs.appendFileSync(this.logPath, line, { encoding: 'utf8' });
  }

  logPass({ flow, role, inputs, state_before, state_after, output, contract = 'NONE', elapsed_ms = 0 }) {
    this._write('PASS', { flow, role, inputs, state_before, state_after, output, contract, elapsed_ms });
  }

  logDecision({ flow, role, condition, evaluated_values, branch_taken, state_snapshot }) {
    this._write('DECISION', {
      flow, role,
      inputs: { condition, evaluated_values },
      state_before: state_snapshot,
      state_after: state_snapshot,
      output: { branch_taken },
      contract: 'BRANCH_TRACE',
      elapsed_ms: 0
    });
  }

  logStuck({ flow, role, waiting_on, current_values, state_snapshot, elapsed_ms }) {
    this._write('STUCK', {
      flow, role,
      inputs: { waiting_on, current_values },
      state_before: state_snapshot,
      state_after: state_snapshot,
      output: 'STUCK_TIMEOUT',
      contract: 'WATCHDOG_BREACH',
      elapsed_ms,
      reason: `Stuck waiting on ${waiting_on} for ${elapsed_ms}ms`
    });
  }

  logFail({ flow, role, reason, inputs, state_before, state_after, contract = 'NONE', elapsed_ms = 0 }) {
    this._write('FAIL', { flow, role, reason, inputs, state_before, state_after, output: 'FAILED', contract, elapsed_ms });
  }

  assertContract(contractId, condition, { flow, role, actual_values, state_snapshot }) {
    if (!condition) {
      this.logFail({ flow, role, reason: `Behavioral Contract ${contractId} violated`, inputs: actual_values, state_before: state_snapshot, state_after: state_snapshot, contract: contractId });
      throw new Error(`[RA CONTRACT BREACH] ${contractId}`);
    }
    this.logPass({ flow, role: `Contract Verification (${contractId}): ${role}`, inputs: actual_values, state_before: state_snapshot, state_after: state_snapshot, output: 'CONTRACT_HOLDING', contract: contractId, elapsed_ms: 0.1 });
  }
}

module.exports = { RALogger };
'''

PHP_LOGGER_SDK = '''<?php
/**
 * RALogger.php — Production-Grade Real-Environment Flow & Value Logger for RA (Laravel / PHP).
 */
class RALogger {
    private string $logPath;
    private string $traceId;
    private int $hopCounter = 0;

    public function __construct(string $logPath, string $traceId = 'REAL_RUN_01') {
        $this->logPath = $logPath;
        $this->traceId = $traceId;
        $dir = dirname($logPath);
        if (!is_dir($dir)) {
            mkdir($dir, 0777, true);
        }
    }

    public function writeRecord(string $status, array $payload): void {
        $this->hopCounter++;
        $ts = (new DateTimeImmutable())->format('Y-m-d\\TH:i:s.vP');
        $record = [
            'timestamp' => $ts,
            'trace_id' => $this->traceId,
            'hop' => $this->hopCounter,
            'status' => $status,
            'flow' => $payload['flow'] ?? 'caller->callee',
            'role' => $payload['role'] ?? 'unspecified',
            'inputs' => $payload['inputs'] ?? [],
            'state_before' => $payload['state_before'] ?? [],
            'state_after' => $payload['state_after'] ?? [],
            'state_delta' => $payload['state_delta'] ?? [],
            'output' => $payload['output'] ?? null,
            'contract' => $payload['contract'] ?? 'NONE',
            'elapsed_ms' => round((float)($payload['elapsed_ms'] ?? 0.0), 3),
            'reason' => $payload['reason'] ?? '',
        ];
        $json = json_encode($record, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        $hopStr = str_pad((string)$this->hopCounter, 4, '0', STR_PAD_LEFT);
        $line = "{$ts} | TRACE={$this->traceId} | HOP={$hopStr} | [{$status}] | flow={$record['flow']} | role=\\"{$record['role']}\\" | inputs=" . json_encode($record['inputs'], JSON_UNESCAPED_UNICODE) . " | state_before=" . json_encode($record['state_before'], JSON_UNESCAPED_UNICODE) . " | state_after=" . json_encode($record['state_after'], JSON_UNESCAPED_UNICODE) . " | delta=" . json_encode($record['state_delta'], JSON_UNESCAPED_UNICODE) . " | output=" . json_encode($record['output'], JSON_UNESCAPED_UNICODE) . " | contract={$record['contract']} | elapsed_ms={$record['elapsed_ms']} || RA_JSON={$json}\\n";
        file_put_contents($this->logPath, $line, FILE_APPEND | LOCK_EX);
    }

    public function logPass(array $payload): void { $this->writeRecord('PASS', $payload); }
    public function logDecision(array $payload): void { $this->writeRecord('DECISION', $payload); }
    public function logStuck(array $payload): void { $this->writeRecord('STUCK', $payload); }
    public function logFail(array $payload): void { $this->writeRecord('FAIL', $payload); }
}
'''


def cmd_inject_sdk(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    target_dir = (workspace / args.dest).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    lang = args.lang.lower()

    if lang == "python":
        dest_file = target_dir / "ra_logger.py"
        src_text = Path(__file__).resolve().read_text(encoding="utf-8")
        dest_file.write_text(src_text, encoding="utf-8")
    elif lang in ("js", "ts", "node"):
        dest_file = target_dir / "ra_logger.js"
        dest_file.write_text(JS_TS_LOGGER_SDK, encoding="utf-8")
    elif lang in ("php", "laravel"):
        dest_file = target_dir / "RALogger.php"
        dest_file.write_text(PHP_LOGGER_SDK, encoding="utf-8")
    else:
        print(f"[RA LOG ENGINE] Unsupported SDK language: {lang}", file=sys.stderr)
        sys.exit(1)

    rel_sdk = dest_file.relative_to(workspace).as_posix() if dest_file.is_relative_to(workspace) else str(dest_file)
    print("=" * 78)
    print(f"  RA PRODUCTION `.log` SDK INJECTED (`{lang.upper()}`)")
    print("=" * 78)
    print(f"  SDK Path : {rel_sdk}")
    print("  Usage    : Wire every real workflow hop to emit `[PASS]`, `[DECISION]`, `[STUCK]`, and `[FAIL]`")
    print("             records with full `flow`, `role`, `inputs`, `state_before`, `state_after`, and `output`.")
    print("=" * 78)


def compute_code_fingerprint(workspace: Path, hyp: str, state: Dict[str, Any]) -> str:
    """Compute a combined SHA-256 fingerprint of tracked / sandbox code files to detect identical-code retry spam."""
    h = hashlib.sha256()
    candidate_files: List[Path] = []
    sandbox_dir = workspace / "research" / "sandbox" / hyp
    if sandbox_dir.exists():
        candidate_files.extend(
            f for f in sorted(sandbox_dir.rglob("*"))
            if f.is_file() and f.suffix.lower() not in {".log", ".json", ".md"}
        )
    for rel_t in sorted(state.get("context_map_snapshot", {}).get("tracked_files", {}).keys()):
        fp = (workspace / rel_t).resolve()
        if fp.exists() and fp.is_file():
            candidate_files.append(fp)
    if not candidate_files:
        for f in sorted(workspace.glob("*")):
            if f.is_file() and f.suffix.lower() in {".py", ".js", ".ts", ".rs", ".go", ".cpp", ".c"}:
                candidate_files.append(f)
    for cf in candidate_files:
        try:
            h.update(str(cf.name).encode("utf-8"))
            h.update(cf.read_bytes())
        except Exception:
            pass
    return h.hexdigest()


def cmd_run(args: argparse.Namespace) -> None:
    """Run a real-environment execution command under a strict OS-level watchdog timer (preventing 30-min hangs & lazy retry loops)."""
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    rdir.mkdir(parents=True, exist_ok=True)
    state_path = rdir / ".ra_state.json"
    state: Dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    hyp = args.hypothesis.strip()
    code_fp = compute_code_fingerprint(workspace, hyp, state)
    retry_lock: Dict[str, Any] = state.get("retry_lock", {})

    # Anti-Lazy-Retry Gate: Block un-reasoned "let's retry" spam or identical-code re-runs after a failed fix attempt
    if retry_lock.get("locked") and not getattr(args, "initial_repro", False):
        if not retry_lock.get("re_evaluated"):
            print(
                "[RA LOG ENGINE BLOCKED — LAZY RETRY / INFINITE LOOP PREVENTED!]\n"
                "  Your previous execution failed. Spamming 'let's retry' or re-running without a first-principles\n"
                "  re-calculation is BANNED.\n"
                "  Before you can run again, you MUST perform a formal re-evaluation:\n"
                "    python ra_gate.py re-evaluate \\\n"
                "      --workspace \".\" \\\n"
                "      --component \"<component_slug>\" \\\n"
                "      --why-failed \"<Mathematical/structural proof of WHY the previous calculation/model failed>\" \\\n"
                "      --new-calculation \"<Exact new equation, invariant, or structural change (NOT a threshold tweak)>\" \\\n"
                "      --why-different \"<Why this new calculation deterministically resolves the failure>\"",
                file=sys.stderr,
            )
            sys.exit(2)
        if code_fp == retry_lock.get("failed_code_hash"):
            print(
                "[RA LOG ENGINE BLOCKED — IDENTICAL CODE RETRY DETECTED!]\n"
                "  You unlocked `re-evaluate`, but attempted to re-run `ra_log_engine.py run` with the EXACT SAME\n"
                "  code SHA-256 fingerprint as the failed run!\n"
                "  Re-running identical code hoping for a different outcome is banned. Implement your new calculation first!",
                file=sys.stderr,
            )
            sys.exit(2)

    logs_dir = rdir / "sandbox" / hyp / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = Path(args.log_file).resolve() if args.log_file else (logs_dir / "runtime_real.log")

    timeout_sec = args.timeout_sec
    logger = RALogger(log_file, trace_id=f"RUN_{hyp}")

    print("=" * 78)
    print(f"  RA REAL-ENVIRONMENT WATCHDOG RUNNER — `{hyp}` (MAX TIMEOUT: {timeout_sec}s)")
    print("=" * 78)
    print(f"  Command  : {args.cmd}")
    print(f"  Log File : {log_file.relative_to(workspace).as_posix() if log_file.is_relative_to(workspace) else log_file}")
    print("-" * 78)

    t0 = time.perf_counter()
    env = os.environ.copy()
    env["RA_LOG_FILE"] = str(log_file)
    env["PYTHONUTF8"] = "1"

    try:
        proc = subprocess.run(
            args.cmd,
            shell=True,
            cwd=str(workspace),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if proc.returncode != 0:
            logger.log_fail(
                role="Real-Environment Process Execution",
                reason=f"Process exited with code {proc.returncode}: {proc.stderr.strip()[:240]}",
                inputs={"cmd": args.cmd},
                state_before={"process": "STARTING"},
                state_after={"process": f"EXIT_{proc.returncode}", "stdout_tail": proc.stdout[-300:]},
                contract="PROCESS_CLEAN_EXIT",
                elapsed_ms=elapsed_ms,
                flow="ra_log_engine:cmd_run->subprocess",
            )
            # If initial repro was already done (or this is a fix attempt), engage the Anti-Lazy-Retry Lock!
            if state.get("initial_repro_done") and not getattr(args, "initial_repro", False):
                state["retry_lock"] = {
                    "locked": True,
                    "re_evaluated": False,
                    "failed_cmd": args.cmd,
                    "failed_code_hash": code_fp,
                    "failed_at": now_iso(),
                }
            else:
                state["initial_repro_done"] = True
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"  [FAIL] Process exited with code {proc.returncode} ({elapsed_ms:.1f}ms). Logged to `{log_file.name}`.")
            sys.exit(proc.returncode)
        else:
            state["retry_lock"] = {"locked": False, "re_evaluated": False, "failed_code_hash": ""}
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"  [COMPLETED] Real-environment run finished in {elapsed_ms:.1f}ms. Running `.log` audit...")
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        out_tail = (exc.stdout or "")[-300:] if isinstance(exc.stdout, str) else ""
        err_tail = (exc.stderr or "")[-300:] if isinstance(exc.stderr, str) else ""
        logger.log_stuck(
            role="Real-Environment Process Execution Watchdog",
            waiting_on=f"Command `{args.cmd}` hung past {timeout_sec}s watchdog limit",
            current_values={"stdout_tail": out_tail, "stderr_tail": err_tail},
            state_snapshot={"process": "KILLED_BY_WATCHDOG"},
            elapsed_ms=elapsed_ms,
            flow="ra_log_engine:cmd_run->subprocess_timeout",
        )
        state["retry_lock"] = {
            "locked": True,
            "re_evaluated": False,
            "failed_cmd": args.cmd,
            "failed_code_hash": code_fp,
            "failed_at": now_iso(),
        }
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(
            f"  [STUCK / KILLED BY WATCHDOG] Command hung past {timeout_sec}s limit! "
            f"Recorded `[STUCK]` state in `{log_file.name}`.",
            file=sys.stderr,
        )
        sys.exit(124)


def extract_required_contracts(workspace: Path) -> List[str]:
    wmap = workspace / "research" / "WORKFLOW_MAP.md"
    if not wmap.exists():
        return []
    contracts: List[str] = []
    for line in wmap.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*-\s*(?:\*\*)?`(BC-\d+)`(?:\*\*)?:(.*)$", line)
        if m and "<e.g.," not in m.group(2):
            contracts.append(m.group(1))
    return contracts


def parse_log_file(log_path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse a `.log` file and validate that records contain full flow + functional role + runtime values
    (rejecting bare 'pass'/'ok' AI slop).
    """
    records: List[Dict[str, Any]] = []
    slop_violations: List[str] = []

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        if "|| RA_JSON=" in stripped:
            json_part = stripped.split("|| RA_JSON=", 1)[1].strip()
            try:
                rec = json.loads(json_part)
                records.append(rec)
                # Verify non-slop completeness on [PASS] records
                if rec.get("status") == "PASS":
                    role = str(rec.get("role", "")).strip()
                    flow = str(rec.get("flow", "")).strip()
                    if not role or role == "unspecified" or len(role) < 5:
                        slop_violations.append(
                            f"{log_path.name}:{idx}: `[PASS]` record missing meaningful functional `role` description."
                        )
                    if "->" not in flow:
                        slop_violations.append(
                            f"{log_path.name}:{idx}: `[PASS]` record `flow='{flow}'` must state `caller->callee` lineage."
                        )
                    empty_vals = (None, {}, "", {"args": [], "kwargs": {}})
                    if (
                        rec.get("inputs") in empty_vals
                        and rec.get("state_before") in empty_vals
                        and rec.get("state_after") in empty_vals
                    ):
                        slop_violations.append(
                            f"{log_path.name}:{idx}: AI-Slop `[PASS]` Violation — record logs zero runtime `inputs` "
                            f"and zero `state_before`/`state_after` values!"
                        )
            except Exception as exc:
                slop_violations.append(f"{log_path.name}:{idx}: Malformed `RA_JSON` payload: {exc}")
        else:
            # Check if the agent wrote raw unstructured slop like `PASS`, `ok`, `test passed`
            if re.search(r"\b(pass(ed)?|ok|success|working)\b", stripped, re.IGNORECASE):
                slop_violations.append(
                    f"{log_path.name}:{idx}: Unstructured AI-slop log line detected (`{stripped[:80]}`). "
                    f"Every `.log` entry must include structured `TRACE`, `HOP`, `[PASS|STUCK|FAIL]`, `flow=caller->callee`, "
                    f"`role`, `inputs`, `state_before`, `state_after`, `output`, and `|| RA_JSON={{...}}`!"
                )

    return records, slop_violations


def cmd_audit(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    state_path = rdir / ".ra_state.json"
    hyp = args.hypothesis.strip()
    sandbox_dir = rdir / "sandbox" / hyp
    logs_dir = sandbox_dir / "logs"

    log_files: List[Path] = []
    if args.log_file:
        lf = Path(args.log_file).resolve()
        if lf.exists():
            log_files.append(lf)
    else:
        if logs_dir.exists():
            log_files.extend(sorted(logs_dir.rglob("*.log")))
        if sandbox_dir.exists():
            for f in sorted(sandbox_dir.glob("*.log")):
                if f not in log_files:
                    log_files.append(f)

    violations: List[str] = []
    all_records: List[Dict[str, Any]] = []

    if not log_files:
        violations.append(
            f"No `.log` files found in `research/sandbox/{hyp}/logs/` (or `research/sandbox/{hyp}/*.log`)! "
            f"RA forbids synthetic unit-test marathons — wire `RALogger` into the real execution path and produce a `.log` trace."
        )

    for lf in log_files:
        recs, slop = parse_log_file(lf)
        all_records.extend(recs)
        violations.extend(slop)

    pass_records = [r for r in all_records if r.get("status") == "PASS"]
    stuck_records = [r for r in all_records if r.get("status") == "STUCK"]
    fail_records = [r for r in all_records if r.get("status") == "FAIL"]
    decision_records = [r for r in all_records if r.get("status") == "DECISION"]

    if log_files and not pass_records and not stuck_records and not fail_records:
        violations.append(
            "Zero structured `[PASS]`, `[STUCK]`, or `[FAIL]` records found in `.log` files! "
            "Instrument the code with `RALogger` (`ra_log_engine.py`) and run in the real environment."
        )

    if stuck_records:
        for sr in stuck_records:
            violations.append(
                f"[STUCK AT HOP {sr.get('hop')}] flow=`{sr.get('flow')}` | role=\"{sr.get('role')}\" | "
                f"reason=\"{sr.get('reason')}\" | values={json.dumps(sr.get('inputs'), ensure_ascii=False)} | "
                f"state={json.dumps(sr.get('state_after'), ensure_ascii=False)}"
            )

    if fail_records:
        for fr in fail_records:
            violations.append(
                f"[FAIL AT HOP {fr.get('hop')}] flow=`{fr.get('flow')}` | role=\"{fr.get('role')}\" | "
                f"reason=\"{fr.get('reason')}\" | state_before={json.dumps(fr.get('state_before'), ensure_ascii=False)} -> "
                f"state_after={json.dumps(fr.get('state_after'), ensure_ascii=False)}"
            )

    # Verify all Existing Behavioral Contracts (`BC-xxx`) from WORKFLOW_MAP.md were verified in `.log`
    required_contracts = extract_required_contracts(workspace)
    logged_contracts = {r.get("contract") for r in pass_records if r.get("contract")}
    for bc in required_contracts:
        if bc not in logged_contracts:
            violations.append(
                f"Existing Behavioral Contract `{bc}` (from `WORKFLOW_MAP.md`) was NEVER verified in the `.log` trace! "
                f"Call `logger.assert_contract('{bc}', ...)` or `log_pass(..., contract='{bc}')` in the real run."
            )

    print("=" * 78)
    print(f"  RA REAL-ENVIRONMENT `.log` FLOW & VALUE AUDIT — `{hyp}`")
    print("=" * 78)
    print(f"  Audited `.log` Files : {len(log_files)}")
    print(f"  Total Flow Hops      : {len(all_records)}")
    print(
        f"  Status Breakdown     : [PASS]={len(pass_records)} | [DECISION]={len(decision_records)} | "
        f"[STUCK]={len(stuck_records)} | [FAIL]={len(fail_records)}"
    )
    print(f"  Contracts Verified   : {', '.join(sorted(logged_contracts - {'NONE'})) or 'NONE'}")
    print("-" * 78)

    if all_records:
        print("  EXECUTION FLOW & VALUE TRACE SUMMARY:")
        for r in all_records[:15]:
            st = r.get("status")
            hop = r.get("hop", 0)
            flow = r.get("flow", "")
            role = r.get("role", "")
            delta = json.dumps(r.get("state_delta", {}), ensure_ascii=False)
            out = json.dumps(r.get("output", None), ensure_ascii=False)
            ms = r.get("elapsed_ms", 0.0)
            print(f"    Hop {hop:02d} [{st}] {flow} ({ms:.1f}ms) — {role}")
            print(f"           delta={delta} | output={out}")
        print("-" * 78)

    if violations:
        rdir.mkdir(parents=True, exist_ok=True)
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        state["log_audit_passed"] = False
        code_fp = compute_code_fingerprint(workspace, hyp, state)
        if state.get("initial_repro_done"):
            state["retry_lock"] = {
                "locked": True,
                "re_evaluated": False,
                "failed_cmd": "audit",
                "failed_code_hash": code_fp,
                "failed_at": now_iso(),
            }
        else:
            state["initial_repro_done"] = True
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("  [FAIL] REAL-ENVIRONMENT `.log` AUDIT REJECTED THE RUN:")
        for v in violations:
            print(f"    - {v}")
        print("-" * 78)
        print(
            "  [ANTI-LAZY-RETRY LOCK] Before re-running after a failed fix attempt, you MUST run:\n"
            "    python ra_gate.py re-evaluate --component <slug> --why-failed \"...\" --new-calculation \"...\" --why-different \"...\""
        )
        print("=" * 78)
        sys.exit(1)

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["log_audit_passed"] = True
        state["retry_lock"] = {"locked": False, "re_evaluated": False, "failed_code_hash": ""}
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("  [PASS] Real-Environment `.log` Flow, Functional Roles, State Deltas & Contracts Verified!")
    print("=" * 78)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA Production-Grade Real-Environment `.log` Telemetry & Flow Auditor")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_sdk = sub.add_parser("inject-sdk", help="Generate production RALogger SDK into a project directory")
    p_sdk.add_argument("--workspace", default=".", help="Workspace root")
    p_sdk.add_argument("--lang", required=True, choices=["python", "js", "ts", "node", "php", "laravel"])
    p_sdk.add_argument("--dest", default=".", help="Destination directory relative to workspace")
    p_sdk.set_defaults(func=cmd_inject_sdk)

    p_run = sub.add_parser("run", help="Run real-environment command under a strict watchdog timer and log `[STUCK]` on hang")
    p_run.add_argument("--workspace", default=".", help="Workspace root")
    p_run.add_argument("--hypothesis", default="STANDALONE", help="Active hypothesis folder (e.g., H001_slug) or STANDALONE")
    p_run.add_argument("--cmd", required=True, help="Command to execute in the real environment")
    p_run.add_argument("--timeout-sec", type=int, default=60, help="Hard watchdog timeout in seconds (prevents 30m hangs)")
    p_run.add_argument("--log-file", default=None, help="Optional custom `.log` file path")
    p_run.add_argument(
        "--initial-repro",
        action="store_true",
        help="Mark this run as the Phase 1 initial bug reproduction (does not trigger the post-fix retry lock)",
    )
    p_run.set_defaults(func=cmd_run)

    p_audit = sub.add_parser("audit", help="Audit real-environment `.log` files for flow, values, `[PASS]`/`[STUCK]`/`[FAIL]`, and contracts")
    p_audit.add_argument("--workspace", default=".", help="Workspace root")
    p_audit.add_argument("--hypothesis", default="STANDALONE", help="Active hypothesis folder (e.g., H001_slug) or STANDALONE")
    p_audit.add_argument("--log-file", default=None, help="Optional explicit `.log` file path to audit")
    p_audit.set_defaults(func=cmd_audit)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
