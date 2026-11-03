# RA — Research Anything (`research-anything`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-None%20(Stdlib)-brightgreen.svg)](#)
[![Agents](https://img.shields.io/badge/Agents-Claude%20Code%20%7C%20Antigravity%20%7C%20Gemini%20CLI%20%7C%20Cursor%20%7C%20Codex-purple.svg)](#installation)

**RA (`research-anything`)** is a first-principles autonomous R&D and invention skill for AI coding and research agents (**Claude Code**, **Google Antigravity**, **Gemini CLI**, **Cursor**, **Codex**, and Open-Standard Agent Skills).

It is purpose-built for **zero-shot, zero-day, and brand-new inventions** where standard pre-trained boilerplate does not exist or fails:
- **Novel Machine Learning & Neural Network Architectures** (new loss functions, attention/gating mechanisms, non-backprop learning rules)
- **Brand-New Algorithms, Data Structures & Frameworks**
- **Custom Cryptography, Hashing & Security Primitives**
- **Complex Game Engines & Emergent Simulation Mechanics**
- **Hardware / CPU Re-Positioning, Thermal & Routing Layouts**
- **Material Science, Lab Data Modeling & Physical Systems**
- **Geometric Redesigns, Mathematical Shapes & Topology**

---

## Why Standard AI Agents Fail at Real R&D

When you ask an LLM to build something genuinely new, six predictable failure modes destroy the project:

| Failure Mode | What Standard AI Agents Do | How **RA (`research-anything`)** Solves It |
| :--- | :--- | :--- |
| **1. The Boilerplate Reflex** | Forces textbook patterns onto novel ideas whose mechanics and connections are fundamentally different. | **First-Principles Mandate**: Forbids pattern-matching; requires explicit mathematical/structural derivation in `REPORT.md` before coding. |
| **2. Useless "Unit Tests"** | Writes happy-path assertions (`assert out.shape == (4, 8)`) that confirm its own broken assumptions. | **Stage 3 Adversarial Break-Testing**: Bans happy-path tests; forces red-team stress sweeps to find the exact failure boundary and build structural prevention. |
| **3. Attention Decay (Step-Skipping)** | Follows instructions for 10 turns, then forgets earlier decisions and reverts to lazy shortcuts. | **Deterministic CLI Gatekeeper (`ra_gate.py`)**: Locks state on disk and echoes **Locked Project Invariants** + **Active Stage Rules** at the bottom of the terminal on every step. |
| **4. The "Hardcoded Data" Slippery Slope** | Sees legitimate math/syntax symbols (like `=`) labeled `# hardcoded` and uses that as an excuse to dump lookup tables or hardcoded answers when stuck. | **Axiom Seal + AST Cheese Auditor (`ra_cheese_audit.py`)**: Separates SHA-256 sealed `AXIOMATIC_PRIMITIVES` from forbidden data cheesing; fails the build if tampered with. |
| **5. Duct-Tape Band-Aids & Code Poisoning** | Slaps `try/except: pass` or `if x is None` over leaking pipes and stacks new experiments onto broken code. | **Quarantined Sandbox & Pipe-Replacement Protocol**: Experiments run in `research/sandbox/Hxxx/`. Falsified code is moved to `research/graveyard/`, leaving the main codebase 100% pure. |
| **6. Lazy Repeat Questions** | Asks the user the same question repeatedly instead of checking reference images and docs already on disk. | **Mandatory Pre-Question Gate (`check-question`)**: Forces the agent to scan and view all files/images in `reference/`, `assets/`, and `research/library/REFERENCES_INDEX.md` before asking anything. |

---

## The 7-Stage RA State Machine

Every research track is governed by [`scripts/ra_gate.py`](./skills/research-anything/scripts/ra_gate.py):

```text
[STAGE 0: INTAKE_AND_SYNC]
  ├── Conversational 1-by-1 Idea Intake -> research/VISION_AND_MISSION.md
  ├── Mandatory Pre-Question Search Gate (ra_gate.py check-question)
  ├── Past-Record Check (LAB_LOG.md, SELF_LEARNING.md, graveyard/)
  └── Ground-Truth Library Firewall (research/library/ vs research/hypotheses/)
       │
       ▼
[STAGE 1: HYPOTHESIS_FORMULATION] ◄────────────────────────────────────────┐
  └── Explicit math/structural formulation & assumptions in REPORT.md      │
       │                                                                   │
       ▼                                                                   │
[STAGE 2: SANDBOX_PROTOTYPE]                                               │
  ├── Quarantined prototype inside research/sandbox/Hxxx_<slug>/           │
  └── Cryptographic SHA-256 sealing of legitimate AXIOMATIC_PRIMITIVES     │
       │                                                                   │
       ▼                                                                   │
[STAGE 3: ADVERSARIAL_BREAK_TEST]                                          │ (If FALSIFIED:
  └── Red-team stress script (break_test.*) to find failure boundaries     │  Archive sandbox to graveyard/,
      & build structural prevention (Happy-path unit tests are banned)     │  keep main codebase 100% clean,
       │                                                                   │  log Issue:Workflow:Found,
       ▼                                                                   │  loop autonomously up to 5x)
[STAGE 4: ANTI_CHEESE_AUDIT]                                               │
  └── Automated AST & Regex scan (ra_cheese_audit.py) for axiom tampering, │
      lookup tables, `if x == const: return const`, & band-aid patches     │
       │                                                                   │
       ▼                                                                   │
[STAGE 5: LAB_REPORT_AND_LEARNING] ────────────────────────────────────────┘
  └── Provenance log (who/what/when) + Self-Learning triad (Issue:Workflow:Found)
       │
       ▼ (Only when PROVEN & Cheese-Free)
[STAGE 6: GRADUATION_REVIEW]
  └── Mandatory User Sign-Off on the Lab Report before merging into main
      project & graduating verified truth to research/library/
```

---

## Key Mechanisms Explained

### 1. Stopping the "Hardcoded Data" Slippery Slope (`AXIOMATIC_PRIMITIVES` vs. Cheesing)
In complex R&D (such as inventing a new neural architecture or symbolic engine), certain foundational constants *must* exist in code—like the `=` operator, $\pi$, physical constants, or dimensional bounds.
- If an agent labels those `# hardcoded data`, the next agent session that hits a hard algorithmic bug will read that comment and think: *"Hardcoded data goes here! I'll add a lookup table to fix my bug."*
- **How RA prevents this**:
  1. The phrase `"hardcoded data"` is banned for legitimate constants. Foundational math/syntax symbols are placed in a dedicated module (`axioms.py`) as **`AXIOMATIC_PRIMITIVES`** and cryptographically sealed:
     ```bash
     python ra_gate.py seal-axioms --workspace . --file "research/sandbox/H001_model/axioms.py"
     ```
  2. Any modification to a sealed axiom file triggers an immediate `AXIOM_SEAL_VIOLATION` in both `ra_gate.py` and `ra_cheese_audit.py`.
  3. **The Deadlock Protocol**: If a hypothesis cannot work without adding lookup tables, domain heuristics, or `if input == X: return Y` branches, the agent is forbidden from patching it with data—it **must falsify the hypothesis** and invent a new mathematical/architectural mechanism.

### 2. Zero-Trust Comments & Multi-Agent Lab Provenance
Agents frequently write lazy comments like `# this source is untrusted` or `# approach X doesn't work`. Future sessions blindly believe those comments and skip valid paths.
- **RA's Zero-Trust Rule**: No claim of failure or untrustworthiness is valid unless backed by a Hypothesis ID (`Hxxx`) or Graveyard report containing:
  1. **Exact Root Cause** (mathematical, physical, or structural proof).
  2. **Reproducible Evidence** (exact inputs, metrics, and raw logs).
  3. **Boundary Scope** (*why* and *when* it fails).
- Every experiment records **Agent/Session ID**, **Timestamp**, **Parent Hypothesis**, and **Raw Trusted Data** in `research/LAB_LOG.md`.

### 3. The Ground-Truth Library Firewall (`research/library/`)
LLMs often blur the line between their own unverified hypotheses and real-world facts. RA enforces a strict directory firewall:
- `research/hypotheses/` = Speculative ideas currently under test.
- `research/graveyard/` = Falsified approaches archived with proof of why they failed.
- `research/library/` = **Undisputed Ground Truth ONLY** (`[USER_GROUND_TRUTH]`, `[EXTERNAL_VERIFIED_LAW]`, or `[GRADUATED_LAB_TRUTH]` that survived Stage 3, Stage 4, and Stage 6 user sign-off).

### 4. Continuous Self-Learning (`Issue : Workflow : Found`)
Every concluded hypothesis (especially falsified ones) requires appending a structured triad to `research/SELF_LEARNING.md`:
- **`Issue`**: What broke empirically.
- **`Workflow`**: What flaw in assumptions or testing methodology allowed it to happen.
- **`Found`**: The permanent rule or mathematical constraint discovered for all future hypotheses.

---

## Installation

### Option 1: Via `npx skills` (Claude Code / Open Agent Skills)

```bash
npx -y skills add Kanorin-chan/research-anything --skill research-anything
```

### Option 2: One-Command Python Installer (Claude Code, Antigravity, Gemini CLI)

Clone this repository and run [`install.py`](./install.py) (requires only Python 3.8+ standard library):

```bash
git clone https://github.com/Kanorin-chan/research-anything.git
cd research-anything

# Install globally for Claude Code, Antigravity, and Gemini CLI:
python install.py --target all

# Or install for a specific platform:
python install.py --target claude        # -> ~/.claude/skills/research-anything
python install.py --target antigravity   # -> ~/.agents/skills/research-anything & ~/.gemini/config/skills/research-anything
python install.py --target gemini        # -> ~/.gemini/skills/research-anything
```

### Option 3: Manual Copy from `distributions/`

Pre-packaged platform folders are available under [`distributions/`](./distributions):
- **Claude Code**: Copy [`distributions/claude/.claude/skills/research-anything`](./distributions/claude/.claude/skills/research-anything) to `~/.claude/skills/research-anything` (global) or `<project>/.claude/skills/research-anything` (workspace).
- **Antigravity**: Copy [`distributions/antigravity/.agents/skills/research-anything`](./distributions/antigravity/.agents/skills/research-anything) to `~/.agents/skills/research-anything` (global) or `<project>/.agents/skills/research-anything` (workspace).
- **Gemini CLI**: Copy [`distributions/gemini/.gemini/skills/research-anything`](./distributions/gemini/.gemini/skills/research-anything) to `~/.gemini/skills/research-anything`.

---

## How to Use

### Triggering the Skill
- **Claude Code**: Run `/research-anything` or prompt: *"Use RA (`research-anything`) to invent/research..."*
- **Antigravity / Gemini CLI / Cursor**: Prompt *"Use RA (`research-anything`)..."* or describe any zero-shot algorithm, neural network, encryption, game mechanic, hardware layout, or material/shape R&D problem.

### Workspace Directory Created by RA (`research/`)
When initialized in a project workspace (`python ra_gate.py init --workspace .`), RA maintains:

```text
<your-project>/
└── research/
    ├── .ra_state.json              # Locked stage state, falsification counter, & SHA-256 axiom seals
    ├── VISION_AND_MISSION.md       # North Star vision, non-negotiables, & decomposed tracks
    ├── INVARIANTS.md               # Locked architectural decisions echoed on every stage transition
    ├── LAB_LOG.md                  # Multi-agent/session chronological provenance ledger
    ├── SELF_LEARNING.md            # Continuous Issue : Workflow : Found mistake & discovery log
    ├── library/                    # Firewall: ONLY verified ground truth & indexed user references
    │   └── REFERENCES_INDEX.md     # Mandatory index of all user images, diagrams, specs & answers
    ├── hypotheses/                 # Per-hypothesis scientific Lab Reports (H001_<slug>/REPORT.md)
    ├── sandbox/                    # Quarantined prototypes & adversarial break_test scripts
    └── graveyard/                  # Falsified hypotheses archived with exact proof of failure
```

---

## CLI Gatekeeper & Auditor Reference

### `ra_gate.py` (State-Machine Gatekeeper)

```bash
# Initialize research/ folder structure in your workspace
python scripts/ra_gate.py init --workspace . --agent "CLAUDE_MAIN"

# Refresh context: print current stage, locked invariants, and active instructions
python scripts/ra_gate.py status --workspace .

# Mandatory Pre-Question Gate: scan reference/, assets/, docs/, and REFERENCES_INDEX.md
python scripts/ra_gate.py check-question --workspace .

# Start a new hypothesis and quarantined sandbox
python scripts/ra_gate.py new-hypothesis --workspace . --id H001 --slug "spectral_gate" --agent "CLAUDE_MAIN"

# Cryptographically seal legitimate mathematical/structural axioms (SHA-256)
python scripts/ra_gate.py seal-axioms --workspace . --file "research/sandbox/H001_spectral_gate/axioms.py"

# Validate stage completion and advance to the next stage
python scripts/ra_gate.py advance --workspace .

# Conclude a hypothesis (PROVEN or FALSIFIED) with mandatory Self-Learning triad
python scripts/ra_gate.py conclude --workspace . \
  --verdict FALSIFIED \
  --issue "Gradient vanished across discrete threshold at step 400" \
  --workflow "Tested only 10 steps initially; missed long-horizon variance collapse" \
  --found "Must use continuous spectral relaxation instead of hard step gating"

# Graduate a PROVEN hypothesis into research/library/ after user sign-off
python scripts/ra_gate.py graduate --workspace .
```

### `ra_cheese_audit.py` (Automated Anti-Cheese & Band-Aid Scanner)

```bash
python scripts/ra_cheese_audit.py --workspace . --hypothesis "H001_spectral_gate"
```
Automatically fails Stage 4 if it detects:
1. SHA-256 mismatch or deletion of any sealed `AXIOMATIC_PRIMITIVES` file.
2. Poison comments (`# hardcoded`, `# hack`, `# band-aid`, `# temporary fix`, or bare `# untrusted` without a `Hxxx` / `LIB-xxx` citation).
3. Symptom-swallowing band-aids (`except: pass`, `except Exception: pass`, empty `catch {}`).
4. AST-level algorithmic fraud (`>= 4` branches of `if input == const: return const` or unsealed constant lookup dicts with `> 20` entries in non-test code).

---

## License

Released under the [MIT License](./LICENSE).
