---
name: research-anything
description: >-
  First-principles autonomous R&D and invention engine (RA) for zero-shot,
  zero-day, and brand-new algorithms, neural networks, architectures, frameworks,
  encryption, games, hardware/CPU layouts, materials, shapes, and complex systems.
  Enforces a strict Scientific Method state machine, adversarial breaking-case
  validation, anti-cheese axiom locking, clean-slate sandbox quarantine, root-cause
  pipe-replacement recovery, a ground-truth library firewall, and a zero-repeat
  question policy. Use whenever inventing novel mechanisms or solving problems
  where standard boilerplate fails.
metadata:
  short_name: RA
  version: "1.0.0"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash"
---

# RA — Research Anything

Use **RA (`research-anything`)** when tackling a novel idea, zero-shot/zero-day problem, brand-new algorithm, neural network architecture, custom encryption, game system, hardware/CPU layout, material model, or geometric/system design where standard off-the-shelf boilerplate fails.

Standard AI coding fails on novel inventions because models try to pattern-match against training data ("boilerplate reflex"), write useless happy-path unit tests, slap duct-tape band-aids over bugs, or sneak hardcoded data ("cheese") into the system when stuck. **RA overrides those reflexes with a strict, state-machine-enforced Scientific Method.**

---

## Core Mindset: The Scientist Protocol

1. **Anti-Boilerplate & First-Principles Invention**: Never force textbook templates onto a novel idea whose connections and mechanics differ. Derive equations, data structures, state transitions, and geometries directly from the raw constraints of the user's idea.
2. **Disproving a Hypothesis IS Progress**: Writing a hypothesis that turns out to be wrong is not a failure—provided you prove *why* it failed with trusted empirical data. Falsification narrows the search space.
3. **"Unsolvable" = Signal to Invent**: Hitting a wall where known techniques fail is not a stopper. It is the trigger to hypothesize a new mathematical function, transformation, state machine, or representation and test toward it.
4. **Truth Over Speed**: Looping across multiple hypotheses to discover a genuine, mathematically/structurally sound mechanism always beats writing fragile or faked code in one pass.

---

## Mandatory Rule: Never Skip Steps (Run the RA Gatekeeper)

To prevent context drift and attention decay during long sessions, **you must not rely on memory to track the research workflow**. You must drive every project through the RA CLI state-machine gatekeeper (`scripts/ra_gate.py`).

At the start of every session and before transitioning between any stage, run:

```bash
python "~/.claude/skills/research-anything/scripts/ra_gate.py" status --workspace "."
```

Every time `ra_gate.py` runs, it echoes **only the active stage instructions** and all **Locked Project Invariants (`INVARIANTS.md`)** to the bottom of your terminal output so you never lose sight of past decisions.

---

## The 7-Stage RA State Machine

```text
[STAGE 0: INTAKE_AND_SYNC]
       │
       ▼
[STAGE 1: HYPOTHESIS_FORMULATION] ◄───────────────┐
       │                                          │
       ▼                                          │
[STAGE 2: SANDBOX_PROTOTYPE]                      │
       │                                          │
       ▼                                          │
[STAGE 3: ADVERSARIAL_BREAK_TEST]                 │ (Falsified -> Clean Revert,
       │                                          │  Log to Graveyard & Self-Learn,
       ▼                                          │  Spawn Next Hypothesis)
[STAGE 4: ANTI_CHEESE_AUDIT]                      │
       │                                          │
       ▼                                          │
[STAGE 5: LAB_REPORT_AND_LEARNING] ───────────────┘
       │
       ▼ (Only when PROVEN & Cheese-Free)
[STAGE 6: GRADUATION_REVIEW (User Sign-Off)]
```

### Stage 0: Conversational Intake, Asset Indexing & Past-Record Sync
- **Look Before You Ask (Zero-Repeat Question Gate)**: Before asking the user *any* question, run `ra_gate.py check-question` and search `research/VISION_AND_MISSION.md`, `research/INVARIANTS.md`, `research/library/REFERENCES_INDEX.md`, `research/SELF_LEARNING.md`, and all `reference/`, `references/`, `assets/`, and `docs/` folders (including opening and viewing images/diagrams). **Never ask the user a question that is already answered in a reference image, file, or past report, or that can be answered by running a test.**
- **1-by-1 Idea Intake**: If starting a new project or major idea, let the user talk through their thoughts 1-by-1. Synthesize them into `research/VISION_AND_MISSION.md` and lock core constraints in `research/INVARIANTS.md`. Read [intake and library rules](references/intake-and-library.md).
- **Mandatory Past-Record Check**: Read `research/LAB_LOG.md`, `research/SELF_LEARNING.md`, and `research/graveyard/` before proposing any hypothesis so you never repeat a falsified dead end.
- **Zero-Trust Comment Rule**: Never blindly trust bare comments in existing code or docs (e.g., `# this source is untrusted` or `# doesn't work`). A claim is only trusted if backed by a Lab Report with exact reproduction evidence and root-cause proof.

### Stage 1: Hypothesis Formulation (`research/hypotheses/Hxxx_<slug>/`)
- Create a new hypothesis via:
  ```bash
  python "~/.claude/skills/research-anything/scripts/ra_gate.py" new-hypothesis --id H001 --slug "<short-name>" --agent "<agent-or-session-id>" --parent "NONE"
  ```
- Define the explicit mathematical, structural, physical, or algorithmic hypothesis, its assumptions, invariants, and predicted failure boundaries in `research/hypotheses/Hxxx_<slug>/REPORT.md`.

### Stage 2: Quarantined Sandbox Prototype (`research/sandbox/Hxxx_<slug>/`)
- **Protect the Main Codebase from Poisoning**: Build and test the prototype inside `research/sandbox/Hxxx_<slug>/` (or an isolated git branch/snapshot). Never pile unverified experiment code directly onto the main codebase.
- **Axiomatic Primitives vs. Hardcoded Cheese**:
  - Legitimate mathematical/structural constants (e.g., operator symbols like `=`, physical constants, dimensional laws, core formulas) must be placed in a dedicated `axioms` module and sealed with `ra_gate.py seal-axioms`.
  - Never label legitimate axioms as `# hardcoded data`.
  - Read [anti-cheese and recovery rules](references/anti-cheese-and-recovery.md).

### Stage 3: Adversarial & Boundary Verification (Red-Teaming Your Own Invention)
- **Happy-Path Unit Tests Are Banned**: Making a prototype pass a toy test does *not* mean it works.
- You must write and execute an adversarial breaking test (`break_test.*`) designed specifically to **destroy** your prototype and map its failure boundary:
  - **ML / Neural Networks**: Extreme gradients (vanishing/exploding), non-stationary/out-of-distribution inputs, adversarial perturbations, degenerate loss landscapes, zero/infinite weights, long-horizon drift.
  - **Algorithms / Games / Systems**: Pathological edge topologies, concurrency/state desynchronization, scale spikes, floating-point accumulation drift over $10^4+$ steps.
  - **Encryption / Security**: Avalanche effect verification, statistical bias/entropy tests, collision/differential probing.
  - **Hardware / CPU / Materials / Shapes**: Thermal/power boundary spikes, geometric singularity/degeneracy stresses, tolerance stack-up extremes.
- Read [adversarial verification playbooks](references/adversarial-verification.md).
- Once the breaking boundary is found, **build structural prevention** into the core equation/architecture—never slap an `if/else` band-aid on the symptom.

### Stage 4: Automated Anti-Cheese & Axiom Audit
- Run the automated auditor before concluding any hypothesis:
  ```bash
  python "~/.claude/skills/research-anything/scripts/ra_cheese_audit.py" --workspace "." --hypothesis "Hxxx_<slug>"
  ```
- The auditor scans for:
  1. Tampering with sealed `AXIOMATIC_PRIMITIVES`.
  2. Suspicious lookup tables, hardcoded output dicts/lists, or specific-value `if input == X: return Y` branches inside algorithmic/model code.
  3. Band-aid symptom suppression (`try/except: pass`, arbitrary `clamp`/`nan_to_num` masking upstream corruption).
  4. Poison/lazy comments (`# hardcoded`, `# hack`, `# temporary`, `# workaround`, `# untrusted` without evidence).

### Stage 5: Lab Report, Clean-Slate Recovery & Self-Learning
- Record raw trusted data, provenance (`Agent/Session ID`, `Timestamp`, `Parent Hypothesis`, `Files Touched`), and the final verdict (`PROVEN` or `FALSIFIED`) in `research/hypotheses/Hxxx_<slug>/REPORT.md` and `research/LAB_LOG.md`.
- **Every mistake or falsification must log a Self-Learning triad** in `research/SELF_LEARNING.md`:
  - **`Issue`**: What broke or failed.
  - **`Workflow`**: Where the reasoning, assumption, or testing process fell short.
  - **`Found`**: The permanent rule or mathematical constraint discovered for all future hypotheses.
- **If `FALSIFIED`**:
  - Archive the sandbox experiment to `research/graveyard/Hxxx_<slug>/` with exact proof of *why* it failed and *when* it should not be used.
  - Ensure the main codebase remains 100% clean and unpoisoned.
  - Loop autonomously to **Stage 1** with a new hypothesis (up to **5 consecutive falsified hypotheses** on the same sub-problem before pausing to consult the user, or immediately if a core contradiction in `VISION_AND_MISSION.md` is proven).

### Stage 6: Graduation Review (Mandatory User Sign-Off)
- **Never merge a proven hypothesis from the sandbox into the main project silently.**
- Even when a hypothesis passes all adversarial breaking tests and `ra_cheese_audit.py`, present the **Lab Report summary, behavioral characteristics, and architectural approach** to the user first.
- Wait for the user's explicit sign-off before graduating the mechanism into the main codebase and recording verified discoveries into `research/library/`.

---

## Bug & Regression Protocol: Pipe Replacement (No Band-Aids)

When a bug is discovered in existing code or reported by the user:
1. **Do NOT put tape over a leaking pipe**: Adding a local guard (`if x is None`, `try/except`, arbitrary clamping, or extra boolean flags) at the crash site is strictly forbidden.
2. **Trace Upstream**: Identify which upstream architectural invariant or mathematical equation allowed the invalid state to exist.
3. **Quarantine & Re-Derive**: Open a recovery hypothesis in `research/hypotheses/`, rip out the flawed mechanism cleanly, and replace the pipe from first principles.
