#!/usr/bin/env python3
"""
ra_forge.py — Project-Local Skill, Multi-Harness Hook & Review Agent Generator for RA.

When a project needs custom domain rules, workflow enforcement, or when off-the-shelf
skills are missing/insufficient, `ra_forge.py` generates a complete project-local
enforcement suite (never polluting global skills):

1. Project-Local Custom Skill:
   - `.claude/skills/<slug>-rd/SKILL.md`
   - `.agents/skills/<slug>-rd/SKILL.md`
2. Executable Python Harness (`research/harness/project_harness.py`):
   - Compatible with Claude Code Hooks (`PreToolUse`, `PostToolUse`, `Stop` via stdin JSON)
   - Compatible with Antigravity / CLI / Git hooks (`check-edit --file <path>`, `check-all [--workspace <dir>]`)
   - Blocks edits to `PROTECTED_WORKING` files/functions, sealed axioms, and RA state files
3. Multi-Platform Hook & Dedicated Review Agent Configs:
   - `.claude/settings.local.json` (Claude Code Pre/Post/Stop hooks, merged into existing hooks; `.bak` kept)
   - `.claude/agents/ra-reviewer.md` (Claude Code adversarial Review Subagent)
   - `.agents/workflows/ra-review.md` & `research/harness/REVIEW_AGENT_PROMPT.md` (Antigravity / Multi-Agent Reviewer)

Usage:
    python ra_forge.py --workspace <project_root> --name <slug> --domain "<R&D domain>"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPTS_DIR = Path(__file__).resolve().parent
RA_HOOK_MARKER = "research/harness/project_harness.py"
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "Stop")


def _save_state_safe(state_path, state):
    # Atomic, lab-aware write via ra_common so concurrent hook updates aren't lost.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import ra_common
        ra_common.write_state(Path(state_path).parent.parent, state)
    except ImportError:
        Path(state_path).write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip().lower()).strip("-")
    return s or "project"


def one_line(text: str) -> str:
    return " ".join(str(text).split())


def yaml_str(text: str) -> str:
    # A JSON string is a valid YAML double-quoted scalar, so newlines, `: ` and `#` cannot break frontmatter.
    return json.dumps(one_line(text), ensure_ascii=False)


HARNESS_PY_TEMPLATE = r'''#!/usr/bin/env python3
"""
project_harness.py — Auto-generated RA Multi-Agent Execution Harness & Hook Gate.

Works as:
1. Claude Code Hook (`pre-tool`, `post-tool`, `stop`; hook payload JSON on stdin)
2. Antigravity / CLI / Git Hook (`check-edit --file <path>`, `check-all [--workspace <dir>]`)

Exit codes: 0 = allow / pass, 2 = block / fail. Internal errors exit 1, which Claude Code
treats as non-blocking, so a harness crash can never block every edit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Absolute RA scripts dir, baked in by ra_forge.py when this harness was generated.
RA_SCRIPTS_DIR = __RA_SCRIPTS_DIR__
if RA_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, RA_SCRIPTS_DIR)
try:
    import ra_common

    RA_COMMON_ERROR = ""
except Exception as _exc:
    ra_common = None
    RA_COMMON_ERROR = f"{type(_exc).__name__}: {_exc}"

WORKSPACE = Path(__file__).resolve().parent.parent.parent
STATE_REL = "research/.ra_state.json"
GUARDED_STATE_FILES = (STATE_REL, "research/context_snapshots/SNAPSHOT_REGISTRY.json")
# Prose documents these markers; only code is scanned.
DOC_SUFFIXES = {".md", ".markdown", ".rst", ".txt"}

BANDAID_PATTERNS = [
    (re.compile(r"(#|//)[ \t]*hardcode(d)?\b", re.IGNORECASE), "Forbidden hardcoded-marker comment"),
    (re.compile(r"(#|//)[ \t]*(hack|band-?aid|cheese|temporary[ \t]+fix)\b", re.IGNORECASE), "Forbidden band-aid/hack comment"),
    (
        # \s crosses newlines: catches `except:` with `pass` on a later line, comment lines allowed between.
        re.compile(r"\bexcept\s*(?:\(?\s*(?:Exception|BaseException)\s*\)?)?(?:\s+as\s+\w+)?\s*:\s*(?:#[^\n]*\s*)*pass\b"),
        "Silent except-pass error swallowing",
    ),
]


def path_key(rel: str) -> str:
    """Comparison key for workspace-relative paths (slash-agnostic; case-insensitive on Windows)."""
    p = str(rel).strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.casefold() if os.name == "nt" else p


_SYMBOL_RE = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")


def split_spec(spec: str) -> Tuple[str, str]:
    """`src\\calc.py:parse` -> (`src/calc.py`, `parse`); same rules as ra_common, usable without it."""
    s = str(spec).strip()
    file_part, sep, sym = s.rpartition(":")
    if sep and file_part and _SYMBOL_RE.match(sym):
        return file_part.replace("\\", "/"), sym
    return s.replace("\\", "/"), ""


def load_state() -> Tuple[Dict[str, Any], str, Optional[str]]:
    """Return (state, error, raw_text). `error` is non-empty when the file exists but is unusable."""
    path = WORKSPACE / STATE_REL
    if not path.exists():
        return {}, "", None
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        return {}, f"unreadable ({type(exc).__name__}: {exc})", None
    try:
        state = json.loads(raw)
    except Exception as exc:
        return {}, f"not valid JSON ({exc})", raw
    if not isinstance(state, dict):
        return {}, "not a JSON object", raw
    for key, typ, name in (
        ("sealed_axioms", dict, "object"),
        ("protected_nodes", list, "array"),
        ("protected_node_hashes", dict, "object"),
    ):
        if key in state and not isinstance(state[key], typ):
            return {}, f"malformed (`{key}` is not a JSON {name})", raw
    return state, "", raw


def sealed_meta(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """`sealed_axioms` maps relpath -> {"sha256": ...} (ra_gate.py); a bare sha string is accepted too."""
    return {
        rel: meta if isinstance(meta, dict) else {"sha256": meta}
        for rel, meta in state.get("sealed_axioms", {}).items()
    }


def protected_specs(state: Dict[str, Any]) -> List[str]:
    specs = [s for s in state.get("protected_nodes", []) if isinstance(s, str) and s.strip()]
    specs += [s for s in state.get("protected_node_hashes", {}) if s not in specs]
    return specs


def referenced_in(raw: str, rel: str) -> bool:
    """Whether `rel` appears anywhere in the (unparseable) state text, in / or JSON-escaped \\ form."""
    hay = raw.replace("\\\\", "/").replace("\\", "/")
    return path_key(rel) in (hay.casefold() if os.name == "nt" else hay)


def to_rel(target: str, cwd: Optional[str] = None) -> Optional[str]:
    """Workspace-relative POSIX path of `target`, or None when it lies outside the workspace."""
    p = Path(target)
    if not p.is_absolute():
        p = Path(cwd or os.getcwd()) / p
    try:
        return p.resolve().relative_to(WORKSPACE).as_posix()
    except ValueError:
        return None


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return None


def read_payload() -> Dict[str, Any]:
    """Claude Code hook payload from stdin; bytes decoded as UTF-8 regardless of the console code page."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace").strip()
        data = json.loads(raw) if raw else {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def tool_input_of(payload: Dict[str, Any]) -> Dict[str, Any]:
    ti = payload.get("tool_input") or payload.get("input") or {}
    return ti if isinstance(ti, dict) else {}


def target_of(tool_input: Dict[str, Any]) -> Optional[str]:
    for key in ("file_path", "path", "Path", "target_file"):
        if isinstance(tool_input.get(key), str) and tool_input[key]:
            return tool_input[key]
    return None


def simulate_edit(text: str, tool_input: Dict[str, Any]) -> Optional[str]:
    """File text after this Write / Edit / MultiEdit, or None when the payload carries no edit."""
    content = tool_input.get("content")
    if isinstance(content, str):
        return content.replace("\r\n", "\n")
    edits = tool_input.get("edits")
    edits = edits if isinstance(edits, list) else [tool_input]
    out, touched = text, False
    for e in edits:
        if not isinstance(e, dict):
            continue
        old, new = e.get("old_string"), e.get("new_string")
        if isinstance(old, str) and old and isinstance(new, str):
            touched = True
            # Replace every occurrence so a non-unique old_string cannot slip past the check.
            out = out.replace(old.replace("\r\n", "\n"), new.replace("\r\n", "\n"))
    return out if touched else None


def node_in_text(text: str, rel: str, sym: str) -> Tuple[int, Optional[str]]:
    """(definition count, normalised source) of `rel:sym` inside `text`, located by ra_common itself."""
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / rel
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_bytes(text.encode("utf-8"))
        spec = f"{rel}:{sym}"
        return ra_common.find_ambiguous(Path(tmp), spec), ra_common.extract_protected_node(Path(tmp), spec)


def symbol_change(rel: str, sym: str, tool_input: Dict[str, Any]) -> Optional[str]:
    """Why this edit touches protected `rel:sym`; "" when it leaves it identical, None when there is no edit to judge."""
    fpath = WORKSPACE / rel
    before = ra_common.read_text_normalised(fpath) if fpath.is_file() else None
    after = simulate_edit(before, tool_input) if before is not None else None
    if after is None:
        return None
    spec = f"{rel}:{sym}"
    old_n, old_src = ra_common.find_ambiguous(WORKSPACE, spec), ra_common.extract_protected_node(WORKSPACE, spec)
    if old_n == 0 or after == before:
        return ""
    new_n, new_src = node_in_text(after, rel, sym)
    if new_n == 0:
        return "removes or renames it"
    if new_n > old_n:
        return "adds a second definition that would shadow it"
    if old_n > 1:
        return f"changes a file where it is already ambiguous ({old_n} definitions)"
    return "changes its source" if new_src != old_src else ""


def block(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def check_pre_edit(target: Optional[str], cwd: Optional[str] = None, tool_input: Optional[Dict[str, Any]] = None) -> int:
    if not target:
        return 0
    rel = to_rel(target, cwd)
    if rel is None:
        return 0
    key = path_key(rel)

    # 1. RA bookkeeping state changes only through the RA scripts
    if key in {path_key(g) for g in GUARDED_STATE_FILES}:
        return block(
            f"[RA HARNESS BLOCKED] `{rel}` is RA bookkeeping state; never Edit/Write it directly. "
            f"Change it only through the RA scripts in `{RA_SCRIPTS_DIR}` "
            f"(`ra_gate.py seal-axioms` / `ra_gate.py map-context`, `ra_context_harness.py`)."
        )

    state, err, raw = load_state()
    if err:
        if raw is None or referenced_in(raw, rel):
            return block(
                f"[RA HARNESS BLOCKED] `{STATE_REL}` is {err}, so the seal / PROTECTED_WORKING lock on `{rel}` "
                f"cannot be verified. Ask the user to repair or restore `{STATE_REL}` before editing `{rel}`."
            )
        return 0

    # 2. Sealed axiom files
    if key in {path_key(r) for r in sealed_meta(state)}:
        return block(
            f"[RA HARNESS BLOCKED] `{rel}` is a cryptographically sealed AXIOMATIC_PRIMITIVES file! "
            f"Do NOT sneak hardcoded data or heuristics into sealed axioms. "
            f"If the axiom itself must change, the user re-seals it with `ra_gate.py seal-axioms`."
        )

    # 3. PROTECTED_WORKING files and functions
    for spec in protected_specs(state):
        file_part, sym = split_spec(spec)
        if path_key(file_part) != key:
            continue
        if not sym:
            return block(
                f"[RA HARNESS BLOCKED] `{rel}` is locked as `PROTECTED_WORKING` (`Symptom != Culprit`). "
                f"Do not modify innocent working files while fixing upstream culprits!"
            )
        if ra_common is None:
            return block(
                f"[RA HARNESS BLOCKED] `{rel}` holds PROTECTED_WORKING `{sym}`, but `ra_common` is not importable "
                f"from `{RA_SCRIPTS_DIR}` ({RA_COMMON_ERROR}), so this edit cannot be checked. "
                f"Ask the user to re-run ra_forge.py."
            )
        reason = symbol_change(rel, sym, tool_input or {})
        if reason is None:
            print(
                f"[RA HARNESS NOTICE] `{rel}` contains PROTECTED_WORKING `{sym}` (`Symptom != Culprit`); "
                f"leave it byte-identical.",
                file=sys.stderr,
            )
            continue
        if reason:
            return block(
                f"[RA HARNESS BLOCKED] This edit {reason}: `{spec}` is PROTECTED_WORKING (`Symptom != Culprit`). "
                f"Keep `{sym}` byte-identical and anchor old_string outside it. If real `[RA_LOG]` evidence proves "
                f"`{sym}` is the culprit, unlock it first: python \"{RA_SCRIPTS_DIR}/ra_gate.py\" map-context "
                f"--workspace \"{WORKSPACE}\" --revoke-protected \"{spec}\" --revoke-reason \"<evidence>\""
            )
    return 0


def integrity_issues(state: Dict[str, Any], only_key: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """(violations, notices) for sealed axioms and protected-node hashes, optionally limited to one file."""
    sealed = {r: m for r, m in sealed_meta(state).items() if only_key is None or path_key(r) == only_key}
    hashes = state.get("protected_node_hashes", {})
    specs = [
        s for s in protected_specs(state)
        if isinstance(hashes.get(s), str) and (only_key is None or path_key(split_spec(s)[0]) == only_key)
    ]
    if not sealed and not specs:
        return [], []
    if ra_common is None:
        return [
            f"Cannot verify seals: `ra_common` is not importable from `{RA_SCRIPTS_DIR}` ({RA_COMMON_ERROR}). "
            f"Re-run ra_forge.py to regenerate this harness."
        ], []

    issues: List[str] = []
    legacy: List[str] = []
    for rel, meta in sealed.items():
        status, _current = ra_common.verify_seal(WORKSPACE / rel.replace("\\", "/"), meta)
        if status == "MISSING":
            issues.append(f"AXIOM SEAL VIOLATION: sealed axiom file `{rel}` is missing!")
        elif status == "TAMPERED":
            issues.append(f"AXIOM SEAL VIOLATION: `{rel}` was modified since it was sealed! Revert it.")
        elif status == "LEGACY_OK":
            legacy.append(rel)
    for spec in specs:
        status, current = ra_common.verify_protected_node(WORKSPACE, spec, hashes[spec])
        if status == "MISSING":
            issues.append(f"[PROTECTED_NODE_TAMPERED] PROTECTED_WORKING node `{spec}` was deleted or renamed!")
        elif status == "AMBIGUOUS":
            found = ", ".join(ra_common.describe_matches(WORKSPACE, spec))
            issues.append(
                f"[PROTECTED_NODE_AMBIGUOUS] `{spec}` now matches several definitions ({found}); "
                f"one may shadow the protected original."
            )
        elif status == "TAMPERED":
            issues.append(
                f"[PROTECTED_NODE_TAMPERED] PROTECTED_WORKING node `{spec}` was modified "
                f"(expected {hashes[spec][:12]}..., got {(current or '')[:12]}...). Revert it, or if real `[RA_LOG]` "
                f"evidence proves it is the culprit, unlock it via `ra_gate.py map-context --revoke-protected`."
            )
        elif status == "LEGACY_OK":
            legacy.append(spec)
    notices = []
    if legacy:
        notices.append(
            f"[RA HARNESS NOTICE] {', '.join(legacy)} verified against a pre-ra_common hash; "
            f"re-run `ra_gate.py seal-axioms` / `map-context` to store the current scheme."
        )
    return issues, notices


def scan_text_for_bandaids(text: str, label: str) -> List[str]:
    issues: List[str] = []
    for regex, reason in BANDAID_PATTERNS:
        for m in regex.finditer(text):
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            shown = " ".join(text[start : end if end != -1 else len(text)].split())
            line_no = text.count("\n", 0, m.start()) + 1
            issues.append(f"{label} (new text line {line_no}): {reason} -> `{shown}`")
    return issues


def new_snippets(tool_input: Dict[str, Any]) -> List[str]:
    snippets = [tool_input[k] for k in ("new_string", "content") if isinstance(tool_input.get(k), str)]
    for e in tool_input.get("edits") or []:
        if isinstance(e, dict) and isinstance(e.get("new_string"), str):
            snippets.append(e["new_string"])
    return [s.replace("\r\n", "\n") for s in snippets]


def check_post_edit(target: Optional[str], cwd: Optional[str] = None, tool_input: Optional[Dict[str, Any]] = None) -> int:
    if not target:
        return 0
    tool_input = tool_input or {}
    rel = to_rel(target, cwd)
    label = rel or Path(target).name
    issues: List[str] = []

    # Only the text this edit introduced, so pre-existing markers don't block every later edit.
    if Path(target).suffix.lower() not in DOC_SUFFIXES:
        snippets = new_snippets(tool_input)
        if not snippets and not tool_input:
            whole = read_text(WORKSPACE / rel) if rel else None
            snippets = [whole] if whole else []
        for snippet in snippets:
            issues += scan_text_for_bandaids(snippet, label)

    if rel is not None:
        state, err, _raw = load_state()
        if not err:
            issues += integrity_issues(state, only_key=path_key(rel))[0]

    if issues:
        print("[RA HARNESS POST-EDIT VIOLATION]:", file=sys.stderr)
        for iss in issues:
            print(f"  - {iss}", file=sys.stderr)
        return 2
    return 0


def check_all() -> int:
    state, err, _raw = load_state()
    if err:
        return block(
            f"[RA HARNESS CHECK FAILED]:\n  - `{STATE_REL}` is {err}; sealed axioms and PROTECTED_WORKING nodes "
            f"cannot be verified. Repair or restore it."
        )
    errors, notices = integrity_issues(state)
    if errors:
        print("[RA HARNESS CHECK FAILED]:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    hashes = state.get("protected_node_hashes", {})
    specs = protected_specs(state)
    unhashed = [s for s in specs if not isinstance(hashes.get(s), str)]
    print(
        f"[RA HARNESS PASS] {len(sealed_meta(state))} sealed axiom(s) and "
        f"{len(specs) - len(unhashed)} protected node hash(es) intact."
    )
    for notice in notices:
        print(notice)
    if unhashed:
        print(
            f"[RA HARNESS NOTICE] No recorded hash for {', '.join(unhashed)}; run `ra_gate.py map-context --protected ...` "
            f"so they are verified."
        )

    cmap = state.get("context_map_snapshot")
    tracked = cmap.get("tracked_files") if isinstance(cmap, dict) else None
    if isinstance(tracked, dict) and tracked and ra_common is not None:
        stale = [
            rel for rel, old_hash in tracked.items()
            if (WORKSPACE / rel).is_file() and ra_common.hash_file(WORKSPACE / rel) != old_hash
        ]
        if stale:
            print(
                f"[RA HARNESS NOTICE] {len(stale)} file(s) changed since the last `WORKFLOW_MAP.md` session snapshot "
                f"({', '.join(stale)}). Run `ra_gate.py map-context` to refresh hashes and invoke the Review Agent!"
            )
    return 0


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse exits 2 on bad usage, which Claude Code would read as a block.
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:  # absent when a host swaps in a non-TextIOWrapper stream
            reconfigure(encoding="utf-8", errors="replace")

    parser = _Parser(description="RA Project Execution Harness & Hook Gate")
    parser.add_argument("mode", choices=["pre-tool", "post-tool", "stop", "check-edit", "check-all"])
    parser.add_argument("--file", default=None, help="Target file path for CLI check-edit / post-tool")
    parser.add_argument("--workspace", default=None, help="Project root (default: the project this harness lives in)")
    args = parser.parse_args()

    global WORKSPACE
    if args.workspace:
        WORKSPACE = Path(args.workspace).resolve()

    payload = read_payload() if args.mode in ("pre-tool", "post-tool", "stop") else {}
    tool_input = tool_input_of(payload)
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None

    if args.mode == "check-all":
        return check_all()
    if args.mode == "stop":
        if payload.get("stop_hook_active"):
            return 0  # Claude already continued once for this stop; blocking again loops forever.
        return check_all()
    if args.mode == "check-edit":
        return check_pre_edit(args.file)
    if args.mode == "pre-tool":
        return check_pre_edit(args.file or target_of(tool_input), cwd, tool_input)
    return check_post_edit(args.file or target_of(tool_input), cwd, tool_input)


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        print(f"[RA HARNESS INTERNAL ERROR] {type(exc).__name__}: {exc} (not blocking; run check-all)", file=sys.stderr)
        code = 1
    sys.exit(code)
'''


def render_harness(scripts_dir: Path) -> str:
    return HARNESS_PY_TEMPLATE.replace("__RA_SCRIPTS_DIR__", repr(scripts_dir.as_posix()), 1)


def build_project_skill_md(
    project_name: str,
    domain: str,
    invariants: List[str],
    contracts: List[str],
    protected_nodes: List[str],
    crawled_skills: List[str],
) -> str:
    inv_block = "\n".join(f"  {i}" for i in invariants) if invariants else "  - See `research/INVARIANTS.md`"
    bc_block = "\n".join(f"  {c}" for c in contracts) if contracts else "  - See `research/WORKFLOW_MAP.md`"
    prot_block = (
        "\n".join(f"  - `{p}` (PROTECTED_WORKING — DO NOT MODIFY)" for p in protected_nodes)
        if protected_nodes
        else "  - See `research/WORKFLOW_MAP.md` Section 2"
    )
    crawled_block = (
        "\n".join(f"  - `{s}`" for s in crawled_skills)
        if crawled_skills
        else "  - (None crawled yet — run `ra_crawler.py skill --query ...` if domain skills are needed)"
    )
    description = yaml_str(
        f"Project-local R&D skill and execution rules for {project_name} ({domain}). "
        "Enforces multi-hop workflow mapping, protected working nodes, behavioral "
        "contracts, anti-cheese rules, and mandatory Review Agent sign-off."
    )

    return f"""---
name: {project_name}-rd
description: {description}
---

# {project_name} — Project-Local R&D Skill (`{domain}`)

> **Scope**: Project-Local Only (`.claude/skills/{project_name}-rd/` & `.agents/skills/{project_name}-rd/`).
> **Generated**: `{now_iso()}` by `ra_forge.py`.

## 1. Mandatory Pre-Edit Workflow & Context Rules
1. **Read `research/WORKFLOW_MAP.md` First**:
   - Note that `WORKFLOW_MAP.md` is an **AI Session Snapshot** — use it to understand the system context without re-discovering everything from scratch, but always run `python research/harness/project_harness.py check-all` and verify live code before editing.
2. **Symptom != Culprit (Protected Innocent Nodes)**:
   - Never mutate a function just because a symptom appeared there. The following nodes are verified working and locked:
{prot_block}
3. **Preserve Existing Behavioral Contracts (Anti-Ping-Pong Lock)**:
{bc_block}
4. **Locked Project Invariants**:
{inv_block}

## 2. Installed Domain Skills in Project Arsenal
{crawled_block}

## 3. Mandatory Verification & Review Agent Protocol
Before claiming any fix, feature, or hypothesis is ready:
1. Run the executable project harness:
   ```bash
   python research/harness/project_harness.py check-all
   ```
2. Run real-environment `.log` verification (`ra_log_engine.py run` & `ra_log_engine.py audit`), anti-cheese audit (`ra_cheese_audit.py`), and User-Eyes visual audit (`ra_visual_audit.py audit`).
3. Invoke the **Project Review Agent** (`.claude/agents/ra-reviewer.md` or `research/harness/REVIEW_AGENT_PROMPT.md`) to audit your diff against `WORKFLOW_MAP.md` and `INVARIANTS.md`.
"""


def build_reviewer_agent_md(project_name: str, domain: str, scripts_dir: Path) -> str:
    scripts = scripts_dir.as_posix()
    description = yaml_str(
        f"Adversarial R&D & Workflow Blast-Radius Review Agent for {project_name} ({domain}). "
        "Invoke after any prototype or code change to verify culprit proof, protected working "
        "nodes, N-hop blast radius, behavioral contracts, and zero-cheese compliance."
    )
    return f"""---
name: ra-reviewer
description: {description}
tools: Read, Grep, Glob, Bash
---

# RA Adversarial Review Agent (`{project_name}`)

You are an independent, zero-trust **R&D & Workflow Blast-Radius Reviewer** for `{project_name}` (`{domain}`).
Your job is to catch tunnel vision, whack-a-mole regressions, mutated innocent functions, and hardcoded cheese **before** the primary agent presents results to the user.

## Mandatory Review Checklist

1. **Workflow & Context Map Audit (`research/WORKFLOW_MAP.md`)**:
   - Did the agent trace the full multi-hop flow (`-N` upstream producers to `+N` downstream consumers and multi-cycle loopbacks), or did it only read surface data / 1-hop neighbors?
   - Did the agent explicitly justify **WHAT** it edited/created, **WHY** edit that node, and **WHY** create a new function (proving no duplicate responsibility)?
2. **Innocent Function Protection (`Symptom != Culprit`)**:
   - Run `git diff` (or inspect modified files) and verify that **zero** functions listed as `PROTECTED_WORKING` in `research/WORKFLOW_MAP.md` or `research/.ra_state.json` were modified.
3. **Anti-Ping-Pong Behavioral Contracts (`BC-xxx`)**:
   - Trace the code changes across multiple loop iterations ($t = 1 \\dots 10^4$) and verify that no existing behavioral contract (`BC-001`, `BC-002`, etc.) is broken or reset by the change.
4. **Real-Environment `.log` Flow & Value Audit (`ra_log_engine.py`)**:
   - Synthetic/mocked unit-test marathons are banned. Verify that every code path is wired to `RALogger` and produces a real `.log` trace with `flow=caller->callee`, functional `role`, `inputs`, `state_before`, `state_after`, `delta`, `output`, and `BC-xxx` contract checks.
   - Run `python "{scripts}/ra_log_engine.py" audit --workspace . --hypothesis <active_hypothesis>` and reject if any `[STUCK]`, `[FAIL]`, or bare `"ok/pass"` AI-slop log lines exist.
5. **Automated Harness & Anti-Cheese Execution**:
   - Run `python research/harness/project_harness.py check-all` and `python "{scripts}/ra_cheese_audit.py" --workspace . --hypothesis <active_hypothesis>`.
   - Reject immediately if you see `# hardcoded`, `try/except: pass`, unsealed lookup tables, or symptom clamping.
6. **User-Eyes Visual & Experiential Reality Check (`ra_visual_audit.py`)**:
   - Never trust code or DOM text alone for visual/UI/game/chart work.
   - Open every screenshot in `visual_captures/` with `Read` and verify from the **user's eyes** that there is no wrong CSS alignment, no displaced icon/data, no unloaded image/asset, and no wrong function/image state displayed.
   - Run `python "{scripts}/ra_visual_audit.py" audit --workspace . --hypothesis <active_hypothesis>`.

## Output Format
Return a structured verdict:
- **`REVIEW VERDICT`**: `APPROVED` or `REJECTED`
- **`WORKFLOW & BLAST-RADIUS FINDINGS`**: Exact multi-hop impacts or missing context.
- **`PROTECTED NODE & CONTRACT CHECK`**: Pass/Fail for each `PROTECTED_WORKING` node and `BC-xxx` contract.
- **`REQUIRED FIXES`**: Exact upstream changes required if `REJECTED`.
"""


def load_json_or_abort(path: Path, what: str) -> Dict[str, Any]:
    """Parse an existing JSON object (BOM tolerated); abort before writing anything if it is unusable."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise SystemExit(f"[RA FORGE] ABORTED: cannot parse {what} `{path}` ({exc}). Fix it and re-run; nothing was written.")
    if not isinstance(data, dict):
        raise SystemExit(f"[RA FORGE] ABORTED: {what} `{path}` is not a JSON object. Fix it and re-run; nothing was written.")
    return data


def load_claude_settings(settings_path: Path) -> Dict[str, Any]:
    settings = load_json_or_abort(settings_path, "Claude settings")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict) or any(not isinstance(hooks.get(ev, []), list) for ev in HOOK_EVENTS):
        raise SystemExit(
            f"[RA FORGE] ABORTED: `hooks` in `{settings_path}` has an unexpected shape. Fix it and re-run; nothing was written."
        )
    return settings


def ra_hook_command(mode: str) -> str:
    # $CLAUDE_PROJECT_DIR keeps the hook working when Claude's cwd is a subdirectory.
    return f'python "$CLAUDE_PROJECT_DIR/{RA_HOOK_MARKER}" {mode}'


def is_ra_hook(hook: Any) -> bool:
    return isinstance(hook, dict) and RA_HOOK_MARKER in str(hook.get("command", "")).replace("\\", "/")


def merge_claude_settings_hooks(settings_path: Path, settings: Dict[str, Any]) -> Path:
    """Append RA hooks to the user's own hooks; RA entries from earlier runs are replaced, not duplicated."""
    edit_tools = "Edit|Write|MultiEdit"
    # shell=bash so $CLAUDE_PROJECT_DIR expands even where the default hook shell is PowerShell.
    ra_groups = {
        "PreToolUse": {"matcher": edit_tools, "hooks": [{"type": "command", "shell": "bash", "command": ra_hook_command("pre-tool")}]},
        "PostToolUse": {"matcher": edit_tools, "hooks": [{"type": "command", "shell": "bash", "command": ra_hook_command("post-tool")}]},
        "Stop": {"hooks": [{"type": "command", "shell": "bash", "command": ra_hook_command("stop")}]},
    }
    hooks = settings.setdefault("hooks", {})
    for event, ra_group in ra_groups.items():
        kept: List[Any] = []
        for group in hooks.get(event, []):
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                own = [h for h in group["hooks"] if not is_ra_hook(h)]
                if not own:
                    continue
                group = {**group, "hooks": own}
            kept.append(group)
        hooks[event] = kept + [ra_group]

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        backup = settings_path.with_name(settings_path.name + ".bak")
        backup.write_bytes(settings_path.read_bytes())
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return settings_path


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:  # absent when a host swaps in a non-TextIOWrapper stream
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="RA Forge — Generate project-local Skill, Multi-Harness Hooks (.py), and Review Agent"
    )
    parser.add_argument("--workspace", default=".", help="Project workspace root")
    parser.add_argument("--name", required=True, help="Project or skill slug name (e.g., 'combat-engine')")
    parser.add_argument("--domain", required=True, help="Project R&D domain (e.g., 'Game Development / State Recognition')")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    slug = slugify(args.name)
    domain = one_line(args.domain)

    # Validate every JSON file we will rewrite before touching anything on disk.
    state_path = rdir / ".ra_state.json"
    state = load_json_or_abort(state_path, "RA state")
    settings_path = workspace / ".claude" / "settings.local.json"
    settings = load_claude_settings(settings_path)

    rdir.mkdir(parents=True, exist_ok=True)

    invariants: List[str] = []
    inv_file = rdir / "INVARIANTS.md"
    if inv_file.exists():
        for line in inv_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.strip().startswith("- **`INV-"):
                invariants.append(line.strip())

    contracts: List[str] = []
    wmap_file = rdir / "WORKFLOW_MAP.md"
    if wmap_file.exists():
        for line in wmap_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            sline = line.strip()
            if (sline.startswith("- **`BC-") or sline.startswith("- `BC-")) and "<e.g.," not in sline:
                contracts.append(sline)

    protected_nodes: List[str] = state.get("protected_nodes", [])
    crawled_skills = [s.get("name", "") for s in state.get("arsenal", {}).get("skills", []) if s.get("name")]

    # 1. Write Executable Python Harness (`research/harness/project_harness.py`)
    harness_dir = rdir / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    harness_py = harness_dir / "project_harness.py"
    harness_py.write_text(render_harness(SCRIPTS_DIR), encoding="utf-8")

    # 2. Write Project-Local Skills (`.claude/skills/<slug>-rd/SKILL.md` and `.agents/skills/<slug>-rd/SKILL.md`)
    skill_md_content = build_project_skill_md(slug, domain, invariants, contracts, protected_nodes, crawled_skills)
    skill_paths = [
        workspace / ".claude" / "skills" / f"{slug}-rd" / "SKILL.md",
        workspace / ".agents" / "skills" / f"{slug}-rd" / "SKILL.md",
        rdir / "arsenal" / "skills" / f"{slug}-rd" / "SKILL.md",
    ]
    for sp in skill_paths:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(skill_md_content, encoding="utf-8")

    # 3. Write Multi-Platform Review Agent & Workflows
    reviewer_md = build_reviewer_agent_md(slug, domain, SCRIPTS_DIR)
    claude_agent_path = workspace / ".claude" / "agents" / "ra-reviewer.md"
    claude_agent_path.parent.mkdir(parents=True, exist_ok=True)
    claude_agent_path.write_text(reviewer_md, encoding="utf-8")

    agy_workflow_path = workspace / ".agents" / "workflows" / "ra-review.md"
    agy_workflow_path.parent.mkdir(parents=True, exist_ok=True)
    agy_workflow_path.write_text(reviewer_md, encoding="utf-8")

    prompt_path = harness_dir / "REVIEW_AGENT_PROMPT.md"
    prompt_path.write_text(reviewer_md, encoding="utf-8")

    # 4. Merge Claude Code Hooks into `.claude/settings.local.json`
    merge_claude_settings_hooks(settings_path, settings)

    # 5. Record in `.ra_state.json`
    if state_path.exists():
        state["forged_suite"] = {
            "project_skill": f".claude/skills/{slug}-rd/SKILL.md",
            "agent_skill": f".agents/skills/{slug}-rd/SKILL.md",
            "harness_py": "research/harness/project_harness.py",
            "claude_hooks": ".claude/settings.local.json",
            "reviewer_agent": ".claude/agents/ra-reviewer.md",
            "forged_at": now_iso(),
        }
        _save_state_safe(state_path, state)

    print("=" * 78)
    print(f"  RA FORGE — PROJECT-LOCAL SKILL, HARNESS & REVIEW AGENT CREATED ('{slug}')")
    print("=" * 78)
    print("  1. Project-Local Skills (Never Global):")
    print(f"     - .claude/skills/{slug}-rd/SKILL.md")
    print(f"     - .agents/skills/{slug}-rd/SKILL.md")
    print("  2. Executable Python Harness & Hook Gate:")
    print(f"     - {harness_py.relative_to(workspace).as_posix()}")
    print(f"     - {settings_path.relative_to(workspace).as_posix()} (Claude Code PreToolUse/PostToolUse/Stop hooks, merged; .bak kept)")
    print("  3. Dedicated Adversarial Review Agent (Multi-Platform):")
    print(f"     - {claude_agent_path.relative_to(workspace).as_posix()} (Claude Code Subagent)")
    print(f"     - {agy_workflow_path.relative_to(workspace).as_posix()} (Antigravity / Agent Workflow)")
    print(f"     - {prompt_path.relative_to(workspace).as_posix()} (Universal Subagent Prompt)")
    print("=" * 78)


if __name__ == "__main__":
    main()
