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
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ra_common lives next to this script; `python -I` does not put the script dir on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ra_common import (  # noqa: E402
    DEFAULT_MAX_ROUNDS_PER_APPROACH,
    DIRECTIVES_HEADER,
    FAMILY_RE,
    HASH_ALGO,
    RETIRED_STATUSES,
    approach_key,
    can_reach,
    canonical_spec,
    ceiling_block,
    clear_reviews,
    code_fingerprint,
    describe_matches,
    extract_protected_node,
    family_in_report,
    find_ambiguous,
    fingerprint_files,
    fmt_score,
    grant_manager_edit,
    hash_file,
    hash_protected_node,
    lab_reviews,
    metric_rule,
    pending_reviews_detail,
    quoted_score,
    raw_sha256,
    read_directives,
    read_text_normalised,
    record_review,
    render_board,
    rule_cap,
    rule_has_numbers,
    sb_all_scores,
    sb_get,
    sb_lines,
    sb_lock_instructions,
    sb_summary,
    spec_path,
    unseen_target_met,
    verify_protected_node,
    verify_seal,
    write_state,
)

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
        "3b. TAKE STOCK in `research/INVENTORY.md`: list EVERY asset, dataset, dump and tool already provided (open them),\n"
        "    triage the product's parts KNOWN vs UNKNOWN (KNOWN needs evidence of fit), and define the BRICK:\n"
        "    the crudest end-to-end version that runs. Required before Stage 2.\n"
        "4. [OPTIONAL] Equip the R&D Arsenal (`ra_crawler.py` — only when the project benefits from external skills/papers/data):\n"
        "   - Priority #1 (Skill Crawler): `ra_crawler.py skill --query \"<domain>\"` (installs project-local skills).\n"
        "   - Priority #2 (Paper Crawler): `ra_crawler.py paper --query \"<topic>\"` (if prior art/equations needed).\n"
        "   - Priority #3 (Data Crawler) : `ra_crawler.py data --query \"<dataset>\"` (if test vectors needed).\n"
        "5. Forge Project-Local Skill, `.py` Harness/Hooks & Review Agent (if needed):\n"
        "   `ra_forge.py --name \"<project-slug>\" --domain \"<domain>\"`\n"
        "6. Advance to Stage 1 (`ra_gate.py map-context --agent <id> [--files ...]`)."
    ),
    "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING": (
        "0. `research/INVENTORY.md` (take stock, KNOWN/UNKNOWN triage, the brick) must be filled before leaving Stage 1.\n"
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
        "1. BRICK FIRST: if `research/INVENTORY.md` says the brick is NOT BUILT, this hypothesis IS the brick.\n"
        "   Otherwise target the brick's weakest link only.\n"
        "2. OPTION SWEEP in REPORT.md Section 3: >= 3 approach FAMILIES (parameter variants = one family),\n"
        "   each with expected ceiling, cost and the inventory assets it uses. Name the baseline to beat.\n"
        "   Put each family's paper ceiling on the board: `ra_gate.py ceiling --approach <family> --estimate <x>\n"
        "   --basis \"<math / simulation / small experiment>\"`. A ceiling that can't reach the target refuses runs.\n"
        "3. Write success criteria + plateau rule, and register them WITH NUMBERS:\n"
        "   `ra_gate.py stop-rule --component <slug> ... --metric \"<name>\" --target <x> --min-gain <g> [--lower-is-better]`.\n"
        "   Every R&D problem has a number; if nothing else, pass-rate over real cases (0..1).\n"
        "4. Fill Section 2 (workflow context) too. Do NOT write boilerplate. Derive from first principles.\n"
        "   Judgment calls are yours: decide and record them (`ra_gate.py decide --what ... --why ...`), don't ask.\n"
        "5. Run `ra_gate.py advance` to unlock Stage 3 (Sandbox Prototype)."
    ),
    "STAGE_3_SANDBOX_PROTOTYPE": (
        "1. LEAD-ORCHESTRATOR DELEGATION & CONTEXT FORKING (`ra_context_harness.py`):\n"
        "   Fork the shared snapshot to a Subagent (`ra_context_harness.py fork --subagent Subagent_A --snapshots <snap_id> --task \"...\"`),\n"
        "   let the Subagent build the prototype & write its report, then reclaim the baton (`ra_context_harness.py return-baton --subagent Subagent_A`).\n"
        "   You are the lab MANAGER: every returned report gets a review meeting before the next fork\n"
        "   (`ra_gate.py review --file research/reviews/REVIEW_<n>.md`: DECISION / LESSON / NEXT lines). `ra_gate.py board`.\n"
        "2. Build the prototype inside `research/sandbox/<active_hypothesis>/<family>/`. RACE the chosen families cheaply\n"
        "   on the SAME real data before polishing any one of them. Use the assets in `research/INVENTORY.md`.\n"
        "   Every program prints `RA_SCORE=<x>`; every `ra_log_engine.py run --approach <family>` is a scored round.\n"
        "3. WIRE PRODUCTION `.log` TELEMETRY (`ra_log_engine.py`): Silent code and bare `print()` are BANNED.\n"
        "   Inject/import `RALogger` (`ra_log_engine.py inject-sdk --lang <python|js|ts|php> --dest research/sandbox/<active_hypothesis>`)\n"
        "   and log every flow hop (`flow=caller->callee`, `role`, `inputs`, `state_before`, `state_after`, `output`, `contract=BC-xxx`).\n"
        "4. Keep the main codebase and all `PROTECTED_WORKING` functions 100% clean and untouched.\n"
        "5. Place legitimate mathematical/structural axioms in a sealed `axioms` file (`ra_gate.py seal-axioms`).\n"
        "6. Run `ra_gate.py advance` to unlock Stage 4 (Real-Environment `.log` & Stress Verification)."
    ),
    "STAGE_4_ADVERSARIAL_BREAK_TEST": (
        "1. Synthetic unit-test marathons (`test_xyz.py`) are BANNED. Verify in the REAL ENVIRONMENT via `.log` telemetry:\n"
        "   `python ra_log_engine.py run --workspace . --hypothesis <active_hypothesis> --approach <family> [--unseen] --timeout-sec 60 -- <real-run-cmd>`\n"
        "2. Audit the generated `.log` file for `[PASS]`, `[DECISION]`, `[STUCK]`, `[FAIL]`, full variable values, and `BC-xxx` contracts:\n"
        "   `python ra_log_engine.py audit --workspace . --hypothesis <active_hypothesis>`\n"
        "3. USER-EYES VISUAL REALITY CHECK (if UI/CSS/game/visual output): Run `ra_visual_audit.py init --hypothesis <active_hypothesis>`,\n"
        "   capture live screenshots into `visual_captures/`, open & inspect the pixels (`read_file`), and complete `VISUAL_AUDIT.md`.\n"
        "4. If any hop is `[STUCK]` or `[FAIL]`, fix the upstream mechanism (NO `if/else` or `try/except` band-aids!).\n"
        "5. SCOREBOARD (mechanical, `ra_gate.py status --scoreboard`): each `run` records its `RA_SCORE=<x>`; pass\n"
        "   `--unseen` on held-out data. No score x3 (BLIND), best of the last 3 under min-gain (FLAT), baseline never\n"
        "   beaten, the per-approach round cap, or a trend that can't reach the target within the budget (TREND)\n"
        "   = PLATEAUED -> runs LOCK until a FRESH subagent's `ra_gate.py cold-review` says CONTINUE (one grace round),\n"
        "   SWITCH (next family) or BRICK-FIRST. Target met on unseen = WON.\n"
        "6. Once `ra_log_engine.py audit` passes, run `ra_gate.py advance` to unlock Stage 5."
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
        "   - If FALSIFIED (incl. PLATEAUED): sandbox is archived to `research/graveyard/`, main code stays clean, and you loop\n"
        "     back to Stage 1/2 with the NEXT FAMILY from the Option Sweep — never a tweak of the archived one.\n"
        "   - If PROVEN (needs an `--unseen` round that met the stop rule's target): moves to Stage 7 (Graduation Review).\n"
        "     After graduation, update the brick's weakest link in INVENTORY.md."
    ),
    "STAGE_7_GRADUATION_REVIEW": (
        "1. Run the forged project harness (`python research/harness/project_harness.py check-all`) and invoke the\n"
        "   Adversarial Review Agent (`.claude/agents/ra-reviewer.md` / `research/harness/REVIEW_AGENT_PROMPT.md`).\n"
        "2. STOP AND PRESENT TO USER: Show the Lab Report summary, workflow blast-radius verification, and empirical bounds.\n"
        "3. Wait for explicit user approval before merging sandbox code into the main project.\n"
        "4. After user approval, run `ra_gate.py graduate --user-approved \"<the user's exact words>\"` to record the truth\n"
        "   in `research/library/`."
    ),
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_md(path: Path) -> str:
    # utf-8-sig: editors on Windows love to prepend a BOM.
    return path.read_text(encoding="utf-8-sig")


def gate_error(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def reason_problem(text: str, flag: str, min_len: int = 30) -> Optional[str]:
    """Why a free-text justification is too weak to accept, or None if it is acceptable."""
    t = (text or "").strip()
    if len(t) < min_len:
        return f"`{flag}` must be at least {min_len} characters (got {len(t)})."
    if len(set(t.replace(" ", "").lower())) < 4 or len(set(t.split())) < 2:
        return f"`{flag}` looks like filler (repeated characters/words). Write the real reason."
    return None


def numbers_line(sr: Dict[str, Any]) -> str:
    return (
        f"`{sr.get('metric') or '?'}` target {fmt_score(sr.get('target'))}, min-gain {fmt_score(sr.get('min_gain'))}, "
        f"{'lower' if sr.get('lower_is_better') else 'higher'} is better, "
        f"cap {rule_cap(sr)} rounds/approach"
    )


def print_scoreboard(workspace: Path, state: Dict[str, Any], hyp: str, stream: Any = None) -> None:
    out = stream or sys.stdout
    print(f"  SCOREBOARD - `{hyp}`", file=out)
    for line in sb_lines(workspace, state, hyp):
        print(f"    {line}", file=out)


def sanitize_token(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw.strip()).strip("_-")


def safe_research_path(rdir: Path, *parts: str) -> Path:
    """rdir/parts resolved, refusing anything that escapes research/ (e.g. `../../src`)."""
    base = rdir.resolve()
    p = base.joinpath(*parts).resolve()
    if p == base or base not in p.parents:
        gate_error(
            f"[RA GATE] REFUSED: `{'/'.join(parts)}` resolves outside `research/` ({p}). "
            "Hypothesis ids/slugs may only contain [A-Za-z0-9_-]; fix `active_hypothesis` in `research/.ra_state.json`."
        )
    return p


def _table_cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def workspace_rel(workspace: Path, path: Path) -> Optional[str]:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return None


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
        "INVENTORY.md": rdir / "INVENTORY.md",
        "LAB_LOG.md": rdir / "LAB_LOG.md",
        "SELF_LEARNING.md": rdir / "SELF_LEARNING.md",
        "REFERENCES_INDEX.md": rdir / "library" / "REFERENCES_INDEX.md",
    }
    for tname, dest in template_map.items():
        if not dest.exists():
            src = templates_dir / tname
            content = read_md(src) if src.exists() else f"# {tname}\n"
            content = content.replace("<ISO-8601>", ts).replace("<YYYY-MM-DD>", ts[:10]).replace("<agent-id>", agent_id)
            dest.write_text(content, encoding="utf-8")

    state_path = get_state_path(workspace)
    if not state_path.exists():
        state = {
            "version": "1.5.0",
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
    return json.loads(read_md(state_path))


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
    state = json.loads(read_md(sp))
    if maintain_state(workspace, state):
        save_state(workspace, state)
    return state


def save_state(workspace: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    write_state(workspace, state)


PASS_FLAGS = {
    "log_audit_passed": "ra_log_engine.py audit",
    "visual_audit_passed": "ra_visual_audit.py audit",
    "cheese_audit_passed": "ra_cheese_audit.py",
}


def maintain_state(workspace: Path, state: Dict[str, Any]) -> bool:
    """Upgrade pre-ra_common hashes and expire audit pass flags whose code changed. True if state changed."""
    changed = False
    for rel_path, meta in state.get("sealed_axioms", {}).items():
        status, current = verify_seal(workspace.resolve() / rel_path, meta)
        if status == "LEGACY_OK":
            meta["sha256"], meta["algo"] = current, HASH_ALGO
            changed = True
    phashes: Dict[str, str] = state.get("protected_node_hashes", {})
    for spec, expected in list(phashes.items()):
        status, current = verify_protected_node(workspace, spec, expected)
        if status == "LEGACY_OK" and current:
            phashes[spec] = current
            changed = True

    # A pass flag is only valid for the code it was earned on.
    hyp = state.get("active_hypothesis")
    fps: Dict[str, str] = state.setdefault("pass_fingerprints", {})
    current_fp = code_fingerprint(workspace, state, hyp)
    for flag, tool in PASS_FLAGS.items():
        if not state.get(flag):
            if fps.pop(flag, None) is not None:
                changed = True
            continue
        recorded = fps.get(flag)
        if recorded is None:
            # First sight of a flag set by an audit tool: anything edited after that tool's state write is unaudited.
            sp = get_state_path(workspace)
            state_mtime = sp.stat().st_mtime if sp.exists() else 0.0
            newest = max((p.stat().st_mtime for p in fingerprint_files(workspace, state, hyp) if p.is_file()), default=0.0)
            stale = newest > state_mtime
        else:
            stale = recorded != current_fp
        if stale:
            state[flag] = False
            fps.pop(flag, None)
            print(f"[RA GATE] Code changed since `{flag}` was earned -> cleared. Re-run `{tool}`.", file=sys.stderr)
        else:
            fps[flag] = current_fp
        changed = changed or stale or recorded is None
    return changed


def verify_sealed_axioms(workspace: Path, state: Dict[str, Any]) -> List[str]:
    violations: List[str] = []
    sealed = state.get("sealed_axioms", {})
    for rel_path, meta in sealed.items():
        status, current_hash = verify_seal(workspace.resolve() / rel_path, meta)
        if status == "MISSING":
            violations.append(
                f"Sealed axiom file deleted: {rel_path} (if intentional: `ra_gate.py unseal --file {rel_path} --reason \"...\"`)"
            )
        elif status == "TAMPERED":
            violations.append(
                f"AXIOM SEAL VIOLATION on `{rel_path}`! Expected SHA-256 {str(meta.get('sha256'))[:12]}..., "
                f"got {str(current_hash)[:12]}... Do NOT sneak hardcoded data into sealed axioms!"
            )
    return violations


def verify_protected_nodes(workspace: Path, state: Dict[str, Any]) -> List[str]:
    violations: List[str] = []
    for spec, expected in state.get("protected_node_hashes", {}).items():
        status, _ = verify_protected_node(workspace, spec, expected)
        if status == "MISSING":
            violations.append(f"PROTECTED node `{spec}` was deleted or renamed.")
        elif status == "AMBIGUOUS":
            violations.append(
                f"PROTECTED node `{spec}` now matches several definitions ({', '.join(describe_matches(workspace, spec))})."
            )
        elif status == "TAMPERED":
            violations.append(f"PROTECTED node `{spec}` was modified since it was locked.")
    unhashed = [n for n in state.get("protected_nodes", []) if n not in state.get("protected_node_hashes", {})]
    for spec in unhashed:
        violations.append(f"PROTECTED node `{spec}` has no stored hash (registered by an older RA); re-register it.")
    return violations


def verify_integrity(workspace: Path, state: Dict[str, Any]) -> List[str]:
    return verify_sealed_axioms(workspace, state) + verify_protected_nodes(workspace, state)


def block_on_integrity(workspace: Path, state: Dict[str, Any], action: str) -> None:
    violations = verify_integrity(workspace, state)
    if violations:
        print(f"[RA GATE] BLOCKED ({action}): sealed axiom / protected node integrity check failed:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "  Revert the change. If real-data `.log` evidence proves a protected node is the culprit, run\n"
            "  `ra_gate.py map-context --revoke-protected <spec> --revoke-reason \"...\"`; for a sealed file,\n"
            "  `ra_gate.py unseal --file <path> --reason \"...\"`.",
            file=sys.stderr,
        )
        sys.exit(1)


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
            curr_hash = hash_file(fpath)
            # Snapshots taken before ra_common hashed raw bytes.
            if curr_hash != recorded_hash and raw_sha256(fpath) != recorded_hash:
                notices.append(
                    f"`{rel_path}` changed since snapshot ({recorded_hash[:10]}... -> {curr_hash[:10]}...)"
                )
    return notices


# `- **`BC-001`**:`, `- **BC-001**:`, `- `BC-001``, `- BC-001:` all count.
def _id_line_re(prefix: str) -> "re.Pattern[str]":
    return re.compile(rf"^[-*]\s+(?:\*\*)?`?{prefix}-\d+")


def extract_locked_invariants(workspace: Path) -> List[str]:
    inv_file = get_research_dir(workspace) / "INVARIANTS.md"
    if not inv_file.exists():
        return []
    pat = _id_line_re("INV")
    return [ln.strip() for ln in read_md(inv_file).splitlines() if pat.match(ln.strip()) and "<e.g.," not in ln]


def extract_behavioral_contracts(workspace: Path) -> List[str]:
    wmap_file = get_research_dir(workspace) / "WORKFLOW_MAP.md"
    if not wmap_file.exists():
        return []
    pat = _id_line_re("BC")
    return [ln.strip() for ln in read_md(wmap_file).splitlines() if pat.match(ln.strip()) and "<e.g.," not in ln]


def print_context_refresh(workspace: Path, state: Dict[str, Any]) -> None:
    stage = state.get("current_stage", "STAGE_0_INTAKE_AND_SYNC")
    active_hyp = state.get("active_hypothesis") or "NONE"
    fals_count = state.get("consecutive_falsifications", 0)
    invariants = extract_locked_invariants(workspace)
    contracts = extract_behavioral_contracts(workspace)
    violations = verify_integrity(workspace, state)
    stale_notices = check_context_map_staleness(workspace, state)
    cmap = state.get("context_map_snapshot", {})
    protected_nodes = state.get("protected_nodes", [])

    print("=" * 78)
    print("  RA (RESEARCH ANYTHING) — STATE MACHINE & CONTEXT REFRESH")
    print("=" * 78)
    if state.get("project_name"):
        print(f"  Project                    : {state['project_name']}")
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
            sreg = json.loads(read_md(snap_reg_path))
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
    summary = sb_summary(state, state.get("active_hypothesis"))
    if summary:
        print(f"  Scoreboard                 : {summary}")
    print("-" * 78)

    sb_lock = sb_get(state, active_hyp, create=False).get("lock") if state.get("active_hypothesis") else None
    if sb_lock:
        print(f"  [!!!] RUNS LOCKED for `{active_hyp}` - {sb_lock.get('reason')}")
        for line in sb_lock_instructions(state, active_hyp):
            print(f"        {line}")
        print("-" * 78)

    if stale_notices:
        print("  [!] WORKFLOW MAP STALENESS / ALTERED CODE WARNING:")
        print("      `research/WORKFLOW_MAP.md` was written by an earlier AI session and tracked files changed:")
        for sn in stale_notices:
            print(f"      - {sn}")
        print("      Re-verify live code and update `WORKFLOW_MAP.md` via `ra_gate.py map-context`!")
        print("-" * 78)

    if violations:
        print("  [!!!] CRITICAL AXIOM SEAL / PROTECTED NODE VIOLATIONS DETECTED:")
        for v in violations:
            print(f"    - {v}")
        print("-" * 78)

    if fals_count >= 5:
        print("  [!!!] CHECKPOINT REACHED: 5 consecutive hypotheses falsified on this track.")
        print("        PAUSE autonomous looping and present the Lab Reports to the user.")
        print("        `new-hypothesis` is LOCKED until you pass the user's own words:")
        print("        `ra_gate.py new-hypothesis ... --user-approved \"<what the user said>\"`")
        print("-" * 78)

    if protected_nodes:
        print("  PROTECTED WORKING NODES (`Symptom != Culprit` — DO NOT MODIFY THESE):")
        for pn in protected_nodes:
            print(f"    - [PROTECTED] {pn}")
        print("-" * 78)

    stop_rules: Dict[str, Any] = state.get("stop_rules", {})
    if stop_rules:
        print("  REGISTERED STOP RULES & 'IF IT NEVER WORKS' PIVOT PLANS (NO INFINITE FAIL->FIX->RETEST):")
        for comp_name, sr in stop_rules.items():
            f_rounds = sr.get("failed_rounds", 0)
            m_rounds = sr.get("max_rounds", 2)
            st = sr.get("status", "ACTIVE")
            print(f"    - [{st}] `{comp_name}` (Failed Rounds: {f_rounds}/{m_rounds})")
            print(f"      Purpose & Reliable Split : {sr.get('purpose', '')}")
            print(f"      Success Criteria         : {sr.get('success_criteria', '')}")
            print(f"      If It Never Works Pivot  : {sr.get('if_never_works', '')}")
            if sr.get("metric") or sr.get("target") is not None:
                print(f"      Number                   : {numbers_line(sr)}")
            if st == "PIVOT_TRIGGERED" or f_rounds >= m_rounds:
                print(
                    f"      [!!! STOP RULE TRIGGERED] Stop tweaking `{comp_name}`! Switch to the `If It Never Works` pivot immediately!"
                )
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
    if args.project_name and state.get("project_name") != args.project_name.strip():
        state["project_name"] = args.project_name.strip()
        save_state(workspace, state)
    print(f"[RA GATE] Initialized research repository at: {rdir}")
    print_context_refresh(workspace, state)


def cmd_status(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    if not get_state_path(workspace).exists():
        # status is read-only: it must never plant research/ (and arm the manager hooks) in a stray folder.
        print(f"[RA GATE] No RA workspace at {workspace} (no research/.ra_state.json). Nothing was created.")
        print("  New project  : ra_gate.py init --workspace .")
        print("  Wrong folder : cd to the project root and run status again.")
        return
    state = load_state(workspace)
    if not args.scoreboard:
        print_context_refresh(workspace, state)
        return
    hyp = (args.hypothesis or "").strip() or state.get("active_hypothesis")
    if not hyp:
        gate_error("[RA GATE] No active hypothesis; pass `--hypothesis <id>` to show an older scoreboard.", 1)
    print("=" * 78)
    print_scoreboard(workspace, state, hyp)
    if sb_get(state, hyp, create=False).get("lock"):
        print("  WHAT TO DO:")
        for line in sb_lock_instructions(state, hyp):
            print(f"    {line}")
    print("=" * 78)


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
        for line in glossary_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()[:30]:
            print(f"    {line}")

    ref_idx = rdir / "library" / "REFERENCES_INDEX.md"
    if ref_idx.exists():
        print("-" * 78)
        print("  INDEXED USER REFERENCES & PAST ANSWERS (`research/library/REFERENCES_INDEX.md`):")
        for line in ref_idx.read_text(encoding="utf-8-sig").splitlines()[:40]:
            print(f"    {line}")

    wmap = rdir / "WORKFLOW_MAP.md"
    if wmap.exists():
        print("-" * 78)
        print("  MAPPED SYSTEM WORKFLOW (`research/WORKFLOW_MAP.md` — check before asking how code flows):")
        for line in wmap.read_text(encoding="utf-8-sig").splitlines()[:25]:
            print(f"    {line}")

    print("-" * 78)
    print("  If the question is a judgment call you can make yourself, make it and record it instead of asking:")
    print("    ra_gate.py decide --what \"<decision>\" --why \"<reason>\" [--alternatives \"<a; b>\"]")
    print("=" * 78)


SUSPICIOUS_INNOCENCE_RE = re.compile(
    r"(except\s*(?:Exception|BaseException)?\s*:\s*pass\b|catch\s*\([^)]*\)\s*\{\s*\}|"
    r"\b(?:mock_?data|fake_?data|dummy_?data|nan_to_num|NotImplementedError)\b|"
    r"(?:#|//)\s*(?:TODO|FIXME|hack|band-?aid|hardcoded)\b)",
    re.IGNORECASE,
)

# The template writes these lines as `> - **Last Mapped By ...`; keep whatever prefix is there.
_STAMP_AGENT_RE = re.compile(r"^(\s*(?:>\s*)?[-*]\s+\*\*Last Mapped By \(Agent / Session\)\*\*:).*$")
_STAMP_TS_RE = re.compile(r"^(\s*(?:>\s*)?[-*]\s+\*\*Last Snapshot Timestamp\*\*:).*$")


def cmd_map_context(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace, auto_init=True)
    rdir = get_research_dir(workspace)
    wmap_path = rdir / "WORKFLOW_MAP.md"

    agent_id = args.agent or "PRIMARY_AGENT"
    ts = now_iso()

    # Validate everything first: a refusal must not leave a half-applied revoke behind.
    errors: List[str] = []
    tracked_updates: Dict[str, str] = {}
    for fstr in args.files or []:
        fpath = (workspace / fstr).resolve()
        rel = workspace_rel(workspace, fpath)
        if rel is None:
            errors.append(f"`--files {fstr}` is outside the workspace ({fpath}).")
        elif not fpath.is_file():
            print(f"[RA GATE] WARNING: Tracked file not found: {fstr}", file=sys.stderr)
        else:
            tracked_updates[rel] = hash_file(fpath)

    protected: List[str] = list(state.get("protected_nodes", []))
    protected_hashes: Dict[str, str] = dict(state.get("protected_node_hashes", {}))
    # Older states may hold backslash specs; match nodes on their canonical form.
    known = {canonical_spec(workspace, k) or k: k for k in protected + list(protected_hashes)}

    revokes: List[str] = []
    reason = (args.revoke_reason or "").strip()
    if args.revoke_protected:
        problem = reason_problem(reason, "--revoke-reason")
        if problem:
            errors.append(
                "Forensic Lock Revocation (`--revoke-protected`) needs `--revoke-reason` quoting the runtime `.log` "
                f"or real-data evidence that exposed the node as corrupted. {problem}"
            )
        for rnode in args.revoke_protected:
            key = known.get(canonical_spec(workspace, rnode) or rnode)
            if key is None:
                errors.append(f"`--revoke-protected {rnode}` is not a protected node (protected: {sorted(known) or 'none'}).")
            elif key not in revokes:
                revokes.append(key)

    registrations: Dict[str, Any] = {}
    for pnode in args.protected or []:
        canon = canonical_spec(workspace, pnode)
        if canon is None:
            errors.append(f"`--protected {pnode}` is outside the workspace ({spec_path(workspace, pnode)}).")
            continue
        count = find_ambiguous(workspace, canon)
        if count == 0:
            errors.append(
                f"`--protected {pnode}` not found (missing file, or no def/class/function of that name). "
                "Use `path`, `path:name` or `path:Class.method`."
            )
            continue
        if count > 1:
            errors.append(
                f"`--protected {pnode}` is ambiguous: it matches {', '.join(describe_matches(workspace, canon))}. "
                "Use a qualified `path:Class.method` spec."
            )
            continue
        seg = extract_protected_node(workspace, canon)
        m_susp = SUSPICIOUS_INNOCENCE_RE.search(seg) if seg is not None else None
        if m_susp:
            errors.append(
                f"Zero-Trust Innocence Check Failed for `{pnode}`: its source contains a suspicious band-aid / "
                f"fake-data / stub pattern `{m_susp.group(0)}`. Only lock functions proven clean by runtime "
                "`[RA_LOG]` boundary traces!"
            )
            continue
        phash = hash_protected_node(workspace, canon)
        if phash is None:
            errors.append(f"`--protected {pnode}` could not be hashed; refusing a lock that would never be enforced.")
            continue
        old_key = known.get(canon)
        if old_key in protected_hashes and old_key not in revokes:
            status, _ = verify_protected_node(workspace, old_key, protected_hashes[old_key])
            if status not in ("OK", "LEGACY_OK"):
                errors.append(
                    f"`{pnode}` is already protected and is now {status} since it was locked. Re-registering would "
                    f"silently re-baseline the tampered code. Revert it, or unlock it in the same call with "
                    f"`--revoke-protected {old_key} --revoke-reason \"<.log evidence>\"`."
                )
                continue
        where = "whole file" if ":" not in canon else ", ".join(describe_matches(workspace, canon))
        registrations[canon] = (phash, old_key, where)

    if errors:
        print("[RA GATE BLOCKED] map-context refused; nothing was changed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    tracked: Dict[str, str] = state.get("context_map_snapshot", {}).get("tracked_files", {})
    tracked.update(tracked_updates)

    for rnode in revokes:
        if rnode in protected:
            protected.remove(rnode)
        protected_hashes.pop(rnode, None)
        state.setdefault("revoked_protected_history", []).append(
            {"node": rnode, "revoked_by": agent_id, "revoked_at": ts, "reason": reason}
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

    for canon, (phash, old_key, where) in registrations.items():
        if old_key and old_key != canon:
            if old_key in protected:
                protected.remove(old_key)
            protected_hashes.pop(old_key, None)
        if canon not in protected:
            protected.append(canon)
        protected_hashes[canon] = phash
        print(f"[RA GATE] Locked `{canon}` as PROTECTED_WORKING ({where}, SHA-256 {phash[:12]}...).")

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
        updated_lines: List[str] = []
        for line in read_md(wmap_path).splitlines():
            line = _STAMP_AGENT_RE.sub(lambda m: f"{m.group(1)} `{agent_id}`", line)
            line = _STAMP_TS_RE.sub(lambda m: f"{m.group(1)} `{ts}`", line)
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
    txt = wmap_path.read_text(encoding="utf-8-sig")
    if "<Exact file and function/symbol>" in txt or "<Why is this the true root-cause location" in txt:
        return False
    return True


INVENTORY_PLACEHOLDERS = ("<Asset / data / code / tool>", "| <part> |", "<input -> part -> part")


def is_inventory_populated(rdir: Path) -> bool:
    inv_path = rdir / "INVENTORY.md"
    if not inv_path.exists():
        return False
    txt = inv_path.read_text(encoding="utf-8-sig")
    return not any(p in txt for p in INVENTORY_PLACEHOLDERS)


def ensure_inventory_file(rdir: Path) -> None:
    # Projects initialised before INVENTORY.md existed get the template on first gate check.
    inv_path = rdir / "INVENTORY.md"
    tpl = get_skill_root() / "resources" / "templates" / "INVENTORY.md"
    if not inv_path.exists() and tpl.exists():
        inv_path.write_text(tpl.read_text(encoding="utf-8-sig"), encoding="utf-8")


OPTION_SWEEP_PLACEHOLDERS = (
    "<Which part of the brick",
    "<The simplest or existing solution",
    "<approach family A>",
    "<number that means WORKS",
    "<minimum gain per round",
)


def stop_rule_for(state: Dict[str, Any], hyp: str) -> bool:
    return any(sr.get("hypothesis") == hyp for sr in state.get("stop_rules", {}).values())


def load_context_snapshot_registry(rdir: Path) -> Dict[str, Any]:
    reg_path = rdir / "context_snapshots" / "SNAPSHOT_REGISTRY.json"
    if not reg_path.exists():
        return {}
    try:
        return json.loads(reg_path.read_text(encoding="utf-8-sig"))
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

    block_on_integrity(workspace, state, "new-hypothesis")

    agent_id = args.agent or "PRIMARY_AGENT"
    ts = now_iso()
    fals_count = state.get("consecutive_falsifications", 0)
    approval = (args.user_approved or "").strip()
    if fals_count >= 5:
        problem = reason_problem(approval, "--user-approved", min_len=10)
        if problem:
            gate_error(
                f"[RA GATE] BLOCKED: {fals_count} consecutive hypotheses FALSIFIED. Stop the autonomous loop, present\n"
                "          the Lab Reports to the user, and ask whether to continue or pivot the direction.\n"
                "          Then pass their exact words: `new-hypothesis ... --user-approved \"<what the user said>\"`.\n"
                f"          ({problem})",
                1,
            )

    hyp_id = sanitize_token(args.id).upper()
    slug = sanitize_token(args.slug.strip().lower().replace(" ", "_"))
    if not hyp_id or not slug:
        gate_error("[RA GATE] ERROR: `--id` and `--slug` need at least one character from [A-Za-z0-9_-].")
    full_id = f"{hyp_id}_{slug}"
    if full_id != f"{args.id.strip().upper()}_{args.slug.strip().lower().replace(' ', '_')}":
        print(f"[RA GATE] NOTE: id/slug sanitised to `{full_id}` (only [A-Za-z0-9_-] allowed).", file=sys.stderr)
    parent_id = sanitize_token(args.parent or "") or "NONE"

    hyp_dir = safe_research_path(rdir, "hypotheses", full_id)
    sandbox_dir = safe_research_path(rdir, "sandbox", full_id)
    if fals_count >= 5:
        state.setdefault("checkpoint_approvals", []).append(
            {"timestamp": ts, "falsifications": fals_count, "user_approved": approval, "next_hypothesis": full_id}
        )
        state["consecutive_falsifications"] = 0
        lab_log = rdir / "LAB_LOG.md"
        if lab_log.exists():
            with lab_log.open("a", encoding="utf-8") as f:
                f.write(
                    f"| `{ts}` | `{hyp_id}` | `{parent_id}` | `{agent_id}` | `CHECKPOINT_APPROVED` "
                    f"| User: \"{_table_cell(approval)}\" | `-` |\n"
                )
    hyp_dir.mkdir(parents=True, exist_ok=True)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    tpl_path = get_skill_root() / "resources" / "templates" / "HYPOTHESIS_REPORT.md"
    report_path = hyp_dir / "REPORT.md"
    if not report_path.exists():
        tpl = tpl_path.read_text(encoding="utf-8-sig") if tpl_path.exists() else "# Report\n"
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
        if (is_workflow_map_populated(rdir) and is_inventory_populated(rdir) and has_reusable_context_snapshot(rdir))
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

    block_on_integrity(workspace, state, "advance")

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
        ensure_inventory_file(rdir)
        if not is_inventory_populated(rdir):
            print(
                "[RA GATE] BLOCKED: `research/INVENTORY.md` is not filled in. Before any hypothesis:\n"
                "          1. Take stock of EVERY asset, dataset, dump and tool already provided (open them).\n"
                "          2. Triage parts KNOWN vs UNKNOWN (KNOWN needs evidence it fits this project).\n"
                "          3. Define the brick: the crudest end-to-end version that runs, and its status.",
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
                "[RA GATE] Stage 1 checks passed (WORKFLOW_MAP.md, INVENTORY.md, Context Snapshot). There is no hypothesis\n"
                "          to advance yet. NEXT STEP: `ra_gate.py new-hypothesis --id H001 --slug <name>` opens it in Stage 2."
            )
            return
        state["current_stage"] = "STAGE_2_HYPOTHESIS_FORMULATION"
        save_state(workspace, state)
        print(f"[RA GATE] Advanced `{active_hyp}` to STAGE_2_HYPOTHESIS_FORMULATION.")
        print_context_refresh(workspace, state)
        return

    if not active_hyp:
        print("[RA GATE] ERROR: No active hypothesis. Run `new-hypothesis` first.", file=sys.stderr)
        sys.exit(1)

    hyp_dir = safe_research_path(rdir, "hypotheses", active_hyp)
    sandbox_dir = safe_research_path(rdir, "sandbox", active_hyp)
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
        report_txt = report_path.read_text(encoding="utf-8-sig")
        if "<Empirical proof that this node is the root cause" in report_txt:
            print(
                "[RA GATE] BLOCKED: You have not filled out Section 2 (Workflow Context, Culprit Proof & "
                "Pre-Edit/Pre-Creation Justification) in REPORT.md!",
                file=sys.stderr,
            )
            sys.exit(1)
        missing = [p for p in OPTION_SWEEP_PLACEHOLDERS if p in report_txt]
        if "Option Sweep" not in report_txt:
            missing.append("Section 3 'Option Sweep, Baseline & Stop Rule' (copy it from the current HYPOTHESIS_REPORT.md template)")
        if missing or "<Write the exact equations" in report_txt or "<Exact equations, state transitions" in report_txt:
            print(
                "[RA GATE] BLOCKED: Section 3 of REPORT.md is not filled out. Required: weakest link targeted,\n"
                "          baseline to beat, an Option Sweep of >= 3 approach FAMILIES, success criteria, plateau rule,\n"
                "          and the chosen approach's formulation. Still unfilled:\n"
                + "\n".join(f"            - {p}..." for p in missing),
                file=sys.stderr,
            )
            sys.exit(1)
        stop_hint = (
            f"`ra_gate.py stop-rule --component <slug> --purpose \"...\" --success-criteria \"...\" "
            f"--max-rounds 2 --if-never-works \"<next family from the Option Sweep>\" "
            f"--metric \"<name>\" --target <x> --min-gain <g> [--lower-is-better]`"
        )
        if not stop_rule_for(state, active_hyp):
            print(
                f"[RA GATE] BLOCKED: No stop rule registered for `{active_hyp}`. Before building, run:\n          {stop_hint}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not any(
            sr.get("hypothesis") == active_hyp and rule_has_numbers(sr) for sr in state.get("stop_rules", {}).values()
        ):
            print(
                f"[RA GATE] BLOCKED: the stop rule for `{active_hyp}` has no number. It needs `--metric`, `--target`\n"
                "          and `--min-gain` (plus `--lower-is-better` if smaller wins): every R&D problem has a number;\n"
                "          if nothing else, pass-rate over real cases (0..1). Re-register the same component:\n"
                f"          {stop_hint}",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_3_SANDBOX_PROTOTYPE"

    elif stage == "STAGE_3_SANDBOX_PROTOTYPE":
        ignored_meta = {"visual_audit.md", "ra_logger.py", "ra_logger.js", "ra_logger.ts", "ra_logger.mjs", "ralogger.php"}
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
            "[RA GATE] Waiting for User Graduation Sign-Off. Run `ra_gate.py graduate --user-approved \"<their words>\"` only AFTER "
            "the user approves the Lab Report.",
            file=sys.stderr,
        )
        sys.exit(1)

    save_state(workspace, state)
    print(f"[RA GATE] Advanced `{active_hyp}` to {state['current_stage']}.")
    print_context_refresh(workspace, state)


def append_self_learning(
    rdir: Path, hyp_id: str, agent_id: str, issue: str, workflow: str, found: str
) -> bool:
    sl_path = rdir / "SELF_LEARNING.md"
    ts = now_iso()
    existing = read_md(sl_path) if sl_path.exists() else "# Self-Learning Log\n"
    body = (
        f"- **Related Hypothesis**: `{hyp_id}`\n"
        f"- **Issue**: {issue.strip()}\n"
        f"- **Workflow**: {workflow.strip()}\n"
        f"- **Found**: {found.strip()}\n"
    )
    # A retried command must not log the same lesson twice.
    if body in existing:
        return False
    sl_id = f"SL-{existing.count('### `SL-'):03d}"
    entry = f"\n### `{sl_id}` ({hyp_id})\n- **Date / Agent**: `{ts}` / `{agent_id}`\n" + body
    rdir.mkdir(parents=True, exist_ok=True)
    with sl_path.open("a", encoding="utf-8") as f:
        if not sl_path.exists() or sl_path.stat().st_size == 0:
            f.write(existing)
        f.write(entry)
    return True


def append_lab_log_row(rdir: Path, ts: str, cells: str) -> None:
    """Append `| ts | <cells>` once; a retry with the same cells is a no-op."""
    lab_log = rdir / "LAB_LOG.md"
    if not lab_log.exists():
        return
    if cells in read_md(lab_log):
        return
    with lab_log.open("a", encoding="utf-8") as f:
        f.write(f"| `{ts}` {cells}\n")


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
        if not unseen_target_met(state, active_hyp):
            comp, sr = metric_rule(state, active_hyp)
            print(
                f"[RA GATE] BLOCKED: Cannot mark `{active_hyp}` PROVEN: stop rule `{comp}` sets target "
                f"{fmt_score(sr.get('target'))} on `{sr.get('metric')}`, and no `--unseen` round has met it.\n"
                "          Run the winning approach on held-out data: `ra_log_engine.py run --approach <family> --unseen ...`.",
                file=sys.stderr,
            )
            print_scoreboard(workspace, state, active_hyp, sys.stderr)
            sys.exit(1)
        block_on_integrity(workspace, state, "conclude PROVEN")
    else:
        for v in verify_integrity(workspace, state):
            print(f"[RA GATE] WARNING (still archiving the sandbox): {v}", file=sys.stderr)

    agent_id = args.agent or "PRIMARY_AGENT"
    ts = now_iso()
    hyp_dir = safe_research_path(rdir, "hypotheses", active_hyp)
    sandbox_dir = safe_research_path(rdir, "sandbox", active_hyp)
    report_path = hyp_dir / "REPORT.md"

    # Files first, logs and state last: a crash part-way can simply be re-run.
    if report_path.exists():
        txt = read_md(report_path)
        txt = txt.replace("**Current Verdict**: `PENDING`", f"**Current Verdict**: `{verdict}`")
        txt = txt.replace("**Final Verdict**: `<PROVEN | FALSIFIED>`", f"**Final Verdict**: `{verdict}`")
        report_path.write_text(txt, encoding="utf-8")

    grave_rel = ""
    if verdict == "FALSIFIED":
        (rdir / "graveyard").mkdir(parents=True, exist_ok=True)
        grave_dir = safe_research_path(rdir, "graveyard", active_hyp)
        if sandbox_dir.exists():
            suffix = 2
            while grave_dir.exists():  # an older hypothesis with the same id is already buried here
                grave_dir = safe_research_path(rdir, "graveyard", f"{active_hyp}__{suffix}")
                suffix += 1
            shutil.move(str(sandbox_dir), str(grave_dir))
        else:
            grave_dir.mkdir(parents=True, exist_ok=True)
        if report_path.exists():
            shutil.copy2(report_path, grave_dir / "REPORT.md")
        grave_rel = workspace_rel(workspace, grave_dir) or str(grave_dir)
        # Seals inside the archived sandbox follow it instead of reading as "deleted" forever.
        old_prefix = f"research/sandbox/{active_hyp}/"
        sealed = state.get("sealed_axioms", {})
        for rel in [r for r in sealed if r.startswith(old_prefix)]:
            sealed[f"{grave_rel}/{rel[len(old_prefix):]}"] = sealed.pop(rel)

    append_self_learning(rdir, active_hyp, agent_id, args.issue, args.workflow, args.found)
    append_lab_log_row(
        rdir,
        ts,
        f"| `{active_hyp}` | `-` | `{agent_id}` | `{verdict}` | {_table_cell(args.found)} "
        f"| `hypotheses/{active_hyp}/REPORT.md` |",
    )

    if verdict == "FALSIFIED":
        state["consecutive_falsifications"] = state.get("consecutive_falsifications", 0) + 1
        state["current_stage"] = "STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING"
        state["active_hypothesis"] = None
        state["cheese_audit_passed"] = False
        state["visual_audit_passed"] = False
        state["log_audit_passed"] = False
        save_state(workspace, state)
        print(
            f"[RA GATE] Hypothesis `{active_hyp}` marked FALSIFIED. "
            f"Sandbox quarantined & moved to `{grave_rel}/`. Main codebase remains clean.\n"
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

    approval = (args.user_approved or "").strip()
    problem = reason_problem(approval, "--user-approved", min_len=10)
    if problem:
        gate_error(
            "[RA GATE] BLOCKED: Graduation needs the user's sign-off on the Lab Report, quoted verbatim:\n"
            "          `ra_gate.py graduate --user-approved \"<the user's exact words>\"`\n"
            f"          ({problem})",
            1,
        )
    block_on_integrity(workspace, state, "graduate")
    stale = [tool for flag, tool in PASS_FLAGS.items() if not state.get(flag)]
    if stale:
        gate_error(
            "[RA GATE] BLOCKED: The code changed since the audits passed. Re-run before graduating: "
            + ", ".join(f"`{t}`" for t in stale),
            1,
        )

    agent_id = args.agent or "PRIMARY_AGENT"
    ts = now_iso()
    lib_note = safe_research_path(rdir, "library", f"GRADUATED_{active_hyp}.md")
    report_path = safe_research_path(rdir, "hypotheses", active_hyp) / "REPORT.md"
    report_body = read_md(report_path) if report_path.exists() else ""
    lib_note.parent.mkdir(parents=True, exist_ok=True)
    lib_note.write_text(
        f"# [GRADUATED_LAB_TRUTH] {active_hyp}\n\n"
        f"- **Graduated Timestamp**: `{ts}`\n"
        f"- **User Sign-Off (verbatim)**: \"{_table_cell(approval)}\"\n"
        f"- **Provenance**: Survived Stage 1 Workflow Mapping, Stage 4 Adversarial Break-Test, Stage 5 Anti-Cheese Audit, and Stage 7 User Sign-Off.\n\n"
        f"---\n\n{report_body}",
        encoding="utf-8",
    )
    append_lab_log_row(
        rdir,
        ts,
        f"| `{active_hyp}` | `-` | `{agent_id}` | `GRADUATED` | User: \"{_table_cell(approval)}\" "
        f"| `library/GRADUATED_{active_hyp}.md` |",
    )

    state.setdefault("graduations", []).append(
        {"hypothesis": active_hyp, "timestamp": ts, "agent": agent_id, "user_approved": approval}
    )
    state["current_stage"] = "STAGE_0_INTAKE_AND_SYNC"
    state["active_hypothesis"] = None
    state["cheese_audit_passed"] = False
    state["visual_audit_passed"] = False
    state["log_audit_passed"] = False
    save_state(workspace, state)
    print(f"[RA GATE] Graduated `{active_hyp}` into `research/library/GRADUATED_{active_hyp}.md`!")
    print_context_refresh(workspace, state)


# Sandboxes move to the graveyard on FALSIFIED, so a seal there would dangle.
UNSEALABLE_PREFIXES = ("research/sandbox/", "research/graveyard/")


def cmd_seal_axioms(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace, auto_init=True)
    fpath = (workspace / args.file).resolve()
    rel = workspace_rel(workspace, fpath)
    if rel is None:
        gate_error(f"[RA GATE] ERROR: `{args.file}` is outside the workspace ({fpath}). Seal files inside it.", 1)
    if not fpath.is_file():
        gate_error(f"[RA GATE] ERROR: Axiom file not found: {fpath}", 1)
    if rel.startswith(UNSEALABLE_PREFIXES):
        gate_error(
            f"[RA GATE] REFUSED: `{rel}` is inside a sandbox/graveyard, which moves when a hypothesis is FALSIFIED.\n"
            "          Put shared axioms in a stable location (e.g. `research/axioms/` or the project tree) and seal that."
        )
    sealed = state.setdefault("sealed_axioms", {})
    if rel in sealed:
        status, _ = verify_seal(fpath, sealed[rel])
        if status == "TAMPERED":
            gate_error(
                f"[RA GATE] REFUSED: `{rel}` is already sealed and was modified since. Re-sealing would launder the edit.\n"
                f"          Revert it, or `ra_gate.py unseal --file {rel} --reason \"...\"` first."
            )

    digest = hash_file(fpath)
    text = read_text_normalised(fpath)
    lines = len(text.splitlines()) if text is not None else 0
    sealed[rel] = {
        "sha256": digest,
        "algo": HASH_ALGO,
        "lines": lines,
        "sealed_at": now_iso(),
    }
    save_state(workspace, state)
    print(f"[RA GATE] Sealed AXIOMATIC_PRIMITIVES file `{rel}` (SHA-256: {digest[:16]}..., {lines} lines).")


def cmd_unseal(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)
    sealed: Dict[str, Any] = state.setdefault("sealed_axioms", {})
    rel = workspace_rel(workspace, workspace / args.file)
    key = next((k for k in (rel, args.file.strip().replace("\\", "/")) if k in sealed), None)
    if key is None:
        gate_error(f"[RA GATE] ERROR: `{args.file}` is not sealed. Sealed files: {sorted(sealed) or 'none'}.", 1)
    problem = reason_problem(args.reason, "--reason")
    if problem:
        gate_error(f"[RA GATE] BLOCKED: unseal needs a real justification. {problem}")

    agent_id = args.agent or "PRIMARY_AGENT"
    reason = args.reason.strip()
    meta = sealed.pop(key)
    state.setdefault("unsealed_history", []).append(
        {"file": key, "sha256": meta.get("sha256"), "unsealed_at": now_iso(), "agent": agent_id, "reason": reason}
    )
    append_self_learning(
        rdir,
        state.get("active_hypothesis") or "AXIOM_UNSEAL",
        agent_id,
        f"Unsealed AXIOMATIC_PRIMITIVES file `{key}`.",
        "A sealed axiom file had to change or move; the seal was lifted explicitly instead of being bypassed.",
        f"Reason: {reason}",
    )
    save_state(workspace, state)
    print(f"[RA GATE] Unsealed `{key}` (reason logged to SELF_LEARNING.md). Re-seal it with `seal-axioms` once it is final.")


def cmd_learn(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    load_state(workspace, auto_init=True)
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


def cmd_stop_rule(args: argparse.Namespace) -> None:
    """
    Register or enforce a hard Stop Rule, Success Criteria, and 'If It Never Works' Pivot Plan
    for a component/mechanism so the AI never enters an open-ended `fail -> fix -> retest` loop.
    """
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace, auto_init=True)
    rdir = get_research_dir(workspace)
    stop_rules: Dict[str, Any] = state.setdefault("stop_rules", {})
    comp = args.component.strip()

    if args.record_failure:
        if comp not in stop_rules:
            print(
                f"[RA GATE BLOCKED] No Stop Rule registered for `{comp}`! "
                f"Register `--purpose`, `--success-criteria`, `--max-rounds`, and `--if-never-works` BEFORE testing/looping.",
                file=sys.stderr,
            )
            sys.exit(2)
        sr = stop_rules[comp]
        sr["failed_rounds"] = sr.get("failed_rounds", 0) + 1
        sr["last_failed_at"] = now_iso()
        # The `re-evaluate` that follows this same failure must not count it again.
        sr["failure_pending_re_evaluate"] = True
        f_rounds = sr["failed_rounds"]
        m_rounds = sr.get("max_rounds", 2)
        if f_rounds >= m_rounds:
            sr["status"] = "PIVOT_TRIGGERED"
            save_state(workspace, state)
            append_self_learning(
                rdir,
                state.get("active_hypothesis") or comp,
                args.agent or "PRIMARY_AGENT",
                f"Component `{comp}` reached hard Stop Rule ({f_rounds}/{m_rounds} failed unseen rounds).",
                "Avoided infinite `fail -> fix -> retest` rabbit hole on a brittle heuristic.",
                f"Triggered `If It Never Works` Pivot Plan for `{comp}`: {sr.get('if_never_works')}",
            )
            print("=" * 78)
            print(f"  [!!!] RA STOP RULE TRIGGERED FOR `{comp}` ({f_rounds}/{m_rounds} FAILED ROUNDS)")
            print("=" * 78)
            print(f"  STOP tweaking `{comp}`! Do NOT run another `fail -> fix -> retest` round.")
            print(f"  Conclude FALSIFIED (PLATEAUED); race the next Option Sweep family, or run the pivot:")
            print(f"    -> {sr.get('if_never_works')}")
            print("=" * 78)
            return
        save_state(workspace, state)
        print(
            f"[RA GATE] Recorded failed round {f_rounds}/{m_rounds} for `{comp}` "
            f"({m_rounds - f_rounds} round(s) remaining before Stop Rule triggers)."
        )
        return

    old = stop_rules.get(comp)
    if args.reset:
        if old is None:
            gate_error(f"[RA GATE BLOCKED] `--reset`: no Stop Rule registered for `{comp}`.")
        problem = reason_problem(args.reason, "--reason")
        if problem:
            gate_error(f"[RA GATE BLOCKED] Resetting `{comp}`'s failed rounds needs `--reason` (why a fresh budget is legitimate). {problem}")
    elif args.reason:
        gate_error("[RA GATE] ERROR: `--reason` only applies together with `--reset`.")

    purpose = (args.purpose or (old or {}).get("purpose", "")).strip()
    success = (args.success_criteria or (old or {}).get("success_criteria", "")).strip()
    never = (args.if_never_works or (old or {}).get("if_never_works", "")).strip()
    if not purpose or not success or not never:
        print(
            "[RA GATE BLOCKED] Registering a Stop Rule requires all three:\n"
            "  1. `--purpose` (what the score/mechanism is for + what is ALREADY reliable vs. weak)\n"
            "  2. `--success-criteria` (accuracy on full/crowded load, false-positive vs. false-negative cost, speed)\n"
            "  3. `--if-never-works` (ground-truth pivot plan so the main project never waits on a brittle heuristic)",
            file=sys.stderr,
        )
        sys.exit(2)

    max_rounds = max(1, int(args.max_rounds)) if args.max_rounds is not None else 2
    keep = old is not None and not args.reset
    if keep:
        # Re-registering never buys more rounds; only `--reset --reason` does.
        if args.max_rounds is None or max_rounds > old.get("max_rounds", 2):
            max_rounds = old.get("max_rounds", 2)

    prev = old or {}
    metric = (args.metric or "").strip() or None
    if args.min_gain is not None and not args.min_gain > 0:
        gate_error("[RA GATE BLOCKED] `--min-gain` must be > 0 (the smallest improvement per round that counts as progress).")
    if args.max_rounds_per_approach is not None and args.max_rounds_per_approach < 1:
        gate_error("[RA GATE BLOCKED] `--max-rounds-per-approach` must be >= 1.")
    given = {"metric": metric, "target": args.target, "min_gain": args.min_gain, "lower_is_better": args.lower_is_better}
    if keep and rule_has_numbers(prev):
        # Moving the goalposts mid-race would dodge the plateau lock.
        moved = [
            k for k, v in given.items()
            if v is not None and v != (bool(prev.get(k)) if k == "lower_is_better" else prev.get(k))
        ]
        if moved:
            gate_error(
                f"[RA GATE BLOCKED] `{comp}` already has its number ({numbers_line(prev)}). Changing "
                + ", ".join(f"`{k}`" for k in moved)
                + " needs `--reset --reason \"...\"` (logged to SELF_LEARNING.md)."
            )
    numbers = {k: (v if v is not None else prev.get(k)) for k, v in given.items()}
    numbers["lower_is_better"] = bool(numbers["lower_is_better"])
    cap = args.max_rounds_per_approach
    old_cap = prev.get("max_rounds_per_approach")
    if keep and old_cap is not None and (cap is None or cap > old_cap):
        cap = old_cap
    numbers["max_rounds_per_approach"] = cap if cap is not None else (old_cap or DEFAULT_MAX_ROUNDS_PER_APPROACH)

    stop_rules[comp] = {
        "component": comp,
        "purpose": purpose,
        "success_criteria": success,
        "max_rounds": max_rounds,
        "failed_rounds": old.get("failed_rounds", 0) if keep else 0,
        "if_never_works": never,
        "status": old.get("status", "ACTIVE") if keep else "ACTIVE",
        "registered_at": old.get("registered_at", now_iso()) if keep else now_iso(),
        "hypothesis": state.get("active_hypothesis"),
        **numbers,
    }
    if keep and old.get("failure_pending_re_evaluate"):
        stop_rules[comp]["failure_pending_re_evaluate"] = True
    if args.reset:
        reason = args.reason.strip()
        state.setdefault("stop_rule_resets", []).append(
            {"component": comp, "at": now_iso(), "reason": reason, "previous": old}
        )
        append_self_learning(
            rdir,
            state.get("active_hypothesis") or comp,
            args.agent or "PRIMARY_AGENT",
            f"Stop Rule for `{comp}` reset at {old.get('failed_rounds', 0)}/{old.get('max_rounds', 2)} failed rounds "
            f"(status {old.get('status', 'ACTIVE')}).",
            "The failure budget was restarted explicitly instead of by silent re-registration.",
            f"Reason: {reason}",
        )
    save_state(workspace, state)
    sr = stop_rules[comp]
    print("=" * 78)
    print(f"  RA STOP RULE & PIVOT CONTRACT LOCKED FOR `{comp}`")
    print("=" * 78)
    print(f"  Purpose & Reliable Split : {purpose}")
    print(f"  Success Criteria         : {success}")
    print(f"  Max Unseen Rounds        : {sr['max_rounds']} round(s) before kill-switch")
    print(f"  If It Never Works Pivot  : {never}")
    if rule_has_numbers(sr):
        print(f"  Number                   : {numbers_line(sr)}")
    else:
        print("  Number                   : MISSING - add --metric/--target/--min-gain (Stage 2 -> 3 requires them)")
    if keep:
        print(
            f"  Kept from the existing rule: {sr['failed_rounds']}/{sr['max_rounds']} failed rounds, status {sr['status']}.\n"
            f"  Starting over needs `--reset --reason \"...\"`."
        )
    print("=" * 78)


LAZY_RETRY_EXCUSE_RE = re.compile(
    r"\b(let'?s\s+(?:just\s+)?(?:retry|re-?run|try)|let\s+us\s+(?:just\s+)?(?:retry|re-?run|try)|"
    r"(?:retry|re-?run|try)(?:\s+it)?\s+(?:again|once\s+more)|just\s+(?:retry|re-?run)|re-?run\s+and\s+see|"
    r"(?:tweak|nudge|adjust|bump|raise|lower|increase|decrease|loosen|relax)\s+(?:up\s+|down\s+)?"
    r"(?:the\s+|a\s+|our\s+|that\s+|this\s+)?(?:threshold|timeout|tolerance|epsilon|margin)s?|"
    r"(?:maybe|probably|likely|just|seems)\s+(?:a\s+)?(?:flak(?:y|ey|iness)|fluke|glitch)|flakey|"
    r"random\s+(?:glitch|fluke|failure))\b",
    re.IGNORECASE,
)


def cmd_re_evaluate(args: argparse.Namespace) -> None:
    """
    Mandatory First-Principles Re-Evaluation Gate to unlock execution after a failed run.
    Blocks lazy 'let's retry' or threshold-tweaking loops and enforces the hard Stop Rule.
    """
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace, auto_init=True)
    rdir = get_research_dir(workspace)

    comp = args.component.strip()
    why_failed = args.why_failed.strip()
    new_calc = args.new_calculation.strip()
    why_diff = args.why_different.strip()

    for field_name, val in (
        ("--why-failed", why_failed),
        ("--new-calculation", new_calc),
        ("--why-different", why_diff),
    ):
        if len(val) < 20:
            print(
                f"[RA GATE BLOCKED — LAZY REASONING REJECTED]\n"
                f"  `{field_name}` is too brief (`{val}`). You must write a real first-principles mathematical\n"
                f"  or structural analysis (>= 20 chars), not a one-word excuse!",
                file=sys.stderr,
            )
            sys.exit(2)
        m_lazy = LAZY_RETRY_EXCUSE_RE.search(val)
        if m_lazy:
            print(
                f"[RA GATE BLOCKED — LAZY RETRY EXCUSE DETECTED IN `{field_name}`]\n"
                f"  Matched forbidden trial-and-error phrase: `{m_lazy.group(0)}`.\n"
                f"  Do NOT spam 'let's retry' or nudge thresholds! If this approach has PLATEAUED, switch to the\n"
                f"  next approach FAMILY in your Option Sweep (REPORT.md Section 3) or run the `If It Never Works` plan.",
                file=sys.stderr,
            )
            sys.exit(2)

    stop_rules: Dict[str, Any] = state.setdefault("stop_rules", {})
    re_eval_counts: Dict[str, int] = state.setdefault("re_evaluation_counts", {})
    re_eval_counts[comp] = re_eval_counts.get(comp, 0) + 1

    if comp in stop_rules:
        sr = stop_rules[comp]
        # One failed round = one count, whether the agent ran record-failure, re-evaluate, or both.
        pending = sr.pop("failure_pending_re_evaluate", False)
        if not pending and sr.get("status") != "PIVOT_TRIGGERED":
            sr["failed_rounds"] = sr.get("failed_rounds", 0) + 1
        f_rounds = sr["failed_rounds"]
        m_rounds = sr.get("max_rounds", 2)
        if f_rounds >= m_rounds or sr.get("status") == "PIVOT_TRIGGERED":
            sr["status"] = "PIVOT_TRIGGERED"
            save_state(workspace, state)
            print("=" * 78, file=sys.stderr)
            print(
                f"  [!!!] RA HARD STOP RULE REACHED FOR `{comp}` ({f_rounds}/{m_rounds} FAILED ROUNDS)",
                file=sys.stderr,
            )
            print("=" * 78, file=sys.stderr)
            print(
                f"  Execution remains LOCKED for `{comp}`! Stop trying to fix this approach.\n"
                f"  Conclude FALSIFIED (PLATEAUED) and race the next family from the Option Sweep, or run the pivot:\n"
                f"    -> {sr.get('if_never_works')}",
                file=sys.stderr,
            )
            print("=" * 78, file=sys.stderr)
            sys.exit(2)
    elif re_eval_counts[comp] >= 2:
        save_state(workspace, state)
        print(
            f"[RA GATE BLOCKED — UNBOUNDED RE-EVALUATION LOOP ON `{comp}`!]\n"
            f"  You have failed `{comp}` {re_eval_counts[comp]} times without registering a Stop Rule!\n"
            f"  Run `ra_gate.py stop-rule --component {comp} --purpose \"...\" --success-criteria \"...\" "
            f"--max-rounds 2 --if-never-works \"...\"` first.",
            file=sys.stderr,
        )
        sys.exit(2)

    retry_lock: Dict[str, Any] = state.setdefault("retry_lock", {})
    retry_lock["re_evaluated"] = True
    retry_lock["last_re_evaluated_at"] = now_iso()
    retry_lock["component"] = comp
    retry_lock["new_calculation"] = new_calc
    save_state(workspace, state)

    append_self_learning(
        rdir,
        state.get("active_hypothesis") or comp,
        args.agent or "PRIMARY_AGENT",
        f"Previous calculation on `{comp}` failed: {why_failed}",
        f"Replaced trial-and-error retry with new calculation: {new_calc}",
        f"Deterministic separation proof: {why_diff}",
    )

    print("=" * 78)
    print(f"  RA FIRST-PRINCIPLES RE-EVALUATION ACCEPTED FOR `{comp}`")
    print("=" * 78)
    print(f"  Why Old Failed   : {why_failed}")
    print(f"  New Calculation  : {new_calc}")
    print(f"  Why Deterministic: {why_diff}")
    print("  Next Step        : Implement it (changing the code SHA-256) before running `ra_log_engine.py run`.")
    print("  Plateau check    : best of 3 rounds under the minimum gain = PLATEAUED. Switch family, don't tweak.")
    print("=" * 78)


COLD_REVIEW_MIN_CHARS = 400
_VERDICT_RE = re.compile(
    r"^[\s>*_#`-]*VERDICT[\s*_`]*:[\s*_`]*(CONTINUE|SWITCH|BRICK[-_ ]?FIRST)\b", re.IGNORECASE | re.MULTILINE
)


def _iso_ts(text: Optional[str]) -> float:
    try:
        return dt.datetime.fromisoformat(str(text)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def archive_family(workspace: Path, rdir: Path, hyp: str, family: str) -> str:
    """Move research/sandbox/<hyp>/<family>/ to the graveyard; returns where it went ("" if there was no folder)."""
    sandbox = safe_research_path(rdir, "sandbox", hyp)
    src = next((d for d in sandbox.iterdir() if d.is_dir() and d.name.lower() == family), None) if sandbox.is_dir() else None
    if src is None:
        return ""
    dest = safe_research_path(rdir, "graveyard", hyp, src.name)
    suffix = 2
    while dest.exists():
        dest = safe_research_path(rdir, "graveyard", hyp, f"{src.name}__{suffix}")
        suffix += 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return workspace_rel(workspace, dest) or str(dest)


def cmd_cold_review(args: argparse.Namespace) -> None:
    """Accept a fresh reviewer's verdict on a plateau lock: CONTINUE, SWITCH or BRICK-FIRST."""
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)
    hyp = state.get("active_hypothesis")
    if not hyp:
        gate_error("[RA GATE] ERROR: No active hypothesis.", 1)
    sb = sb_get(state, hyp)
    lock = sb.get("lock")
    if not lock:
        gate_error(
            f"[RA GATE] REFUSED: `{hyp}` has no plateau lock, so there is nothing to review.\n"
            "          To try another family voluntarily, just `run --approach <family>` (it must be in the Option Sweep)."
        )
    locked = lock.get("approach") or ""
    if lock.get("rule") in ("BRICK_FIRST", "RESTART"):
        said = "a cold review already said BRICK-FIRST" if lock.get("rule") == "BRICK_FIRST" else "your review decided RESTART"
        gate_error(
            f"[RA GATE] REFUSED: {said} for `{hyp}`. Do not shop for another verdict:\n"
            "          " + "\n          ".join(sb_lock_instructions(state, hyp))
        )

    fpath = Path(args.file)
    fpath = (fpath if fpath.is_absolute() else workspace / fpath).resolve()
    rel = workspace_rel(workspace, fpath) or str(fpath)
    if rdir.resolve() not in fpath.parents:
        gate_error(f"[RA GATE] REFUSED: `{args.file}` must live under `research/` (expected research/hypotheses/{hyp}/COLD_REVIEW_<n>.md).")
    if not fpath.is_file():
        gate_error(f"[RA GATE] REFUSED: cold review file not found: {rel}")
    text = read_md(fpath)
    problems: List[str] = []
    if len(text.strip()) < COLD_REVIEW_MIN_CHARS:
        problems.append(f"it is {len(text.strip())} chars; a real review is >= {COLD_REVIEW_MIN_CHARS}.")
    verdicts = _VERDICT_RE.findall(text)
    if not verdicts:
        problems.append("it has no `VERDICT: CONTINUE|SWITCH|BRICK-FIRST` line.")
    scores = sb_all_scores(state, hyp)
    locked_name = str(lock.get("approach") or "")
    lock_rule = str(lock.get("rule") or "")
    if scores:
        quoted = quoted_score(text, scores)
        if not quoted:
            problems.append(
                "it quotes none of the scoreboard's scores ("
                + ", ".join(fmt_score(s) for s in scores[-8:])
                + "). The reviewer must have read `ra_gate.py status --scoreboard`."
            )
    else:
        # A board with no numbers at all (BLIND) has nothing to quote: name what it shows instead.
        low = text.lower()
        quoted = f"{locked_name}/{lock_rule}" if locked_name.lower() in low and lock_rule.lower() in low else None
        if not quoted:
            problems.append(
                f"the scoreboard has no scores yet, so the review must name the locked approach `{locked_name}` "
                f"and the lock rule `{lock_rule}` it read on `ra_gate.py status --scoreboard`."
            )
    if fpath.stat().st_mtime + 2 < _iso_ts(lock.get("since")):
        problems.append(f"it was written before the lock ({lock.get('since')}); review the current scoreboard.")
    digest = hash_file(fpath)
    if any(c.get("sha256") == digest or c.get("file") == rel for c in sb["cold_reviews"]):
        problems.append("this review was already used; every lock needs a new review file.")
    reviewer = (args.reviewer or "").strip()
    if len(reviewer) < 2:
        problems.append("`--reviewer` must name the fresh agent that wrote it.")
    if problems:
        print(f"[RA GATE] REFUSED cold review `{rel}`:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(2)

    verdict = re.sub(r"[-_ ]", "-", verdicts[-1].upper())
    nxt = approach_key(args.next_approach or "")
    if verdict != "SWITCH" and nxt:
        gate_error(f"[RA GATE] REFUSED: `--next-approach` only applies to SWITCH; the review's last verdict is {verdict}.")
    ap = sb["approaches"].setdefault(locked, {"rounds": [], "status": "PLATEAUED"})
    agent_id = args.agent or "PRIMARY_AGENT"
    ts = now_iso()
    n = len(sb["cold_reviews"]) + 1
    moved_to = ""

    if verdict == "CONTINUE":
        mine = [c for c in sb["cold_reviews"] if c.get("approach") == locked]
        if mine and mine[-1].get("verdict") == "CONTINUE":
            gate_error(
                f"[RA GATE] REFUSED: the last cold review on `{locked}` was already CONTINUE. "
                "Two CONTINUEs on a flat approach = switch or stop.\n"
                "          Get a SWITCH (`--next-approach <family>`) or BRICK-FIRST verdict, or conclude FALSIFIED."
            )
        sb["lock"] = None
        sb["grace"][locked] = 1
        ap["status"] = "RACING"
        ap["kept_at_round"] = len(ap.get("rounds", []))
        if lock.get("rule") == "TREND" and lock.get("projected") is not None:
            ap["trend_floor"] = lock["projected"]
    elif verdict == "SWITCH":
        if not nxt:
            gate_error("[RA GATE] REFUSED: a SWITCH verdict needs `--next-approach <family>` (a family from the Option Sweep).")
        if not FAMILY_RE.match(nxt):
            gate_error(f"[RA GATE] REFUSED: `--next-approach {args.next_approach}` must be [A-Za-z0-9_-] (e.g. template-reader).")
        if nxt == locked:
            gate_error(f"[RA GATE] REFUSED: `--next-approach` must differ from the locked approach `{locked}`.")
        nxt_status = (sb["approaches"].get(nxt) or {}).get("status")
        if nxt_status in RETIRED_STATUSES:
            gate_error(f"[RA GATE] REFUSED: `{nxt}` is already {nxt_status}; pick a family that is still in the race.")
        if not family_in_report(workspace, hyp, nxt):
            gate_error(f"[RA GATE] REFUSED: add `{nxt}` to the Option Sweep in REPORT.md Section 3 first.")
        blocked = ceiling_block(state, hyp, nxt)
        if blocked:
            gate_error(f"[RA GATE] REFUSED: `{nxt}` can't be raced: {blocked}.")
        ap["status"] = "SWITCHED"
        sb["grace"].pop(locked, None)
        moved_to = archive_family(workspace, rdir, hyp, locked)
        sb["lock"] = None
        found = metric_rule(state, hyp)
        sr = found[1] if found else {}
        scored = [r["score"] for r in ap.get("rounds", []) if r.get("score") is not None]
        best = (min(scored) if sr.get("lower_is_better") else max(scored)) if scored else None
        append_self_learning(
            rdir,
            hyp,
            agent_id,
            f"Approach `{locked}` PLATEAUED after {len(ap.get('rounds', []))} round(s); best {fmt_score(best)} "
            f"on `{sr.get('metric')}` (target {fmt_score(sr.get('target'))}).",
            f"{lock.get('reason')} Cold review #{n} by `{reviewer}` ({rel}) said SWITCH.",
            f"Switched to `{nxt}`" + (f"; `{locked}` archived to `{moved_to}/`" if moved_to else "")
            + ". Do not tweak the archived family again.",
        )
    else:
        sb["lock"] = {
            "approach": locked,
            "rule": "BRICK_FIRST",
            "reason": f"BRICK_FIRST: cold review #{n} by `{reviewer}` said build the end-to-end brick first",
            "since": ts,
            "stop_rule": lock.get("stop_rule"),
        }

    sb["cold_reviews"].append(
        {
            "n": n,
            "at": ts,
            "file": rel,
            "sha256": digest,
            "reviewer": reviewer,
            "verdict": verdict,
            "approach": locked,
            "lock_reason": lock.get("reason"),
            "next_approach": nxt or None,
            "quoted_score": quoted,
            "archived_to": moved_to or None,
        }
    )
    append_lab_log_row(
        rdir,
        ts,
        f"| `{hyp}` | `-` | `{reviewer}` | `COLD_REVIEW_{verdict}` | #{n} on `{locked}`: "
        f"{_table_cell(str(lock.get('reason')))}" + (f" -> `{nxt}`" if nxt else "") + f" | `{rel}` |",
    )
    state.setdefault("history", []).append(
        {"timestamp": ts, "agent": agent_id, "event": "COLD_REVIEW", "hypothesis": hyp, "verdict": verdict, "file": rel}
    )
    save_state(workspace, state)

    print("=" * 78)
    print(f"  RA COLD REVIEW #{n} ACCEPTED - `{hyp}` - VERDICT: {verdict} (reviewer `{reviewer}`, quoted {quoted})")
    print("=" * 78)
    if verdict == "CONTINUE":
        print(f"  Lock cleared. `{locked}` gets ONE grace round: it must beat its best by min-gain or runs re-lock.")
        print("  A second CONTINUE on this approach will be refused.")
    elif verdict == "SWITCH":
        print(f"  `{locked}` is SWITCHED (any `run --approach {locked}` is refused). Lock cleared.")
        if moved_to:
            print(f"  Archived its sandbox folder to `{moved_to}/`.")
        print(f"  Next: build `research/sandbox/{hyp}/{nxt}/` and `run --approach {nxt}`.")
    else:
        print("  Runs stay LOCKED. Conclude this hypothesis FALSIFIED and open a new one whose goal is the end-to-end brick:")
        print("    ra_gate.py conclude --verdict FALSIFIED --issue \"...\" --workflow \"...\" --found \"...\"")
        print("    ra_gate.py new-hypothesis --id <next> --slug <brick-slug>")
    print_scoreboard(workspace, state, hyp)
    print("=" * 78)


def cmd_decide(args: argparse.Namespace) -> None:
    """Record a decision the agent made itself instead of asking the user."""
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace, auto_init=True)
    rdir = get_research_dir(workspace)
    what, why = (args.what or "").strip(), (args.why or "").strip()
    for flag, val in (("--what", what), ("--why", why)):
        problem = reason_problem(val, flag, min_len=15)
        if problem:
            gate_error(f"[RA GATE BLOCKED] decide: {problem}")
    alts = [a.strip() for a in (args.alternatives or "").split(";") if a.strip()]
    path = rdir / "DECISIONS.md"
    existing = read_md(path) if path.exists() else "# Decisions - made and recorded by the agent instead of asking the user\n"
    body = f"- **What**: {what}\n- **Why**: {why}\n" + (f"- **Alternatives**: {'; '.join(alts)}\n" if alts else "")
    if body in existing:
        print("[RA GATE] Decision already recorded in `research/DECISIONS.md` (no change).")
        return
    ts = now_iso()
    n = existing.count("\n## D-") + 1
    hyp = state.get("active_hypothesis") or "GENERAL"
    entry = f"\n## D-{n:03d} - {ts[:10]} ({hyp})\n- **When / Agent**: `{ts}` / `{args.agent or 'PRIMARY_AGENT'}`\n" + body
    rdir.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        if not path.exists() or path.stat().st_size == 0:
            f.write(existing)
        f.write(entry)
    print(f"[RA GATE] Recorded D-{n:03d} in `research/DECISIONS.md`: {what}")
    print("          An AI decision is a reversible suggestion, not law. If the user said it, record it with `directive`.")


def cmd_directive(args: argparse.Namespace) -> None:
    """Record (or list) the user's own words, verbatim: the only rules that are the user's."""
    workspace = Path(args.workspace).resolve()
    load_state(workspace, auto_init=True)
    path = get_research_dir(workspace) / "DIRECTIVES.md"
    if args.list:
        if args.quote or args.source:
            gate_error("[RA GATE] ERROR: `directive --list` takes no --quote / --source.")
        dirs = read_directives(workspace)
        print("=" * 78)
        print(f"  USER DIRECTIVES - {len(dirs)} verbatim quote(s) in research/DIRECTIVES.md")
        print("  Every other rule (DECISIONS.md, INVARIANTS.md, notes, docs) is an AI suggestion unless it is quoted here.")
        print("-" * 78)
        for d in dirs:
            print(f"  {d['id']}  ({d['source'] or 'no source'})")
            for ln in d["quote"].splitlines():
                print(f"      > {ln}")
        if not dirs:
            print("  (none yet: `ra_gate.py directive --quote \"<the user's exact words>\" --source \"<when/where>\"`)")
        print("=" * 78)
        return
    quote, source = (args.quote or "").strip(), (args.source or "").strip()
    if len(quote) < 3:
        gate_error("[RA GATE BLOCKED] directive: `--quote` must be the user's exact words (>= 3 chars), or use `--list`.")
    if len(source) < 3:
        gate_error("[RA GATE BLOCKED] directive: `--source` must say when/where the user said it (e.g. \"chat 2026-10-12\").")
    if any(d["quote"] == quote for d in read_directives(workspace)):
        print("[RA GATE] That directive is already recorded in `research/DIRECTIVES.md` (no change).")
        return
    existing = read_md(path) if path.exists() else ""
    n = max((int(x) for x in re.findall(r"^## U-(\d+)", existing, re.MULTILINE)), default=0) + 1
    entry = (
        f"\n## U-{n:03d}\n"
        + "".join(f"> {ln}".rstrip() + "\n" for ln in quote.splitlines())
        + f"- **Source**: {source}\n- **Recorded**: `{now_iso()}` / `{args.agent or 'PRIMARY_AGENT'}`\n"
    )
    with path.open("a", encoding="utf-8") as f:
        if not existing.strip():
            f.write(DIRECTIVES_HEADER + "\n")
        f.write(entry)
    print(f"[RA GATE] Recorded U-{n:03d} in `research/DIRECTIVES.md` (the user's words, verbatim, from {source}).")


def cmd_ceiling(args: argparse.Namespace) -> None:
    """Put an approach family's paper ceiling on the board; one that can't reach the target refuses runs."""
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)
    hyp = state.get("active_hypothesis")
    if not hyp:
        gate_error("[RA GATE] ERROR: No active hypothesis; a ceiling belongs to one of its approach families.", 1)
    raw = (args.approach or "").strip()
    if not FAMILY_RE.match(raw):
        gate_error(f"[RA GATE] REFUSED: `--approach {raw}` must be [A-Za-z0-9_-] (e.g. template-reader).")
    fam = approach_key(raw)
    found = metric_rule(state, hyp)
    if not found or found[1].get("target") is None:
        gate_error(
            f"[RA GATE] REFUSED: `{hyp}` has no numeric target to compare a ceiling with. Register it first:\n"
            "          `ra_gate.py stop-rule --component <slug> ... --metric <name> --target <x> --min-gain <g>`"
        )
    comp, sr = found
    if not family_in_report(workspace, hyp, fam):
        gate_error(f"[RA GATE] REFUSED: add `{raw}` to the Option Sweep in REPORT.md Section 3 first.")
    sb = sb_get(state, hyp)
    ap = sb["approaches"].get(fam) or {}
    if ap.get("status") in RETIRED_STATUSES:
        gate_error(f"[RA GATE] REFUSED: `{fam}` is {ap.get('status')}; it is out of the race.")
    old: Dict[str, Any] = dict(ap.get("ceiling") or {})
    if args.estimate is None and not old:
        gate_error(f"[RA GATE] REFUSED: `{fam}` has no ceiling yet: pass `--estimate <number>` and `--basis \"...\"`.")
    est = float(args.estimate) if args.estimate is not None else float(old["estimate"])
    basis = (args.basis or "").strip() or (old.get("basis", "") if args.estimate is None else "")
    problem = reason_problem(basis, "--basis", min_len=20)
    if problem:
        gate_error(f"[RA GATE BLOCKED] ceiling: {problem} Say how you got the number: math, a simulation or a small experiment.")
    stepping = (args.stepping_stone or "").strip()
    if stepping:
        problem = reason_problem(stepping, "--stepping-stone", min_len=20)
        if problem:
            gate_error(f"[RA GATE BLOCKED] ceiling: {problem} Say what racing it teaches or builds for an approach that can win.")
    elif args.estimate is None:
        stepping = old.get("stepping_stone", "")
    reaches = can_reach(est, sr)
    if old and not can_reach(old.get("estimate"), sr) and reaches and basis == old.get("basis"):
        gate_error(
            f"[RA GATE BLOCKED] Raising `{fam}`'s ceiling from {fmt_score(old.get('estimate'))} past the target needs new "
            "evidence: write the new `--basis` (what you computed or measured since)."
        )
    agent_id = args.agent or "PRIMARY_AGENT"
    ts = now_iso()
    ap = sb["approaches"].setdefault(fam, {"rounds": [], "status": "RACING"})
    if old:
        ap.setdefault("ceiling_history", []).append(old)
    ap["ceiling"] = {"estimate": est, "basis": basis, "at": ts, "agent": agent_id}
    if stepping:
        ap["ceiling"]["stepping_stone"] = stepping
    status = ap.get("status", "RACING")
    if not reaches and not stepping and status in ("RACING", "CANT_REACH"):
        ap["status"] = "CANT_REACH"
    elif status == "CANT_REACH":
        ap["status"] = "RACING"
    state.setdefault("history", []).append(
        {"timestamp": ts, "agent": agent_id, "event": "CEILING", "hypothesis": hyp, "approach": fam, "estimate": est,
         "stepping_stone": bool(stepping)}
    )
    save_state(workspace, state)
    append_lab_log_row(
        rdir,
        ts,
        f"| `{hyp}` | `-` | `{agent_id}` | `CEILING` | `{fam}` paper ceiling {fmt_score(est)} vs target "
        f"{fmt_score(sr.get('target'))}: {_table_cell(basis)}" + (f" STEPPING STONE: {_table_cell(stepping)}" if stepping else "")
        + " | `-` |",
    )
    sign = ">" if sr.get("lower_is_better") else "<"
    print(f"[RA GATE] Paper ceiling for `{fam}` on `{hyp}`: {fmt_score(est)} (target {fmt_score(sr.get('target'))}).")
    print(f"          Basis: {basis}")
    if reaches:
        print("          It can reach the target on paper. Race it and let the scoreboard confirm.")
    elif stepping:
        print(f"          {fmt_score(est)} {sign} target, raced as a STEPPING STONE: {stepping}")
    else:
        print(
            f"          CAN'T REACH: {fmt_score(est)} {sign} target {fmt_score(sr.get('target'))}. `{fam}` is CANT_REACH and\n"
            f"          `ra_log_engine.py run --approach {fam}` is refused. Change the architecture, DROP it in a review, or\n"
            f"          justify it: `ra_gate.py ceiling --approach {fam} --estimate {fmt_score(est)} --basis \"...\" "
            "--stepping-stone \"<why>\"`."
        )


_DECISION_RE = re.compile(
    r"^[\s>*_#`-]*DECISION[\s*_`]*:[\s*_`]*([A-Za-z0-9][A-Za-z0-9_-]{0,63})[\s*_`]*:[\s*_`]*"
    r"(KEEP|SWITCH|DROP|RESTART)\b(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_LESSON_RE = re.compile(r"^[\s>*_#`-]*LESSON[\s*_`]*:(.*)$", re.IGNORECASE | re.MULTILINE)
_NEXT_RE = re.compile(r"^[\s>*_#`-]*NEXT[\s*_`]*:(.*)$", re.IGNORECASE | re.MULTILINE)


def _line_text(m: "re.Match[str]") -> str:
    return m.group(1).strip().strip("*_`").strip()


def _names_family(text: str, fam: str, decided: set) -> bool:
    if fam in decided or re.search(rf"`{re.escape(fam)}`", text, re.IGNORECASE):
        return True
    # A 1-2 letter family ("a") hides inside ordinary prose, so it must be on a DECISION line or in backticks.
    return len(fam) >= 3 and bool(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(fam)}(?![A-Za-z0-9_-])", text, re.IGNORECASE))


def cmd_review(args: argparse.Namespace) -> None:
    """The manager's review meeting on finished worker reports: decide per approach, record lessons, name the next step."""
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)
    hyp = state.get("active_hypothesis")
    fpath = Path(args.file)
    fpath = (fpath if fpath.is_absolute() else workspace / fpath).resolve()
    rel = workspace_rel(workspace, fpath) or str(fpath)
    if rdir.resolve() not in fpath.parents:
        gate_error(f"[RA GATE] REFUSED: `{args.file}` must live under `research/` (e.g. research/reviews/REVIEW_<n>.md).")
    if not fpath.is_file():
        gate_error(f"[RA GATE] REFUSED: review file not found: {rel}")
    text = read_md(fpath)
    reviews = lab_reviews(workspace)
    pending = pending_reviews_detail(workspace)
    workers = [w for w, _ in pending]
    scores = sb_all_scores(state, hyp) if hyp else []
    if not pending and not scores:
        gate_error("[RA GATE] REFUSED: nothing to review - no worker report is waiting and the board has no scores yet.")

    problems: List[str] = []
    digest = hash_file(fpath)
    if any(r.get("sha256") == digest or r.get("file") == rel for r in reviews):
        problems.append("this review file was already used; every meeting writes a new one.")
    if pending:
        oldest = min(_iso_ts(e.get("since")) for _, e in pending)
        if fpath.stat().st_mtime + 2 < oldest:
            problems.append(
                f"it was written before worker `{workers[0]}`'s report came back ({pending[0][1].get('since')}); "
                "review the report you actually got."
            )
    approaches: Dict[str, Any] = sb_get(state, hyp, create=False)["approaches"] if hyp else {}
    live = [f for f, ap in approaches.items() if (ap or {}).get("status") not in RETIRED_STATUSES]
    decisions = [(approach_key(m.group(1)), m.group(2).upper(), m.group(3).strip(" *_`-:")) for m in _DECISION_RE.finditer(text)]
    decided = {f for f, _, _ in decisions}
    missing = [f for f in live if not _names_family(text, f, decided)]
    if missing:
        problems.append(
            "it does not name every approach still in the race: missing "
            + ", ".join(f"`{f}`" for f in missing)
            + " (a name under 3 characters must be in backticks or on a DECISION line)."
        )
    quoted: Optional[str]
    if scores:
        quoted = quoted_score(text, scores)
        if not quoted:
            problems.append(
                "it quotes none of the scoreboard's numbers (" + ", ".join(fmt_score(s) for s in scores[-8:])
                + "). Judge with the numbers on `ra_gate.py board`."
            )
    else:
        quoted = next((w for w in workers if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", text, re.IGNORECASE)), None)
        if not quoted:
            problems.append(f"the board has no scores yet, so the review must name the worker it reviews ({', '.join(workers)}).")
    if not decisions:
        problems.append("it has no `DECISION: <family>: KEEP|SWITCH|DROP|RESTART` line.")
    by_fam: Dict[str, set] = {}
    for f, verb, _ in decisions:
        by_fam.setdefault(f, set()).add(verb)
    for f, verbs in by_fam.items():
        if len(verbs) > 1:
            problems.append(f"conflicting decisions for `{f}`: {', '.join(sorted(verbs))}.")
        elif not hyp and verbs - {"KEEP"}:
            problems.append(f"there is no active hypothesis, so `DECISION: {f}: {next(iter(verbs))}` has nothing to act on.")
        elif hyp and f not in approaches and not family_in_report(workspace, hyp, f):
            problems.append(f"`DECISION: {f}` names no approach on the board or in REPORT.md's Option Sweep.")
        elif hyp and "KEEP" in verbs and (approaches.get(f) or {}).get("status") in RETIRED_STATUSES:
            problems.append(f"`{f}` is already {approaches[f].get('status')}; it can't be kept.")
    lessons = [_line_text(m) for m in _LESSON_RE.finditer(text)]
    if not lessons:
        problems.append("it has no `LESSON: <what we learned>` line (>= 20 chars).")
    for ls in lessons:
        bad = reason_problem(ls, "LESSON", min_len=20)
        if bad:
            problems.append(bad)
    nexts = [_line_text(m) for m in _NEXT_RE.finditer(text) if len(_line_text(m)) >= 5]
    if not nexts:
        problems.append("it has no `NEXT: <the next step>` line.")
    if problems:
        print(f"[RA GATE] REFUSED review `{rel}`:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(2)

    n = len(reviews) + 1
    ts = now_iso()
    agent_id = args.agent or "PRIMARY_AGENT"
    nxt = nexts[-1]
    notes: List[str] = []
    restart = ""
    if hyp:
        sb = sb_get(state, hyp)
        for f, verb, _ in decisions:
            lock = sb.get("lock") or {}
            lock_here = lock.get("approach") == f and lock.get("rule") not in ("BRICK_FIRST", "RESTART")
            if verb == "KEEP":
                ap = sb["approaches"].get(f)
                if ap is not None:
                    ap["kept_at_round"] = len(ap.get("rounds", []))
                notes.append(f"`{f}` KEEP" + (f" (its {lock.get('rule')} lock still needs a cold review)" if lock_here else ""))
            elif verb in ("DROP", "SWITCH"):
                ap = sb["approaches"].setdefault(f, {"rounds": [], "status": "RACING"})
                if ap.get("status") in RETIRED_STATUSES:
                    notes.append(f"`{f}` was already {ap.get('status')}")
                    continue
                ap["status"] = "DROPPED" if verb == "DROP" else "SWITCHED"
                sb["grace"].pop(f, None)
                moved = archive_family(workspace, rdir, hyp, f)
                note = f"`{f}` {ap['status']} (runs refused" + (f", sandbox -> `{moved}/`" if moved else "") + ")"
                if lock_here:
                    sb["lock"] = None
                    note += f"; its {lock.get('rule')} lock is cleared"
                notes.append(note)
            else:
                restart = f
        if restart:
            found = metric_rule(state, hyp)
            sb["lock"] = {
                "approach": restart,
                "rule": "RESTART",
                "reason": f"RESTART: review #{n} ({rel}) decided to restart `{hyp}`",
                "since": ts,
                "stop_rule": found[0] if found else None,
            }
            notes.append(f"RESTART: runs of `{hyp}` are LOCKED")
    else:
        notes.extend(f"`{f}` {verb}" for f, verb, _ in decisions)
    summary = "; ".join(f"{f}: {verb}" for f, verb, _ in decisions)
    state.setdefault("history", []).append(
        {"timestamp": ts, "agent": agent_id, "event": "REVIEW", "hypothesis": hyp, "n": n, "file": rel, "decisions": summary}
    )
    save_state(workspace, state)
    for ls in lessons:
        append_self_learning(
            rdir,
            hyp or "LAB_REVIEW",
            agent_id,
            f"Review #{n} (`{rel}`) of {', '.join(workers) or 'the scoreboard'}.",
            f"Manager review meeting - {summary}. NEXT: {nxt}",
            ls,
        )
    append_lab_log_row(
        rdir, ts, f"| `{hyp or '-'}` | `-` | `{agent_id}` | `REVIEW_{n}` | {_table_cell(summary + '. NEXT: ' + nxt)} | `{rel}` |"
    )
    clear_reviews(workspace, workers)
    record_review(
        workspace,
        {"n": n, "at": ts, "file": rel, "sha256": digest, "workers": workers, "hypothesis": hyp,
         "decisions": [{"approach": f, "decision": v, "why": w} for f, v, w in decisions],
         "lessons": lessons, "next": nxt, "quoted": quoted},
    )
    print("=" * 78)
    print(f"  RA REVIEW #{n} ACCEPTED - `{hyp or 'no hypothesis'}` (reviewed: {', '.join(workers) or 'scoreboard'}; quoted {quoted})")
    print("=" * 78)
    for note in notes:
        print(f"  DECISION : {note}")
    print(f"  LESSONS  : {len(lessons)} appended to research/SELF_LEARNING.md (they ride along in every next fork brief)")
    print(f"  NEXT     : {nxt}")
    if workers:
        print(f"  Cleared pending review(s): {', '.join(workers)}. The next fork is open.")
    if restart:
        for line in sb_lock_instructions(state, hyp):
            print(f"  {line}")
    print("=" * 78)


def _rule_docs(workspace: Path) -> List[str]:
    names = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "research/INVARIANTS.md", "research/DECISIONS.md", "research/VISION_AND_MISSION.md")
    return [n for n in names if (workspace / n).is_file()]


def _print_board(workspace: Path, mode: str) -> None:
    import ra_common  # the raising variant: a broken board must show its error here, not vanish

    if not get_state_path(workspace).is_file():
        gate_error("[RA GATE] No `research/.ra_state.json` here - run `ra_gate.py init --workspace .` first.", 1)
    print(ra_common._board(workspace, mode))


def cmd_board(args: argparse.Namespace) -> None:
    _print_board(Path(args.workspace).resolve(), "summary" if args.summary else "full")


def cmd_resume(args: argparse.Namespace) -> None:
    """Pick a run back up as the lab manager: the board, then the resume protocol."""
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    _print_board(workspace, "full")
    hyp = state.get("active_hypothesis")
    print("RESUME PROTOCOL - you are the lab manager picking this run back up:")
    print("  1. Reconcile rules. Rules found in project docs are AI suggestions unless research/DIRECTIVES.md quotes the")
    print("     user saying them. Check each one; record the real ones verbatim:")
    print("       ra_gate.py directive --quote \"<the user's exact words>\" --source \"<when/where>\"")
    docs = _rule_docs(workspace)
    print(f"     Docs here with rules in them: {', '.join(docs) if docs else 'none found'}")
    print("  2. Pull the in-flight hypothesis through today's gates: Option Sweep (>= 3 families, REPORT.md Section 3),")
    print("     a numeric stop rule (`stop-rule ... --metric --target --min-gain`), a paper ceiling per family (`ceiling`).")
    if hyp:
        found = metric_rule(state, hyp)
        gaps: List[str] = []
        if not found or not rule_has_numbers(found[1]):
            gaps.append("no numeric stop rule")
        no_ceiling = [
            f for f, ap in sb_get(state, hyp, create=False)["approaches"].items()
            if not (ap or {}).get("ceiling") and (ap or {}).get("status") not in RETIRED_STATUSES
        ]
        if no_ceiling:
            gaps.append("no paper ceiling for " + ", ".join(no_ceiling))
        print(f"     `{hyp}`: {'; '.join(gaps) if gaps else 'gates in place'}")
    else:
        print("     No hypothesis is open.")
    print("  3. Do the NEXT DECISION now and report afterwards - don't ask what to do.")


def cmd_manager_edit(args: argparse.Namespace) -> None:
    """One-time allowance for the manager to edit a file itself, on the user's own words."""
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    reason = (args.reason or "").strip()
    problem = reason_problem(reason, "--reason", min_len=10)
    if problem:
        gate_error(f"[RA GATE BLOCKED] manager-edit needs the user's exact words asking you to edit it yourself. {problem}")
    rel = workspace_rel(workspace, (workspace / args.file).resolve())
    if rel is None:
        gate_error(f"[RA GATE] REFUSED: `{args.file}` is outside the workspace.")
    agent_id = args.agent or "PRIMARY_AGENT"
    state.setdefault("history", []).append(
        {"timestamp": now_iso(), "agent": agent_id, "event": "MANAGER_EDIT_ALLOWED", "file": rel, "user_words": reason}
    )
    save_state(workspace, state)
    shown = grant_manager_edit(workspace, rel, reason, agent_id)
    if shown is None:
        gate_error("[RA GATE] ERROR: could not record the allowance (research/.ra_state.json unreadable).", 1)
    print(f"[RA GATE] One-time allowance: the manager may edit `{shown}` itself ONCE (user: \"{reason}\").")
    print("          The first direct edit uses it up; after that, delegate to a worker again.")


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
    p_status.add_argument(
        "--scoreboard",
        action="store_true",
        help="Print only the active hypothesis' scoreboard (rounds, best, last, best-unseen, status, lock)",
    )
    p_status.add_argument("--hypothesis", default=None, help="With --scoreboard: show this hypothesis instead of the active one")
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
        help="Working functions/modules verified as innocent by runtime `.log` boundaries (`file`, `file:func`, `file:Class.method`) that must NOT be modified",
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
        help="Required (>= 30 chars) runtime `.log` or real-data evidence explaining why `--revoke-protected` unlocks the node",
    )
    p_mc.set_defaults(func=cmd_map_context)

    p_nh = sub.add_parser("new-hypothesis", help="Create a new hypothesis and quarantined sandbox")
    p_nh.add_argument("--workspace", default=".", help="Workspace root directory")
    p_nh.add_argument("--id", required=True, help="Hypothesis ID (e.g., H001)")
    p_nh.add_argument("--slug", required=True, help="Short descriptive slug")
    p_nh.add_argument("--parent", default="NONE", help="Parent hypothesis ID if branching/iterating")
    p_nh.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_nh.add_argument(
        "--user-approved",
        default="",
        help="The user's exact words approving another hypothesis after 5 consecutive FALSIFIED (required then)",
    )
    p_nh.set_defaults(func=cmd_new_hypothesis)

    p_adv = sub.add_parser("advance", help="Validate current stage artifacts and advance to the next stage")
    p_adv.add_argument("--workspace", default=".", help="Workspace root directory")
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
    p_grad.add_argument("--user-approved", default="", help="The user's exact sign-off words (>= 10 chars, required)")
    p_grad.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_grad.set_defaults(func=cmd_graduate)

    p_seal = sub.add_parser("seal-axioms", help="Cryptographically seal a legitimate axioms file")
    p_seal.add_argument("--workspace", default=".", help="Workspace root directory")
    p_seal.add_argument("--file", required=True, help="Relative path to axioms file")
    p_seal.set_defaults(func=cmd_seal_axioms)

    p_unseal = sub.add_parser("unseal", help="Lift the seal on an axioms file (reason logged to SELF_LEARNING.md)")
    p_unseal.add_argument("--workspace", default=".", help="Workspace root directory")
    p_unseal.add_argument("--file", required=True, help="Sealed file path, as sealed (workspace-relative)")
    p_unseal.add_argument("--reason", required=True, help="Why the seal is lifted (>= 30 chars)")
    p_unseal.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_unseal.set_defaults(func=cmd_unseal)

    p_learn = sub.add_parser("learn", help="Append an Issue:Workflow:Found entry to SELF_LEARNING.md")
    p_learn.add_argument("--workspace", default=".", help="Workspace root directory")
    p_learn.add_argument("--hypothesis", default="GENERAL", help="Related hypothesis ID")
    p_learn.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_learn.add_argument("--issue", required=True, help="What went wrong")
    p_learn.add_argument("--workflow", required=True, help="Where the workflow/thinking failed")
    p_learn.add_argument("--found", required=True, help="Permanent rule discovered")
    p_learn.set_defaults(func=cmd_learn)

    p_sr = sub.add_parser(
        "stop-rule",
        help="Register or enforce a hard Stop Rule, Success Criteria, and 'If It Never Works' Pivot Plan",
    )
    p_sr.add_argument("--workspace", default=".", help="Workspace root directory")
    p_sr.add_argument("--component", required=True, help="Component/mechanism slug (e.g., pixel_god_tracker)")
    p_sr.add_argument("--purpose", default="", help="What the score/mechanism is for + what is already reliable vs. weak")
    p_sr.add_argument(
        "--success-criteria",
        default="",
        help="Accuracy on full/crowded load, false-positive vs. false-negative asymmetry, and speed budget",
    )
    p_sr.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="Max failed unseen test rounds before triggering pivot (default 2; re-registering cannot raise it)",
    )
    p_sr.add_argument(
        "--if-never-works",
        default="",
        help="Ground-truth fallback/pivot plan so the main project never waits on a brittle heuristic",
    )
    p_sr.add_argument(
        "--record-failure",
        action="store_true",
        help="Increment failed rounds for --component and trigger the 'If It Never Works' pivot if max-rounds reached",
    )
    p_sr.add_argument(
        "--reset",
        action="store_true",
        help="Restart an existing rule's failed rounds / PIVOT_TRIGGERED status (needs --reason)",
    )
    p_sr.add_argument("--reason", default="", help="Why --reset is legitimate (>= 30 chars, logged to SELF_LEARNING.md)")
    p_sr.add_argument("--metric", default=None, help="Name of the number every run prints as RA_SCORE (e.g. \"pass-rate\")")
    p_sr.add_argument("--target", type=float, default=None, help="Score that means WORKS, met on an --unseen run")
    p_sr.add_argument("--min-gain", type=float, default=None, help="Smallest per-round improvement that counts as progress (> 0)")
    p_sr.add_argument(
        "--lower-is-better", action="store_true", default=None, help="Smaller scores win (default: higher is better)"
    )
    p_sr.add_argument(
        "--max-rounds-per-approach",
        type=int,
        default=None,
        help=f"Rounds one approach family gets before the CAP lock (default {DEFAULT_MAX_ROUNDS_PER_APPROACH}; re-registering cannot raise it)",
    )
    p_sr.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_sr.set_defaults(func=cmd_stop_rule)

    p_cr = sub.add_parser(
        "cold-review",
        help="Accept a FRESH subagent's verdict (read from the file's last `VERDICT:` line) on a plateau lock",
    )
    p_cr.add_argument("--workspace", default=".", help="Workspace root directory")
    p_cr.add_argument("--file", required=True, help="research/hypotheses/<hyp>/COLD_REVIEW_<n>.md (>= 400 chars, quotes a score)")
    p_cr.add_argument("--reviewer", required=True, help="Agent id of the fresh reviewer that wrote the file")
    p_cr.add_argument("--next-approach", default=None, help="SWITCH only: the Option Sweep family to race next")
    p_cr.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID running the command")
    p_cr.set_defaults(func=cmd_cold_review)

    p_dec = sub.add_parser("decide", help="Record a decision in research/DECISIONS.md instead of asking the user")
    p_dec.add_argument("--workspace", default=".", help="Workspace root directory")
    p_dec.add_argument("--what", required=True, help="The decision (>= 15 chars)")
    p_dec.add_argument("--why", required=True, help="The reason (>= 15 chars)")
    p_dec.add_argument("--alternatives", default="", help="Options considered, separated by `;`")
    p_dec.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_dec.set_defaults(func=cmd_decide)

    p_re = sub.add_parser(
        "re-evaluate",
        help="Mandatory First-Principles Re-Evaluation Gate to unlock `ra_log_engine.py run` after a failed attempt (blocks lazy 'let's retry' loops)",
    )
    p_re.add_argument("--workspace", default=".", help="Workspace root directory")
    p_re.add_argument("--component", required=True, help="Component/mechanism slug being re-evaluated")
    p_re.add_argument(
        "--why-failed",
        required=True,
        help="Mathematical or structural proof of WHY the previous calculation/model failed",
    )
    p_re.add_argument(
        "--new-calculation",
        required=True,
        help="Exact new equation or structural change, OR the next approach family from the Option Sweep (NOT a threshold tweak)",
    )
    p_re.add_argument(
        "--why-different",
        required=True,
        help="Why this new calculation deterministically separates the failure case",
    )
    p_re.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_re.set_defaults(func=cmd_re_evaluate)

    p_dir = sub.add_parser("directive", help="Record the user's own words verbatim in research/DIRECTIVES.md, or --list them")
    p_dir.add_argument("--workspace", default=".", help="Workspace root directory")
    p_dir.add_argument("--quote", default=None, help="The user's exact words (verbatim, never paraphrased)")
    p_dir.add_argument("--source", default=None, help="When/where the user said it (e.g. \"chat 2026-10-12\")")
    p_dir.add_argument("--list", action="store_true", help="Print every recorded directive")
    p_dir.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_dir.set_defaults(func=cmd_directive)

    p_ceil = sub.add_parser(
        "ceiling", help="Store an approach family's paper ceiling; one that can't reach the target refuses its runs"
    )
    p_ceil.add_argument("--workspace", default=".", help="Workspace root directory")
    p_ceil.add_argument("--approach", required=True, help="Option Sweep family (REPORT.md Section 3)")
    p_ceil.add_argument("--estimate", type=float, default=None, help="Best score this family can reach, on paper")
    p_ceil.add_argument("--basis", default="", help="How you got the estimate: math / simulation / small experiment (>= 20 chars)")
    p_ceil.add_argument(
        "--stepping-stone", default="", help="Why race it anyway although the ceiling misses the target (>= 20 chars)"
    )
    p_ceil.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_ceil.set_defaults(func=cmd_ceiling)

    p_rev = sub.add_parser(
        "review", help="The manager's review meeting on finished worker reports (DECISION / LESSON / NEXT lines)"
    )
    p_rev.add_argument("--workspace", default=".", help="Workspace root directory")
    p_rev.add_argument("--file", required=True, help="research/reviews/REVIEW_<n>.md")
    p_rev.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_rev.set_defaults(func=cmd_review)

    p_board = sub.add_parser("board", help="Print the live lab board (aim, user directives, approaches, reviews, next decision)")
    p_board.add_argument("--workspace", default=".", help="Workspace root directory")
    p_board.add_argument("--summary", action="store_true", help="Two-line summary instead of the full board")
    p_board.set_defaults(func=cmd_board)

    p_res = sub.add_parser("resume", help="The full board plus the resume protocol for picking a run back up")
    p_res.add_argument("--workspace", default=".", help="Workspace root directory")
    p_res.set_defaults(func=cmd_resume)

    p_me = sub.add_parser("manager-edit", help="One-time allowance for the manager to edit a file itself (user's words)")
    p_me.add_argument("--workspace", default=".", help="Workspace root directory")
    p_me.add_argument("--file", required=True, help="File the user asked you to edit directly")
    p_me.add_argument("--reason", required=True, help="The user's exact words asking for it (>= 10 chars)")
    p_me.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
    p_me.set_defaults(func=cmd_manager_edit)

    return p


def main() -> None:
    # Stage instructions must reach the agent even on cp932/cp1252 consoles.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    if args.cmd not in ("board", "resume"):
        footer = render_board(Path(args.workspace).resolve(), "summary")
        if footer:
            print(footer)


if __name__ == "__main__":
    main()
