# RA — Research Anything (`research-anything`) v1.2.0

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Version: 1.2.0](https://img.shields.io/badge/Version-1.2.0-orange.svg)](#)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-None%20(Stdlib)-brightgreen.svg)](#)
[![Platforms](https://img.shields.io/badge/Platforms-OpenCode%20%7C%20Claude%20Code%20%7C%20Antigravity%20%7C%20Gemini%20CLI-purple.svg)](#installation)

**RA (`research-anything`)** is a first-principles autonomous R&D (Research & Development), multi-hop debugging, and invention engine for AI coding agents (**OpenCode**, **Claude Code**, **Google Antigravity / AGY**, **Gemini CLI**, and Open-Standard Agent Skills).

It is purpose-built for **zero-shot, zero-day, and brand-new inventions** as well as **deep multi-hop system architectures** where standard pre-trained boilerplate, 1-hop symptom fixes, and synthetic unit tests fail:
- **Novel Machine Learning & Neural Network Architectures** (new loss functions, attention/gating mechanisms, non-backprop learning rules)
- **Brand-New Algorithms, Data Structures & Distributed Frameworks**
- **Custom Cryptography, Hashing & Security Primitives**
- **Complex Game Engines, State Pipelines & Emergent Simulation Mechanics**
- **Hardware / CPU Re-Positioning, Thermal & Routing Layouts**
- **Material Science, Lab Data Modeling & Physical Systems**
- **Geometric Redesigns, Mathematical Shapes & Topology**

---

## Why Standard AI Agents Fail at Real R&D (And How RA Fixes It)

When you ask an LLM to invent something new or debug a deep multi-hop pipeline, ten predictable failure modes destroy the project:

| Failure Mode | What Standard AI Agents Do | How **RA (`research-anything`) v1.2.0** Solves It |
| :--- | :--- | :--- |
| **1. 1-Hop Symptom Blindness & Innocent-Function Mutation** | User says *"Function A is broken!"* and the AI blindly mutates `Function A`, breaking working code when the real bug was `Function C` 2 hops upstream (`Symptom != Culprit`). | **Stage 1 Multi-Hop Workflow Map & `PROTECTED_WORKING` Lock (`ra_gate.py map-context`)**: Traces `-N` to `+N` hops in `WORKFLOW_MAP.md`, proves culprit vs. innocent victim, and locks working functions so they cannot be modified. |
| **2. Whack-a-Mole Ping-Pong Regressions** | Fixes Bug B by wiping shared state, which silently breaks Behavior A that depended on that state. | **Existing Behavioral Contracts (`BC-xxx`)**: Locks all existing working guarantees (`BC-001`, `BC-002`...) in `WORKFLOW_MAP.md` and verifies every contract in real-environment `.log` traces. |
| **3. Context Bloat & Subagent Re-Reading** | Either dumps 7 tasks onto 1 long-context agent (causing attention decay) or spawns subagents that each re-read the entire codebase from scratch. | **Multi-Platform `/fork` Context Controller (`ra_context_harness.py`)**: Enforces **Read-Once $\rightarrow$ Fork-Many** snapshots (`BASE_FRAMEWORK`, `WORKFLOW_SLICE`, `TASK_EPHEMERAL`), **1-Concurrency Baton Relay**, **1 atomic task per R&D subagent**, and auto-eviction on SHA-256 hash drift across **OpenCode**, **Claude Code**, and **Antigravity/Gemini**. |
| **4. 30-Minute Trash Unit-Test Marathons** | Wastes 30 minutes running mocked `test_xyz.py` suites that pass in a synthetic bubble while the real deployment breaks or hangs. | **Production `.log` Spine & Watchdog (`ra_log_engine.py`)**: Bans synthetic unit tests; wires deployment code to `RALogger` (`Python`/`JS`/`TS`/`PHP`) logging `flow=caller->callee`, `inputs`, `state_before/after`, `delta`, `output`, `contract=BC-xxx`, and `[PASS]`/`[DECISION]`/`[STUCK]`/`[FAIL]` under a hard OS watchdog timer. |
| **5. Code-Context Visual Blindness & Ignored/Misfitted Provided Assets** | Reads CSS/HTML/shader code and claims *"UI looks great!"* while ignoring the user's provided assets/icons (substituting bare CSS boxes, emoji, or `placehold.co`), hallucinating broken asset paths, or squishing/stretching assets into the wrong container aspect ratio. | **User-Eyes Visual & Provided-Asset Reality Gate (`ra_visual_audit.py`)**: Auto-discovers provided assets (`assets/`, `public/`, `icons/`, `sprites/`), extracts native `WxH` & aspect ratio (`W:H`), blocks ignored provided assets (`[IGNORED_PROVIDED_ASSETS]`) or broken asset paths (`[BROKEN_ASSET_PATH]`), verifies real screenshots (`>= 64x64`, Shannon entropy `>= 2.2`), and audits container fit in `VISUAL_AUDIT.md`. |
| **6. Missing Domain Knowledge / Unverified Equations** | Hallucinates domain APIs or math formulas instead of pulling verified skills, peer-reviewed papers, or real benchmark vectors. | **Autonomous R&D Crawler Suite (`ra_crawler.py`)**: Priority #1: **Skill Crawler** (quarantine-audits & installs skills **project-locally** to `.claude/skills/` & `.agents/skills/`); Priority #2: **Paper Crawler** (arXiv & Semantic Scholar); Priority #3: **Data Crawler** (real test vectors). |
| **7. No Project-Specific Guardrails or Cold Review** | Uses generic prompts with no automated pre/post-edit hooks or independent reviewer to catch subtle regressions. | **Self-Forging Project Skill, `.py` Hooks & Reviewer (`ra_forge.py`)**: Generates a custom project skill, executable `research/harness/project_harness.py` (CLI + Claude Code `PreToolUse`/`PostToolUse`/`Stop` hooks), and a cold-eyes `ra-reviewer` agent. |
| **8. The Boilerplate Reflex** | Forces textbook patterns onto novel ideas whose mechanics and connections are fundamentally different. | **First-Principles Mandate (Stage 2)**: Forbids pattern-matching; requires explicit mathematical/structural derivation and Pre-Edit/Pre-Creation justification in `REPORT.md` before coding. |
| **9. The "Hardcoded Data" Slippery Slope** | Sees legitimate math/syntax symbols (like `=`) labeled `# hardcoded` and uses that as an excuse to dump lookup tables or `if input == X: return Y` branches when stuck. | **Axiom Seal + AST Cheese Auditor (`ra_cheese_audit.py`)**: Separates SHA-256 sealed `AXIOMATIC_PRIMITIVES` from forbidden data cheesing; fails Stage 5 if tampered with. |
| **10. Lazy Repeat Questions** | Asks the user the same question repeatedly instead of checking reference images and docs already on disk. | **Mandatory Pre-Question Gate (`check-question`)**: Forces the agent to scan and view all files/images in `reference/`, `assets/`, and `research/library/REFERENCES_INDEX.md` before asking anything. |

---

## The 8-Stage RA State Machine

Every research or debugging track is deterministically governed by [`scripts/ra_gate.py`](./scripts/ra_gate.py):

```text
[STAGE 0: INTAKE_AND_SYNC]
  ├── Conversational 1-by-1 Idea Intake -> research/VISION_AND_MISSION.md & INVARIANTS.md
  ├── Mandatory Pre-Question Search Gate (ra_gate.py check-question)
  ├── Autonomous R&D Crawler Suite (ra_crawler.py: 1. Skills -> 2. Papers -> 3. Data)
  └── Self-Forging Project Skill, .py Hooks & Review Agent (ra_forge.py)
       │
       ▼
[STAGE 1: WORKFLOW_AND_CONTEXT_MAPPING] ◄──────────────────────────────────┐
  ├── Full -N to +N hop trace & blast radius in research/WORKFLOW_MAP.md   │
  ├── Prove Culprit vs. Innocent Victim -> Lock PROTECTED_WORKING nodes    │
  ├── Lock Existing Behavioral Contracts (BC-001, BC-002...)               │
  └── Create Read-Once Shared Context Snapshot (ra_context_harness.py)     │
       │                                                                   │
       ▼                                                                   │
[STAGE 2: HYPOTHESIS_FORMULATION] ◄────────────────────────────────────────┤
  └── Culprit proof, Pre-Edit Justification & math formulation (REPORT.md) │
       │                                                                   │
       ▼                                                                   │
[STAGE 3: SANDBOX_PROTOTYPE & CONTEXT FORKING]                             │
  ├── Quarantined prototype inside research/sandbox/Hxxx_<slug>/           │
  ├── Fork shared snapshot to Subagents (opencode / claude / agy)          │
  ├── 1-Concurrency Baton Relay + Return Baton with Subagent Report        │
  ├── Wire deployment telemetry via RALogger (ra_log_engine.py inject-sdk) │
  └── Cryptographic SHA-256 sealing of legitimate AXIOMATIC_PRIMITIVES     │
       │                                                                   │
       ▼                                                                   │ (If FALSIFIED:
[STAGE 4: ADVERSARIAL_BREAK_TEST & REAL .LOG TELEMETRY]                    │  Quarantine to
  ├── Execute real workflow under OS Watchdog (ra_log_engine.py run)       │  research/graveyard/,
  └── Audit .log for [PASS]/[DECISION]/[STUCK]/[FAIL] & BC-xxx contracts   │  log Self-Learning,
       │                                                                   │  keep main codebase
       ▼                                                                   │  100% clean, & loop
[STAGE 5: ANTI_CHEESE_AND_VISUAL_REALITY_AUDIT]                            │  up to 5x autonomously)
  ├── AST + regex scan for lookup tables, band-aids & axiom tampering      │
  └── User-Eyes Visual Reality Gate (ra_visual_audit.py on real pixels)    │
       │                                                                   │
       ▼                                                                   │
[STAGE 6: LAB_REPORT_AND_LEARNING] ────────────────────────────────────────┘
  └── Provenance log (who/what/when) + Self-Learning triad (Issue:Workflow:Found)
       │
       ▼ (Only when PROVEN & Cheese-Free)
[STAGE 7: GRADUATION_REVIEW (Mandatory User Sign-Off)]
  ├── Run project_harness.py check-all & cold-eyes ra-reviewer audit
  └── Present Lab Report & wait for explicit User Sign-Off before merging
```

---

## Core Engines & Architecture

### 1. Multi-Platform `/fork` Context Controller, 1-Concurrency Baton & 3-Tier Snapshot Eviction ([`scripts/ra_context_harness.py`](./scripts/ra_context_harness.py))
Prevents Main-Agent context pollution and stops sibling subagents from redundantly re-reading the codebase:
- **Lead-Orchestrator Delegation & 1-Concurrency Baton Relay**: Even on single-GPU / 1-concurrency local setups (e.g., local `llama.cpp` 120B models), the Main Agent acts as Lead Orchestrator and passes a strict **1-concurrency execution baton** (`MAIN_ORCHESTRATOR` $\rightarrow$ `Subagent_A` $\rightarrow$ `MAIN_ORCHESTRATOR` $\rightarrow$ `Subagent_B`).
- **Task-Sizing Enforcement**:
  - `REAL_RD` (R&D, algorithmic, bug-fix): Strictly **1 atomic task per subagent** (blocks multi-task dumping).
  - `TRIVIAL_BATCH`: Small surface tweaks (*change CSS, swap icon, update text/labels*) allowed in one batch.
- **First-Class Multi-Platform `/fork` Support (`--platform auto|opencode|claude|agy`)**:
  - **OpenCode (`opencode`)**: Generates `opencode run --session <id> --fork --title "<subagent>"` and standalone `-f research/context_snapshots/forks/FORK_<subagent>.md` dispatches.
  - **Claude Code (`claude`)**: Generates `claude --resume <id> --fork-session` and native `Task(subagent_type="general-purpose", ...)` dispatches.
  - **Antigravity / Gemini (`agy`)**: Generates `invoke_subagent(TypeName="self", Role="...", Prompt="...")` dispatches.
- **3-Tier Snapshot Retention & Automatic Eviction (Throw-Away) Harness**:
  1. **`BASE_FRAMEWORK` (Tier 1)**: Project rules, `INVARIANTS.md`, crawled skills (`max_reuses=25`, `ttl=1440m`).
  2. **`WORKFLOW_SLICE` (Tier 2)**: Subsystem `-N` to `+N` hop map, `PROTECTED_WORKING` nodes, `BC-xxx` contracts, and SHA-256 file hashes (`max_reuses=6`, `ttl=180m`). **Automatically thrown away** on `HASH_DRIFT` as soon as any tracked file is edited.
  3. **`TASK_EPHEMERAL` (Tier 3)**: Single-task delta (`max_reuses=1`, `ttl=30m`). **Thrown away immediately** after 1 fork.
- **Hard Gate Enforcement**: `ra_gate.py advance` blocks leaving Stage 1 without an active `BASE_FRAMEWORK` or `WORKFLOW_SLICE` snapshot, and blocks leaving Stage 3 unless at least one subagent fork (`ra_context_harness.py fork`) and baton return (`ra_context_harness.py return-baton`) have completed.

### 2. Stage 1 Workflow, Blast-Radius & Innocent-Function Protection ([`research/WORKFLOW_MAP.md`](./resources/templates/WORKFLOW_MAP.md))
- **Symptom $\neq$ Culprit**: Before touching any code, the agent must trace the upstream producers (`-N` hops), shared state/ledgers, target node (`Hop 0`), downstream consumers (`+N` hops), and multi-cycle loopbacks.
- **`PROTECTED_WORKING` Lock**: Innocent functions are stamped via `ra_gate.py map-context --protected file.py:func_a` and cryptographically tracked by SHA-256 hash. Modifying a protected node fails `project_harness.py`.
- **AI-Session Staleness Warning**: Every `ra_gate.py status` refresh reminds incoming agents that `WORKFLOW_MAP.md` is an AI session snapshot and flags `[STALE / HASH CHANGED]` if any mapped file was modified.

### 3. Production `.log` Telemetry Spine, OS Watchdog & Flow Auditor ([`scripts/ra_log_engine.py`](./scripts/ra_log_engine.py))
- **No More 30-Minute Trash Unit-Test Marathons**: Synthetic unit tests (`test_xyz.py`) that mock away reality are banned.
- **Multi-Language `RALogger` SDK (`Python`, `JS/TS`, `PHP`)**: Injects a zero-dependency structured JSONL/text `.log` logger into the sandbox (`ra_log_engine.py inject-sdk --lang python`). Every hop logs:
  - `flow="caller->callee"`, `role`, `inputs`, `state_before`, `state_after`, `delta`, `output`, `contract="BC-001"`, `elapsed_ms`, and status (`[PASS]`, `[DECISION]`, `[STUCK]`, `[FAIL]`).
- **Hard Watchdog Execution (`ra_log_engine.py run --timeout-sec 60`)**: Terminates hung processes automatically and appends a `[STUCK]` record so the agent can immediately see which hop stalled and what values it held.
- **Automated `.log` Auditor (`ra_log_engine.py audit`)**: Verifies `>= 1` `[PASS]` hop, `0` `[STUCK]`/`[FAIL]` hops, non-empty variable telemetry, and `100%` of `BC-xxx` behavioral contracts from `WORKFLOW_MAP.md`.

### 4. Autonomous R&D Crawler Suite ([`scripts/ra_crawler.py`](./scripts/ra_crawler.py))
Equips the workspace in strict priority order:
1. **Priority #1 — Skill Crawler (`ra_crawler.py skill`)**: Searches GitHub and skill registries, runs a quarantine security audit (blocking `curl|bash`, `eval()`, obfuscated payloads), and installs skills **strictly project-locally** (`.claude/skills/<slug>/` and `.agents/skills/<slug>/`—never polluting global skills).
2. **Priority #2 — Research Paper Crawler (`ra_crawler.py paper`)**: Queries arXiv and Semantic Scholar APIs and indexes peer-reviewed formulations into `research/library/PAPERS_<slug>.md` (`[EXTERNAL_VERIFIED_LAW]`).
3. **Priority #3 — Data & Test-Vector Crawler (`ra_crawler.py data`)**: Pulls real-world benchmark datasets and edge-case test vectors into `research/arsenal/data/`.

### 5. Self-Forging Project Skill, `.py` Hooks & Cold-Eyes Review Agent ([`scripts/ra_forge.py`](./scripts/ra_forge.py))
Generates a project-tailored enforcement suite in one command:
- `.claude/skills/<slug>-rd/SKILL.md` & `.agents/skills/<slug>-rd/SKILL.md`
- `research/harness/project_harness.py` (executable CLI + Claude Code `PreToolUse`, `PostToolUse`, and `Stop` JSON stdin hook runner wired in `.claude/settings.local.json`)
- `.claude/agents/ra-reviewer.md`, `.agents/workflows/ra-review.md`, and `research/harness/REVIEW_AGENT_PROMPT.md` (hostile cold-eyes reviewer that audits diffs against `WORKFLOW_MAP.md`, `PROTECTED_WORKING` nodes, and `BC-xxx` contracts).

### 6. User-Eyes Visual, Provided-Asset & Container-Fit Gate ([`scripts/ra_visual_audit.py`](./scripts/ra_visual_audit.py))
- **Provided-Asset Auto-Discovery & Native Aspect-Ratio Extraction (`ra_visual_audit.py scan-assets`)**: Scans workspace and sandbox asset directories (`assets/`, `public/`, `static/`, `icons/`, `images/`, `sprites/`, `reference/`) for provided assets (`.png`, `.jpg`, `.webp`, `.svg`, `.ico`, `.gif`, `.bmp`, fonts, 3D models) and reports their native `WxH` resolution and aspect ratio (`W:H`) so the agent fits every asset/icon into a properly proportioned container.
- **Blocks Ignored Assets, Hallucinated Paths & Dummy Placeholders**: Fails Stage 5 if provided assets exist on disk but the AI ignored them (`[IGNORED_PROVIDED_ASSETS]`), if code references a non-existent asset filename (`[BROKEN_ASSET_PATH]` with fuzzy closest-asset suggestions), or if code uses external dummy URLs (`placehold.co`, `via.placeholder.com`).
- **Screenshot Binary & Pixel Audit**: Requires real rendered screenshots in `research/sandbox/Hxxx/visual_captures/`, verifies binary PNG/JPEG/WebP dimensions (`>= 64x64`) and **Shannon byte entropy (`>= 2.2` bits/byte)** to reject blank screens, and audits the 5-point User-Eyes & Asset-Fit checklist in `VISUAL_AUDIT.md`.

---

## Installation

### Option 1: Via `npx skills` (Open Agent Skills / Claude Code / OpenCode / Antigravity)

```bash
npx -y skills add Kanorin-chan/research-anything --skill research-anything
```

### Option 2: One-Command Python Installer (OpenCode, Claude Code, Antigravity, Gemini CLI)

Clone this repository and run [`install.py`](./install.py) (requires only Python 3.8+ standard library):

```bash
git clone https://github.com/Kanorin-chan/research-anything.git
cd research-anything

# Install globally for OpenCode, Claude Code, Antigravity, and Gemini CLI:
python install.py --target all

# Or install for a specific platform:
python install.py --target opencode      # -> ~/.agents/skills/research-anything & ~/.config/opencode/skills/research-anything
python install.py --target claude        # -> ~/.claude/skills/research-anything
python install.py --target antigravity   # -> ~/.agents/skills/research-anything & ~/.gemini/config/skills/research-anything
python install.py --target gemini        # -> ~/.gemini/skills/research-anything
```

### Option 3: Direct Clone Into Your Skill Directory

Because the repository root also contains `SKILL.md`, `scripts/`, `references/`, and `resources/`, you can clone it directly into any agent's skill folder:

```bash
git clone https://github.com/Kanorin-chan/research-anything.git ~/.gemini/skills/research-anything
# or ~/.agents/skills/research-anything
# or ~/.claude/skills/research-anything
```

---

## Workspace Directory Created by RA (`research/`)

When initialized in a project workspace (`python ra_gate.py init --workspace .`), RA maintains:

```text
<your-project>/
├── .claude/                        # Project-local crawled/forged skills, settings.local.json hooks, & ra-reviewer agent
├── .agents/                        # Project-local skills & workflows for OpenCode / Antigravity
└── research/
    ├── .ra_state.json              # Locked 8-stage state, protected nodes, axiom seals, & audit flags
    ├── VISION_AND_MISSION.md       # North Star vision, non-negotiables, & decomposed tracks
    ├── INVARIANTS.md               # Locked architectural decisions echoed on every stage transition
    ├── WORKFLOW_MAP.md             # Stage 1 multi-hop (-N to +N) map, PROTECTED_WORKING nodes, & BC-xxx contracts
    ├── LAB_LOG.md                  # Multi-agent/session chronological provenance ledger
    ├── SELF_LEARNING.md            # Continuous Issue : Workflow : Found mistake & discovery log
    ├── arsenal/                    # Crawled skills, papers, and real-world test vectors (ARMANIFEST.json)
    ├── harness/                    # Forged project_harness.py & REVIEW_AGENT_PROMPT.md
    ├── context_snapshots/          # Read-Once -> Fork-Many snapshots, forks/, reports/, & evicted/
    │   └── SNAPSHOT_REGISTRY.json  # Active baton state, reuse counters, SHA-256 hashes, & eviction history
    ├── library/                    # Firewall: ONLY verified ground truth & indexed user references
    │   └── REFERENCES_INDEX.md     # Mandatory index of all user images, diagrams, specs & answers
    ├── hypotheses/                 # Per-hypothesis scientific Lab Reports (H001_<slug>/REPORT.md)
    ├── sandbox/                    # Quarantined prototypes, RALogger SDK, logs/*.log, & visual_captures/
    └── graveyard/                  # Falsified hypotheses archived with exact proof of failure
```

---

## CLI Reference (All 7 Engines)

### 1. `ra_gate.py` — 8-Stage State-Machine Gatekeeper
```bash
# Initialize research/ folder structure in your workspace
python scripts/ra_gate.py init --workspace . --agent "MAIN_ORCHESTRATOR"

# Refresh context: print current stage, workflow staleness, protected nodes, BC-xxx, and INV-xxx
python scripts/ra_gate.py status --workspace .

# Mandatory Pre-Question Gate: scan reference/, assets/, docs/, and REFERENCES_INDEX.md
python scripts/ra_gate.py check-question --workspace .

# Stamp Stage 1 Workflow Map with tracked file hashes and PROTECTED_WORKING functions
python scripts/ra_gate.py map-context --workspace . --agent "MAIN_ORCHESTRATOR" \
  --files "bot_pipeline.py" --protected "bot_pipeline.py:func_a_summon"

# Start a new hypothesis and quarantined sandbox
python scripts/ra_gate.py new-hypothesis --workspace . --id H001 --slug "retry_fix" --agent "MAIN_ORCHESTRATOR"

# Cryptographically seal legitimate mathematical/structural axioms (SHA-256)
python scripts/ra_gate.py seal-axioms --workspace . --file "research/sandbox/H001_retry_fix/axioms.py"

# Validate stage completion and advance to the next stage
python scripts/ra_gate.py advance --workspace .

# Conclude a hypothesis (PROVEN or FALSIFIED) with mandatory Self-Learning triad
python scripts/ra_gate.py conclude --workspace . --verdict PROVEN \
  --issue "Upstream retry recovery cleared session dispatch ledger" \
  --workflow "User blamed downstream consumer func_a_summon; 2-hop trace isolated func_c" \
  --found "Transient retry state and session-once dispatch ledgers must remain orthogonal"

# Graduate a PROVEN hypothesis into research/library/ after user sign-off
python scripts/ra_gate.py graduate --workspace .
```

### 2. `ra_context_harness.py` — Multi-Platform `/fork` Context Controller & Eviction Harness
```bash
# Create a shared Read-Once context snapshot (BASE_FRAMEWORK, WORKFLOW_SLICE, or TASK_EPHEMERAL)
python scripts/ra_context_harness.py create --workspace . \
  --id "SNAP_WORKFLOW" --tier "WORKFLOW_SLICE" \
  --files "bot_pipeline.py" --summary "Compiled -2 to +2 hop workflow map and BC-001/BC-002 contracts"

# Fork the shared snapshot to Subagent_A (supports --platform auto|opencode|claude|agy)
python scripts/ra_context_harness.py fork --workspace . \
  --snapshots "SNAP_WORKFLOW" --subagent "Subagent_A" \
  --task-type "REAL_RD" --platform "opencode" \
  --task "Build isolated prototype in research/sandbox/H001_retry_fix/ and wire RALogger"

# Return the 1-concurrency baton after Subagent_A writes its report (auto-evicts hash-drifted snapshots)
python scripts/ra_context_harness.py return-baton --workspace . \
  --subagent "Subagent_A" --report-file "research/context_snapshots/reports/REPORT_Subagent_A.md"

# Check active snapshots, reuse budgets, baton holder, and evicted history
python scripts/ra_context_harness.py status --workspace .

# Run automatic garbage collection for hash-drifted, expired, or exhausted snapshots
python scripts/ra_context_harness.py evict --workspace . --auto-gc
```

### 3. `ra_log_engine.py` — Production `.log` Spine, OS Watchdog & Flow Auditor
```bash
# Inject zero-dependency RALogger SDK into the active sandbox (python, js, ts, or php)
python scripts/ra_log_engine.py inject-sdk --workspace . --hypothesis "H001_retry_fix" --lang python

# Run real workflow under a hard OS watchdog timer (auto-logs [STUCK] on timeout)
python scripts/ra_log_engine.py run --workspace . --hypothesis "H001_retry_fix" \
  --timeout-sec 60 --cmd "python research/sandbox/H001_retry_fix/bot_pipeline.py"

# Audit the generated .log file for [PASS]/[DECISION]/[STUCK]/[FAIL], variable deltas, and BC-xxx contracts
python scripts/ra_log_engine.py audit --workspace . --hypothesis "H001_retry_fix"
```

### 4. `ra_crawler.py` — Autonomous Skill, Paper & Data Crawler
```bash
# Priority #1: Crawl & quarantine-audit domain skills into project-local .claude/skills/ & .agents/skills/
python scripts/ra_crawler.py skill --workspace . --query "game-development"

# Priority #2: Crawl arXiv & Semantic Scholar papers into research/library/PAPERS_<slug>.md
python scripts/ra_crawler.py paper --workspace . --query "monotonic state lattice"

# Priority #3: Crawl real-world test vectors into research/arsenal/data/
python scripts/ra_crawler.py data --workspace . --query "json-test-suite"
```

### 5. `ra_forge.py` — Self-Forging Project Skill, `.py` Hooks & Cold-Eyes Reviewer
```bash
# Forge project-local skill, research/harness/project_harness.py, .claude/settings.local.json hooks, & ra-reviewer
python scripts/ra_forge.py --workspace . --name "bot-pipeline" --domain "stateful-dispatch-pipeline"

# Run the forged project harness at Stage 7 before Graduation Review
python research/harness/project_harness.py check-all --workspace .
```

### 6. `ra_cheese_audit.py` & `ra_visual_audit.py` — Stage 5 Auditors
```bash
# Scan sandbox for axiom tampering, lookup tables, hardcoded branches, and band-aid exception swallowing
python scripts/ra_cheese_audit.py --workspace . --hypothesis "H001_retry_fix"

# Scan provided workspace/sandbox assets, native WxH/aspect ratios, unused assets, and broken asset paths
python scripts/ra_visual_audit.py scan-assets --workspace . --hypothesis "H001_retry_fix"

# Initialize & audit User-Eyes Visual + Provided-Asset Fit Reality (verifies assets, dimensions & entropy >= 2.2)
python scripts/ra_visual_audit.py init --workspace . --hypothesis "H001_retry_fix"
python scripts/ra_visual_audit.py audit --workspace . --hypothesis "H001_retry_fix"
```

---

## License

Released under the [MIT License](./LICENSE).
