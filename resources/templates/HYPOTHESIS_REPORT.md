# Hypothesis Lab Report: {{HYPOTHESIS_ID}} ({{SLUG}})

## 1. Provenance & Lineage
- **Hypothesis ID**: `{{HYPOTHESIS_ID}}`
- **Slug / Title**: `{{SLUG}}`
- **Parent Hypothesis**: `{{PARENT_ID}}`
- **Agent / Session ID**: `{{AGENT_ID}}`
- **Created Timestamp**: `{{TIMESTAMP}}`
- **Sandbox Path**: `research/sandbox/{{HYPOTHESIS_ID}}_{{SLUG}}/`
- **Current Verdict**: `PENDING` (`PROVEN` | `FALSIFIED` | `PENDING`)

---

## 2. Workflow Context, Culprit Proof & Pre-Edit/Pre-Creation Justification (Stage 1)
- **Brick Status** (`research/INVENTORY.md` §3): <RUNS / NOT BUILT — if NOT BUILT, this hypothesis must be the brick>
> **Rule**: Never edit a function just because a symptom appeared there, and never edit/create code without mapping the multi-hop workflow in `research/WORKFLOW_MAP.md`.

- **End-to-End Flow Summary (`-N` to `+N` Hops)**:
  <Trace Upstream Producer -> Shared State -> Target Node -> Downstream Consumers -> Multi-Cycle Loopback>
- **WHAT is Being Edited or Created**:
  - **True Culprit / Target Node(s)**: `<Exact file:function to modify or create>`
  - **Protected Working Nodes (`DO NOT TOUCH`)**: `<Functions verified as innocent/working that must remain untouched>`
- **WHY Edit This Specific Location**:
  <Empirical proof that this node is the root cause rather than an innocent downstream victim>
- **WHY Create a New Function/Module (or `N/A` if modifying existing)**:
  <Proof that no existing function in `WORKFLOW_MAP.md` already handles or should handle this responsibility>
- **N-Hop Blast Radius & Existing Behavioral Contracts (`BC-xxx`)**:
  <List every downstream path, shared state variable, and existing working behavior (e.g., once-per-cycle execution guarantees) that must remain unbroken>

---

## 3. Option Sweep, Baseline & Stop Rule (Stage 2)
> **Rule**: List approaches from DIFFERENT families before building any. Parameter variants of one approach count as ONE row.

- **Weakest Link Targeted**: <Which part of the brick (`research/INVENTORY.md` §3) this hypothesis improves, and its current number>
- **Baseline To Beat**: <The simplest or existing solution and its measured score on the same real data>
- **Option Sweep (>= 3 families)**:

| # | Approach family | Expected ceiling | Cost / speed | Data or assets it needs | Race it? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| A | <approach family A> | <best case and why> | <build + run cost> | <from INVENTORY.md> | <YES / NO — why> |
| B | <approach family B> | | | | |
| C | <approach family C> | | | | |

- **Success Criteria (unseen, hardest real data)**: <number that means WORKS, error direction that hurts more, speed budget>
- **Plateau Rule**: <minimum gain per round; 2 rounds below it, a baseline beating us, or an unseen-data miss = PLATEAUED -> switch family>
- **Stop Rule Registered**: `ra_gate.py stop-rule --component <slug> --metric ... --target ... --min-gain ...` (required to leave Stage 2). Each spike lives in `research/sandbox/<hyp>/<family>/` and prints `RA_SCORE=<number>`.
- **Chosen Approach Formulation**:
  <Exact equations, state transitions, data structures, or model for the approach(es) being raced>
- **Explicit Assumptions**:
  1. <Assumption 1 — and why we believe it holds>
  2. <Assumption 2 — and what would falsify it>

---

## 4. Real-Environment `.log` Telemetry, Watchdog & Stress Verification (Stage 4)
> **Rule**: Trash synthetic/mocked unit tests are BANNED. Every function and state hop must be wired to a real-environment `.log` file (`ra_log_engine.py`) logging `flow=caller->callee`, `role`, `inputs`, `state_before -> state_after`, `output`, `[PASS]`/`[STUCK]`/`[FAIL]`, and `BC-xxx` contract checks.

- **Real-Environment `.log` Path**: `research/sandbox/{{HYPOTHESIS_ID}}_{{SLUG}}/logs/run_<timestamp>.log` (one file per `ra_log_engine.py run`; `audit` reads the latest)
- **Log Audit Command**: `python ra_log_engine.py audit --workspace . --hypothesis {{HYPOTHESIS_ID}}_{{SLUG}}`
- **Real-Environment Scenarios & Stress Vectors Logged**:
  1. **End-to-End Live Flow (`-N` to `+N` Hops)**: <Verify every hop in `WORKFLOW_MAP.md` logged `[PASS]` with exact runtime values>
  2. **Watchdog & Anti-Hang Check (`[STUCK]` Probe)**: <Prove no polling/recognition/retry loop hangs or exceeds its ms threshold>
  3. **Existing Behavioral Contracts & Protected Nodes (`BC-xxx`)**: <Prove `logger.assert_contract("BC-xxx", ...)` held across multi-cycle runs>
- **Discovered Boundary / Stuck Threshold**:
  <At what exact parameter/input threshold does this mechanism stall or fail, and what structural prevention was built?>

---

## 5. Trusted Raw Empirical Data
```text
<Paste unedited metrics, tensor norms, entropy measurements, execution traces, or failure outputs here>
```

---

## 6. Anti-Cheese & User-Eyes Visual Reality Audit Result (Stage 5)
- **Anti-Cheese Command**: `python ra_cheese_audit.py --workspace . --hypothesis {{HYPOTHESIS_ID}}_{{SLUG}}`
- **Anti-Cheese Status**: `<PASS / FAIL>`
- **Visual Reality Command**: `python ra_visual_audit.py audit --workspace . --hypothesis {{HYPOTHESIS_ID}}_{{SLUG}}`
- **Visual Reality Status**: `<PASS / FAIL / NOT_APPLICABLE>` (See `research/sandbox/{{HYPOTHESIS_ID}}_{{SLUG}}/VISUAL_AUDIT.md`)
- **Axiom Seal Status**: `<VERIFIED / NOT_APPLICABLE>`

---

## 7. Scientific Conclusion & Next Step (Stage 6)
- **Final Verdict**: `<PROVEN | FALSIFIED>` — PROVEN only if the Success Criteria hold on unseen data; PLATEAUED or DEAD = FALSIFIED.
- **Race Scoreboard** (paste `ra_gate.py status --scoreboard`): <each raced approach vs. baseline, unseen data, one number each>
- **Exact Root Cause (Why it worked or why it failed)**:
  <Zero-trust requirement: Never write a vague claim. State the exact mathematical/structural reason and when this approach must or must not be used.>
- **Biggest Remaining Limit**: <what now holds the brick back most, with its number>
- **Next Move**: <PLATEAUED -> next family from §3 (not a tweak of this one) | WORKS -> next weakest link | sweep exhausted -> ask the user>
