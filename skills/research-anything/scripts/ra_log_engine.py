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
- Multi-Language SDK Generator (`inject-sdk --lang python|js|esm|ts|php`) for any project stack.
- Watchdog Process Runner that kills the whole process tree on timeout and writes one fresh
  `.log` per run (`research/sandbox/<hyp>/logs/run_<YYYYmmdd-HHMMSS-mmm>.log`, path in `$RA_LOG_FILE`):
    run --timeout-sec 60 -- python app.py --flag     (argv form, no shell, same on every OS)
    run --timeout-sec 60 --cmd "python app.py"       (string run by the platform shell: cmd.exe on Windows)
- Deep `.log` Flow & Value Auditor (`audit`) that rejects bare "ok/pass" AI slop and verifies
  every workflow hop and behavioral contract (`BC-xxx`) of the latest `run` log.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="milliseconds")


_SDK_CODE_FILE = now_iso.__code__.co_filename


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

    def _caller_chain(self) -> str:
        """`caller->callee` for the nearest two frames outside this SDK file (also skips `trace_step` wrappers)."""
        sites: List[str] = []
        frame = sys._getframe(1)
        while frame is not None and len(sites) < 2:
            fname = frame.f_code.co_filename
            if fname != _SDK_CODE_FILE and not fname.startswith("<frozen"):
                sites.append(f"{Path(fname).name}:{frame.f_code.co_name}:L{frame.f_lineno}")
            frame = frame.f_back
        if not sites:
            return "root->unknown"
        return f"{sites[1] if len(sites) > 1 else 'root'}->{sites[0]}"

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

        # role/reason are JSON-quoted so a multi-line traceback cannot split the record across lines
        line = (
            f"{ts} | TRACE={self.trace_id} | HOP={hop:04d} | [{status}] "
            f"| flow={flow} | role={json.dumps(role, ensure_ascii=False)} | inputs={inputs} "
            f"| state_before={s_before} | state_after={s_after} | delta={delta} "
            f"| output={output} | contract={contract} | elapsed_ms={elapsed_ms:.3f}"
            + (f" | reason={json.dumps(reason, ensure_ascii=False)}" if reason else "")
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
                "flow": flow or self._caller_chain(),
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
                "flow": flow or self._caller_chain(),
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
                "flow": flow or self._caller_chain(),
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
                "flow": flow or self._caller_chain(),
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
        flow = self._caller_chain()
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
                cframe = sys._getframe(1)
                caller_str = f"{Path(cframe.f_code.co_filename).name}:{cframe.f_code.co_name}:L{cframe.f_lineno}"
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


# Shared JS body for the CommonJS (.js), ES module (.mjs) and TypeScript (.ts) SDK files.
_JS_LOGGER_BODY = r'''
const SDK_FILE_RE = /^ra_logger\.(?:c|m)?[jt]s$/;

function computeDelta(before, after) {
  const b = before || {};
  const a = after || {};
  const delta = {};
  for (const k of [...new Set([...Object.keys(b), ...Object.keys(a)])].sort()) {
    const from = k in b ? b[k] : '<UNSET>';
    const to = k in a ? a[k] : '<DELETED>';
    if (JSON.stringify(from) !== JSON.stringify(to)) delta[k] = { from, to };
  }
  return delta;
}

// Nearest two stack frames outside this file, as "caller->callee".
function deriveFlow() {
  const sites = [];
  for (const line of String(new Error().stack).split('\n').slice(1)) {
    const m = line.match(/^\s*at (?:(.*?) \()?(.*?):(\d+):\d+\)?$/);
    if (!m || m[2].startsWith('node:')) continue;
    const file = m[2].split(/[\\/]/).pop();
    if (SDK_FILE_RE.test(file)) continue;
    const fn = (m[1] || '<module>').replace(/^(?:async |new )/, '');
    sites.push(`${file}:${fn}:L${m[3]}`);
    if (sites.length === 2) break;
  }
  if (!sites.length) return 'unknown->unknown';
  return `${sites[1] || 'root'}->${sites[0]}`;
}

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
    const before = payload.state_before || {};
    const after = payload.state_after || {};
    const record = {
      timestamp: ts,
      trace_id: this.traceId,
      hop: this.hopCounter,
      status,
      flow: payload.flow || deriveFlow(),
      role: payload.role || 'unspecified',
      inputs: payload.inputs || {},
      state_before: before,
      state_after: after,
      state_delta: payload.state_delta || computeDelta(before, after),
      output: payload.output ?? null,
      contract: payload.contract || 'NONE',
      elapsed_ms: Number(Number(payload.elapsed_ms || 0).toFixed(3)),
      reason: payload.reason || ''
    };
    const line = `${ts} | TRACE=${this.traceId} | HOP=${String(this.hopCounter).padStart(4, '0')} | [${status}] | flow=${record.flow} | role=${JSON.stringify(record.role)} | inputs=${JSON.stringify(record.inputs)} | state_before=${JSON.stringify(record.state_before)} | state_after=${JSON.stringify(record.state_after)} | delta=${JSON.stringify(record.state_delta)} | output=${JSON.stringify(record.output)} | contract=${record.contract} | elapsed_ms=${record.elapsed_ms}${record.reason ? ` | reason=${JSON.stringify(record.reason)}` : ''} || RA_JSON=${JSON.stringify(record)}\n`;
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
    const site = flow || deriveFlow();
    if (!condition) {
      this.logFail({ flow: site, role, reason: `Behavioral Contract ${contractId} violated`, inputs: actual_values, state_before: state_snapshot, state_after: state_snapshot, contract: contractId });
      throw new Error(`[RA CONTRACT BREACH] ${contractId}`);
    }
    this.logPass({ flow: site, role: `Contract Verification (${contractId}): ${role}`, inputs: actual_values, state_before: state_snapshot, state_after: state_snapshot, output: 'CONTRACT_HOLDING', contract: contractId, elapsed_ms: 0.1 });
  }
}
'''

_JS_DOC = '''/**
 * {name} — Production-Grade Real-Environment Flow & Value Logger for RA ({kind}).
 * Logs [PASS], [DECISION], [STUCK], and [FAIL] with full caller->callee flow,
 * functional purpose, inputs, state_before -> state_after, delta, and elapsed_ms.
 * `flow` and `state_delta` are derived automatically when omitted.
 */
'''

JS_TS_LOGGER_SDK = (
    _JS_DOC.format(name="ra_logger.js", kind="CommonJS")
    + "const fs = require('fs');\nconst path = require('path');\n"
    + _JS_LOGGER_BODY
    + "\nmodule.exports = { RALogger, computeDelta };\n"
)

JS_ESM_LOGGER_SDK = (
    _JS_DOC.format(name="ra_logger.mjs", kind="ES module")
    + "import * as fs from 'node:fs';\nimport * as path from 'node:path';\n"
    + _JS_LOGGER_BODY
    + "\nexport { RALogger, computeDelta };\n"
)

TS_LOGGER_SDK = (
    "// @ts-nocheck -- vendored untyped SDK; keeps strict project settings from failing on it\n"
    + _JS_DOC.format(name="ra_logger.ts", kind="TypeScript / ES module")
    + "import * as fs from 'node:fs';\nimport * as path from 'node:path';\n"
    + _JS_LOGGER_BODY
    + "\nexport { RALogger, computeDelta };\n"
)

PHP_LOGGER_SDK = r'''<?php
/**
 * RALogger.php — Production-Grade Real-Environment Flow & Value Logger for RA (Laravel / PHP).
 * Every method takes one associative array, e.g.
 *   $log->logPass(['role' => '...', 'inputs' => [...], 'state_before' => [...], 'state_after' => [...], 'output' => $x]);
 *   $log->logDecision(['role' => '...', 'condition' => 'n > 1', 'evaluated_values' => [...], 'branch_taken' => 'big', 'state_snapshot' => [...]]);
 * `flow` and `state_delta` are derived automatically when omitted.
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

    public static function computeDelta(array $before, array $after): array {
        $delta = [];
        $keys = array_unique(array_merge(array_keys($before), array_keys($after)));
        sort($keys);
        foreach ($keys as $k) {
            $from = array_key_exists($k, $before) ? $before[$k] : '<UNSET>';
            $to = array_key_exists($k, $after) ? $after[$k] : '<DELETED>';
            if ($from !== $to) {
                $delta[$k] = ['from' => $from, 'to' => $to];
            }
        }
        return $delta;
    }

    // Nearest two call sites outside this file, as "caller->callee".
    private function deriveFlow(): string {
        $bt = debug_backtrace(DEBUG_BACKTRACE_IGNORE_ARGS);
        $sites = [];
        foreach ($bt as $i => $frame) {
            if (!isset($frame['file']) || $frame['file'] === __FILE__) {
                continue;
            }
            $fn = $bt[$i + 1]['function'] ?? '<main>';
            $sites[] = basename($frame['file']) . ':' . $fn . ':L' . ($frame['line'] ?? 0);
            if (count($sites) === 2) {
                break;
            }
        }
        if (!$sites) {
            return 'unknown->unknown';
        }
        return ($sites[1] ?? 'root') . '->' . $sites[0];
    }

    public function writeRecord(string $status, array $payload): void {
        $this->hopCounter++;
        $ts = (new DateTimeImmutable())->format('Y-m-d\TH:i:s.vP');
        $before = $payload['state_before'] ?? [];
        $after = $payload['state_after'] ?? [];
        $delta = $payload['state_delta'] ?? ((is_array($before) && is_array($after)) ? self::computeDelta($before, $after) : []);
        $record = [
            'timestamp' => $ts,
            'trace_id' => $this->traceId,
            'hop' => $this->hopCounter,
            'status' => $status,
            'flow' => $payload['flow'] ?? $this->deriveFlow(),
            'role' => $payload['role'] ?? 'unspecified',
            'inputs' => $payload['inputs'] ?? [],
            'state_before' => $before,
            'state_after' => $after,
            'state_delta' => $delta,
            'output' => $payload['output'] ?? null,
            'contract' => $payload['contract'] ?? 'NONE',
            'elapsed_ms' => round((float)($payload['elapsed_ms'] ?? 0.0), 3),
            'reason' => $payload['reason'] ?? '',
        ];
        $flags = JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE;
        $enc = fn($v) => json_encode($v, $flags);
        $hopStr = str_pad((string)$this->hopCounter, 4, '0', STR_PAD_LEFT);
        $line = "{$ts} | TRACE={$this->traceId} | HOP={$hopStr} | [{$status}] | flow={$record['flow']}"
            . " | role=" . $enc($record['role'])
            . " | inputs=" . $enc($record['inputs'])
            . " | state_before=" . $enc($record['state_before'])
            . " | state_after=" . $enc($record['state_after'])
            . " | delta=" . $enc($record['state_delta'])
            . " | output=" . $enc($record['output'])
            . " | contract={$record['contract']} | elapsed_ms={$record['elapsed_ms']}"
            . ($record['reason'] !== '' ? " | reason=" . $enc($record['reason']) : '')
            . " || RA_JSON=" . $enc($record) . "\n";
        file_put_contents($this->logPath, $line, FILE_APPEND | LOCK_EX);
    }

    public function logPass(array $payload): void {
        $this->writeRecord('PASS', $payload);
    }

    public function logDecision(array $payload): void {
        $snapshot = $payload['state_snapshot'] ?? [];
        $this->writeRecord('DECISION', [
            'flow' => $payload['flow'] ?? null,
            'role' => $payload['role'] ?? null,
            'inputs' => ['condition' => $payload['condition'] ?? null, 'evaluated_values' => $payload['evaluated_values'] ?? []],
            'state_before' => $snapshot,
            'state_after' => $snapshot,
            'output' => ['branch_taken' => $payload['branch_taken'] ?? null],
            'contract' => 'BRANCH_TRACE',
        ]);
    }

    public function logStuck(array $payload): void {
        $snapshot = $payload['state_snapshot'] ?? [];
        $waitingOn = $payload['waiting_on'] ?? 'unknown';
        $elapsed = (float)($payload['elapsed_ms'] ?? 0.0);
        $this->writeRecord('STUCK', [
            'flow' => $payload['flow'] ?? null,
            'role' => $payload['role'] ?? null,
            'inputs' => ['waiting_on' => $waitingOn, 'current_values' => $payload['current_values'] ?? []],
            'state_before' => $snapshot,
            'state_after' => $snapshot,
            'output' => 'STUCK_TIMEOUT',
            'contract' => 'WATCHDOG_BREACH',
            'elapsed_ms' => $elapsed,
            'reason' => "Stuck waiting on {$waitingOn} for {$elapsed}ms",
        ]);
    }

    public function logFail(array $payload): void {
        $payload['output'] = 'FAILED';
        $this->writeRecord('FAIL', $payload);
    }

    public function assertContract(string $contractId, bool $condition, array $payload): void {
        $snapshot = $payload['state_snapshot'] ?? [];
        $values = $payload['actual_values'] ?? [];
        $flow = $payload['flow'] ?? $this->deriveFlow();
        $role = $payload['role'] ?? 'unspecified';
        if (!$condition) {
            $this->logFail(['flow' => $flow, 'role' => $role, 'reason' => "Behavioral Contract {$contractId} violated",
                'inputs' => $values, 'state_before' => $snapshot, 'state_after' => $snapshot, 'contract' => $contractId]);
            throw new RuntimeException("[RA CONTRACT BREACH] {$contractId}");
        }
        $this->logPass(['flow' => $flow, 'role' => "Contract Verification ({$contractId}): {$role}", 'inputs' => $values,
            'state_before' => $snapshot, 'state_after' => $snapshot, 'output' => 'CONTRACT_HOLDING',
            'contract' => $contractId, 'elapsed_ms' => 0.1]);
    }
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
    elif lang in ("js", "node"):
        dest_file = target_dir / "ra_logger.js"
        dest_file.write_text(JS_TS_LOGGER_SDK, encoding="utf-8")
    elif lang in ("esm", "mjs"):
        dest_file = target_dir / "ra_logger.mjs"
        dest_file.write_text(JS_ESM_LOGGER_SDK, encoding="utf-8")
    elif lang == "ts":
        dest_file = target_dir / "ra_logger.ts"
        dest_file.write_text(TS_LOGGER_SDK, encoding="utf-8")
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
    print("             Under `ra_log_engine.py run`, log to the path in the `RA_LOG_FILE` environment variable.")
    print("=" * 78)


_FP_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".nox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist", "target", "obj", ".next",
    ".nuxt", ".gradle", ".idea", ".vscode", "coverage", ".cache", "vendor",
}
_FP_DOC_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".log"}
_FP_SOURCE_SUFFIXES = {
    ".py", ".pyx", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte",
    ".rs", ".go", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".cs", ".java", ".kt", ".kts",
    ".scala", ".swift", ".m", ".mm", ".rb", ".php", ".lua", ".dart", ".zig", ".ex", ".exs", ".erl",
    ".hs", ".ml", ".r", ".jl", ".sh", ".bash", ".ps1", ".psm1", ".bat", ".cmd", ".sql", ".html",
    ".htm", ".css", ".scss", ".sass", ".less", ".glsl", ".hlsl", ".wgsl", ".shader", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".gradle", ".cmake", ".mk",
}
_FP_SOURCE_NAMES = {"Makefile", "Dockerfile", "CMakeLists.txt"}
_FP_MAX_HASHED_BYTES = 5 * 1024 * 1024
_FP_MAX_WALKED_FILES = 20000


def _fp_rel_ok(rel: str) -> bool:
    parts = rel.split("/")
    return parts[0] != "research" and not any(p in _FP_SKIP_DIRS for p in parts[:-1])


def _git_source_files(workspace: Path) -> Optional[List[str]]:
    """Tracked + untracked-but-not-ignored files under the workspace, or None outside a git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(workspace), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    rels = {r for r in proc.stdout.decode("utf-8", errors="replace").split("\0") if r}
    return sorted(
        r for r in rels
        if _fp_rel_ok(r) and Path(r).suffix.lower() not in _FP_DOC_SUFFIXES
    )


def _walk_source_files(workspace: Path) -> List[str]:
    found: List[str] = []
    for root, dirs, files in os.walk(workspace):
        root_p = Path(root)
        dirs[:] = sorted(
            d for d in dirs
            if d not in _FP_SKIP_DIRS
            and not (root_p == workspace and d == "research")
            and not (root_p / d / "pyvenv.cfg").exists()
        )
        for name in sorted(files):
            suffix = Path(name).suffix.lower()
            if name in _FP_SOURCE_NAMES or (suffix in _FP_SOURCE_SUFFIXES and suffix not in _FP_DOC_SUFFIXES):
                found.append((root_p / name).relative_to(workspace).as_posix())
                if len(found) >= _FP_MAX_WALKED_FILES:
                    return found
    return found


def compute_code_fingerprint(workspace: Path, hyp: str, state: Dict[str, Any]) -> str:
    """
    SHA-256 over the workspace's source files (git ls-files + untracked when in a git repo, else a
    recursive source walk), the hypothesis sandbox code, and ra_gate tracked files. Returns "" when
    no file was found, so callers never lock on an empty set.
    """
    rels = _git_source_files(workspace)
    if rels is None:
        rels = _walk_source_files(workspace)
    selected = set(rels)

    sandbox_dir = workspace / "research" / "sandbox" / hyp
    if sandbox_dir.exists():
        for f in sandbox_dir.rglob("*"):
            rel_in = f.relative_to(sandbox_dir).parts
            if (
                f.is_file()
                and f.suffix.lower() not in {".log", ".json", ".md", ".txt"}
                and not ({"logs", "visual_captures"} & set(rel_in[:-1]))
            ):
                selected.add(f.relative_to(workspace).as_posix())
    for rel_t in state.get("context_map_snapshot", {}).get("tracked_files", {}).keys():
        rel_t = Path(rel_t).as_posix()
        if _fp_rel_ok(rel_t):
            selected.add(rel_t)

    h = hashlib.sha256()
    hashed = 0
    for rel in sorted(selected):
        fp = workspace / rel
        try:
            st = fp.stat()
            if not fp.is_file():
                continue
            h.update(rel.encode("utf-8") + b"\0")
            if st.st_size > _FP_MAX_HASHED_BYTES:
                h.update(f"{st.st_size}:{st.st_mtime_ns}".encode("ascii"))
            else:
                h.update(fp.read_bytes())
            h.update(b"\0")
            hashed += 1
        except OSError:
            continue
    return h.hexdigest() if hashed else ""


def _load_state(state_path: Path) -> Dict[str, Any]:
    return json.loads(state_path.read_text(encoding="utf-8-sig")) if state_path.exists() else {}


def _save_state(state_path: Path, state: Dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _lock_for(state: Dict[str, Any], hyp: str) -> Optional[Dict[str, Any]]:
    """
    The engaged retry lock that applies to `hyp`. A parked lock is swapped into `retry_lock` so that
    `ra_gate.py re-evaluate` (which only edits `retry_lock`) acts on it. Locks without a
    `hypothesis` key predate scoping and apply to every hypothesis.
    """
    current = state.get("retry_lock") or {}
    owner = current.get("hypothesis")
    if current.get("locked") and owner in (None, hyp):
        return current
    parked = state.get("retry_lock_parked") or {}
    lock = parked.pop(hyp, None)
    if not (lock and lock.get("locked")):
        return None
    if current.get("locked") and owner:
        parked[owner] = current
    state["retry_lock_parked"] = parked
    state["retry_lock"] = lock
    return lock


def _engage_lock(state: Dict[str, Any], hyp: str, *, failed_cmd: str, code_fp: str, failed_log: str) -> None:
    current = state.get("retry_lock") or {}
    owner = current.get("hypothesis")
    if current.get("locked") and owner == hyp and failed_log and current.get("failed_log") == failed_log:
        return  # same failed run already locked: keep any re-evaluation done since
    if current.get("locked") and owner and owner != hyp:
        state.setdefault("retry_lock_parked", {})[owner] = current
    (state.get("retry_lock_parked") or {}).pop(hyp, None)
    state["retry_lock"] = {
        "locked": True,
        "re_evaluated": False,
        "hypothesis": hyp,
        "failed_cmd": failed_cmd,
        "failed_code_hash": code_fp,
        "failed_log": failed_log,
        "failed_at": now_iso(),
    }


def _clear_lock(state: Dict[str, Any], hyp: str) -> None:
    current = state.get("retry_lock") or {}
    if current.get("hypothesis") in (None, hyp):
        state["retry_lock"] = {"locked": False, "re_evaluated": False, "failed_code_hash": "", "hypothesis": hyp}
    (state.get("retry_lock_parked") or {}).pop(hyp, None)


def _repro_done(state: Dict[str, Any], hyp: str) -> bool:
    repro: Dict[str, Any] = state.setdefault("initial_repro", {})
    if state.pop("initial_repro_done", False) and not repro:
        repro[hyp] = "legacy"  # old global flag: attribute it to the hypothesis now in use
    return hyp in repro


def _record_failure(state: Dict[str, Any], hyp: str, *, failed_cmd: str, code_fp: str, failed_log: str) -> bool:
    """First failure of a hypothesis is its initial repro; every later failure engages the retry lock."""
    if _repro_done(state, hyp):
        _engage_lock(state, hyp, failed_cmd=failed_cmd, code_fp=code_fp, failed_log=failed_log)
        return True
    state["initial_repro"][hyp] = now_iso()
    return False


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _rel_to(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix() if path.is_relative_to(workspace) else str(path)


def _tail(text: str, max_lines: int = 15, max_chars: int = 2000) -> str:
    lines = text.rstrip().splitlines()[-max_lines:]
    return "\n".join(lines)[-max_chars:]


def _count_records(path: Path) -> int:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            return sum(1 for line in f if "|| RA_JSON=" in line)
    except OSError:
        return 0


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _run_watchdog(
    command: Any, *, shell: bool, cwd: Path, env: Dict[str, str], timeout_sec: float
) -> Tuple[Optional[int], str, str, bool]:
    """
    Run under a hard timeout and kill the whole process tree on expiry. Output goes to temp files,
    not pipes, so a surviving grandchild holding the handles cannot block the runner.
    """
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        kw: Dict[str, Any] = {"cwd": str(cwd), "env": env, "shell": shell, "stdout": out_f, "stderr": err_f}
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        proc = subprocess.Popen(command, **kw)
        timed_out = False
        try:
            rc: Optional[int] = proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rc = None
        except BaseException:
            _kill_tree(proc)
            raise
        streams = []
        for fh in (out_f, err_f):
            fh.seek(0)
            streams.append(fh.read().decode("utf-8", errors="replace").replace("\r\n", "\n"))
    return rc, streams[0], streams[1], timed_out


_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _prepare_argv(argv: List[str], workspace: Path, env: Dict[str, str]) -> List[str]:
    """Apply leading NAME=VALUE tokens to env (like `env`) and resolve the program for CreateProcess."""
    argv = list(argv)
    while argv and _ENV_ASSIGN_RE.match(argv[0]):
        name, _, value = argv.pop(0).partition("=")
        env[name] = value
    if not argv:
        raise ValueError("no program given after `--` (only NAME=VALUE assignments)")
    if os.name == "nt":
        prog = argv[0]
        if "/" in prog or "\\" in prog:
            candidate = Path(prog) if Path(prog).is_absolute() else workspace / prog
            if candidate.exists():
                argv[0] = str(candidate)
        else:
            # CreateProcess ignores PATHEXT, so `npm` / `npx` (.cmd shims) need resolving here
            resolved = shutil.which(prog, path=env.get("PATH"))
            if resolved:
                argv[0] = resolved
    return argv


def _display_argv(argv: List[str]) -> str:
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _ra_common() -> Any:
    """ra_common.py beside the skill's copy of this file; None in an SDK copy inside a project."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import ra_common
    except ImportError:
        return None
    return ra_common


def _score_from_log(log_file: Path) -> Optional[float]:
    """Fallback score: the last log record whose role is `RA_SCORE` and whose output is a number."""
    score: Optional[float] = None
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if "|| RA_JSON=" not in line:
            continue
        try:
            rec = json.loads(line.split("|| RA_JSON=", 1)[1])
        except ValueError:
            continue
        out = rec.get("output")
        if rec.get("role") == "RA_SCORE" and isinstance(out, (int, float)) and not isinstance(out, bool):
            score = float(out)
    return score


def _print_plateau_lock(common: Any, workspace: Path, state: Dict[str, Any], hyp: str, header: str, stream: Any) -> None:
    lock = common.sb_get(state, hyp, create=False).get("lock") or {}
    print("=" * 78, file=stream)
    print(f"  {header}", file=stream)
    print(f"  Reason : {lock.get('reason')}", file=stream)
    print("-" * 78, file=stream)
    print(f"  SCOREBOARD - `{hyp}`", file=stream)
    for line in common.sb_lines(workspace, state, hyp):
        print(f"    {line}", file=stream)
    print("-" * 78, file=stream)
    print("  WHAT TO DO:", file=stream)
    for line in common.sb_lock_instructions(state, hyp):
        print(f"    {line}", file=stream)
    print("=" * 78, file=stream)


def _scoreboard_gate(args: argparse.Namespace, workspace: Path, state: Dict[str, Any], hyp: str) -> Tuple[Any, Optional[str]]:
    """(ra_common or None, approach key or None); exits 2 when the plateau lock or approach rules refuse the run."""
    if hyp == "STANDALONE":
        return None, None
    board = (state.get("scoreboard") or {}).get(hyp) or {}
    numeric = any(
        sr.get("hypothesis") == hyp and sr.get("min_gain") is not None for sr in (state.get("stop_rules") or {}).values()
    )
    common = _ra_common()
    if common is None:
        if board.get("lock") or numeric:
            print(
                "[RA LOG ENGINE BLOCKED] This copy has no ra_common.py beside it, so it cannot keep the scoreboard.\n"
                "  Run the skill's own scripts/ra_log_engine.py for this hypothesis.",
                file=sys.stderr,
            )
            sys.exit(2)
        return None, None
    sb = common.sb_get(state, hyp, create=False)
    if sb.get("lock"):
        _print_plateau_lock(
            common, workspace, state, hyp, f"[RA LOG ENGINE BLOCKED - PLATEAU LOCK] `{hyp}`: nothing was run.", sys.stderr
        )
        sys.exit(2)
    found = common.metric_rule(state, hyp)
    required = bool(found and found[1].get("min_gain") is not None)
    raw = (args.approach or "").strip()
    if not raw:
        if required:
            print(
                f"[RA LOG ENGINE BLOCKED] `--approach <family>` is required: stop rule `{found[0]}` has a min-gain, so\n"
                "  every round must name its Option Sweep family (REPORT.md Section 3).",
                file=sys.stderr,
            )
            sys.exit(2)
        return common, common.DEFAULT_APPROACH
    if not common.FAMILY_RE.match(raw):
        print(f"[RA LOG ENGINE] `--approach {raw}` must be [A-Za-z0-9_-] (e.g. template-reader).", file=sys.stderr)
        sys.exit(2)
    key = common.approach_key(raw)
    if (sb["approaches"].get(key) or {}).get("status") == "SWITCHED":
        print(
            f"[RA LOG ENGINE BLOCKED] `{key}` was SWITCHED away from by a cold review; its sandbox is in the graveyard.\n"
            "  Race a different family from the Option Sweep.",
            file=sys.stderr,
        )
        sys.exit(2)
    if required and not common.family_in_report(workspace, hyp, key):
        print(
            f"[RA LOG ENGINE BLOCKED] add `{raw}` to the Option Sweep in REPORT.md Section 3 first "
            f"(research/hypotheses/{hyp}/REPORT.md).",
            file=sys.stderr,
        )
        sys.exit(2)
    return common, key


def cmd_run(args: argparse.Namespace) -> None:
    """Run a real-environment execution command under a strict OS-level watchdog timer (preventing 30-min hangs & lazy retry loops)."""
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    rdir.mkdir(parents=True, exist_ok=True)
    state_path = rdir / ".ra_state.json"
    state = _load_state(state_path)
    hyp = args.hypothesis.strip()

    argv_form: List[str] = list(getattr(args, "argv", None) or [])
    if bool(args.cmd) == bool(argv_form):
        print(
            "[RA LOG ENGINE] Give exactly one command: `--cmd \"<shell string>\"` OR `-- <program> [args...]`.",
            file=sys.stderr,
        )
        sys.exit(2)

    common, approach = _scoreboard_gate(args, workspace, state, hyp)
    code_fp = compute_code_fingerprint(workspace, hyp, state)
    lock = _lock_for(state, hyp)

    # Anti-Lazy-Retry Gate: Block un-reasoned "let's retry" spam or identical-code re-runs after a failed fix attempt
    if lock is not None:
        if not lock.get("re_evaluated"):
            _save_state(state_path, state)
            print(
                f"[RA LOG ENGINE BLOCKED — LAZY RETRY / INFINITE LOOP PREVENTED!] (hypothesis `{hyp}`)\n"
                "  Your previous execution failed. Spamming 'let's retry' or re-running without a first-principles\n"
                "  re-calculation is BANNED.\n"
                "  Before you can run again, you MUST perform a formal re-evaluation:\n"
                "    python ra_gate.py re-evaluate \\\n"
                "      --workspace \".\" \\\n"
                "      --component \"<component_slug>\" \\\n"
                "      --why-failed \"<Mathematical/structural proof of WHY the previous calculation/model failed>\" \\\n"
                "      --new-calculation \"<New equation/structural change, OR the next Option Sweep family if this one PLATEAUED>\" \\\n"
                "      --why-different \"<Why this new calculation deterministically resolves the failure>\"",
                file=sys.stderr,
            )
            sys.exit(2)
        if code_fp and code_fp == lock.get("failed_code_hash"):
            _save_state(state_path, state)
            print(
                "[RA LOG ENGINE BLOCKED — IDENTICAL CODE RETRY DETECTED!]\n"
                "  You unlocked `re-evaluate`, but attempted to re-run `ra_log_engine.py run` with the EXACT SAME\n"
                "  code SHA-256 fingerprint as the failed run!\n"
                "  Re-running identical code hoping for a different outcome is banned. Implement your new calculation first!",
                file=sys.stderr,
            )
            sys.exit(2)

    if args.initial_repro and _repro_done(state, hyp):
        print(
            f"  NOTE: `--initial-repro` was already used for `{hyp}` "
            f"({state['initial_repro'][hyp]}); this is a normal run under the retry lock."
        )

    logs_dir = rdir / "sandbox" / hyp / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    if args.log_file:
        log_file = Path(args.log_file).resolve()
        if log_file.suffix.lower() != ".log":
            print(f"[RA LOG ENGINE] --log-file must end in `.log` (it is overwritten per run): {log_file}", file=sys.stderr)
            sys.exit(2)
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        log_file = logs_dir / f"run_{stamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("", encoding="utf-8")
    rel_log = _rel_to(workspace, log_file)

    timeout_sec = args.timeout_sec
    env = os.environ.copy()
    env["RA_LOG_FILE"] = str(log_file)
    env["PYTHONUTF8"] = "1"

    if argv_form:
        try:
            command: Any = _prepare_argv(argv_form, workspace, env)
        except ValueError as exc:
            print(f"[RA LOG ENGINE] {exc}", file=sys.stderr)
            sys.exit(2)
        shell = False
        shown_cmd = _display_argv(argv_form)
    else:
        command = args.cmd
        shell = True
        shown_cmd = args.cmd

    print("=" * 78)
    print(f"  RA REAL-ENVIRONMENT WATCHDOG RUNNER — `{hyp}` (MAX TIMEOUT: {timeout_sec}s)")
    print("=" * 78)
    print(f"  Command  : {shown_cmd}" + ("" if argv_form else "   (via platform shell)"))
    print(f"  Log File : {rel_log}")
    if os.name == "nt" and not argv_form and "'" in args.cmd:
        print("  WARNING  : cmd.exe does not treat '...' as quotes. Use the argv form: run [opts] -- prog arg ...")
    print("-" * 78)

    t0 = time.perf_counter()
    try:
        rc, out, err, timed_out = _run_watchdog(command, shell=shell, cwd=workspace, env=env, timeout_sec=timeout_sec)
    except OSError as exc:
        log_file.unlink(missing_ok=True)
        print(f"  [ERROR] Could not start the command: {exc}", file=sys.stderr)
        sys.exit(127)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    logger = RALogger(log_file, trace_id=f"RUN_{hyp}")
    logger.hop_counter = _count_records(log_file)
    if timed_out:
        logger.log_stuck(
            role="Real-Environment Process Execution Watchdog",
            waiting_on=f"Command `{shown_cmd}` hung past {timeout_sec}s watchdog limit",
            current_values={"stdout_tail": out.strip()[-600:], "stderr_tail": err.strip()[-600:]},
            state_snapshot={"process": "KILLED_BY_WATCHDOG" if rc is not None else "KILL_UNCONFIRMED"},
            elapsed_ms=elapsed_ms,
            flow="ra_log_engine:cmd_run->subprocess_timeout",
        )
        outcome, exit_code = "STUCK", 124
    elif rc != 0:
        detail = (err.strip() or out.strip())[-600:]
        logger.log_fail(
            role="Real-Environment Process Execution",
            reason=f"Process exited with code {rc}: {detail}",
            inputs={"cmd": shown_cmd},
            state_before={"process": "STARTING"},
            state_after={"process": f"EXIT_{rc}", "stdout_tail": out.strip()[-300:]},
            contract="PROCESS_CLEAN_EXIT",
            elapsed_ms=elapsed_ms,
            flow="ra_log_engine:cmd_run->subprocess",
        )
        outcome = "FAIL"
        exit_code = rc if 0 < rc < 256 else (128 - rc if -64 < rc < 0 else 1)
    else:
        outcome, exit_code = "PASS", 0

    score: Optional[float] = None
    if common is not None:
        score = common.parse_ra_score(out)
        if score is None:
            score = _score_from_log(log_file)

    # Only the log `run` wrote, byte-identical, may later pass `audit` and release the retry lock.
    state.setdefault("log_runs", {})[hyp] = {
        "log": rel_log,
        "sha256": _sha256_file(log_file),
        "outcome": outcome,
        "exit_code": rc,
        "cmd": shown_cmd,
        "at": now_iso(),
        "approach": approach,
        "score": score,
        "unseen": bool(args.unseen),
    }
    state["log_audit_passed"] = False  # an older audit no longer describes the latest run
    locked = False
    if outcome == "PASS":
        _clear_lock(state, hyp)
    else:
        locked = _record_failure(state, hyp, failed_cmd=shown_cmd, code_fp=code_fp, failed_log=rel_log)
    sb_notes: List[str] = []
    plateau = None
    if common is not None and approach:
        sb_notes, plateau = common.sb_record_round(
            workspace, state, hyp, approach, score=score, unseen=bool(args.unseen), log=rel_log, exit_code=rc
        )
    _save_state(state_path, state)

    for label, text in (("stdout", out), ("stderr", err)):
        if text.strip():
            print(f"  --- {label} (tail) ---")
            for tl in _tail(text).splitlines():
                print(f"  | {tl}")
    print("-" * 78)

    audit_hint = f"python ra_log_engine.py audit --workspace \"{args.workspace}\" --hypothesis {hyp}"
    sys.stdout.flush()
    if outcome == "STUCK":
        print(
            f"  [STUCK / KILLED BY WATCHDOG] Command hung past {timeout_sec}s limit! Process tree killed. "
            f"Recorded `[STUCK]` state in `{rel_log}`.",
            file=sys.stderr,
        )
    elif outcome == "FAIL":
        print(f"  [FAIL] Process exited with code {rc} ({elapsed_ms:.1f}ms). Logged to `{rel_log}`.")
    else:
        print(f"  [COMPLETED] Process exited 0 in {elapsed_ms:.1f}ms. Log: `{rel_log}`.")
        print(f"  Next     : {audit_hint}")
    if outcome != "PASS":
        print("  Retry lock ENGAGED for this hypothesis." if locked else "  Recorded as the hypothesis' initial reproduction (no retry lock).")
    if common is not None and approach:
        ap = common.sb_get(state, hyp)["approaches"][approach]
        found = common.metric_rule(state, hyp)
        cap = (found[1].get("max_rounds_per_approach") if found else None) or common.DEFAULT_MAX_ROUNDS_PER_APPROACH
        shown = common.fmt_score(score) if score is not None else "NONE (no `RA_SCORE=<x>` line on stdout)"
        print(
            f"  Score    : {shown} | approach `{approach}` round {len(ap['rounds'])}"
            + (f"/{cap}" if found else "")
            + (" | unseen" if args.unseen else "")
            + f" | {ap['status']}"
        )
        for note in sb_notes:
            print(f"  {note}")
        if plateau:
            sys.stdout.flush()
            _print_plateau_lock(
                common, workspace, state, hyp,
                f"[PLATEAU LOCK ENGAGED] `{hyp}`: further runs are refused until a cold review.", sys.stdout,
            )
    sys.exit(exit_code)


def extract_required_contracts(workspace: Path) -> List[str]:
    wmap = workspace / "research" / "WORKFLOW_MAP.md"
    if not wmap.exists():
        return []
    contracts: List[str] = []
    for line in wmap.read_text(encoding="utf-8-sig").splitlines():
        # `- **BC-001**: ...`, `- **`BC-001`**: ...`, `- BC-001: ...`, `- **BC-001:** ...`
        m = re.match(r"^\s*[-*]\s*(?:\*\*)?`?(BC-\d+)`?(?:\*\*)?\s*:(?:\*\*)?(.*)$", line)
        if m and "<e.g.," not in m.group(2):
            contracts.append(m.group(1))
    return contracts


_PLACEHOLDER_FLOWS = {"caller->callee", "unknown->unknown", "root->unknown"}


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
                    caller, _, callee = flow.partition("->")
                    if not role or role == "unspecified" or len(role) < 5:
                        slop_violations.append(
                            f"{log_path.name}:{idx}: `[PASS]` record missing meaningful functional `role` description."
                        )
                    if not caller.strip() or not callee.strip() or flow in _PLACEHOLDER_FLOWS:
                        slop_violations.append(
                            f"{log_path.name}:{idx}: `[PASS]` record `flow='{flow}'` must state the real `caller->callee` lineage."
                        )
                    empty_vals = (None, {}, [], "", {"args": [], "kwargs": {}})
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


def _resolve_audit_target(
    args: argparse.Namespace, workspace: Path, hyp: str, state: Dict[str, Any]
) -> Tuple[Optional[Path], bool, str]:
    """(log to audit, trusted?, provenance note). Trusted = the latest `run` log for `hyp`, unmodified."""
    sandbox_dir = workspace / "research" / "sandbox" / hyp
    rec = (state.get("log_runs") or {}).get(hyp)
    rec_path: Optional[Path] = None
    if rec and rec.get("log"):
        rec_path = Path(rec["log"])
        rec_path = (rec_path if rec_path.is_absolute() else workspace / rec_path).resolve()

    if args.log_file:
        target: Optional[Path] = Path(args.log_file).resolve()
    elif rec_path is not None:
        target = rec_path
    else:
        candidates = [p for p in sandbox_dir.rglob("*.log")] if sandbox_dir.exists() else []
        target = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

    if target is None or not target.exists():
        return target, False, "missing"
    if rec_path is None:
        return target, False, f"no `run` recorded for `{hyp}`"
    if target != rec_path:
        return target, False, f"not the latest `run` log (latest: {rec['log']})"
    if _sha256_file(target) != rec.get("sha256"):
        return target, False, "modified after `run` finished (sha256 mismatch)"
    return target, True, f"written by `run` at {rec.get('at')}"


def cmd_audit(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    state_path = rdir / ".ra_state.json"
    hyp = args.hypothesis.strip()
    state = _load_state(state_path)

    target, trusted, provenance = _resolve_audit_target(args, workspace, hyp, state)
    log_files: List[Path] = [target] if target is not None and target.exists() else []

    violations: List[str] = []
    all_records: List[Dict[str, Any]] = []

    if not log_files:
        where = f"`{target}`" if target is not None else f"`research/sandbox/{hyp}/`"
        violations.append(
            f"No `.log` file found at {where}! Run the real workflow with `ra_log_engine.py run` "
            f"(it writes `research/sandbox/{hyp}/logs/run_<timestamp>.log`) and wire `RALogger` to `$RA_LOG_FILE`. "
            f"RA forbids synthetic unit-test marathons."
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
            "Instrument the code with `RALogger` (`ra_log_engine.py`), log to `$RA_LOG_FILE`, and run it via `run`."
        )

    if stuck_records:
        for sr in stuck_records:
            violations.append(
                f"[STUCK AT HOP {sr.get('hop')}] flow=`{sr.get('flow')}` | role=\"{sr.get('role')}\" | "
                f"reason={json.dumps(sr.get('reason'), ensure_ascii=False)} | values={json.dumps(sr.get('inputs'), ensure_ascii=False)} | "
                f"state={json.dumps(sr.get('state_after'), ensure_ascii=False)}"
            )

    if fail_records:
        for fr in fail_records:
            violations.append(
                f"[FAIL AT HOP {fr.get('hop')}] flow=`{fr.get('flow')}` | role=\"{fr.get('role')}\" | "
                f"reason={json.dumps(fr.get('reason'), ensure_ascii=False)} | state_before={json.dumps(fr.get('state_before'), ensure_ascii=False)} -> "
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
    print(f"  Audited `.log` File  : {_rel_to(workspace, target) if target is not None else 'NONE'}")
    print(f"  Provenance           : {provenance}" + ("" if trusted else "  [ADVISORY ONLY - state unchanged]"))
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
        locked = False
        if trusted:
            state["log_audit_passed"] = False
            run_rec = state["log_runs"][hyp]
            # A failed/stuck run already did its own lock accounting in `run`.
            if run_rec.get("outcome") == "PASS":
                locked = _record_failure(
                    state,
                    hyp,
                    failed_cmd="audit",
                    code_fp=compute_code_fingerprint(workspace, hyp, state),
                    failed_log=run_rec["log"],
                )
            _save_state(state_path, state)
        print("  [FAIL] REAL-ENVIRONMENT `.log` AUDIT REJECTED THE RUN:")
        for v in violations:
            print(f"    - {v}")
        print("-" * 78)
        if locked or (trusted and _lock_for(state, hyp)):
            print(
                "  [ANTI-LAZY-RETRY LOCK] Before re-running after a failed fix attempt, you MUST run:\n"
                "    python ra_gate.py re-evaluate --component <slug> --why-failed \"...\" --new-calculation \"...\" --why-different \"...\""
            )
        print("=" * 78)
        sys.exit(1)

    if not trusted:
        print(
            "  [NOT ACCEPTED] The trace is clean, but only the latest log written by `ra_log_engine.py run`\n"
            "  (unmodified) can pass the audit gate. Re-run the workflow via `run`, then audit again."
        )
        print("=" * 78)
        sys.exit(2)

    if state_path.exists():
        state["log_audit_passed"] = True
        common = _ra_common()  # lazy: this file doubles as the Python SDK copied into projects without ra_common
        if common is not None:
            state.setdefault("pass_fingerprints", {})["log_audit_passed"] = common.code_fingerprint(workspace, state, hyp)
        _clear_lock(state, hyp)
        _save_state(state_path, state)

    print("  [PASS] Real-Environment `.log` Flow, Functional Roles, State Deltas & Contracts Verified!")
    print("=" * 78)


RUN_EPILOG = """\
command forms (give exactly one):
  --cmd "<string>"      run through the platform shell: cmd.exe on Windows, /bin/sh on POSIX.
                        cmd.exe does NOT understand '...' quotes or `NAME=value prog` prefixes.
  -- PROG [ARGS...]     argv form, no shell, identical on every OS. Leading NAME=value
                        tokens set environment variables for the program.

examples:
  run --hypothesis H001 --timeout-sec 60 -- python app.py --flag
  run --hypothesis H001 -- DEBUG=1 node server.js
  run --hypothesis H001 --cmd "npm test"

every run writes a fresh log research/sandbox/<hyp>/logs/run_<YYYYmmdd-HHMMSS-mmm>.log; its path
is exported to the program as $RA_LOG_FILE. `audit` checks the latest one by default.

scoreboard: every run is a round. The program prints `RA_SCORE=<x>` (the last such stdout line
counts). With a numeric stop rule, pass --approach <family> (from REPORT.md Section 3) and --unseen
on held-out data. BLIND / FLAT / BASELINE / CAP plateaus lock all runs of the hypothesis until
`ra_gate.py cold-review`; target met on an --unseen round = WON. See `ra_gate.py status --scoreboard`.

exit codes: the program's exit code, 124 = killed by the watchdog, 127 = could not start,
2 = blocked by the retry lock / plateau lock / usage error.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA Production-Grade Real-Environment `.log` Telemetry & Flow Auditor")
    sub = p.add_subparsers(dest="subcommand", required=True)

    p_sdk = sub.add_parser("inject-sdk", help="Generate production RALogger SDK into a project directory")
    p_sdk.add_argument("--workspace", default=".", help="Workspace root")
    p_sdk.add_argument(
        "--lang",
        required=True,
        choices=["python", "js", "node", "esm", "mjs", "ts", "php", "laravel"],
        help="python -> ra_logger.py | js/node -> ra_logger.js (CommonJS) | esm/mjs -> ra_logger.mjs (ES module) "
        "| ts -> ra_logger.ts (ES module) | php/laravel -> RALogger.php",
    )
    p_sdk.add_argument("--dest", default=".", help="Destination directory relative to workspace")
    p_sdk.set_defaults(func=cmd_inject_sdk)

    p_run = sub.add_parser(
        "run",
        help="Run a real-environment command under a strict watchdog timer and log `[STUCK]` on hang",
        usage="%(prog)s [options] (--cmd \"<shell string>\" | -- PROG [ARGS...])",
        epilog=RUN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_run.add_argument("--workspace", default=".", help="Workspace root (the command runs here)")
    p_run.add_argument("--hypothesis", default="STANDALONE", help="Active hypothesis folder (e.g., H001_slug) or STANDALONE")
    p_run.add_argument(
        "--cmd",
        default=None,
        help="Command string run through the platform shell (cmd.exe on Windows, /bin/sh on POSIX). "
        "For portable quoting use the argv form after `--` instead.",
    )
    p_run.add_argument("--timeout-sec", type=int, default=60, help="Hard watchdog timeout in seconds; the whole process tree is killed")
    p_run.add_argument("--log-file", default=None, help="Optional custom `.log` path (must end in .log; overwritten each run)")
    p_run.add_argument(
        "--initial-repro",
        action="store_true",
        help="Mark this run as the hypothesis' Phase 1 bug reproduction. Allowed once per hypothesis; "
        "the first failing run of a hypothesis never engages the retry lock, every later one does",
    )
    p_run.add_argument(
        "--approach",
        default=None,
        help="Option Sweep family this round belongs to (required once the stop rule has --min-gain; "
        "must appear in REPORT.md Section 3). Default: main",
    )
    p_run.add_argument("--unseen", action="store_true", help="This run used held-out data (only unseen rounds can be WON)")
    p_run.set_defaults(func=cmd_run)

    p_audit = sub.add_parser(
        "audit",
        help="Audit the latest `run` log for flow, values, `[PASS]`/`[STUCK]`/`[FAIL]`, and contracts",
    )
    p_audit.add_argument("--workspace", default=".", help="Workspace root")
    p_audit.add_argument("--hypothesis", default="STANDALONE", help="Active hypothesis folder (e.g., H001_slug) or STANDALONE")
    p_audit.add_argument(
        "--log-file",
        default=None,
        help="Audit this `.log` instead of the latest `run` log. Only an unmodified log written by `run` "
        "can pass the gate; any other file is audited as advisory (state unchanged)",
    )
    p_audit.set_defaults(func=cmd_audit)

    return p


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: Optional[List[str]] = None) -> None:
    _utf8_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    tail: Optional[List[str]] = None
    if "--" in argv:
        split = argv.index("--")
        argv, tail = argv[:split], argv[split + 1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if tail is not None and args.subcommand != "run":
        parser.error("`-- PROG [ARGS...]` is only valid for `run`")
    args.argv = tail or []
    args.func(args)


if __name__ == "__main__":
    main()
