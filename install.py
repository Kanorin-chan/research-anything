#!/usr/bin/env python3
"""
install.py — Multi-Platform Distribution Builder & Composable Suite Installer for RA (research-anything).

Supports:
  - OpenCode         (~/.agents/skills/* & ~/.config/opencode/skills/*)
  - Claude Code      (~/.claude/skills/*)
  - Codex            (~/.agents/skills/* & ~/.codex/skills/*)
  - Antigravity      (~/.agents/skills/* & ~/.gemini/config/skills/*)
  - Gemini CLI       (~/.gemini/skills/*)
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
from pathlib import Path


def _on_rm_error(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree_force(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, onerror=_on_rm_error)

ROOT_SKILL_PARTS = ("SKILL.md", "agents", "scripts", "references", "resources")

ALL_SKILLS = (
    "research-anything",
    "ra-ask",
    "ra-talk",
    "ra-systemic-debug",
    "ra-workflow-map",
    "ra-context-fork",
    "ra-log-verify",
    "ra-visual-audit",
    "ra-anti-cheese",
    "ra-grilling",
    "ra-domain-modeling",
)

OPENCODE_SNIPPET = """# RA (Research Anything) Composable Suite for OpenCode

- Use `/ra-ask` to pick the right flow, `/ra-talk` to talk through a project without coding, `/ra-systemic-debug` for root-cause debugging without band-aids, `/ra-context-fork` for `/fork` subagent snapshots, or `/research-anything` for full 8-stage R&D.
"""

CLAUDE_SNIPPET = """# RA (Research Anything) Composable Suite for Claude Code

- Use `/ra-ask` to pick the right flow, `/ra-talk` to talk through a project without coding, `/ra-systemic-debug` for root-cause debugging without band-aids, `/ra-context-fork` for `/fork` subagent snapshots, or `/research-anything` for full 8-stage R&D.
"""

CODEX_SNIPPET = """# RA (Research Anything) Composable Suite for OpenAI Codex

- Use `$ra-ask` to pick the right flow, `$ra-talk` to talk through a project without coding, `$ra-systemic-debug` for root-cause debugging without band-aids, `$ra-context-fork` for subagent context snapshots, or `$research-anything` for full 8-stage R&D.
"""

ANTIGRAVITY_SNIPPET = """# RA (Research Anything) Composable Suite for Antigravity

- Use `ra-ask` to pick the right flow, `ra-talk` to talk through a project without coding, `ra-systemic-debug` for root-cause debugging without band-aids, `ra-context-fork` for subagent snapshots, or `research-anything` for full 8-stage R&D.
"""

GEMINI_SNIPPET = """# RA (Research Anything) Composable Suite for Gemini CLI

- Use `ra-ask` to pick the right flow, `ra-talk` to talk through a project without coding, `ra-systemic-debug` for root-cause debugging without band-aids, `ra-context-fork` for subagent snapshots, or `research-anything` for full 8-stage R&D.
"""


def sync_root_to_canonical_skill(repo_root: Path) -> Path:
    """Ensure `skills/research-anything/` mirrors the root skill files if root contains `SKILL.md`."""
    canonical = repo_root / "skills" / "research-anything"
    root_skill_md = repo_root / "SKILL.md"
    if root_skill_md.exists():
        canonical.mkdir(parents=True, exist_ok=True)
        for part in ROOT_SKILL_PARTS:
            src = repo_root / part
            dst = canonical / part
            if not src.exists():
                continue
            if dst.exists():
                if dst.is_dir():
                    rmtree_force(dst)
                else:
                    dst.unlink()
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    return canonical


def copy_skill_tree(src_skill: Path, dest_skill: Path) -> None:
    if src_skill.resolve() == dest_skill.resolve():
        return
    if dest_skill.exists():
        rmtree_force(dest_skill)
    dest_skill.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_skill, dest_skill)


def rewrite_skill_paths(skill_dir: Path, ra_dir: str | None) -> None:
    """Fill ${CLAUDE_SKILL_DIR} for harnesses that don't substitute it. ra_dir=None keeps the token (Claude Code)."""
    if ra_dir is None:
        return
    own_dir = ra_dir if skill_dir.name == "research-anything" else ra_dir.rsplit("/", 1)[0] + "/" + skill_dir.name
    for md in skill_dir.rglob("*.md"):
        raw = md.read_bytes().decode("utf-8")
        txt = (
            raw.replace("${CLAUDE_SKILL_DIR}/../research-anything", ra_dir)
            .replace("${CLAUDE_SKILL_DIR}", own_dir)
            .replace("~/.gemini/skills/research-anything", ra_dir)
        )
        if txt != raw:
            md.write_bytes(txt.encode("utf-8"))


def build_distributions(repo_root: Path) -> None:
    sync_root_to_canonical_skill(repo_root)
    skills_root = repo_root / "skills"
    dist_root = repo_root / "distributions"

    # $HOME (not ~) so quoted paths still expand in bash and PowerShell on the user's machine.
    platforms = [
        ("opencode", ".agents/skills", "$HOME/.agents/skills/research-anything", "AGENTS.md.snippet", OPENCODE_SNIPPET),
        ("claude", ".claude/skills", None, "CLAUDE.md.snippet", CLAUDE_SNIPPET),
        ("codex", ".agents/skills", "$HOME/.agents/skills/research-anything", "AGENTS.md.snippet", CODEX_SNIPPET),
        ("antigravity", ".agents/skills", "$HOME/.agents/skills/research-anything", "AGENTS.md.snippet", ANTIGRAVITY_SNIPPET),
        ("gemini", ".gemini/skills", "$HOME/.gemini/skills/research-anything", "GEMINI.md.snippet", GEMINI_SNIPPET),
    ]

    for plat_name, rel_skills_dir, script_base, snippet_name, snippet_body in platforms:
        plat_dir = dist_root / plat_name
        dest_skills_base = plat_dir / rel_skills_dir
        for sname in ALL_SKILLS:
            src_s = skills_root / sname
            if not src_s.exists():
                continue
            dst_s = dest_skills_base / sname
            copy_skill_tree(src_s, dst_s)
            rewrite_skill_paths(dst_s, script_base)
        (plat_dir / snippet_name).write_text(snippet_body, encoding="utf-8")

    print(
        f"[RA INSTALLER] Synchronized {len(ALL_SKILLS)} skills and built multi-platform distributions under: {dist_root}"
    )


def install_skill_dir_safe(src_skill: Path, dst_skill: Path, is_repo_root: bool = False) -> None:
    if src_skill.resolve() == dst_skill.resolve():
        return
    if is_repo_root or (dst_skill / ".git").exists():
        dst_skill.mkdir(parents=True, exist_ok=True)
        for part in ROOT_SKILL_PARTS:
            s = src_skill / part
            d = dst_skill / part
            if not s.exists() or s.resolve() == d.resolve():
                continue
            if d.exists():
                if d.is_dir():
                    rmtree_force(d)
                else:
                    d.unlink()
            if s.is_dir():
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
    else:
        copy_skill_tree(src_skill, dst_skill)


def install_suite_to_base(
    skills_root: Path, target_skills_base: Path, repo_root: Path, substitutes_skill_dir: bool = False
) -> None:
    target_skills_base.mkdir(parents=True, exist_ok=True)
    ra_dir = None if substitutes_skill_dir else (target_skills_base / "research-anything").resolve().as_posix()
    for sname in ALL_SKILLS:
        src_s = skills_root / sname
        if not src_s.exists():
            continue
        dst_s = target_skills_base / sname
        is_root = dst_s.resolve() == repo_root.resolve()
        install_skill_dir_safe(src_s, dst_s, is_repo_root=is_root)
        # A stale .git in the target must not skip the rewrite; only the source repo itself is left as-is.
        if not is_root:
            rewrite_skill_paths(dst_s, ra_dir)


def install_global(repo_root: Path, target: str) -> None:
    sync_root_to_canonical_skill(repo_root)
    home = Path.home()
    skills_root = repo_root / "skills"

    if target in ("opencode", "all"):
        dst1 = home / ".agents" / "skills"
        dst2 = home / ".config" / "opencode" / "skills"
        install_suite_to_base(skills_root, dst1, repo_root)
        install_suite_to_base(skills_root, dst2, repo_root)
        print(f"[RA INSTALLER] Installed {len(ALL_SKILLS)} skills for OpenCode     -> {dst1} & {dst2}")

    if target in ("claude", "all"):
        dst = home / ".claude" / "skills"
        install_suite_to_base(skills_root, dst, repo_root, substitutes_skill_dir=True)
        print(f"[RA INSTALLER] Installed {len(ALL_SKILLS)} skills for Claude Code  -> {dst}")

    if target in ("codex", "all"):
        dst1 = home / ".agents" / "skills"
        dst2 = home / ".codex" / "skills"
        install_suite_to_base(skills_root, dst1, repo_root)
        install_suite_to_base(skills_root, dst2, repo_root)
        print(f"[RA INSTALLER] Installed {len(ALL_SKILLS)} skills for Codex        -> {dst1} & {dst2}")

    if target in ("antigravity", "all"):
        dst1 = home / ".agents" / "skills"
        dst2 = home / ".gemini" / "config" / "skills"
        install_suite_to_base(skills_root, dst1, repo_root)
        install_suite_to_base(skills_root, dst2, repo_root)
        print(f"[RA INSTALLER] Installed {len(ALL_SKILLS)} skills for Antigravity  -> {dst1} & {dst2}")

    if target in ("gemini", "all"):
        dst = home / ".gemini" / "skills"
        install_suite_to_base(skills_root, dst, repo_root)
        print(f"[RA INSTALLER] Installed {len(ALL_SKILLS)} skills for Gemini CLI   -> {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and install the RA (research-anything) Composable Skill Suite across agent platforms."
    )
    parser.add_argument(
        "--target",
        choices=["all", "opencode", "claude", "codex", "antigravity", "gemini", "dist-only"],
        default="all",
        help="Target agent platform to install globally (or dist-only to build optional distributions/)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    if args.target == "dist-only":
        build_distributions(repo_root)
    else:
        install_global(repo_root, args.target)


if __name__ == "__main__":
    main()
