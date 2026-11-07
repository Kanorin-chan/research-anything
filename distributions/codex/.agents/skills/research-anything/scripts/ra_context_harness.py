#!/usr/bin/env python3
"""
ra_context_harness.py — Multi-Platform Subagent Context Controller, `/fork` Manager & Eviction Harness.

First-Class Platform Support:
  1. `opencode` (OpenCode CLI: `opencode run --session <id> --fork` & `-f FORK_<subagent>.md`)
  2. `claude`   (Claude Code: `claude --resume <id> --fork-session`, `/fork`, & `Task` subagent tool)
  3. `codex`    (OpenAI Codex CLI: `codex exec --full-auto` & `codex resume <id>`)
  4. `agy`      (Antigravity / Gemini: `invoke_subagent` with `Workspace: share/branch/inherit` & Gemini CLI)

Enforces RA's Lead-Orchestrator & Context-Control Protocol:
  1. Main Agent = Lead Orchestrator / Compiler (delegates execution to Subagents even at 1-concurrency baton-pass).
  2. Read Once -> Fork Many (`/fork` style):
     Compile a shared context snapshot once (`BASE_FRAMEWORK` or `WORKFLOW_SLICE`) and fork it to
     `Subagent_A`, `Subagent_B`, etc., so subagents do not re-read the whole codebase from scratch.
  3. 3-Tier Snapshot Lifecycle & Automatic Eviction (Throw-Away Rules):
     - Tier 1 (`BASE_FRAMEWORK`): Framework/domain knowledge, `INVARIANTS.md`, crawled skills.
       Kept across the track; thrown away only if invariants/framework files change (`HASH_DRIFT`).
     - Tier 2 (`WORKFLOW_SLICE`): Subsystem workflow subgraph (`-N` to `+N` hops), `PROTECTED_WORKING`
       nodes, `BC-xxx` contracts, and exact source file SHA-256 hashes.
       Forked across sibling subagents; thrown away immediately on `HASH_DRIFT` (any tracked file edited),
       `MAX_REUSE_EXCEEDED`, or `TTL_EXPIRED`.
     - Tier 3 (`TASK_EPHEMERAL`): Single-task delta for 1 subagent (`max_reuses = 1`).
       Thrown away immediately upon task completion or subagent failure/drift.
  4. Task-Sizing Gate:
     - `REAL_RD` tasks (logic, state flow, bug fix, hypothesis prototype, `.log` wiring): Strictly 1 task per subagent.
     - `TRIVIAL_BATCH` tasks (CSS, icons, labels, formatting): Batching allowed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TIER_DEFAULTS = {
    "BASE_FRAMEWORK": {"max_reuses": 25, "ttl_minutes": 1440},
    "WORKFLOW_SLICE": {"max_reuses": 6, "ttl_minutes": 180},
    "TASK_EPHEMERAL": {"max_reuses": 1, "ttl_minutes": 30},
}

SUPPORTED_PLATFORMS = ("auto", "opencode", "claude", "codex", "agy")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone()


def now_iso() -> str:
    return now_utc().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip()).strip("_")
    return s or "snap"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_platform(requested: str = "auto") -> str:
    req = requested.lower()
    if req in ("opencode", "claude", "codex", "agy"):
        return req
    if os.environ.get("OPENCODE") or os.environ.get("OPENCODE_SESSION"):
        return "opencode"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_SANDBOX"):
        return "codex"
    if os.environ.get("ANTIGRAVITY_CLI") or os.environ.get("GEMINI_CLI"):
        return "agy"
    if shutil.which("opencode"):
        return "opencode"
    if shutil.which("claude"):
        return "claude"
    if shutil.which("codex"):
        return "codex"
    return "agy"


def get_snapshots_dir(workspace: Path) -> Path:
    d = workspace / "research" / "context_snapshots"
    (d / "forks").mkdir(parents=True, exist_ok=True)
    (d / "reports").mkdir(parents=True, exist_ok=True)
    (d / "evicted").mkdir(parents=True, exist_ok=True)
    return d


def get_registry_path(workspace: Path) -> Path:
    return get_snapshots_dir(workspace) / "SNAPSHOT_REGISTRY.json"


def load_registry(workspace: Path) -> Dict[str, Any]:
    rp = get_registry_path(workspace)
    default_reg: Dict[str, Any] = {
        "snapshots": {},
        "evicted_history": [],
        "active_baton": "MAIN_ORCHESTRATOR",
        "total_forks_dispatched": 0,
        "completed_subagent_relays": 0,
        "subagent_reports": [],
        "last_gc_at": None,
    }
    if not rp.exists():
        return default_reg
    try:
        loaded = json.loads(rp.read_text(encoding="utf-8"))
        for k, v in default_reg.items():
            loaded.setdefault(k, v)
        return loaded
    except Exception:
        return default_reg


def save_registry(workspace: Path, reg: Dict[str, Any]) -> None:
    rp = get_registry_path(workspace)
    reg["updated_at"] = now_iso()
    rp.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def evaluate_snapshot_health(workspace: Path, snap: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Determine whether a snapshot is still valid for reuse/forking or MUST be thrown away (evicted).
    Returns (is_healthy, eviction_reasons).
    """
    reasons: List[str] = []

    if snap.get("status") != "ACTIVE":
        reasons.append(f"STATUS_{snap.get('status', 'INACTIVE')}")
        return False, reasons

    # 1. Check file SHA-256 hash drift
    for rel_path, recorded_hash in snap.get("tracked_files", {}).items():
        fpath = workspace / rel_path
        if not fpath.exists():
            reasons.append(f"FILE_DELETED ({rel_path})")
        else:
            curr_hash = sha256_file(fpath)
            if curr_hash != recorded_hash:
                reasons.append(f"HASH_DRIFT ({rel_path}: {recorded_hash[:8]}... -> {curr_hash[:8]}...)")

    # 2. Check reuse count budget
    reuse_count = snap.get("reuse_count", 0)
    max_reuses = snap.get("max_reuses", 5)
    if reuse_count >= max_reuses:
        reasons.append(f"MAX_REUSE_EXCEEDED ({reuse_count}/{max_reuses})")

    # 3. Check TTL expiration
    created_str = snap.get("created_at")
    ttl_minutes = snap.get("ttl_minutes", 180)
    if created_str and ttl_minutes > 0:
        try:
            created_dt = dt.datetime.fromisoformat(created_str)
            age_min = (now_utc() - created_dt).total_seconds() / 60.0
            if age_min > ttl_minutes:
                reasons.append(f"TTL_EXPIRED ({int(age_min)}m > {ttl_minutes}m)")
        except Exception:
            pass

    return len(reasons) == 0, reasons


def evict_snapshot_internal(workspace: Path, reg: Dict[str, Any], snap_id: str, reason: str) -> None:
    snaps = reg.get("snapshots", {})
    if snap_id not in snaps:
        return
    snap = snaps.pop(snap_id)
    snap["status"] = "EVICTED"
    snap["evicted_at"] = now_iso()
    snap["eviction_reason"] = reason
    reg.setdefault("evicted_history", []).append(snap)

    sdir = get_snapshots_dir(workspace)
    src_md = sdir / f"{snap_id}.md"
    if src_md.exists():
        dest_md = sdir / "evicted" / f"{snap_id}_EVICTED.md"
        if dest_md.exists():
            dest_md.unlink()
        src_md.rename(dest_md)


def build_platform_fork_instructions(
    platform: str,
    subagent_name: str,
    rel_fork_file: str,
    rel_report_file: str,
    base_session_id: Optional[str],
    model: Optional[str],
) -> Dict[str, str]:
    """Generate exact context-forking commands/calls for OpenCode, Claude Code, Codex, and Antigravity/Gemini."""
    oc_model_flag = f'--model "{model}" ' if model else ""
    codex_model_flag = f'-m "{model}" ' if model else ""
    if base_session_id:
        opencode_cmd = (
            f'opencode run --session "{base_session_id}" --fork --title "{subagent_name}" '
            f'{oc_model_flag}--auto -f "{rel_fork_file}" '
            f'"Execute the bounded task in {rel_fork_file} and write your findings to {rel_report_file}."'
        )
        claude_cmd = (
            f'claude --resume "{base_session_id}" --fork-session '
            f'-p "Read {rel_fork_file}, execute ONLY the bounded task, and write your report to {rel_report_file}."'
        )
        codex_cmd = (
            f'codex exec resume "{base_session_id}" {codex_model_flag}--full-auto '
            f'"Read {rel_fork_file} (shared forked context snapshot). Do NOT re-read already-summarized files. '
            f'Execute ONLY the bounded task and write your report to {rel_report_file}."'
        )
    else:
        opencode_cmd = (
            f'opencode run --title "{subagent_name}" {oc_model_flag}--auto -f "{rel_fork_file}" '
            f'"Execute the bounded task in {rel_fork_file} and write your findings to {rel_report_file}."'
        )
        claude_cmd = (
            f'Task(subagent_type="general-purpose", description="{subagent_name}", '
            f'prompt="Read {rel_fork_file} (shared forked context snapshot). Do NOT re-read already-summarized files. '
            f'Execute ONLY the bounded task and write your report to {rel_report_file}.")'
        )
        codex_cmd = (
            f'codex exec {codex_model_flag}--full-auto '
            f'"Read {rel_fork_file} (shared forked context snapshot). Do NOT re-read already-summarized files. '
            f'Execute ONLY the bounded task and write your report to {rel_report_file}."'
        )

    agy_cmd = (
        f'invoke_subagent(TypeName="self", Role="{subagent_name}", Workspace="inherit", '
        f'Prompt="Read {rel_fork_file} (shared forked context snapshot). Do NOT re-read already-summarized files. '
        f'Execute ONLY the bounded task and write your report to {rel_report_file}.")'
    )

    return {
        "active_platform": platform,
        "opencode": opencode_cmd,
        "claude": claude_cmd,
        "codex": codex_cmd,
        "agy": agy_cmd,
    }


def cmd_create(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    sdir = get_snapshots_dir(workspace)
    reg = load_registry(workspace)

    snap_id = slugify(args.id)
    tier = args.tier.upper()
    defaults = TIER_DEFAULTS[tier]
    max_reuses = args.max_reuses if args.max_reuses is not None else defaults["max_reuses"]
    ttl_minutes = args.ttl_minutes if args.ttl_minutes is not None else defaults["ttl_minutes"]
    ts = now_iso()

    tracked_files: Dict[str, str] = {}
    for fstr in args.files or []:
        fpath = (workspace / fstr).resolve()
        if not fpath.exists() or not fpath.is_file():
            print(f"[RA CONTEXT HARNESS] WARNING: File not found: {fstr}", file=sys.stderr)
            continue
        rel = fpath.relative_to(workspace).as_posix()
        tracked_files[rel] = sha256_file(fpath)

    snap_md_path = sdir / f"{snap_id}.md"
    md_content = (
        f"# Context Snapshot `{snap_id}` (`{tier}`)\n\n"
        f"- **Created Timestamp**: `{ts}`\n"
        f"- **Tier**: `{tier}`\n"
        f"- **Base Session ID (for native `/fork`)**: `{args.base_session or 'DISK_SNAPSHOT_PACKET'}`\n"
        f"- **Reuse Budget**: `0 / {max_reuses}` forks\n"
        f"- **TTL**: `{ttl_minutes}` minutes\n"
        f"- **Tracked Files ({len(tracked_files)})**: "
        f"{', '.join(f'`{k}` (`{v[:10]}...`)' for k, v in tracked_files.items()) or 'None'}\n\n"
        f"## Compiled Context Summary (Read-Once Shared Packet)\n"
        f"{args.summary.strip()}\n"
    )
    snap_md_path.write_text(md_content, encoding="utf-8")
    approx_tokens = max(1, len(md_content) // 4)

    reg.setdefault("snapshots", {})[snap_id] = {
        "id": snap_id,
        "tier": tier,
        "status": "ACTIVE",
        "created_at": ts,
        "base_session_id": args.base_session,
        "max_reuses": max_reuses,
        "reuse_count": 0,
        "ttl_minutes": ttl_minutes,
        "approx_tokens": approx_tokens,
        "tracked_files": tracked_files,
        "forked_to": [],
        "file": snap_md_path.relative_to(workspace).as_posix(),
    }
    save_registry(workspace, reg)

    print("=" * 78)
    print(f"  RA CONTEXT SNAPSHOT CREATED: `{snap_id}` ({tier})")
    print("=" * 78)
    print(f"  Snapshot File   : {snap_md_path.relative_to(workspace).as_posix()} (~{approx_tokens} tokens)")
    print(f"  Retention Limit : Up to {max_reuses} fork(s) or {ttl_minutes} minutes (auto-evicted on hash drift)")
    print(f"  Tracked Files   : {len(tracked_files)}")
    print("=" * 78)


def cmd_fork(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    sdir = get_snapshots_dir(workspace)
    reg = load_registry(workspace)
    snaps = reg.get("snapshots", {})

    # 1-Concurrency Baton Check: Do not allow overlapping subagents unless --parallel is explicitly passed
    active_baton = reg.get("active_baton", "MAIN_ORCHESTRATOR")
    if active_baton != "MAIN_ORCHESTRATOR" and not args.parallel:
        print(
            f"[RA CONTEXT HARNESS BLOCKED] 1-Concurrency Baton Violation!\n"
            f"  Baton is currently held by `{active_baton}`.\n"
            f"  Wait for the active subagent to finish and run `ra_context_harness.py return-baton --subagent ...`\n"
            f"  before forking the next subagent (or pass `--parallel` if multi-instance concurrency is enabled).",
            file=sys.stderr,
        )
        sys.exit(1)

    subagent_name = slugify(args.subagent)
    task_type = args.task_type.upper()
    raw_task = args.task
    if isinstance(raw_task, list):
        if len(raw_task) > 1 and task_type == "REAL_RD" and not args.allow_multi_step:
            print(
                "[RA CONTEXT HARNESS BLOCKED] Task-Sizing Violation (`REAL_RD`):\n"
                "  Do NOT pass multiple tasks to a `REAL_RD` subagent fork (causes long-context pollution).\n"
                "  Split into 1 atomic task per subagent fork, OR use `--task-type TRIVIAL_BATCH` only for small\n"
                "  surface tweaks (e.g., CSS, icon, label changes).",
                file=sys.stderr,
            )
            sys.exit(1)
        task_desc = "\n".join(f"- {t.strip()}" for t in raw_task if t.strip()) if len(raw_task) > 1 else raw_task[0].strip()
    else:
        task_desc = str(raw_task).strip()
    platform = detect_platform(args.platform)

    # Enforce Task-Sizing Gate: Real R&D tasks must be 1 atomic task per subagent
    if task_type == "REAL_RD":
        numbered_items = re.findall(r"(?:^|\n)\s*\d+[\.\)]\s+", task_desc)
        if len(numbered_items) > 1 and not args.allow_multi_step:
            print(
                "[RA CONTEXT HARNESS BLOCKED] Task-Sizing Violation (`REAL_RD`):\n"
                "  Do NOT dump multiple real R&D/logic tasks onto a single subagent (causes long-context pollution).\n"
                "  Split into 1 atomic task per subagent fork, OR use `--task-type TRIVIAL_BATCH` only for small\n"
                "  surface tweaks (e.g., CSS, icon, label changes).",
                file=sys.stderr,
            )
            sys.exit(1)

    requested_ids = [slugify(sid) for sid in args.snapshots]
    compiled_sections: List[str] = []
    base_session_id: Optional[str] = args.base_session

    for sid in requested_ids:
        if sid not in snaps:
            print(f"[RA CONTEXT HARNESS ERROR] Snapshot `{sid}` not found (or already evicted).", file=sys.stderr)
            sys.exit(1)
        snap = snaps[sid]
        healthy, reasons = evaluate_snapshot_health(workspace, snap)
        if not healthy:
            reason_str = ", ".join(reasons)
            evict_snapshot_internal(workspace, reg, sid, reason_str)
            save_registry(workspace, reg)
            print(
                f"[RA CONTEXT HARNESS AUTO-EVICTED] Snapshot `{sid}` is stale/invalid ({reason_str}) and was "
                f"THROWN AWAY!\n  Rebuild a fresh snapshot before forking to `{subagent_name}`.",
                file=sys.stderr,
            )
            sys.exit(1)

        if not base_session_id and snap.get("base_session_id"):
            base_session_id = snap.get("base_session_id")

        # Increment reuse counter and log fork lineage
        snap["reuse_count"] = snap.get("reuse_count", 0) + 1
        snap.setdefault("forked_to", []).append(
            {
                "subagent": subagent_name,
                "forked_at": now_iso(),
                "task_type": task_type,
                "platform": platform,
            }
        )
        snap_file = workspace / snap["file"]
        if snap_file.exists():
            compiled_sections.append(snap_file.read_text(encoding="utf-8"))

        # If this was a 1-shot TASK_EPHEMERAL snapshot, mark it consumed after this fork
        if snap.get("tier") == "TASK_EPHEMERAL" and snap["reuse_count"] >= snap.get("max_reuses", 1):
            evict_snapshot_internal(workspace, reg, sid, "TASK_EPHEMERAL_CONSUMED_BY_FORK")

    # Record 1-Concurrency Baton Pass to the Subagent
    reg["active_baton"] = f"SUBAGENT:{subagent_name}"
    reg["total_forks_dispatched"] = reg.get("total_forks_dispatched", 0) + 1
    save_registry(workspace, reg)

    fork_file = sdir / "forks" / f"FORK_{subagent_name}.md"
    report_file = sdir / "reports" / f"REPORT_{subagent_name}.md"
    rel_fork = fork_file.relative_to(workspace).as_posix()
    rel_report = report_file.relative_to(workspace).as_posix()

    dispatch_cmds = build_platform_fork_instructions(
        platform, subagent_name, rel_fork, rel_report, base_session_id, args.model
    )

    fork_packet = (
        f"# Forked Subagent Execution Brief — `{subagent_name}`\n\n"
        f"- **Forked Timestamp**: `{now_iso()}`\n"
        f"- **Target Platform**: `{platform}` (`opencode` | `claude` | `codex` | `agy`)\n"
        f"- **Concurrency / Baton Mode**: `1-CONCURRENCY BATON PASS` (Main Agent is IDLE waiting for your report)\n"
        f"- **Task Classification**: `{task_type}`\n"
        f"- **Inherited Context Snapshots**: {', '.join(f'`{s}`' for s in requested_ids)}\n"
        f"- **Required Report Output Path**: `{rel_report}`\n\n"
        f"---\n\n"
        f"## 1. Your Bounded Task Assignment\n"
        f"{task_desc}\n\n"
        f"> **Strict Subagent Context-Control Rules**:\n"
        f"> 1. **Do NOT re-read files already summarized in Section 2** — this context was forked to you so you do not waste tokens re-discovering the project.\n"
        f"> 2. **Do NOT touch any `PROTECTED_WORKING` function (`Symptom != Culprit`)**.\n"
        f"> 3. **Write your concise evidence-backed report to `{rel_report}`** and stop immediately so the Main Agent can verify your work and reclaim the baton.\n\n"
        f"---\n\n"
        f"## 2. Inherited Context Snapshots (`/fork` Shared State)\n\n"
        + "\n\n---\n\n".join(compiled_sections)
    )
    fork_file.write_text(fork_packet, encoding="utf-8")

    print("=" * 78)
    print(f"  RA CONTEXT FORK READY -> SUBAGENT: `{subagent_name}` (PLATFORM: {platform.upper()})")
    print("=" * 78)
    print(f"  Forked Brief File   : {rel_fork}")
    print(f"  Subagent Report Out : {rel_report}")
    print(f"  Inherited Snapshots : {', '.join(requested_ids)}")
    print(f"  Task Classification : {task_type}")
    print(f"  Active Execution    : BATON PASSED TO `{subagent_name}` (Main Agent waits for report)")
    print("-" * 78)
    print("  MULTI-PLATFORM SUBAGENT DISPATCH COMMANDS:")
    print(f"    [opencode]    : {dispatch_cmds['opencode']}")
    print(f"    [claude-code] : {dispatch_cmds['claude']}")
    print(f"    [codex]       : {dispatch_cmds['codex']}")
    print(f"    [agy/gemini]  : {dispatch_cmds['agy']}")
    print("-" * 78)
    print(
        f"  WHEN `{subagent_name}` FINISHES: Run `ra_context_harness.py return-baton --subagent {subagent_name} "
        f"--report-file {rel_report}`"
    )
    print("=" * 78)


def cmd_return_baton(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    sdir = get_snapshots_dir(workspace)
    reg = load_registry(workspace)
    subagent_name = slugify(args.subagent)

    report_path = (
        (workspace / args.report_file).resolve()
        if args.report_file
        else (sdir / "reports" / f"REPORT_{subagent_name}.md")
    )
    report_summary = (args.summary or "").strip()

    if report_path.exists():
        body = report_path.read_text(encoding="utf-8", errors="replace").strip()
        if not report_summary:
            report_summary = body[:300].replace("\n", " ")
    elif report_summary:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            f"# Subagent Report: `{subagent_name}`\n\n- **Returned At**: `{now_iso()}`\n\n{report_summary}\n",
            encoding="utf-8",
        )
    else:
        print(
            f"[RA CONTEXT HARNESS BLOCKED] Cannot return baton from `{subagent_name}` without a report!\n"
            f"  Either have `{subagent_name}` write `{report_path.relative_to(workspace).as_posix()}` "
            f"or pass `--summary \"<findings>\"`.",
            file=sys.stderr,
        )
        sys.exit(1)

    reg["active_baton"] = "MAIN_ORCHESTRATOR"
    reg["completed_subagent_relays"] = reg.get("completed_subagent_relays", 0) + 1
    reg.setdefault("subagent_reports", []).append(
        {
            "subagent": subagent_name,
            "returned_at": now_iso(),
            "report_file": report_path.relative_to(workspace).as_posix()
            if report_path.is_relative_to(workspace)
            else str(report_path),
            "summary": report_summary[:240],
        }
    )

    # Auto-check if any active snapshots drifted during the subagent's work!
    drifted_snaps: List[Tuple[str, str]] = []
    for sid in list(reg.get("snapshots", {}).keys()):
        healthy, reasons = evaluate_snapshot_health(workspace, reg["snapshots"][sid])
        if not healthy:
            r_str = ", ".join(reasons)
            evict_snapshot_internal(workspace, reg, sid, f"AUTO_EVICT_ON_BATON_RETURN: {r_str}")
            drifted_snaps.append((sid, r_str))

    save_registry(workspace, reg)

    print("=" * 78)
    print(f"  RA BATON RETURNED: `{subagent_name}` -> `MAIN_ORCHESTRATOR`")
    print("=" * 78)
    print(f"  Completed Subagent Relays : {reg['completed_subagent_relays']}")
    print(f"  Verified Report File      : {report_path.relative_to(workspace).as_posix() if report_path.is_relative_to(workspace) else report_path}")
    if drifted_snaps:
        print("  [AUTO-EVICTED STALE SNAPSHOTS AFTER SUBAGENT WORK]:")
        for sid, r_str in drifted_snaps:
            print(f"    - Threw away `{sid}` ({r_str})")
    print("-" * 78)
    print("  ZERO-TRUST SUBAGENT SUPERVISION CHECKLIST FOR MAIN AGENT:")
    print("    1. Assume the subagent may have drifted or missed a constraint — verify its diff/output directly.")
    print("    2. Run `python research/harness/project_harness.py check-all` (if forged) or `ra_cheese_audit.py`.")
    print("=" * 78)


def cmd_evict(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    reg = load_registry(workspace)
    snaps = list(reg.get("snapshots", {}).keys())

    evicted_now: List[Tuple[str, str]] = []
    if args.auto_gc:
        for sid in snaps:
            healthy, reasons = evaluate_snapshot_health(workspace, reg["snapshots"][sid])
            if not healthy:
                reason_str = ", ".join(reasons)
                evict_snapshot_internal(workspace, reg, sid, reason_str)
                evicted_now.append((sid, reason_str))
        reg["last_gc_at"] = now_iso()
    elif args.id:
        sid = slugify(args.id)
        if sid in reg.get("snapshots", {}):
            reason = args.reason or "MANUAL_MAIN_AGENT_EVICTION"
            evict_snapshot_internal(workspace, reg, sid, reason)
            evicted_now.append((sid, reason))
        else:
            print(f"[RA CONTEXT HARNESS] Snapshot `{sid}` not found in active registry.", file=sys.stderr)
            sys.exit(1)

    save_registry(workspace, reg)
    print("=" * 78)
    print("  RA CONTEXT SNAPSHOT GARBAGE COLLECTION / EVICTION")
    print("=" * 78)
    if evicted_now:
        for sid, r in evicted_now:
            print(f"  - [THROWN AWAY / EVICTED] `{sid}` -> Reason: {r}")
    else:
        print("  - All active snapshots are fresh (0 snapshots evicted).")
    print("=" * 78)


def cmd_status(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    reg = load_registry(workspace)
    snaps = reg.get("snapshots", {})
    evicted_hist = reg.get("evicted_history", [])

    print("=" * 78)
    print("  RA SUBAGENT CONTEXT CONTROLLER & SNAPSHOT HARNESS STATUS")
    print("=" * 78)
    print(f"  Active Execution Baton    : {reg.get('active_baton', 'MAIN_ORCHESTRATOR')}")
    print(f"  Total Forks Dispatched    : {reg.get('total_forks_dispatched', 0)}")
    print(f"  Completed Subagent Relays : {reg.get('completed_subagent_relays', 0)}")
    print(f"  Active Snapshots          : {len(snaps)}")
    print(f"  Evicted (Thrown Away)     : {len(evicted_hist)}")
    print("-" * 78)

    if snaps:
        print("  ACTIVE CONTEXT SNAPSHOTS (RETENTION & REUSE METRICS):")
        for sid, snap in snaps.items():
            healthy, reasons = evaluate_snapshot_health(workspace, snap)
            health_tag = "FRESH" if healthy else f"STALE — MUST THROW AWAY ({', '.join(reasons)})"
            forks = [f.get("subagent", "?") for f in snap.get("forked_to", [])]
            print(
                f"    - `{sid}` [{snap.get('tier')}] | Reuses: {snap.get('reuse_count')}/{snap.get('max_reuses')} "
                f"| ~{snap.get('approx_tokens', 0)} tok | Status: {health_tag}"
            )
            if forks:
                print(f"      Forked To Subagents: {', '.join(forks)}")
    else:
        print("  (No active snapshots. Use `ra_context_harness.py create` to build a shared base/slice snapshot.)")

    if evicted_hist:
        print("-" * 78)
        print("  RECENTLY THROWN-AWAY (EVICTED) SNAPSHOTS:")
        for ev in evicted_hist[-5:]:
            print(f"    - `{ev.get('id')}` [{ev.get('tier')}] -> Thrown away because: {ev.get('eviction_reason')}")
    print("=" * 78)


def cmd_handoff(args: argparse.Namespace) -> None:
    """Write a portable cross-harness handoff document (like `/handoff`) with RA artifact pointers."""
    import tempfile

    workspace = Path(args.workspace).resolve()
    reg = load_registry(workspace)
    snaps = list(reg.get("snapshots", {}).keys())

    # Collect existing RA and domain artifacts by path (never duplicating their full text)
    artifact_pointers: List[str] = []
    for candidate in (
        "GLOSSARY.md",
        "research/VISION_AND_MISSION.md",
        "research/INVARIANTS.md",
        "research/WORKFLOW_MAP.md",
        "research/LAB_LOG.md",
        "research/SELF_LEARNING.md",
    ):
        fp = workspace / candidate
        if fp.exists():
            artifact_pointers.append(f"- `{ (workspace / candidate).as_posix() }`")

    for sid in snaps:
        sfile = reg["snapshots"][sid].get("file")
        if sfile:
            artifact_pointers.append(f"- Context Snapshot `{sid}`: `{ (workspace / sfile).as_posix() }`")

    suggested_skills = args.suggested_skills or ["ra-ask", "ra-systemic-debug", "research-anything"]
    skills_bullets = "\n".join(f'- Call the Skill tool with `"{s}"`' for s in suggested_skills)

    ts_slug = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        tmp_dir = Path(tempfile.gettempdir())
        out_path = tmp_dir / f"RA_HANDOFF_{workspace.name}_{ts_slug}.md"

    doc = (
        f"# RA Portable Session Handoff — `{workspace.name}`\n\n"
        f"- **Created Timestamp**: `{now_iso()}`\n"
        f"- **Workspace Path**: `{workspace.as_posix()}`\n"
        f"- **Next Session Focus**: {args.focus or 'Continue active R&D / systemic engineering work'}\n\n"
        f"---\n\n"
        f"## 1. Conversation & State Summary\n"
        f"{args.summary}\n\n"
        f"---\n\n"
        f"## 2. Primary Source Artifacts on Disk (Read by Path — Do Not Duplicate)\n"
        + ("\n".join(artifact_pointers) if artifact_pointers else "- *(No RA artifacts initialized yet)*")
        + "\n\n---\n\n"
        f"## 3. Suggested Skills for Next Session\n"
        f"{skills_bullets}\n"
    )
    out_path.write_text(doc, encoding="utf-8")

    print("=" * 78)
    print("  RA PORTABLE HANDOFF DOCUMENT CREATED")
    print("=" * 78)
    print(f"  Handoff File     : {out_path.as_posix()}")
    print(f"  Next Focus       : {args.focus or 'Continue active work'}")
    print(f"  Suggested Skills : {', '.join(suggested_skills)}")
    print("=" * 78)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA Multi-Platform Subagent Context Controller & `/fork` Snapshot Harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser(
        "create",
        help="Create a shared context snapshot (`BASE_FRAMEWORK`, `WORKFLOW_SLICE`, `TASK_EPHEMERAL`)",
    )
    p_create.add_argument("--workspace", default=".", help="Workspace root")
    p_create.add_argument("--id", required=True, help="Snapshot ID (e.g., 'laravel_base' or 'auth_flow_slice')")
    p_create.add_argument(
        "--tier",
        required=True,
        choices=[
            "BASE_FRAMEWORK",
            "WORKFLOW_SLICE",
            "TASK_EPHEMERAL",
            "base_framework",
            "workflow_slice",
            "task_ephemeral",
        ],
        help="Snapshot lifecycle tier",
    )
    p_create.add_argument("--summary", required=True, help="Compiled context summary text so subagents skip re-reading")
    p_create.add_argument(
        "--files",
        nargs="*",
        default=[],
        help="Source files summarized by this snapshot (tracked via SHA-256 for auto-eviction on edit)",
    )
    p_create.add_argument(
        "--base-session",
        default=None,
        help="Optional native session ID for `opencode run --session <id> --fork` or `claude --resume <id> --fork-session`",
    )
    p_create.add_argument("--max-reuses", type=int, default=None, help="Override max fork reuse count before eviction")
    p_create.add_argument("--ttl-minutes", type=int, default=None, help="Override TTL in minutes before eviction")
    p_create.set_defaults(func=cmd_create)

    p_fork = sub.add_parser("fork", help="Fork shared context snapshot(s) into a bounded Subagent execution packet")
    p_fork.add_argument("--workspace", default=".", help="Workspace root")
    p_fork.add_argument("--subagent", required=True, help="Subagent identifier (e.g., 'Subagent_A', 'Subagent_B')")
    p_fork.add_argument(
        "--snapshots",
        "--id",
        dest="snapshots",
        nargs="+",
        required=True,
        help="Snapshot ID(s) to fork into this subagent",
    )
    p_fork.add_argument(
        "--task",
        "--tasks",
        dest="task",
        nargs="+",
        required=True,
        help="Bounded task description for this subagent",
    )
    p_fork.add_argument(
        "--task-type",
        default="REAL_RD",
        choices=["REAL_RD", "TRIVIAL_BATCH", "real_rd", "trivial_batch"],
        help="REAL_RD (strictly 1 task) or TRIVIAL_BATCH (small CSS/icon/text tweaks allowed together)",
    )
    p_fork.add_argument(
        "--platform",
        default="auto",
        choices=list(SUPPORTED_PLATFORMS),
        help="Target agent platform (`auto`, `opencode`, `claude`, `agy`)",
    )
    p_fork.add_argument(
        "--base-session",
        "--session-id",
        dest="base_session",
        default=None,
        help="Optional native session ID override for `--fork`",
    )
    p_fork.add_argument("--model", default=None, help="Optional model name for opencode dispatch command")
    p_fork.add_argument("--parallel", action="store_true", help="Allow parallel forks (default enforces 1-concurrency baton pass)")
    p_fork.add_argument("--allow-multi-step", action="store_true", help="Allow numbered sub-steps within a single atomic goal")
    p_fork.set_defaults(func=cmd_fork)

    p_ret = sub.add_parser("return-baton", help="Return execution baton & report from Subagent back to Main Orchestrator")
    p_ret.add_argument("--workspace", default=".", help="Workspace root")
    p_ret.add_argument("--subagent", required=True, help="Subagent returning the baton")
    p_ret.add_argument(
        "--report-file",
        "--report",
        dest="report_file",
        default=None,
        help="Path to subagent report markdown file",
    )
    p_ret.add_argument("--summary", default=None, help="Inline report summary if report file was not written directly")
    p_ret.add_argument("--status", default="COMPLETED", help="Optional completion status tag (e.g., COMPLETED)")
    p_ret.set_defaults(func=cmd_return_baton)

    p_evict = sub.add_parser("evict", help="Throw away (evict) a specific snapshot or auto-garbage-collect stale snapshots")
    p_evict.add_argument("--workspace", default=".", help="Workspace root")
    p_evict.add_argument("--id", default=None, help="Snapshot ID to throw away")
    p_evict.add_argument("--reason", default="MANUAL_EVICTION", help="Why this snapshot is being thrown away")
    p_evict.add_argument(
        "--auto-gc",
        action="store_true",
        help="Automatically throw away all hash-drifted, expired, or exhausted snapshots",
    )
    p_evict.set_defaults(func=cmd_evict)

    p_status = sub.add_parser("status", help="Show active snapshots, fork reuse counts, staleness, and baton state")
    p_status.add_argument("--workspace", default=".", help="Workspace root")
    p_status.set_defaults(func=cmd_status)

    p_handoff = sub.add_parser(
        "handoff",
        help="Write a portable cross-harness handoff document with RA artifact pointers and suggested skills",
    )
    p_handoff.add_argument("--workspace", default=".", help="Workspace root")
    p_handoff.add_argument("--summary", required=True, help="Summary of the current conversation and decisions")
    p_handoff.add_argument("--focus", default="", help="What the next session will focus on")
    p_handoff.add_argument("--suggested-skills", nargs="*", default=[], help="Skills the next agent should invoke")
    p_handoff.add_argument("--output", default=None, help="Optional custom output path (defaults to OS temp dir)")
    p_handoff.set_defaults(func=cmd_handoff)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
