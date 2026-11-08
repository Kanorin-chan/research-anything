# RA — Research Anything (`research-anything`) v1.5.0

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Version: 1.3.0](https://img.shields.io/badge/Version-1.3.0-orange.svg)](#)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-None%20(Stdlib)-brightgreen.svg)](#)
[![Platforms](https://img.shields.io/badge/Platforms-OpenCode%20%7C%20Claude%20Code%20%7C%20Codex%20%7C%20Antigravity%20%7C%20Gemini%20CLI-purple.svg)](#installation-30-second-setup)

**RA (`research-anything`)** is a composable **Super-Skill Suite** for first-principles R&D, stateful project grilling, systemic multi-hop root-cause debugging, `/fork` context controlling, real-environment `.log` telemetry, and User-Eyes visual/asset reality auditing across **OpenCode**, **Claude Code**, **OpenAI Codex**, **Google Antigravity (AGY)**, and **Gemini CLI**.

Use it **partially** (e.g., just talking through a project with `/ra-talk`, mapping a subsystem with `/ra-workflow-map`, or fixing a bug from its upstream root cause with `/ra-systemic-debug`) **or** run the **Full 8-Stage Super-Skill (`/research-anything`)** for zero-shot inventions where standard pre-trained boilerplate fails.

---

## Installation (30-Second Setup)

Pick one installation route per agent (installing both a managed plugin and a manual copy gives you every skill twice).

<details>
<summary><strong>Claude Code</strong> (Plugin Marketplace)</summary>

```bash
claude plugin marketplace add Kanorin-chan/research-anything
claude plugin install research-anything@kanorin-chan
```

</details>

<details>
<summary><strong>Codex</strong> (Plugin Marketplace)</summary>

```bash
codex plugin marketplace add Kanorin-chan/research-anything
codex plugin add research-anything@kanorin-chan
```

Updates itself at startup. Every skill includes `agents/openai.yaml` metadata.

</details>

<details>
<summary><strong>GitHub Copilot</strong> (CLI and VS Code)</summary>

```bash
copilot plugin marketplace add Kanorin-chan/research-anything
copilot plugin install research-anything@kanorin-chan
```

In VS Code, run **Chat: Install Plugin From Source** and enter `https://github.com/Kanorin-chan/research-anything`.

</details>

<details>
<summary><strong>OpenCode, Antigravity (AGY), Claude Code, Codex & Gemini CLI</strong> (One-Command Python Installer)</summary>

Clone this repository and run [`install.py`](./install.py) (zero dependencies, Python 3.8+ stdlib):

```bash
git clone https://github.com/Kanorin-chan/research-anything.git
cd research-anything

# Install all 11 composable skills globally across OpenCode, Claude Code, Codex, Antigravity, and Gemini CLI:
python install.py --target all

# Or install for a specific platform:
python install.py --target opencode      # -> ~/.agents/skills/* & ~/.config/opencode/skills/*
python install.py --target claude        # -> ~/.claude/skills/*
python install.py --target codex         # -> ~/.agents/skills/* & ~/.codex/skills/*
python install.py --target antigravity   # -> ~/.agents/skills/* & ~/.gemini/config/skills/*
python install.py --target gemini        # -> ~/.gemini/skills/*
```

</details>

<details>
<summary><strong>Gemini CLI</strong> (Git Skill Installer)</summary>

```bash
gemini skills install https://github.com/Kanorin-chan/research-anything.git --path skills
```

</details>

<details>
<summary><strong>Any Agent via <code>skills.sh</code></strong> (<code>npx skills@latest</code>)</summary>

```bash
# Install the entire suite for your agent (opencode, claude-code, codex, cursor, windsurf, etc.):
npx skills@latest add Kanorin-chan/research-anything -a <agent>

# Or install a single skill on its own:
npx skills@latest add Kanorin-chan/research-anything --skill=ra-systemic-debug
npx skills@latest add Kanorin-chan/research-anything --skill=ra-talk
npx skills@latest add Kanorin-chan/research-anything --skill=research-anything
```

</details>

---

## Composable Skill Suite Reference (Partial vs. Full Flows)

Every skill in this repo splits on one axis: **who can invoke it**.
- **User-invoked** skills (`disable-model-invocation: true` in `SKILL.md` and `policy.allow_implicit_invocation: false` in `agents/openai.yaml`) run only when you explicitly invoke them; their job is to orchestrate.
- **Model-invoked** skills can be invoked directly by you *or* reached automatically by the agent (or by another skill via `Call the Skill tool with "<skill>"`).

### User-Invoked Orchestrators

- **[`ra-ask`](./skills/ra-ask/SKILL.md)**: **Router over the entire RA skill suite.** Ask which partial skill or full flow fits your current situation (includes [PHASE-BOUNDARIES.md](./skills/ra-ask/PHASE-BOUNDARIES.md) for choosing between Continue, `/ra-context-fork`, `/clear`, `handoff`, and `/compact`).
- **[`ra-talk`](./skills/ra-talk/SKILL.md)**: **Just talk through the project (no coding).** Runs the Pre-Question Search Gate (`ra_gate.py check-question`) so the agent reads your existing `GLOSSARY.md`, `reference/`, `assets/`, and `VISION_AND_MISSION.md` first, then drives [`ra-grilling`](./skills/ra-grilling/SKILL.md) and [`ra-domain-modeling`](./skills/ra-domain-modeling/SKILL.md) to interview you in frontier rounds (`❓ Q1 ... ➡️ Recommended`) and update `GLOSSARY.md` + `research/INVARIANTS.md` inline.

### Model-Invoked (and User-Invocable) Engineering & R&D Skills

- **[`ra-systemic-debug`](./skills/ra-systemic-debug/SKILL.md)**: **Systemic Multi-Hop Root-Cause Debugger (Fix From Root, Never Patch a Band-Aid).**
  1. Builds a fast, deterministic real-environment `.log` feedback loop (`ra_log_engine.py run`) that goes red (`[FAIL]`/`[STUCK]`) on the exact bug (bans 30-minute mocked unit tests).
  2. Traces `-N` to `+N` hops in `WORKFLOW_MAP.md`, proves `Symptom != Culprit`, locks innocent working functions as **`PROTECTED_WORKING`**, and locks existing **`BC-xxx` behavioral contracts** to prevent whack-a-mole regressions.
  3. Formulates 3–5 ranked falsifiable hypotheses with explicit predictions.
  4. Replaces the broken upstream pipe from first principles (**strictly bans** `try/except: pass`, `if x is None` crash-site guards, clamping, or extra boolean flags) and verifies via `ra_log_engine.py audit` + `ra_cheese_audit.py`.
- **[`ra-workflow-map`](./skills/ra-workflow-map/SKILL.md)**: **Standalone `-N` to `+N` Hop Workflow, Blast-Radius & Contract Mapper.** Traces upstream producers $\rightarrow$ shared state $\rightarrow$ target node $\rightarrow$ downstream consumers in `research/WORKFLOW_MAP.md`, locks `PROTECTED_WORKING` functions and `BC-xxx` contracts, and stamps SHA-256 file hashes (`ra_gate.py map-context`).
- **[`ra-context-fork`](./skills/ra-context-fork/SKILL.md)**: **Multi-Platform `/fork` Context Controller, 1-Concurrency Baton & Portable Handoff.** Compiles Read-Once snapshots (`BASE_FRAMEWORK`, `WORKFLOW_SLICE`, `TASK_EPHEMERAL`), forks bounded 1-task packets across **OpenCode (`opencode`)**, **Claude Code (`claude`)**, **Codex (`codex`)**, and **Antigravity/Gemini (`agy`)**, manages the 1-concurrency baton (`return-baton`), writes portable cross-harness `/handoff` files (`ra_context_harness.py handoff`), and auto-evicts stale snapshots on `HASH_DRIFT`.
- **[`ra-log-verify`](./skills/ra-log-verify/SKILL.md)**: **Production `.log` Telemetry Spine, OS Watchdog & Flow Auditor.** Injects zero-dependency `RALogger` (`Python`/`JS`/`TS`/`PHP`), runs real commands under an OS watchdog timer (`ra_log_engine.py run --timeout-sec 60`), and audits `[PASS]`/`[DECISION]`/`[STUCK]`/`[FAIL]` hops + `BC-xxx` contracts (`ra_log_engine.py audit`).
- **[`ra-visual-audit`](./skills/ra-visual-audit/SKILL.md)**: **User-Eyes Visual, Provided-Asset & Container-Fit Gate.** Auto-discovers provided workspace assets (`assets/`, `public/`, `icons/`, `sprites/`), extracts native `WxH` dimensions & aspect ratios (`W:H`) for container fitting (`ra_visual_audit.py scan-assets`), blocks ignored provided assets (`[IGNORED_PROVIDED_ASSETS]`) or broken asset paths (`[BROKEN_ASSET_PATH]`), and audits real screenshots (`>= 64x64`, Shannon entropy `>= 2.2`).
- **[`ra-anti-cheese`](./skills/ra-anti-cheese/SKILL.md)**: **Axiom Seal, Anti-Cheese AST Scanner & Self-Forging Harness/Reviewer.** Cryptographically seals `AXIOMATIC_PRIMITIVES` (`ra_gate.py seal-axioms`), scans for hardcoded lookup tables and band-aids (`ra_cheese_audit.py`), and forges `project_harness.py` + the cold-eyes `ra-reviewer` agent (`ra_forge.py`).
- **[`ra-grilling`](./skills/ra-grilling/SKILL.md)**: **Relentless Design-Tree Interview Primitive.** Interviews the user in frontier rounds (`❓ Q1 ... ➡️ Recommended`), checking local files/images for facts first via `check-question`.
- **[`ra-domain-modeling`](./skills/ra-domain-modeling/SKILL.md)**: **Active Shared Language (`GLOSSARY.md`), Invariants (`INVARIANTS.md`) & ADR Builder.** Challenges fuzzy/overloaded terms, stress-tests with concrete edge cases, cross-references code with Zero-Trust Comment verification, and updates `GLOSSARY.md` & `INVARIANTS.md` inline.
- **[`research-anything`](./skills/research-anything/SKILL.md)**: **The Full 8-Stage Super-Skill (`STAGE_0` $\rightarrow$ `STAGE_7`).** Orchestrates the entire Scientific Method state machine for zero-shot inventions, novel algorithms, neural architectures, custom cryptography, games, and hardware/material systems.

---

## Why Standard AI Agents Fail at Real Engineering & R&D (And How RA Fixes It)

| Failure Mode | What Standard AI Agents Do | How **RA (`research-anything`) v1.3.0** Solves It |
| :--- | :--- | :--- |
| **1. 1-Hop Symptom Blindness & Innocent-Function Mutation** | User says *"Function A is broken!"* and the AI blindly mutates `Function A`, breaking working code when the real bug was `Function C` 2 hops upstream (`Symptom != Culprit`). | **`ra-workflow-map` & `ra-systemic-debug` (`ra_gate.py map-context`)**: Traces `-N` to `+N` hops in `WORKFLOW_MAP.md`, proves culprit vs. innocent victim, and locks working functions as `PROTECTED_WORKING`. |
| **2. Whack-a-Mole Ping-Pong Regressions** | Fixes Bug B by wiping shared state, which silently breaks Behavior A that depended on that state. | **Existing Behavioral Contracts (`BC-xxx`)**: Locks all existing working guarantees (`BC-001`, `BC-002`...) in `WORKFLOW_MAP.md` and verifies every contract in real-environment `.log` traces. |
| **3. Context Bloat & Subagent Re-Reading** | Either dumps 7 tasks onto 1 long-context agent (causing attention decay) or spawns subagents that each re-read the entire codebase from scratch. | **`ra-context-fork` (`ra_context_harness.py`)**: Enforces **Read-Once $\rightarrow$ Fork-Many** snapshots (`BASE_FRAMEWORK`, `WORKFLOW_SLICE`, `TASK_EPHEMERAL`), **1-Concurrency Baton Relay**, **1 atomic task per R&D subagent**, and auto-eviction on SHA-256 hash drift across **OpenCode**, **Claude Code**, **Codex**, and **Antigravity/Gemini**. |
| **4. 30-Minute Trash Unit-Test Marathons** | Wastes 30 minutes running mocked `test_xyz.py` suites that pass in a synthetic bubble while the real deployment breaks or hangs. | **`ra-log-verify` (`ra_log_engine.py`)**: Bans synthetic unit tests; wires deployment code to `RALogger` (`Python`/`JS`/`TS`/`PHP`) logging `flow=caller->callee`, `inputs`, `state_before/after`, `delta`, `output`, `contract=BC-xxx`, and `[PASS]`/`[DECISION]`/`[STUCK]`/`[FAIL]` under a hard OS watchdog timer. |
| **5. Code-Context Visual Blindness & Ignored/Misfitted Provided Assets** | Reads CSS/HTML/shader code and claims *"UI looks great!"* while ignoring the user's provided assets/icons (substituting bare CSS boxes, emoji, or `placehold.co`), hallucinating broken asset paths, or squishing/stretching assets into the wrong container aspect ratio. | **`ra-visual-audit` (`ra_visual_audit.py`)**: Auto-discovers provided assets (`assets/`, `public/`, `icons/`, `sprites/`), extracts native `WxH` & aspect ratio (`W:H`), blocks ignored provided assets (`[IGNORED_PROVIDED_ASSETS]`) or broken asset paths (`[BROKEN_ASSET_PATH]`), verifies real screenshots (`>= 64x64`, Shannon entropy `>= 2.2`), and audits container fit in `VISUAL_AUDIT.md`. |
| **6. Missing Domain Knowledge / Unverified Equations** | Hallucinates domain APIs or math formulas when working in specialized domains instead of pulling verified skills, papers, or benchmark vectors. | **Optional R&D Crawler Suite (`ra_crawler.py`)**: On-demand when a project benefits from external knowledge — Priority #1: **Skill Crawler** (quarantine-audits & installs skills **project-locally** to `.claude/skills/` & `.agents/skills/`); Priority #2: **Paper Crawler** (arXiv & Semantic Scholar); Priority #3: **Data Crawler** (real test vectors). |
| **7. No Project-Specific Guardrails or Cold Review** | Uses generic prompts with no automated pre/post-edit hooks or independent reviewer to catch subtle regressions. | **`ra-anti-cheese` (`ra_forge.py`)**: Generates a custom project skill, executable `research/harness/project_harness.py` (CLI + Claude Code `PreToolUse`/`PostToolUse`/`Stop` hooks), and a cold-eyes `ra-reviewer` agent. |
| **8. The Boilerplate Reflex** | Forces textbook patterns onto novel ideas whose mechanics and connections are fundamentally different. | **First-Principles Mandate (Stage 2)**: Forbids pattern-matching; requires explicit mathematical/structural derivation and Pre-Edit/Pre-Creation justification in `REPORT.md` before coding. |
| **9. The "Hardcoded Data" Slippery Slope & Band-Aids** | Sees legitimate math/syntax symbols (like `=`) labeled `# hardcoded` and uses that as an excuse to dump lookup tables, `if input == X: return Y`, or `try/except: pass` band-aids when stuck. | **Axiom Seal + AST Cheese Auditor (`ra_cheese_audit.py`)**: Separates SHA-256 sealed `AXIOMATIC_PRIMITIVES` from forbidden data cheesing; fails immediately if tampered with. |
| **10. Misalignment & Lazy Repeat Questions** | Starts coding before aligning with the user, or asks the user the same question repeatedly instead of checking reference images and docs already on disk. | **`/ra-talk` + Pre-Question Gate (`check-question`)**: Scans `GLOSSARY.md`, `reference/`, `assets/`, and `REFERENCES_INDEX.md` first, then runs frontier grilling rounds and updates `GLOSSARY.md` inline. |

---

## The 8-Stage RA State Machine (When Running Full `/research-anything`)

Every full R&D track is deterministically governed by [`scripts/ra_gate.py`](./scripts/ra_gate.py):

```text
[STAGE 0: INTAKE_AND_SYNC] (/ra-talk)
  ├── Mandatory Pre-Question Search Gate (ra_gate.py check-question)
  ├── Frontier Grilling & Shared Language -> GLOSSARY.md, VISION_AND_MISSION.md & INVARIANTS.md
  ├── [Optional] R&D Crawler Suite (ra_crawler.py: 1. Skills -> 2. Papers -> 3. Data)
  └── Self-Forging Project Skill, .py Hooks & Review Agent (ra_forge.py)
       │
       ▼
[STAGE 1: WORKFLOW_AND_CONTEXT_MAPPING] (/ra-workflow-map & /ra-context-fork) ◄─┐
  ├── Full -N to +N hop trace & blast radius in research/WORKFLOW_MAP.md        │
  ├── Prove Culprit vs. Innocent Victim -> Lock PROTECTED_WORKING nodes         │
  ├── Lock Existing Behavioral Contracts (BC-001, BC-002...)                    │
  └── Create Read-Once Shared Context Snapshot (ra_context_harness.py create)   │
       │                                                                        │
       ▼                                                                        │
[STAGE 2: HYPOTHESIS_FORMULATION] ◄─────────────────────────────────────────────┤
  └── Culprit proof, Pre-Edit Justification & math formulation (REPORT.md)      │
       │                                                                        │
       ▼                                                                        │
[STAGE 3: SANDBOX_PROTOTYPE & CONTEXT FORKING] (/ra-context-fork)               │
  ├── Quarantined prototype inside research/sandbox/Hxxx_<slug>/                │
  ├── Fork shared snapshot to Subagents (opencode / claude / codex / agy)       │
  ├── 1-Concurrency Baton Relay + Return Baton with Subagent Report             │
  ├── Wire deployment telemetry via RALogger (ra_log_engine.py inject-sdk)      │
  └── Cryptographic SHA-256 sealing of legitimate AXIOMATIC_PRIMITIVES          │
       │                                                                        │
       ▼                                                                        │ (If FALSIFIED:
[STAGE 4: ADVERSARIAL_BREAK_TEST & REAL .LOG TELEMETRY] (/ra-log-verify)        │  Quarantine to
  ├── Execute real workflow under OS Watchdog (ra_log_engine.py run)            │  research/graveyard/,
  └── Audit .log for [PASS]/[DECISION]/[STUCK]/[FAIL] & BC-xxx contracts        │  log Self-Learning,
       │                                                                        │  keep main codebase
       ▼                                                                        │  100% clean, & loop
[STAGE 5: ANTI_CHEESE_AND_VISUAL_REALITY_AUDIT] (/ra-anti-cheese & /ra-visual)  │  up to 5x autonomously)
  ├── AST + regex scan for lookup tables, band-aids & axiom tampering           │
  └── User-Eyes Visual & Provided-Asset Fit Gate (ra_visual_audit.py)           │
       │                                                                        │
       ▼                                                                        │
[STAGE 6: LAB_REPORT_AND_LEARNING] ─────────────────────────────────────────────┘
  └── Provenance log (who/what/when) + Self-Learning triad (Issue:Workflow:Found)
       │
       ▼ (Only when PROVEN & Cheese-Free)
[STAGE 7: GRADUATION_REVIEW (Mandatory User Sign-Off)]
  ├── Run project_harness.py check-all & cold-eyes ra-reviewer audit
  └── Present Lab Report & wait for explicit User Sign-Off before merging
```

---

## CLI Reference (All 7 Deterministic Python Engines)

All engines work both in **Standalone / Partial Mode** (`--hypothesis STANDALONE`, auto-initializing `research/` lazily when needed) and in **Full 8-Stage Mode**:

### 1. `ra_gate.py` — State-Machine, Pre-Question & Workflow Snapshot Gatekeeper
```bash
# Mandatory Pre-Question Gate: scan GLOSSARY.md, reference/, assets/, docs/, and REFERENCES_INDEX.md
python scripts/ra_gate.py check-question --workspace .

# Stamp Stage 1 Workflow Map with tracked file hashes and PROTECTED_WORKING functions (auto-inits research/)
python scripts/ra_gate.py map-context --workspace . --agent "MAIN_ORCHESTRATOR" \
  --files "bot_pipeline.py" --protected "bot_pipeline.py:func_a_summon"

# Refresh context: print current stage, workflow staleness, protected nodes, BC-xxx, and INV-xxx
python scripts/ra_gate.py status --workspace .

# Start a new hypothesis, seal axioms, advance, conclude, or graduate
python scripts/ra_gate.py new-hypothesis --workspace . --id H001 --slug "retry_fix" --agent "MAIN_ORCHESTRATOR"
python scripts/ra_gate.py seal-axioms --workspace . --file "src/axioms.py"   # sandbox paths are refused
python scripts/ra_gate.py advance --workspace .
python scripts/ra_gate.py conclude --workspace . --verdict PROVEN \
  --issue "Upstream retry recovery cleared session dispatch ledger" \
  --workflow "User blamed downstream consumer func_a_summon; 2-hop trace isolated func_c" \
  --found "Transient retry state and session-once dispatch ledgers must remain orthogonal"
```

### 2. `ra_context_harness.py` — Multi-Platform `/fork` Controller, Baton & Handoff Engine
```bash
# Create a shared Read-Once context snapshot (BASE_FRAMEWORK, WORKFLOW_SLICE, or TASK_EPHEMERAL)
python scripts/ra_context_harness.py create --workspace . \
  --id "SNAP_WORKFLOW" --tier "WORKFLOW_SLICE" \
  --files "bot_pipeline.py" --summary "Compiled -2 to +2 hop workflow map and BC-001/BC-002 contracts"

# Fork the shared snapshot to Subagent_A (supports --platform auto|opencode|claude|codex|agy)
python scripts/ra_context_harness.py fork --workspace . \
  --snapshots "SNAP_WORKFLOW" --subagent "Subagent_A" \
  --task-type "REAL_RD" --platform "codex" \
  --task "Build isolated prototype in research/sandbox/H001_retry_fix/ and wire RALogger"

# Return the 1-concurrency baton after Subagent_A writes its report (auto-evicts hash-drifted snapshots)
python scripts/ra_context_harness.py return-baton --workspace . \
  --subagent "Subagent_A" --report-file "research/context_snapshots/reports/REPORT_Subagent_A.md"

# Write a portable cross-harness handoff document (Claude <-> Codex <-> OpenCode <-> AGY)
python scripts/ra_context_harness.py handoff --workspace . \
  --focus "Verify edge-case retry sequences" \
  --summary "Mapped workflow and isolated func_c ledger clear bug" \
  --suggested-skills "ra-systemic-debug" "ra-log-verify"
```

### 3. `ra_log_engine.py` — Production `.log` Spine, OS Watchdog & Flow Auditor
```bash
# Inject zero-dependency RALogger SDK (python, js, ts, or php)
python scripts/ra_log_engine.py inject-sdk --workspace . --lang python --dest "research/sandbox/STANDALONE"

# Run real workflow under a hard OS watchdog timer (defaults to --hypothesis STANDALONE)
python scripts/ra_log_engine.py run --workspace . --timeout-sec 60 --cmd "python app.py"

# Audit the generated .log file for [PASS]/[DECISION]/[STUCK]/[FAIL], variable deltas, and BC-xxx contracts
python scripts/ra_log_engine.py audit --workspace .
```

### 4. `ra_visual_audit.py` — User-Eyes Visual, Provided-Asset & Container-Fit Gate
```bash
# Scan provided workspace/sandbox assets, native WxH/aspect ratios, unused assets, and broken asset paths
python scripts/ra_visual_audit.py scan-assets --workspace .

# Initialize & audit User-Eyes Visual + Provided-Asset Fit Reality (verifies assets, dimensions & entropy >= 2.2)
python scripts/ra_visual_audit.py init --workspace .
python scripts/ra_visual_audit.py audit --workspace .
```

### 5. `ra_cheese_audit.py`, `ra_forge.py` & `ra_crawler.py` (Optional On-Demand Crawler)
```bash
# Scan code for axiom tampering, lookup tables, hardcoded branches, and band-aid exception swallowing
python scripts/ra_cheese_audit.py --workspace . --files "bot_pipeline.py"

# Forge project-local skill, research/harness/project_harness.py, .claude/settings.local.json hooks, & ra-reviewer
python scripts/ra_forge.py --workspace . --name "bot-pipeline" --domain "stateful-dispatch-pipeline"

# [Optional / On-Demand] Crawl domain skills (installed project-locally), papers, or benchmark test vectors
python scripts/ra_crawler.py skill --workspace . --query "game-development"
python scripts/ra_crawler.py paper --workspace . --query "monotonic state lattice"
python scripts/ra_crawler.py data --workspace . --query "json-test-suite"
```

---

## License

Released under the [MIT License](./LICENSE).
