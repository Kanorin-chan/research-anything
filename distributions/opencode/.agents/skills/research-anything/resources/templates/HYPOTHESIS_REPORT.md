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

## 3. First-Principles Formulation & Assumptions (Stage 2)
- **Problem / Mechanism Targeted**: <Which track or broken invariant does this hypothesis address?>
- **Mathematical / Structural Formulation**:
  <Write the exact equations, state transitions, data structures, or physical/geometric model being invented>
- **Explicit Assumptions**:
  1. <Assumption 1 — and why we believe it holds>
  2. <Assumption 2 — and what would falsify it>

---

## 4. Real-Environment `.log` Telemetry, Watchdog & Stress Verification (Stage 4)
> **Rule**: Trash synthetic/mocked unit tests are BANNED. Every function and state hop must be wired to a real-environment `.log` file (`ra_log_engine.py`) logging `flow=caller->callee`, `role`, `inputs`, `state_before -> state_after`, `output`, `[PASS]`/`[STUCK]`/`[FAIL]`, and `BC-xxx` contract checks.

- **Real-Environment `.log` Path**: `research/sandbox/{{HYPOTHESIS_ID}}_{{SLUG}}/logs/runtime_real.log`
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
- **Final Verdict**: `<PROVEN | FALSIFIED>`
- **Exact Root Cause (Why it worked or why it failed)**:
  <Zero-trust requirement: Never write a vague claim. State the exact mathematical/structural reason and when this approach must or must not be used.>
- **Spawned Next Hypothesis (if Falsified or Partial)**:
  <What new mathematical function or architectural mechanism should `H_next` test?>
