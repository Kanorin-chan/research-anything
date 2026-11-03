# Self-Learning Log (`Issue : Workflow : Found`)

> **Managed by RA (`research-anything`)** — Every falsified hypothesis, discovered blind spot, or workflow mistake must append a structured entry here so no future session repeats the same mistake.

## Format
Each entry must follow the strict triad:
- **`Issue`**: The concrete technical, mathematical, or behavioral failure observed.
- **`Workflow`**: What flaw in the reasoning, assumption, or verification workflow allowed this issue to happen.
- **`Found`**: The permanent lesson, invariant, or boundary constraint discovered that all future hypotheses must obey.

---

## Recorded Lessons

### `SL-000` (Initialization Baseline)
- **Date / Agent**: `<ISO-8601>` / `SYSTEM`
- **Related Hypothesis**: `INIT`
- **Issue**: Standard AI agents fail on novel R&D by pattern-matching boilerplate, writing happy-path tests, slapping band-aid patches on bugs, and hardcoding lookup data when stuck.
- **Workflow**: Unconstrained code generation without first-principles hypothesis formulation, adversarial break-testing, and axiom sealing.
- **Found**: Enforce the 7-Stage RA State Machine (`ra_gate.py`) and Automated Anti-Cheese Auditor (`ra_cheese_audit.py`) on every research cycle.
