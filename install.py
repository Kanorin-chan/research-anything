#!/usr/bin/env python3
"""
install.py — Multi-Platform Distribution Builder & Installer for RA (research-anything).

Supports:
  - Claude Code      (~/.claude/skills/research-anything)
  - Antigravity      (~/.agents/skills/research-anything & ~/.gemini/config/skills/research-anything)
  - Gemini CLI       (~/.gemini/skills/research-anything)
  - Local Workspace  (<workspace>/.agents/skills/research-anything & <workspace>/.claude/skills/research-anything)
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

CLAUDE_SNIPPET = """# RA (Research Anything) Integration for Claude Code

When researching or inventing zero-shot algorithms, neural networks, custom encryption, games, hardware/CPU layouts, materials, or novel systems:
1. Activate the `research-anything` (`RA`) skill (`/research-anything`).
2. Drive every step through `python ~/.claude/skills/research-anything/scripts/ra_gate.py`.
3. Never use hardcoded domain data ("cheese") or symptom-level band-aid patches.
"""

ANTIGRAVITY_SNIPPET = """# RA (Research Anything) Integration for Antigravity

When tackling novel ideas, zero-shot/zero-day problems, brand-new algorithms, neural networks, encryption, hardware/CPU layouts, or material/shape systems:
1. Read and follow the `research-anything` (`RA`) skill (`SKILL.md`).
2. Enforce the 7-stage state machine via `scripts/ra_gate.py` and `scripts/ra_cheese_audit.py`.
3. Never ask repeated questions without running `ra_gate.py check-question` first.
"""

GEMINI_SNIPPET = """# RA (Research Anything) Integration for Gemini CLI

Use the `research-anything` (`RA`) skill for first-principles invention and research-style engineering.
Always run `ra_gate.py status --workspace .` before transitioning stages and `ra_cheese_audit.py` before marking any hypothesis proven.
"""


def copy_skill_tree(src_skill: Path, dest_skill: Path) -> None:
    if dest_skill.exists():
        shutil.rmtree(dest_skill)
    dest_skill.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_skill, dest_skill)


def build_distributions(repo_root: Path) -> None:
    src_skill = repo_root / "skills" / "research-anything"
    dist_root = repo_root / "distributions"

    # 1. Claude Code distribution
    claude_dir = dist_root / "claude"
    copy_skill_tree(src_skill, claude_dir / ".claude" / "skills" / "research-anything")
    # Customize SKILL.md frontmatter for Claude Code (include allowed-tools hint)
    claude_skill_md = claude_dir / ".claude" / "skills" / "research-anything" / "SKILL.md"
    txt = claude_skill_md.read_text(encoding="utf-8")
    txt = txt.replace(
        '  version: "1.0.0"\n---',
        '  version: "1.0.0"\nallowed-tools: "Read, Write, Edit, Grep, Glob, Bash"\n---',
    )
    txt = txt.replace("<SKILL_DIR>", "~/.claude/skills/research-anything")
    claude_skill_md.write_text(txt, encoding="utf-8")
    (claude_dir / "CLAUDE.md.snippet").write_text(CLAUDE_SNIPPET, encoding="utf-8")

    # 2. Antigravity distribution
    agy_dir = dist_root / "antigravity"
    copy_skill_tree(src_skill, agy_dir / ".agents" / "skills" / "research-anything")
    agy_skill_md = agy_dir / ".agents" / "skills" / "research-anything" / "SKILL.md"
    txt_agy = agy_skill_md.read_text(encoding="utf-8").replace(
        "<SKILL_DIR>", "~/.agents/skills/research-anything"
    )
    agy_skill_md.write_text(txt_agy, encoding="utf-8")
    (agy_dir / "AGENTS.md.snippet").write_text(ANTIGRAVITY_SNIPPET, encoding="utf-8")

    # 3. Gemini CLI distribution
    gem_dir = dist_root / "gemini"
    copy_skill_tree(src_skill, gem_dir / ".gemini" / "skills" / "research-anything")
    gem_skill_md = gem_dir / ".gemini" / "skills" / "research-anything" / "SKILL.md"
    txt_gem = gem_skill_md.read_text(encoding="utf-8").replace(
        "<SKILL_DIR>", "~/.gemini/skills/research-anything"
    )
    gem_skill_md.write_text(txt_gem, encoding="utf-8")
    (gem_dir / "GEMINI.md.snippet").write_text(GEMINI_SNIPPET, encoding="utf-8")

    print(f"[RA INSTALLER] Built platform distributions under: {dist_root}")


def install_global(repo_root: Path, target: str) -> None:
    home = Path.home()
    dist_root = repo_root / "distributions"

    if target in ("claude", "all"):
        src = dist_root / "claude" / ".claude" / "skills" / "research-anything"
        dst = home / ".claude" / "skills" / "research-anything"
        copy_skill_tree(src, dst)
        print(f"[RA INSTALLER] Installed for Claude Code   -> {dst}")

    if target in ("antigravity", "all"):
        src = dist_root / "antigravity" / ".agents" / "skills" / "research-anything"
        dst1 = home / ".agents" / "skills" / "research-anything"
        dst2 = home / ".gemini" / "config" / "skills" / "research-anything"
        copy_skill_tree(src, dst1)
        copy_skill_tree(src, dst2)
        print(f"[RA INSTALLER] Installed for Antigravity   -> {dst1}")
        print(f"[RA INSTALLER] Installed for AGY Global    -> {dst2}")

    if target in ("gemini", "all"):
        src = dist_root / "gemini" / ".gemini" / "skills" / "research-anything"
        dst = home / ".gemini" / "skills" / "research-anything"
        copy_skill_tree(src, dst)
        print(f"[RA INSTALLER] Installed for Gemini CLI    -> {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and install RA (research-anything) across agent platforms.")
    parser.add_argument(
        "--target",
        choices=["all", "claude", "antigravity", "gemini", "dist-only"],
        default="all",
        help="Target agent platform to install globally (or dist-only to just build distributions/)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    build_distributions(repo_root)
    if args.target != "dist-only":
        install_global(repo_root, args.target)


if __name__ == "__main__":
    main()
