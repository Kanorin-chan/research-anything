#!/usr/bin/env python3
"""
ra_common.py — Shared hashing helpers for the RA scripts.

One definition of "the hash of a file" and "the hash of a protected node", so the
script that records a hash (ra_gate.py) and the scripts that verify it
(ra_cheese_audit.py, ra_forge.py) can never disagree.

Protected node spec:
    relpath                whole file (same hash as hash_file)
    relpath:name           a def / class / function. A bare name means the top-level
                           definition; if there is none, the single nested one.
    relpath:Class.method   a qualified name

Callers must refuse a spec when find_ambiguous() != 1.

Also holds the per-hypothesis scoreboard (rounds, plateau rules, lock) shared by
ra_log_engine.py `run` (records rounds) and ra_gate.py (cold-review, status, conclude),
the atomic state writer every script uses, and the lab board (state["lab"]) that the
hooks push back at the lead agent: render_board, next_decision, review_pending,
mark_worker_finished, clear_reviews, consume_manager_edit, record_main_tool_call.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HASH_ALGO = "ra_common.v1"

PYTHON_SUFFIXES = {".py", ".pyw", ".pyi"}
# Block = lines indented under the declaration (plus a closing `end`).
INDENT_SUFFIXES = PYTHON_SUFFIXES | {".lua", ".rb", ".jl", ".ex", ".exs", ".nim", ".coffee", ".cr"}
HASH_COMMENT_SUFFIXES = {".php", ".sh", ".bash", ".zsh", ".pl", ".pm", ".r", ".ps1", ".tcl"}
C_PREPROCESSOR_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".cu", ".cuh", ".m", ".mm"}

FINGERPRINT_SKIP_DIRS = {
    "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", ".git", ".venv", "venv", "visual_captures",
}
FINGERPRINT_SKIP_SUFFIXES = {".log", ".json", ".md", ".pyc", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

_SYMBOL_RE = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")
_CHAR_LIT_RE = re.compile(r"'(?:\\[^\n]{1,10}?|[^\\'\n])'")
_ATTR_LINE_RE = re.compile(r"^[ \t]*(?:@[\w$.]|#\[|\[[A-Za-z_][\w.]*(?:\(.*\))?\][ \t]*$)")
_END_LINE_RE = re.compile(r"^[ \t]*(?:end\b|\}[;,)]*[ \t]*$)")

_DECL_TEMPLATES = (
    r"\b(?:def|function\*?|fn|fun|func|class|struct|interface|trait|enum|impl|sub|procedure|module|object|record)"
    r"[ \t]+(?P<n>{name})\b",
    r"\bfunc[ \t]*\([^)]*\)[ \t]*(?P<n>{name})\b",
    r"(?:\b(?:const|let|var)[ \t]+|^[ \t]*(?:(?:static|readonly|private|public|protected)[ \t]+)*)(?P<n>{name})"
    r"[ \t]*(?::[^=\n]+)?=[ \t]*(?:async[ \t]+)?(?:function\b|\([^)]*\)[^=\n]*=>|[\w$]+[ \t]*=>)",
    # C-like definitions / class methods; `{` on the same or next line, and not a call taking `() => {`.
    r"^[ \t]*(?:[\w$:<>\[\]\*&,~]+[ \t]+)*\*?(?:[\w$]+::)*(?P<n>{name})[ \t]*"
    r"\((?:[^;{{}}()]|\([^;{{}}()]*\))*\)(?:(?!=>)[^;{{}}\n])*(?:\n[ \t]*)?\{{",
)
_CONTAINER_TEMPLATE = (
    r"\b(?:class|struct|interface|trait|enum|impl|module|object|namespace|record)[ \t]+(?P<n>{name})\b"
)


# ---------------------------------------------------------------------------
# Whole files
# ---------------------------------------------------------------------------

def normalise_bytes(raw: bytes) -> Optional[str]:
    """Text with the UTF-8 BOM stripped and CRLF -> LF, or None when the bytes are binary."""
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return None


def read_text_normalised(path: Path) -> Optional[str]:
    return normalise_bytes(Path(path).read_bytes())


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hash_file(path: Path) -> str:
    """SHA-256 of the file's text (BOM stripped, CRLF -> LF); binary files hash their raw bytes."""
    raw = Path(path).read_bytes()
    text = normalise_bytes(raw)
    return hashlib.sha256(raw).hexdigest() if text is None else hash_text(text)


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------

def split_spec(spec: str) -> Tuple[str, str]:
    """`a\\b.py:Cls.fn` -> ("a/b.py", "Cls.fn"); a spec without a symbol -> (path, "")."""
    spec = spec.strip()
    if ":" in spec:
        file_part, sym = spec.rsplit(":", 1)
        # `C:/x.py` is a drive letter, not a symbol.
        if file_part and _SYMBOL_RE.match(sym):
            return file_part.replace("\\", "/"), sym
    return spec.replace("\\", "/"), ""


def spec_path(workspace: Path, spec: str) -> Path:
    return (Path(workspace).resolve() / split_spec(spec)[0]).resolve()


def canonical_spec(workspace: Path, spec: str) -> Optional[str]:
    """Workspace-relative POSIX form of a spec, or None when it points outside the workspace."""
    ws = Path(workspace).resolve()
    file_part, sym = split_spec(spec)
    try:
        rel = (ws / file_part).resolve().relative_to(ws).as_posix()
    except ValueError:
        return None
    return f"{rel}:{sym}" if sym else rel


# ---------------------------------------------------------------------------
# Locating a symbol
# ---------------------------------------------------------------------------

def _pick_tier(found: List[Tuple[str, int, str]], sym: str) -> List[Tuple[str, int, str]]:
    exact = [f for f in found if f[0] == sym]
    return exact or [f for f in found if f[0].endswith("." + sym)]


def _python_nodes(src: str, sym: str) -> Optional[List[Tuple[str, int, str]]]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    lines = src.split("\n")
    found: List[Tuple[str, int, str]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = prefix + child.name
                first = min([d.lineno for d in child.decorator_list] + [child.lineno])
                last = child.end_lineno or child.lineno
                found.append((qual, first, "\n".join(lines[first - 1:last])))
                visit(child, qual + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return _pick_tier(found, sym)


def _skip_literal(src: str, i: int, suffix: str) -> int:
    """Index after the comment / string starting at i, or i when there is none."""
    c = src[i]
    nxt = src[i + 1] if i + 1 < len(src) else ""
    line_comment = (c == "/" and nxt == "/") or (c == "#" and suffix in HASH_COMMENT_SUFFIXES) or (
        c == "#" and suffix in C_PREPROCESSOR_SUFFIXES and src[src.rfind("\n", 0, i) + 1:i].strip() == ""
    )
    if line_comment:
        j = src.find("\n", i)
        return len(src) if j < 0 else j
    if c == "/" and nxt == "*":
        j = src.find("*/", i + 2)
        return len(src) if j < 0 else j + 2
    if c == "`":
        j = i + 1
        while j < len(src) and src[j] != "`":
            j += 2 if src[j] == "\\" else 1
        return min(j + 1, len(src))
    if c in "\"'":
        if c == "'":
            m = _CHAR_LIT_RE.match(src, i)
            if m:
                return m.end()
            if suffix == ".rs":
                return i + 1  # lifetime `'a`
        j = i + 1
        while j < len(src) and src[j] not in (c, "\n"):
            j += 2 if src[j] == "\\" else 1
        return j + 1 if j < len(src) and src[j] == c else min(j, len(src))
    return i


def _match_brace(src: str, i: int, suffix: str) -> int:
    depth = 0
    n = len(src)
    while i < n:
        j = _skip_literal(src, i, suffix)
        if j != i:
            i = j
            continue
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _brace_block_end(src: str, i: int, suffix: str, max_newlines: int = 4) -> Optional[int]:
    """End of the `{...}` body (or `;`) that follows a declaration; None if none appears soon."""
    paren = 0
    newlines = 0
    n = len(src)
    while i < n:
        j = _skip_literal(src, i, suffix)
        if j != i:
            i = j
            continue
        c = src[i]
        if c in "([":
            paren += 1
        elif c in ")]":
            paren = max(0, paren - 1)
        elif paren == 0:
            if c == "{":
                return _match_brace(src, i, suffix)
            if c == ";":
                return i + 1
            if c == "\n":
                newlines += 1
                if newlines > max_newlines:
                    return None
        i += 1
    return None


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _indent_block_end(src: str, line_start: int, header_from: int) -> int:
    n = len(src)
    line_end = src.find("\n", line_start)
    base = _indent_width(src[line_start:n if line_end < 0 else line_end])
    i, depth = header_from, 0
    while i < n and not (src[i] == "\n" and depth == 0):
        if src[i] in "([{":
            depth += 1
        elif src[i] in ")]}":
            depth = max(0, depth - 1)
        i += 1
    end = i
    pos = i + 1
    while pos < n:
        nl = src.find("\n", pos)
        stop = n if nl < 0 else nl
        line = src[pos:stop]
        if line.strip():
            if _indent_width(line) <= base:
                if _END_LINE_RE.match(line):
                    end = stop
                break
            end = stop
        pos = stop + 1
    return end


def _extend_up_over_attributes(src: str, line_start: int) -> int:
    while line_start > 0:
        prev_start = src.rfind("\n", 0, line_start - 1) + 1
        if _ATTR_LINE_RE.match(src[prev_start:line_start - 1]):
            line_start = prev_start
        else:
            break
    return line_start


def _regex_decls(src: str, lo: int, hi: int, name: str, suffix: str, containers_only: bool) -> List[Tuple[int, int, int]]:
    """(start, end, indent) of each declaration of `name` inside src[lo:hi]."""
    templates = (_CONTAINER_TEMPLATE,) if containers_only else _DECL_TEMPLATES
    seen: Dict[int, Tuple[int, int, int]] = {}
    for tpl in templates:
        pat = re.compile(tpl.format(name=re.escape(name)), re.MULTILINE)
        for m in pat.finditer(src, lo, hi):
            line_start = src.rfind("\n", 0, m.start("n")) + 1
            if line_start in seen:
                continue
            end: Optional[int] = None
            if suffix not in INDENT_SUFFIXES:
                end = _brace_block_end(src, m.end("n"), suffix)
            if end is None:
                end = _indent_block_end(src, line_start, m.end("n"))
            start = _extend_up_over_attributes(src, line_start)
            seen[line_start] = (start, min(end, hi), _indent_width(src[line_start:m.start("n")]))
    return sorted(seen.values())


def _regex_nodes(src: str, sym: str, suffix: str) -> List[Tuple[str, int, str]]:
    parts = sym.split(".")
    regions: List[Tuple[int, int, int]] = [(0, len(src), 0)]
    for idx, part in enumerate(parts):
        last = idx == len(parts) - 1
        regions = [
            decl
            for lo, hi, _ in regions
            for decl in _regex_decls(src, lo, hi, part, suffix, containers_only=not last)
        ]
    found: List[Tuple[str, int, str]] = []
    for start, end, indent in regions:
        # Without a parser, "top level" means column 0.
        qual = sym if (len(parts) > 1 or indent == 0) else "?." + sym
        found.append((qual, src.count("\n", 0, start) + 1, src[start:end]))
    return _pick_tier(found, sym)


def _find_nodes(workspace: Path, spec: str) -> List[Tuple[str, int, str]]:
    file_part, sym = split_spec(spec)
    fpath = (Path(workspace).resolve() / file_part).resolve()
    if not sym or not fpath.is_file():
        return []
    src = read_text_normalised(fpath)
    if src is None:
        return []
    suffix = fpath.suffix.lower()
    if suffix in PYTHON_SUFFIXES:
        nodes = _python_nodes(src, sym)
        if nodes is not None:
            return nodes
    return _regex_nodes(src, sym, suffix)


# ---------------------------------------------------------------------------
# Public node API
# ---------------------------------------------------------------------------

def find_ambiguous(workspace: Path, spec: str) -> int:
    """How many definitions the spec matches (0 = not found, 1 = usable, >1 = ambiguous)."""
    if not split_spec(spec)[1]:
        return 1 if spec_path(workspace, spec).is_file() else 0
    return len(_find_nodes(workspace, spec))


def describe_matches(workspace: Path, spec: str) -> List[str]:
    """Human-readable matches, e.g. ["Engine.run (line 14)"], for error messages."""
    return [f"{qual} (line {line})" for qual, line, _ in _find_nodes(workspace, spec)]


def extract_protected_node(workspace: Path, spec: str) -> Optional[str]:
    """Normalised source of the node (decorators included); None if missing, binary or ambiguous."""
    if not split_spec(spec)[1]:
        path = spec_path(workspace, spec)
        return read_text_normalised(path) if path.is_file() else None
    nodes = _find_nodes(workspace, spec)
    return nodes[0][2] if len(nodes) == 1 else None


def hash_protected_node(workspace: Path, spec: str) -> Optional[str]:
    """SHA-256 of a protected node; None if it is not found (or is ambiguous — see find_ambiguous)."""
    if not split_spec(spec)[1]:
        path = spec_path(workspace, spec)
        return hash_file(path) if path.is_file() else None
    seg = extract_protected_node(workspace, spec)
    return None if seg is None else hash_text(seg)


def _legacy_protected_hash(workspace: Path, spec: str) -> Optional[str]:
    """Hash scheme of ra_gate <= 1.3.4, kept only to migrate hashes stored by it."""
    file_part, sym = spec.rsplit(":", 1) if ":" in spec else (spec, "")
    fpath = (Path(workspace) / file_part).resolve()
    if not fpath.is_file():
        return None
    try:
        src = fpath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    seg: Optional[str] = src if not sym else None
    if sym and fpath.suffix.lower() == ".py":
        try:
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == sym:
                    seg = ast.get_source_segment(src, node) or ast.dump(node)
                    break
        except (SyntaxError, ValueError):
            pass
    if sym and seg is None:
        m = re.search(
            rf"\b(?:def|function|fn|class|struct)\s+{re.escape(sym)}\b.*?(?=\n(?:def|function|fn|class|struct)\s+|\Z)",
            src,
            re.DOTALL,
        )
        seg = m.group(0) if m else None
    return None if seg is None else hashlib.sha256(seg.strip().encode("utf-8")).hexdigest()


def verify_protected_node(workspace: Path, spec: str, expected: str) -> Tuple[str, Optional[str]]:
    """(OK | LEGACY_OK | MISSING | AMBIGUOUS | TAMPERED, current hash). On LEGACY_OK, store the new hash."""
    count = find_ambiguous(workspace, spec)
    if count == 0:
        return "MISSING", None
    if count > 1:
        return "AMBIGUOUS", None
    current = hash_protected_node(workspace, spec)
    if current == expected:
        return "OK", current
    if _legacy_protected_hash(workspace, spec) == expected:
        return "LEGACY_OK", current
    return "TAMPERED", current


def verify_seal(path: Path, meta: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """("OK" | "LEGACY_OK" | "MISSING" | "TAMPERED", current hash) for a sealed axiom file."""
    path = Path(path)
    if not path.is_file():
        return "MISSING", None
    current = hash_file(path)
    expected = meta.get("sha256")
    if current == expected:
        return "OK", current
    # Seals made before ra_common hashed raw bytes.
    if meta.get("algo") != HASH_ALGO and raw_sha256(path) == expected:
        return "LEGACY_OK", current
    return "TAMPERED", current


# ---------------------------------------------------------------------------
# Code fingerprint (what an audit pass flag was earned against)
# ---------------------------------------------------------------------------

def fingerprint_files(workspace: Path, state: Dict[str, Any], hyp: Optional[str] = None) -> List[Path]:
    ws = Path(workspace).resolve()
    paths = set()
    if hyp:
        sandbox = ws / "research" / "sandbox" / hyp
        if sandbox.is_dir():
            for f in sandbox.rglob("*"):
                if (
                    f.is_file()
                    and not set(f.relative_to(sandbox).parts[:-1]) & FINGERPRINT_SKIP_DIRS
                    and f.suffix.lower() not in FINGERPRINT_SKIP_SUFFIXES
                ):
                    paths.add(f.resolve())
    for rel in state.get("context_map_snapshot", {}).get("tracked_files", {}):
        paths.add((ws / rel).resolve())
    for rel in state.get("sealed_axioms", {}):
        paths.add((ws / rel).resolve())
    for spec in state.get("protected_node_hashes", {}):
        paths.add(spec_path(ws, spec))
    return sorted(paths)


def code_fingerprint(workspace: Path, state: Dict[str, Any], hyp: Optional[str] = None) -> str:
    """SHA-256 over the active sandbox, tracked files, sealed axioms and protected-node files."""
    ws = Path(workspace).resolve()
    h = hashlib.sha256()
    for p in fingerprint_files(ws, state, hyp):
        try:
            rel = p.relative_to(ws).as_posix()
        except ValueError:
            rel = p.as_posix()
        h.update(rel.encode("utf-8") + b"\0")
        h.update((hash_file(p) if p.is_file() else "MISSING").encode("utf-8") + b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Scoreboard: progress is measured per run, and a plateau locks runs
# ---------------------------------------------------------------------------

DEFAULT_APPROACH = "main"
# New stop rules only; a registered rule keeps the cap stored in it.
DEFAULT_MAX_ROUNDS_PER_APPROACH = 10
BLIND_ROUNDS = 3
FLAT_WINDOW = 3
FLAT_MIN_SCORED = FLAT_WINDOW + 1
BASELINE_MIN_SCORED = 3
TREND_MIN_SCORED = 4
TREND_WINDOW = 6
RETIRED_STATUSES = ("SWITCHED", "DROPPED")
_EPS = 1e-12

RA_SCORE_RE = re.compile(r"^[ \t]*RA_SCORE[ \t]*[=:][ \t]*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", re.MULTILINE)
FAMILY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_NUM_TOKEN_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?!\w)")
_BASELINE_LINE_RE = re.compile(r"Baseline To Beat[*_\s]*:[*_\s]*(.*)$", re.IGNORECASE | re.MULTILINE)
_BASELINE_VALUE_RE = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)(?:\s*/\s*(\d+(?:\.\d+)?)|\s*(%))?(?![\w.]\d)")


def _sb_now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_ra_score(stdout: str) -> Optional[float]:
    """The number on the LAST `RA_SCORE=<x>` (or `RA_SCORE: <x>`) stdout line, or None."""
    found = RA_SCORE_RE.findall(stdout or "")
    return float(found[-1]) if found else None


def fmt_score(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.6g}"


def approach_key(family: str) -> str:
    return family.strip().lower()


def metric_rule(state: Dict[str, Any], hyp: Optional[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(component, rule) of the hypothesis' numeric stop rule: the last registered one with numbers."""
    found = None
    for comp, sr in (state.get("stop_rules") or {}).items():
        if hyp and sr.get("hypothesis") == hyp and any(sr.get(k) is not None for k in ("min_gain", "target", "metric")):
            found = (comp, sr)
    return found


def rule_has_numbers(sr: Dict[str, Any]) -> bool:
    return bool(sr.get("metric")) and sr.get("target") is not None and sr.get("min_gain") is not None


def rule_cap(sr: Optional[Dict[str, Any]]) -> int:
    """Rounds one approach family gets under this stop rule."""
    try:
        return int((sr or {}).get("max_rounds_per_approach") or DEFAULT_MAX_ROUNDS_PER_APPROACH)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ROUNDS_PER_APPROACH


def sb_get(state: Dict[str, Any], hyp: str, create: bool = True) -> Dict[str, Any]:
    boards = state.setdefault("scoreboard", {}) if create else (state.get("scoreboard") or {})
    sb = boards.get(hyp)
    if sb is None:
        if not create:
            return {"approaches": {}, "lock": None, "cold_reviews": [], "grace": {}}
        sb = boards[hyp] = {}
    for key, default in (("approaches", {}), ("lock", None), ("cold_reviews", []), ("grace", {})):
        sb.setdefault(key, default)
    return sb


def _lower(sr: Optional[Dict[str, Any]]) -> bool:
    return bool(sr and sr.get("lower_is_better"))


def _best(scores: List[float], lower: bool) -> Optional[float]:
    return (min(scores) if lower else max(scores)) if scores else None


def _gain(new: float, old: float, lower: bool) -> float:
    return old - new if lower else new - old


def _meets(score: float, target: float, lower: bool) -> bool:
    return score <= target if lower else score >= target


def can_reach(value: Optional[float], sr: Optional[Dict[str, Any]]) -> bool:
    """True when `value` meets the stop rule's target (direction-aware), or there is no target to miss."""
    target = (sr or {}).get("target")
    if target is None or value is None:
        return True
    return _meets(float(value), float(target), _lower(sr))


def approach_projection(ap: Dict[str, Any], sr: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """
    Where this approach lands at the end of its round budget: least-squares slope of best-so-far over
    the last TREND_WINDOW scored rounds, extended over the rounds left. None with fewer than 2 scores.
    """
    lower = _lower(sr)
    rounds = ap.get("rounds") or []
    scored = [float(r["score"]) for r in rounds if r.get("score") is not None]
    if len(scored) < 2:
        return None
    best_so_far: List[float] = []
    for s in scored:
        best_so_far.append(s if not best_so_far or _gain(s, best_so_far[-1], lower) > 0 else best_so_far[-1])
    pts = best_so_far[-TREND_WINDOW:]
    n = len(pts)
    mx, my = (n - 1) / 2.0, sum(pts) / n
    slope = sum((i - mx) * (y - my) for i, y in enumerate(pts)) / sum((i - mx) ** 2 for i in range(n))
    left = max(0, rule_cap(sr) - len(rounds))
    best = best_so_far[-1]
    return {"slope": slope, "left": float(left), "best": best, "projected": best + slope * left, "n": float(len(scored))}


def _norm_words(text: str) -> str:
    return re.sub(r"[\s_-]+", " ", text.lower()).strip()


def report_path(workspace: Path, hyp: str) -> Path:
    return Path(workspace).resolve() / "research" / "hypotheses" / hyp / "REPORT.md"


def report_section3(text: str) -> str:
    """Section 3 (Option Sweep) of a hypothesis REPORT.md; the whole text if there is no such heading."""
    m = re.search(r"^##(?!#)\s*3\b.*$", text, re.MULTILINE)
    if not m:
        return text
    end = re.search(r"^##(?!#)\s", text[m.end():], re.MULTILINE)
    return text[m.start(): m.end() + end.start()] if end else text[m.start():]


def family_in_report(workspace: Path, hyp: str, family: str) -> bool:
    rp = report_path(workspace, hyp)
    if not rp.is_file():
        return False
    text = rp.read_text(encoding="utf-8-sig", errors="replace")
    return _norm_words(family) in _norm_words(report_section3(text))


def report_baseline(workspace: Path, hyp: str, sr: Optional[Dict[str, Any]]) -> Optional[float]:
    """The one number on REPORT.md's 'Baseline To Beat' line (a/b and n% understood); None unless exactly one."""
    rp = report_path(workspace, hyp)
    if not rp.is_file():
        return None
    m = _BASELINE_LINE_RE.search(rp.read_text(encoding="utf-8-sig", errors="replace"))
    if not m or "<" in m.group(1):
        return None
    target = (sr or {}).get("target")
    values: List[float] = []
    for v in _BASELINE_VALUE_RE.finditer(m.group(1)):
        num = float(v.group(1))
        if v.group(2):
            den = float(v.group(2))
            values.append(num / den if den else num)
        elif v.group(3):
            # 62% is 0.62 on a 0..1 metric, 62 on a 0..100 one.
            values.append(num / 100.0 if target is not None and abs(target) <= 1 else num)
        else:
            values.append(num)
    return values[0] if len(values) == 1 else None


def sb_all_scores(state: Dict[str, Any], hyp: str) -> List[float]:
    sb = sb_get(state, hyp, create=False)
    return [r["score"] for ap in sb["approaches"].values() for r in ap.get("rounds", []) if r.get("score") is not None]


def quoted_score(text: str, scores: List[float]) -> Optional[str]:
    """First number in `text` equal to a scoreboard score. A bare 0-9 is too common to count as a quote."""
    if not scores:
        return None
    shown = {float(fmt_score(s)) for s in scores} | set(scores)
    for m in _NUM_TOKEN_RE.finditer(text):
        tok = m.group(0)
        if "." not in tok and len(tok.lstrip("-")) < 2:
            continue
        if float(tok) in shown:
            return tok
    return None


def unseen_target_met(state: Dict[str, Any], hyp: str) -> bool:
    """True when the stop rule has no target, or some --unseen round (any approach) met it."""
    found = metric_rule(state, hyp)
    if not found or found[1].get("target") is None:
        return True
    sr = found[1]
    sb = sb_get(state, hyp, create=False)
    return any(
        r.get("unseen") and r.get("score") is not None and _meets(r["score"], sr["target"], _lower(sr))
        for ap in sb["approaches"].values()
        for r in ap.get("rounds", [])
    )


def sb_record_round(
    workspace: Path,
    state: Dict[str, Any],
    hyp: str,
    family: str,
    *,
    score: Optional[float],
    unseen: bool,
    log: str,
    exit_code: Optional[int],
) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """Append one round and apply the plateau rules. Returns (notes to print, the lock it engaged or None)."""
    sb = sb_get(state, hyp)
    ap = sb["approaches"].setdefault(family, {"rounds": [], "status": "RACING"})
    earlier = [r["score"] for r in ap["rounds"] if r.get("score") is not None]
    ap["rounds"].append(
        {
            "t": _sb_now(),
            "score": score,
            "unseen": bool(unseen),
            "fingerprint": code_fingerprint(workspace, state, hyp),
            "log": log,
            "exit": exit_code,
        }
    )
    rounds = ap["rounds"]
    found = metric_rule(state, hyp)
    if not found or found[1].get("min_gain") is None or ap.get("status") == "WON":
        return [], None
    comp, sr = found
    lower = _lower(sr)
    target = sr.get("target")
    min_gain = float(sr["min_gain"])
    cap = rule_cap(sr)
    scored = earlier + ([score] if score is not None else [])

    if score is not None and unseen and target is not None and _meets(score, target, lower):
        ap["status"] = "WON"
        sb["grace"].pop(family, None)
        return [
            f"target met on unseen data ({fmt_score(score)} vs target {fmt_score(target)}) - move on: audit -> advance"
        ], None

    rule = reason = None
    if sb["grace"].pop(family, 0):
        prev = _best(earlier, lower)
        if score is None or (prev is not None and _gain(score, prev, lower) < min_gain - _EPS):
            rule, reason = "GRACE", (
                f"the grace round granted by CONTINUE scored {fmt_score(score)} and did not beat the previous best "
                f"{fmt_score(prev)} by min-gain {fmt_score(min_gain)}"
            )
    if rule is None and len(rounds) >= BLIND_ROUNDS and all(r.get("score") is None for r in rounds[-BLIND_ROUNDS:]):
        rule, reason = "BLIND", (
            f"{BLIND_ROUNDS} rounds in a row with no RA_SCORE - activity without a number can't show progress; "
            "print `RA_SCORE=<x>` from the run"
        )
    if rule is None and len(scored) >= FLAT_MIN_SCORED:
        # A window of 3 lets one noisy dip (30, 29, 25, 31) pass.
        recent, prior = _best(scored[-FLAT_WINDOW:], lower), _best(scored[:-FLAT_WINDOW], lower)
        gain = _gain(recent, prior, lower)
        if gain < min_gain - _EPS:
            rule, reason = "FLAT", (
                f"best of the last {FLAT_WINDOW} scored rounds ({fmt_score(recent)}) improves on the best of the "
                f"{len(scored) - FLAT_WINDOW} earlier one(s) ({fmt_score(prior)}) by {fmt_score(gain)} "
                f"< min-gain {fmt_score(min_gain)}"
            )
    baseline = report_baseline(workspace, hyp, sr)
    if rule is None and baseline is not None and len(scored) >= BASELINE_MIN_SCORED:
        if not any(_gain(s, baseline, lower) > _EPS for s in scored):
            rule, reason = "BASELINE", (
                f"{len(scored)} scored rounds never beat the baseline {fmt_score(baseline)} "
                f"(best {fmt_score(_best(scored, lower))}, REPORT.md 'Baseline To Beat')"
            )
    if rule is None and len(rounds) >= cap:
        rule, reason = "CAP", (
            f"{len(rounds)} rounds on `{family}` (cap {cap}) without meeting target {fmt_score(target)} on an --unseen round"
        )
    projected: Optional[float] = None
    if rule is None and target is not None and len(scored) >= TREND_MIN_SCORED:
        proj = approach_projection(ap, sr)
        floor = ap.get("trend_floor")
        # After a CONTINUE, only a projection worse than the one the reviewer accepted re-locks.
        if proj and not _meets(proj["projected"], target, lower) and (
            floor is None or _gain(proj["projected"], float(floor), lower) < -_EPS
        ):
            projected = proj["projected"]
            rule, reason = "TREND", (
                f"{proj['slope']:+.3g}/round with {int(proj['left'])} rounds left reaches ~{fmt_score(projected)}; "
                f"target {fmt_score(target)} - a fresh reviewer decides"
            )
    if rule is None:
        return [], None
    ap["status"] = "PLATEAUED"
    lock = {"approach": family, "rule": rule, "reason": f"{rule}: {reason}", "since": _sb_now(), "stop_rule": comp}
    if projected is not None:
        lock["projected"] = projected
    sb["lock"] = lock
    return [], lock


def sb_lock_instructions(state: Dict[str, Any], hyp: str) -> List[str]:
    sb = sb_get(state, hyp, create=False)
    lock = sb.get("lock") or {}
    if lock.get("rule") == "BRICK_FIRST":
        return [
            "A cold review said BRICK-FIRST. Conclude this hypothesis FALSIFIED",
            "(`ra_gate.py conclude --verdict FALSIFIED ...`) and open a new one whose goal is the end-to-end brick",
            "(`ra_gate.py new-hypothesis ...`).",
        ]
    if lock.get("rule") == "RESTART":
        return [
            "Your review decided RESTART. Conclude this hypothesis FALSIFIED",
            "(`ra_gate.py conclude --verdict FALSIFIED ...` with what it taught you) and open a new hypothesis",
            "(`ra_gate.py new-hypothesis ...`) built on the lessons, not a tweak of this one.",
        ]
    n = len(sb.get("cold_reviews") or []) + 1
    rel = f"research/hypotheses/{hyp}/COLD_REVIEW_{n}.md"
    return [
        "Dispatch a FRESH subagent (no history) with research/INVENTORY.md, REPORT.md Section 3 and this",
        "scoreboard (`ra_gate.py status --scoreboard`). It writes",
        f"{rel} ending in `VERDICT: CONTINUE|SWITCH|BRICK-FIRST`.",
        f"Then run `ra_gate.py cold-review --file {rel} --reviewer \"<agent id>\" [--next-approach <family>]`.",
    ]


def sb_lines(workspace: Path, state: Dict[str, Any], hyp: str) -> List[str]:
    """Plain-text scoreboard for one hypothesis (no leading indentation)."""
    found = metric_rule(state, hyp)
    sr = found[1] if found else None
    lower = _lower(sr)
    sb = sb_get(state, hyp, create=False)
    lines: List[str] = []
    if sr:
        cap = rule_cap(sr)
        lines.append(
            f"metric `{sr.get('metric') or '?'}` ({'lower' if lower else 'higher'} is better) | "
            f"target {fmt_score(sr.get('target'))} | min-gain {fmt_score(sr.get('min_gain'))} | "
            f"cap {cap} rounds/approach | stop rule `{found[0]}`"
        )
        baseline = report_baseline(workspace, hyp, sr)
        lines.append(
            f"baseline {fmt_score(baseline)} (REPORT.md 'Baseline To Beat')" if baseline is not None
            else "baseline: not parsed (write exactly one number on REPORT.md's 'Baseline To Beat' line to enable it)"
        )
    else:
        lines.append("no numeric stop rule for this hypothesis (`ra_gate.py stop-rule ... --metric --target --min-gain`)")
    if not sb["approaches"]:
        lines.append("no rounds yet (every `ra_log_engine.py run` is a round; print `RA_SCORE=<x>` from the program)")
    else:
        lines.append(
            f"{'approach':<20}{'rounds':>7}{'best':>10}{'last':>10}{'best-unseen':>12}{'ceiling':>9}{'proj':>9}  status"
        )
        for fam, ap in sb["approaches"].items():
            rounds = ap.get("rounds", [])
            scores = [r["score"] for r in rounds if r.get("score") is not None]
            unseen = [r["score"] for r in rounds if r.get("score") is not None and r.get("unseen")]
            last = rounds[-1].get("score") if rounds else None
            proj = approach_projection(ap, sr)
            lines.append(
                f"{fam:<20}{len(rounds):>7}{fmt_score(_best(scores, lower)):>10}{fmt_score(last):>10}"
                f"{fmt_score(_best(unseen, lower)):>12}{fmt_score((ap.get('ceiling') or {}).get('estimate')):>9}"
                f"{fmt_score(proj['projected'] if proj else None):>9}  {ap.get('status', 'RACING')}"
            )
            seq = ", ".join(fmt_score(r.get("score")) + ("u" if r.get("unseen") else "") for r in rounds[-12:])
            lines.append(f"    rounds: {'... ' if len(rounds) > 12 else ''}{seq}   (u = unseen, - = no RA_SCORE)")
    if sb["grace"]:
        lines.append("grace: " + ", ".join(f"{k} {v} round(s)" for k, v in sb["grace"].items()))
    lock = sb.get("lock")
    if lock:
        lines.append(f"LOCKED since {lock.get('since')} on approach `{lock.get('approach')}` - {lock.get('reason')}")
    else:
        lines.append("lock: none")
    reviews = sb.get("cold_reviews") or []
    if reviews:
        lines.append(
            f"cold reviews: {len(reviews)} - "
            + "; ".join(f"#{c.get('n')} {c.get('verdict')} on `{c.get('approach')}`" for c in reviews[-4:])
        )
    return lines


def sb_summary(state: Dict[str, Any], hyp: Optional[str]) -> Optional[str]:
    """One line for `ra_gate.py status`; None when there is nothing to show."""
    if not hyp:
        return None
    found = metric_rule(state, hyp)
    sb = sb_get(state, hyp, create=False)
    if not sb["approaches"]:
        if found and rule_has_numbers(found[1]):
            return f"no rounds yet (metric `{found[1].get('metric')}`, target {fmt_score(found[1].get('target'))})"
        return None
    lower = _lower(found[1] if found else None)
    parts = []
    for fam, ap in sb["approaches"].items():
        scores = [r["score"] for r in ap.get("rounds", []) if r.get("score") is not None]
        parts.append(f"{fam} {len(ap.get('rounds', []))}r best {fmt_score(_best(scores, lower))} [{ap.get('status', 'RACING')}]")
    lock = sb.get("lock")
    return "; ".join(parts) + (f" | LOCKED ({lock.get('rule')}) - see `status --scoreboard`" if lock else "")


def ceiling_block(state: Dict[str, Any], hyp: Optional[str], family: str) -> Optional[str]:
    """Why runs of `family` are refused by its paper ceiling (it can't reach the target), or None."""
    found = metric_rule(state, hyp) if hyp else None
    if not found:
        return None
    sr = found[1]
    ap = sb_get(state, hyp, create=False)["approaches"].get(family) or {}
    ceil = ap.get("ceiling") or {}
    est = ceil.get("estimate")
    if est is None or ceil.get("stepping_stone") or can_reach(est, sr):
        return None
    return (
        f"paper ceiling {fmt_score(est)} {'>' if _lower(sr) else '<'} target {fmt_score(sr.get('target'))} - change "
        f"architecture or justify with `ra_gate.py ceiling --approach {family} --estimate {fmt_score(est)} "
        f"--basis \"...\" --stepping-stone \"<why>\"`"
    )


# ---------------------------------------------------------------------------
# State file: one atomic writer for every script and hook (hooks fire concurrently)
# ---------------------------------------------------------------------------

_LOCK_WAIT_S = 1.0
_LOCK_STALE_S = 10.0


def state_file(workspace: Path) -> Path:
    return Path(workspace).resolve() / "research" / ".ra_state.json"


def read_state(workspace: Path) -> Optional[Dict[str, Any]]:
    """The parsed research/.ra_state.json, or None when it is missing or unreadable."""
    try:
        data = json.loads(state_file(workspace).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class _StateLock:
    """Best-effort lock file beside the state; after _LOCK_WAIT_S it proceeds unlocked rather than stall a hook."""

    def __init__(self, sp: Path) -> None:
        self.path = sp.with_name(sp.name + ".lock")
        self.held = False

    def __enter__(self) -> "_StateLock":
        deadline = time.monotonic() + _LOCK_WAIT_S
        while True:
            try:
                os.close(os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > _LOCK_STALE_S:
                        self.path.unlink()
                        continue
                except OSError:
                    pass
            except PermissionError:
                pass  # Windows: the previous holder's lock file is mid-delete
            except OSError:
                return self
            if time.monotonic() >= deadline:
                return self
            time.sleep(0.005)

    def __exit__(self, *exc: Any) -> None:
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)  # Windows refuses to replace a file another process is reading
    try:
        path.write_text(text, encoding="utf-8")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _dump_state(state: Dict[str, Any]) -> str:
    return json.dumps(state, indent=2, ensure_ascii=False) + "\n"


def write_state(workspace: Path, state: Dict[str, Any]) -> None:
    """Atomically write the whole state. state["lab"] belongs to the lab functions below, so the disk copy wins."""
    sp = state_file(workspace)
    sp.parent.mkdir(parents=True, exist_ok=True)
    with _StateLock(sp):
        disk = read_state(workspace)
        if disk is not None and isinstance(disk.get("lab"), dict):
            state["lab"] = disk["lab"]
        _atomic_write(sp, _dump_state(state))


# ---------------------------------------------------------------------------
# Lab state (state["lab"]): pending reviews, review meetings, manager-edit allowances, call counter
# ---------------------------------------------------------------------------

_LAB_FIELDS = (("pending_reviews", dict), ("reviews", list), ("manager_edit_allow", dict), ("main_tool_calls", int))


def _lab_of(state: Dict[str, Any]) -> Dict[str, Any]:
    lab = state.get("lab")
    if not isinstance(lab, dict):
        lab = state["lab"] = {}
    for key, typ in _LAB_FIELDS:
        val = lab.get(key)
        if not isinstance(val, typ) or isinstance(val, bool):
            lab[key] = typ()
    return lab


def _lab_update(workspace: Path, fn: Any, default: Any) -> Any:
    """Locked read-modify-write of state["lab"]. fn(lab) -> (result, changed). Never creates or clobbers a state."""
    try:
        sp = state_file(workspace)
        if not sp.is_file():
            return default
        with _StateLock(sp):
            state = read_state(workspace)
            if state is None:
                return default
            result, changed = fn(_lab_of(state))
            if changed:
                _atomic_write(sp, _dump_state(state))
            return result
    except Exception:
        return default


def _pending_sorted(lab: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    items = [(w, e) for w, e in lab["pending_reviews"].items() if isinstance(e, dict)]
    return sorted(items, key=lambda kv: str(kv[1].get("since", "")))


def review_pending(workspace: Path) -> List[str]:
    """Workers whose finished work the manager has not reviewed yet, oldest first."""
    try:
        state = read_state(workspace)
        return [w for w, _ in _pending_sorted(_lab_of(state))] if state else []
    except Exception:
        return []


def pending_reviews_detail(workspace: Path) -> List[Tuple[str, Dict[str, Any]]]:
    """(worker, {"since", "last", "events": [{"t", "sources"}]}) for every pending review, oldest first."""
    try:
        state = read_state(workspace)
        return _pending_sorted(_lab_of(state)) if state else []
    except Exception:
        return []


def mark_worker_finished(workspace: Path, worker: str, source: str) -> None:
    """Record that a worker finished and its report awaits review. Idempotent per worker + second."""
    name = str(worker or "").strip() or "unknown-worker"
    src = str(source or "").strip() or "unknown"
    t = _sb_now()

    def fn(lab: Dict[str, Any]) -> Tuple[None, bool]:
        entry = lab["pending_reviews"].get(name)
        if not isinstance(entry, dict):
            entry = lab["pending_reviews"][name] = {"since": t, "events": []}
        events = entry.setdefault("events", [])
        for ev in events:
            if ev.get("t") == t:
                if src in ev.setdefault("sources", []):
                    return None, False
                ev["sources"].append(src)
                return None, True
        events.append({"t": t, "sources": [src]})
        entry["last"] = t
        return None, True

    _lab_update(workspace, fn, None)


def clear_reviews(workspace: Path, workers: List[str]) -> None:
    def fn(lab: Dict[str, Any]) -> Tuple[None, bool]:
        gone = [w for w in workers if w in lab["pending_reviews"]]
        for w in gone:
            del lab["pending_reviews"][w]
        return None, bool(gone)

    _lab_update(workspace, fn, None)


def record_review(workspace: Path, entry: Dict[str, Any]) -> None:
    def fn(lab: Dict[str, Any]) -> Tuple[None, bool]:
        lab["reviews"].append(entry)
        return None, True

    _lab_update(workspace, fn, None)


def lab_reviews(workspace: Path) -> List[Dict[str, Any]]:
    try:
        state = read_state(workspace)
        return list(_lab_of(state)["reviews"]) if state else []
    except Exception:
        return []


def _path_key(workspace: Path, raw: str) -> Tuple[str, str]:
    """(comparison key, display path) of a file, workspace-relative when inside it."""
    ws = Path(workspace).resolve()
    p = Path(str(raw).strip())
    p = (p if p.is_absolute() else ws / p).resolve()
    try:
        shown = p.relative_to(ws).as_posix()
    except ValueError:
        shown = p.as_posix()
    return (shown.lower() if os.name == "nt" else shown), shown


def grant_manager_edit(workspace: Path, rel_path: str, reason: str, agent: str = "PRIMARY_AGENT") -> Optional[str]:
    """One-time allowance for the manager to edit `rel_path` itself; returns the display path, or None without a state."""
    try:
        key, shown = _path_key(workspace, rel_path)
    except (OSError, ValueError):
        return None

    def fn(lab: Dict[str, Any]) -> Tuple[str, bool]:
        lab["manager_edit_allow"][key] = {"path": shown, "reason": reason, "at": _sb_now(), "agent": agent}
        return shown, True

    return _lab_update(workspace, fn, None)


def consume_manager_edit(workspace: Path, rel_path: str) -> bool:
    """True (and the allowance is used up) if a one-time manager-edit allowance exists for this path."""
    try:
        key, _ = _path_key(workspace, rel_path)
    except (OSError, ValueError):
        return False

    def fn(lab: Dict[str, Any]) -> Tuple[bool, bool]:
        if key not in lab["manager_edit_allow"]:
            return False, False
        del lab["manager_edit_allow"][key]
        return True, True

    return bool(_lab_update(workspace, fn, False))


def record_main_tool_call(workspace: Path) -> int:
    """Count one main-agent tool call; returns the new total (0 when there is no RA state here)."""

    def fn(lab: Dict[str, Any]) -> Tuple[int, bool]:
        lab["main_tool_calls"] += 1
        return lab["main_tool_calls"], True

    try:
        return int(_lab_update(workspace, fn, 0))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# The lab board: the live picture pushed back at the lead agent (the lab manager)
# ---------------------------------------------------------------------------

DIRECTIVES_HEADER = "# Directives — the user's own words, verbatim. Everything else is an AI suggestion."
REVIEW_QUESTIONS = (
    "Are we closer to the target? (best vs target, per approach)",
    "Does each approach's trend reach the target within its round budget?",
    "Is another approach better, or dominating this one?",
    "KEEP, SWITCH, DROP or RESTART - per approach?",
    "What did we learn? (LESSON lines go to SELF_LEARNING.md and every next fork brief)",
)
MANAGER_LINE = "You are the lab manager: delegate, review, decide. Don't ask the user what you can decide or test."
_PLACEHOLDER_RE = re.compile(r"<[A-Za-z][^<>\n]{2,}>")
_BOARD_MAX_APPROACHES = 8


def _rdir(workspace: Path) -> Path:
    return Path(workspace).resolve() / "research"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _clip(text: Any, n: int) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[: n - 3] + "..."


def board_aim(workspace: Path) -> str:
    """First real content line under the first heading of research/VISION_AND_MISSION.md ("" if unwritten)."""
    lines = _read_text(_rdir(workspace) / "VISION_AND_MISSION.md").splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if ln.lstrip().startswith("#")), 0)
    for ln in lines[start:]:
        s = ln.strip()
        if not s or s.startswith(("#", ">", "<!--", "---", "|", "```", "===")):
            continue
        s = re.sub(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?", "", s)
        s = re.sub(r"^\*\*[^*\n]{1,40}\*\*\s*:\s*", "", s)
        if not s or _PLACEHOLDER_RE.search(s):
            return ""
        return _clip(s.replace("**", ""), 160)
    return ""


def read_directives(workspace: Path) -> List[Dict[str, str]]:
    """[{"id", "quote", "source"}] from research/DIRECTIVES.md, oldest first."""
    out: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for ln in _read_text(_rdir(workspace) / "DIRECTIVES.md").splitlines():
        m = re.match(r"^##\s+(U-\d+)\b", ln)
        if m:
            cur = {"id": m.group(1), "quote": [], "source": ""}
            out.append(cur)
        elif cur is not None and ln.startswith(">"):
            cur["quote"].append(ln[2:] if ln.startswith("> ") else ln[1:])
        elif cur is not None:
            ms = re.match(r"^\s*[-*]\s*\*\*Source\*\*\s*:\s*(.*)$", ln)
            if ms:
                cur["source"] = ms.group(1).strip()
    for d in out:
        d["quote"] = "\n".join(d["quote"]).strip()
    return [d for d in out if d["quote"]]


def decisions_count(workspace: Path) -> int:
    return len(re.findall(r"^## D-\d+", _read_text(_rdir(workspace) / "DECISIONS.md"), re.MULTILINE))


def brick_status(workspace: Path) -> str:
    """The `Brick status` value from research/INVENTORY.md section 3 ("" when missing or still a placeholder)."""
    m = re.search(
        r"\*\*Brick status\*\*\s*:\s*(.+)$", _read_text(_rdir(workspace) / "INVENTORY.md"), re.MULTILINE | re.IGNORECASE
    )
    if not m:
        return ""
    val = m.group(1).strip()
    return "" if val.startswith("<") or _PLACEHOLDER_RE.search(val) else _clip(val, 140)


def read_lessons(workspace: Path, n: int = 3) -> List[str]:
    """Last n `Found` / `LESSON:` lines of research/SELF_LEARNING.md (the template's baseline entry skipped)."""
    found: List[str] = []
    heading = ""
    for ln in _read_text(_rdir(workspace) / "SELF_LEARNING.md").splitlines():
        if ln.startswith("#"):
            heading = ln
            continue
        if "Initialization Baseline" in heading:
            continue
        m = re.match(r"^\s*[-*]\s*\*\*Found\*\*\s*:\s*(.+)$", ln) or re.match(r"^\s*LESSON\s*:\s*(.+)$", ln)
        if m:
            found.append(_clip(m.group(1), 200))
    return found[-n:] if n > 0 else []


def _approach_rows(
    state: Dict[str, Any], hyp: str, sr: Optional[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(active rows ranked best-projected first, retired rows)."""
    lower = _lower(sr)
    sb = sb_get(state, hyp, create=False)
    lock = sb.get("lock") or {}
    rows: List[Dict[str, Any]] = []
    for fam, ap in sb["approaches"].items():
        if not isinstance(ap, dict):
            continue
        rounds = ap.get("rounds") or []
        scores = [r["score"] for r in rounds if r.get("score") is not None]
        ceil = ap.get("ceiling") or {}
        status = ap.get("status", "RACING")
        rows.append(
            {
                "family": fam,
                "ap": ap,
                "rounds": len(rounds),
                "n_scored": len(scores),
                "best": _best(scores, lower),
                "last": rounds[-1].get("score") if rounds else None,
                "ceiling": ceil.get("estimate"),
                "stepping": bool(ceil.get("stepping_stone")),
                "proj": approach_projection(ap, sr),
                "status": status,
                "retired": status in RETIRED_STATUSES,
                "locked": bool(lock) and lock.get("approach") == fam,
            }
        )

    def rank(r: Dict[str, Any]) -> Tuple[int, float]:
        v = r["proj"]["projected"] if r["proj"] else r["best"]
        return (1, 0.0) if v is None else (0, v if lower else -v)

    return sorted([r for r in rows if not r["retired"]], key=rank), [r for r in rows if r["retired"]]


def _dominated_by(r: Dict[str, Any], active: List[Dict[str, Any]], lower: bool) -> Optional[Dict[str, Any]]:
    if not r["proj"] or r["best"] is None or r["status"] == "WON":
        return None
    for o in active:
        if o is r or not o["proj"] or o["best"] is None:
            continue
        if _gain(o["best"], r["best"], lower) >= 0 and _gain(o["proj"]["projected"], r["proj"]["projected"], lower) > _EPS:
            return o
    return None


def _ceiling_blocked(r: Dict[str, Any], sr: Optional[Dict[str, Any]]) -> bool:
    return r["ceiling"] is not None and not r["stepping"] and not can_reach(r["ceiling"], sr)


def _concern(r: Dict[str, Any], active: List[Dict[str, Any]], sr: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why this approach should be dropped or justified, or None."""
    if r["status"] == "WON":
        return None
    fam = r["family"]
    t = fmt_score((sr or {}).get("target"))
    if _ceiling_blocked(r, sr):
        return (
            f"paper ceiling {fmt_score(r['ceiling'])} can't reach target {t} "
            f"(`ra_gate.py ceiling --approach {fam} ... --stepping-stone \"<why>\"`, or review DECISION: {fam}: DROP)"
        )
    if r["ap"].get("kept_at_round") == r["rounds"]:
        return None  # a review already chose KEEP at this round
    p = r["proj"]
    how = f"(review DECISION: {fam}: DROP, or KEEP with the reason)"
    if p and r["n_scored"] >= TREND_MIN_SCORED and not can_reach(p["projected"], sr):
        return f"its trend reaches ~{fmt_score(p['projected'])} by the end of its budget, target {t} {how}"
    dom = _dominated_by(r, active, _lower(sr))
    if dom:
        return (
            f"dominated by {dom['family']} (best {fmt_score(r['best'])} vs {fmt_score(dom['best'])}, "
            f"projection ~{fmt_score(p['projected'])} vs ~{fmt_score(dom['proj']['projected'])}) {how}"
        )
    return None


def _board_ctx(workspace: Path) -> Optional[Dict[str, Any]]:
    state = read_state(workspace)
    if state is None:
        return None
    hyp = state.get("active_hypothesis") or None
    found = metric_rule(state, hyp) if hyp else None
    sr = found[1] if found else None
    lab = _lab_of(state)
    active, retired = _approach_rows(state, hyp, sr) if hyp else ([], [])
    brick = brick_status(workspace)
    return {
        "state": state,
        "hyp": hyp,
        "comp": found[0] if found else None,
        "sr": sr,
        "lock": (sb_get(state, hyp, create=False).get("lock") if hyp else None) or None,
        "active": active,
        "retired": retired,
        "pending": _pending_sorted(lab),
        "reviews": lab["reviews"],
        "brick": brick,
        "brick_not_built": "NOT BUILT" in brick.upper(),
    }


def _next_decision(ctx: Dict[str, Any]) -> str:
    review_cmd = f"ra_gate.py review --file research/reviews/REVIEW_{len(ctx['reviews']) + 1}.md"
    if ctx["pending"]:
        names = [w for w, _ in ctx["pending"]]
        who = f"worker {names[0]}'s report" if len(names) == 1 else f"workers {', '.join(names)}' reports"
        return f"Review {who} ({review_cmd})"
    lock = ctx["lock"]
    if lock:
        if lock.get("rule") in ("BRICK_FIRST", "RESTART"):
            return f"{lock.get('reason')} - conclude FALSIFIED (ra_gate.py conclude) and open a new hypothesis"
        return f"{lock.get('reason')} - get a cold review (steps: ra_gate.py status --scoreboard)"
    if ctx["brick_not_built"]:
        return "build the brick: research/INVENTORY.md section 3 says NOT BUILT - crudest end-to-end version first"
    hyp, sr = ctx["hyp"], ctx["sr"]
    if not hyp:
        return "open the next hypothesis (ra_gate.py new-hypothesis --id <H> --slug <slug>)"
    if not sr or not rule_has_numbers(sr):
        return f"register the numeric stop rule for {hyp} (ra_gate.py stop-rule ... --metric --target --min-gain)"
    active = ctx["active"]
    won = next((r for r in active if r["status"] == "WON"), None)
    if won:
        return f"{won['family']} met the target on unseen data - audit, advance and conclude PROVEN"
    for r in reversed(active):
        why = _concern(r, active, sr)
        if why:
            return f"drop or justify {r['family']}: {why}"
    runnable = [r for r in active if not _ceiling_blocked(r, sr)]
    if not any(r["rounds"] for r in runnable):
        return "race the Option Sweep families (ra_log_engine.py run --approach <family> ...)"
    return f"next round on the best-projected approach {runnable[0]['family']}"


def next_decision(workspace: Path) -> str:
    """The one thing the lab manager should do next ("" when there is no RA state here)."""
    try:
        ctx = _board_ctx(workspace)
        return _next_decision(ctx) if ctx else ""
    except Exception:
        return ""


def _approach_line(r: Dict[str, Any], cap: int) -> str:
    p = r["proj"]
    proj = (f"~{fmt_score(p['projected'])}" + ("" if r["n_scored"] >= TREND_MIN_SCORED else "?")) if p else "-"
    ceil = (fmt_score(r["ceiling"]) + ("*" if r["stepping"] else "")) if r["ceiling"] is not None else "-"
    status = r["status"] + (" [LOCKED]" if r["locked"] else "")
    return (
        f"  {_clip(r['family'], 18):<18} ceiling {ceil:<7} {r['rounds']:>2}/{cap:<3} best {fmt_score(r['best']):<8} "
        f"last {fmt_score(r['last']):<8} proj {proj:<9} {status}"
    )


def _board_full(workspace: Path, ctx: Dict[str, Any]) -> str:
    hyp, sr, comp = ctx["hyp"], ctx["sr"], ctx["comp"]
    out: List[str] = ["=" * 30 + " RA LAB BOARD " + "=" * 30]
    out.append(f"AIM          : {board_aim(workspace) or 'not written - first line of research/VISION_AND_MISSION.md'}")
    if sr and rule_has_numbers(sr):
        lower = _lower(sr)
        out.append(
            f"  stop rule  : `{sr.get('metric')}` {'<=' if lower else '>='} {fmt_score(sr.get('target'))} "
            f"({'lower' if lower else 'higher'} is better) | budget {rule_cap(sr)} rounds/approach | "
            f"min-gain {fmt_score(sr.get('min_gain'))} | `{comp}` on {hyp}"
        )
    elif hyp:
        out.append(f"  stop rule  : none with numbers for {hyp}")
    else:
        out.append("  hypothesis : none open")
    dirs = read_directives(workspace)
    out.append(f"USER SAID    : {len(dirs)} directive(s), verbatim (research/DIRECTIVES.md) - the only rules that are the user's")
    for d in dirs[-5:]:
        src = f" ({_clip(d['source'], 40)})" if d["source"] else ""
        out.append(f"  {d['id']} \"{_clip(d['quote'], 110)}\"{src}")
    out.append(f"AI DECISIONS : {decisions_count(workspace)} in research/DECISIONS.md - reversible suggestions, not law")
    out.append(f"BRICK        : {ctx['brick'] or 'status not written (research/INVENTORY.md section 3)'}")
    if hyp:
        target = fmt_score((sr or {}).get("target"))
        out.append(f"APPROACHES   : {hyp}, ranked by projection at budget end (target {target}; ?=early, *=stepping stone)")
        active, cap = ctx["active"], rule_cap(sr)
        for r in active[:_BOARD_MAX_APPROACHES]:
            out.append(_approach_line(r, cap))
        if len(active) > _BOARD_MAX_APPROACHES:
            out.append(f"  ... {len(active) - _BOARD_MAX_APPROACHES} more (ra_gate.py status --scoreboard)")
        if not active:
            out.append("  none on the board yet (ra_gate.py ceiling / ra_log_engine.py run --approach <family>)")
        if ctx["retired"]:
            out.append("  retired: " + ", ".join(f"{r['family']} ({r['status']})" for r in ctx["retired"]))
        if ctx["lock"]:
            out.append(f"  LOCK       : {_clip(ctx['lock'].get('reason'), 150)}")
    if ctx["pending"]:
        parts = [f"{w} ({len(e.get('events') or [])} report(s))" for w, e in ctx["pending"]]
        total = sum(len(e.get("events") or []) for _, e in ctx["pending"])
        out.append(f"REVIEWS      : NOT REVIEWED - {', '.join(parts)}; {total} report(s) since the last review")
    else:
        out.append("REVIEWS      : nothing waiting for review")
    if ctx["reviews"]:
        last = ctx["reviews"][-1]
        out.append(f"  last review: #{last.get('n')} at {last.get('at')} ({last.get('file')})")
    lessons = read_lessons(workspace, 3)
    out.append(f"LESSONS      : {'last ' + str(len(lessons)) if lessons else 'none recorded yet (review LESSON: lines)'}")
    for ls in lessons:
        out.append(f"  - {_clip(ls, 150)}")
    out.append(f"NEXT DECISION: {_next_decision(ctx)}")
    out.append(MANAGER_LINE)
    out.append("=" * 74)
    return "\n".join(_clip(ln, 200) if len(ln) > 200 else ln for ln in out)


def _board_summary(workspace: Path, ctx: Dict[str, Any]) -> str:
    hyp, sr = ctx["hyp"], ctx["sr"]
    parts: List[str] = []
    if hyp:
        tgt = f"target {fmt_score(sr.get('target'))}" if sr and sr.get("target") is not None else "no target"
        aps = ", ".join(
            f"{r['family']} best {fmt_score(r['best'])}"
            + (f" proj ~{fmt_score(r['proj']['projected'])}" if r["proj"] else "")
            + ("?" if r["proj"] and r["n_scored"] < TREND_MIN_SCORED else "")
            for r in ctx["active"][:3]
        )
        parts.append(f"{hyp} ({tgt}): {aps or 'no approach on the board yet'}")
    else:
        parts.append("no open hypothesis")
    if ctx["lock"]:
        parts.append(f"LOCKED {ctx['lock'].get('rule')} on {ctx['lock'].get('approach')}")
    if ctx["pending"]:
        parts.append("NOT REVIEWED: " + ", ".join(w for w, _ in ctx["pending"]))
    parts.append(f"{len(read_directives(workspace))} user directive(s), {decisions_count(workspace)} AI decision(s)")
    return _clip("[RA BOARD] " + " | ".join(parts), 240) + "\n" + _clip("[RA NEXT] " + _next_decision(ctx), 240)


def _board(workspace: Path, mode: str = "full") -> str:
    ctx = _board_ctx(workspace)
    if ctx is None:
        return ""
    return _board_summary(workspace, ctx) if mode == "summary" else _board_full(workspace, ctx)


def render_board(workspace: Path, mode: str = "full") -> str:
    """The lab board: "full" (<= ~40 lines) or "summary" (2 lines); "" when research/.ra_state.json doesn't exist."""
    try:
        return _board(workspace, mode)
    except Exception:
        return ""
