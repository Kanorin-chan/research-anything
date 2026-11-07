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
   - Compatible with Antigravity / CLI / Git hooks (`check-edit`, `check-all`)
   - Blocks edits to `PROTECTED_WORKING` files/functions, sealed axioms, and unmapped workflows
3. Multi-Platform Hook & Dedicated Review Agent Configs:
   - `.claude/settings.local.json` (Claude Code automated Pre/Post/Stop hooks)
   - `.claude/agents/ra-reviewer.md` (Claude Code adversarial Review Subagent)
   - `.agents/workflows/ra-review.md` & `research/harness/REVIEW_AGENT_PROMPT.md` (Antigravity / Multi-Agent Reviewer)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip().lower()).strip("-")
    return s or "project"


HARNESS_PY_TEMPLATE = '''#!/usr/bin/env python3
"""
project_harness.py — Auto-generated RA Multi-Agent Execution Harness & Hook Gate.

Works as:
1. Claude Code Hook (`pre-tool`, `post-tool`, `stop` reading hook payload from stdin)
2. Antigravity / CLI / Git Hook (`check-edit --file <path>`, `check-all`)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

WORKSPACE = Path(__file__).resolve().parent.parent.parent
RESEARCH_DIR = WORKSPACE / "research"
STATE_PATH = RESEARCH_DIR / ".ra_state.json"
WORKFLOW_MAP_PATH = RESEARCH_DIR / "WORKFLOW_MAP.md"

BANDAID_PATTERNS = [
    (re.compile(r"(#|//)\\s*hardcode(d)?\\b", re.IGNORECASE), "Forbidden `# hardcoded` marker"),
    (re.compile(r"(#|//)\\s*(hack|band-?aid|cheese|temporary\\s+fix)\\b", re.IGNORECASE), "Forbidden band-aid/hack comment"),
    (re.compile(r"except\\s*(Exception|BaseException)?\\s*:\\s*pass\\b"), "Silent `except: pass` error swallowing"),
]


def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_target_file_from_stdin() -> str | None:
    if sys.stdin.isatty():
        return None
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return None
        payload = json.loads(raw)
        tool_input = payload.get("tool_input") or payload.get("input") or {}
        for key in ("file_path", "path", "Path", "target_file"):
            if key in tool_input and isinstance(tool_input[key], str):
                return tool_input[key]
    except Exception:
        return None
    return None


def check_pre_edit(target_file: str | None) -> int:
    if not target_file:
        return 0
    state = load_state()
    try:
        rel = Path(target_file).resolve().relative_to(WORKSPACE).as_posix()
    except Exception:
        rel = target_file.replace("\\\\", "/")

    # 1. Block tampering with sealed axiom files
    sealed = state.get("sealed_axioms", {})
    if rel in sealed:
        print(
            f"[RA HARNESS BLOCKED] `{rel}` is a cryptographically sealed AXIOMATIC_PRIMITIVES file! "
            f"Do NOT sneak hardcoded data or heuristics into sealed axioms.",
            file=sys.stderr,
        )
        return 2

    # 2. Block modifying files explicitly locked as PROTECTED_WORKING (when file-level lock matches)
    protected_nodes: List[str] = state.get("protected_nodes", [])
    for pnode in protected_nodes:
        if pnode.strip() == rel:
            print(
                f"[RA HARNESS BLOCKED] `{rel}` is locked as `PROTECTED_WORKING` (`Symptom != Culprit`). "
                f"Do not modify innocent working files while fixing upstream culprits!",
                file=sys.stderr,
            )
            return 2
        if pnode.startswith(f"{rel}:"):
            func_name = pnode.split(":", 1)[1]
            print(
                f"[RA HARNESS NOTICE] `{rel}` contains protected working function `{func_name}` "
                f"(`Symptom != Culprit`). Ensure `{func_name}` remains 100% untouched!",
                file=sys.stderr,
            )

    return 0


def scan_file_for_bandaids(fpath: Path) -> List[str]:
    issues: List[str] = []
    if not fpath.exists() or not fpath.is_file():
        return issues
    try:
        text = fpath.read_text(encoding="utf-8")
    except Exception:
        return issues
    for idx, line in enumerate(text.splitlines(), start=1):
        for regex, reason in BANDAID_PATTERNS:
            if regex.search(line):
                issues.append(f"{fpath.name}:{idx}: {reason} -> `{line.strip()}`")
    return issues


def check_post_edit(target_file: str | None) -> int:
    if not target_file:
        return 0
    fpath = Path(target_file)
    if not fpath.is_absolute():
        fpath = (WORKSPACE / fpath).resolve()
    issues = scan_file_for_bandaids(fpath)
    if issues:
        print("[RA HARNESS POST-EDIT VIOLATION] Detected forbidden band-aid or hardcode marker:", file=sys.stderr)
        for iss in issues:
            print(f"  - {iss}", file=sys.stderr)
        return 2
    return 0


def check_all() -> int:
    state = load_state()
    errors: List[str] = []

    # 1. Verify sealed axioms
    for rel_path, meta in state.get("sealed_axioms", {}).items():
        fpath = WORKSPACE / rel_path
        if not fpath.exists():
            errors.append(f"Sealed axiom file missing: {rel_path}")
        elif sha256_file(fpath) != meta.get("sha256"):
            errors.append(f"AXIOM SEAL VIOLATION: `{rel_path}` was modified!")

    # 2. Check workflow map staleness
    cmap = state.get("context_map_snapshot", {})
    stale: List[str] = []
    for rel_path, old_hash in cmap.get("tracked_files", {}).items():
        fpath = WORKSPACE / rel_path
        if fpath.exists() and sha256_file(fpath) != old_hash:
            stale.append(rel_path)

    if errors:
        print("[RA HARNESS CHECK FAILED]:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    print("[RA HARNESS PASS] All sealed axioms intact.")
    if stale:
        print(
            f"[RA HARNESS NOTICE] {len(stale)} file(s) changed since the last `WORKFLOW_MAP.md` session snapshot "
            f"({', '.join(stale)}). Run `ra_gate.py map-context` to refresh hashes and invoke the Review Agent!"
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="RA Project Execution Harness & Hook Gate")
    parser.add_argument("mode", choices=["pre-tool", "post-tool", "stop", "check-edit", "check-all"])
    parser.add_argument("--file", default=None, help="Target file path for CLI check-edit")
    args = parser.parse_args()

    if args.mode == "check-all" or args.mode == "stop":
        sys.exit(check_all())
    elif args.mode == "check-edit":
        sys.exit(check_pre_edit(args.file))
    elif args.mode == "pre-tool":
        target = args.file or extract_target_file_from_stdin()
        sys.exit(check_pre_edit(target))
    elif args.mode == "post-tool":
        target = args.file or extract_target_file_from_stdin()
        sys.exit(check_post_edit(target))


if __name__ == "__main__":
    main()
'''


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

    return f"""---
name: {project_name}-rd
description: >-
  Project-local R&D skill and execution rules for {project_name} ({domain}).
  Enforces multi-hop workflow mapping, protected working nodes, behavioral
  contracts, anti-cheese rules, and mandatory Review Agent sign-off.
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


def build_reviewer_agent_md(project_name: str, domain: str) -> str:
    return f"""---
name: ra-reviewer
description: >-
  Adversarial R&D & Workflow Blast-Radius Review Agent for {project_name} ({domain}).
  Invoke after any prototype or code change to verify culprit proof, protected working
  nodes, N-hop blast radius, behavioral contracts, and zero-cheese compliance.
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
   - Run `python ~/.gemini/skills/research-anything/scripts/ra_log_engine.py audit --workspace . --hypothesis <active_hypothesis>` and reject if any `[STUCK]`, `[FAIL]`, or bare `"ok/pass"` AI-slop log lines exist.
5. **Automated Harness & Anti-Cheese Execution**:
   - Run `python research/harness/project_harness.py check-all` and `ra_cheese_audit.py`.
   - Reject immediately if you see `# hardcoded`, `try/except: pass`, unsealed lookup tables, or symptom clamping.
6. **User-Eyes Visual & Experiential Reality Check (`ra_visual_audit.py`)**:
   - Never trust code or DOM text alone for visual/UI/game/chart work.
   - Open every screenshot in `visual_captures/` with `Read` and verify from the **user's eyes** that there is no wrong CSS alignment, no displaced icon/data, no unloaded image/asset, and no wrong function/image state displayed.
   - Run `python ~/.gemini/skills/research-anything/scripts/ra_visual_audit.py audit --workspace . --hypothesis <active_hypothesis>`.

## Output Format
Return a structured verdict:
- **`REVIEW VERDICT`**: `APPROVED` or `REJECTED`
- **`WORKFLOW & BLAST-RADIUS FINDINGS`**: Exact multi-hop impacts or missing context.
- **`PROTECTED NODE & CONTRACT CHECK`**: Pass/Fail for each `PROTECTED_WORKING` node and `BC-xxx` contract.
- **`REQUIRED FIXES`**: Exact upstream changes required if `REJECTED`.
"""


def merge_claude_settings_hooks(workspace: Path) -> Path:
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.local.json"

    existing: Dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    hooks = existing.setdefault("hooks", {})
    hooks["PreToolUse"] = [
        {
            "matcher": "Edit|Write|MultiEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": "python research/harness/project_harness.py pre-tool",
                }
            ],
        }
    ]
    hooks["PostToolUse"] = [
        {
            "matcher": "Edit|Write|MultiEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": "python research/harness/project_harness.py post-tool",
                }
            ],
        }
    ]
    hooks["Stop"] = [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "python research/harness/project_harness.py stop",
                }
            ],
        }
    ]

    settings_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return settings_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RA Forge — Generate project-local Skill, Multi-Harness Hooks (.py), and Review Agent"
    )
    parser.add_argument("--workspace", default=".", help="Project workspace root")
    parser.add_argument("--name", required=True, help="Project or skill slug name (e.g., 'combat-engine')")
    parser.add_argument("--domain", required=True, help="Project R&D domain (e.g., 'Game Development / State Recognition')")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    rdir.mkdir(parents=True, exist_ok=True)

    slug = slugify(args.name)
    domain = args.domain.strip()

    # Load existing invariants, behavioral contracts, protected nodes, and crawled skills
    state_path = rdir / ".ra_state.json"
    state: Dict[str, Any] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    invariants: List[str] = []
    inv_file = rdir / "INVARIANTS.md"
    if inv_file.exists():
        for line in inv_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("- **`INV-"):
                invariants.append(line.strip())

    contracts: List[str] = []
    wmap_file = rdir / "WORKFLOW_MAP.md"
    if wmap_file.exists():
        for line in wmap_file.read_text(encoding="utf-8").splitlines():
            sline = line.strip()
            if (sline.startswith("- **`BC-") or sline.startswith("- `BC-")) and "<e.g.," not in sline:
                contracts.append(sline)

    protected_nodes: List[str] = state.get("protected_nodes", [])
    crawled_skills = [s.get("name", "") for s in state.get("arsenal", {}).get("skills", []) if s.get("name")]

    # 1. Write Executable Python Harness (`research/harness/project_harness.py`)
    harness_dir = rdir / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    harness_py = harness_dir / "project_harness.py"
    harness_py.write_text(HARNESS_PY_TEMPLATE, encoding="utf-8")

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
    reviewer_md = build_reviewer_agent_md(slug, domain)
    claude_agent_path = workspace / ".claude" / "agents" / "ra-reviewer.md"
    claude_agent_path.parent.mkdir(parents=True, exist_ok=True)
    claude_agent_path.write_text(reviewer_md, encoding="utf-8")

    agy_workflow_path = workspace / ".agents" / "workflows" / "ra-review.md"
    agy_workflow_path.parent.mkdir(parents=True, exist_ok=True)
    agy_workflow_path.write_text(reviewer_md, encoding="utf-8")

    prompt_path = harness_dir / "REVIEW_AGENT_PROMPT.md"
    prompt_path.write_text(reviewer_md, encoding="utf-8")

    # 4. Configure Claude Code Hooks in `.claude/settings.local.json`
    settings_path = merge_claude_settings_hooks(workspace)

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
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=" * 78)
    print(f"  RA FORGE — PROJECT-LOCAL SKILL, HARNESS & REVIEW AGENT CREATED ('{slug}')")
    print("=" * 78)
    print("  1. Project-Local Skills (Never Global):")
    print(f"     - .claude/skills/{slug}-rd/SKILL.md")
    print(f"     - .agents/skills/{slug}-rd/SKILL.md")
    print("  2. Executable Python Harness & Hook Gate:")
    print(f"     - {harness_py.relative_to(workspace).as_posix()}")
    print(f"     - {settings_path.relative_to(workspace).as_posix()} (Claude Code PreToolUse/PostToolUse/Stop hooks)")
    print("  3. Dedicated Adversarial Review Agent (Multi-Platform):")
    print(f"     - {claude_agent_path.relative_to(workspace).as_posix()} (Claude Code Subagent)")
    print(f"     - {agy_workflow_path.relative_to(workspace).as_posix()} (Antigravity / Agent Workflow)")
    print(f"     - {prompt_path.relative_to(workspace).as_posix()} (Universal Subagent Prompt)")
    print("=" * 78)


if __name__ == "__main__":
    main()
