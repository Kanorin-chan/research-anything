#!/usr/bin/env python3
"""
ra_context_harness.py — Subagent Context Controller, `/fork` Snapshot Manager & Eviction Harness.

Enforces RA's Lead-Orchestrator & Context-Control Protocol:
1. Main Agent = Lead Orchestrator / Compiler (delegates execution to Subagents even at 1-concurrency baton-pass).
2. Read Once -> Fork Many (`/fork` style):
   Compile a shared context snapshot once (`BASE_FRAMEWORK` or `WORKFLOW_SLICE`) and fork it to
   `Subagent_A`, `Subagent_B`, etc., so subagents do not re-read the whole codebase from scratch.
3. 3-Tier Snapshot Lifecycle & Automatic Eviction (Throw-Away Rules):
   - Tier 1 (`BASE_FRAMEWORK`): Framework/domain knowledge, `INVARIANTS.md`, crawled skills.
     Kept across the track; thrown away only if invariants/framework files change.
   - Tier 2 (`WORKFLOW_SLICE`): Subsystem workflow subgraph (`-N` to `+N` hops), `PROTECTED_WORKING`
     nodes, `BC-xxx` contracts, and exact source file SHA-256 hashes.
     Forked across sibling subagents; thrown away immediately on `HASH_DRIFT` (any tracked file edited),
     `MAX_REUSE_EXCEEDED`, or `TTL_EXPIRED`.
   - Tier 3 (`TASK_EPHEMERAL`): Single-task delta for 1 subagent (`max_reuses = 1`).
     Thrown away immediately upon task completion or subagent failure/drift.
4. Task-Sizing Gate:
   - `REAL_RD` tasks (logic, state flow, bug fix, hypothesis prototype, break-test): Strictly 1 task per subagent.
   - `TRIVIAL_BATCH` tasks (CSS, icons, labels, formatting): Batching allowed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

TIER_DEFAULTS = {
    "BASE_FRAMEWORK": {"max_reuses": 25, "ttl_minutes": 1440},
    "WORKFLOW_SLICE": {"max_reuses": 6, "ttl_minutes": 180},
    "TASK_EPHEMERAL": {"max_reuses": 1, "ttl_minutes": 30},
}


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


def get_snapshots_dir(workspace: Path) -> Path:
    d = workspace / "research" / "context_snapshots"
    (d / "forks").mkdir(parents=True, exist_ok=True)
    (d / "evicted").mkdir(parents=True, exist_ok=True)
    return d


def get_registry_path(workspace: Path) -> Path:
    return get_snapshots_dir(workspace) / "SNAPSHOT_REGISTRY.json"


def load_registry(workspace: Path) -> Dict[str, Any]:
    rp = get_registry_path(workspace)
    if not rp.exists():
        return {"snapshots": {}, "evicted_history": [], "active_baton": "MAIN_ORCHESTRATOR"}
    try:
        return json.loads(rp.read_text(encoding="utf-8"))
    except Exception:
        return {"snapshots": {}, "evicted_history": [], "active_baton": "MAIN_ORCHESTRATOR"}


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
    file_excerpts: List[str] = []
    for fstr in args.files or []:
        fpath = (workspace / fstr).resolve()
        if not fpath.exists() or not fpath.is_file():
            print(f"[RA CONTEXT HARNESS] WARNING: File not found: {fstr}", file=sys.stderr)
            continue
        rel = fpath.relative_to(workspace).as_posix()
        digest = sha256_file(fpath)
        tracked_files[rel] = digest

    snap_md_path = sdir / f"{snap_id}.md"
    md_content = (
        f"# Context Snapshot `{snap_id}` (`{tier}`)\n\n"
        f"- **Created Timestamp**: `{ts}`\n"
        f"- **Tier**: `{tier}`\n"
        f"- **Reuse Budget**: `0 / {max_reuses}` forks\n"
        f"- **TTL**: `{ttl_minutes}` minutes\n"
        f"- **Tracked Files ({len(tracked_files)})**: {', '.join(f'`{k}` (`{v[:10]}...`)' for k, v in tracked_files.items()) or 'None'}\n\n"
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

    subagent_name = slugify(args.subagent)
    task_type = args.task_type.upper()
    task_desc = args.task.strip()

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

        # Increment reuse counter and log fork lineage
        snap["reuse_count"] = snap.get("reuse_count", 0) + 1
        snap.setdefault("forked_to", []).append(
            {"subagent": subagent_name, "forked_at": now_iso(), "task_type": task_type}
        )
        snap_file = workspace / snap["file"]
        if snap_file.exists():
            compiled_sections.append(snap_file.read_text(encoding="utf-8"))

        # If this was a 1-shot TASK_EPHEMERAL snapshot, mark it consumed after this fork
        if snap.get("tier") == "TASK_EPHEMERAL" and snap["reuse_count"] >= snap.get("max_reuses", 1):
            evict_snapshot_internal(workspace, reg, sid, "TASK_EPHEMERAL_CONSUMED_BY_FORK")

    # Record 1-Concurrency Baton Pass to the Subagent
    reg["active_baton"] = f"SUBAGENT:{subagent_name}"
    save_registry(workspace, reg)

    fork_file = sdir / "forks" / f"FORK_{subagent_name}.md"
    fork_packet = (
        f"# Forked Subagent Execution Brief — `{subagent_name}`\n\n"
        f"- **Forked Timestamp**: `{now_iso()}`\n"
        f"- **Concurrency / Baton Mode**: `1-CONCURRENCY BATON PASS` (Main Agent is IDLE waiting for your report; complete ONLY this task, write your report, and return baton to Main Agent)\n"
        f"- **Task Classification**: `{task_type}`\n"
        f"- **Inherited Context Snapshots**: {', '.join(f'`{s}`' for s in requested_ids)}\n\n"
        f"---\n\n"
        f"## 1. Your Bounded Task Assignment\n"
        f"{task_desc}\n\n"
        f"> **Strict Subagent Boundary Rules**:\n"
        f"> 1. Do NOT re-read the entire codebase from scratch — rely on the Inherited Context Snapshots below and inspect only the exact target lines you need.\n"
        f"> 2. Do NOT touch any file or function marked `PROTECTED_WORKING` (`Symptom != Culprit`).\n"
        f"> 3. Do NOT perform unrequested extra tasks. When finished, write a concise evidence-backed report and stop immediately so the Main Agent can verify your work.\n\n"
        f"---\n\n"
        f"## 2. Inherited Context Snapshots (`/fork` Shared State)\n\n"
        + "\n\n---\n\n".join(compiled_sections)
    )
    fork_file.write_text(fork_packet, encoding="utf-8")

    print("=" * 78)
    print(f"  RA CONTEXT FORK READY -> SUBAGENT: `{subagent_name}`")
    print("=" * 78)
    print(f"  Forked Brief File   : {fork_file.relative_to(workspace).as_posix()}")
    print(f"  Inherited Snapshots : {', '.join(requested_ids)}")
    print(f"  Task Classification : {task_type}")
    print(f"  Active Execution    : BATON PASSED TO `{subagent_name}` (Main Agent waits for report)")
    print("=" * 78)


def cmd_return_baton(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    reg = load_registry(workspace)
    subagent_name = slugify(args.subagent)
    reg["active_baton"] = "MAIN_ORCHESTRATOR"
    save_registry(workspace, reg)

    print("=" * 78)
    print(f"  RA BATON RETURNED: `{subagent_name}` -> `MAIN_ORCHESTRATOR`")
    print("=" * 78)
    print("  ZERO-TRUST SUBAGENT SUPERVISION CHECKLIST FOR MAIN AGENT:")
    print("    1. Assume the subagent may have drifted or missed a constraint — DO NOT trust its word alone.")
    print("    2. Run `python research/harness/project_harness.py check-all` (if forged) or `ra_cheese_audit.py`.")
    print("    3. Run `ra_context_harness.py status` to auto-evict any snapshots whose tracked files changed.")
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
    print(f"  Active Execution Baton : {reg.get('active_baton', 'MAIN_ORCHESTRATOR')}")
    print(f"  Active Snapshots       : {len(snaps)}")
    print(f"  Evicted (Thrown Away)  : {len(evicted_hist)}")
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA Subagent Context Controller & `/fork` Snapshot Harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create a shared context snapshot (`BASE_FRAMEWORK`, `WORKFLOW_SLICE`, `TASK_EPHEMERAL`)")
    p_create.add_argument("--workspace", default=".", help="Workspace root")
    p_create.add_argument("--id", required=True, help="Snapshot ID (e.g., 'laravel_base' or 'auth_flow_slice')")
    p_create.add_argument(
        "--tier",
        required=True,
        choices=["BASE_FRAMEWORK", "WORKFLOW_SLICE", "TASK_EPHEMERAL", "base_framework", "workflow_slice", "task_ephemeral"],
        help="Snapshot lifecycle tier",
    )
    p_create.add_argument("--summary", required=True, help="Compiled context summary text so subagents skip re-reading")
    p_create.add_argument("--files", nargs="*", default=[], help="Source files summarized by this snapshot (tracked via SHA-256)")
    p_create.add_argument("--max-reuses", type=int, default=None, help="Override max fork reuse count before eviction")
    p_create.add_argument("--ttl-minutes", type=int, default=None, help="Override TTL in minutes before eviction")
    p_create.set_defaults(func=cmd_create)

    p_fork = sub.add_parser("fork", help="Fork shared context snapshot(s) into a bounded Subagent execution packet")
    p_fork.add_argument("--workspace", default=".", help="Workspace root")
    p_fork.add_argument("--subagent", required=True, help="Subagent identifier (e.g., 'Subagent_A', 'Subagent_B')")
    p_fork.add_argument("--snapshots", nargs="+", required=True, help="Snapshot IDs to fork into this subagent")
    p_fork.add_argument("--task", required=True, help="Bounded task description for this subagent")
    p_fork.add_argument(
        "--task-type",
        default="REAL_RD",
        choices=["REAL_RD", "TRIVIAL_BATCH", "real_rd", "trivial_batch"],
        help="REAL_RD (strictly 1 task) or TRIVIAL_BATCH (small CSS/icon/text tweaks allowed together)",
    )
    p_fork.add_argument("--allow-multi-step", action="store_true", help="Allow numbered sub-steps within a single atomic goal")
    p_fork.set_defaults(func=cmd_fork)

    p_ret = sub.add_parser("return-baton", help="Return execution baton from Subagent back to Main Orchestrator")
    p_ret.add_argument("--workspace", default=".", help="Workspace root")
    p_ret.add_argument("--subagent", required=True, help="Subagent returning the baton")
    p_ret.set_defaults(func=cmd_return_baton)

    p_evict = sub.add_parser("evict", help="Throw away (evict) a specific snapshot or auto-garbage-collect stale snapshots")
    p_evict.add_argument("--workspace", default=".", help="Workspace root")
    p_evict.add_argument("--id", default=None, help="Snapshot ID to throw away")
    p_evict.add_argument("--reason", default="MANUAL_EVICTION", help="Why this snapshot is being thrown away")
    p_evict.add_argument("--auto-gc", action="store_true", help="Automatically throw away all hash-drifted, expired, or exhausted snapshots")
    p_evict.set_defaults(func=cmd_evict)

    p_status = sub.add_parser("status", help="Show active snapshots, fork reuse counts, staleness, and baton state")
    p_status.add_argument("--workspace", default=".", help="Workspace root")
    p_status.set_defaults(func=cmd_status)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
