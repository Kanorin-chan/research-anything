# System Context, Workflow & Blast-Radius Map

> ⚠️ **AI SESSION SNAPSHOT — VERIFY LIVE CODE BEFORE TRUSTING**
> This document records the end-to-end workflow and context discovered by prior AI sessions so future agents do not need to re-discover the entire codebase from scratch. **However, because this map is written by an AI session, entries may be incomplete, partially mistaken, or outdated/altered after subsequent edits.**
> - **Last Mapped By (Agent / Session)**: `<agent-id>`
> - **Last Snapshot Timestamp**: `<ISO-8601>`
> - **Verification Rule**: Run `ra_gate.py status` to check if any tracked source file SHA-256 hash has changed since this snapshot, and **always verify live source lines** along your target path before modifying code.

---

## 1. End-to-End Execution & State Flow Map (Multi-Hop, Beyond Surface Data)
Trace the complete workflow from entry to exit across multiple cycles (`Upstream Producers -> Shared State -> Target Mechanism -> Downstream Consumers -> Loopback / Reset`):

```text
[Upstream Caller / Event] ──► [Function C (Producer)] ──► (Shared State / Counter / Queue) ──► [Function A (Consumer)] ──► [Downstream / Loop Reset]
```

| Hop / Stage | File & Symbol (`path:function`) | Actual Runtime Responsibility (Not Just Surface Name) | Reads State / Inputs | Mutates State / Outputs |
| :--- | :--- | :--- | :--- | :--- |
| `-2 (Upstream)` | `<file:func>` | `<What it actually does>` | `<Inputs/State>` | `<State/Outputs>` |
| `-1 (Producer)` | `<file:func>` | `<What it actually does>` | `<Inputs/State>` | `<State/Outputs>` |
| `0 (Target)` | `<file:func>` | `<What it actually does>` | `<Inputs/State>` | `<State/Outputs>` |
| `+1 (Downstream)` | `<file:func>` | `<What it actually does>` | `<Inputs/State>` | `<State/Outputs>` |
| `+N (Loopback)` | `<file:func>` | `<How state resets or persists over long runs>` | `<Inputs/State>` | `<State/Outputs>` |

---

## 2. Culprit Proof vs. Protected Innocent Nodes (`Symptom != Culprit`)
Never mutate a function just because the symptom appeared there. Prove which node broke the contract and lock working functions so they are not accidentally broken during fixes:

| File & Function | Role in Observed Issue | Status (`CULPRIT` / `PROTECTED_WORKING` / `INSPECTED`) | Empirical Proof / Trace Evidence |
| :--- | :--- | :--- | :--- |
| `<e.g., module.py:func_a>` | `<Symptom appeared here, but input was already corrupted>` | **`PROTECTED_WORKING` (Do Not Edit)** | `<Verified func_a works properly when given valid state>` |
| `<e.g., module.py:func_c>` | `<Upstream producer corrupting shared state>` | **`CULPRIT` (Target for Fix)** | `<Traced invalid state originating at line X>` |

---

## 3. Existing Behavioral Contracts to Preserve (Anti-Ping-Pong Lock)
List every existing working behavior connected to this workflow or shared state. **If a hypothesis/fix breaks any contract below, it must be immediately rejected (`FALSIFIED`)**:

- **`BC-001`**: `<e.g., Action/Resource X must execute at most once per session/cycle; retry loops must never reset its completion state.>`
- **`BC-002`**: `<e.g., Function A's output ordering and return contract must remain unchanged for downstream consumers D and E.>`

---

## 4. Pre-Edit & Pre-Creation Justification (For Active Hypothesis)
Before editing any existing function or creating any new function, answer all four questions:

1. **WHAT am I editing or creating?**:
   - **Target to Edit / Create**: `<Exact file and function/symbol>`
   - **Protected Nodes (Strictly Untouched)**: `<List working functions that must NOT be modified>`
2. **WHY edit this specific location?**:
   - `<Why is this the true root-cause location rather than a 1-hop symptom band-aid?>`
3. **WHY create a new function/module (if applicable)?**:
   - `<If creating a new function: prove no existing function in the workflow map already owns or should own this logic. If editing existing: write N/A.>`
4. **WHAT is the N-Hop Blast Radius?**:
   - `<Trace the impact 2, 3, and N hops away across all callers, shared state variables, and multi-cycle runs.>`
