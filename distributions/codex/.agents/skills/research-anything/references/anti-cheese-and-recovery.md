# Anti-Cheese, Axiom Locking & Clean-Slate Code Recovery

This reference governs how **RA (`research-anything`)** prevents algorithmic fraud ("cheesing"), stops the "hardcoded data" slippery slope across sessions, protects the codebase from poisoning, and eliminates band-aid bug patches.

---

## 1. Stopping the "Hardcoded Data" Slippery Slope

### The Broken-Window Failure Mode
In multi-session AI projects, a common disaster occurs:
1. The user tells the agent: *"Do not use hardcoded data."*
2. Certain foundational symbols or laws *must* exist in code (e.g., mathematical operators like `=`, `+`, `pi`, dimensional constants, or grammar delimiters).
3. Agent 1 writes those constants and adds a comment like `# hardcoded data - do not add more here`.
4. Agent 2 later hits an algorithmic wall it cannot solve, reads the file, sees `# hardcoded data`, and thinks: *"Hardcoded data is allowed in this block! I will hardcode lookup tables / special-case answers here to fix my bug."*

### The RA Solution: Strict Taxonomy & Cryptographic Axiom Lock

#### A. Ban the Phrase "Hardcoded Data" for Legitimate Primitives
Never refer to mathematical symbols, physical laws, or structural syntax tokens as "hardcoded data". Instead, enforce a strict two-tier taxonomy:

| Category | Definition | Examples | Status |
| :--- | :--- | :--- | :--- |
| **`AXIOMATIC_PRIMITIVES`** | Immutable mathematical symbols, physical constants, dimensional bounds, or structural delimiters required to define the problem space. | Operator symbols (`=`, `+`), $\pi$, Boltzmann constant, tensor rank definitions, byte header magic numbers. | **Allowed ONLY in a sealed `axioms` file/block** |
| **Forbidden Cheesing (Hardcoded Data)** | Embedding domain answers, lookup tables, dataset-specific heuristics, keyword lists, magic thresholds tuned to pass one test, or `if input == X: return Y` branches that bypass the algorithm/model. | Vocabulary answer dicts inside a neural network, hardcoded coordinates for a specific test case, special-case `if` branches. | **Strictly Forbidden (Fatal Audit Failure)** |

#### B. Cryptographic Sealing of `axioms`
1. Place all legitimate `AXIOMATIC_PRIMITIVES` in a dedicated file (e.g., `axioms.py`, `axioms.ts`, `axioms.rs`, or `research/AXIOMS.json`).
2. Seal the file using the gatekeeper:
   ```bash
   python "<SKILL_DIR>/scripts/ra_gate.py" seal-axioms --file "<path/to/axioms>"
   ```
3. `ra_gate.py` records the SHA-256 hash and line count of the axioms file in `research/.ra_state.json`.
4. If any subsequent session or subagent modifies the sealed axioms file to sneak in lookup data or heuristics, `ra_cheese_audit.py` and `ra_gate.py` immediately fail with `AXIOM_SEAL_VIOLATION` unless the user explicitly approves resealing.

---

## 2. The Deadlock Protocol (What to Do When Stuck)

Why do agents cheese or add hardcoded data? Because they hit an algorithmic wall and are afraid to admit the current design doesn't work.

**In RA, falsifying a broken hypothesis is a successful research outcome; faking a working result is a fatal failure.**

When your algorithm, neural network, or system design cannot solve a case without adding special-case data, heuristics, or lookup tables:
1. **STOP IMMEDIATELY.** Do not add lookup data, magic thresholds, or special-case `if/else` branches.
2. Mark the current hypothesis as **`FALSIFIED (Expressivity / Mechanism Deadlock)`**.
3. Document in `REPORT.md` the exact input/state where the mechanism lacked the mathematical or structural capacity to succeed.
4. Formulate a **new hypothesis** that invents the missing mathematical function, representation, or state transition so the behavior emerges naturally.

---

## 3. Zero-Trust Comments & Anti-Poisoning Documentation

### Never Write or Trust Bare Claims
- If Agent 1 writes a bare comment like `# this source is untrusted` or `# method X doesn't work`, Agent 2 will blindly skip a valid path—or worse, trust a faked one.
- **Rule**: Any claim that a data source, equation, library, or approach is "untrusted", "broken", or "unusable" **must** cite a specific Hypothesis ID (`Hxxx`) or Graveyard entry containing:
  1. **Exact Root Cause**: Why it failed mathematically, physically, or structurally.
  2. **Reproducible Evidence**: The exact script, input, and log output proving the failure.
  3. **Invalidation Scope**: Under what exact conditions it fails (so future agents know *why* and *when* it should not be used, rather than blindly skipping or guessing).

---

## 4. Clean-Slate Sandbox Quarantine

Failed experiments leave behind dead variables, half-baked abstractions, and confusing comments that poison future reasoning.

1. **Quarantine Every Hypothesis**: Build and test every hypothesis inside `research/sandbox/Hxxx_<slug>/` (or an isolated git worktree/branch).
2. **Clean Revert on Falsification**: When `Hxxx` is falsified, move its code and logs to `research/graveyard/Hxxx_<slug>/` and ensure the main project directory remains untouched.
3. **Never Stack Unproven Hypotheses**: Do not build `H002` on top of dirty, broken leftovers from `H001`. Start `H002` from a clean slate informed by `H001`'s lab report.

---

## 5. Pipe-Replacement Bug Recovery (No Duct Tape on Leaking Pipes)

When a bug occurs or the user reports a broken behavior:

### Forbidden Band-Aids ("Duct Tape")
The following are classified as **Illicit Band-Aids** and will fail `ra_cheese_audit.py`:
- Adding `if x is None: return default` or `if isnan(x): x = 0` at the symptom site without proving why `x` became `None`/`NaN` upstream.
- Wrapping buggy logic in `try ... except: pass` or silent fallbacks.
- Clamping outputs (`clamp(val, min, max)`) to hide an unstable equation or exploding gradient.
- Adding post-processing patches to fix corrupted output instead of fixing the generator.

### Mandatory Pipe-Replacement Protocol
1. **Symptom $\neq$ Cause (Protect Innocent Functions)**: A leak at `Function A` (line 300) often means the pipe pressure or state producer failed upstream at `Function C` (line 50). Never blindly mutate `Function A` if it is working properly—lock `Function A` as `PROTECTED_WORKING` in `research/WORKFLOW_MAP.md`.
2. **Trace the Full Multi-Hop Workflow (`Stage 1`)**: Map upstream producers, shared state, and $N$-hop downstream consumers in `research/WORKFLOW_MAP.md` and lock all existing behavioral contracts (`BC-xxx`) so your fix does not trigger whack-a-mole regressions.
3. **Rip Out & Replace the Pipe**: If the underlying mechanism is flawed, quarantine it, formulate a recovery hypothesis (`Hxxx_fix_<mechanism>`), redesign the upstream mechanism so the invalid state is structurally impossible, and subject it to Stage 4 Adversarial & Regression Break-Testing.
