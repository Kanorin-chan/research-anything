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
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".c", ".cpp", ".h", ".hpp",
    ".cu", ".go", ".cs", ".java", ".wgsl", ".glsl", ".hlsl", ".lua", ".jl"
}

POISON_COMMENT_PATTERNS = [
    (
        re.compile(r"(#|//)\s*hardcode(d)?\b", re.IGNORECASE),
        "Forbidden `# hardcoded` comment. Use sealed `AXIOMATIC_PRIMITIVES` for real math/syntax constants; never hardcode data.",
    ),
    (
        re.compile(r"(#|//)\s*(hack|band-?aid|cheese|faked?|dummy\s+return|todo:\s*fix\s+later)\b", re.IGNORECASE),
        "Detected shortcut/band-aid comment marker (`hack`/`band-aid`/`cheese`/`fake`). Replace with a first-principles mechanism.",
    ),
    (
        re.compile(r"(#|//)\s*temporary\s+(fix|patch|workaround)\b", re.IGNORECASE),
        "Detected temporary workaround comment. RA forbids duct-tape patches.",
    ),
    (
        re.compile(r"(#|//).*\buntrusted\b(?!.*(H\d{3}|LIB-\d{3}|REF-\d{3}))", re.IGNORECASE),
        "Zero-Trust Comment Violation: Bare `untrusted` claim without citing a Hypothesis ID (`Hxxx`) or Library ID (`LIB-xxx`).",
    ),
]

BANDAID_REGEX_PATTERNS = [
    (
        re.compile(r"except\s*(Exception|BaseException)?\s*:\s*pass\b"),
        "Band-Aid Violation: Silent `except: pass` error swallowing masks upstream broken invariants.",
    ),
    (
        re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}"),
        "Band-Aid Violation: Empty `catch {}` block silently swallows upstream failures.",
    ),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_constant_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant)


def audit_python_ast(fpath: Path, source: str, is_break_test: bool) -> List[str]:
    issues: List[str] = []
    try:
        tree = ast.parse(source, filename=str(fpath))
    except SyntaxError as exc:
        return [f"{fpath.name}:{exc.lineno}: SyntaxError during AST audit: {exc.msg}"]

    for node in ast.walk(tree):
        # 1. Check silent except handlers
        if isinstance(node, ast.ExceptHandler):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                issues.append(
                    f"{fpath.name}:{node.lineno}: AST Band-Aid Violation — `except ...: pass` swallows upstream state corruption."
                )

        if is_break_test:
            continue

        # 2. Check suspicious `if x == const: return const` chains (>= 4 branches) in non-test code
        if isinstance(node, ast.If):
            branch_count = 0
            curr: ast.AST | None = node
            while isinstance(curr, ast.If):
                has_const_cmp = isinstance(curr.test, ast.Compare) and any(
                    is_constant_node(c) for c in curr.test.comparators
                )
                has_const_ret = any(
                    isinstance(stmt, ast.Return) and stmt.value is not None and is_constant_node(stmt.value)
                    for stmt in curr.body
                )
                if has_const_cmp and has_const_ret:
                    branch_count += 1
                if len(curr.orelse) == 1 and isinstance(curr.orelse[0], ast.If):
                    curr = curr.orelse[0]
                else:
                    break
            if branch_count >= 4:
                issues.append(
                    f"{fpath.name}:{node.lineno}: AST Cheese Violation — Detected {branch_count}-branch hardcoded "
                    f"`if input == const: return const` lookup chain."
                )

        # 3. Check unsealed large constant lookup dictionaries (> 20 literal key-value pairs) in non-axiom model code
        if isinstance(node, ast.Dict):
            if len(node.keys) > 20 and all(
                k is not None and is_constant_node(k) and is_constant_node(v)
                for k, v in zip(node.keys, node.values)
            ):
                issues.append(
                    f"{fpath.name}:{node.lineno}: AST Cheese Violation — Unsealed constant lookup dictionary with "
                    f"{len(node.keys)} entries. If these are legitimate mathematical/structural axioms, move them "
                    f"to an axioms file and seal with `ra_gate.py seal-axioms`."
                )

    return issues


def audit_file(fpath: Path, sealed_rel_paths: set[str], workspace: Path) -> List[str]:
    issues: List[str] = []
    rel = fpath.resolve().relative_to(workspace.resolve()).as_posix()
    is_sealed = rel in sealed_rel_paths
    is_sdk_helper = fpath.name.lower() in {"ra_logger.py", "ra_logger.js", "ralogger.php"}

    try:
        text = fpath.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"{rel}: Could not read file as UTF-8: {exc}"]

    for idx, line in enumerate(text.splitlines(), start=1):
        for regex, msg in POISON_COMMENT_PATTERNS:
            if regex.search(line):
                issues.append(f"{rel}:{idx}: {msg} -> `{line.strip()}`")
        for regex, msg in BANDAID_REGEX_PATTERNS:
            if regex.search(line):
                issues.append(f"{rel}:{idx}: {msg} -> `{line.strip()}`")

    if fpath.suffix.lower() == ".py" and not is_sealed:
        issues.extend(audit_python_ast(fpath, text, is_sdk_helper))

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="RA Automated Anti-Cheese & Axiom Seal Auditor")
    parser.add_argument("--workspace", default=".", help="Workspace root directory")
    parser.add_argument(
        "--hypothesis",
        default="STANDALONE",
        help="Active hypothesis folder name (e.g., H001_slug) or STANDALONE for partial mode",
    )
    parser.add_argument("--files", nargs="*", default=[], help="Optional explicit files to audit in standalone mode")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    state_path = rdir / ".ra_state.json"

    state: Dict[str, Any] = (
        json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    )
    sealed_axioms: Dict[str, Any] = state.get("sealed_axioms", {})
    sealed_set = set(sealed_axioms.keys())

    violations: List[str] = []

    # 1. Verify cryptographic seal on all registered axiom files
    for rel_path, meta in sealed_axioms.items():
        af = workspace / rel_path
        if not af.exists():
            violations.append(f"AXIOM SEAL VIOLATION: Sealed axiom file `{rel_path}` was deleted!")
        else:
            actual = sha256_file(af)
            expected = meta.get("sha256", "")
            if actual != expected:
                violations.append(
                    f"AXIOM SEAL VIOLATION: `{rel_path}` was modified! Expected SHA-256 {expected[:12]}..., "
                    f"got {actual[:12]}... Never sneak hardcoded data into sealed axioms!"
                )

    # 2. Scan sandbox files for the target hypothesis (or explicit/tracked files in standalone mode)
    sandbox_dir = rdir / "sandbox" / args.hypothesis
    code_files: List[Path] = []
    if args.files:
        for fstr in args.files:
            fp = (workspace / fstr).resolve()
            if fp.exists() and fp.is_file():
                code_files.append(fp)
    elif sandbox_dir.exists():
        code_files = [
            f for f in sorted(sandbox_dir.rglob("*")) if f.is_file() and f.suffix.lower() in CODE_EXTENSIONS
        ]
    elif args.hypothesis == "STANDALONE":
        for rel_t in state.get("context_map_snapshot", {}).get("tracked_files", {}).keys():
            fp = (workspace / rel_t).resolve()
            if fp.exists() and fp.is_file() and fp.suffix.lower() in CODE_EXTENSIONS:
                code_files.append(fp)
    else:
        print(f"[RA CHEESE AUDIT] ERROR: Sandbox directory not found: {sandbox_dir}", file=sys.stderr)
        sys.exit(1)
    if not code_files:
        violations.append(f"No code files found inside `research/sandbox/{args.hypothesis}/` to audit.")

    for cf in code_files:
        violations.extend(audit_file(cf, sealed_set, workspace))

    print("=" * 78)
    print(f"  RA ANTI-CHEESE & AXIOM SEAL AUDIT — HYPOTHESIS: {args.hypothesis}")
    print("=" * 78)
    print(f"  Audited Code Files  : {len(code_files)}")
    print(f"  Sealed Axiom Files  : {len(sealed_axioms)}")
    print(f"  Violations Found    : {len(violations)}")
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
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("  [PASS] Zero cheese, zero band-aids, and all axiom seals verified!")
    print("         Ensure `ra_log_engine.py audit` and `ra_visual_audit.py audit` also pass, then run `ra_gate.py advance` to proceed to Stage 6.")
    print("=" * 78)


if __name__ == "__main__":
    main()
