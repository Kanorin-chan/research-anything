# Autonomous R&D Crawler Suite & Project Skill/Harness Forge

**RA (`research-anything`)** is a full **R&D (Research & Development) Engine**. It covers both **Research** (inventing and proving mechanisms from first principles) and **Development** (automatically equipping the project workspace with domain skills, reference papers, test datasets, executable `.py` harnesses, hooks, and an adversarial Review Agent so the project actually works in production).

---

## 1. The Autonomous R&D Crawler Suite (`scripts/ra_crawler.py` — Optional / On-Demand)

Not every project requires external skills, research papers, or external datasets (for example, self-contained codebase debugging or pure internal logic fixes). However, when entering a specialized domain or when prior art / benchmark vectors are useful, use `ra_crawler.py` in priority order:

### Priority #1: Skill Crawler (`ra_crawler.py skill`)
When entering a domain (e.g., Game Development, Shader/GPU Programming, Physics Simulation, Cryptography, Embedded Systems, Custom Compilers), first check if the workspace already has the required domain skill. If not, crawl it automatically:

```bash
python "~/.gemini/skills/research-anything/scripts/ra_crawler.py" skill \
  --workspace "." \
  --query "game development"
```

Or pull directly from a known GitHub skill repository:
```bash
python "~/.gemini/skills/research-anything/scripts/ra_crawler.py" skill \
  --workspace "." \
  --query "game development" \
  --repo "anthropics/skills"
```

#### Strict Skill Crawler Rules:
1. **Quarantine & Security Audit First**: Every crawled skill is cloned into `research/arsenal/quarantine/` first and scanned for dangerous shell/eval payloads before installation.
2. **Project-Local Installation ONLY (Never Global)**: Verified skills are installed strictly inside the project workspace:
   - `.claude/skills/<skill-name>/SKILL.md`
   - `.agents/skills/<skill-name>/SKILL.md`
   - `research/arsenal/skills/<skill-name>/SKILL.md`
   Global skills (`~/.gemini/skills/` or `~/.claude/skills/`) are never polluted.

---

### Priority #2: Research Paper & Spec Crawler (`ra_crawler.py paper`)
When inventing or refining an equation, algorithm, or physical/system model, crawl peer-reviewed papers from arXiv and Semantic Scholar:

```bash
python "~/.gemini/skills/research-anything/scripts/ra_crawler.py" paper \
  --workspace "." \
  --query "state space model long horizon stability" \
  --max-results 5
```
- Saves structured titles, authors, publication years, URLs, and abstracts to `research/library/PAPERS_<slug>.md` with the `[EXTERNAL_VERIFIED_LAW]` provenance tag and indexes them in `research/library/REFERENCES_INDEX.md`.

---

### Priority #3: Data & Test-Vector Crawler (`ra_crawler.py data`)
To prevent using fake toy inputs during Stage 4 (`ADVERSARIAL_BREAK_TEST`), crawl real-world benchmark datasets or test vectors:

```bash
python "~/.gemini/skills/research-anything/scripts/ra_crawler.py" data \
  --workspace "." \
  --query "nist cryptographic test vectors" \
  --url "<optional-direct-dataset-url>"
```
- Stores downloaded files and SHA-256 provenance manifests in `research/arsenal/data/<slug>/`.

---

## 2. Forging a Custom Project Skill, `.py` Harness/Hooks & Review Agent (`scripts/ra_forge.py`)

When off-the-shelf crawled skills do not cover your project's unique workflow—or as soon as you lock `INVARIANTS.md` and `WORKFLOW_MAP.md`—forge a **project-specific skill, executable Python harness, multi-agent hooks, and dedicated Review Agent**:

```bash
python "~/.gemini/skills/research-anything/scripts/ra_forge.py" \
  --workspace "." \
  --name "<project-slug>" \
  --domain "<e.g., Game Development / Autonomous State Engine>"
```

### What `ra_forge.py` Creates (Multi-Harness Compliant & Project-Local):

| Generated Artifact | Path in Project Workspace | Purpose |
| :--- | :--- | :--- |
| **Project-Local Skill** | `.claude/skills/<slug>-rd/SKILL.md`<br>`.agents/skills/<slug>-rd/SKILL.md` | Encodes the project's `WORKFLOW_MAP.md`, `PROTECTED_WORKING` nodes (`Symptom != Culprit`), `BC-xxx` behavioral contracts, `INV-xxx` invariants, and crawled skills. |
| **Executable `.py` Harness** | `research/harness/project_harness.py` | Standalone CLI checker (`check-edit`, `check-all`) AND automated Hook runner (`pre-tool`, `post-tool`, `stop`). Blocks edits to `PROTECTED_WORKING` files and sealed axioms; catches `# hardcoded` and `except: pass` band-aids immediately. |
| **Claude Code Automated Hooks** | `.claude/settings.local.json` | Wires `PreToolUse` (`Edit\|Write\|MultiEdit`), `PostToolUse`, and `Stop` directly to `python research/harness/project_harness.py`. |
| **Dedicated Review Agent** | `.claude/agents/ra-reviewer.md`<br>`.agents/workflows/ra-review.md`<br>`research/harness/REVIEW_AGENT_PROMPT.md` | Independent adversarial Reviewer Agent for Claude Code, Antigravity (`invoke_subagent`), Cursor, or CLI agents. Audits every diff against `WORKFLOW_MAP.md`, `PROTECTED_WORKING` nodes, `BC-xxx` contracts, and `ra_cheese_audit.py`. |

### Mandatory Review Agent Gate
Before advancing any hypothesis to **Stage 7 (`GRADUATION_REVIEW`)** or merging any fix into the main project:
1. Run `python research/harness/project_harness.py check-all`.
2. Invoke the forged **Review Agent** (`ra-reviewer` / `REVIEW_AGENT_PROMPT.md`) to cold-audit the diff against `research/WORKFLOW_MAP.md` and verify zero regressions on existing behavioral contracts (`BC-xxx`).
