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

DATA_POLLUTION_PATTERNS = [
    (
        re.compile(r"\b(ground_truth|golden_output|expected_results|benchmark_answers|eval_labels)\b", re.IGNORECASE),
        "[DATA_POLLUTION_LEAK] Production/model code references ground-truth or evaluation answer identifiers. Keep eval ground truth strictly inside break-test harnesses (`break_tests.*`).",
    ),
    (
        re.compile(r"\b(nan_to_num|fillna\s*\(\s*0)\b"),
        "[DATA_POLLUTION_MASKING] Silent `nan_to_num` / `fillna(0)` coerces corrupted upstream NaN/Null values into synthetic zeros, polluting downstream data. Fix the upstream producer instead.",
    ),
]


def compute_protected_symbol_hash(workspace: Path, spec: str) -> str | None:
    """Compute a deterministic SHA-256 hash of a protected `file:symbol` (or entire file if `:symbol` is omitted)."""
    if ":" in spec:
        file_part, sym_name = spec.rsplit(":", 1)
    else:
        file_part, sym_name = spec, ""
    fpath = (workspace / file_part).resolve()
    if not fpath.exists() or not fpath.is_file():
        return None
    if not sym_name:
        return sha256_file(fpath)
    try:
        src = fpath.read_text(encoding="utf-8")
    except Exception:
        return None
    if fpath.suffix.lower() == ".py":
        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == sym_name:
                    seg = ast.get_source_segment(src, node) or ast.dump(node)
                    return hashlib.sha256(seg.strip().encode("utf-8")).hexdigest()
        except Exception:
            pass
    pat = re.compile(rf"\b(?:def|function|fn|class|struct)\s+{re.escape(sym_name)}\b.*?(?=\n(?:def|function|fn|class|struct)\s+|\Z)", re.DOTALL)
    m = pat.search(src)
    if m:
        return hashlib.sha256(m.group(0).strip().encode("utf-8")).hexdigest()
    return None


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
    fname_lower = fpath.name.lower()
    is_sdk_helper = fname_lower in {"ra_logger.py", "ra_logger.js", "ralogger.php"}
    is_break_test = is_sdk_helper or "break_test" in fname_lower or fname_lower.startswith("test_")

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
        if not is_break_test and not is_sealed:
            for regex, msg in DATA_POLLUTION_PATTERNS:
                if regex.search(line):
                    issues.append(f"{rel}:{idx}: {msg} -> `{line.strip()}`")

    if fpath.suffix.lower() == ".py" and not is_sealed:
        issues.extend(audit_python_ast(fpath, text, is_break_test))

    return issues


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
        rel = cf.resolve().relative_to(workspace.resolve()).as_posix()
        try:
            lines = cf.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, start=1):
            if clamp_re.search(line):
                clamp_hits.append(f"- `{rel}:{idx}`: `{line.strip()}`")
            if mutation_re.search(line):
                mutation_hits.append(f"- `{rel}:{idx}`: `{line.strip()}`")

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


def main() -> None:
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
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    state_path = rdir / ".ra_state.json"

    state: Dict[str, Any] = (
        json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    )
    sealed_axioms: Dict[str, Any] = state.get("sealed_axioms", {})
    sealed_set = set(sealed_axioms.keys())
    protected_hashes: Dict[str, str] = state.get("protected_node_hashes", {})

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

    # 1b. Verify cryptographic lock on all PROTECTED_WORKING innocent nodes (`Symptom != Culprit`)
    for pnode, expected_phash in protected_hashes.items():
        actual_phash = compute_protected_symbol_hash(workspace, pnode)
        if actual_phash is None:
            violations.append(
                f"[PROTECTED_NODE_TAMPERED] Innocent `PROTECTED_WORKING` node `{pnode}` was deleted or renamed!"
            )
        elif actual_phash != expected_phash:
            violations.append(
                f"[PROTECTED_NODE_TAMPERED] Innocent `PROTECTED_WORKING` node `{pnode}` was modified "
                f"(expected SHA-256 {expected_phash[:12]}..., got {actual_phash[:12]}...)! "
                f"Symptom != Culprit: revert `{pnode}` and fix the upstream culprit instead."
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

    brief_path = None
    if args.emit_review_brief:
        brief_path = emit_cold_eyes_review_brief(workspace, code_files, protected_hashes, violations)

    print("=" * 78)
    print(f"  RA ANTI-CHEESE, DATA-POLLUTION & AXIOM SEAL AUDIT — HYPOTHESIS: {args.hypothesis}")
    print("=" * 78)
    print(f"  Audited Code Files  : {len(code_files)}")
    print(f"  Protected Nodes     : {len(protected_hashes)}")
    print(f"  Sealed Axiom Files  : {len(sealed_axioms)}")
    print(f"  Violations Found    : {len(violations)}")
    if brief_path:
        print(f"  Review Brief Out    : {brief_path.relative_to(workspace).as_posix()}")
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
