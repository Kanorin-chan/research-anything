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

# What the REVIEW file needs besides the `## Answers` section (the questions come from the review-meeting template).
REVIEW_QUESTIONS = (
    "  It must name every approach still racing, quote a scoreboard number, and carry\n"
    "  `DECISION: <family>: KEEP|SWITCH|DROP|RESTART`, `LESSON: <text>` and `NEXT: <text>` lines."
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


def _native(p: str) -> str:
    return common()._native(p)


def _inside(p: str, base: str) -> Optional[str]:
    return common()._inside(p, base)


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


# ---------------------------------------------------------------- shell safety (deletes, other agents)

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
_WRAPPERS = {"call", "then", "do", "else", "if", "while", "!", "{", "&", "try", "finally"}
# Prefixes that run the command after them: (short options taking a value, long options taking a value).
_PREFIX_OPTS = {
    "timeout": ("sk", {"--signal", "--kill-after"}),
    "nice": ("n", {"--adjustment"}),
    "ionice": ("cnpPu", {"--class", "--classdata", "--pid", "--pgid", "--uid"}),
    "stdbuf": ("ioe", {"--input", "--output", "--error"}),
    "env": ("uCS", {"--unset", "--chdir", "--split-string"}),
    "sudo": ("ughpCDrtTU", {"--user", "--group", "--host", "--prompt", "--close-from", "--chdir", "--role", "--type",
                            "--command-timeout", "--other-user"}),
    "doas": ("uC", set()),
    "time": ("fo", {"--format", "--output"}),
    "exec": ("a", set()),
    "command": ("", set()),
    "nohup": ("", set()),
    "builtin": ("", set()),
}
_MOVE_COMMANDS = {"mv", "move", "move-item", "mi", "ren", "rename", "rename-item", "rni"}
_RENAMES = {"ren", "rename", "rename-item", "rni"}
# Move-Item / Rename-Item parameters that take a value, and which operand each one is.
_PS_MOVE_PARAMS = {"path": "src", "literalpath": "src", "lp": "src", "pspath": "src", "destination": "dest",
                   "newname": "", "filter": "", "include": "", "exclude": "", "credential": ""}
_PKG_RUNNERS = {"npx", "bunx", "pnpx"}
_SHELL_C = {"bash": ("-c",), "sh": ("-c",), "zsh": ("-c",), "cmd": ("/c", "/k"), "pwsh": ("-c", "-command"),
            "powershell": ("-c", "-command")}
_CODE_DELETE = re.compile(r"rmtree|\.remove\(|\.unlink\(|\.rmdir\(|rmSync|unlinkSync|unlink\(|\brm\(|os\.remove|os\.unlink")
_CODE_MOVE = re.compile(r"(?<![\w.])(?:shutil\.move|os\.renames?|os\.replace)\s*\(|\brenameSync\s*\(")
_CODE_MOVE_ARGS = re.compile(r"\s*(['\"])(.*?)\1\s*,\s*(['\"])(.*?)\3")
_EXT = (".exe", ".cmd", ".ps1", ".bat")


def _strip_heredocs(command: str) -> str:
    lines, out, end = command.split("\n"), [], None
    for line in lines:
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = _HEREDOC.search(line)
        if m:
            end = m.group(2)
    return "\n".join(out)


def _split_segments(command: str) -> List[str]:
    """Split on ; | & && || newline outside quotes, so a quoted one-liner stays whole."""
    segs, cur, quote, i = [], [], "", 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch == "\\" and command[i + 1:i + 2] in (";", "|", "&"):
            cur.append(command[i:i + 2])
            i += 2
            continue
        elif ch in "\"'":
            quote = ch
        elif ch in ";|\n" or (ch == "&" and command[i - 1:i] not in (">", "<") and command[i + 1:i + 2] not in (">",)):
            segs.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def _tokens(seg: str) -> List[str]:
    """Whitespace split outside quotes; quotes dropped, backslashes kept (Windows paths)."""
    toks, cur, quote, has = [], [], "", False
    for ch in seg:
        if quote:
            if ch == quote:
                quote = ""
            else:
                cur.append(ch)
        elif ch in "\"'":
            quote, has = ch, True
        elif ch.isspace():
            if cur or has:
                toks.append("".join(cur))
            cur, has = [], False
        else:
            cur.append(ch)
    if cur or has:
        toks.append("".join(cur))
    return toks


def _cli_name(tok: str) -> str:
    name = tok.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for ext in _EXT:
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


def _is_flag(a: str) -> bool:
    return a.startswith("-") or bool(re.fullmatch(r"/[A-Za-z?]", a))


def _strip_prefix(toks: List[str]) -> Optional[List[str]]:
    """The command a prefix runs (`timeout 60 rm x` -> `rm x`), or None when toks[0] is no prefix."""
    name = _cli_name(toks[0])
    if name not in _PREFIX_OPTS or (name == "command" and any(a in ("-v", "-V") for a in toks[1:3])):
        return None
    short, longs = _PREFIX_OPTS[name]
    rest, split, i = toks[1:], [], 0
    while i < len(rest) and rest[i].startswith("-"):
        a, val = rest[i], None
        if a == "--":
            i += 1
            break
        if a.startswith("--"):
            key, eq, val = a.partition("=")
            if key in longs and not eq:
                i += 1
                val = rest[i] if i < len(rest) else ""
            if key == "--split-string":
                split = _tokens(val or "")
        else:
            for j, ch in enumerate(a[1:], 1):
                if ch in short:
                    val = a[j + 1:]
                    if not val:
                        i += 1
                        val = rest[i] if i < len(rest) else ""
                    if name == "env" and ch == "S":
                        split = _tokens(val)
                    break
        i += 1
    rest = rest[i:]
    if name == "timeout" and rest:
        rest = rest[1:]  # the duration
    return split + rest


def _move_operands(cmd: str, args: List[str]) -> Any:
    """(sources, destination) of mv / Move-Item / move / ren; destination None = the current directory."""
    srcs, dest, pos, i = [], None, [], 0
    while i < len(args):
        a, low = args[i], args[i].lower()
        nxt = args[i + 1] if i + 1 < len(args) else ""
        name = low[1:].split(":", 1)[0] if low.startswith("-") and not low.startswith("--") else ""
        ps = name if name in _PS_MOVE_PARAMS else next(
            (p for p in _PS_MOVE_PARAMS if len(name) >= 3 and p.startswith(name)), None)
        if a == "--":
            pos += args[i + 1:]
            break
        if ps:
            val = a.split(":", 1)[1] if ":" in a else nxt
            i += 0 if ":" in a else 1
            if _PS_MOVE_PARAMS[ps] == "src":
                srcs += [v for v in val.split(",") if v]
            elif _PS_MOVE_PARAMS[ps] == "dest":
                dest = val
        elif low in ("-t", "--target-directory"):
            dest, i = nxt, i + 1
        elif low.startswith("--target-directory="):
            dest = a.split("=", 1)[1]
        elif a == "-S" or low == "--suffix":
            i += 1
        elif not (a.startswith("-") or re.fullmatch(r"/-?[A-Za-z?]", a)):
            pos.append(a)
        i += 1
    if cmd in _RENAMES:
        return srcs + pos, None  # a new name stays in the same folder
    if dest is not None:
        return srcs + pos, dest
    if srcs:
        return srcs, (pos[0] if pos else None)
    return (pos[:-1], pos[-1]) if len(pos) >= 2 else (pos, None)


def _lookup_hit(args: List[str], listing: bool) -> Optional[str]:
    c = common()
    for a in args:
        if _is_flag(a):
            continue
        norm = a.replace("\\", "/").lower().rstrip("/")
        parts = [p.rstrip("*") for p in norm.split("/") if p]
        names = {p[: -len(e)] if e and p.endswith(e) else p for p in parts for e in ("", ".exe", ".cmd", ".ps1")}
        if not listing and any(n in c.SAFETY_AGENT_CLIS for n in names):
            return a
        if listing:
            probe = "/" + norm.lstrip("/")
            if any(h in probe for h in c.SAFETY_AGENT_PATH_HINTS) or re.search(c.SAFETY_AGENT_PATH_REGEX, probe):
                return a
    return None


def _code_moves(code: str) -> List[Any]:
    """Move calls in a one-liner as mv-style hits; one whose paths aren't string literals can't be checked: a delete."""
    hits: List[Any] = []
    for m in _CODE_MOVE.finditer(code):
        a = _CODE_MOVE_ARGS.match(code, m.end())
        hits.append(("move", ([a.group(2)], a.group(4))) if a else ("delete", ""))
    return hits


def _model_flag(args: List[str]) -> str:
    """The value of -m / --model (also -m=x, --model=x), or ''."""
    for i, a in enumerate(args):
        for flag in ("-m", "--model"):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(flag + "="):
                return a[len(flag) + 1:]
    return ""


def _short_has(rest: List[str], ch: str) -> bool:
    return any(re.fullmatch(r"-[A-Za-z]+", a) and ch in a for a in rest)


def _pathspec(a: str) -> bool:
    # `.`, `:/`, globs and ./paths name files; a bare word may be a branch.
    return a in (".", "..", ":/", ":") or a.startswith(("./", ".\\", "../", ":/", ":(")) or any(ch in a for ch in "*?[")


def _git_hit(args: List[str]) -> bool:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c") else 1
    sub, rest = (args[i] if i < len(args) else ""), args[i + 1:]
    if sub == "clean":
        return not any(a == "--dry-run" or (a.startswith("-") and not a.startswith("--") and "n" in a) for a in rest)
    if sub == "reset":
        return "--hard" in rest
    if sub == "checkout":
        if "--" in rest and rest.index("--") + 1 < len(rest):
            return True
        return "--force" in rest or _short_has(rest, "f") or any(_pathspec(a) for a in rest if not a.startswith("-"))
    if sub == "switch":
        return "--discard-changes" in rest or "--force" in rest or _short_has(rest, "f")
    if sub == "restore":
        staged = "--staged" in rest or _short_has(rest, "S")
        return not staged or "--worktree" in rest or _short_has(rest, "W")
    if sub == "rm":
        return "--cached" not in rest and "--dry-run" not in rest and not _short_has(rest, "n")
    return False


def _is_gate_remove(cmd: str, args: List[str]) -> bool:
    """Only `python [flags] ra_gate.py remove`; -c, -m or another script first means no exemption."""
    if not (cmd in ("python", "python3", "py") or re.fullmatch(r"python[\d.]+", cmd)):
        return False
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-c" or args[i] == "-m" or args[i].startswith(("-c", "-m")) and not args[i].startswith("--"):
            return False
        i += 2 if args[i] in ("-X", "-W") else 1
    return _cli_name(args[i]) == "ra_gate.py" and args[i + 1:i + 2] == ["remove"] if i < len(args) else False


_PS_VALUE_PARAMS = {"-executionpolicy", "-ep", "-workingdirectory", "-wd", "-version", "-inputformat", "-outputformat",
                    "-windowstyle", "-configurationname", "-settingsfile", "-custompipename"}


def _ps_encoded(args: List[str]) -> bool:
    """-EncodedCommand among powershell's own parameters (those before -Command / -File / the script)."""
    i = 0
    while i < len(args) and (args[i].startswith("-") or (args[i].startswith("/") and "/" not in args[i][1:])):
        a = "-" + args[i][1:].lower()
        if a in ("-c", "-command", "-f", "-file"):
            return False
        if len(a) > 1 and a[1] == "e" and ("-encodedcommand".startswith(a) or a == "-ec"):
            return True
        i += 2 if a in _PS_VALUE_PARAMS else 1
    return False


def _segment_safety(toks: List[str], depth: int, worker: bool = False) -> List[Any]:
    c = common()
    out: List[Any] = []
    while toks:
        head = toks[0].lstrip("({").lstrip("$(")
        if head.startswith("\\") and not re.search(r"[\\/]", head[1:]):
            head = head[1:]  # \rm skips shell aliases; a bare name, not a path
        if toks[0] and not head:
            toks = toks[1:]  # a lone `(` or `{`
            continue
        toks = [head] + toks[1:]
        if re.match(r"^\w+=", head) or head in _WRAPPERS or head.lower() == "start":
            was_start = head.lower() == "start"
            toks = toks[1:]
            while was_start and toks and (toks[0] == "" or re.fullmatch(r"/\w+", toks[0])):
                toks = toks[1:]
            continue
        nxt = _strip_prefix(toks)
        if nxt is None:
            break
        toks = nxt
    if not toks:
        return out
    cmd, args = _cli_name(toks[0]), toks[1:]
    if cmd in _PKG_RUNNERS or (cmd in ("npm", "pnpm", "yarn") and args[:1] in (["exec"], ["dlx"])):
        rest = args[1:] if cmd not in _PKG_RUNNERS else args
        rest = [a for a in rest if a not in ("-y", "--yes", "-p", "--package", "--")] if rest[:1] and rest[0].startswith("-") else rest
        return _segment_safety(rest, depth, worker) if rest else out
    if cmd in ("powershell", "pwsh") and _ps_encoded(args):
        return out + [("unclassifiable", "encoded command")]
    if cmd in _SHELL_C and depth < 4:
        for i, a in enumerate(args):
            if a.lower() in _SHELL_C[cmd] or (cmd in ("bash", "sh", "zsh") and re.fullmatch(r"-[a-z]*c[a-z]*", a)):
                return out + shell_safety(" ".join(args[i + 1:]), depth + 1, worker)
    if cmd in ("eval", "iex", "invoke-expression") and depth < 4:
        return out + shell_safety(" ".join(args), depth + 1, worker)
    if _is_gate_remove(cmd, args):
        return out + ([("delete", "")] if worker else [])
    if cmd in ("echo", "printf", "write-host", "write-output", "write-error"):
        return out
    if cmd in c.SAFETY_AGENT_CLIS:
        if cmd == "claude" and args and all(a in ("--version", "--help") for a in args):
            return out
        model = _model_flag(args)  # checked against a model grant; none = the CLI's default model
        return out + [("agent-launch", f"{cmd}:{model}" if model else cmd)]
    if cmd == "type":
        # PowerShell's `type` is Get-Content: only a bare agent name is a lookup.
        hit = next((a for a in args if not _is_flag(a) and _cli_name(a) in c.SAFETY_AGENT_CLIS and not re.search(r"[\\/]", a)), None)
        return out + ([("agent-lookup", hit)] if hit else [])
    if cmd in c.SAFETY_LOOKUP_COMMANDS or (cmd == "command" and ("-v" in args or "-V" in args)):
        hit = _lookup_hit(args, False)
        return out + ([("agent-lookup", hit)] if hit else [])
    if cmd in _MOVE_COMMANDS:
        srcs, dest = _move_operands(cmd, args)
        return out + ([("move", (srcs, dest))] if srcs else [])
    if cmd in c.SAFETY_LISTING_COMMANDS:
        hit = _lookup_hit(args, True)
        return out + ([("agent-lookup", hit)] if hit else [])
    plain = [a for a in args if not _is_flag(a)]
    if cmd in c.SAFETY_DELETE_COMMANDS:
        return out + [("delete", "\n".join(plain))]
    if cmd == "git" and _git_hit(args):
        return out + [("delete", "")]
    if cmd == "find" and ("-delete" in args or any(a == "-exec" and args[i + 1:i + 2] and _cli_name(args[i + 1]) in c.SAFETY_DELETE_COMMANDS
                                                    for i, a in enumerate(args))):
        return out + [("delete", "")]
    if cmd == "xargs" and any(_cli_name(a) in c.SAFETY_DELETE_COMMANDS for a in args):
        return out + [("delete", "")]
    if cmd in ("python", "python3", "py", "node", "nodejs", "deno", "bun") or re.fullmatch(r"python[\d.]+", cmd):
        py = cmd.startswith(("python", "py"))
        i = 0
        while i < len(args) and args[i].startswith("-"):
            a = args[i]
            if py:
                m = re.fullmatch(r"-[A-Za-z]*?c(.*)", a, re.S) if not a.startswith("--") else None
            else:
                m = re.fullmatch(r"-[ep](.*)", a, re.S) or re.fullmatch(r"--(?:eval|print)(.*)", a, re.S)
            if m:
                code = " ".join([m.group(1)] + args[i + 1:])
                if _CODE_DELETE.search(code):
                    return out + [("delete", "")]
                return out + _code_moves(code)
            i += 2 if a in ("-X", "-W") else 1
    return out


def _substitutions(command: str) -> List[str]:
    """Bodies of $(...), <(...), >(...) and `...`; none inside single quotes, `'` inert inside double quotes."""
    bodies, i, n, single, double = [], 0, len(command), False, False
    while i < n:
        ch = command[i]
        if single:
            single = ch != "'"
        elif ch == "\\":
            i += 1
        elif ch == "'" and not double:
            single = True
        elif ch == '"':
            double = not double
        elif (ch == "$" or (ch in "<>" and not double)) and command[i + 1:i + 2] == "(":
            depth, j = 1, i + 2
            while j < n and depth:
                depth += (command[j] == "(") - (command[j] == ")")
                j += 1
            bodies.append(command[i + 2:j - 1 if depth == 0 else j])
        elif ch == "`":
            j = command.find("`", i + 1)
            if j < 0:
                break
            bodies.append(command[i + 1:j])
            i = j
        i += 1
    return bodies


def shell_safety(command: str, depth: int = 0, worker: bool = False) -> List[Any]:
    """(kind, detail) per risky segment: delete | agent-launch | agent-lookup | unclassifiable.
    `ra_gate.py remove` is the one door: not a hit, except for a worker. Pure string work, no subprocess."""
    hits: List[Any] = []
    command = _strip_heredocs(command or "")
    if depth < 4:
        for body in _substitutions(command):
            hits += shell_safety(body, depth + 1, worker)
    for seg in _split_segments(command):
        hits += _segment_safety(_tokens(seg), depth, worker)
    return hits


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


def handover_call(ws: Path, rf: str) -> str:
    """The worker-handover questions for each finished worker whose report has not answered them yet."""
    c = common()
    out = []
    for w, entry in c.pending_reviews_detail(ws):
        if c.handover_settled(entry):
            continue
        out.append(
            f"Worker `{w}`'s report has no accepted `## Handover answers`. `ra_gate.py review` refuses until they are in "
            f"its report {c.worker_report_rel(w)} (the worker writes them) or in {rf} under `## Handover answers ({w})`:\n"
            + c.render_injection("worker-handover", worker=w, task=entry.get("task") or "(see the worker's brief)",
                                 workspace=ws.as_posix())
        )
    return "".join(f"{t.rstrip()}\n" for t in out)


def review_call(ws: Path, reason: Optional[str]) -> str:
    """Full board + the handover and review-meeting questions with live facts, for the moment a worker's report lands."""
    rf = next_review_file(ws)
    who = ", ".join(common().review_pending(ws)) or "the worker"
    return (
        f"Worker {who} finished — review before anything else. Write {rf}:\n"
        f"{handover_call(ws, rf)}"
        f"{common().render_review_meeting(ws)}\n"
        f"{REVIEW_QUESTIONS}\n"
        f"then run {gate_cmd()} review --file {rf}\n"
        f"{full_board(ws, reason)}"
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


def finished_notifications(prompt: str) -> List[Any]:
    """(worker, its result text) for each background run that just ended, from <task-notification> blocks."""
    out: List[Any] = []
    for body in _NOTIF_RE.findall(prompt or ""):
        status = re.search(r"<status>\s*([\w-]+)\s*</status>", body)
        if not status or status.group(1).lower() not in {"completed", "failed"}:
            continue
        summ = re.search(r"<summary>\s*Agent\s+\"(.+?)\"", body)
        tid = re.search(r"<task-id>\s*(a[0-9a-f]{8,})\s*</task-id>", body)
        result = re.search(r"<result>(.*?)(?:</result>|$)", body, re.DOTALL)
        name = summ.group(1) if summ else tid.group(1) if tid else None
        if name:
            out.append((name, result.group(1) if result else ""))
    return out


def finished_from_notifications(prompt: str) -> List[str]:
    """Workers whose background run just ended, from <task-notification> blocks in a prompt."""
    return [name for name, _ in finished_notifications(prompt)]


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
    if text:
        # Reminder first: emit_context cuts the tail of a long board, never the head.
        state = common().read_state(ws) or {}
        lead = common().render_injection(
            "session-start", workspace=ws.as_posix(), identity=hook_identity(payload),
            stage=state.get("current_stage") or "unknown")
        if not manager_seat(ws, payload):
            lead += f"\n{SEAT_HINT}"
        text = f"{lead}\n{text}"
    emit_context("SessionStart", text)
    return 0


def on_prompt(ws: Path, payload: Dict[str, Any]) -> int:
    reason = context_reset(ws, payload)
    if not manager_seat(ws, payload):
        if reason:
            emit_context("UserPromptSubmit", f"{full_board(ws, reason)}\n{SEAT_HINT}".strip())
        return 0
    finished = finished_notifications(str(payload.get("prompt") or ""))
    for name, result in finished:
        common().mark_worker_finished(ws, name, "task-notification", handover=not common().handover_problems(result))
    if finished:
        text = review_call(ws, reason)
    elif reason:
        text = full_board(ws, reason)
    else:
        text = f"{common().render_board(ws, mode='summary')}\n{pending_line(ws)}"
    emit_context("UserPromptSubmit", text.strip())
    return 0


def _delete_targets(ws: Path, detail: str, cwd: Optional[str]) -> str:
    shown = []
    for raw in (r for r in detail.split("\n") if r.strip()):
        try:
            # Display only: the block happens either way, so no look inside directories.
            zone, posix = common().classify_delete_path(ws, raw, cwd, check_children=False)
            shown.append(f"{posix} ({zone})")
        except Exception:
            shown.append(raw)
    return ", ".join(shown[:6]) or "(targets not readable from the command)"


def _move_hit(ws: Path, srcs: List[str], dest: Optional[str], cwd: Optional[str]) -> Optional[str]:
    """Why a move is a delete (a protected source, or a destination outside the workspace); None when it is not."""
    import glob

    c = common()
    base = _native(cwd) if cwd else str(ws)
    for raw in srcs:
        pat = _native(raw.strip("\"'"))
        names = glob.glob(pat if os.path.isabs(pat) else os.path.join(base, pat)) if any(ch in pat for ch in "*?[") else []
        for name in names or [raw]:
            zone, posix = c.classify_delete_path(ws, name, cwd)
            if zone == "protected":
                return f"{posix} (protected)"
    if dest:
        zone, posix = c.classify_delete_path(ws, os.path.expandvars(dest), cwd, check_children=False)
        if zone == "outside":
            return f"{', '.join(srcs[:4])} -> {posix} (outside the workspace)"
    return None


def hook_identity(payload: Dict[str, Any]) -> str:
    """claude-code:<model> from the payload or the transcript tail; never walks processes."""
    keep = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CONFIG_DIR", "USERPROFILE", "HOME")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["CLAUDECODE"] = "1"  # hooks only run in Claude Code
    try:
        return str(common().resolve_identity(env, payload)["agent"])
    except Exception:
        return "claude-code:unknown"


def shell_gate(ws: Path, payload: Dict[str, Any], command: str) -> int:
    """Delete / other-agent checks; every session in an RA workspace, workers included."""
    worker = bool(payload.get("agent_id"))
    cwd = payload.get("cwd")
    c = common()

    def tail() -> str:
        if worker:
            return "Do not delete from the shell. Workers: list it in your report; the manager removes it."
        return (f"Do not delete from the shell. The one door: {gate_cmd()} remove --path <path> "
                f"--answers {c.next_answers_file(ws, 'before-delete')}.")

    for kind, detail in shell_safety(command, worker=worker):
        if kind == "delete":
            text = c.render_injection("before-delete", targets=_delete_targets(ws, detail, cwd), workspace=ws.as_posix())
            return block(f"[RA HOOK] Delete blocked.\n{text}\n{tail()}")
        if kind == "move":
            hit = _move_hit(ws, detail[0], detail[1], cwd)
            if hit:
                text = c.render_injection("before-delete", targets=hit, workspace=ws.as_posix())
                return block(f"[RA HOOK] Move blocked: moving a protected record, or out of the workspace, is a delete.\n"
                             f"{text}\n{tail()}")
            continue
        if kind == "agent-launch" and not c.is_agent_allowed(ws, detail, own_harness=""):
            text = c.render_injection("before-other-agent", agent=detail, identity=hook_identity(payload))
            return block(f"[RA HOOK] Other agent blocked; no user grant on file for it.\n{text}")
        if kind == "unclassifiable":
            return block("[RA HOOK] Blocked: unclassifiable encoded command; run it in plain text.")
        if kind == "agent-lookup":
            return block(
                f"[RA HOOK] Searching this machine for agent CLIs ({detail}) is not allowed. "
                "Use only the agents the user granted in research/AGENT_PERMISSIONS.json."
            )
    return 0


def on_pre_tool(ws: Path, payload: Dict[str, Any]) -> int:
    tool = payload.get("tool_name") or ""
    tin = payload.get("tool_input") or {}
    if tool in ("Bash", "PowerShell"):
        if shell_gate(ws, payload, str(tin.get("command") or "")) == 2:
            return 2
    if payload.get("agent_id"):
        return 0  # workers are never blocked by the manager harness
    if not manager_seat(ws, payload):
        return 0
    if tool in ("Agent", "Task"):
        pending = common().review_pending(ws)
        if pending:
            rf = next_review_file(ws)
            who = ", ".join(pending)
            n = len(common().load_injection("review-meeting")["questions"])
            return block(
                f"[RA HOOK] Review worker {who}'s report first: write {rf} "
                f"(answer the {n} review-meeting questions under `## Answers`) and run {gate_cmd()} review --file {rf} "
                "— then dispatch."
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
    if tool in ("Bash", "PowerShell"):
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
        resp = payload.get("tool_response")
        task = str(tin.get("description") or tin.get("prompt") or "")[:300]
        c.mark_worker_finished(ws, worker_label(tin, resp), "agent-tool", handover=not c.handover_problems(_flatten(resp)),
                               task=task)
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
