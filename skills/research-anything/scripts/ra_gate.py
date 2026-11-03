#!/usr/bin/env python3
"""
ra_gate.py — State-Machine Gatekeeper & Context Refresher for RA (research-anything).

Prevents LLM step-skipping, attention decay, codebase poisoning, repeat questions,
and axiom tampering by enforcing hard stage gates on disk and echoing active
invariants + current-stage instructions at every transition.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

STAGES = [
    "STAGE_0_INTAKE_AND_SYNC",
    "STAGE_1_HYPOTHESIS_FORMULATION",
    "STAGE_2_SANDBOX_PROTOTYPE",
    "STAGE_3_ADVERSARIAL_BREAK_TEST",
    "STAGE_4_ANTI_CHEESE_AUDIT",
    "STAGE_5_LAB_REPORT_AND_LEARNING",
    "STAGE_6_GRADUATION_REVIEW",
]

STAGE_INSTRUCTIONS: Dict[str, str] = {
    "STAGE_0_INTAKE_AND_SYNC": (
        "1. Run `check-question` and inspect all reference folders/images BEFORE asking the user anything.\n"
        "2. Gather user ideas 1-by-1 and synthesize into `research/VISION_AND_MISSION.md`.\n"
        "3. Lock non-negotiable rules in `research/INVARIANTS.md`.\n"
        "4. Review `research/LAB_LOG.md`, `research/SELF_LEARNING.md`, and `research/graveyard/`.\n"
        "5. When ready to test a mechanism, run: `ra_gate.py new-hypothesis --id H001 --slug <name>`."
    ),
    "STAGE_1_HYPOTHESIS_FORMULATION": (
        "1. Edit `research/hypotheses/<active_hypothesis>/REPORT.md`.\n"
        "2. Write the explicit mathematical/structural formulation, assumptions, and predicted failure bounds.\n"
        "3. Do NOT write boilerplate. Derive from first principles.\n"
        "4. Run `ra_gate.py advance` to unlock Stage 2 (Sandbox Prototype)."
    ),
    "STAGE_2_SANDBOX_PROTOTYPE": (
        "1. Build the isolated prototype ONLY inside `research/sandbox/<active_hypothesis>/`.\n"
        "2. Keep the main codebase 100% clean and unpoisoned.\n"
        "3. If you define legitimate mathematical/structural axioms (e.g., `=`, formulas), place them in an\n"
        "   `axioms` file and seal them with `ra_gate.py seal-axioms --file <path>`.\n"
        "4. NEVER hardcode lookup data, domain answers, or special-case branches.\n"
        "5. Run `ra_gate.py advance` to unlock Stage 3 (Adversarial Break-Test)."
    ),
    "STAGE_3_ADVERSARIAL_BREAK_TEST": (
        "1. Happy-path unit tests are BANNED. Create `break_test.*` inside `research/sandbox/<active_hypothesis>/`.\n"
        "2. Stress-test extreme scale, pathological inputs, OOD shifts, gradient/numerical stability, and invariants\n"
        "   until you find the failure boundary.\n"
        "3. If a flaw is found, fix the upstream equation/architecture (NO `if/else` or `try/except` band-aids!).\n"
        "4. Save raw empirical test output into `research/sandbox/<active_hypothesis>/evidence.log` or `REPORT.md`.\n"
        "5. Run `ra_gate.py advance` to unlock Stage 4 (Anti-Cheese Audit)."
    ),
    "STAGE_4_ANTI_CHEESE_AUDIT": (
        "1. Run `python ra_cheese_audit.py --workspace . --hypothesis <active_hypothesis>`.\n"
        "2. Resolve any Axiom Seal violations, hardcoded lookup tables, band-aid patches, or poison comments.\n"
        "3. If the hypothesis cannot work without hardcoded data, STOP and falsify it via `ra_gate.py conclude`.\n"
        "4. Once `ra_cheese_audit.py` passes, run `ra_gate.py advance` to unlock Stage 5."
    ),
    "STAGE_5_LAB_REPORT_AND_LEARNING": (
        "1. Complete `research/hypotheses/<active_hypothesis>/REPORT.md` with raw trusted data and root-cause proof.\n"
        "2. Run `ra_gate.py conclude --verdict <PROVEN|FALSIFIED> --issue \"...\" --workflow \"...\" --found \"...\"`.\n"
        "   - If FALSIFIED: sandbox is archived to `research/graveyard/`, main code stays clean, and you loop to the next hypothesis.\n"
        "   - If PROVEN: moves to Stage 6 (Graduation Review)."
    ),
    "STAGE_6_GRADUATION_REVIEW": (
        "1. STOP AND PRESENT TO USER: Show the Lab Report summary, empirical breaking-test bounds, and approach.\n"
        "2. Wait for explicit user approval before merging sandbox code into the main project.\n"
        "3. After user approval, run `ra_gate.py graduate --workspace .` to record the truth in `research/library/`."
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


def load_state(workspace: Path) -> Dict[str, Any]:
    sp = get_state_path(workspace)
    if not sp.exists():
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


def print_context_refresh(workspace: Path, state: Dict[str, Any]) -> None:
    stage = state.get("current_stage", "STAGE_0_INTAKE_AND_SYNC")
    active_hyp = state.get("active_hypothesis") or "NONE"
    fals_count = state.get("consecutive_falsifications", 0)
    invariants = extract_locked_invariants(workspace)
    violations = verify_sealed_axioms(workspace, state)

    print("=" * 78)
    print("  RA (RESEARCH ANYTHING) — STATE MACHINE & CONTEXT REFRESH")
    print("=" * 78)
    print(f"  Current Stage              : {stage}")
    print(f"  Active Hypothesis          : {active_hyp}")
    print(f"  Consecutive Falsifications : {fals_count} / 5 (Autonomous Loop Threshold)")
    print(f"  Sealed Axiom Files         : {len(state.get('sealed_axioms', {}))}")
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
    templates_dir = get_skill_root() / "resources" / "templates"

    for subdir in ["hypotheses", "sandbox", "graveyard", "library"]:
        (rdir / subdir).mkdir(parents=True, exist_ok=True)

    ts = now_iso()
    agent_id = args.agent or "PRIMARY_AGENT"

    template_map = {
        "VISION_AND_MISSION.md": rdir / "VISION_AND_MISSION.md",
        "INVARIANTS.md": rdir / "INVARIANTS.md",
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
            "version": "1.0.0",
            "created_at": ts,
            "updated_at": ts,
            "current_stage": "STAGE_0_INTAKE_AND_SYNC",
            "active_hypothesis": None,
            "consecutive_falsifications": 0,
            "cheese_audit_passed": False,
            "sealed_axioms": {},
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
    else:
        state = load_state(workspace)

    print(f"[RA GATE] Initialized research repository at: {rdir}")
    print_context_refresh(workspace, state)


def cmd_status(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
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
    for cdir in candidate_dirs:
        if cdir.exists() and cdir.is_dir():
            for f in sorted(cdir.rglob("*")):
                if f.is_file():
                    found_files.append(f)

    if found_files:
        print("  DISCOVERED REFERENCE / ASSET / LIBRARY FILES ON DISK:")
        for f in found_files[:60]:
            rel = f.relative_to(workspace)
            print(f"    - {rel} ({f.stat().st_size} bytes)")
        print("  [RULE] If any image (.png/.jpg/.webp) or doc above relates to your question,")
        print("         you MUST open and view it BEFORE asking the user!")
    else:
        print("  (No files found in reference/, references/, assets/, docs/, or research/library/)")

    ref_idx = rdir / "library" / "REFERENCES_INDEX.md"
    if ref_idx.exists():
        print("-" * 78)
        print("  INDEXED USER REFERENCES & PAST ANSWERS (`research/library/REFERENCES_INDEX.md`):")
        for line in ref_idx.read_text(encoding="utf-8").splitlines()[:40]:
            print(f"    {line}")

    print("=" * 78)


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

    lab_log = rdir / "LAB_LOG.md"
    if lab_log.exists():
        with lab_log.open("a", encoding="utf-8") as f:
            f.write(
                f"| `{ts}` | `{hyp_id}` | `{parent_id}` | `{agent_id}` | `STAGE_1_STARTED` "
                f"| Created hypothesis `{full_id}` | `hypotheses/{full_id}/REPORT.md` |\n"
            )

    state["current_stage"] = "STAGE_1_HYPOTHESIS_FORMULATION"
    state["active_hypothesis"] = full_id
    state["cheese_audit_passed"] = False
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
    if not active_hyp and stage != "STAGE_0_INTAKE_AND_SYNC":
        print("[RA GATE] ERROR: No active hypothesis. Run `new-hypothesis` first.", file=sys.stderr)
        sys.exit(1)

    if stage == "STAGE_0_INTAKE_AND_SYNC":
        print("[RA GATE] Use `new-hypothesis --id H001 --slug <name>` to advance from Stage 0.", file=sys.stderr)
        sys.exit(1)

    hyp_dir = rdir / "hypotheses" / active_hyp
    sandbox_dir = rdir / "sandbox" / active_hyp
    report_path = hyp_dir / "REPORT.md"

    if stage == "STAGE_1_HYPOTHESIS_FORMULATION":
        if not report_path.exists():
            print(f"[RA GATE] BLOCKED: Missing `{report_path}`.", file=sys.stderr)
            sys.exit(1)
        report_txt = report_path.read_text(encoding="utf-8")
        if "<Write the exact equations" in report_txt:
            print(
                "[RA GATE] BLOCKED: You have not filled out Section 2 (First-Principles Formulation) in REPORT.md!",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_2_SANDBOX_PROTOTYPE"

    elif stage == "STAGE_2_SANDBOX_PROTOTYPE":
        files = [f for f in sandbox_dir.rglob("*") if f.is_file()]
        if not files:
            print(
                f"[RA GATE] BLOCKED: Sandbox `research/sandbox/{active_hyp}/` has no prototype files!",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_3_ADVERSARIAL_BREAK_TEST"

    elif stage == "STAGE_3_ADVERSARIAL_BREAK_TEST":
        break_files = [
            f
            for f in sandbox_dir.rglob("*")
            if f.is_file() and ("break" in f.name.lower() or "stress" in f.name.lower() or "adversar" in f.name.lower())
        ]
        if not break_files:
            print(
                f"[RA GATE] BLOCKED: Stage 3 requires an adversarial breaking test file (e.g., `break_test.py`) "
                f"inside `research/sandbox/{active_hyp}/`!",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_4_ANTI_CHEESE_AUDIT"

    elif stage == "STAGE_4_ANTI_CHEESE_AUDIT":
        if not state.get("cheese_audit_passed", False):
            print(
                "[RA GATE] BLOCKED: You must run `ra_cheese_audit.py` and pass with zero violations before advancing!",
                file=sys.stderr,
            )
            sys.exit(1)
        state["current_stage"] = "STAGE_5_LAB_REPORT_AND_LEARNING"

    elif stage == "STAGE_5_LAB_REPORT_AND_LEARNING":
        print(
            "[RA GATE] Use `ra_gate.py conclude --verdict <PROVEN|FALSIFIED> --issue ... --workflow ... --found ...` "
            "to complete Stage 5.",
            file=sys.stderr,
        )
        sys.exit(1)

    elif stage == "STAGE_6_GRADUATION_REVIEW":
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

    if verdict == "PROVEN" and not state.get("cheese_audit_passed", False):
        print(
            "[RA GATE] BLOCKED: Cannot mark hypothesis PROVEN without passing `ra_cheese_audit.py` first!",
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
        state["current_stage"] = "STAGE_0_INTAKE_AND_SYNC"
        state["active_hypothesis"] = None
        state["cheese_audit_passed"] = False
        save_state(workspace, state)
        print(
            f"[RA GATE] Hypothesis `{active_hyp}` marked FALSIFIED. "
            f"Sandbox quarantined & moved to `research/graveyard/{active_hyp}/`. Main codebase remains clean."
        )
    else:
        state["consecutive_falsifications"] = 0
        state["current_stage"] = "STAGE_6_GRADUATION_REVIEW"
        save_state(workspace, state)
        print(
            f"[RA GATE] Hypothesis `{active_hyp}` marked PROVEN! "
            f"Entered STAGE 6 (Graduation Review). Present the Lab Report to the user before merging."
        )

    print_context_refresh(workspace, state)


def cmd_graduate(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
    rdir = get_research_dir(workspace)

    active_hyp = state.get("active_hypothesis")
    if not active_hyp or state.get("current_stage") != "STAGE_6_GRADUATION_REVIEW":
        print("[RA GATE] ERROR: Only a hypothesis in STAGE_6_GRADUATION_REVIEW can be graduated.", file=sys.stderr)
        sys.exit(1)

    ts = now_iso()
    lib_note = rdir / "library" / f"GRADUATED_{active_hyp}.md"
    report_path = rdir / "hypotheses" / active_hyp / "REPORT.md"
    report_body = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    lib_note.write_text(
        f"# [GRADUATED_LAB_TRUTH] {active_hyp}\n\n"
        f"- **Graduated Timestamp**: `{ts}`\n"
        f"- **Provenance**: Survived Stage 3 Adversarial Break-Test, Stage 4 Anti-Cheese Audit, and Stage 6 User Sign-Off.\n\n"
        f"---\n\n{report_body}",
        encoding="utf-8",
    )

    state["current_stage"] = "STAGE_0_INTAKE_AND_SYNC"
    state["active_hypothesis"] = None
    state["cheese_audit_passed"] = False
    save_state(workspace, state)
    print(f"[RA GATE] Graduated `{active_hyp}` into `research/library/GRADUATED_{active_hyp}.md`!")
    print_context_refresh(workspace, state)


def cmd_seal_axioms(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    state = load_state(workspace)
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
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="Display current stage, locked invariants, and active instructions")
    p_status.add_argument("--workspace", default=".", help="Workspace root directory")
    p_status.set_defaults(func=cmd_status)

    p_cq = sub.add_parser("check-question", help="Run mandatory pre-question search gate across reference folders")
    p_cq.add_argument("--workspace", default=".", help="Workspace root directory")
    p_cq.set_defaults(func=cmd_check_question)

    p_nh = sub.add_parser("new-hypothesis", help="Create a new hypothesis and quarantined sandbox")
    p_nh.add_argument("--workspace", default=".", help="Workspace root directory")
    p_nh.add_argument("--id", required=True, help="Hypothesis ID (e.g., H001)")
    p_nh.add_argument("--slug", required=True, help="Short descriptive slug")
    p_nh.add_argument("--parent", default="NONE", help="Parent hypothesis ID if branching/iterating")
    p_nh.add_argument("--agent", default="PRIMARY_AGENT", help="Agent or session ID")
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
