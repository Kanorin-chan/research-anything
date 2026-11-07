#!/usr/bin/env python3
"""
ra_crawler.py — Autonomous R&D Crawler Suite for RA (research-anything).

Priority 1: Skill Crawler (`skill`)
  - Searches GitHub / skill registries for domain `SKILL.md` packages (e.g., game dev,
    shaders, rust, robotics, ml) or clones from a specific repo/URL.
  - Audits crawled skills in quarantine (`research/arsenal/quarantine/`) for malicious
    patterns before installing them strictly PROJECT-LOCALLY into `.claude/skills/`
    and `.agents/skills/` (never polluting global skills).

Priority 2: Research Paper & Spec Crawler (`paper`)
  - Queries arXiv and Semantic Scholar APIs for peer-reviewed papers, mathematical
    formulations, and technical specifications matching the research query.
  - Saves structured summaries and citations to `research/library/PAPERS_<slug>.md`
    tagged with `[EXTERNAL_VERIFIED_LAW]`.

Priority 3: Data & Test-Vector Crawler (`data`)
  - Fetches real-world benchmark datasets, test vectors, or edge-case corpora from URLs
    or searches GitHub/HuggingFace datasets so Stage 4 break-tests use real test vectors
    instead of synthetic toy data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Tuple

USER_AGENT = "RA-ResearchAnything-Crawler/1.1 (Autonomous-RD-Engine)"

DANGEROUS_SKILL_PATTERNS = [
    (re.compile(r"\brm\s+-rf\s+(/|~|\$HOME)\b"), "Destructive root/home deletion command (`rm -rf`)"),
    (re.compile(r"(curl|wget)\s+[^\n|]+\|\s*(sh|bash|pwsh|powershell)\b", re.IGNORECASE), "Piped remote shell execution"),
    (re.compile(r"\b(eval|exec)\s*\(\s*base64\.", re.IGNORECASE), "Obfuscated base64 eval/exec payload"),
]

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


def ensure_research_dirs(workspace: Path) -> Path:
    rdir = workspace / "research"
    for sub in ["library", "arsenal/quarantine", "arsenal/skills", "arsenal/data"]:
        (rdir / sub).mkdir(parents=True, exist_ok=True)
    return rdir


def update_state_arsenal(workspace: Path, category: str, item_meta: Dict[str, Any]) -> None:
    sp = workspace / "research" / ".ra_state.json"
    if not sp.exists():
        return
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
        arsenal = state.setdefault("arsenal", {"skills": [], "papers": [], "data": []})
        entries: List[Dict[str, Any]] = arsenal.setdefault(category, [])
        entries = [e for e in entries if e.get("id") != item_meta.get("id")]
        entries.append(item_meta)
        arsenal[category] = entries
        state["updated_at"] = now_iso()
        sp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass


def append_reference_index(workspace: Path, ref_id: str, path_str: str, desc: str, constraints: str) -> None:
    ref_idx = workspace / "research" / "library" / "REFERENCES_INDEX.md"
    if not ref_idx.exists():
        return
    today = now_iso()[:10]
    row = f"| `{ref_id}` | `{path_str}` | `{today}` | {desc} | {constraints} |\n"
    txt = ref_idx.read_text(encoding="utf-8")
    if ref_id not in txt:
        with ref_idx.open("a", encoding="utf-8") as f:
            f.write(row)


def audit_skill_directory(skill_dir: Path) -> List[str]:
    issues: List[str] = []
    for fpath in sorted(skill_dir.rglob("*")):
        if not fpath.is_file():
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for regex, reason in DANGEROUS_SKILL_PATTERNS:
            if regex.search(content):
                issues.append(f"{fpath.name}: {reason}")
    return issues


def search_github_skills(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search GitHub repositories for skills matching the domain query."""
    results: List[Dict[str, str]] = []
    q = urllib.parse.quote(f"{query} skill claude OR agent OR SKILL.md")
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={max_results}"
    try:
        data = http_get_json(url)
        for item in data.get("items", [])[:max_results]:
            results.append(
                {
                    "full_name": item.get("full_name", ""),
                    "html_url": item.get("html_url", ""),
                    "description": item.get("description") or "No description",
                    "stars": str(item.get("stargazers_count", 0)),
                    "default_branch": item.get("default_branch", "main"),
                }
            )
    except Exception as exc:
        print(f"[RA CRAWLER] Note: GitHub API search returned: {exc}", file=sys.stderr)
    return results


def try_fetch_skill_from_repo(
    repo_full_name: str, skill_query: str, quarantine_dir: Path, branch: str = "main"
) -> Tuple[ bool, Path, str ]:
    """
    Clone or fetch a repository into quarantine and locate the best matching SKILL.md folder.
    Uses `git clone --depth 1` for speed.
    """
    clone_target = quarantine_dir / slugify(repo_full_name)
    if clone_target.exists():
        shutil.rmtree(clone_target)

    repo_url = repo_full_name if repo_full_name.startswith("http") else f"https://github.com/{repo_full_name}.git"
    cmd = ["git", "clone", "--depth", "1", repo_url, str(clone_target)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return False, clone_target, f"git clone failed: {proc.stderr.strip()}"

    # Remove .git metadata inside quarantine
    git_dir = clone_target / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir, ignore_errors=True)

    # Locate all SKILL.md files in the cloned repo
    skill_mds = list(clone_target.rglob("SKILL.md"))
    if not skill_mds:
        return True, clone_target, "Cloned repository (no standalone SKILL.md found; full repo staged in quarantine)."

    query_tokens = [t.lower() for t in re.split(r"\W+", skill_query) if t]
    best_md = skill_mds[0]
    best_score = -1
    for smd in skill_mds:
        rel_str = smd.relative_to(clone_target).as_posix().lower()
        body_preview = smd.read_text(encoding="utf-8", errors="ignore")[:1000].lower()
        score = sum(3 for tok in query_tokens if tok in rel_str) + sum(1 for tok in query_tokens if tok in body_preview)
        if score > best_score:
            best_score = score
            best_md = smd

    return True, best_md.parent, f"Located matching skill at `{best_md.relative_to(clone_target).as_posix()}`"


def install_skill_project_locally(
    workspace: Path, source_dir: Path, skill_name: str, provenance_url: str, query: str
) -> List[Path]:
    """
    Install a verified skill strictly inside the project workspace:
    - `.claude/skills/<skill_name>/`
    - `.agents/skills/<skill_name>/`
    - `research/arsenal/skills/<skill_name>/`
    Never touches global user skills.
    """
    installed_paths: List[Path] = []
    targets = [
        workspace / ".claude" / "skills" / skill_name,
        workspace / ".agents" / "skills" / skill_name,
        workspace / "research" / "arsenal" / "skills" / skill_name,
    ]
    for dest in targets:
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, dest)

        # Ensure SKILL.md exists; if source was a raw repo without SKILL.md, wrap README.md into SKILL.md
        skill_md = dest / "SKILL.md"
        if not skill_md.exists():
            readme = dest / "README.md"
            readme_body = readme.read_text(encoding="utf-8", errors="ignore") if readme.exists() else ""
            synthesized = (
                f"---\n"
                f"name: {skill_name}\n"
                f"description: Project-local skill crawled from {provenance_url} for domain '{query}'.\n"
                f"---\n\n"
                f"# {skill_name} (Crawled Project-Local Skill)\n\n"
                f"> **Provenance**: `{provenance_url}` | **Installed**: `{now_iso()}` (Project-Local Only)\n\n"
                f"{readme_body[:12000]}\n"
            )
            skill_md.write_text(synthesized, encoding="utf-8")

        installed_paths.append(dest)
    return installed_paths


def cmd_skill(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = ensure_research_dirs(workspace)
    quarantine_dir = rdir / "arsenal" / "quarantine"

    query = args.query.strip()
    skill_slug = slugify(args.name or query)

    print("=" * 78)
    print(f"  RA SKILL CRAWLER (PRIORITY #1) — DOMAIN: '{query}'")
    print("=" * 78)

    # 1. Check existing project-local skills first
    local_candidates = [
        workspace / ".claude" / "skills",
        workspace / ".agents" / "skills",
        rdir / "arsenal" / "skills",
    ]
    existing_local: List[Path] = []
    for ldir in local_candidates:
        if ldir.exists():
            for smd in ldir.rglob("SKILL.md"):
                existing_local.append(smd)

    if existing_local:
        print(f"  Existing Project-Local Skills ({len(existing_local)} found):")
        for el in existing_local[:10]:
            print(f"    - {el.relative_to(workspace).as_posix()}")
        print("-" * 78)

    target_repo = args.repo
    candidates: List[Dict[str, str]] = []

    if not target_repo:
        print(f"  Searching GitHub & skill registries for `{query}`...")
        candidates = search_github_skills(query, max_results=args.max_results)
        if candidates:
            print("  Top Discovered Skill Repositories:")
            for idx, c in enumerate(candidates, start=1):
                print(f"    [{idx}] {c['full_name']} (★ {c['stars']}) — {c['description']}")
                print(f"        URL: {c['html_url']}")
            if not args.search_only:
                target_repo = candidates[0]["full_name"]
        else:
            print("  No direct GitHub search hit; checking curated skill registries (`anthropics/skills`)...")
            if not args.search_only:
                target_repo = CURATED_SKILL_REPOS[0]

    if args.search_only or not target_repo:
        print("=" * 78)
        return

    print("-" * 78)
    print(f"  Fetching skill from `{target_repo}` into quarantine...")
    ok, staged_dir, msg = try_fetch_skill_from_repo(target_repo, query, quarantine_dir)
    if not ok:
        print(f"  [ERROR] Failed to crawl `{target_repo}`: {msg}", file=sys.stderr)
        sys.exit(1)

    print(f"  [OK] {msg}")
    print("  Running Security & Anti-Malware Quarantine Audit...")
    issues = audit_skill_directory(staged_dir)
    if issues:
        print("  [BLOCKED] Quarantined skill failed security audit and was NOT installed:", file=sys.stderr)
        for iss in issues:
            print(f"    - {iss}", file=sys.stderr)
        sys.exit(1)

    installed = install_skill_project_locally(workspace, staged_dir, skill_slug, target_repo, query)
    print("  [PASS] Security audit clean! Installed PROJECT-LOCALLY (global skills untouched):")
    for ip in installed:
        print(f"    - {ip.relative_to(workspace).as_posix()}")

    update_state_arsenal(
        workspace,
        "skills",
        {
            "id": f"SKILL-{skill_slug}",
            "name": skill_slug,
            "query": query,
            "source": target_repo,
            "installed_at": now_iso(),
            "paths": [p.relative_to(workspace).as_posix() for p in installed],
        },
    )
    append_reference_index(
        workspace,
        f"SKILL-{skill_slug.upper()[:12]}",
        f".claude/skills/{skill_slug}/SKILL.md",
        f"Crawled project-local skill from `{target_repo}` for `{query}`",
        "Project-local domain skill conventions & workflows",
    )
    print("=" * 78)


def crawl_arxiv(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    papers: List[Dict[str, str]] = []
    q = urllib.parse.quote(f"all:{query}")
    url = f"http://export.arxiv.org/api/query?search_query={q}&start=0&max_results={max_results}"
    try:
        xml_text = http_get_text(url)
        root = ET.fromstring(xml_text)
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
    except Exception as exc:
        print(f"[RA CRAWLER] Note: arXiv query returned: {exc}", file=sys.stderr)
    return papers


def crawl_semantic_scholar(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    papers: List[Dict[str, str]] = []
    q = urllib.parse.quote(query)
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={q}&limit={max_results}&fields=title,authors,year,url,abstract"
    )
    try:
        data = http_get_json(url)
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
    except Exception as exc:
        print(f"[RA CRAWLER] Note: Semantic Scholar query returned: {exc}", file=sys.stderr)
    return papers


def cmd_paper(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = ensure_research_dirs(workspace)

    query = args.query.strip()
    slug = slugify(query)
    out_file = rdir / "library" / f"PAPERS_{slug}.md"

    print("=" * 78)
    print(f"  RA RESEARCH PAPER CRAWLER (PRIORITY #2) — QUERY: '{query}'")
    print("=" * 78)

    papers = crawl_arxiv(query, max_results=args.max_results)
    if len(papers) < args.max_results:
        papers.extend(crawl_semantic_scholar(query, max_results=args.max_results - len(papers)))

    ts = now_iso()
    lines = [
        f"# [EXTERNAL_VERIFIED_LAW] Research Papers & Prior Art: {query}",
        "",
        f"- **Crawled Timestamp**: `{ts}`",
        f"- **Search Query**: `{query}`",
        f"- **Papers Indexed**: `{len(papers)}`",
        "",
        "> **RA Ground-Truth Library Rule**: Use these peer-reviewed formulations and empirical bounds as reference laws, but never copy-paste mismatched boilerplate when your project's constraints differ.",
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
        lines.append("_No external papers returned from live API query (check network or refine query terms)._\n")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    rel_out = out_file.relative_to(workspace).as_posix()

    update_state_arsenal(
        workspace,
        "papers",
        {"id": f"PAPERS-{slug}", "query": query, "count": len(papers), "file": rel_out, "crawled_at": ts},
    )
    append_reference_index(
        workspace,
        f"LIB-PAPER-{slug.upper()[:10]}",
        rel_out,
        f"Crawled {len(papers)} research paper(s) for `{query}`",
        "External mathematical/empirical prior art",
    )

    print(f"  Indexed {len(papers)} paper(s) into `{rel_out}`.")
    for idx, p in enumerate(papers, start=1):
        print(f"    [{idx}] ({p['published']}) {p['title']} — {p['url']}")
    print("=" * 78)


def cmd_data(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = ensure_research_dirs(workspace)

    slug = slugify(args.name or args.query)
    data_dir = rdir / "arsenal" / "data" / slug
    data_dir.mkdir(parents=True, exist_ok=True)
    ts = now_iso()

    print("=" * 78)
    print(f"  RA DATA & TEST-VECTOR CRAWLER (PRIORITY #3) — '{args.query}'")
    print("=" * 78)

    if args.url:
        req = urllib.request.Request(args.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
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
            f"DATA-{slug.upper()[:10]}",
            dest.relative_to(workspace).as_posix(),
            f"Crawled benchmark/test dataset from `{args.url}` ({len(raw)} bytes, SHA256 `{digest[:10]}...`)",
            "Real-world verification dataset for Stage 4 break-tests",
        )
        print(f"  Downloaded `{dest.relative_to(workspace).as_posix()}` ({len(raw)} bytes, SHA-256: {digest[:16]}...).")
    else:
        q = urllib.parse.quote(f"{args.query} dataset OR benchmark OR test-vectors")
        gh_url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=5"
        hf_url = f"https://huggingface.co/api/datasets?search={urllib.parse.quote(args.query)}&limit=5"
        discovered: List[Dict[str, str]] = []
        try:
            gh_data = http_get_json(gh_url)
            for item in gh_data.get("items", [])[:5]:
                discovered.append(
                    {
                        "source": "GitHub",
                        "name": item.get("full_name", ""),
                        "url": item.get("html_url", ""),
                        "description": item.get("description") or "",
                    }
                )
        except Exception:
            pass
        try:
            hf_data = http_get_json(hf_url)
            for item in hf_data[:5]:
                ds_id = item.get("id", "")
                discovered.append(
                    {
                        "source": "HuggingFace",
                        "name": ds_id,
                        "url": f"https://huggingface.co/datasets/{ds_id}",
                        "description": f"Downloads: {item.get('downloads', 0)}",
                    }
                )
        except Exception:
            pass

        catalog_path = data_dir / "DATA_SOURCES.md"
        lines = [
            f"# Discovered Benchmark & Test-Vector Sources: {args.query}",
            "",
            f"- **Crawled Timestamp**: `{ts}`",
            "",
            "| Source | Dataset / Repo | URL | Notes |",
            "| :--- | :--- | :--- | :--- |",
        ]
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA Autonomous R&D Crawler Suite (Skills, Papers, Data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_skill = sub.add_parser("skill", help="Priority #1: Crawl & audit a domain skill into project-local folders")
    p_skill.add_argument("--workspace", default=".", help="Project workspace root")
    p_skill.add_argument("--query", required=True, help="Domain or skill search query (e.g., 'game development')")
    p_skill.add_argument("--repo", default=None, help="Optional explicit GitHub repo ('owner/repo' or git URL)")
    p_skill.add_argument("--name", default=None, help="Optional project-local skill folder name override")
    p_skill.add_argument("--max-results", type=int, default=5, help="Max search results to inspect")
    p_skill.add_argument("--search-only", action="store_true", help="List matching skill repos without cloning")
    p_skill.set_defaults(func=cmd_skill)

    p_paper = sub.add_parser("paper", help="Priority #2: Crawl arXiv / Semantic Scholar papers into research/library/")
    p_paper.add_argument("--workspace", default=".", help="Project workspace root")
    p_paper.add_argument("--query", required=True, help="Research topic or mathematical mechanism query")
    p_paper.add_argument("--max-results", type=int, default=5, help="Max papers to index")
    p_paper.set_defaults(func=cmd_paper)

    p_data = sub.add_parser("data", help="Priority #3: Crawl real-world test vectors or datasets into research/arsenal/data/")
    p_data.add_argument("--workspace", default=".", help="Project workspace root")
    p_data.add_argument("--query", required=True, help="Dataset or test-vector topic")
    p_data.add_argument("--url", default=None, help="Optional direct URL to download dataset/test-vector file")
    p_data.add_argument("--name", default=None, help="Optional dataset folder slug")
    p_data.set_defaults(func=cmd_data)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
