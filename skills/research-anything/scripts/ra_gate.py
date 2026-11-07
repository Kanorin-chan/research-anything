#!/usr/bin/env python3
"""
ra_gate.py — State-Machine Gatekeeper & Context Refresher for RA (research-anything).

Prevents LLM step-skipping, surface-data tunnel vision, whack-a-mole regressions,
attention decay, codebase poisoning, repeat questions, and axiom tampering by
enforcing hard stage gates on disk and echoing active invariants, behavioral
contracts, protected nodes, and current-stage instructions at every transition.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

STAGES = [
    "STAGE_0_INTAKE_AND_SYNC",
    "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING",
    "STAGE_2_HYPOTHESIS_FORMULATION",
    "STAGE_3_SANDBOX_PROTOTYPE",
    "STAGE_4_ADVERSARIAL_BREAK_TEST",
    "STAGE_5_ANTI_CHEESE_AUDIT",
    "STAGE_6_LAB_REPORT_AND_LEARNING",
    "STAGE_7_GRADUATION_REVIEW",
]

STAGE_INSTRUCTIONS: Dict[str, str] = {
    "STAGE_0_INTAKE_AND_SYNC": (
        "1. Run `check-question` and inspect all reference folders/images BEFORE asking the user anything.\n"
        "2. Gather user ideas 1-by-1 and synthesize into `research/VISION_AND_MISSION.md`.\n"
        "3. Lock non-negotiable rules in `research/INVARIANTS.md`.\n"
        "4. [OPTIONAL] Equip the R&D Arsenal (`ra_crawler.py` — only when the project benefits from external skills/papers/data):\n"
        "   - Priority #1 (Skill Crawler): `ra_crawler.py skill --query \"<domain>\"` (installs project-local skills).\n"
        "   - Priority #2 (Paper Crawler): `ra_crawler.py paper --query \"<topic>\"` (if prior art/equations needed).\n"
        "   - Priority #3 (Data Crawler) : `ra_crawler.py data --query \"<dataset>\"` (if test vectors needed).\n"
        "5. Forge Project-Local Skill, `.py` Harness/Hooks & Review Agent (if needed):\n"
        "   `ra_forge.py --name \"<project-slug>\" --domain \"<domain>\"`\n"
        "6. Advance to Stage 1 (`ra_gate.py map-context --agent <id> [--files ...]`)."
    ),
    "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING": (
        "1. DO NOT read only surface data or 1-hop neighbors. Trace the FULL multi-hop workflow in `research/WORKFLOW_MAP.md`:\n"
        "   Upstream Producers (-N hops) -> Shared State/Counters -> Target Node -> Downstream Consumers (+N hops) -> Multi-Cycle Loopback.\n"
        "2. Prove Culprit vs. Victim (`Symptom != Culprit`): If `Function A` is working properly and `Function C` is the culprit,\n"
        "   mark `Function A` as `PROTECTED_WORKING` so it is NEVER modified while fixing `Function C`.\n"
        "3. Lock all existing working behaviors in `WORKFLOW_MAP.md` (`BC-001`, `BC-002`...) to prevent whack-a-mole regressions.\n"
        "4. Fill out Section 4 of `WORKFLOW_MAP.md` (and Section 2 of `REPORT.md` if a hypothesis is active):\n"
        "   WHAT you are editing/creating, WHY edit this exact node, WHY create a new function (if any), and the N-hop blast radius.\n"
        "5. Stamp the session snapshot (`ra_gate.py map-context --agent <id> --files <paths...>`) AND compile a reusable\n"
        "   Context Snapshot for subagent `/fork` sharing (`ra_context_harness.py create --id <id> --tier WORKFLOW_SLICE --files <paths...> --summary \"...\"`).\n"
        "6. Run `ra_gate.py advance`."
    ),
    "STAGE_2_HYPOTHESIS_FORMULATION": (
        "1. Edit `research/hypotheses/<active_hypothesis>/REPORT.md`.\n"
        "2. Ensure Section 2 (Workflow Context, Protected Nodes & Pre-Edit/Pre-Creation Justification) and\n"
        "   Section 3 (First-Principles Mathematical/Structural Formulation & Assumptions) are completely filled out.\n"
        "3. Do NOT write boilerplate. Derive from first principles.\n"
        "4. Run `ra_gate.py advance` to unlock Stage 3 (Sandbox Prototype)."
    ),
    "STAGE_3_SANDBOX_PROTOTYPE": (
        "1. LEAD-ORCHESTRATOR DELEGATION & CONTEXT FORKING (`ra_context_harness.py`):\n"
        "   Fork the shared snapshot to a Subagent (`ra_context_harness.py fork --subagent Subagent_A --snapshots <snap_id> --task \"...\"`),\n"
        "   let the Subagent build the prototype & write its report, then reclaim the baton (`ra_context_harness.py return-baton --subagent Subagent_A`).\n"
        "2. Build the deployment-grade prototype inside `research/sandbox/<active_hypothesis>/`.\n"
        "3. WIRE PRODUCTION `.log` TELEMETRY (`ra_log_engine.py`): Silent code and bare `print()` are BANNED.\n"
        "   Inject/import `RALogger` (`ra_log_engine.py inject-sdk --lang <python|js|ts|php> --dest research/sandbox/<active_hypothesis>`)\n"
        "   and log every flow hop (`flow=caller->callee`, `role`, `inputs`, `state_before`, `state_after`, `output`, `contract=BC-xxx`).\n"
        "4. Keep the main codebase and all `PROTECTED_WORKING` functions 100% clean and untouched.\n"
        "5. Place legitimate mathematical/structural axioms in a sealed `axioms` file (`ra_gate.py seal-axioms`).\n"
        "6. Run `ra_gate.py advance` to unlock Stage 4 (Real-Environment `.log` & Stress Verification)."
    ),
    "STAGE_4_ADVERSARIAL_BREAK_TEST": (
        "1. Synthetic unit-test marathons (`test_xyz.py`) are BANNED. Verify in the REAL ENVIRONMENT via `.log` telemetry:\n"
        "   `python ra_log_engine.py run --workspace . --hypothesis <active_hypothesis> --timeout-sec 60 --cmd \"<real-run-cmd>\"`\n"
        "2. Audit the generated `.log` file for `[PASS]`, `[DECISION]`, `[STUCK]`, `[FAIL]`, full variable values, and `BC-xxx` contracts:\n"
        "   `python ra_log_engine.py audit --workspace . --hypothesis <active_hypothesis>`\n"
        "3. USER-EYES VISUAL REALITY CHECK (if UI/CSS/game/visual output): Run `ra_visual_audit.py init --hypothesis <active_hypothesis>`,\n"
        "   capture live screenshots into `visual_captures/`, open & inspect the pixels (`read_file`), and complete `VISUAL_AUDIT.md`.\n"
        "4. If any hop is `[STUCK]` or `[FAIL]`, fix the upstream mechanism (NO `if/else` or `try/except` band-aids!).\n"
        "5. Once `ra_log_engine.py audit` passes, run `ra_gate.py advance` to unlock Stage 5."
    ),
    "STAGE_5_ANTI_CHEESE_AUDIT": (
        "1. Run `python ra_cheese_audit.py --workspace . --hypothesis <active_hypothesis>`.\n"
        "2. Run `python ra_log_engine.py audit --workspace . --hypothesis <active_hypothesis>` (verifies real `.log` flow & values).\n"
        "3. Run `python ra_visual_audit.py audit --workspace . --hypothesis <active_hypothesis>` (verifies User-Eyes screenshots).\n"
        "4. Once `ra_cheese_audit.py`, `ra_log_engine.py audit`, and `ra_visual_audit.py` pass, run `ra_gate.py advance` to unlock Stage 6."
    ),
    "STAGE_6_LAB_REPORT_AND_LEARNING": (
        "1. Complete `research/hypotheses/<active_hypothesis>/REPORT.md` with raw trusted data and root-cause proof.\n"
        "2. Run `ra_gate.py conclude --verdict <PROVEN|FALSIFIED> --issue \"...\" --workflow \"...\" --found \"...\"`.\n"
        "   - If FALSIFIED: sandbox is archived to `research/graveyard/`, main code stays clean, and you loop back to Stage 1/2.\n"
        "   - If PROVEN: moves to Stage 7 (Graduation Review)."
    ),
    "STAGE_7_GRADUATION_REVIEW": (
        "1. Run the forged project harness (`python research/harness/project_harness.py check-all`) and invoke the\n"
        "   Adversarial Review Agent (`.claude/agents/ra-reviewer.md` / `research/harness/REVIEW_AGENT_PROMPT.md`).\n"
        "2. STOP AND PRESENT TO USER: Show the Lab Report summary, workflow blast-radius verification, and empirical bounds.\n"
        "3. Wait for explicit user approval before merging sandbox code into the main project.\n"
        "4. After user approval, run `ra_gate.py graduate --workspace .` to record the truth in `research/library/`."
    ),
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_research_dir(workspace: Path) -> Path:
    return workspace.resolve() / "research"


def get_state_path(workspace: Path) -> Path:
    return get_research_dir(workspace) / ".ra_state.json"


def ensure_initialized(workspace: Path, agent_id: str = "PRIMARY_AGENT") -> Dict[str, Any]:
    rdir = get_research_dir(workspace)
    templates_dir = get_skill_root() / "resources" / "templates"
    for subdir in ["hypotheses", "sandbox", "graveyard", "library"]:
        (rdir / subdir).mkdir(parents=True, exist_ok=True)

    ts = now_iso()
    template_map = {
        "VISION_AND_MISSION.md": rdir / "VISION_AND_MISSION.md",
        "INVARIANTS.md": rdir / "INVARIANTS.md",
        "WORKFLOW_MAP.md": rdir / "WORKFLOW_MAP.md",
        "LAB_LOG.md": rdir / "LAB_LOG.md",
        "SELF_LEARNING.md": rdir / "SELF_LEARNING.md",
        "REFERENCES_INDEX.md": rdir / "library" / "REFERENCES_INDEX.md",
    }
    for tname, dest in template_map.items():
        if not dest.exists():
            src = templates_dir / tname
            content = src.read_text(encoding="utf-8") if src.exists() else f"# {tname}\n"
            content = content.replace("<ISO-8601>", ts).replace("<YYYY-MM-DD>", ts[:10]).replace("<agent-id>", agent_id)
            dest.write_text(content, encoding="utf-8")

    state_path = get_state_path(workspace)
    if not state_path.exists():
        state = {
            "version": "1.3.0",
            "created_at": ts,
            "updated_at": ts,
            "current_stage": "STAGE_0_INTAKE_AND_SYNC",
            "active_hypothesis": None,
            "consecutive_falsifications": 0,
            "cheese_audit_passed": False,
            "visual_audit_passed": False,
            "log_audit_passed": False,
            "sealed_axioms": {},
            "protected_nodes": [],
            "context_map_snapshot": {
                "agent": None,
                "timestamp": None,
                "tracked_files": {},
            },
            "history": [
                {
                    "timestamp": ts,
                    "agent": agent_id,
                    "event": "INIT",
                    "details": "Initialized RA research structure.",
                }
            ],
        }
        save_state(workspace, state)
        return state
    return json.loads(state_path.read_text(encoding="utf-8"))


def load_state(workspace: Path, auto_init: bool = False) -> Dict[str, Any]:
    sp = get_state_path(workspace)
    if not sp.exists():
        if auto_init:
            return ensure_initialized(workspace)
        print(
            "[RA GATE] ERROR: Research repository not initialized. Run `ra_gate.py init --workspace .` first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(sp.read_text(encoding="utf-8"))


def save_state(workspace: Path, state: Dict[str, Any]) -> None:
    sp = get_state_path(workspace)
    state["updated_at"] = now_iso()
    sp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_sealed_axioms(workspace: Path, state: Dict[str, Any]) -> List[str]:
    violations: List[str] = []
    sealed = state.get("sealed_axioms", {})
    for rel_path, meta in sealed.items():
        fpath = workspace.resolve() / rel_path
        if not fpath.exists():
            violations.append(f"Sealed axiom file deleted: {rel_path}")
            continue
        current_hash = sha256_file(fpath)
        if current_hash != meta.get("sha256"):
            violations.append(
                f"AXIOM SEAL VIOLATION on `{rel_path}`! Expected SHA-256 {meta.get('sha256')[:12]}..., "
                f"got {current_hash[:12]}... Do NOT sneak hardcoded data into sealed axioms!"
            )
    return violations


def check_context_map_staleness(workspace: Path, state: Dict[str, Any]) -> List[str]:
    """Check if any source files tracked in the AI session's workflow map have been modified or deleted."""
    notices: List[str] = []
    cmap = state.get("context_map_snapshot", {})
    tracked_files: Dict[str, str] = cmap.get("tracked_files", {})
    for rel_path, recorded_hash in tracked_files.items():
        fpath = workspace.resolve() / rel_path
        if not fpath.exists():
            notices.append(f"`{rel_path}` was deleted since context snapshot!")
        else:
            curr_hash = sha256_file(fpath)
            if curr_hash != recorded_hash:
                notices.append(
                    f"`{rel_path}` changed since snapshot ({recorded_hash[:10]}... -> {curr_hash[:10]}...)"
                )
    return notices


def extract_locked_invariants(workspace: Path) -> List[str]:
    inv_file = get_research_dir(workspace) / "INVARIANTS.md"
    if not inv_file.exists():
        return []
    lines: List[str] = []
    for line in inv_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- **`INV-") or stripped.startswith("- `INV-"):
            lines.append(stripped)
    return lines


def extract_behavioral_contracts(workspace: Path) -> List[str]:
    wmap_file = get_research_dir(workspace) / "WORKFLOW_MAP.md"
    if not wmap_file.exists():
        return []
    lines: List[str] = []
    for line in wmap_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if (stripped.startswith("- **`BC-") or stripped.startswith("- `BC-")) and "<e.g.," not in stripped:
            lines.append(stripped)
    return lines


def print_context_refresh(workspace: Path, state: Dict[str, Any]) -> None:
    stage = state.get("current_stage", "STAGE_0_INTAKE_AND_SYNC")
    active_hyp = state.get("active_hypothesis") or "NONE"
    fals_count = state.get("consecutive_falsifications", 0)
    invariants = extract_locked_invariants(workspace)
    contracts = extract_behavioral_contracts(workspace)
    violations = verify_sealed_axioms(workspace, state)
    stale_notices = check_context_map_staleness(workspace, state)
    cmap = state.get("context_map_snapshot", {})
    protected_nodes = state.get("protected_nodes", [])

    print("=" * 78)
    print("  RA (RESEARCH ANYTHING) — STATE MACHINE & CONTEXT REFRESH")
    print("=" * 78)
    print(f"  Current Stage              : {stage}")
    print(f"  Active Hypothesis          : {active_hyp}")
    print(f"  Consecutive Falsifications : {fals_count} / 5 (Autonomous Loop Threshold)")
    print(f"  Sealed Axiom Files         : {len(state.get('sealed_axioms', {}))}")
    if cmap.get("timestamp"):
        print(
            f"  Workflow Map Snapshot      : by `{cmap.get('agent', 'UNKNOWN')}` at `{cmap.get('timestamp')}` "
            f"(AI Session Data — Verify Live Code!)"
        )
    else:
        print("  Workflow Map Snapshot      : NOT YET MAPPED (Run `ra_gate.py map-context`)")

    arsenal = state.get("arsenal", {})
    crawled_skills = [s.get("name", "") for s in arsenal.get("skills", [])]
    forged = state.get("forged_suite", {})
    print(
        f"  Project-Local R&D Arsenal  : {len(crawled_skills)} crawled skill(s), "
        f"{len(arsenal.get('papers', []))} paper set(s), {len(arsenal.get('data', []))} dataset(s)"
    )
    if forged.get("harness_py"):
        print(
            f"  Forged Project Suite       : ACTIVE (`{forged.get('project_skill')}`, "
            f"`{forged.get('harness_py')}`, `{forged.get('reviewer_agent')}`)"
        )
    else:
        print("  Forged Project Suite       : NOT YET FORGED (Run `ra_forge.py --name <slug> --domain <domain>`)")

    snap_reg_path = get_research_dir(workspace) / "context_snapshots" / "SNAPSHOT_REGISTRY.json"
    if snap_reg_path.exists():
        try:
            sreg = json.loads(snap_reg_path.read_text(encoding="utf-8"))
            active_snaps = len(sreg.get("snapshots", {}))
            evicted_snaps = len(sreg.get("evicted_history", []))
            baton = sreg.get("active_baton", "MAIN_ORCHESTRATOR")
            print(
                f"  Subagent Context Snapshots : {active_snaps} active, {evicted_snaps} thrown away (evicted) "
                f"| Baton: `{baton}`"
            )
        except Exception:
            pass
    else:
        print("  Subagent Context Snapshots : 0 active (Use `ra_context_harness.py create` / `fork` to share context)")
    print("-" * 78)

    if stale_notices:
        print("  [!] WORKFLOW MAP STALENESS / ALTERED CODE WARNING:")
        print("      `research/WORKFLOW_MAP.md` was written by an earlier AI session and tracked files changed:")
        for sn in stale_notices:
            print(f"      - {sn}")
        print("      Re-verify live code and update `WORKFLOW_MAP.md` via `ra_gate.py map-context`!")
        print("-" * 78)

    if violations:
        print("  [!!!] CRITICAL AXIOM SEAL VIOLATIONS DETECTED:")
        for v in violations:
            print(f"    - {v}")
        print("-" * 78)

    if fals_count >= 5:
        print("  [!!!] CHECKPOINT REACHED: 5 consecutive hypotheses falsified on this track.")
        print("        PAUSE autonomous looping and present the Lab Reports to the user")
        print("        to confirm whether to pivot the overarching direction.")
        print("-" * 78)

    if protected_nodes:
        print("  PROTECTED WORKING NODES (`Symptom != Culprit` — DO NOT MODIFY THESE):")
        for pn in protected_nodes:
            print(f"    - [PROTECTED] {pn}")
        print("-" * 78)

    if contracts:
        print("  EXISTING BEHAVIORAL CONTRACTS (`WORKFLOW_MAP.md` — DO NOT REGRESS):")
        for bc in contracts:
            print(f"    {bc}")
        print("-" * 78)

    if invariants:
        print("  LOCKED PROJECT INVARIANTS (DO NOT VIOLATE OR FORGET):")
        for inv in invariants:
            print(f"    {inv}")
        print("-" * 78)

    instructions = STAGE_INSTRUCTIONS.get(stage, "").replace("<active_hypothesis>", active_hyp)
    print(f"  ACTIVE INSTRUCTIONS FOR {stage}:")
    for line in instructions.splitlines():
        print(f"    {line}")
    print("=" * 78)


def cmd_init(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = get_research_dir(workspace)
    agent_id = args.agent or "PRIMARY_AGENT"
    state = ensure_initialized(workspace, agent_id=agent_id)
    print(f"[RA GATE] Initialized research repository at: {rdir}")
    print_context_refresh(workspace, state)


def cmd_status(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace, auto_init=True)
    print_context_refresh(workspace, state)


def cmd_check_question(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = get_research_dir(workspace)
    print("=" * 78)
    print("  RA ZERO-REPEAT QUESTION GATE — MANDATORY PRE-QUESTION INVENTORY")
    print("=" * 78)
    print("  STOP! Before asking the user ANY question, verify the answer is not below:")
    print("-" * 78)

    candidate_dirs = [
        workspace / "reference",
        workspace / "references",
        workspace / "assets",
        workspace / "docs",
        rdir / "library",
    ]
    found_files: List[Path] = []
    for root_doc in ("GLOSSARY.md", "GLOSSARY-MAP.md", "CONTEXT.md"):
        rp = workspace / root_doc
        if rp.exists() and rp.is_file():
            found_files.append(rp)
    for cdir in candidate_dirs:
        if cdir.exists() and cdir.is_dir():
            for f in sorted(cdir.rglob("*")):
                if f.is_file():
                    found_files.append(f)

    if found_files:
        print("  DISCOVERED REFERENCE / GLOSSARY / ASSET / LIBRARY FILES ON DISK:")
        for f in found_files[:60]:
            rel = f.relative_to(workspace)
            print(f"    - {rel} ({f.stat().st_size} bytes)")
        print("  [RULE] If any image (.png/.jpg/.webp) or doc above relates to your question,")
        print("         you MUST open and view it BEFORE asking the user!")
    else:
        print("  (No files found in GLOSSARY.md, reference/, references/, assets/, docs/, or research/library/)")

    glossary_path = workspace / "GLOSSARY.md"
    if glossary_path.exists():
        print("-" * 78)
        print("  PROJECT SHARED LANGUAGE (`GLOSSARY.md`):")
        for line in glossary_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:30]:
            print(f"    {line}")

    ref_idx = rdir / "library" / "REFERENCES_INDEX.md"
    if ref_idx.exists():
        print("-" * 78)
        print("  INDEXED USER REFERENCES & PAST ANSWERS (`research/library/REFERENCES_INDEX.md`):")
        for line in ref_idx.read_text(encoding="utf-8").splitlines()[:40]:
            print(f"    {line}")

    wmap = rdir / "WORKFLOW_MAP.md"
    if wmap.exists():
        print("-" * 78)
        print("  MAPPED SYSTEM WORKFLOW (`research/WORKFLOW_MAP.md` — check before asking how code flows):")
        for line in wmap.read_text(encoding="utf-8").splitlines()[:25]:
            print(f"    {line}")

    print("=" * 78)


def extract_symbol_source_segment(workspace: Path, spec: str) -> Optional[str]:
    """Extract the source text of `file:symbol` (or entire file if `:symbol` is omitted)."""
    if ":" in spec:
        file_part, sym_name = spec.rsplit(":", 1)
    else:
        file_part, sym_name = spec, ""
    fpath = (workspace / file_part).resolve()
    if not fpath.exists() or not fpath.is_file():
        return None
    try:
        src = fpath.read_text(encoding="utf-8")
    except Exception:
        return None
    if not sym_name:
        return src
    if fpath.suffix.lower() == ".py":
        try:
            import ast as _ast

            tree = _ast.parse(src)
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)) and node.name == sym_name:
                    return _ast.get_source_segment(src, node) or _ast.dump(node)
        except Exception:
            pass
    pat = re.compile(
        rf"\b(?:def|function|fn|class|struct)\s+{re.escape(sym_name)}\b.*?(?=\n(?:def|function|fn|class|struct)\s+|\Z)",
        re.DOTALL,
    )
    m = pat.search(src)
    if m:
        return m.group(0)
    return None


def compute_protected_symbol_hash(workspace: Path, spec: str) -> Optional[str]:
    """Compute a deterministic SHA-256 hash of a protected `file:symbol` (or entire file if `:symbol` is omitted)."""
    seg = extract_symbol_source_segment(workspace, spec)
    if seg is None:
        return None
    return hashlib.sha256(seg.strip().encode("utf-8")).hexdigest()


SUSPICIOUS_INNOCENCE_RE = re.compile(
    r"(except\s*(?:Exception|BaseException)?\s*:\s*pass\b|catch\s*\([^)]*\)\s*\{\s*\}|"
    r"\b(?:mock_?data|fake_?data|dummy_?data|nan_to_num|NotImplementedError)\b|"
    r"(?:#|//)\s*(?:TODO|FIXME|hack|band-?aid|hardcoded)\b)",
    re.IGNORECASE,
)


def cmd_map_context(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace, auto_init=True)
    rdir = get_research_dir(workspace)
    wmap_path = rdir / "WORKFLOW_MAP.md"

    agent_id = args.agent or "PRIMARY_AGENT"
    ts = now_iso()

    tracked: Dict[str, str] = state.get("context_map_snapshot", {}).get("tracked_files", {})
    if args.files:
        for fstr in args.files:
            fpath = (workspace / fstr).resolve()
            if not fpath.exists() or not fpath.is_file():
                print(f"[RA GATE] WARNING: Tracked file not found: {fstr}", file=sys.stderr)
                continue
            rel = fpath.relative_to(workspace).as_posix()
            tracked[rel] = sha256_file(fpath)

    protected: List[str] = state.get("protected_nodes", [])
    protected_hashes: Dict[str, str] = state.get("protected_node_hashes", {})

    # 1. Handle Forensic Lock Revocation (`--revoke-protected`) when real data exposes a disguised culprit
    if getattr(args, "revoke_protected", None):
        reason = (getattr(args, "revoke_reason", None) or "").strip()
        if len(reason) < 10:
            print(
                "[RA GATE BLOCKED] Forensic Lock Revocation (`--revoke-protected`) requires `--revoke-reason` "
                "explaining the runtime `.log` or real-data pipe evidence that exposed the node as corrupted!",
                file=sys.stderr,
            )
            sys.exit(2)
        for rnode in args.revoke_protected:
            if rnode in protected:
                protected.remove(rnode)
            protected_hashes.pop(rnode, None)
            state.setdefault("revoked_protected_history", []).append(
                {
                    "node": rnode,
                    "revoked_by": agent_id,
                    "revoked_at": ts,
                    "reason": reason,
                }
            )
            append_self_learning(
                rdir,
                state.get("active_hypothesis") or "FORENSIC_REVOCATION",
                agent_id,
                f"Former `PROTECTED_WORKING` node `{rnode}` exposed as corrupted under real data / `.log` trace.",
                "Static/initial pass masked a coupled bug that only surfaced after upstream sent real production data.",
                f"Revoked `PROTECTED_WORKING` lock on `{rnode}` ({reason}) so root-cause repair can proceed.",
            )
            print(
                f"[RA GATE FORENSIC REVOCATION] Unlocked `{rnode}` (Reason: {reason}). "
                f"You may now repair `{rnode}` to handle the real data contract."
            )

    # 2. Handle Zero-Trust `--protected` registration
    if args.protected:
        for pnode in args.protected:
            seg = extract_symbol_source_segment(workspace, pnode)
            if seg is not None:
                m_susp = SUSPICIOUS_INNOCENCE_RE.search(seg)
                if m_susp:
                    print(
                        f"[RA GATE BLOCKED] Zero-Trust Innocence Check Failed for `{pnode}`!\n"
                        f"  Cannot lock `{pnode}` as `PROTECTED_WORKING` because its source contains a suspicious "
                        f"band-aid / fake-data / stub pattern: `{m_susp.group(0)}`.\n"
                        f"  Only lock functions proven clean by runtime `[RA_LOG]` boundary traces!",
                        file=sys.stderr,
                    )
                    sys.exit(2)
            if pnode not in protected:
                protected.append(pnode)
            phash = compute_protected_symbol_hash(workspace, pnode)
            if phash:
                protected_hashes[pnode] = phash

    state["protected_nodes"] = protected
    state["protected_node_hashes"] = protected_hashes
    state["context_map_snapshot"] = {
        "agent": agent_id,
        "timestamp": ts,
        "tracked_files": tracked,
    }

    if state.get("current_stage") == "STAGE_0_INTAKE_AND_SYNC":
        state["current_stage"] = "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING"

    if wmap_path.exists():
        txt = wmap_path.read_text(encoding="utf-8")
        lines = txt.splitlines()
        updated_lines: List[str] = []
        for line in lines:
            if line.strip().startswith("- **Last Mapped By (Agent / Session)**:"):
                updated_lines.append(f"- **Last Mapped By (Agent / Session)**: `{agent_id}`")
            elif line.strip().startswith("- **Last Snapshot Timestamp**:"):
                updated_lines.append(f"- **Last Snapshot Timestamp**: `{ts}`")
            else:
                updated_lines.append(line)
        wmap_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    state.setdefault("history", []).append(
        {
            "timestamp": ts,
            "agent": agent_id,
            "event": "MAP_CONTEXT",
            "tracked_files": list(tracked.keys()),
            "protected_nodes": protected,
        }
    )
    save_state(workspace, state)
    print(
        f"[RA GATE] Recorded AI Session Workflow Snapshot by `{agent_id}` at `{ts}` "
        f"({len(tracked)} tracked file(s), {len(protected)} protected node(s))."
    )
    print_context_refresh(workspace, state)


def is_workflow_map_populated(rdir: Path) -> bool:
    wmap_path = rdir / "WORKFLOW_MAP.md"
    if not wmap_path.exists():
        return False
    txt = wmap_path.read_text(encoding="utf-8")
    if "<Exact file and function/symbol>" in txt or "<Why is this the true root-cause location" in txt:
        return False
    return True


def load_context_snapshot_registry(rdir: Path) -> Dict[str, Any]:
    reg_path = rdir / "context_snapshots" / "SNAPSHOT_REGISTRY.json"
    if not reg_path.exists():
        return {}
    try:
        return json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def has_reusable_context_snapshot(rdir: Path) -> bool:
    reg = load_context_snapshot_registry(rdir)
    snaps = reg.get("snapshots", {})
    return any(
        s.get("status") == "ACTIVE" and s.get("tier") in ("BASE_FRAMEWORK", "WORKFLOW_SLICE")
        for s in snaps.values()
    )


def verify_subagent_fork_and_baton(rdir: Path) -> List[str]:
    issues: List[str] = []
    reg = load_context_snapshot_registry(rdir)
    if not reg:
        issues.append(
            "No Context Snapshot Registry found (`research/context_snapshots/SNAPSHOT_REGISTRY.json`). "
            "Run `ra_context_harness.py create` and `ra_context_harness.py fork`!"
        )
        return issues
    if reg.get("total_forks_dispatched", 0) < 1:
        issues.append(
            "Zero subagent context forks dispatched! Main Agent must fork context (`ra_context_harness.py fork "
            "--subagent <name> --snapshots <id> --task \"...\"`) instead of doing all work in one monolithic context."
        )
    if reg.get("completed_subagent_relays", 0) < 1:
        issues.append(
            "No completed subagent baton relay recorded! After the forked subagent finishes its task, run "
            "`ra_context_harness.py return-baton --subagent <name>`."
        )
    baton = reg.get("active_baton", "MAIN_ORCHESTRATOR")
    if baton != "MAIN_ORCHESTRATOR":
        issues.append(
            f"1-Concurrency Baton is still held by `{baton}`! Run `ra_context_harness.py return-baton --subagent ...` "
            "to return execution control to `MAIN_ORCHESTRATOR`."
        )
    return issues


def cmd_new_hypothesis(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)

    violations = verify_sealed_axioms(workspace, state)
    if violations:
        print("[RA GATE] BLOCKED: Fix sealed axiom violations before starting a hypothesis.", file=sys.stderr)
        sys.exit(1)

    hyp_id = args.id.strip().upper()
    slug = args.slug.strip().lower().replace(" ", "_")
    full_id = f"{hyp_id}_{slug}"
    agent_id = args.agent or "PRIMARY_AGENT"
    parent_id = args.parent or "NONE"
    ts = now_iso()

    hyp_dir = rdir / "hypotheses" / full_id
    sandbox_dir = rdir / "sandbox" / full_id
    hyp_dir.mkdir(parents=True, exist_ok=True)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    tpl_path = get_skill_root() / "resources" / "templates" / "HYPOTHESIS_REPORT.md"
    report_path = hyp_dir / "REPORT.md"
    if not report_path.exists():
        tpl = tpl_path.read_text(encoding="utf-8") if tpl_path.exists() else "# Report\n"
        content = (
            tpl.replace("{{HYPOTHESIS_ID}}", hyp_id)
            .replace("{{SLUG}}", slug)
            .replace("{{PARENT_ID}}", parent_id)
            .replace("{{AGENT_ID}}", agent_id)
            .replace("{{TIMESTAMP}}", ts)
        )
        report_path.write_text(content, encoding="utf-8")

    # Always enter Stage 1 (Workflow & Context Mapping) first unless WORKFLOW_MAP.md is populated AND a context snapshot exists
    next_stage = (
        "STAGE_2_HYPOTHESIS_FORMULATION"
        if (is_workflow_map_populated(rdir) and has_reusable_context_snapshot(rdir))
        else "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING"
    )

    lab_log = rdir / "LAB_LOG.md"
    if lab_log.exists():
        with lab_log.open("a", encoding="utf-8") as f:
            f.write(
                f"| `{ts}` | `{hyp_id}` | `{parent_id}` | `{agent_id}` | `{next_stage}` "
                f"| Initialized `{full_id}` | `hypotheses/{full_id}/REPORT.md` |\n"
            )

    state["current_stage"] = next_stage
    state["active_hypothesis"] = full_id
    state["cheese_audit_passed"] = False
    state["visual_audit_passed"] = False
    state["log_audit_passed"] = False
    state.setdefault("history", []).append(
        {"timestamp": ts, "agent": agent_id, "event": "NEW_HYPOTHESIS", "hypothesis": full_id, "parent": parent_id}
    )
    save_state(workspace, state)
    print(f"[RA GATE] Created Hypothesis `{full_id}` and quarantined sandbox `research/sandbox/{full_id}/`.")
    print_context_refresh(workspace, state)


def cmd_advance(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)

    violations = verify_sealed_axioms(workspace, state)
    if violations:
        print("[RA GATE] BLOCKED: Axiom seal violation detected!", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    stage = state.get("current_stage", "STAGE_0_INTAKE_AND_SYNC")
    active_hyp = state.get("active_hypothesis")

    if stage == "STAGE_0_INTAKE_AND_SYNC":
        state["current_stage"] = "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING"
        save_state(workspace, state)
        print("[RA GATE] Entered STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING.")
        print_context_refresh(workspace, state)
        return

    if stage == "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING":
        if not is_workflow_map_populated(rdir):
            print(
                "[RA GATE] BLOCKED: You cannot advance from Stage 1 until you complete `research/WORKFLOW_MAP.md`!\n"
                "          Map the multi-hop workflow, identify Protected Working Nodes (`Symptom != Culprit`),\n"
                "          and fill out Section 4 (WHAT you are editing/creating, WHY edit this, WHY create a new function).",
                file=sys.stderr,
            )
            sys.exit(1)
        if not has_reusable_context_snapshot(rdir):
            print(
                "[RA GATE] BLOCKED: You must compile a shared Context Snapshot for subagent `/fork` reuse before leaving Stage 1!\n"
                "          Run: `python ra_context_harness.py create --workspace . --id <slice_id> --tier WORKFLOW_SLICE "
                "--files <paths...> --summary \"...\"`",
                file=sys.stderr,
            )
            sys.exit(1)
        if not active_hyp:
            print(
                "[RA GATE] `research/WORKFLOW_MAP.md` and Context Snapshot verified! Now run `ra_gate.py new-hypothesis --id H001 --slug <name>` "
                "to open your hypothesis in Stage 2.",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_2_HYPOTHESIS_FORMULATION"
        save_state(workspace, state)
        print(f"[RA GATE] Advanced `{active_hyp}` to STAGE_2_HYPOTHESIS_FORMULATION.")
        print_context_refresh(workspace, state)
        return

    if not active_hyp:
        print("[RA GATE] ERROR: No active hypothesis. Run `new-hypothesis` first.", file=sys.stderr)
        sys.exit(1)

    hyp_dir = rdir / "hypotheses" / active_hyp
    sandbox_dir = rdir / "sandbox" / active_hyp
    report_path = hyp_dir / "REPORT.md"

    if stage == "STAGE_2_HYPOTHESIS_FORMULATION":
        if not is_workflow_map_populated(rdir):
            print(
                "[RA GATE] BLOCKED: `research/WORKFLOW_MAP.md` still has unfilled placeholders! Complete Stage 1 mapping first.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not report_path.exists():
            print(f"[RA GATE] BLOCKED: Missing `{report_path}`.", file=sys.stderr)
            sys.exit(1)
        report_txt = report_path.read_text(encoding="utf-8")
        if "<Empirical proof that this node is the root cause" in report_txt:
            print(
                "[RA GATE] BLOCKED: You have not filled out Section 2 (Workflow Context, Culprit Proof & "
                "Pre-Edit/Pre-Creation Justification) in REPORT.md!",
                file=sys.stderr,
            )
            sys.exit(1)
        if "<Write the exact equations" in report_txt:
            print(
                "[RA GATE] BLOCKED: You have not filled out Section 3 (First-Principles Formulation) in REPORT.md!",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_3_SANDBOX_PROTOTYPE"

    elif stage == "STAGE_3_SANDBOX_PROTOTYPE":
        ignored_meta = {"visual_audit.md", "ra_logger.py", "ra_logger.js", "ralogger.php"}
        files = [
            f
            for f in sandbox_dir.rglob("*")
            if f.is_file() and f.name.lower() not in ignored_meta and f.suffix.lower() != ".log"
        ]
        if not files:
            print(
                f"[RA GATE] BLOCKED: Sandbox `research/sandbox/{active_hyp}/` has no prototype code files!",
                file=sys.stderr,
            )
            sys.exit(1)
        fork_issues = verify_subagent_fork_and_baton(rdir)
        if fork_issues:
            print("[RA GATE] BLOCKED: Context Forking & Subagent Baton Relay Gate failed:", file=sys.stderr)
            for fi in fork_issues:
                print(f"  - {fi}", file=sys.stderr)
            sys.exit(1)
        state["current_stage"] = "STAGE_4_ADVERSARIAL_BREAK_TEST"

    elif stage == "STAGE_4_ADVERSARIAL_BREAK_TEST":
        if not state.get("log_audit_passed", False):
            print(
                f"[RA GATE] BLOCKED: Stage 4 requires a verified real-environment `.log` trace (no fake unit tests!).\n"
                f"          Run `python ra_log_engine.py audit --workspace . --hypothesis {active_hyp}` and resolve any\n"
                f"          `[STUCK]`, `[FAIL]`, or missing flow/value logs before advancing!",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_5_ANTI_CHEESE_AUDIT"

    elif stage == "STAGE_5_ANTI_CHEESE_AUDIT":
        if not state.get("log_audit_passed", False):
            print(
                f"[RA GATE] BLOCKED: Real-environment `.log` audit (`ra_log_engine.py audit`) has not passed!",
                file=sys.stderr,
            )
            sys.exit(1)
        if not state.get("cheese_audit_passed", False):
            print(
                "[RA GATE] BLOCKED: You must run `ra_cheese_audit.py` and pass with zero violations before advancing!",
                file=sys.stderr,
            )
            sys.exit(1)
        if not state.get("visual_audit_passed", False):
            print(
                "[RA GATE] BLOCKED: You must run `python ra_visual_audit.py audit --workspace . --hypothesis "
                f"{active_hyp}` and pass User-Eyes Visual Reality verification before advancing!",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_6_LAB_REPORT_AND_LEARNING"

    elif stage == "STAGE_6_LAB_REPORT_AND_LEARNING":
        print(
            "[RA GATE] Use `ra_gate.py conclude --verdict <PROVEN|FALSIFIED> --issue ... --workflow ... --found ...` "
            "to complete Stage 6.",
            file=sys.stderr,
        )
        sys.exit(1)

    elif stage == "STAGE_7_GRADUATION_REVIEW":
        print(
            "[RA GATE] Waiting for User Graduation Sign-Off. Run `ra_gate.py graduate --workspace .` only AFTER "
            "the user approves the Lab Report.",
            file=sys.stderr,
        )
        sys.exit(1)

    save_state(workspace, state)
    print(f"[RA GATE] Advanced `{active_hyp}` to {state['current_stage']}.")
    print_context_refresh(workspace, state)


def append_self_learning(
    rdir: Path, hyp_id: str, agent_id: str, issue: str, workflow: str, found: str
) -> None:
    sl_path = rdir / "SELF_LEARNING.md"
    ts = now_iso()
    existing = sl_path.read_text(encoding="utf-8") if sl_path.exists() else "# Self-Learning Log\n"
    count = existing.count("### `SL-")
    sl_id = f"SL-{count:03d}"
    entry = (
        f"\n### `{sl_id}` ({hyp_id})\n"
        f"- **Date / Agent**: `{ts}` / `{agent_id}`\n"
        f"- **Related Hypothesis**: `{hyp_id}`\n"
        f"- **Issue**: {issue.strip()}\n"
        f"- **Workflow**: {workflow.strip()}\n"
        f"- **Found**: {found.strip()}\n"
    )
    with sl_path.open("a", encoding="utf-8") as f:
        f.write(entry)


def cmd_conclude(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)

    active_hyp = state.get("active_hypothesis")
    if not active_hyp:
        print("[RA GATE] ERROR: No active hypothesis to conclude.", file=sys.stderr)
        sys.exit(1)

    verdict = args.verdict.strip().upper()
    if verdict not in ("PROVEN", "FALSIFIED"):
        print("[RA GATE] ERROR: Verdict must be PROVEN or FALSIFIED.", file=sys.stderr)
        sys.exit(1)

    if verdict == "PROVEN":
        if state.get("current_stage") != "STAGE_6_LAB_REPORT_AND_LEARNING":
            print(
                f"[RA GATE] BLOCKED: Cannot mark hypothesis PROVEN from `{state.get('current_stage')}`! "
                "Advance through Stages 3, 4, 5, and 6 first.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not state.get("log_audit_passed", False):
            print(
                "[RA GATE] BLOCKED: Cannot mark hypothesis PROVEN without passing `ra_log_engine.py audit` first!",
                file=sys.stderr,
            )
            sys.exit(1)
        if not state.get("cheese_audit_passed", False):
            print(
                "[RA GATE] BLOCKED: Cannot mark hypothesis PROVEN without passing `ra_cheese_audit.py` first!",
                file=sys.stderr,
            )
            sys.exit(1)
        if not state.get("visual_audit_passed", False):
            print(
                "[RA GATE] BLOCKED: Cannot mark hypothesis PROVEN without passing `ra_visual_audit.py audit` first!",
                file=sys.stderr,
            )
            sys.exit(1)

    agent_id = args.agent or "PRIMARY_AGENT"
    ts = now_iso()

    append_self_learning(rdir, active_hyp, agent_id, args.issue, args.workflow, args.found)

    hyp_dir = rdir / "hypotheses" / active_hyp
    report_path = hyp_dir / "REPORT.md"
    if report_path.exists():
        txt = report_path.read_text(encoding="utf-8")
        txt = txt.replace("**Current Verdict**: `PENDING`", f"**Current Verdict**: `{verdict}`")
        txt = txt.replace("**Final Verdict**: `<PROVEN | FALSIFIED>`", f"**Final Verdict**: `{verdict}`")
        report_path.write_text(txt, encoding="utf-8")

    lab_log = rdir / "LAB_LOG.md"
    if lab_log.exists():
        with lab_log.open("a", encoding="utf-8") as f:
            f.write(
                f"| `{ts}` | `{active_hyp}` | `-` | `{agent_id}` | `{verdict}` "
                f"| {args.found.strip()} | `hypotheses/{active_hyp}/REPORT.md` |\n"
            )

    sandbox_dir = rdir / "sandbox" / active_hyp
    if verdict == "FALSIFIED":
        grave_dir = rdir / "graveyard" / active_hyp
        if sandbox_dir.exists():
            if grave_dir.exists():
                shutil.rmtree(grave_dir)
            shutil.move(str(sandbox_dir), str(grave_dir))
        if report_path.exists():
            shutil.copy2(report_path, grave_dir / "REPORT.md")

        state["consecutive_falsifications"] = state.get("consecutive_falsifications", 0) + 1
        state["current_stage"] = "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING"
        state["active_hypothesis"] = None
        state["cheese_audit_passed"] = False
        state["visual_audit_passed"] = False
        state["log_audit_passed"] = False
        save_state(workspace, state)
        print(
            f"[RA GATE] Hypothesis `{active_hyp}` marked FALSIFIED. "
            f"Sandbox quarantined & moved to `research/graveyard/{active_hyp}/`. Main codebase remains clean.\n"
            f"          Returned to STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING to re-verify workflow context before next hypothesis."
        )
    else:
        state["consecutive_falsifications"] = 0
        state["current_stage"] = "STAGE_7_GRADUATION_REVIEW"
        save_state(workspace, state)
        print(
            f"[RA GATE] Hypothesis `{active_hyp}` marked PROVEN! "
            f"Entered STAGE 7 (Graduation Review). Present the Lab Report to the user before merging."
        )

    print_context_refresh(workspace, state)


def cmd_graduate(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)

    active_hyp = state.get("active_hypothesis")
    if not active_hyp or state.get("current_stage") != "STAGE_7_GRADUATION_REVIEW":
        print("[RA GATE] ERROR: Only a hypothesis in STAGE_7_GRADUATION_REVIEW can be graduated.", file=sys.stderr)
        sys.exit(1)

    ts = now_iso()
    lib_note = rdir / "library" / f"GRADUATED_{active_hyp}.md"
    report_path = rdir / "hypotheses" / active_hyp / "REPORT.md"
    report_body = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    lib_note.write_text(
        f"# [GRADUATED_LAB_TRUTH] {active_hyp}\n\n"
        f"- **Graduated Timestamp**: `{ts}`\n"
        f"- **Provenance**: Survived Stage 1 Workflow Mapping, Stage 4 Adversarial Break-Test, Stage 5 Anti-Cheese Audit, and Stage 7 User Sign-Off.\n\n"
        f"---\n\n{report_body}",
        encoding="utf-8",
    )

    state["current_stage"] = "STAGE_0_INTAKE_AND_SYNC"
    state["active_hypothesis"] = None
    state["cheese_audit_passed"] = False
    state["visual_audit_passed"] = False
    state["log_audit_passed"] = False
    save_state(workspace, state)
    print(f"[RA GATE] Graduated `{active_hyp}` into `research/library/GRADUATED_{active_hyp}.md`!")
    print_context_refresh(workspace, state)


def cmd_seal_axioms(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace, auto_init=True)
    fpath = (workspace / args.file).resolve()
    if not fpath.exists():
        print(f"[RA GATE] ERROR: Axiom file not found: {fpath}", file=sys.stderr)
        sys.exit(1)

    rel = fpath.relative_to(workspace).as_posix()
    digest = sha256_file(fpath)
    lines = len(fpath.read_text(encoding="utf-8").splitlines())
    state.setdefault("sealed_axioms", {})[rel] = {
        "sha256": digest,
        "lines": lines,
        "sealed_at": now_iso(),
    }
    save_state(workspace, state)
    print(f"[RA GATE] Sealed AXIOMATIC_PRIMITIVES file `{rel}` (SHA-256: {digest[:16]}..., {lines} lines).")


def cmd_learn(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = get_research_dir(workspace)
    append_self_learning(
        rdir,
        args.hypothesis or "GENERAL",
        args.agent or "PRIMARY_AGENT",
        args.issue,
        args.workflow,
        args.found,
    )
    print("[RA GATE] Recorded lesson in `research/SELF_LEARNING.md`.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA (research-anything) State-Machine Gatekeeper")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize research/ directory and state machine")
    p_init.add_argument("--workspace", default=".", help="Workspace root directory")
    p_init.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session identifier")
    p_init.add_argument("--name", "--project", dest="project_name", default=None, help="Optional project name")
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="Display current stage, locked invariants, and active instructions")
    p_status.add_argument("--workspace", default=".", help="Workspace root directory")
    p_status.set_defaults(func=cmd_status)

    p_cq = sub.add_parser("check-question", help="Run mandatory pre-question search gate across reference folders")
    p_cq.add_argument("--workspace", default=".", help="Workspace root directory")
    p_cq.set_defaults(func=cmd_check_question)

    p_mc = sub.add_parser(
        "map-context",
        help="Stamp Stage 1 workflow map with session provenance, tracked file SHA-256 hashes, and protected working nodes",
    )
    p_mc.add_argument("--workspace", default=".", help="Workspace root directory")
    p_mc.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID recording this context map")
    p_mc.add_argument("--files", nargs="*", default=[], help="Source files mapped in WORKFLOW_MAP.md to track for staleness")
    p_mc.add_argument(
        "--protected",
        nargs="*",
        default=[],
        help="Working functions/modules verified as innocent by runtime `.log` boundaries (`file:func`) that must NOT be modified",
    )
    p_mc.add_argument(
        "--revoke-protected",
        nargs="*",
        default=[],
        help="Forensically unlock a former `PROTECTED_WORKING` node (`file:func`) after real data / `.log` traces expose it as corrupted",
    )
    p_mc.add_argument(
        "--revoke-reason",
        default="",
        help="Required runtime `.log` or real-data pipe evidence explaining why `--revoke-protected` is unlocking the node",
    )
    p_mc.set_defaults(func=cmd_map_context)

    p_nh = sub.add_parser("new-hypothesis", help="Create a new hypothesis and quarantined sandbox")
    p_nh.add_argument("--workspace", default=".", help="Workspace root directory")
    p_nh.add_argument("--id", required=True, help="Hypothesis ID (e.g., H001)")
    p_nh.add_argument("--slug", required=True, help="Short descriptive slug")
    p_nh.add_argument("--parent", default="NONE", help="Parent hypothesis ID if branching/iterating")
    p_nh.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_nh.set_defaults(func=cmd_new_hypothesis)

    p_adv = sub.add_parser("advance", help="Validate current stage artifacts and advance to the next stage")
    p_adv.add_argument("--workspace", default=".", help="Workspace root directory")
    p_adv.add_argument("--to", default=None, help="Optional target stage name")
    p_adv.set_defaults(func=cmd_advance)

    p_conc = sub.add_parser("conclude", help="Conclude active hypothesis (PROVEN or FALSIFIED) and log self-learning")
    p_conc.add_argument("--workspace", default=".", help="Workspace root directory")
    p_conc.add_argument("--verdict", required=True, choices=["PROVEN", "FALSIFIED", "proven", "falsified"])
    p_conc.add_argument("--issue", required=True, help="Self-learning Issue description")
    p_conc.add_argument("--workflow", required=True, help="Self-learning Workflow flaw/observation")
    p_conc.add_argument("--found", required=True, help="Self-learning Found rule/discovery")
    p_conc.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_conc.set_defaults(func=cmd_conclude)

    p_grad = sub.add_parser("graduate", help="Graduate a user-approved PROVEN hypothesis into research/library/")
    p_grad.add_argument("--workspace", default=".", help="Workspace root directory")
    p_grad.set_defaults(func=cmd_graduate)

    p_seal = sub.add_parser("seal-axioms", help="Cryptographically seal a legitimate axioms file")
    p_seal.add_argument("--workspace", default=".", help="Workspace root directory")
    p_seal.add_argument("--file", required=True, help="Relative path to axioms file")
    p_seal.set_defaults(func=cmd_seal_axioms)

    p_learn = sub.add_parser("learn", help="Append an Issue:Workflow:Found entry to SELF_LEARNING.md")
    p_learn.add_argument("--workspace", default=".", help="Workspace root directory")
    p_learn.add_argument("--hypothesis", default="GENERAL", help="Related hypothesis ID")
    p_learn.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_learn.add_argument("--issue", required=True, help="What went wrong")
    p_learn.add_argument("--workflow", required=True, help="Where the workflow/thinking failed")
    p_learn.add_argument("--found", required=True, help="Permanent rule discovered")
    p_learn.set_defaults(func=cmd_learn)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
