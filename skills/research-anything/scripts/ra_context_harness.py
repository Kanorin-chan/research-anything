#!/usr/bin/env python3
"""
ra_context_harness.py — Multi-Platform Subagent Context Controller, `/fork` Manager & Eviction Harness.

Supported harnesses: OpenCode, Claude Code, Codex, Antigravity/Gemini.
Dispatch with your own harness's native sub-agent tool; other harnesses or CLI forms need
`ra_gate.py allow-agent` with the user's words.

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
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TIER_DEFAULTS = {
    "BASE_FRAMEWORK": {"max_reuses": 25, "ttl_minutes": 1440},
    "WORKFLOW_SLICE": {"max_reuses": 6, "ttl_minutes": 180},
    "TASK_EPHEMERAL": {"max_reuses": 1, "ttl_minutes": 30},
}

SUPPORTED_PLATFORMS = ("auto", "opencode", "claude", "codex", "agy")

# Each harness exports its own current session id; never cross-feed one platform's id to another.
SESSION_ENV_VARS = {
    "opencode": "OPENCODE_SESSION_ID",
    "claude": "CLAUDE_CODE_SESSION_ID",
    "codex": "CODEX_SESSION_ID",
}

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

RELAY_STATUSES = ("COMPLETED", "FAILED", "PARTIAL", "ABORTED")


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {text!r}")
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be greater than 0 (got {value})")
    return value


def resolve_inside(workspace: Path, raw: str) -> Optional[Path]:
    """Resolve `raw` against the workspace; None if it lands outside it."""
    p = (workspace / raw).resolve()
    return p if p.is_relative_to(workspace) else None


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


# ra_common names harnesses "claude-code"; the dispatch builders here say "claude". Mapped only here.
_PLATFORM_OF = {"opencode": "opencode", "claude-code": "claude", "codex": "codex", "agy": "agy"}
_HARNESS_OF = {v: k for k, v in _PLATFORM_OF.items()}
_DISPATCH_LABEL = {"opencode": "opencode", "claude": "claude-code", "codex": "codex", "agy": "agy/gemini"}


def current_platform() -> str:
    """The harness running this script, read from env only; 'unknown' when none is detected."""
    common = lab()
    harness = common.resolve_identity()["harness"] if common is not None else "unknown"
    return _PLATFORM_OF.get(harness, "unknown")


def detect_platform(requested: str = "auto") -> str:
    """An explicit platform name as given, else the current harness. Never looks at PATH."""
    req = requested.lower()
    if req in _PLATFORM_OF.values():
        return req
    return current_platform()


def emit(text: str, stream: Any = None) -> None:
    """UTF-8 out even on a cp932 console."""
    stream = stream or sys.stdout
    stream.flush()
    stream.buffer.write((text.rstrip("\n") + "\n").encode("utf-8", "replace"))
    stream.buffer.flush()


def lab() -> Any:
    """ra_common beside this script (the lab board), or None if it is missing."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import ra_common
    except ImportError:
        return None
    return ra_common


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
        "outstanding_forks": {},
        "session_owners": {},
        "last_gc_at": None,
    }
    if not rp.exists():
        return default_reg
    try:
        loaded = json.loads(rp.read_text(encoding="utf-8"))
        for k, v in default_reg.items():
            loaded.setdefault(k, v)
        baton = str(loaded.get("active_baton", "MAIN_ORCHESTRATOR"))
        # Registries written before `outstanding_forks` existed only know the baton holder.
        if baton.startswith("SUBAGENT:") and not loaded["outstanding_forks"]:
            loaded["outstanding_forks"][baton.split(":", 1)[1]] = {"forked_at": None, "legacy": True}
        return loaded
    except (OSError, ValueError) as exc:
        # Silently resetting would erase fork/relay counts the gate relies on.
        print(f"[RA CONTEXT] ERROR: cannot read {rp} ({exc}). Fix or restore it; refusing to reset.", file=sys.stderr)
        sys.exit(1)


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


def path_key(p: Any) -> str:
    return os.path.normcase(os.path.realpath(str(p)))


def claude_project_dirs(workspace: Path) -> List[Path]:
    """Exact `~/.claude/projects/<encoded cwd>` folders for this workspace (short and long path forms)."""
    root = Path.home() / ".claude" / "projects"
    forms = {os.path.abspath(str(workspace)), os.path.realpath(str(workspace))}
    # Claude Code replaces every non-alphanumeric char of the cwd with "-" (`F:\AI_Kazeto V2` -> `F--AI-Kazeto-V2`).
    names = sorted({re.sub(r"[^a-zA-Z0-9]", "-", f) for f in forms})
    return [root / n for n in names if (root / n).is_dir()]


def auto_discover_native_session_id(workspace: Path, platform: str) -> Optional[str]:
    """
    Find the session to fork for `platform` when `--base-session` is not given.
    Returns None unless the session is provably this workspace's, so the caller falls back
    to a fresh subagent instead of loading some other conversation.
    """
    env_val = os.environ.get(SESSION_ENV_VARS.get(platform, ""), "").strip()
    ws_key = path_key(workspace)

    if platform == "claude":
        dirs = claude_project_dirs(workspace)
        if env_val:
            # `claude --resume` only finds sessions stored under the cwd's project folder.
            return env_val if any((d / f"{env_val}.jsonl").is_file() for d in dirs) else None
        sessions = [f for d in dirs for f in d.glob("*.jsonl") if f.is_file()]
        # Concurrent sessions share a folder; "newest file" may be someone else's conversation.
        return sessions[0].stem if len(sessions) == 1 else None

    if env_val:
        return env_val

    if platform == "opencode":
        return None  # OPENCODE_SESSION_ID or nothing: no PATH lookup, no `opencode session list`

    if platform == "codex":
        root = Path.home() / ".codex" / "sessions"
        if not root.is_dir():
            return None
        rollouts = sorted(root.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in rollouts:
            try:
                with f.open(encoding="utf-8", errors="replace") as h:
                    meta = json.loads(h.readline())
            except (OSError, ValueError):
                continue
            payload = meta.get("payload") if isinstance(meta, dict) else None
            if not isinstance(payload, dict) or meta.get("type") != "session_meta":
                continue
            if isinstance(payload.get("source"), dict):
                continue  # dict source = a sub-agent thread spawned inside another session
            if payload.get("cwd") and path_key(payload["cwd"]) == ws_key:
                m = UUID_RE.search(str(payload.get("id", ""))) or UUID_RE.search(f.stem)
                if m:
                    return m.group(0)
        return None

    return None


def build_platform_fork_instructions(
    platform: str,
    subagent_name: str,
    rel_fork_file: str,
    rel_report_file: str,
    base_session_id: Optional[str],
    model: Optional[str],
    workspace: Optional[Path] = None,
    discover_session: bool = True,
) -> Dict[str, str]:
    """Generate exact context-forking commands/calls for OpenCode, Claude Code, Codex, and Antigravity/Gemini."""
    oc_model_flag = f'--model "{model}" ' if model else ""
    codex_model_flag = f'-m "{model}" ' if model else ""

    # A session id only means something to the platform that owns it; other platforms get a fresh subagent.
    session = base_session_id or (auto_discover_native_session_id(workspace, platform) if workspace and discover_session else None)
    oc_session = session if platform == "opencode" else None
    claude_session = session if platform == "claude" else None
    codex_session = session if platform == "codex" else None

    if oc_session:
        opencode_cmd = (
            f'opencode run --session "{oc_session}" --fork --title "{subagent_name}" '
            f'{oc_model_flag}--auto -f "{rel_fork_file}" '
            f'"Execute the bounded task in {rel_fork_file} and write your findings to {rel_report_file}."'
        )
    else:
        opencode_cmd = (
            f'opencode run --title "{subagent_name}" {oc_model_flag}--auto -f "{rel_fork_file}" '
            f'"Execute the bounded task in {rel_fork_file} and write your findings to {rel_report_file}."'
        )

    if claude_session:
        claude_cmd = (
            f'claude --resume "{claude_session}" --fork-session --permission-mode acceptEdits '
            f'-p "Read {rel_fork_file}, execute ONLY the bounded task, and write your report to {rel_report_file}."'
        )
    else:
        claude_cmd = (
            f'Agent(subagent_type="general-purpose", description="{subagent_name}", '
            f'prompt="Read {rel_fork_file} (KV-cache prefix-aligned snapshot). Do NOT re-read already-summarized files. '
            f'Execute ONLY the bounded task and write your report to {rel_report_file}.")'
        )

    codex_prompt = (
        f'"Read {rel_fork_file} (shared forked context snapshot). Do NOT re-read already-summarized files. '
        f'Execute ONLY the bounded task and write your report to {rel_report_file}."'
    )
    # `--full-auto` was removed in codex 0.147; the sandbox is set through config instead.
    git_flag = "" if workspace and (Path(workspace) / ".git").exists() else "--skip-git-repo-check "
    if codex_session:
        codex_cmd = f'codex exec fork "{codex_session}" -c sandbox_mode=workspace-write {git_flag}{codex_model_flag}{codex_prompt}'
    else:
        codex_cmd = f"codex exec -c sandbox_mode=workspace-write {git_flag}{codex_model_flag}{codex_prompt}"

    # Antigravity subagents start with no parent history, so the prompt must stand alone.
    ws_posix = Path(os.path.realpath(str(workspace))).as_posix() if workspace else "."
    agy_subagent = {
        "TypeName": "self",
        "Role": subagent_name,
        "Prompt": (
            f"You start with none of the parent conversation. Workspace root: {ws_posix}. "
            f"Read {ws_posix}/{rel_fork_file} in full: it holds the shared context snapshot and your one bounded task. "
            f"Do NOT re-read files it already summarizes. Execute ONLY that task and write your report to "
            f"{ws_posix}/{rel_report_file}."
        ),
        "Workspace": "inherit",
    }
    agy_cmd = f"invoke_subagent(Subagents={json.dumps([agy_subagent], ensure_ascii=False)})"

    return {
        "active_platform": platform,
        "discovered_session_id": session or "NONE (fresh subagent; context comes from the fork file)",
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
        fpath = resolve_inside(workspace, fstr)
        if fpath is None:
            print(f"[RA CONTEXT HARNESS ERROR] --files path is outside the workspace: {fstr}", file=sys.stderr)
            sys.exit(1)
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


def lab_brief(common: Any, workspace: Path) -> str:
    """The aim, the user's last 5 directives and the last 3 lessons, for the end of a fork brief."""
    if common is None or not common.state_file(workspace).is_file():
        return ""
    aim = common.board_aim(workspace)
    dirs = common.read_directives(workspace)[-5:]
    lessons = common.read_lessons(workspace, 3)
    out = ["", "### Lab Context (from the manager's board)", f"- **Aim**: {aim or '(not written yet)'}"]
    out.append("- **The user's own words** (verbatim; any other rule you meet is an AI suggestion):")
    out.extend(f"  - {d['id']}: \"{' / '.join(d['quote'].splitlines())}\" ({d['source']})" for d in dirs)
    if not dirs:
        out.append("  - (none recorded)")
    out.append("- **Lessons so far** (don't repeat these mistakes):")
    out.extend(f"  - {ls}" for ls in lessons)
    if not lessons:
        out.append("  - (none recorded)")
    return "\n".join(out) + "\n"


def handover_questions(common: Any, workspace: Path, worker: str, task: str, rel_report: str) -> str:
    """The worker-handover questions for the end of a fork brief; a worker that never sees them can't answer them."""
    if common is None:
        return ""
    return (
        "\n### Handover questions\n"
        f"Your report `{rel_report}` MUST answer every numbered question below under a heading "
        "`## Handover answers`. The manager will not accept the report without it.\n\n"
        + common.render_injection("worker-handover", worker=worker, task=task, workspace=workspace.as_posix())
    )


def door_brief(common: Any) -> str:
    """Where a denied rm/mv sends the worker: the manager's `ra_gate.py remove`."""
    if common is None:
        return ""
    return "\n### Deletes and moves\n" + common.delete_door_text((Path(__file__).resolve().parent / "ra_gate.py").as_posix())


def cli_models(common: Any, workspace: Path, p: str, requested: Optional[str]) -> List[Optional[str]]:
    """Models to print a granted CLI line for on platform p: [] = none; None = no -m (a harness-wide grant)."""
    if common is None or p not in _HARNESS_OF:
        return []
    harness = _HARNESS_OF[p]
    if requested:
        return [requested] if common.is_agent_allowed(workspace, f"{harness}:{requested}", own_harness="") else []
    grants = common.harness_grant_models(workspace, harness)
    return [None] if "" in grants else list(grants)


def worker_cli_lines(label: str, name: str, cmd: str) -> List[str]:
    """A CLI worker has no parent session, so RA_WORKER marks it; set for this one command only."""
    if cmd.split(" ", 1)[0] not in ("opencode", "claude", "codex"):
        return [f"    [{label:<12}] CLI (granted): {cmd}"]
    return [f"    [{label:<12}] CLI (granted), bash      : RA_WORKER={name} {cmd}",
            f"    [{label:<12}] CLI (granted), PowerShell: $env:RA_WORKER='{name}'; try {{ {cmd} }} "
            "finally { $env:RA_WORKER=$null }"]


def native_dispatch(p: str, rel_fork: str, rel_report: str, name: str) -> str:
    """How to dispatch with this harness's own sub-agent tool (no CLI, so no grant is involved)."""
    prompt = f"Read {rel_fork}, execute ONLY the bounded task, and write your report to {rel_report}."
    if p == "claude":
        return f'Agent tool (subagent_type="general-purpose", description="{name}"), prompt: "{prompt}"'
    if p == "opencode":
        return f'`subagent` tool with agent="general", description="{name}", prompt="{prompt}"'
    return "use your harness's own subagent tool; point it at the brief file above."


def cmd_fork(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    sdir = get_snapshots_dir(workspace)
    reg = load_registry(workspace)
    snaps = reg.get("snapshots", {})

    common = lab()
    ident = common.resolve_identity() if common is not None else {"agent": "unknown", "harness": "unknown", "session": ""}
    own = current_platform()
    platform = detect_platform(args.platform)
    if platform != own and not cli_models(common, workspace, platform, args.model):
        grants = common.harness_grant_models(workspace, _HARNESS_OF.get(platform, platform)) if common else []
        why = (f"is granted only for model(s) {', '.join(grants)}, not `--model {args.model}`" if grants and args.model
               else "needs the user's written grant; none is recorded")
        emit(f"[RA CONTEXT HARNESS BLOCKED] `--platform {platform}` {why}.\n"
             "  Ask the user. Then: ra_gate.py allow-agent --agent <harness:model> --quote \"<their exact words>\" --source \"...\"\n",
             sys.stderr)
        if common is not None:
            emit(common.render_injection("before-other-agent", agent=platform, identity=ident["agent"]), sys.stderr)
        sys.exit(1)

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

    pending = common.review_pending(workspace) if common is not None else []
    if pending:
        n = len(common.lab_reviews(workspace)) + 1
        print(
            f"[RA CONTEXT HARNESS BLOCKED] review worker {', '.join(pending)} first: "
            f"ra_gate.py review --file research/reviews/REVIEW_{n}.md\n"
            "  The manager reviews every finished report (DECISION / LESSON / NEXT) before delegating more work.",
            file=sys.stderr,
        )
        sys.exit(2)

    subagent_name = slugify(args.subagent)
    outstanding = reg["outstanding_forks"]
    if subagent_name in outstanding:
        print(
            f"[RA CONTEXT HARNESS BLOCKED] `{subagent_name}` already holds an outstanding fork.\n"
            f"  Run `ra_context_harness.py return-baton --subagent {subagent_name}` first, or use another name.",
            file=sys.stderr,
        )
        sys.exit(1)
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

    requested_ids = list(dict.fromkeys(slugify(sid) for sid in args.snapshots))

    # Validate every snapshot before charging any, so an aborted fork leaves the registry untouched.
    missing = [sid for sid in requested_ids if sid not in snaps]
    if missing:
        print(
            f"[RA CONTEXT HARNESS ERROR] Snapshot(s) not found (or already evicted): {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)
    stale: List[Tuple[str, str]] = []
    for sid in requested_ids:
        healthy, reasons = evaluate_snapshot_health(workspace, snaps[sid])
        if not healthy:
            stale.append((sid, ", ".join(reasons)))
    if stale:
        for sid, reason_str in stale:
            evict_snapshot_internal(workspace, reg, sid, reason_str)
            print(
                f"[RA CONTEXT HARNESS AUTO-EVICTED] Snapshot `{sid}` is stale/invalid ({reason_str}) and was "
                f"THROWN AWAY!",
                file=sys.stderr,
            )
        save_registry(workspace, reg)
        print(f"  Nothing was forked. Rebuild fresh snapshot(s) before forking to `{subagent_name}`.", file=sys.stderr)
        sys.exit(1)

    base_session_id: Optional[str] = args.base_session or next(
        (snaps[sid]["base_session_id"] for sid in requested_ids if snaps[sid].get("base_session_id")), None
    )
    # A session that is not the manager's own belongs to the worker that ran in it (the 2026-11-11 Qwen case).
    owners = reg["session_owners"]
    if base_session_id and base_session_id != ident["session"]:
        owner = owners.get(base_session_id)
        if owner and owner != subagent_name:
            emit(
                f"[RA CONTEXT HARNESS BLOCKED] Session `{base_session_id}` already belongs to worker `{owner}`.\n"
                f"  `{subagent_name}` is a different worker: one fresh worker per task. Drop --base-session, or fork "
                f"from your own session.",
                sys.stderr,
            )
            sys.exit(1)
    compiled_sections: List[str] = []
    for sid in requested_ids:
        snap_file = workspace / snaps[sid]["file"]
        if snap_file.exists():
            compiled_sections.append(snap_file.read_text(encoding="utf-8"))

    fork_file = sdir / "forks" / f"FORK_{subagent_name}.md"
    report_file = sdir / "reports" / f"REPORT_{subagent_name}.md"
    rel_fork = fork_file.relative_to(workspace).as_posix()
    rel_report = report_file.relative_to(workspace).as_posix()

    # Unresolved form keeps a short (8.3) cwd, which Claude Code may have used for its project folder.
    # Dispatch lines: this harness, plus any the user granted. Nothing else is printed.
    shown = [p for p in dict.fromkeys([own, platform] + [_PLATFORM_OF[h] for h in (common.granted_harnesses(workspace) if common else [])])
             if p in _HARNESS_OF]
    # Granted CLI lines carry the granted model's -m: a bare launch runs the default model, which nobody granted.
    cli_lines = [
        (p, build_platform_fork_instructions(
            p, subagent_name, rel_fork, rel_report, base_session_id, model,
            workspace=Path(os.path.abspath(args.workspace)), discover_session=(p == platform),
        )[p])
        for p in shown for model in cli_models(common, workspace, p, args.model)
    ]

    # IMPORTANT HARDWARE KV-CACHE PREFIX OPTIMIZATION:
    # Section 1 (Token 0..N) MUST be 100% byte-identical across Subagent_A, Subagent_B, etc.
    # so that llama.cpp (`--cache-reuse`), OpenAI Prefix Caching, Anthropic Prompt Caching,
    # and Gemini Context Caching reuse the pre-computed GPU KV-cache without recomputation.
    # All dynamic per-subagent fields (subagent_name, timestamp, task_desc) go in Section 2 at the suffix!
    fork_packet = (
        "# RA SHARED CONTEXT SNAPSHOT PREFIX (IMMUTABLE KV-CACHE PREFIX)\n\n"
        "> **Strict Subagent Context-Control Rules**:\n"
        "> 1. **Do NOT re-read files already summarized in Section 1** — this context was forked to you so you do not waste tokens re-discovering the project.\n"
        "> 2. **Do NOT touch any `PROTECTED_WORKING` function (`Symptom != Culprit`)**.\n"
        "> 3. **Execute ONLY your bounded task in Section 2 and write your report to the required output path.**\n\n"
        "## 1. Inherited Context Snapshots (`/fork` Shared State — Byte-Identical Prefix)\n\n"
        + "\n\n---\n\n".join(compiled_sections)
        + "\n\n---\n\n"
        f"## 2. Ephemeral Subagent Task Suffix — `{subagent_name}`\n\n"
        f"- **Subagent Identifier**: `{subagent_name}`\n"
        f"- **Forked Timestamp**: `{now_iso()}`\n"
        f"- **Target Platform**: `{platform}`\n"
        f"- **Concurrency / Baton Mode**: `1-CONCURRENCY BATON PASS` (Main Agent is IDLE waiting for your report)\n"
        f"- **Task Classification**: `{task_type}`\n"
        f"- **Inherited Context Snapshots**: {', '.join(f'`{s}`' for s in requested_ids)}\n"
        f"- **Required Report Output Path**: `{rel_report}`\n\n"
        f"### Bounded Task Assignment\n"
        f"{task_desc}\n"
        + door_brief(common)
        + lab_brief(common, workspace)
        + handover_questions(common, workspace, subagent_name, task_desc, rel_report)
    )
    fork_file.write_text(fork_packet, encoding="utf-8")

    forked_at = now_iso()
    for sid in requested_ids:
        snap = snaps[sid]
        snap["reuse_count"] = snap.get("reuse_count", 0) + 1
        snap.setdefault("forked_to", []).append(
            {"subagent": subagent_name, "forked_at": forked_at, "task_type": task_type, "platform": platform}
        )
        if snap.get("tier") == "TASK_EPHEMERAL" and snap["reuse_count"] >= snap.get("max_reuses", 1):
            evict_snapshot_internal(workspace, reg, sid, "TASK_EPHEMERAL_CONSUMED_BY_FORK")

    outstanding[subagent_name] = {
        "forked_at": forked_at,
        "snapshots": requested_ids,
        "platform": platform,
        "task_type": task_type,
        "task": task_desc[:300],
    }
    if base_session_id and base_session_id != ident["session"]:
        owners[base_session_id] = subagent_name
    reg["active_baton"] = f"SUBAGENT:{subagent_name}"
    reg["total_forks_dispatched"] = reg.get("total_forks_dispatched", 0) + 1
    save_registry(workspace, reg)

    print("=" * 78)
    print(f"  RA CONTEXT FORK READY -> SUBAGENT: `{subagent_name}` (PLATFORM: {platform.upper()})")
    print("=" * 78)
    print(f"  Forked Brief File   : {rel_fork} (Token 0..N Prefix-Cache Aligned)")
    print(f"  Subagent Report Out : {rel_report}")
    # No session id here: a native sub-agent tool would reuse it (the 2026-11-11 case); granted CLI lines carry their own.
    print("  Worker Session      : fresh (the brief file carries the context)")
    print(f"  Inherited Snapshots : {', '.join(requested_ids)}")
    print(f"  Task Classification : {task_type}")
    print(f"  Active Execution    : BATON PASSED TO `{subagent_name}` (Main Agent waits for report)")
    print("-" * 78)
    print("  SUBAGENT DISPATCH (native tool on your own model; CLI forms only for agents the user granted):")
    if own == "unknown":
        print("    [native]      : use your harness's own subagent tool; point it at the brief file above.")
    if own in shown:
        print(f"    [{_DISPATCH_LABEL[own]:<12}]: {native_dispatch(own, rel_fork, rel_report, subagent_name)}")
    for p, cmd in cli_lines:
        for line in worker_cli_lines(_DISPATCH_LABEL[p], subagent_name, cmd):
            emit(line)
    print("-" * 78)
    print(
        f"  WHEN `{subagent_name}` FINISHES: Run `ra_context_harness.py return-baton --subagent {subagent_name} "
        f"--status COMPLETED --report-file {rel_report}` (or --status FAILED)"
    )
    print("=" * 78)
    if common is not None:
        emit(common.render_injection("worker-dispatch", task=task_desc, worker=subagent_name, identity=ident["agent"]))
    footer = common.render_board(workspace, "summary") if common is not None else ""
    if footer:
        print(footer)


def cmd_return_baton(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    sdir = get_snapshots_dir(workspace)
    reg = load_registry(workspace)
    subagent_name = slugify(args.subagent)
    status = args.status
    outstanding = reg["outstanding_forks"]

    if subagent_name not in outstanding:
        holders = ", ".join(f"`{n}`" for n in outstanding) or "none"
        print(
            f"[RA CONTEXT HARNESS BLOCKED] `{subagent_name}` holds no outstanding fork, so it has no baton to return.\n"
            f"  Outstanding forks: {holders}.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.report_file:
        report_path = resolve_inside(workspace, args.report_file)
        if report_path is None:
            print(f"[RA CONTEXT HARNESS ERROR] --report-file is outside the workspace: {args.report_file}", file=sys.stderr)
            sys.exit(1)
    else:
        report_path = sdir / "reports" / f"REPORT_{subagent_name}.md"
    report_summary = (args.summary or "").strip()

    common = lab()
    if status == "COMPLETED" and common is not None:
        shown = report_path.read_text(encoding="utf-8-sig", errors="replace") if report_path.exists() else report_summary
        problems = common.handover_problems(shown)
        if problems:
            rel_rp = report_path.relative_to(workspace).as_posix() if workspace in report_path.parents else str(report_path)
            emit(f"[RA CONTEXT HARNESS BLOCKED] `{subagent_name}`'s report is not accepted yet:\n"
                 + "\n".join(f"  - {p}" for p in problems)
                 + f"\n  TO FIX, in one try: open `{rel_rp}` and add the heading `## Handover answers` with every numbered answer below.\n"
                 f"  Who writes it: the worker `{subagent_name}`. If the worker is gone, re-dispatch it, or the manager answers on its\n"
                 "  behalf from the worker's own evidence (logs, files) and marks each answer `(written by the manager)`.\n"
                 f"  Then re-run: ra_context_harness.py return-baton --workspace . --subagent {subagent_name} "
                 f"--status COMPLETED --report-file {rel_rp}", sys.stderr)
            emit(common.render_injection("worker-handover", worker=subagent_name,
                                         task=outstanding[subagent_name].get("task") or "(task not recorded)",
                                         workspace=workspace.as_posix()), sys.stderr)
            sys.exit(1)

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

    outstanding.pop(subagent_name)
    # With --parallel forks still out, the baton stays with the most recent remaining subagent.
    reg["active_baton"] = f"SUBAGENT:{list(outstanding)[-1]}" if outstanding else "MAIN_ORCHESTRATOR"
    if status == "COMPLETED":
        reg["completed_subagent_relays"] = reg.get("completed_subagent_relays", 0) + 1
    reg.setdefault("subagent_reports", []).append(
        {
            "subagent": subagent_name,
            "status": status,
            "returned_at": now_iso(),
            "report_file": report_path.relative_to(workspace).as_posix(),
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
    print(f"  RA BATON RETURNED: `{subagent_name}` -> `{reg['active_baton']}` (status: {status})")
    print("=" * 78)
    print(f"  Completed Subagent Relays : {reg['completed_subagent_relays']}")
    print(f"  Verified Report File      : {report_path.relative_to(workspace).as_posix()}")
    if drifted_snaps:
        print("  [AUTO-EVICTED STALE SNAPSHOTS AFTER SUBAGENT WORK]:")
        for sid, r_str in drifted_snaps:
            print(f"    - Threw away `{sid}` ({r_str})")
    print("-" * 78)
    print("  ZERO-TRUST SUBAGENT SUPERVISION CHECKLIST FOR MAIN AGENT:")
    print("    1. Assume the subagent may have drifted or missed a constraint — verify its diff/output directly.")
    print("    2. Run `python research/harness/project_harness.py check-all` (if forged) or `ra_cheese_audit.py`.")
    print("=" * 78)
    if common is None or not common.state_file(workspace).is_file():
        return
    common.mark_worker_finished(workspace, subagent_name, "return-baton")
    board = common.render_board(workspace, "full")
    if board:
        print(board)
    n = len(common.lab_reviews(workspace)) + 1
    print(f"  REVIEW MEETING before the next fork - write research/reviews/REVIEW_{n}.md:")
    emit(common.render_review_meeting(workspace))
    print("  It must name every approach still racing, quote a scoreboard number, carry")
    print("  `DECISION: <family>: KEEP|SWITCH|DROP|RESTART`, `LESSON: <text>` and `NEXT: <text>` lines,")
    print("  and a `## Answers` section answering the numbered questions above. Then:")
    print(f"    ra_gate.py review --file research/reviews/REVIEW_{n}.md")


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
    else:
        # No --id / --auto-gc: report health only, change nothing.
        stale = []
        for sid in snaps:
            healthy, reasons = evaluate_snapshot_health(workspace, reg["snapshots"][sid])
            if not healthy:
                stale.append((sid, ", ".join(reasons)))
        print("=" * 78)
        print("  RA CONTEXT SNAPSHOT HEALTH CHECK (dry run, nothing evicted)")
        print("=" * 78)
        for sid, r in stale:
            print(f"  - [STALE] `{sid}` -> {r}")
        if stale:
            print("  Throw them away with `evict --auto-gc`, or one at a time with `evict --id <id>`.")
        else:
            print(f"  - All {len(snaps)} active snapshot(s) are fresh.")
        print("=" * 78)
        return

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
    print(f"  Outstanding Forks         : {', '.join(reg['outstanding_forks']) or 'none'}")
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
        help="Optional native session ID of the parent session, to fork from",
    )
    p_create.add_argument("--max-reuses", type=positive_int, default=None, help="Override max fork reuse count before eviction (> 0)")
    p_create.add_argument("--ttl-minutes", type=positive_int, default=None, help="Override TTL in minutes before eviction (> 0)")
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
        help="`auto` = this harness. Another platform needs the user's grant (ra_gate.py allow-agent).",
    )
    p_fork.add_argument(
        "--base-session",
        "--session-id",
        dest="base_session",
        default=None,
        help="Native session ID to fork; applies to the target platform only",
    )
    p_fork.add_argument("--model", default=None, help="Optional model name for the opencode / codex dispatch command")
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
    p_ret.add_argument(
        "--status",
        default="COMPLETED",
        type=str.upper,
        choices=list(RELAY_STATUSES),
        help="Outcome of the subagent's task; only COMPLETED counts toward completed_subagent_relays",
    )
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
    # Windows pipes default to the ANSI code page (e.g. cp932), which cannot encode the em dashes printed here.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
