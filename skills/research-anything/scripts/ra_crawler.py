#!/usr/bin/env python3
"""
ra_crawler.py — Autonomous R&D Crawler Suite for RA (research-anything).

Priority 1: Skill Crawler (`skill`) — nothing is installed without an explicit approve step:
  - search (default): `skill --query Q` prints ranked GitHub candidates; nothing is fetched.
  - fetch: `skill --query Q --repo owner/name` shallow-clones the repo into
    `research/arsenal/quarantine/`, picks the SKILL.md that best matches Q (refuses a zero
    match), runs a regex tripwire audit, stages the skill into `research/arsenal/skills/<slug>/`
    and lists every staged file (scripts, hooks, settings, plugin manifests flagged
    NEEDS HUMAN REVIEW).
  - approve: `skill --approve <slug>` re-audits the staged copy and copies it into the project's
    `.claude/skills/` and `.agents/skills/` (never the global skill folders).

Priority 2: Research Paper & Spec Crawler (`paper`)
  - Queries arXiv and Semantic Scholar and saves raw abstracts to
    `research/library/PAPERS_<slug>.md` tagged `[EXTERNAL_UNVERIFIED]` (crawled abstracts are
    not verified laws until someone checks the source).

Priority 3: Data & Test-Vector Crawler (`data`)
  - Fetches real-world benchmark datasets, test vectors, or edge-case corpora from URLs
    or searches GitHub/HuggingFace datasets so Stage 4 break-tests use real test vectors
    instead of synthetic toy data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Tuple

USER_AGENT = "RA-ResearchAnything-Crawler/1.1 (Autonomous-RD-Engine)"

AUDIT_DISCLAIMER = (
    "The audit is a regex tripwire, not a guarantee: obfuscated payloads can pass it. "
    "Read every staged file yourself before approving."
)

_RM_TARGET = r"""["']?(?:/|~|\$\{?HOME\}?|\$\{?USERPROFILE\}?|%USERPROFILE%|\$env:USERPROFILE|[A-Za-z]:)[\\/]?\*?["']?(?=[\s;&|)`]|$)"""
# PowerShell accepts any prefix of -EncodedCommand (-en, -enc, -encodedc...).
_ENC_PARAM = "|".join("encodedcommand"[:i] for i in range(14, 1, -1))
_WIN_TARGET = r"""["']?(?:~|\$env:USERPROFILE|\$env:SystemDrive|\$HOME|%USERPROFILE%|%SystemDrive%|[A-Za-z]:)[\\/]?\*?["']?(?=[\s;|)]|$)"""

DANGEROUS_SKILL_PATTERNS = [
    (re.compile(r"\brm\s+(?:-[-\w]*\s+)+" + _RM_TARGET, re.I | re.M), "Recursive delete of root/home (`rm -rf /|~|$HOME`)"),
    (
        re.compile(r"\b(?:Remove-Item|ri|rd|rmdir|del|erase)\b(?=[^\n]*\s(?:-r\w*|/s)\b)[^\n]*?\s" + _WIN_TARGET, re.I | re.M),
        "Recursive delete of a drive root or home folder (PowerShell/cmd)",
    ),
    (
        re.compile(
            r"rmtree\(\s*(?:os\.path\.expanduser\(\s*['\"]~['\"]\s*\)\s*[,)]|(?:pathlib\.)?Path\.home\(\)\s*[,)]"
            r"|os\.environ(?:\[|\.get\()\s*['\"](?:HOME|USERPROFILE)['\"]|['\"](?:/|~|[A-Za-z]:(?:\\\\|/)?)['\"]\s*[,)])",
            re.I,
        ),
        "Recursive delete of root/home (rmtree)",
    ),
    (
        re.compile(
            r"\b(?:curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\s+[^\s|][^\n]*\|\s*(?:sudo\s+)?"
            r"(?:(?:sh|bash|zsh|dash|ksh|fish|pwsh|powershell|iex|Invoke-Expression)\b"
            r"|(?:python[\d.]*|perl|ruby|node)(?:\s+-)?\s*(?=$|[;&|)`\"']))",
            re.I | re.M,
        ),
        "Remote download piped into a shell or interpreter",
    ),
    (
        re.compile(
            r"\b(?:curl|wget|iwr|Invoke-WebRequest|Start-BitsTransfer)\b[^\n]*?(?:&&|;|\|\|)\s*(?:sudo\s+)?"
            r"(?:(?:sh|bash|zsh|source|pwsh|powershell|chmod\s+\+x|start|cmd)\b|\.{1,2}/|\.\s)",
            re.I,
        ),
        "Download followed by execution",
    ),
    (
        re.compile(r"(?:\b(?:sh|bash|zsh|source|eval)|(?<!\S)\.)\s+(?:-c\s+)?[\"']?(?:<\(|\$\()\s*(?:curl|wget|iwr|irm)\b", re.I),
        "Remote script executed via command substitution",
    ),
    (
        re.compile(
            r"New-Object\s+(?:System\.)?Net\.WebClient|\.DownloadString\s*\(|\bInvoke-Expression\b|\|\s*iex\b"
            r"|\biex\s*\(\s*(?:\(|\[|New-Object|iwr|irm|Invoke-)",
            re.I,
        ),
        "PowerShell download cradle / Invoke-Expression",
    ),
    (re.compile(rf"\b(?:powershell|pwsh)(?:\.exe)?\b[^\n]*?\s[-/](?:{_ENC_PARAM}|ec|e)\b", re.I), "Encoded PowerShell command (-enc)"),
    (
        re.compile(
            r"\bcertutil\b[^\n]*-urlcache|\bbitsadmin\b[^\n]*/transfer|\bmshta\s+[\"']?(?:https?|vbscript|javascript):"
            r"|\bregsvr32\b[^\n]*/i:\s*https?:",
            re.I,
        ),
        "Windows LOLBin download/execute",
    ),
    (
        re.compile(
            r"\b(?:eval|exec|Function)\s*\([^\n]*?(?:b64decode|base64|atob\s*\(|__import__|marshal\.loads"
            r"|zlib\.decompress|codecs\.decode|fromhex|fromCharCode|urlopen|requests\.get)",
            re.I,
        ),
        "Obfuscated or remote eval/exec payload",
    ),
    (re.compile(r"/dev/tcp/|\bnc(?:at)?\b[^\n]*\s-[a-z]*e\s|\bsocat\b[^\n]*\bexec:", re.I), "Reverse-shell pattern"),
]

SCRIPT_EXTS = {
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1", ".psd1", ".bat", ".cmd", ".vbs", ".js", ".mjs", ".cjs",
    ".ts", ".py", ".rb", ".pl", ".php", ".lua", ".exe", ".dll", ".so", ".dylib", ".jar", ".msi", ".scr", ".wasm",
}
CREDENTIAL_RE = re.compile(
    r"\.ssh[/\\]|\bid_(?:rsa|ecdsa|ed25519)\b|\.aws[/\\]credentials|\.netrc\b|\.git-credentials|\.pypirc"
    r"|\.credentials\.json|Login Data",
    re.I,
)
FRONTMATTER_KEY_RE = re.compile(r"^\s*(hooks|allowed-tools|allowed_tools)\s*:", re.M | re.I)
QUERY_STOPWORDS = {"the", "and", "for", "with", "an", "of", "to", "in", "on", "md", "skill", "skills"}
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$")

CURATED_SKILL_REPOS = [
    "anthropics/skills",
    "affaan-m/everything-claude-code",
    "hesreallyhim/awesome-claude-code",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip().lower()).strip("-")
    return s or "item"


def fail(msg: str, code: int = 1) -> None:
    print(f"  [ERROR] {msg}", file=sys.stderr)
    sys.exit(code)


def banner(title: str) -> None:
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def http_get_json(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def http_get_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_workspace(raw: str) -> Path:
    ws = Path(raw).expanduser().resolve()
    if not ws.is_dir():
        fail(f"--workspace `{raw}` does not exist ({ws}). Create it first or fix the path.")
    return ws


def refuse_home_workspace(workspace: Path) -> None:
    if os.path.normcase(str(workspace)) == os.path.normcase(str(Path.home().resolve())):
        fail(
            f"--workspace resolves to your home folder ({workspace}); its .claude/skills and .agents/skills "
            "are the GLOBAL skill folders. Run this from a project folder."
        )


def ensure_research_dirs(workspace: Path) -> Path:
    rdir = workspace / "research"
    for sub in ["library", "arsenal/quarantine", "arsenal/skills", "arsenal/data"]:
        (rdir / sub).mkdir(parents=True, exist_ok=True)
    return rdir


def _is_link(path: str) -> bool:
    if os.path.islink(path):
        return True
    # Windows junctions are not symlinks to islink() but are followed by copytree.
    return getattr(os.lstat(path), "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


def _make_writable_and_retry(func: Any, path: str, _exc: Any) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def force_rmtree(path: Path) -> None:
    """Delete a tree, including read-only git pack files; a link is removed without touching its target."""
    if not os.path.lexists(path):
        return
    if _is_link(str(path)):
        try:
            os.unlink(path)
        except OSError:
            os.rmdir(path)
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=_make_writable_and_retry)


def update_state_arsenal(workspace: Path, category: str, item_meta: Dict[str, Any]) -> None:
    sp = workspace / "research" / ".ra_state.json"
    if not sp.exists():
        return
    try:
        state = json.loads(sp.read_text(encoding="utf-8-sig"))
        arsenal = state.setdefault("arsenal", {"skills": [], "papers": [], "data": []})
        entries: List[Dict[str, Any]] = arsenal.setdefault(category, [])
        entries = [e for e in entries if e.get("id") != item_meta.get("id")]
        entries.append(item_meta)
        arsenal[category] = entries
        state["updated_at"] = now_iso()
        sp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"  [WARN] Could not update `{sp}`: {exc}", file=sys.stderr)


def append_reference_index(workspace: Path, ref_id: str, path_str: str, desc: str, constraints: str) -> None:
    ref_idx = workspace / "research" / "library" / "REFERENCES_INDEX.md"
    if not ref_idx.exists():
        return
    today = now_iso()[:10]
    row = f"| `{ref_id}` | `{path_str}` | `{today}` | {desc} | {constraints} |\n"
    txt = ref_idx.read_text(encoding="utf-8-sig")
    # Match the backticked cell, so an ID that prefixes another still counts as new.
    if f"`{ref_id}`" not in txt:
        with ref_idx.open("a", encoding="utf-8") as f:
            f.write(row)


def _read_for_audit(fpath: Path) -> Tuple[str, bool]:
    data = fpath.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text, binary = data.decode("utf-16", errors="ignore"), False
    else:
        text, binary = data.decode("utf-8", errors="ignore"), b"\x00" in data[:8192]
    # Join shell/PowerShell line continuations so a split command still matches.
    return re.sub(r"[\\`]\r?\n", " ", text), binary


def _frontmatter(text: str) -> str:
    t = text.lstrip("\ufeff")
    if not t.startswith("---"):
        return ""
    end = t.find("\n---", 3)
    return t[3:end] if end != -1 else ""


def review_flags(rel: str, text: str, binary: bool) -> List[str]:
    parts = [p.lower() for p in rel.split("/")]
    name = parts[-1]
    flags: List[str] = []
    if os.path.splitext(name)[1] in SCRIPT_EXTS or text.startswith("#!"):
        flags.append("executable script")
    if "hooks" in parts[:-1] or name == "hooks.json":
        flags.append("hook definition")
    if fnmatch.fnmatch(name, "settings*.json"):
        flags.append("harness settings file")
    if ".claude-plugin" in parts:
        flags.append(".claude-plugin manifest")
    if name in (".mcp.json", "mcp.json"):
        flags.append("MCP server config")
    if name.endswith(".md"):
        keys = sorted({m.group(1).lower() for m in FRONTMATTER_KEY_RE.finditer(_frontmatter(text))})
        flags.extend(f"frontmatter `{k}:`" for k in keys)
    if binary:
        flags.append("binary file")
    if CREDENTIAL_RE.search(text):
        flags.append("references credential files")
    return flags


def audit_skill_directory(skill_dir: Path) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """Return (blocking issues, [(relative path, review flags)] for every file). Never follows links."""
    if _is_link(str(skill_dir)):
        return [f"{skill_dir.name}: the skill folder itself is a symlink/junction"], []
    blocked: List[str] = []
    files: List[Tuple[str, List[str]]] = []
    for dirpath, dirnames, filenames in os.walk(skill_dir, followlinks=False):
        for name in dirnames + filenames:
            full = os.path.join(dirpath, name)
            if _is_link(full):
                rel = Path(full).relative_to(skill_dir).as_posix()
                blocked.append(f"{rel}: symlink/junction (could expose files outside the skill)")
        dirnames[:] = [d for d in dirnames if not _is_link(os.path.join(dirpath, d))]
        for name in filenames:
            fpath = Path(dirpath) / name
            if _is_link(str(fpath)):
                continue
            rel = fpath.relative_to(skill_dir).as_posix()
            text, binary = _read_for_audit(fpath)
            for regex, reason in DANGEROUS_SKILL_PATTERNS:
                if regex.search(text):
                    blocked.append(f"{rel}: {reason}")
            files.append((rel, review_flags(rel, text, binary)))
    return blocked, sorted(files)


def print_audited_files(files: List[Tuple[str, List[str]]]) -> None:
    flagged = sum(1 for _, flags in files if flags)
    print(f"  Files ({len(files)} total, {flagged} NEEDS HUMAN REVIEW):")
    for rel, flags in files:
        suffix = f"  [NEEDS HUMAN REVIEW: {', '.join(flags)}]" if flags else ""
        print(f"    - {rel}{suffix}")


def search_github_skills(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search GitHub repositories for skills matching the domain query. Raises on network/API failure."""
    q = urllib.parse.quote(f"{query} skill claude OR agent OR SKILL.md")
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={max_results}"
    data = http_get_json(url)
    return [
        {
            "full_name": item.get("full_name", ""),
            "html_url": item.get("html_url", ""),
            "description": item.get("description") or "No description",
            "stars": str(item.get("stargazers_count", 0)),
        }
        for item in data.get("items", [])[:max_results]
    ]


def github_repo_url(repo: str) -> str:
    if GITHUB_REPO_RE.match(repo):
        name = repo[:-4] if repo.endswith(".git") else repo
        return f"https://github.com/{name}.git"
    if repo.startswith("https://"):
        return repo
    raise ValueError(f"--repo must be `owner/name` or an https:// git URL, got `{repo}`.")


def clone_into_quarantine(repo_url: str, clone_target: Path) -> Path:
    force_rmtree(clone_target)
    cmd = ["git", "-c", "core.longpaths=true", "clone", "--depth", "1", "--", repo_url, str(clone_target)]
    # Never block on a credential prompt for a missing/private repo.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    except FileNotFoundError:
        raise RuntimeError("git is not installed or not on PATH.")
    if proc.returncode != 0:
        force_rmtree(clone_target)
        raise RuntimeError(f"git clone failed (partial clone removed): {proc.stderr.strip()}")
    force_rmtree(clone_target / ".git")
    return clone_target


def _has_word(text: str, token: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(token), text) is not None


def rank_skill_mds(clone_root: Path, query: str) -> List[Tuple[int, str]]:
    """Score every SKILL.md: +3 per query word in its path, +1 per word in its first 1000 chars."""
    tokens = sorted({t for t in re.split(r"[\W_]+", query.lower()) if len(t) >= 2 and t not in QUERY_STOPWORDS})
    ranked: List[Tuple[int, str]] = []
    for dirpath, dirnames, filenames in os.walk(clone_root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not _is_link(os.path.join(dirpath, d)))
        smd = Path(dirpath) / "SKILL.md"
        if "SKILL.md" not in filenames or _is_link(str(smd)):
            continue
        rel = smd.relative_to(clone_root).as_posix()
        body = smd.read_text(encoding="utf-8", errors="ignore")[:1000].lower()
        score = sum(3 for t in tokens if _has_word(rel.lower(), t)) + sum(1 for t in tokens if _has_word(body, t))
        ranked.append((score, rel))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked


def list_existing_local_skills(workspace: Path) -> None:
    existing: List[Path] = []
    for ldir in [workspace / ".claude" / "skills", workspace / ".agents" / "skills", workspace / "research" / "arsenal" / "skills"]:
        if ldir.is_dir():
            existing.extend(ldir.rglob("SKILL.md"))
    if existing:
        print(f"  Existing Project-Local Skills ({len(existing)} found):")
        for el in existing[:10]:
            print(f"    - {el.relative_to(workspace).as_posix()}")
        print("-" * 78)


def skill_search(workspace: Path, query: str, max_results: int) -> None:
    banner(f"RA SKILL CRAWLER (PRIORITY #1) — SEARCH: '{query}'")
    list_existing_local_skills(workspace)
    print(f"  Searching GitHub for `{query}` (search only: nothing is fetched or installed)...")
    curated = ", ".join(CURATED_SKILL_REPOS)
    try:
        candidates = search_github_skills(query, max_results=max_results)
    except Exception as exc:
        print(f"  Curated registries you can pass to --repo instead: {curated}", file=sys.stderr)
        fail(f"GitHub search failed: {exc}")
        return
    if candidates:
        print("  Ranked Skill Repositories (by GitHub stars):")
        for idx, c in enumerate(candidates, start=1):
            print(f"    [{idx}] {c['full_name']} (stars: {c['stars']}) — {c['description']}")
            print(f"        URL: {c['html_url']}")
    else:
        print("  No GitHub results.")
    print(f"  Curated registries: {curated}")
    print("-" * 78)
    print("  Next: fetch + audit one into quarantine/staging (does NOT install):")
    print(f'    ra_crawler.py skill --workspace "." --query "{query}" --repo <owner/name>')
    print("=" * 78)


def skill_fetch(workspace: Path, repo: str, query: str, slug: str, force: bool) -> None:
    refuse_home_workspace(workspace)
    try:
        repo_url = github_repo_url(repo)
    except ValueError as exc:
        fail(str(exc))
        return
    rdir = ensure_research_dirs(workspace)
    quarantine_dir = rdir / "arsenal" / "quarantine"
    staged_dir = rdir / "arsenal" / "skills" / slug
    rel_staged = staged_dir.relative_to(workspace).as_posix()

    banner(f"RA SKILL CRAWLER (PRIORITY #1) — FETCH `{repo}` FOR '{query}'")
    if os.path.lexists(staged_dir) and not force:
        fail(f"`{rel_staged}` already exists. Pick another --name, or pass --force to replace it.")

    print(f"  Cloning `{repo}` into quarantine...")
    try:
        clone_root = clone_into_quarantine(repo_url, quarantine_dir / slugify(repo))
    except RuntimeError as exc:
        fail(f"Failed to crawl `{repo}`: {exc}")
        return

    ranked = rank_skill_mds(clone_root, query)
    if not ranked:
        fail(f"No SKILL.md found in `{repo}`; nothing staged.")
    print("  SKILL.md candidates (score = 3 per query word in path + 1 per word in first 1000 chars):")
    for score, rel in ranked[:5]:
        print(f"    {score:>3}  {rel}")
    best_score, best_rel = ranked[0]
    if best_score == 0:
        fail(f"No SKILL.md in `{repo}` matches the query words; nothing staged. Use a --query naming the skill folder.")

    source_dir = (clone_root / best_rel).parent
    print(f"  Selected `{best_rel}`. Running quarantine audit...")
    blocked, files = audit_skill_directory(source_dir)
    if blocked:
        print("  [BLOCKED] Skill failed the quarantine audit; nothing staged:", file=sys.stderr)
        for issue in blocked:
            print(f"    - {issue}", file=sys.stderr)
        print(f"  Left for inspection in `{source_dir.relative_to(workspace).as_posix()}`.", file=sys.stderr)
        sys.exit(1)

    force_rmtree(staged_dir)
    shutil.copytree(source_dir, staged_dir, symlinks=True)
    provenance = {"slug": slug, "repo": repo, "skill_path": best_rel, "score": best_score, "query": query, "staged_at": now_iso()}
    (quarantine_dir / f"{slug}.staged.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")

    print(f"  [STAGED] `{rel_staged}` (NOT installed; harness skill folders untouched).")
    print_audited_files(files)
    print(f"  NOTE: {AUDIT_DISCLAIMER}")
    print("-" * 78)
    print("  After reviewing, install into this project's .claude/skills and .agents/skills with:")
    print(f'    ra_crawler.py skill --workspace "." --approve {slug}')
    print("=" * 78)


def skill_approve(workspace: Path, slug: str, force: bool) -> None:
    refuse_home_workspace(workspace)
    if slugify(slug) != slug:
        fail(f"--approve takes a staged slug (lowercase letters, digits, - and _), got `{slug}`.")
    rdir = workspace / "research"
    staged_dir = rdir / "arsenal" / "skills" / slug
    if not (staged_dir / "SKILL.md").is_file():
        fail(f"Nothing staged at `research/arsenal/skills/{slug}/SKILL.md`. Run the --repo fetch step first.")

    banner(f"RA SKILL CRAWLER (PRIORITY #1) — APPROVE `{slug}`")
    print("  Re-auditing staged copy...")
    blocked, files = audit_skill_directory(staged_dir)
    if blocked:
        print("  [BLOCKED] Staged skill failed the audit; nothing installed:", file=sys.stderr)
        for issue in blocked:
            print(f"    - {issue}", file=sys.stderr)
        sys.exit(1)
    print_audited_files(files)
    print(f"  NOTE: {AUDIT_DISCLAIMER}")

    targets = [workspace / ".claude" / "skills" / slug, workspace / ".agents" / "skills" / slug]
    for dest in targets:
        if not dest.parent.resolve().is_relative_to(workspace):
            fail(f"`{dest.parent}` resolves outside the workspace (a link?); refusing to install there.")
    existing = [d for d in targets if os.path.lexists(d)]
    if existing and not force:
        names = ", ".join(d.relative_to(workspace).as_posix() for d in existing)
        fail(f"Already exists: {names}. Pass --force to replace.")

    for dest in targets:
        force_rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged_dir, dest, symlinks=True)
    rel_paths = [d.relative_to(workspace).as_posix() for d in targets]
    print("  [INSTALLED] Project-local only (global skills untouched):")
    for rp in rel_paths:
        print(f"    - {rp}")

    prov_file = rdir / "arsenal" / "quarantine" / f"{slug}.staged.json"
    try:
        prov = json.loads(prov_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prov = {}
    source = prov.get("repo", "unknown (no staging record)")
    query = prov.get("query", "")
    update_state_arsenal(
        workspace,
        "skills",
        {
            "id": f"SKILL-{slug}",
            "name": slug,
            "query": query,
            "source": source,
            "skill_path": prov.get("skill_path", ""),
            "installed_at": now_iso(),
            "paths": rel_paths,
        },
    )
    append_reference_index(
        workspace,
        f"SKILL-{slug.upper()}",
        f".claude/skills/{slug}/SKILL.md",
        f"Crawled project-local skill from `{source}` for `{query}`",
        "Project-local domain skill conventions & workflows",
    )
    print("=" * 78)


def cmd_skill(args: argparse.Namespace) -> None:
    workspace = resolve_workspace(args.workspace)
    if args.approve:
        skill_approve(workspace, args.approve, args.force)
        return
    query = (args.query or "").strip()
    if not query:
        fail("--query is required (except with --approve).")
    if args.repo:
        skill_fetch(workspace, args.repo, query, slugify(args.name or query), args.force)
    else:
        skill_search(workspace, query, args.max_results)


def crawl_arxiv(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    words = re.findall(r"\w+", query)
    if not words:
        return []
    # Each word needs its own field prefix; `all:a b` only scopes the first word.
    q = urllib.parse.quote(" AND ".join(f"all:{w}" for w in words))
    url = f"https://export.arxiv.org/api/query?search_query={q}&start=0&max_results={max_results}"
    papers: List[Dict[str, str]] = []
    root = ET.fromstring(http_get_text(url))
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip().replace("\n", " ")
        link = entry.findtext("atom:id", default="", namespaces=ns) or ""
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "")[:10]
        authors = [
            (a.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for a in entry.findall("atom:author", ns)
        ]
        if title:
            papers.append(
                {
                    "source": "arXiv",
                    "title": re.sub(r"\s+", " ", title),
                    "authors": ", ".join(authors[:5]),
                    "published": published,
                    "url": link,
                    "abstract": re.sub(r"\s+", " ", summary),
                }
            )
    return papers


def crawl_semantic_scholar(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    q = urllib.parse.quote(query)
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={q}&limit={max_results}&fields=title,authors,year,url,abstract"
    )
    data = http_get_json(url)
    papers: List[Dict[str, str]] = []
    for item in data.get("data", [])[:max_results]:
        authors = ", ".join(a.get("name", "") for a in (item.get("authors") or [])[:5])
        papers.append(
            {
                "source": "SemanticScholar",
                "title": item.get("title") or "Untitled",
                "authors": authors,
                "published": str(item.get("year") or "Unknown"),
                "url": item.get("url") or "",
                "abstract": re.sub(r"\s+", " ", (item.get("abstract") or "No abstract available.")),
            }
        )
    return papers


def cmd_paper(args: argparse.Namespace) -> None:
    workspace = resolve_workspace(args.workspace)
    query = args.query.strip()
    slug = slugify(query)

    banner(f"RA RESEARCH PAPER CRAWLER (PRIORITY #2) — QUERY: '{query}'")

    errors: List[str] = []
    papers: List[Dict[str, str]] = []
    try:
        papers = crawl_arxiv(query, max_results=args.max_results)
    except Exception as exc:
        errors.append(f"arXiv: {exc}")
    if len(papers) < args.max_results:
        try:
            papers.extend(crawl_semantic_scholar(query, max_results=args.max_results - len(papers)))
        except Exception as exc:
            errors.append(f"Semantic Scholar: {exc}")
    for err in errors:
        print(f"  [ERROR] {err}", file=sys.stderr)
    if errors and not papers:
        fail("Nothing written: a paper source failed and the rest returned no results.")

    rdir = ensure_research_dirs(workspace)
    out_file = rdir / "library" / f"PAPERS_{slug}.md"
    ts = now_iso()
    lines = [
        f"# [EXTERNAL_UNVERIFIED] Research Papers & Prior Art: {query}",
        "",
        f"- **Crawled Timestamp**: `{ts}`",
        f"- **Search Query**: `{query}`",
        f"- **Papers Indexed**: `{len(papers)}`",
    ]
    if errors:
        lines.append(f"- **Failed Sources**: {'; '.join(errors)}")
    lines += [
        "",
        "> **RA Ground-Truth Library Rule**: These are raw crawled abstracts (arXiv preprints are not peer-reviewed). "
        "Read the source and check it against your project's constraints before promoting any result to "
        "`[EXTERNAL_VERIFIED_LAW]`.",
        "",
        "---",
        "",
    ]
    for idx, p in enumerate(papers, start=1):
        lines.extend(
            [
                f"## {idx}. {p['title']}",
                f"- **Source / Date**: `{p['source']}` (`{p['published']}`)",
                f"- **Authors**: {p['authors']}",
                f"- **URL**: {p['url']}",
                f"- **Abstract**: {p['abstract']}",
                "",
            ]
        )
    if not papers:
        lines.append("_No papers matched this query._\n")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    rel_out = out_file.relative_to(workspace).as_posix()

    update_state_arsenal(
        workspace,
        "papers",
        {"id": f"PAPERS-{slug}", "query": query, "count": len(papers), "file": rel_out, "crawled_at": ts},
    )
    append_reference_index(
        workspace,
        f"LIB-PAPER-{slug.upper()}",
        rel_out,
        f"Crawled {len(papers)} research paper(s) for `{query}`",
        "`[EXTERNAL_UNVERIFIED]` raw abstracts; verify before citing as law",
    )

    print(f"  Indexed {len(papers)} paper(s) into `{rel_out}`.")
    for idx, p in enumerate(papers, start=1):
        print(f"    [{idx}] ({p['published']}) {p['title']} — {p['url']}")
    print("=" * 78)
    if errors:
        sys.exit(1)


def cmd_data(args: argparse.Namespace) -> None:
    workspace = resolve_workspace(args.workspace)
    slug = slugify(args.name or args.query)
    ts = now_iso()

    banner(f"RA DATA & TEST-VECTOR CRAWLER (PRIORITY #3) — '{args.query}'")

    if args.url:
        try:
            req = urllib.request.Request(args.url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
        except Exception as exc:
            fail(f"Download failed for `{args.url}`: {exc}")
            return
        data_dir = ensure_research_dirs(workspace) / "arsenal" / "data" / slug
        data_dir.mkdir(parents=True, exist_ok=True)
        fname = Path(urllib.parse.urlparse(args.url).path).name or f"{slug}.dat"
        dest = data_dir / fname
        dest.write_bytes(raw)
        digest = sha256_bytes(raw)
        manifest = {
            "id": f"DATA-{slug}",
            "query": args.query,
            "source_url": args.url,
            "file": dest.relative_to(workspace).as_posix(),
            "bytes": len(raw),
            "sha256": digest,
            "crawled_at": ts,
        }
        (data_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        update_state_arsenal(workspace, "data", manifest)
        append_reference_index(
            workspace,
            f"DATA-{slug.upper()}",
            dest.relative_to(workspace).as_posix(),
            f"Crawled benchmark/test dataset from `{args.url}` ({len(raw)} bytes, SHA256 `{digest[:10]}...`)",
            "Real-world verification dataset for Stage 4 break-tests",
        )
        print(f"  Downloaded `{dest.relative_to(workspace).as_posix()}` ({len(raw)} bytes, SHA-256: {digest[:16]}...).")
        print("=" * 78)
        return

    q = urllib.parse.quote(f"{args.query} dataset OR benchmark OR test-vectors")
    gh_url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=5"
    hf_url = f"https://huggingface.co/api/datasets?search={urllib.parse.quote(args.query)}&limit=5"
    discovered: List[Dict[str, str]] = []
    errors: List[str] = []
    try:
        for item in http_get_json(gh_url).get("items", [])[:5]:
            discovered.append(
                {
                    "source": "GitHub",
                    "name": item.get("full_name", ""),
                    "url": item.get("html_url", ""),
                    "description": item.get("description") or "",
                }
            )
    except Exception as exc:
        errors.append(f"GitHub: {exc}")
    try:
        for item in http_get_json(hf_url)[:5]:
            ds_id = item.get("id", "")
            discovered.append(
                {
                    "source": "HuggingFace",
                    "name": ds_id,
                    "url": f"https://huggingface.co/datasets/{ds_id}",
                    "description": f"Downloads: {item.get('downloads', 0)}",
                }
            )
    except Exception as exc:
        errors.append(f"HuggingFace: {exc}")
    for err in errors:
        print(f"  [ERROR] {err}", file=sys.stderr)
    if errors and not discovered:
        fail("Nothing cataloged: a dataset source failed and the rest returned no results.")

    data_dir = ensure_research_dirs(workspace) / "arsenal" / "data" / slug
    data_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = data_dir / "DATA_SOURCES.md"
    lines = [
        f"# Discovered Benchmark & Test-Vector Sources: {args.query}",
        "",
        f"- **Crawled Timestamp**: `{ts}`",
    ]
    if errors:
        lines.append(f"- **Failed Sources**: {'; '.join(errors)}")
    lines += ["", "| Source | Dataset / Repo | URL | Notes |", "| :--- | :--- | :--- | :--- |"]
    for d in discovered:
        lines.append(f"| `{d['source']}` | `{d['name']}` | {d['url']} | {d['description']} |")
    catalog_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rel_cat = catalog_path.relative_to(workspace).as_posix()
    update_state_arsenal(
        workspace,
        "data",
        {"id": f"DATA-{slug}", "query": args.query, "sources_found": len(discovered), "file": rel_cat, "crawled_at": ts},
    )
    print(f"  Cataloged {len(discovered)} dataset/test-vector source(s) in `{rel_cat}`:")
    for d in discovered:
        print(f"    - [{d['source']}] {d['name']} -> {d['url']}")
    print("=" * 78)
    if errors:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA Autonomous R&D Crawler Suite (Skills, Papers, Data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_skill = sub.add_parser(
        "skill",
        help="Priority #1: search (default) / fetch+stage (--repo) / install (--approve) a project-local skill",
    )
    p_skill.add_argument("--workspace", default=".", help="Project workspace root (must exist; never your home folder)")
    p_skill.add_argument("--query", default=None, help="Domain or skill search query (required unless --approve)")
    mode = p_skill.add_mutually_exclusive_group()
    mode.add_argument("--repo", default=None, help="Fetch + audit + stage from this GitHub repo ('owner/name' or https URL)")
    mode.add_argument("--approve", default=None, metavar="SLUG", help="Install a staged skill into .claude/skills and .agents/skills")
    mode.add_argument("--search-only", action="store_true", help="Search only (already the default; kept for compatibility)")
    p_skill.add_argument("--name", default=None, help="Staged skill slug override (default: slug of --query)")
    p_skill.add_argument("--force", action="store_true", help="Replace an existing staged/installed skill of the same slug")
    p_skill.add_argument("--max-results", type=int, default=5, help="Max search results to list")
    p_skill.set_defaults(func=cmd_skill)

    p_paper = sub.add_parser("paper", help="Priority #2: Crawl arXiv / Semantic Scholar papers into research/library/")
    p_paper.add_argument("--workspace", default=".", help="Project workspace root (must exist)")
    p_paper.add_argument("--query", required=True, help="Research topic or mathematical mechanism query")
    p_paper.add_argument("--max-results", type=int, default=5, help="Max papers to index")
    p_paper.set_defaults(func=cmd_paper)

    p_data = sub.add_parser("data", help="Priority #3: Crawl real-world test vectors or datasets into research/arsenal/data/")
    p_data.add_argument("--workspace", default=".", help="Project workspace root (must exist)")
    p_data.add_argument("--query", required=True, help="Dataset or test-vector topic")
    p_data.add_argument("--url", default=None, help="Optional direct URL to download dataset/test-vector file")
    p_data.add_argument("--name", default=None, help="Optional dataset folder slug")
    p_data.set_defaults(func=cmd_data)

    return p


def main() -> None:
    # Legacy code pages (cp932/cp1252) cannot encode the banner/dash characters.
    # Line buffering keeps stdout and stderr in order when both go to one pipe.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
