# Locked Project Invariants & Sealed Axioms

> **Managed by RA (`research-anything`)** — Every active invariant in this file is echoed into the agent's terminal on every `ra_gate.py` transition to prevent context drift and decision forgetting.

## Locked Architectural Decisions (`INV-xxx`)
- **`INV-001`**: No hardcoded domain data, lookup tables, or special-case output branches inside algorithmic/model modules.
- **`INV-002`**: No symptom-level band-aid patches (`try/except: pass`, arbitrary clamping, silent fallbacks). All bugs require upstream pipe replacement.
- **`INV-003`**: All hypotheses must be built and break-tested in `research/sandbox/` and require user Graduation Sign-Off before merging into the main project.

## Sealed Axiomatic Primitives
Legitimate mathematical symbols, physical constants, or structural tokens must reside in a dedicated axioms file and be cryptographically sealed with `ra_gate.py seal-axioms`. Never label them `# hardcoded data`.
