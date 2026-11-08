#!/usr/bin/env python3
"""
ra_hooks.py — Claude Code hook harness that keeps the main agent acting as the lab manager.

    python ra_hooks.py <event>        # hook JSON on stdin

Events: session-start | prompt | pre-tool | post-tool | subagent-stop.
Silent unless <workspace>/research/.ra_state.json exists. Fails open: its own errors exit 0;
only a deliberate block exits 2.

Verified on Claude Code 2.1.319 (skill-frontmatter hooks):
  - they fire for the MAIN agent's PreToolUse / PostToolUse / UserPromptSubmit only;
  - SessionStart, SubagentStop, PreCompact and PostCompact from skill frontmatter never fire,
    so compaction / resume is detected here from the transcript and CLAUDE_PID instead;
  - a background worker's completion arrives as a <task-notification> user prompt.

Two launch paths: the skill frontmatter (active once the skill is invoked) and, after ra_forge.py, the project's
.claude/settings.local.json with --armed (every session: board at start / after compaction; blocks and per-prompt
reminders only once the skill is invoked in that session). When both exist the frontmatter copy stays silent.

Manager edit rule: no code file anywhere (CODE_SUFFIXES, research/sandbox/ included); notes, reports and config
under research/, docs/, .claude/ and any .md/.txt/.log are the manager's. Bash writes (redirect, tee, sed -i,
cp/mv, Set-Content/Out-File) are judged by the same rule; writes a regex can't see fail open.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
BOARD_EVERY = 25
CONTEXT_CAP = 9500
TAIL_CAP = 8 * 1024 * 1024
MANAGER_DIRS = {"research", "docs", ".claude"}
MANAGER_SUFFIXES = {".md", ".txt", ".log"}
# Code is bench work wherever it lives — research/sandbox/ and research/harness/ included.
CODE_SUFFIXES = {
    ".py", ".pyi", ".ipynb", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".php", ".rb", ".rs", ".go", ".java", ".kt", ".kts", ".scala", ".swift", ".m", ".mm",
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".fs", ".lua", ".pl", ".r", ".jl", ".dart", ".zig",
    ".sh", ".bash", ".zsh", ".ps1", ".psm1", ".bat", ".cmd", ".sql", ".html", ".htm", ".css", ".scss", ".less",
    ".glsl", ".hlsl", ".wgsl", ".shader", ".cu", ".proto", ".graphql",
}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
RA_SKILL = "research-anything"
WIN = os.name == "nt"
# --armed = launched from the project's own .claude/settings hooks (written by ra_forge.py), not the skill frontmatter.
ARMED = "--armed" in sys.argv
SEAT_HINT = "RA run in flight here. Take the manager seat: invoke the research-anything skill, then run ra_gate.py resume."

REVIEW_QUESTIONS = (
    "  1. Is it closer to the target?\n"
    "  2. Does its trend reach the target within the budget?\n"
    "  3. Would another approach be better?\n"
    "  4. Keep, switch, drop or restart?\n"
    "  5. What did we learn?"
)

_common = None


def common():
    global _common
    if _common is None:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import ra_common  # noqa: E402  (lazy: most pre-tool calls never need it)

        _common = ra_common
    return _common


# ---------------------------------------------------------------- I/O


def read_payload() -> Dict[str, Any]:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace").lstrip("\ufeff")
    data = json.loads(raw) if raw.strip() else {}
    return data if isinstance(data, dict) else {}


def emit_context(event_name: str, text: str) -> None:
    if not text:
        return
    if len(text) > CONTEXT_CAP:
        text = text[: CONTEXT_CAP - 60].rstrip() + "\n… [board truncated — run ra_gate.py status]"
    out = {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}}
    # ASCII-escaped JSON survives any console code page.
    sys.stdout.buffer.write(json.dumps(out).encode("ascii") + b"\n")
    sys.stdout.flush()


def block(msg: str) -> int:
    sys.stderr.buffer.write(msg.encode("utf-8") + b"\n")
    sys.stderr.flush()
    return 2


def note(msg: str) -> None:
    try:
        sys.stderr.buffer.write(f"[ra_hooks] {msg}\n".encode("utf-8", "replace"))
    except Exception:
        pass


# ---------------------------------------------------------------- workspace / paths


def find_workspace(payload: Dict[str, Any]) -> Optional[Path]:
    for cand in (os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd")):
        if cand:
            ws = Path(_native(cand))
            sp = ws / "research" / ".ra_state.json"
            if sp.is_file():
                try:
                    ok = isinstance(json.loads(sp.read_text(encoding="utf-8-sig")), dict)
                except (OSError, ValueError):
                    ok = False
                # An unreadable state must not leave the manager blocked with no way out.
                return ws if ok else None
    return None


def _native(p: str) -> str:
    # Git Bash may hand over /c/Users/... ; Python on Windows needs C:/Users/...
    if WIN and re.match(r"^/[A-Za-z]/", p):
        return p[1].upper() + ":" + p[2:]
    return p


def rel_to_workspace(ws: Path, file_path: str, cwd: Optional[str]) -> Optional[str]:
    """Workspace-relative posix path, or None when the file lies outside the workspace."""
    p = _native(file_path)
    if not os.path.isabs(p):
        p = os.path.join(_native(cwd) if cwd else str(ws), p)
    p = os.path.normpath(os.path.abspath(p))
    base = os.path.normpath(os.path.abspath(str(ws)))
    rel = _inside(p, base)
    if rel is None:
        # 8.3 short names, junctions or symlinks can hide that the file is inside after all.
        rel = _inside(os.path.realpath(p), os.path.realpath(base))
    return rel


def _inside(p: str, base: str) -> Optional[str]:
    try:
        rel = os.path.relpath(os.path.normcase(p), os.path.normcase(base))
    except ValueError:  # different drive
        return None
    if rel == os.curdir or rel.startswith(os.pardir):
        return None
    # Keep the caller's casing for the reported path.
    return p[len(base):].lstrip("\\/").replace("\\", "/")


def manager_may_edit(rel: str) -> bool:
    suffix = Path(rel).suffix.lower()
    if suffix in CODE_SUFFIXES:
        return False
    first = rel.split("/", 1)[0]
    if WIN:
        first = first.lower()
    return first in MANAGER_DIRS or suffix in MANAGER_SUFFIXES


_SEG_SPLIT = re.compile(r"\s*(?:\|\||&&|[;|\n])\s*")
_REDIRECT = re.compile(r"(?<![<>&\d])\d?>{1,2}\s*([^\s;|&<>]+)")
_PS_TARGET = re.compile(r"-(?:Path|FilePath|LiteralPath|Destination)\s+(\S+)", re.IGNORECASE)
_LEADING_VAR = re.compile(r"^\$(?:\{\w+\}|\w+)/")


def bash_write_targets(command: str) -> List[str]:
    """Files a shell command writes, as far as a regex can tell: redirects, tee, sed -i, cp/mv/install,
    Set-Content/Out-File. Heredoc bodies are skipped. Misses fail open; a false block is the bug to avoid."""
    if "<<" in command:
        command = command.split("\n", 1)[0]
    out: List[str] = []
    for seg in _SEG_SPLIT.split(command):
        if not seg.strip():
            continue
        out += [m.group(1) for m in _REDIRECT.finditer(seg) if m.group(1) not in ("/dev/null", "$null")]
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            toks = seg.split()
        while toks and re.match(r"^\w+=", toks[0]):
            toks.pop(0)
        if toks and toks[0] in ("sudo", "command", "exec", "time"):
            toks.pop(0)
        if not toks:
            continue
        cmd = os.path.basename(toks[0]).lower()
        args = toks[1:]
        plain = [a for a in args if not a.startswith("-")]
        if cmd == "tee":
            out += plain
        elif cmd == "sed" and any(
            a == "--in-place" or a.startswith("--in-place=") or (a.startswith("-") and not a.startswith("--") and "i" in a[1:])
            for a in args
        ):
            if len(plain) >= 2:
                out.append(plain[-1])
        elif cmd in ("cp", "mv", "install"):
            if len(plain) >= 2:
                out.append(plain[-1])
        elif cmd in ("set-content", "out-file", "add-content", "copy-item", "move-item"):
            m = _PS_TARGET.search(seg)
            if m:
                out.append(m.group(1))
            elif plain:
                out.append(plain[-1])
    cleaned: List[str] = []
    for t in out:
        t = t.strip("'\"")
        if not t or t.startswith(("$(", "`")):
            continue
        cleaned.append(_LEADING_VAR.sub("", t))  # "$W/src/x.py" -> "src/x.py" (judged relative to the workspace)
    return cleaned


def gate_cmd() -> str:
    return f'python "{(HERE / "ra_gate.py").as_posix()}"'


def next_review_file(ws: Path) -> str:
    # Same numbering as the board's NEXT DECISION: recorded reviews + 1.
    return f"research/reviews/REVIEW_{len(common().lab_reviews(ws)) + 1}.md"


# ---------------------------------------------------------------- session tracking (compaction / resume)


def _hooks_state_path(ws: Path) -> Path:
    return ws / "research" / ".ra_hooks.json"


def _load_hooks_state(ws: Path) -> Dict[str, Any]:
    try:
        data = json.loads(_hooks_state_path(ws).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_hooks_state(ws: Path, data: Dict[str, Any]) -> None:
    sess = data.get("sessions", {})
    if len(sess) > 20:
        keep = sorted(sess.items(), key=lambda kv: kv[1].get("seen", 0))[-20:]
        data["sessions"] = dict(keep)
    path = _hooks_state_path(ws)
    tmp = path.with_name(f".ra_hooks.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _transcript_size(payload: Dict[str, Any]) -> int:
    tp = payload.get("transcript_path")
    try:
        return os.path.getsize(_native(tp)) if tp else 0
    except OSError:
        return 0


def _compacted_since(payload: Dict[str, Any], offset: int) -> bool:
    tp = payload.get("transcript_path")
    if not tp:
        return False
    try:
        with open(_native(tp), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            start = offset if 0 <= offset <= size else max(0, size - TAIL_CAP)
            start = max(start, size - TAIL_CAP)
            f.seek(start)
            return b'"subtype":"compact_boundary"' in f.read()
    except OSError:
        return False


def context_reset(ws: Path, payload: Dict[str, Any], source: Optional[str] = None) -> Optional[str]:
    """None = same context as last time. Otherwise the reason this context has not seen the board:
    'startup', 'compact', 'resume', 'clear' or 'new'."""
    sid = str(payload.get("session_id") or "")
    if not sid:
        return None
    pid = os.environ.get("CLAUDE_PID", "")
    data = _load_hooks_state(ws)
    sessions = data.setdefault("sessions", {})
    rec = sessions.get(sid)
    size = _transcript_size(payload)
    reason: Optional[str] = source
    if reason is None:
        if rec is None:
            reason = "new"
        elif pid and rec.get("pid") and rec.get("pid") != pid:
            reason = "resume"
        elif _compacted_since(payload, int(rec.get("off", 0))):
            reason = "compact"
    sessions[sid] = {
        "pid": pid or (rec or {}).get("pid", ""),
        "off": size,
        "seen": time.time(),
        "skill": bool((rec or {}).get("skill")),
    }
    _save_hooks_state(ws, data)
    return reason


def project_armed(ws: Path) -> bool:
    for name in ("settings.local.json", "settings.json"):
        try:
            if "ra_hooks.py" in (ws / ".claude" / name).read_text(encoding="utf-8-sig"):
                return True
        except OSError:
            pass
    return False


def mark_skill_active(ws: Path, payload: Dict[str, Any]) -> None:
    sid = str(payload.get("session_id") or "")
    if not sid:
        return
    data = _load_hooks_state(ws)
    rec = data.setdefault("sessions", {}).setdefault(sid, {})
    if not rec.get("skill"):
        rec["skill"] = True
        rec.setdefault("seen", time.time())
        _save_hooks_state(ws, data)


def manager_seat(ws: Path, payload: Dict[str, Any]) -> bool:
    """Blocks and per-prompt reminders need the skill invoked in this session; frontmatter hooks imply that."""
    if not ARMED:
        return True
    sid = str(payload.get("session_id") or "")
    return bool(_load_hooks_state(ws).get("sessions", {}).get(sid, {}).get("skill"))


RESET_LINES = {
    "compact": "Context was compacted — this board is the plan; trust it over your memory.",
    "resume": "Session was resumed — this board is the plan; trust it over your memory.",
}


def full_board(ws: Path, reason: Optional[str] = None) -> str:
    board = common().render_board(ws, mode="full")
    if not board:
        return ""
    head = RESET_LINES.get(reason or "")
    return f"{head}\n{board}" if head else board


def pending_line(ws: Path) -> str:
    pending = common().review_pending(ws)
    if not pending:
        return ""
    names = ", ".join(pending)
    return f"Worker {names} finished — review before anything else ({next_review_file(ws)})."


def review_call(ws: Path, reason: Optional[str]) -> str:
    """Full board + the five review questions, for the moment a worker's report lands."""
    rf = next_review_file(ws)
    who = ", ".join(common().review_pending(ws)) or "the worker"
    return (
        f"{full_board(ws, reason)}\n"
        f"Worker {who} finished — review before anything else. Write {rf} answering:\n"
        f"{REVIEW_QUESTIONS}\n"
        f"then run {gate_cmd()} review --file {rf}"
    )


# ---------------------------------------------------------------- worker detection


def _flatten(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "\n".join(_flatten(x) for x in obj)
    if isinstance(obj, dict):
        if "text" in obj and isinstance(obj["text"], str):
            return obj["text"]
        return "\n".join(_flatten(obj.get(k)) for k in ("content", "result", "output") if k in obj)
    return ""


_BG_RE = re.compile(
    r"async agent launched|launched successfully|running in the background|working in the background"
    r"|is running in background|run_in_background",
    re.IGNORECASE,
)


def agent_report_finished(resp: Any) -> bool:
    """True only for a foreground Agent result that carries the worker's report."""
    if isinstance(resp, dict):
        status = str(resp.get("status") or "").lower()
        if resp.get("isAsync") or status in {"async_launched", "launched", "running"}:
            return False
        if status == "completed":
            return True
    text = _flatten(resp)
    return bool(text.strip()) and not _BG_RE.search(text)


def worker_label(tool_input: Dict[str, Any], resp: Any) -> str:
    desc = str(tool_input.get("description") or "").strip()
    if desc:
        return desc
    if isinstance(resp, dict) and resp.get("agentId"):
        return str(resp["agentId"])
    return str(tool_input.get("subagent_type") or "worker")


_NOTIF_RE = re.compile(r"<task-notification>(.*?)</task-notification>", re.DOTALL)


def finished_from_notifications(prompt: str) -> List[str]:
    """Workers whose background run just ended, from <task-notification> blocks in a prompt."""
    out: List[str] = []
    for body in _NOTIF_RE.findall(prompt or ""):
        status = re.search(r"<status>\s*([\w-]+)\s*</status>", body)
        if not status or status.group(1).lower() not in {"completed", "failed"}:
            continue
        summ = re.search(r"<summary>\s*Agent\s+\"(.+?)\"", body)
        tid = re.search(r"<task-id>\s*(a[0-9a-f]{8,})\s*</task-id>", body)
        if summ:
            out.append(summ.group(1))
        elif tid:
            out.append(tid.group(1))
    return out


def subagent_label(payload: Dict[str, Any]) -> Optional[str]:
    # Claude Code writes agent-<id>.meta.json next to the subagent transcript; its description
    # matches the Agent tool's, so all three finish paths name the worker the same way.
    atp = payload.get("agent_transcript_path")
    if atp:
        try:
            meta = Path(_native(atp)).with_suffix(".meta.json")
            desc = json.loads(meta.read_text(encoding="utf-8")).get("description")
            if desc:
                return str(desc)
        except Exception:
            pass
    if not payload.get("agent_type"):
        return None  # internal agents (prompt suggestions, /btw) are not workers
    return str(payload.get("agent_type") or payload.get("agent_id"))


# ---------------------------------------------------------------- events


def on_session_start(ws: Path, payload: Dict[str, Any]) -> int:
    source = str(payload.get("source") or "startup")
    context_reset(ws, payload, source=source)
    text = full_board(ws, source)
    if text and not manager_seat(ws, payload):
        text = f"{text}\n{SEAT_HINT}"
    emit_context("SessionStart", text)
    return 0


def on_prompt(ws: Path, payload: Dict[str, Any]) -> int:
    reason = context_reset(ws, payload)
    if not manager_seat(ws, payload):
        if reason:
            emit_context("UserPromptSubmit", f"{full_board(ws, reason)}\n{SEAT_HINT}".strip())
        return 0
    finished = finished_from_notifications(str(payload.get("prompt") or ""))
    for name in finished:
        common().mark_worker_finished(ws, name, "task-notification")
    if finished:
        text = review_call(ws, reason)
    elif reason:
        text = full_board(ws, reason)
    else:
        text = f"{common().render_board(ws, mode='summary')}\n{pending_line(ws)}"
    emit_context("UserPromptSubmit", text.strip())
    return 0


def on_pre_tool(ws: Path, payload: Dict[str, Any]) -> int:
    if payload.get("agent_id"):
        return 0  # workers are never blocked by the manager harness
    if not manager_seat(ws, payload):
        return 0
    tool = payload.get("tool_name") or ""
    tin = payload.get("tool_input") or {}
    if tool in ("Agent", "Task"):
        pending = common().review_pending(ws)
        if pending:
            rf = next_review_file(ws)
            who = ", ".join(pending)
            return block(
                f"[RA HOOK] Review worker {who}'s report first: write {rf} "
                f"(the five review questions) and run {gate_cmd()} review --file {rf} — then dispatch."
            )
        return 0
    if tool in EDIT_TOOLS:
        fp = tin.get("file_path") or tin.get("notebook_path") or ""
        if not fp:
            return 0
        rel = rel_to_workspace(ws, str(fp), payload.get("cwd"))
        if rel is None or manager_may_edit(rel):
            return 0
        if common().consume_manager_edit(ws, rel):
            return 0
        return block(
            f"[RA HOOK] You are the lab manager — delegate this edit of {rel} to a worker (Agent tool) "
            f"with a brief. Code is bench work wherever it lives, research/sandbox/ included. "
            f"One-off exception only with the user's words: "
            f'{gate_cmd()} manager-edit --file {rel} --reason "<user quote>"'
        )
    if tool == "Bash":
        hits = []
        for target in bash_write_targets(str(tin.get("command") or "")):
            rel = rel_to_workspace(ws, target, payload.get("cwd"))
            if rel is not None and not manager_may_edit(rel):
                hits.append(rel)
        if not hits:
            return 0
        rel = hits[0]
        if common().consume_manager_edit(ws, rel):
            return 0
        return block(
            f"[RA HOOK] You are the lab manager — this command writes {rel}. Delegate code changes to a worker "
            f"(Agent tool) with a brief; redirects, tee, sed -i and cp/mv count as edits. "
            f'One-off exception only with the user\'s words: {gate_cmd()} manager-edit --file {rel} --reason "<user quote>"'
        )
    return 0


def on_post_tool(ws: Path, payload: Dict[str, Any]) -> int:
    if payload.get("agent_id"):
        return 0
    c = common()
    tool = payload.get("tool_name") or ""
    tin = payload.get("tool_input") or {}
    if tool == "Skill" and str(tin.get("skill") or "").split(":")[-1] == RA_SKILL:
        mark_skill_active(ws, payload)
    count = c.record_main_tool_call(ws)
    reason = context_reset(ws, payload)
    if not manager_seat(ws, payload):
        if reason:
            emit_context("PostToolUse", f"{full_board(ws, reason)}\n{SEAT_HINT}".strip())
        return 0
    if tool in ("Agent", "Task") and agent_report_finished(payload.get("tool_response")):
        c.mark_worker_finished(ws, worker_label(tin, payload.get("tool_response")), "agent-tool")
        text = review_call(ws, reason)
    elif (
        reason
        or (count and count % BOARD_EVERY == 0)
        or (tool == "Skill" and str(tin.get("skill") or "").split(":")[-1] == RA_SKILL)
    ):
        text = full_board(ws, reason)
    else:
        return 0
    emit_context("PostToolUse", text.strip())
    return 0


def on_subagent_stop(ws: Path, payload: Dict[str, Any]) -> int:
    if not manager_seat(ws, payload):
        return 0
    label = subagent_label(payload)
    if label:
        common().mark_worker_finished(ws, label, "subagent-stop")
    return 0


HANDLERS = {
    "session-start": on_session_start,
    "prompt": on_prompt,
    "pre-tool": on_pre_tool,
    "post-tool": on_post_tool,
    "subagent-stop": on_subagent_stop,
}


def main(argv: List[str]) -> int:
    args = [a for a in argv[1:] if a != "--armed"]
    handler = HANDLERS.get(args[0] if args else "")
    if handler is None:
        return 0
    payload = read_payload()
    ws = find_workspace(payload)
    if ws is None:
        return 0
    if not ARMED and project_armed(ws):
        # The project's settings hooks carry the harness; the skill-frontmatter copy only takes the seat.
        mark_skill_active(ws, payload)
        return 0
    return handler(ws, payload)


if __name__ == "__main__":
    try:
        code = main(sys.argv)
    except Exception as exc:  # fail open: a harness bug must never block the agent
        note(f"internal error, ignored: {type(exc).__name__}: {exc}")
        code = 0
    sys.exit(2 if code == 2 else 0)
