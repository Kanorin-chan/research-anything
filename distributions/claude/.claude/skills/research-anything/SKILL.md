---
name: research-anything
description: >-
  First-principles autonomous R&D (Research & Development) and invention engine
  (RA) for zero-shot, zero-day, and brand-new algorithms, neural networks,
  architectures, frameworks, encryption, games, hardware/CPU layouts, materials,
  shapes, and complex systems. Enforces a strict Scientific Method state machine,
  autonomous domain Skill/Paper/Data crawling, custom project-local Skill +
  multi-harness `.py` hooks + Review Agent generation, full multi-hop workflow
  and blast-radius mapping before edits, innocent-function protection,
  adversarial breaking-case validation, anti-cheese axiom locking, clean-slate
  sandbox quarantine, root-cause pipe-replacement recovery, a ground-truth
  library firewall, and a zero-repeat question policy. Use whenever inventing
  novel mechanisms or building R&D projects where standard boilerplate fails.
metadata:
  short_name: RA
  version: "1.3.0"
---

# RA — Research Anything (Super-Skill & Composable Suite)

Use **RA (`research-anything`)** as either the **Full 8-Stage Autonomous R&D Super-Skill** OR invoke any of its **Composable Partial Skills** when you only need one part of the workflow (such as just talking through a project, mapping a multi-hop workflow, or fixing a hard bug from root cause without band-aids):

| Mode / Skill | When to Use | How It Runs |
| :--- | :--- | :--- |
| **`/ra-ask`** *(Router)* | Not sure which partial skill or flow fits your current situation. | Routes you to the right partial or full RA flow. |
| **`/ra-talk`** *(Conversation Only)* | **Just want to talk through the project**, sharpen a design, or align on domain language (`GLOSSARY.md` + `VISION_AND_MISSION.md`) without writing code yet. | Runs `ra_gate.py check-question`, then calls `"ra-grilling"` and `"ra-domain-modeling"`. |
| **`ra-systemic-debug`** (`/ra-debug`) | **Something is broken/slow**: diagnose and fix from root cause (`Symptom != Culprit`, `-N` to `+N` hop trace, real `.log` loop, **zero band-aids**). | Runs the 6-phase systemic root-cause debugger without forcing all 8 R&D stages. |
| **`ra-workflow-map`** (`/ra-map`) | **Only map context & blast radius**: trace `-N` to `+N` hops, lock `PROTECTED_WORKING` functions and `BC-xxx` behavioral contracts in `WORKFLOW_MAP.md`. | Runs Stage 1 mapping & SHA-256 file stamping (`ra_gate.py map-context`). |
| **`ra-context-fork`** (`/ra-fork`) | **Read-Once $\rightarrow$ Fork-Many snapshots, 1-concurrency baton, or portable `/handoff`** across **OpenCode**, **Claude Code**, **Codex**, and **Antigravity/Gemini**. | Drives `ra_context_harness.py` (`create`, `fork`, `return-baton`, `handoff`, `evict`). |
| **`ra-log-verify`** (`/ra-log`) | **Verify in the real environment via `.log` telemetry** (no 30-minute synthetic unit-test marathons). | Wires `RALogger` and runs `ra_log_engine.py run` + `audit`. |
| **`ra-visual-audit`** (`/ra-visual`) | **Verify real UI screenshots & provided-asset fit** (catch ignored assets, broken paths, or stretched aspect ratios). | Runs `ra_visual_audit.py scan-assets`, `init`, and `audit`. |
| **`ra-anti-cheese`** (`/ra-cheese`) | **Seal axioms, scan for hardcoded lookup tables/band-aids, or forge project hooks & `ra-reviewer`**. | Runs `ra_cheese_audit.py` and `ra_forge.py`. |
| **`research-anything`** *(Full Super-Skill)* | **Full 8-Stage zero-shot invention, novel algorithm/architecture/game/hardware R&D**. | Drives the complete `STAGE_0` $\rightarrow$ `STAGE_7` state machine via `ra_gate.py`. |

Standard AI coding fails on novel inventions and complex systems because models read only surface data, fix 1-hop symptoms without checking the downstream blast radius, mutate innocent working functions, pattern-match against training data ("boilerplate reflex"), write useless happy-path unit tests, slap duct-tape band-aids over bugs, or sneak hardcoded data ("cheese") into the system when stuck. **RA overrides those reflexes with a strict, state-machine-enforced Scientific Method.**

---

## Core Mindset: The Scientist Protocol

1. **Whole-Context & Multi-Hop Understanding Before Action**: Never read only *what* the user wants and skim surface data or immediate neighbors. Map the entire end-to-end workflow, state lifecycle, and multi-hop blast radius before proposing any edit or new function.
2. **Anti-Boilerplate & First-Principles Invention**: Never force textbook templates onto a novel idea whose connections and mechanics differ. Derive equations, data structures, state transitions, and geometries directly from the raw constraints of the user's idea.
3. **Disproving a Hypothesis IS Progress**: Writing a hypothesis that turns out to be wrong is not a failure—provided you prove *why* it failed with trusted empirical data. Falsification narrows the search space.
4. **"Unsolvable" = Signal to Invent**: Hitting a wall where known techniques fail is not a stopper. It is the trigger to hypothesize a new mathematical function, transformation, state machine, or representation and test toward it.
5. **Truth Over Speed**: Looping across multiple hypotheses to discover a genuine, mathematically/structurally sound mechanism always beats writing fragile or faked code in one pass.

---

## Lead-Orchestrator Delegation, `/fork` Context Controlling & Snapshot Eviction

To prevent the Main Agent's context window from bloating and decaying during deep R&D:

1. **Main Agent = Lead Orchestrator & Compiler (Whenever Subagents Exist)**:
   - The Main Agent compiles data, manages the state machine, controls context snapshots, distributes tasks, and waits for reports.
   - **Always Delegate (Even at 1-Concurrency)**: On local or single-concurrency setups where only 1 model runs at a time, use a strict **1-Concurrency Baton-Pass Relay**:
     `Main Agent prepares snapshot & task` $\rightarrow$ `Main Agent waits (idle)` $\rightarrow$ `Subagent runs alone, finishes report & pauses/stops` $\rightarrow$ `Main Agent wakes up, verifies report, and passes next baton`.
2. **Expect Subagents to Drift (Zero-Trust Supervision)**:
   - Never blindly trust a subagent's report. Verify every subagent deliverable with `project_harness.py check-all`, `ra_cheese_audit.py`, and the forged `ra-reviewer` agent.
3. **Prevent Long-Context Subagents (Task-Sizing Rule)**:
   - **Real R&D / Logic / Bug-Fix Tasks (`REAL_RD`)**: Strictly **1 atomic task per subagent** (never dump 7 tasks onto 1 subagent).
   - **Small Surface Tweaks (`TRIVIAL_BATCH`)**: Small cosmetic/surface tasks (*change CSS, swap icon, update text/labels*) can be batched together in a single subagent run.
4. **Read Once $\rightarrow$ Fork Many (`/fork` Shared Context Snapshots Across `opencode`, `claude`, `codex`, and `agy`)**:
   - First-class platform support is built into `ra_context_harness.py` (`--platform auto|opencode|claude|codex|agy`):
     - **`opencode`**: Generates `opencode run --session <id> --fork --title "<subagent>"` or standalone `-f research/context_snapshots/forks/FORK_<subagent>.md` dispatches.
     - **`claude` (`claude-code`)**: Generates `claude --resume <id> --fork-session` and native `Task(subagent_type="general-purpose", ...)` dispatches.
     - **`codex`**: Generates `codex exec resume <id> --full-auto` and `codex exec --full-auto` dispatches.
     - **`agy` (`antigravity` / `gemini`)**: Generates `invoke_subagent(TypeName="self", Role="...", Prompt="...")` dispatches.
   - When `Subagent_A` and `Subagent_B` need the same framework/workflow context (e.g., both working on a Laravel subsystem), read and compile the context **once** into a snapshot (`ra_context_harness.py create`), then **fork** it (`ra_context_harness.py fork`) into `Subagent_A` and `Subagent_B` so neither re-reads the codebase from scratch.
5. **3-Tier Snapshot Retention & Throw-Away (Eviction) Harness (`scripts/ra_context_harness.py`)**:
   - **`BASE_FRAMEWORK` (Tier 1)**: Domain/framework rules, `INVARIANTS.md`, crawled skills. Kept across the track; thrown away only when invariants or framework configs change.
   - **`WORKFLOW_SLICE` (Tier 2)**: Subsystem `-N` to `+N` hop map, `PROTECTED_WORKING` nodes, `BC-xxx` contracts, and file SHA-256 hashes. Forked across sibling subagents; **thrown away immediately** on `HASH_DRIFT` (any tracked file edited), `MAX_REUSE_EXCEEDED`, or `TTL_EXPIRED`.
   - **`TASK_EPHEMERAL` (Tier 3)**: 1-task delta (`max_reuses = 1`). **Thrown away immediately** after 1 fork or if the subagent fails/drifts.
   - **Hard Gate**: `ra_gate.py advance` blocks leaving Stage 1 without an active `BASE_FRAMEWORK` or `WORKFLOW_SLICE` snapshot, and blocks leaving Stage 3 unless at least one subagent fork (`ra_context_harness.py fork`) and 1-concurrency baton return (`ra_context_harness.py return-baton`) have completed.
   - Read [subagent context and forking rules](references/subagent-context-and-forking.md).

---

## Mandatory Rule: Never Skip Steps (Run the RA Gatekeeper)

To prevent context drift and attention decay during long sessions, **you must not rely on memory to track the research workflow**. You must drive every project through the RA CLI state-machine gatekeeper (`scripts/ra_gate.py`).

At the start of every session and before transitioning between any stage, run:

```bash
python "~/.claude/skills/research-anything/scripts/ra_gate.py" status --workspace "."
```

Every time `ra_gate.py` runs, it echoes **the active stage instructions**, **Workflow Map staleness warnings**, **Protected Working Nodes**, **Existing Behavioral Contracts (`BC-xxx`)**, and **Locked Project Invariants (`INV-xxx`)** to the bottom of your terminal output so you never lose sight of past decisions.

---

## The 8-Stage RA State Machine

```text
[STAGE 0: INTAKE_AND_SYNC]
       │
       ▼
[STAGE 1: WORKFLOW_AND_CONTEXT_MAPPING] ◄──────────┐
       │                                           │
       ▼                                           │
[STAGE 2: HYPOTHESIS_FORMULATION] ◄────────────────┤
       │                                           │
       ▼                                           │
[STAGE 3: SANDBOX_PROTOTYPE]                       │
       │                                           │
       ▼                                           │
[STAGE 4: ADVERSARIAL_BREAK_TEST]                  │ (Falsified -> Clean Revert,
       │                                           │  Log to Graveyard & Self-Learn,
       ▼                                           │  Re-verify Context Map &
[STAGE 5: ANTI_CHEESE_AUDIT]                       │  Spawn Next Hypothesis)
       │                                           │
       ▼                                           │
[STAGE 6: LAB_REPORT_AND_LEARNING] ────────────────┘
       │
       ▼ (Only when PROVEN & Cheese-Free)
[STAGE 7: GRADUATION_REVIEW (User Sign-Off)]
```

### Stage 0: Conversational Intake, R&D Crawler Suite, Project Skill/Harness Forge & Sync
- **Look Before You Ask (Zero-Repeat Question Gate)**: Before asking the user *any* question, run `ra_gate.py check-question` and search `research/VISION_AND_MISSION.md`, `research/INVARIANTS.md`, `research/WORKFLOW_MAP.md`, `research/library/REFERENCES_INDEX.md`, `research/SELF_LEARNING.md`, and all `reference/`, `references/`, `assets/`, and `docs/` folders (including opening and viewing images/diagrams). **Never ask the user a question that is already answered in a reference image, file, or past report, or that can be answered by running a test.**
- **1-by-1 Idea Intake**: If starting a new project or major idea, let the user talk through their thoughts 1-by-1. Synthesize them into `research/VISION_AND_MISSION.md` and lock core constraints in `research/INVARIANTS.md`. Read [intake and library rules](references/intake-and-library.md).
- **Autonomous R&D Crawler Suite (`scripts/ra_crawler.py` — Optional / On-Demand)**: Not every project needs external skills, papers, or datasets. When entering an unfamiliar domain or when external formulations/test vectors are helpful, equip the workspace in priority order:
  1. **Priority #1 — Skill Crawler (`ra_crawler.py skill`)**: Automatically search GitHub and skill registries for domain skills the AI needs (e.g., Game Development, Shaders, Rust, Cryptography), audit them in quarantine, and install them **strictly project-locally** (`.claude/skills/` and `.agents/skills/`—never polluting global skills):
     ```bash
     python "~/.claude/skills/research-anything/scripts/ra_crawler.py" skill --workspace "." --query "<domain-or-skill>"
     ```
  2. **Priority #2 — Research Paper Crawler (`ra_crawler.py paper`)**: Crawl arXiv and Semantic Scholar for peer-reviewed formulations and index them in `research/library/PAPERS_<slug>.md` (`[EXTERNAL_VERIFIED_LAW]`).
  3. **Priority #3 — Data & Test-Vector Crawler (`ra_crawler.py data`)**: Crawl real-world test vectors and benchmark datasets into `research/arsenal/data/` so Stage 4 break-tests use real data.
- **Self-Forging Project Skill, `.py` Harness/Hooks & Review Agent (`scripts/ra_forge.py`)**: If needed (or once project rules are locked), generate a custom project-local skill, executable Python harness (`research/harness/project_harness.py`), Claude Code hooks (`.claude/settings.local.json`), and a dedicated Adversarial Review Agent (`.claude/agents/ra-reviewer.md` & `.agents/workflows/ra-review.md`):
  ```bash
  python "~/.claude/skills/research-anything/scripts/ra_forge.py" --workspace "." --name "<project-slug>" --domain "<domain>"
  ```
  Read [crawler and skill forge rules](references/crawler-and-skill-forge.md).
- **Mandatory Past-Record Check**: Read `research/WORKFLOW_MAP.md`, `research/LAB_LOG.md`, `research/SELF_LEARNING.md`, and `research/graveyard/` before proposing any hypothesis so you never repeat a falsified dead end.
- **Zero-Trust Comment Rule**: Never blindly trust bare comments in existing code or docs (e.g., `# this source is untrusted` or `# doesn't work`). A claim is only trusted if backed by a Lab Report with exact reproduction evidence and root-cause proof.

### Stage 1: Workflow, Context & Blast-Radius Mapping (`research/WORKFLOW_MAP.md`)
- **Go Beyond Surface Data & 1-Hop Relatives**: Never inspect only the blocked line/function and its immediate neighbor. Trace the full multi-hop workflow (`Upstream Producers -> Shared State/Counters -> Target Node -> Downstream Consumers -> Multi-Cycle Loopback`) and record it in `research/WORKFLOW_MAP.md`.
- **Prove Culprit vs. Innocent Victim (`Symptom != Culprit`)**: Even if the user says *"Function A looks buggy"*, never blindly mutate `Function A`. Verify whether `Function A` is actually working properly and receiving bad state from `Function C`. Mark innocent working functions as **`PROTECTED_WORKING`** (`ra_gate.py map-context --protected module.py:func_a`) so they are **never modified** while fixing `Function C`.
- **Lock Existing Behavioral Contracts (`BC-xxx`)**: List all existing working behaviors connected to the flow (e.g., *"Action/Resource X must execute at most once per cycle"*) so fixing one issue never triggers a secondary whack-a-mole regression elsewhere.
- **Pre-Edit / Pre-Creation Justification Gate**: Explicitly write down in `research/WORKFLOW_MAP.md` (and `REPORT.md`):
  1. **WHAT** you are editing or creating (and what is `PROTECTED_WORKING`).
  2. **WHY** edit this exact node (proof of root cause).
  3. **WHY** create a new function/module (proof no existing function in the workflow map already owns this responsibility).
  4. **WHAT** the $N$-hop blast radius is across the full workflow loop.
- **Persistent Context Map with AI-Session Staleness Warning**: Record the map in `research/WORKFLOW_MAP.md` and stamp it via:
  ```bash
  python "~/.claude/skills/research-anything/scripts/ra_gate.py" map-context --agent "<agent-id>" --files <file1> <file2> --protected <module:func>
  ```
  Future agents read `WORKFLOW_MAP.md` so they do not need to re-discover the codebase from scratch, while `ra_gate.py status` warns them that the map is an **AI session snapshot** and flags any files whose SHA-256 hashes have been altered since the snapshot.
- **Create Read-Once Shared Context Snapshot (`ra_context_harness.py create`)**: Before advancing to Stage 2, compile the workflow context once so downstream subagents can fork from it without re-reading the codebase:
  ```bash
  python "~/.claude/skills/research-anything/scripts/ra_context_harness.py" create --workspace "." --id "SNAP_WORKFLOW" --tier "WORKFLOW_SLICE" --files <file1> <file2> --summary "<workflow-summary>"
  ```
- Read [workflow and context mapping rules](references/workflow-and-context-mapping.md).

### Stage 2: Hypothesis Formulation (`research/hypotheses/Hxxx_<slug>/`)
- Create a new hypothesis via:
  ```bash
  python "~/.claude/skills/research-anything/scripts/ra_gate.py" new-hypothesis --id H001 --slug "<short-name>" --agent "<agent-or-session-id>" --parent "NONE"
  ```
- Complete both **Section 2 (Workflow Context, Culprit Proof & Pre-Edit/Pre-Creation Justification)** and **Section 3 (First-Principles Mathematical/Structural Formulation, Assumptions & Failure Boundaries)** in `research/hypotheses/Hxxx_<slug>/REPORT.md`.

### Stage 3: Quarantined Sandbox Prototype, Context Forking & Production `.log` Wiring (`research/sandbox/Hxxx_<slug>/`)
- **Protect the Main Codebase & Protected Nodes from Poisoning**: Build and test the prototype inside `research/sandbox/Hxxx_<slug>/` (or an isolated git branch/snapshot). Never pile unverified experiment code onto the main codebase, and never touch `PROTECTED_WORKING` functions.
- **Mandatory Subagent Context Fork & 1-Concurrency Baton Relay (`scripts/ra_context_harness.py`)**:
  - Fork the shared Stage 1 context snapshot (`WORKFLOW_SLICE` / `BASE_FRAMEWORK`) into an atomic subagent task (`REAL_RD` = strictly 1 task per subagent; `TRIVIAL_BATCH` = small surface tweaks only) across `opencode`, `claude`, or `agy`:
    ```bash
    python "~/.claude/skills/research-anything/scripts/ra_context_harness.py" fork --workspace "." --id "SNAP_WORKFLOW" --subagent "Subagent_A" --task-type "REAL_RD" --platform "auto" --tasks "<single-atomic-task>"
    ```
  - Once the subagent completes its work and writes its report (`research/context_snapshots/reports/REPORT_Subagent_A.md`), return the 1-concurrency baton (which also auto-evicts any snapshots whose tracked files changed via `HASH_DRIFT`):
    ```bash
    python "~/.claude/skills/research-anything/scripts/ra_context_harness.py" return-baton --workspace "." --subagent "Subagent_A" --status "COMPLETED" --report "research/context_snapshots/reports/REPORT_Subagent_A.md"
    ```
- **Mandatory Production `.log` Spine (`scripts/ra_log_engine.py`)**:
  - **Treat all prototype and production code as real deployment code**: Silent code, bare `print("ok")` statements, and isolated synthetic unit tests are **banned**.
  - Wire every function, branch decision, and state transition to `RALogger` (`ra_log_engine.py inject-sdk --lang <python|js|ts|php>`) so every hop emits structured `.log` records containing:
    `flow=caller->callee`, functional `role`, exact runtime `inputs`, `state_before`, `state_after`, `delta`, `output`, `contract=BC-xxx`, `elapsed_ms`, and status (`[PASS]`, `[DECISION]`, `[STUCK]`, or `[FAIL]`).
- **Axiomatic Primitives vs. Hardcoded Cheese**:
  - Legitimate mathematical/structural constants (e.g., operator symbols like `=`, physical constants, dimensional laws, core formulas) must be placed in a dedicated `axioms` module and sealed with `ra_gate.py seal-axioms`.
  - Never label legitimate axioms as `# hardcoded data`.
  - Read [anti-cheese and recovery rules](references/anti-cheese-and-recovery.md).

### Stage 4: Real-Environment `.log` Telemetry, Watchdog & Boundary Verification
- **Trash Synthetic Unit-Test Marathons Are Banned**: Never waste 30 minutes writing or running mocked unit tests (`test_xyz.py`) that pass in an isolated bubble while the real system breaks.
- **Execute in the Real Environment with a Hard Watchdog & Audit the `.log` (`scripts/ra_log_engine.py`)**:
  1. Run the real workflow under a hard watchdog timer (preventing 30-minute hangs and automatically logging `[STUCK]` with live variable state if any step stalls):
     ```bash
     python "~/.claude/skills/research-anything/scripts/ra_log_engine.py" run --workspace "." --hypothesis "Hxxx_<slug>" --timeout-sec 60 --cmd "<real-run-cmd>"
     ```
  2. Audit the generated `.log` file to verify every hop's `[PASS]` functional + value telemetry, zero `[STUCK]`/`[FAIL]` states, and 100% of Existing Behavioral Contracts (`BC-xxx`):
     ```bash
     python "~/.claude/skills/research-anything/scripts/ra_log_engine.py" audit --workspace "." --hypothesis "Hxxx_<slug>"
     ```
- Read [real-environment log and boundary verification rules](references/adversarial-verification.md).
- Once any `[STUCK]` or `[FAIL]` boundary is found in the `.log`, **build structural prevention** into the upstream mechanism—never slap an `if/else` band-aid on the symptom.

### Stage 5: Automated Anti-Cheese, Axiom & User-Eyes Visual Reality Audit
- Run both automated auditors before concluding any hypothesis:
  ```bash
  python "~/.claude/skills/research-anything/scripts/ra_cheese_audit.py" --workspace "." --hypothesis "Hxxx_<slug>"
  python "~/.claude/skills/research-anything/scripts/ra_visual_audit.py" audit --workspace "." --hypothesis "Hxxx_<slug>"
  ```
- **Anti-Cheese Auditor (`ra_cheese_audit.py`)** scans for:
  1. Tampering with sealed `AXIOMATIC_PRIMITIVES`.
  2. Suspicious lookup tables, hardcoded output dicts/lists, or specific-value `if input == X: return Y` branches inside algorithmic/model code.
  3. Band-aid symptom suppression (`try/except: pass`, arbitrary `clamp`/`nan_to_num` masking upstream corruption).
  4. Poison/lazy comments (`# hardcoded`, `# hack`, `# temporary`, `# workaround`, `# untrusted` without evidence).
- **User-Eyes Visual, Provided-Asset & Experiential Reality Auditor (`ra_visual_audit.py`)**:
  - Whenever visual, UI, CSS, game, shader, or chart files are touched, **never trust code/DOM context alone**.
  - **Detect & Fit Provided Assets (`ra_visual_audit.py scan-assets`)**: Automatically scans workspace/sandbox asset folders (`assets/`, `public/`, `static/`, `icons/`, `images/`, `sprites/`, `reference/`) for provided assets, extracts their native `WxH` dimensions and aspect ratios (`W:H`), and blocks the stage if the AI ignored the provided assets (`[IGNORED_PROVIDED_ASSETS]`), hallucinated broken asset paths (`[BROKEN_ASSET_PATH]`), or used dummy placeholder URLs (`placehold.co`).
  - Capture real screenshots into `research/sandbox/Hxxx_<slug>/visual_captures/`, open and inspect every screenshot with your vision tool (`read_file`), and interrogate the pixels from the **User's View** in `VISUAL_AUDIT.md` (checking for wrong CSS alignment, misfitted/stretched provided assets or icons, displaced data, unloaded assets, and wrong function/image display).
  - Read [visual and user-perspective validation rules](references/visual-and-user-perspective-validation.md).

### Stage 6: Lab Report, Clean-Slate Recovery & Self-Learning
- Record raw trusted data, provenance (`Agent/Session ID`, `Timestamp`, `Parent Hypothesis`, `Files Touched`), and the final verdict (`PROVEN` or `FALSIFIED`) in `research/hypotheses/Hxxx_<slug>/REPORT.md` and `research/LAB_LOG.md`.
- **Every mistake or falsification must log a Self-Learning triad** in `research/SELF_LEARNING.md`:
  - **`Issue`**: What broke or failed.
  - **`Workflow`**: Where the reasoning, context mapping, assumption, or testing process fell short.
  - **`Found`**: The permanent rule or mathematical constraint discovered for all future hypotheses.
- **If `FALSIFIED`**:
  - Archive the sandbox experiment to `research/graveyard/Hxxx_<slug>/` with exact proof of *why* it failed and *when* it should not be used.
  - Ensure the main codebase remains 100% clean and unpoisoned.
  - Loop autonomously back to **Stage 1/2** to re-verify the workflow map and formulate the next hypothesis (up to **5 consecutive falsified hypotheses** on the same sub-problem before pausing to consult the user, or immediately if a core contradiction in `VISION_AND_MISSION.md` is proven).

### Stage 7: Review Agent Audit & Graduation Review (Mandatory User Sign-Off)
- **Run Project Harness & Dedicated Review Agent First**: Execute `python research/harness/project_harness.py check-all` and run the forged **Review Agent** (`.claude/agents/ra-reviewer.md` / `research/harness/REVIEW_AGENT_PROMPT.md`) to cold-audit the diff against `WORKFLOW_MAP.md`, `PROTECTED_WORKING` nodes, and `BC-xxx` behavioral contracts.
- **Never merge a proven hypothesis from the sandbox into the main project silently.**
- Even when a hypothesis passes all adversarial breaking tests, behavioral contract checks, `ra_cheese_audit.py`, and the Review Agent audit, present the **Lab Report summary, N-hop blast-radius verification, and architectural approach** to the user first.
- Wait for the user's explicit sign-off before graduating the mechanism into the main codebase and recording verified discoveries into `research/library/`.

---

## Bug & Regression Protocol: Pipe Replacement (No Band-Aids, No Whack-a-Mole)

When a bug is discovered in existing code or reported by the user:
1. **Do NOT put tape over a leaking pipe**: Adding a local guard (`if x is None`, `try/except`, arbitrary clamping, or extra boolean flags) at the crash site is strictly forbidden.
2. **Prove Culprit vs. Victim (`Stage 1`)**: Trace the full multi-hop workflow in `research/WORKFLOW_MAP.md`. Identify which upstream architectural invariant or equation allowed the invalid state to exist, and lock innocent working functions as `PROTECTED_WORKING` so you never break working code while fixing the culprit.
3. **Quarantine & Re-Derive**: Open a recovery hypothesis in `research/hypotheses/`, rip out the flawed mechanism cleanly, replace the pipe from first principles, and prove zero regressions across all existing behavioral contracts (`BC-xxx`).
