#!/usr/bin/env python3
"""
ra_cheese_audit.py — Automated Anti-Cheese, Band-Aid & Axiom Seal Auditor for RA.

Scans sandbox prototypes and sealed axiom files for:
1. Cryptographic Axiom Seal tampering (Broken-Window hardcode slippery slope).
2. Poison / unverified comments (`# hardcoded`, `# hack`, `# workaround`, bare `# untrusted`).
3. Duct-tape band-aid patches (`except: pass`, silent error swallowing).
4. Algorithmic fraud / Cheesing (`if x == const: return const` chains or unsealed lookup tables).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import warnings
import re
import sys
from bisect import bisect_right
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

CODE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".php", ".kt", ".kts", ".dart",
    ".rs", ".c", ".cpp", ".h", ".hpp", ".cu", ".go", ".cs", ".java", ".wgsl", ".glsl", ".hlsl", ".lua", ".jl",
}

# Matched case-insensitively against directory names; pruned before descending.
PRUNED_DIR_NAMES = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "jspm_packages", "venv", ".venv", "env",
    "virtualenv", "site-packages", "__pycache__", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    "dist", "build", "builds", "out", "target", "obj", "bin", "library", "temp", ".gradle", ".next", ".nuxt",
    ".svelte-kit", ".dart_tool", ".expo", "vendor", "third_party", "third-party", "thirdparty", "external",
    "coverage", "pods", "research", ".agents", ".claude", ".codex", ".gemini",
}
TEST_DIR_NAMES = {
    "test", "tests", "__tests__", "__mocks__", "spec", "specs", "testdata", "test_data", "fixtures", "androidtest",
}
_TEST_FILE_RE = re.compile(r"^test_.*\.py$|_test\.(py|go|dart|rs)$|\.(test|spec)\.[^.]+$|^conftest\.py$", re.IGNORECASE)
_TEST_CLASS_FILE_RE = re.compile(r"[a-z0-9](Tests?|Spec)\.(java|kt|kts|cs|php|dart)$")

SCAN_EXCLUSION_NOTE = (
    "test code (tests/, test/, __tests__/, spec/, fixtures/ dirs; test_*.py, *_test.*, *.test.*, *.spec.*, conftest.py), "
    "vendored/generated dirs (node_modules, venvs, .git and other dot-dirs, build, dist, out, bin, obj, Library, Temp, "
    ".gradle, third_party, vendor, external), RA state (research/), and minified files"
)
PYTHON_ONLY_NOTE = (
    "Python-only (AST): if/elif/match `== const -> return const` chains, constant lookup tables, broad silent "
    "`except`, `contextlib.suppress(Exception)`. Comment, empty-catch, `@ts-ignore`, `setTimeout`, fake-data, "
    "stub and pollution checks run on every language."
)
LOOKUP_TABLE_RULE = (
    "Lookup tables are flagged only when they look like answers to inputs: a dict with number/tuple keys and "
    "number/bool values, or a dict/list of pairs named like ANSWERS/EXPECTED/SOLUTIONS/LOOKUP. Label, translation, "
    "enum and alias tables (string values) are not flagged."
)

SNIPPET_MAX = 160

# Run on comment text only (strings and URLs never reach these).
POISON_COMMENT_PATTERNS = [
    (
        re.compile(r"^hard-?coded?\b", re.IGNORECASE),
        "Forbidden `# hardcoded` comment. Use sealed `AXIOMATIC_PRIMITIVES` for real math/syntax constants; never hardcode data.",
    ),
    (
        re.compile(r"^(hack|band-?aid|cheese|faked?|dummy\s+return|todo:\s*fix\s+later)\b(?!-)", re.IGNORECASE),
        "Detected shortcut/band-aid comment marker (`hack`/`band-aid`/`cheese`/`fake`). Replace with a first-principles mechanism.",
    ),
    (
        re.compile(r"^temporary\s+(fix|patch|workaround)\b", re.IGNORECASE),
        "Detected temporary workaround comment. RA forbids duct-tape patches.",
    ),
    (
        re.compile(r"\buntrusted\b(?!.*(H\d{3}|LIB-\d{3}|REF-\d{3}))", re.IGNORECASE),
        "Zero-Trust Comment Violation: Bare `untrusted` claim without citing a Hypothesis ID (`Hxxx`) or Library ID (`LIB-xxx`).",
    ),
]

BROAD_EXCEPT_MSG = "AST Band-Aid Violation — broad `except: pass` / `except Exception: ...` swallows upstream state corruption."
PY_EXCEPT_FALLBACK_RE = re.compile(r"\bexcept\s*(?:\(?\s*(?:Exception|BaseException)\s*\)?)?\s*(?:as\s+\w+)?\s*:\s*(?:pass|\.\.\.)\s*$")

# Run over the whole file with strings blanked (comments kept), so multi-line blocks match.
EMPTY_CATCH_PATTERNS = [
    re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}"),
    re.compile(r"\.catch\s*\(\s*(?:\(\s*[\w$]*\s*\)|[\w$]+)\s*=>\s*(?:\{\s*\}|null|undefined|void\s+0)\s*\)"),
    re.compile(r"\.catch\s*\(\s*function\s*[\w$]*\s*\([^)]*\)\s*\{\s*\}\s*\)"),
]
EMPTY_CATCH_MSG = "Band-Aid Violation: Empty `catch {}` / `.catch(() => {})` silently swallows upstream failures."

DATA_POLLUTION_PATTERNS = [
    (
        re.compile(r"\b(ground_truth|golden_output|expected_results|benchmark_answers|eval_labels)\b", re.IGNORECASE),
        "[DATA_POLLUTION_LEAK] Production/model code references ground-truth or evaluation answer identifiers. Keep eval ground truth strictly inside break-test harnesses (`break_tests.*`).",
    ),
    (
        re.compile(r"\bnan_to_num\b|\bfillna\s*\(\s*(?:value\s*=\s*)?0(?:\.0*)?\s*[,)]"),
        "[DATA_POLLUTION_MASKING] Silent `nan_to_num` / `fillna(0)` coerces corrupted upstream NaN/Null values into synthetic zeros, polluting downstream data. Fix the upstream producer instead.",
    ),
]

# `*_data` names in any case; MOCK_/FAKE_/DUMMY_ only as UPPER constants (`dummy_placeholders` is not one).
FAKE_DATA_RE = re.compile(
    r"\b(?i:mock_?data|fake_?data|dummy_?data|sample_?data|placeholder_?data)\b|\b(?:MOCK|FAKE|DUMMY)_[A-Z0-9_]+\b"
)
FAKE_DATA_MSG = "[EXPOSED_FAKE_DATA] Fake/mock/dummy data identifier found in non-test project code. Replace with a real upstream data pipe."
TODO_COMMENT_RE = re.compile(r"^(TODO|FIXME|XXX)\b", re.IGNORECASE)
TODO_MSG = "[EXPOSED_UNFINISHED_STUB] Unfinished `TODO`/`FIXME` stub left in codebase."
NOT_IMPLEMENTED_RE = re.compile(r"\braise\s+NotImplementedError\b|\bthrow\s+new\s+NotImplementedException\b")
NOT_IMPLEMENTED_MSG = "[EXPOSED_UNFINISHED_STUB] Hollow `NotImplementedError` / `NotImplementedException` stub — wire the real implementation."
TYPE_IGNORE_COMMENT_RE = re.compile(r"\btype:\s*ignore\b|@ts-(?:ignore|expect-error|nocheck)\b")
TYPE_IGNORE_MSG = "[EXPOSED_BANDAID] Type-check bypass (`@ts-ignore` / `type: ignore`) masking broken interface contract."
SET_TIMEOUT_RE = re.compile(r"\bsetTimeout\s*\(.*,\s*\d+\s*\)")
# A timer whose line names its purpose (polling, debounce, retry, animation...) is not a race band-aid.
TIMER_PURPOSE_RE = re.compile(
    r"poll|debounce|throttle|retr(?:y|ies)|backoff|interval|heartbeat|tick|animat|blink|toast|cooldown|expire|clearTimeout",
    re.IGNORECASE,
)
SET_TIMEOUT_MSG = "[EXPOSED_BANDAID] Suspicious `setTimeout(..., delay)` timing band-aid — verify whether this is masking an async race condition."

# --- Lexer: blank out strings and pull out comments, keeping offsets and line numbers intact. ---
_DQ = r'"(?:\\.|[^"\\\n])*"?'
_SQ = r"'(?:\\.|[^'\\\n])*'?"
_CHAR = r"'(?:\\.|[^'\\\n])'"
_TRIPLE = r'"""[\s\S]*?(?:"""|\Z)|\'\'\'[\s\S]*?(?:\'\'\'|\Z)'
_BACKTICK = r"`(?:\\[\s\S]|[^`\\])*`?"
_C_COMMENTS = r"/\*[\s\S]*?(?:\*/|\Z)|//[^\n]*"
_LEXER_SPECS = {
    "py": (r"#[^\n]*", "|".join((_TRIPLE, _DQ, _SQ))),
    "jl": (r"#=[\s\S]*?(?:=#|\Z)|#[^\n]*", "|".join((_TRIPLE, _DQ, _CHAR))),
    "php": (_C_COMMENTS + r"|#(?!\[)[^\n]*", "|".join((_DQ, _SQ))),
    "lua": (r"--\[(?P<lc>=*)\[[\s\S]*?(?:\](?P=lc)\]|\Z)|--[^\n]*",
            "|".join((r"\[(?P<ls>=*)\[[\s\S]*?(?:\](?P=ls)\]|\Z)", _DQ, _SQ))),
    "js": (_C_COMMENTS, "|".join((_BACKTICK, _DQ, _SQ))),
    "vue": (r"<!--[\s\S]*?(?:-->|\Z)|" + _C_COMMENTS, "|".join((_BACKTICK, _DQ, _SQ))),
    # Rust: a lone ' is a lifetime, not a string.
    "rs": (_C_COMMENTS, "|".join((r'b?r(?P<rh>#*)"[\s\S]*?"(?P=rh)', _DQ, _CHAR))),
    "cs": (_C_COMMENTS, "|".join((r'@"(?:""|[^"])*"?', _DQ, _SQ))),
    "kt": (_C_COMMENTS, "|".join((_TRIPLE, _DQ, _SQ))),
    "c": (_C_COMMENTS, "|".join((_DQ, _SQ))),
}
_LEXERS = {k: re.compile(f"(?P<com>{c})|(?P<str>{s})") for k, (c, s) in _LEXER_SPECS.items()}
_LEX_FAMILY = {
    ".py": "py", ".jl": "jl", ".php": "php", ".lua": "lua", ".rs": "rs", ".cs": "cs",
    ".kt": "kt", ".kts": "kt", ".dart": "kt", ".vue": "vue", ".svelte": "vue",
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".go": "js",
}
_NOT_NEWLINE_RE = re.compile(r"[^\n]")
_COMMENT_LEAD_RE = re.compile(r"^[\s/*#!<=\-]+")
_COMMENT_TAIL_RE = re.compile(r"(\*/|-->|=#|\]=*\])\s*$")


def _ra_common():
    # Same hashing as ra_gate.py; the script dir is not on sys.path under `python -I`.
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import ra_common

    return ra_common


def is_test_file_name(name: str) -> bool:
    return bool(_TEST_FILE_RE.search(name) or _TEST_CLASS_FILE_RE.search(name))


def walk_code_files(root: Path, skip_tests: bool = True) -> List[Path]:
    """Code files under `root`, pruning vendored/generated/VCS/venv dirs (and test code when `skip_tests`)."""
    found: List[Path] = []
    for cur, dirs, files in os.walk(root):
        kept = []
        for d in dirs:
            dl = d.lower()
            if dl in PRUNED_DIR_NAMES or (dl.startswith(".") and dl != ".github") or dl.endswith(".egg-info"):
                continue
            if skip_tests and dl in TEST_DIR_NAMES:
                continue
            if os.path.isfile(os.path.join(cur, d, "pyvenv.cfg")):  # a venv under any name
                continue
            kept.append(d)
        dirs[:] = sorted(kept)
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in CODE_EXTENSIONS and not (skip_tests and is_test_file_name(f)):
                found.append(Path(cur, f))
    return found


def ws_rel(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def read_source(path: Path) -> Optional[str]:
    """File text (UTF-8, BOM stripped, newlines normalised), or None when it is not UTF-8 text."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        return None


def is_minified(name: str, text: str) -> bool:
    if ".min." in name.lower():
        return True
    return len(text) > 4000 and len(text) / (text.count("\n") + 1) > 300


def snippet(line: str) -> str:
    s = line.strip().replace("`", "'")
    return s if len(s) <= SNIPPET_MAX else s[: SNIPPET_MAX - 3] + "..."


def format_finding(rel: str, line: int, msg: str, snip: str, md: bool = False) -> str:
    loc = f"`{rel}:{line}`" if md else f"{rel}:{line}"
    return f"{loc}: {msg} -> `{snip}`" if snip else f"{loc}: {msg}"


def lex_source(text: str, ext: str) -> Tuple[str, str, List[Tuple[int, str]]]:
    """(code, code_with_comments, comments) — strings blanked in both, comments also blanked in `code`.

    Both strings keep the length and line breaks of `text`; comments = (line, comment text without markers).
    """
    rx = _LEXERS[_LEX_FAMILY.get(ext, "c")]
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    code: List[str] = []
    keep: List[str] = []
    comments: List[Tuple[int, str]] = []
    pos = 0
    for m in rx.finditer(text):
        start, end = m.span()
        if start == end:
            continue
        tok = m.group(0)
        blank = _NOT_NEWLINE_RE.sub(" ", tok)
        code.append(text[pos:start])
        keep.append(text[pos:start])
        code.append(blank)
        if m.group("com") is not None:
            keep.append(tok)
            first = bisect_right(line_starts, start)
            for i, part in enumerate(tok.split("\n")):
                body = _COMMENT_TAIL_RE.sub("", _COMMENT_LEAD_RE.sub("", part)).strip()
                if body:
                    comments.append((first + i, body))
        else:
            keep.append(blank)
        pos = end
    code.append(text[pos:])
    keep.append(text[pos:])
    return "".join(code), "".join(keep), comments


# --------------------------------------------------------------------------- Python AST checks

_BROAD_EXCEPTIONS = {"<bare>", "Exception", "BaseException"}
_ANSWER_NAME_RE = re.compile(r"answer|expected|solution|precomputed|golden|cheat|oracle|lookup", re.IGNORECASE)


def _literal(node: ast.AST) -> Tuple[bool, Any]:
    """(True, value) for a constant, a signed number, or a tuple of those."""
    if isinstance(node, ast.Constant):
        return True, node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.USub, ast.UAdd))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float, complex))
    ):
        v = node.operand.value
        return True, -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Tuple) and node.elts:
        items = [_literal(e) for e in node.elts]
        if all(ok for ok, _ in items):
            return True, tuple(v for _, v in items)
    return False, None


def _is_number_like(v: Any) -> bool:
    if isinstance(v, tuple):
        return bool(v) and all(isinstance(x, (int, float)) for x in v)
    return isinstance(v, (int, float, complex))


def _exception_names(node: Optional[ast.AST]) -> Set[str]:
    if node is None:
        return {"<bare>"}
    if isinstance(node, ast.Tuple):
        return set().union(*(_exception_names(e) for e in node.elts)) if node.elts else set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    return set()


def _is_silent(body: List[ast.stmt]) -> bool:
    return all(isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) for s in body)


def _is_broad_suppress(expr: ast.AST) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    fn = expr.func
    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
    return name == "suppress" and any(_exception_names(a) & _BROAD_EXCEPTIONS for a in expr.args)


def _const_branch(test: ast.AST, body: List[ast.stmt]) -> Optional[Tuple[str, str]]:
    """(subject, returned constant) for `if subject == const: ... return const`, else None."""
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.Is))):
        return None
    left_const, right_const = _literal(test.left)[0], _literal(test.comparators[0])[0]
    if left_const == right_const:
        return None
    subject = ast.dump(test.comparators[0] if left_const else test.left)
    for stmt in body:
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            ok, val = _literal(stmt.value)
            if ok:
                return subject, repr(val)
    return None


def _cheese_chain(branches: List[Tuple[str, str]]) -> Optional[Tuple[int, int]]:
    """(branch count, distinct answers) when >= 4 branches on one subject return >= 3 distinct constants."""
    if not branches:
        return None
    values = [v for s, v in branches if s == branches[0][0]]
    # Few distinct answers (True/False parsers, bucketing) is a classifier, not a memorised answer table.
    if len(values) >= 4 and len(set(values)) >= 3:
        return len(values), len(set(values))
    return None


def _const_pattern(p: ast.AST) -> bool:
    if isinstance(p, ast.MatchValue):
        return _literal(p.value)[0]
    if isinstance(p, ast.MatchSingleton):
        return True
    if isinstance(p, ast.MatchOr):
        return all(_const_pattern(x) for x in p.patterns)
    return False


def _target_name(t: ast.AST) -> str:
    return t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else ""


def _chain_msg(n: int, distinct: int) -> str:
    return (
        f"AST Cheese Violation — Detected {n}-branch hardcoded `if input == const: return const` lookup chain "
        f"({distinct} distinct answers)."
    )


def _ast_cheese(tree: ast.AST) -> List[Tuple[str, int, str]]:
    out: List[Tuple[str, int, str]] = []
    elif_children: Set[int] = set()
    table_names: Dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if _target_name(t):
                    table_names[id(node.value)] = _target_name(t)
        elif isinstance(node, ast.AnnAssign) and node.value is not None and _target_name(node.target):
            table_names[id(node.value)] = _target_name(node.target)

    for node in ast.walk(tree):
        # if / elif chains (each chain reported once, at its head)
        if isinstance(node, ast.If) and id(node) not in elif_children:
            branches: List[Tuple[str, str]] = []
            cur = node
            while True:
                b = _const_branch(cur.test, cur.body)
                if b:
                    branches.append(b)
                if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
                    cur = cur.orelse[0]
                    elif_children.add(id(cur))
                else:
                    break
            hit = _cheese_chain(branches)
            if hit:
                out.append(("CHEESE", node.lineno, _chain_msg(*hit)))

        # runs of separate `if x == c: return v` statements (no elif)
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list) or len(stmts) < 4:
                continue
            run: List[Tuple[ast.stmt, Tuple[str, str]]] = []
            for st in stmts + [None]:
                b = _const_branch(st.test, st.body) if isinstance(st, ast.If) and not st.orelse else None
                if b and run and b[0] == run[0][1][0]:
                    run.append((st, b))
                    continue
                hit = _cheese_chain([x[1] for x in run])
                if hit:
                    out.append(("CHEESE", run[0][0].lineno, _chain_msg(*hit)))
                run = [(st, b)] if b else []

        if isinstance(node, ast.Match):
            vals: List[str] = []
            for case in node.cases:
                if case.guard is None and _const_pattern(case.pattern):
                    for st in case.body:
                        if isinstance(st, ast.Return) and st.value is not None:
                            ok, v = _literal(st.value)
                            if ok:
                                vals.append(repr(v))
                            break
            if len(vals) >= 4 and len(set(vals)) >= 3:
                out.append((
                    "CHEESE", node.lineno,
                    f"AST Cheese Violation — Detected {len(vals)}-case hardcoded `match x: case const: return const` lookup table.",
                ))

        pairs = None
        if isinstance(node, ast.Dict) and len(node.keys) > 20 and all(k is not None for k in node.keys):
            pairs, kind = list(zip(node.keys, node.values)), "dictionary"
        elif isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) > 20 and all(
            isinstance(e, (ast.Tuple, ast.List)) and len(e.elts) == 2 for e in node.elts
        ):
            pairs, kind = [(e.elts[0], e.elts[1]) for e in node.elts], "list of pairs"
        if pairs:
            lits = [(_literal(k), _literal(v)) for k, v in pairs]
            if all(k[0] and v[0] for k, v in lits):
                keys = [k[1] for k, _ in lits]
                vals_t = [v[1] for _, v in lits]
                name = table_names.get(id(node), "")
                numeric = kind == "dictionary" and all(map(_is_number_like, keys)) and all(map(_is_number_like, vals_t))
                named = bool(_ANSWER_NAME_RE.search(name)) and not any(
                    isinstance(v, str) and " " in v.strip() for v in vals_t
                )
                if numeric or named:
                    label = f" `{name}`" if name else ""
                    out.append((
                        "CHEESE", node.lineno,
                        f"AST Cheese Violation — Unsealed constant lookup {kind}{label} with {len(pairs)} entries mapping "
                        f"inputs to answers. If these are legitimate mathematical/structural axioms, move them to an "
                        f"axioms file and seal with `ra_gate.py seal-axioms`.",
                    ))
    return out


def _abstract_stub_lines(tree: ast.AST) -> Set[int]:
    """Lines of `raise NotImplementedError` that are abstract-method bodies, not unfinished stubs."""
    lines: Set[int] = set()
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            abstract = any(_target_name(d) == "abstractmethod" for d in fn.decorator_list)
            body = fn.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]
            if abstract or (len(body) == 1 and isinstance(body[0], ast.Raise)):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Raise):
                        lines.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    return lines


def audit_python_ast(
    source: str, is_break_test: bool
) -> Tuple[Optional[Tuple[int, str]], List[Tuple[str, int, str]], Set[int]]:
    """(parse error, findings, abstract-stub lines); findings = (category, line, message)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # the audited code's own SyntaxWarnings are not findings
            tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return (getattr(exc, "lineno", None) or 1, f"SyntaxError during AST audit: {getattr(exc, 'msg', exc)}"), [], set()

    findings: List[Tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if _exception_names(node.type) & _BROAD_EXCEPTIONS and _is_silent(node.body):
                findings.append(("BANDAID", node.lineno, BROAD_EXCEPT_MSG))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            if any(_is_broad_suppress(item.context_expr) for item in node.items):
                findings.append((
                    "BANDAID", node.lineno,
                    "AST Band-Aid Violation — `contextlib.suppress(Exception)` silently swallows upstream failures.",
                ))
    if not is_break_test:
        findings.extend(_ast_cheese(tree))
    return None, findings, _abstract_stub_lines(tree)


def audit_file(
    fpath: Path, sealed_rel_paths: set[str], workspace: Path, vibe: bool = False
) -> Tuple[str, List[Tuple[str, int, str, str]]]:
    """(status, findings). status: "ok" | "unreadable" | "minified".

    findings = (category, line, message, snippet); category: BANDAID, CHEESE, POLLUTION, FAKE, STUB, PARSE.
    `vibe` adds the --scan-project checks (fake data, stubs, type-check bypasses, setTimeout).
    """
    rel = ws_rel(fpath, workspace)
    is_sealed = rel in sealed_rel_paths
    fname_lower = fpath.name.lower()
    is_sdk_helper = fname_lower in {"ra_logger.py", "ra_logger.js", "ra_logger.ts", "ra_logger.mjs", "ralogger.php"}
    is_break_test = is_sdk_helper or "break_test" in fname_lower or is_test_file_name(fpath.name)

    text = read_source(fpath)
    if text is None:
        return "unreadable", []
    if is_minified(fpath.name, text):
        return "minified", []

    ext = fpath.suffix.lower()
    code, code_with_comments, comments = lex_source(text, ext)
    raw_lines = text.split("\n")
    code_lines = code.split("\n")
    found: Dict[Tuple[int, str], str] = {}

    def add(cat: str, line: int, msg: str) -> None:
        found.setdefault((line, msg), cat)

    for line, body in comments:
        for regex, msg in POISON_COMMENT_PATTERNS:
            if regex.search(body):
                add("BANDAID", line, msg)
        if vibe:
            if TODO_COMMENT_RE.search(body):
                add("STUB", line, TODO_MSG)
            if TYPE_IGNORE_COMMENT_RE.search(body):
                add("BANDAID", line, TYPE_IGNORE_MSG)

    abstract_lines: Set[int] = set()
    py_parsed = False
    if ext == ".py" and not is_sealed:
        err, ast_findings, abstract_lines = audit_python_ast(text, is_break_test)
        py_parsed = err is None
        if err:
            add("PARSE", err[0], err[1])
        for cat, line, msg in ast_findings:
            add(cat, line, msg)

    if ext == ".py":
        if not py_parsed:  # AST unavailable: one-line fallback
            for idx, cl in enumerate(code_lines, start=1):
                if PY_EXCEPT_FALLBACK_RE.search(cl):
                    add("BANDAID", idx, BROAD_EXCEPT_MSG)
    else:
        for rx in EMPTY_CATCH_PATTERNS:
            for m in rx.finditer(code_with_comments):
                add("BANDAID", code_with_comments.count("\n", 0, m.start()) + 1, EMPTY_CATCH_MSG)

    for idx, cl in enumerate(code_lines, start=1):
        if not is_break_test and not is_sealed:
            for regex, msg in DATA_POLLUTION_PATTERNS:
                if regex.search(cl):
                    add("POLLUTION", idx, msg)
        if vibe:
            if FAKE_DATA_RE.search(cl):
                add("FAKE", idx, FAKE_DATA_MSG)
            if NOT_IMPLEMENTED_RE.search(cl) and idx not in abstract_lines:
                add("STUB", idx, NOT_IMPLEMENTED_MSG)
            if SET_TIMEOUT_RE.search(cl) and not TIMER_PURPOSE_RE.search(raw_lines[idx - 1].replace("setTimeout", "")):
                add("BANDAID", idx, SET_TIMEOUT_MSG)

    findings = [
        (cat, line, msg, snippet(raw_lines[line - 1]) if 0 < line <= len(raw_lines) else "")
        for (line, msg), cat in found.items()
    ]
    findings.sort(key=lambda f: f[1])
    return "ok", findings


def emit_cold_eyes_review_brief(
    workspace: Path, code_files: List[Path], protected_hashes: Dict[str, str], violations: List[str]
) -> Path:
    rdir = workspace / "research"
    rdir.mkdir(parents=True, exist_ok=True)
    brief_path = rdir / "DATA_POLLUTION_REVIEW_BRIEF.md"

    clamp_re = re.compile(r"\b(np\.clip|torch\.clamp|Math\.clamp|min\s*\(|max\s*\(|fillna|nan_to_num)\b")
    mutation_re = re.compile(r"\b(global\s+\w+|\w+\[[^\]]+\]\s*=|\.pop\s*\(|\.clear\s*\()")

    clamp_hits: List[str] = []
    mutation_hits: List[str] = []

    for cf in code_files:
        rel = ws_rel(cf, workspace)
        text = read_source(cf)
        if text is None or is_minified(cf.name, text):
            continue
        for idx, line in enumerate(text.split("\n"), start=1):
            if clamp_re.search(line):
                clamp_hits.append(f"- `{rel}:{idx}`: `{snippet(line)}`")
            if mutation_re.search(line):
                mutation_hits.append(f"- `{rel}:{idx}`: `{snippet(line)}`")

    brief_md = (
        "# Cold-Eyes Semantic & Data-Pollution Review Brief\n\n"
        "> **Reviewer Mandate**: Inspect the hotspots below for **semantic band-aids** (rescaling/clamping outputs to hide upstream bugs) and **polluted data** (mutating shared input structures, leaking eval/test distributions, or silently coercing `NaN`/`Null` into `0`).\n\n"
        "## 1. Protected Working Nodes (`Symptom != Culprit` Lock)\n"
        + ("\n".join(f"- `{k}` (`SHA-256: {v[:12]}...`)" for k, v in protected_hashes.items()) or "- None registered")
        + "\n\n## 2. Numeric Clamping / Rescaling / Coercion Hotspots (Check for Semantic Band-Aids)\n"
        + ("\n".join(clamp_hits[:40]) or "- None detected")
        + "\n\n## 3. State & In-Place Input Mutation Hotspots (Check for Upstream Data Pollution)\n"
        + ("\n".join(mutation_hits[:40]) or "- None detected")
        + "\n\n## 4. Automated AST & Axiom Violations\n"
        + ("\n".join(f"- {v}" for v in violations) or "- Zero syntactic/AST violations")
        + "\n"
    )
    brief_path.write_text(brief_md, encoding="utf-8")
    return brief_path


def scan_existing_project_truth_path(workspace: Path, sealed_set: set[str]) -> None:
    """
    Scan an existing brownfield / mid-flight / vibe-coded project to expose:
      1. Symptom-swallowing band-aids (`except: pass`, `@ts-ignore`, timing hacks)
      2. Fake / mocked / hardcoded data left inside non-test code
      3. Unfinished hollow stubs (`TODO`, `FIXME`, `NotImplementedError`)
      4. Data pollution (`nan_to_num`, `fillna(0)`, ground-truth leakage)
    Writes `research/TRUTH_PATH_AUDIT.md` with a step-by-step Truth-Path Recovery Plan.
    """
    rdir = workspace / "research"
    rdir.mkdir(parents=True, exist_ok=True)
    report_path = rdir / "TRUTH_PATH_AUDIT.md"

    project_files = walk_code_files(workspace)

    buckets: Dict[str, List[str]] = {"BANDAID": [], "FAKE": [], "POLLUTION": [], "STUB": []}
    not_scanned: List[str] = []
    scanned = 0
    for pf in project_files:
        rel = ws_rel(pf, workspace)
        status, findings = audit_file(pf, sealed_set, workspace, vibe=True)
        if status != "ok":
            not_scanned.append(f"`{rel}` — {'not UTF-8 text' if status == 'unreadable' else 'minified'}")
            continue
        scanned += 1
        for cat, line, msg, snip in findings:
            if cat == "PARSE":
                not_scanned.append(f"`{rel}:{line}` — Python AST checks skipped: {msg}")
            else:
                buckets["BANDAID" if cat == "CHEESE" else cat].append(format_finding(rel, line, msg, snip, md=True))

    exposed_bandaids, exposed_fake_data = buckets["BANDAID"], buckets["FAKE"]
    exposed_pollution, exposed_stubs = buckets["POLLUTION"], buckets["STUB"]
    total_findings = sum(len(v) for v in buckets.values())
    if not project_files:
        project_tier = "FRESH_GREENFIELD"
    elif exposed_bandaids or exposed_fake_data or exposed_pollution:
        project_tier = "POLLUTED_VIBE_CODE_NEEDS_TRUTH_PATH"
    elif exposed_stubs:
        project_tier = "UNFINISHED_HALF_WIRED"
    else:
        project_tier = "CLEAN_PRODUCTION_TIER"

    md = (
        "# RA Truth-Path Project Intake & Pollution Audit (`TRUTH_PATH_AUDIT.md`)\n\n"
        f"- **Project Health Classification**: `{project_tier}`\n"
        f"- **Scanned Production Code Files**: `{scanned}`\n"
        f"- **Total Obstacles Exposed**: `{total_findings}`\n"
        f"- **Not Scanned**: `{len(not_scanned)}` (see section 6)\n"
        f"- **Excluded**: {SCAN_EXCLUSION_NOTE}.\n"
        f"- **Coverage**: {PYTHON_ONLY_NOTE}\n"
        f"- **Lookup-table rule**: {LOOKUP_TABLE_RULE}\n\n"
        "---\n\n"
        "## 1. Exposed Band-Aids & Symptom Bypasses (Replace with Upstream Root-Cause Fixes)\n"
        + ("\n".join(f"- {x}" for x in exposed_bandaids) or "- Zero band-aids detected.")
        + "\n\n## 2. Exposed Fake / Mocked / Hardcoded Data in Production Code\n"
        + ("\n".join(f"- {x}" for x in exposed_fake_data) or "- Zero fake/mocked data identifiers detected.")
        + "\n\n## 3. Exposed Data Pollution & Silent NaN/Null Coercion\n"
        + ("\n".join(f"- {x}" for x in exposed_pollution) or "- Zero data-pollution patterns detected.")
        + "\n\n## 4. Exposed Unfinished / Hollow Stubs (`TODO` / `FIXME` / `NotImplementedError`)\n"
        + ("\n".join(f"- {x}" for x in exposed_stubs) or "- Zero unfinished stubs detected.")
        + "\n\n---\n\n"
        "## 5. Truth-Path Recovery Protocol (How the AI Must Fix This Project)\n"
        "1. **Lock Innocent Working Modules First (`/ra-workflow-map`)**: Before fixing any exposed band-aid, trace `-N` to `+N` hops and register working functions via `ra_gate.py map-context --protected <file:func>`.\n"
        "2. **Remove Band-Aids & Wire Real Upstream Pipes (`/ra-systemic-debug`)**: Delete every `except: pass`, `@ts-ignore`, and fake data constant above and replace the broken upstream producer at its root cause.\n"
        "3. **Prove Execution with Deterministic `.log` Traces (`/ra-log-verify`)**: Verify each recovered pipe with `ra_log_engine.py run` and `ra_cheese_audit.py`.\n"
        "\n## 6. Not Scanned (Unreadable, Minified, or Unparseable — Review by Hand)\n"
        + ("\n".join(f"- {x}" for x in not_scanned) or "- None.")
        + "\n"
    )
    report_path.write_text(md, encoding="utf-8")

    print("=" * 78)
    print(f"  RA TRUTH-PATH PROJECT INTAKE AUDIT — TIER: {project_tier}")
    print("=" * 78)
    print(f"  Scanned Production Files : {scanned}")
    print(f"  Exposed Band-Aids/Cheese : {len(exposed_bandaids)}")
    print(f"  Exposed Fake/Mocked Data : {len(exposed_fake_data)}")
    print(f"  Exposed Data Pollution   : {len(exposed_pollution)}")
    print(f"  Exposed Unfinished Stubs : {len(exposed_stubs)}")
    print(f"  Not Scanned (see report) : {len(not_scanned)}")
    print(f"  Truth-Path Recovery Plan : {report_path.relative_to(workspace).as_posix()}")
    print(f"  Note: {PYTHON_ONLY_NOTE}")
    print("=" * 78)


def _utf8_console() -> None:
    # Windows consoles default to cp932/cp1252, which cannot print the report's dashes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> None:
    _utf8_console()
    parser = argparse.ArgumentParser(description="RA Automated Anti-Cheese, Data-Pollution & Axiom Seal Auditor")
    parser.add_argument("--workspace", default=".", help="Workspace root directory")
    parser.add_argument(
        "--hypothesis",
        default="STANDALONE",
        help="Active hypothesis folder name (e.g., H001_slug) or STANDALONE for partial mode",
    )
    parser.add_argument("--files", nargs="*", default=[], help="Optional explicit files to audit in standalone mode")
    parser.add_argument(
        "--emit-review-brief",
        action="store_true",
        help="Emit research/DATA_POLLUTION_REVIEW_BRIEF.md for a cold-eyes reviewer subagent",
    )
    parser.add_argument(
        "--scan-project",
        action="store_true",
        help="Scan an existing/mid-flight/vibe-coded project to expose band-aids, fake data, and polluted pipes into research/TRUTH_PATH_AUDIT.md",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"[RA CHEESE AUDIT] ERROR: Workspace directory not found: {workspace}", file=sys.stderr)
        sys.exit(2)
    rdir = workspace / "research"
    state_path = rdir / ".ra_state.json"

    state: Dict[str, Any] = (
        json.loads(state_path.read_text(encoding="utf-8-sig")) if state_path.exists() else {}
    )
    sealed_axioms: Dict[str, Any] = state.get("sealed_axioms", {})
    sealed_set = set(sealed_axioms.keys())
    protected_hashes: Dict[str, str] = state.get("protected_node_hashes", {})

    if args.scan_project:
        scan_existing_project_truth_path(workspace, sealed_set)
        return

    violations: List[str] = []

    # 1. Verify cryptographic seal on all registered axiom files
    rc = _ra_common()
    for rel_path, meta in sealed_axioms.items():
        seal_status, actual = rc.verify_seal(workspace / rel_path, meta)
        expected = meta.get("sha256", "")
        if seal_status == "MISSING":
            violations.append(f"AXIOM SEAL VIOLATION: Sealed axiom file `{rel_path}` was deleted!")
        elif seal_status == "TAMPERED":
            violations.append(
                f"AXIOM SEAL VIOLATION: `{rel_path}` was modified! Expected SHA-256 {expected[:12]}..., "
                f"got {actual[:12]}... Never sneak hardcoded data into sealed axioms!"
            )

    # 1b. Verify cryptographic lock on all PROTECTED_WORKING innocent nodes (`Symptom != Culprit`)
    for pnode, expected_phash in protected_hashes.items():
        node_status, actual_phash = rc.verify_protected_node(workspace, pnode, expected_phash)
        if node_status == "AMBIGUOUS":
            violations.append(
                f"[PROTECTED_NODE_TAMPERED] `PROTECTED_WORKING` node `{pnode}` now matches several definitions "
                f"({', '.join(rc.describe_matches(workspace, pnode))}) — a duplicate definition can shadow the locked one. "
                f"Remove the duplicate, or revoke and re-register a qualified `file:Class.method` spec."
            )
        elif node_status == "MISSING":
            violations.append(
                f"[PROTECTED_NODE_TAMPERED] Innocent `PROTECTED_WORKING` node `{pnode}` was deleted or renamed! "
                f"(If real data exposed `{pnode}` as corrupted, unlock it first via `ra_gate.py map-context --revoke-protected {pnode} --revoke-reason \"...\"`)."
            )
        elif node_status == "TAMPERED":
            violations.append(
                f"[PROTECTED_NODE_TAMPERED] Innocent `PROTECTED_WORKING` node `{pnode}` was modified "
                f"(expected SHA-256 {expected_phash[:12]}..., got {actual_phash[:12]}...)! "
                f"If `{pnode}` is an innocent bystander (`Symptom != Culprit`), revert it immediately. "
                f"If fixing an upstream pipe to pass REAL data exposed that `{pnode}` could only handle old fake/band-aid data, "
                f"forensically unlock it first via `ra_gate.py map-context --revoke-protected {pnode} --revoke-reason \"<[RA_LOG] proof>\"`."
            )

    # 2. Scan explicit --files, the hypothesis sandbox, or (STANDALONE) the whole project
    sandbox_dir = rdir / "sandbox" / args.hypothesis
    code_files: List[Path] = []
    if args.files:
        for fstr in args.files:
            fp = (workspace / fstr).resolve()
            if not fp.is_file():
                print(f"[RA CHEESE AUDIT] ERROR: --files path not found: {fstr}", file=sys.stderr)
                sys.exit(2)
            if not fp.is_relative_to(workspace):
                print(f"[RA CHEESE AUDIT] ERROR: --files path is outside the workspace ({workspace}): {fstr}", file=sys.stderr)
                sys.exit(2)
            code_files.append(fp)
        scope = "--files"
    elif args.hypothesis == "STANDALONE":
        candidates = walk_code_files(workspace)
        if sandbox_dir.is_dir():
            candidates += walk_code_files(sandbox_dir, skip_tests=False)
        for rel_t in state.get("context_map_snapshot", {}).get("tracked_files", {}).keys():
            fp = workspace / rel_t
            if fp.is_file() and fp.suffix.lower() in CODE_EXTENSIONS:
                candidates.append(fp)
        seen: Set[Path] = set()
        for fp in candidates:
            if fp.resolve() not in seen:
                seen.add(fp.resolve())
                code_files.append(fp.resolve())
        scope = "project (STANDALONE)"
    elif sandbox_dir.is_dir():
        code_files = walk_code_files(sandbox_dir, skip_tests=False)
        scope = f"research/sandbox/{args.hypothesis}/"
    else:
        print(f"[RA CHEESE AUDIT] ERROR: Sandbox directory not found: {sandbox_dir}", file=sys.stderr)
        sys.exit(1)
    if not code_files:
        violations.append(f"No code files found in {scope} to audit.")

    not_scanned: List[str] = []
    audited = 0
    for cf in code_files:
        rel = ws_rel(cf, workspace)
        status, findings = audit_file(cf, sealed_set, workspace)
        if status != "ok":
            not_scanned.append(f"{rel} ({'not UTF-8 text' if status == 'unreadable' else 'minified'})")
            continue
        audited += 1
        violations.extend(format_finding(rel, line, msg, snip) for _, line, msg, snip in findings)

    brief_path = None
    if args.emit_review_brief:
        brief_path = emit_cold_eyes_review_brief(workspace, code_files, protected_hashes, violations)

    print("=" * 78)
    print(f"  RA ANTI-CHEESE, DATA-POLLUTION & AXIOM SEAL AUDIT — HYPOTHESIS: {args.hypothesis}")
    print("=" * 78)
    print(f"  Scope               : {scope}")
    print(f"  Audited Code Files  : {audited}")
    if not_scanned:
        more = " ..." if len(not_scanned) > 10 else ""
        print(f"  Not Scanned         : {len(not_scanned)}, not violations ({', '.join(not_scanned[:10])}{more})")
    print(f"  Protected Nodes     : {len(protected_hashes)}")
    print(f"  Sealed Axiom Files  : {len(sealed_axioms)}")
    print(f"  Violations Found    : {len(violations)}")
    if brief_path:
        print(f"  Review Brief Out    : {brief_path.relative_to(workspace).as_posix()}")
    print(f"  Note: {PYTHON_ONLY_NOTE}")
    print("-" * 78)

    if violations:
        if state_path.exists():
            state["cheese_audit_passed"] = False
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("  [FAIL] AUDIT REJECTED THE PROTOTYPE FOR THE FOLLOWING REASONS:")
        for v in violations:
            print(f"    - {v}")
        print("-" * 78)
        print("  REQUIRED ACTION:")
        print("    - If you hit an algorithmic wall and tried to hardcode data or add a band-aid:")
        print("      STOP! Falsify this hypothesis (`ra_gate.py conclude --verdict FALSIFIED ...`)")
        print("      and invent a new mathematical/architectural hypothesis.")
        print("=" * 78)
        sys.exit(1)

    if state_path.exists():
        state["cheese_audit_passed"] = True
        state.setdefault("pass_fingerprints", {})["cheese_audit_passed"] = rc.code_fingerprint(
            workspace, state, args.hypothesis
        )
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("  [PASS] Zero cheese, zero band-aids, and all axiom seals verified!")
    print("         Ensure `ra_log_engine.py audit` and `ra_visual_audit.py audit` also pass, then run `ra_gate.py advance` to proceed to Stage 6.")
    print("=" * 78)


if __name__ == "__main__":
    main()
