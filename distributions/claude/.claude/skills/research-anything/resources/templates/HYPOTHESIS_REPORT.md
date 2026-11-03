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

## 2. First-Principles Formulation & Assumptions
- **Problem / Mechanism Targeted**: <Which track or broken invariant does this hypothesis address?>
- **Mathematical / Structural Formulation**:
  <Write the exact equations, state transitions, data structures, or physical/geometric model being invented>
- **Explicit Assumptions**:
  1. <Assumption 1 — and why we believe it holds>
  2. <Assumption 2 — and what would falsify it>

---

## 3. Adversarial & Boundary Verification (Stage 3)
> **Rule**: Happy-path tests do not count. Document the adversarial stress tests designed to break this prototype.

- **Breaking Test Script**: `research/sandbox/{{HYPOTHESIS_ID}}_{{SLUG}}/break_test.*`
- **Stress Vectors Executed**:
  1. **Extreme Scale / Horizon**: <e.g., 10,000 steps / OOD inputs / peak thermal load>
  2. **Degenerate / Pathological Inputs**: <e.g., zero/infinite gradients, adversarial noise, cyclic states>
  3. **Invariance / Conservation Check**: <Did core invariants hold across the entire sweep?>
- **Discovered Failure Boundary**:
  <At what exact parameter/input threshold does this mechanism break, and what structural prevention was built?>

---

## 4. Trusted Raw Empirical Data
```text
<Paste unedited metrics, tensor norms, entropy measurements, execution traces, or failure outputs here>
```

---

## 5. Anti-Cheese Audit Result (Stage 4)
- **Audit Command**: `python ra_cheese_audit.py --workspace . --hypothesis {{HYPOTHESIS_ID}}_{{SLUG}}`
- **Audit Status**: `<PASS / FAIL>`
- **Axiom Seal Status**: `<VERIFIED / NOT_APPLICABLE>`

---

## 6. Scientific Conclusion & Next Step
- **Final Verdict**: `<PROVEN | FALSIFIED>`
- **Exact Root Cause (Why it worked or why it failed)**:
  <Zero-trust requirement: Never write a vague claim. State the exact mathematical/structural reason and when this approach must or must not be used.>
- **Spawned Next Hypothesis (if Falsified or Partial)**:
  <What new mathematical function or architectural mechanism should `H_next` test?>
