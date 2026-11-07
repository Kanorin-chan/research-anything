# Workflow, Context & Blast-Radius Mapping (Stage 1)

This reference governs **Stage 1 (`STAGE_1_WORKFLOW_AND_CONTEXT_MAPPING`)** of **RA (`research-anything`)**: forcing the agent to understand the complete system context, end-to-end execution flows, culprit vs. victim nodes, and multi-hop blast radius **before** formulating any hypothesis, editing any function, or creating any new function.

---

## 1. Why Surface Reading Fails (The Three Tunnel-Vision Disasters)

Standard LLMs read *what* the user wants to do and skim *surface data* (file names, function signatures, or the single line where a symptom appeared), then immediately mutate code. This causes three classic engineering failures:

### A. 1-Hop Tunnel Vision (The Blocked-Road Map Fallacy)
Suppose a system is a road network and `Node X` is blocked. A naive agent inspects only `Node X` and its immediate neighbor (`1-hop relative`), alters their logic, and declares the bug fixed—never checking what that rerouting does `2, 3, or N hops` downstream or on the next execution cycle.

### B. Whack-a-Mole Regressions (Breaking Existing Behavioral Contracts)
Suppose a system has an already-working behavioral invariant—for example, *"Resource/Action A must execute at most once per lifecycle/session."*
1. Later, an unrelated `Bug B` appears in the recognition or retry loop.
2. The agent focuses solely on making `Bug B` disappear (e.g., resetting a state flag or loosening a condition).
3. Because the agent never mapped the full state lifecycle, its fix for `Bug B` silently invalidates the state guard that kept `Action A` executing only once—causing `Action A` to trigger multiple times.
4. When the user reports that regression, the agent patches `Action A` and re-breaks `Bug B`, trapping the project in an endless back-and-forth ping-pong loop.

### C. Mutating Innocent Functions (`Symptom != Culprit`)
The user says: *"Function A looks like it has a bug."*
- Often, **`Function A` is written properly**, and an upstream producer (`Function C`) is feeding it corrupted state or violating a timing/ordering contract.
- Or worse: while fixing `Function C`, the agent casually modifies `Function A` "just in case," breaking `Function A`'s working guarantees and introducing a new bug that only surfaces during real runtime usage.

---

## 2. Mandatory Stage 1 Protocol: Full Context Before Action

Before proposing any hypothesis (`Stage 2`) or writing any prototype code (`Stage 3`), you **must** complete four steps and record them in `research/WORKFLOW_MAP.md`:

### Step 1: End-to-End Multi-Hop Flow Mapping (Beyond Surface Data)
Do not stop at function signatures, variable names, or immediate callers. Trace the actual runtime flow across the entire lifecycle:
- **Upstream Producers (`-N` hops)**: Every caller, event source, configuration loader, or state initializer that feeds the target area.
- **Shared State & Lifecycle Memory**: Every counter, flag, cache, queue, tensor state, or global/instance variable read or mutated along the path.
- **Downstream Consumers (`+N` hops)**: Everything that consumes the output or reacts to the state change several steps later.
- **Loopback / Multi-Cycle Behavior**: How the state behaves on iteration $t = 1$ vs. $t = 1,000$ (e.g., long-running loops, retries, state resets, cooldowns).

### Step 2: Culprit Proof vs. Protected Innocent Nodes
Never assume the function mentioned by the user or showing the crash/symptom is the culprit:
1. **Verify Input vs. Contract**: Check what enters `Function A` vs. what `Function A` is designed to do.
2. **Trace to the True Origin**: If `Function A` is behaving according to its contract and `Function C` upstream introduced the invalid state, identify `Function C` as the **True Culprit**.
3. **Lock Innocent Nodes as `PROTECTED`**: Explicitly list `Function A` (and all other working neighbor functions) in the **`Protected Working Nodes`** table. You are **strictly forbidden** from modifying `PROTECTED` functions while fixing `Function C`.

### Step 3: Registry of Existing Behavioral Contracts (Anti-Ping-Pong Lock)
List every existing working behavior that shares the mapped workflow or state variables (e.g., *"Action A triggers at most 1 time per run"*, *"State X persists across retry loops"*).
- Every behavior listed here becomes a **Mandatory Regression Invariant** in Stage 4 (`ADVERSARIAL_BREAK_TEST`).
- If your fix for the new issue alters or breaks any existing behavioral contract on the map, your hypothesis is **automatically `FALSIFIED`**.

### Step 4: Pre-Edit & Pre-Creation Justification Gate
Before you are allowed to edit a function or create a new function, you must write down explicit answers to four questions:
1. **WHAT am I editing or creating?**
   - Exact file, function/symbol, and state variables—plus which nearby functions are locked as `PROTECTED (Do Not Touch)`.
2. **WHY edit this exact place?**
   - Concrete trace proof showing why *this* node is the root cause and why upstream/downstream nodes are not the right place to fix it.
3. **WHY create a new function/class (if creating one)?**
   - Proof that you searched the workflow map and confirmed no existing function already handles (or should handle) this responsibility—preventing duplicate, fragmented, or conflicting logic.
4. **WHAT is the N-hop blast radius?**
   - Trace how modifying or adding this function affects callers, shared state, downstream consumers, and multi-cycle loops `2, 3, ... N` hops away.

---

## 3. Shared Context Persistence & AI-Session Staleness Warning (`research/WORKFLOW_MAP.md`)

Re-discovering the entire codebase from scratch in every session wastes time and context. However, blindly trusting another AI session's notes is equally dangerous if the code was later edited or if the previous AI misunderstood something.

### Rules for `research/WORKFLOW_MAP.md`
1. **Write It Down for Future Agents**: Always record your workflow map, component roles, state dependencies, and protected nodes in `research/WORKFLOW_MAP.md` (and register mapped source files via `ra_gate.py map-context --files ...`).
2. **Mandatory Session Provenance & Staleness Banner**:
   Every workflow map section **must** carry:
   - **Recorded By**: `<Agent / Session ID>`
   - **Timestamp**: `<ISO-8601>`
   - **Tracked File Hashes (SHA-256)**: Recorded automatically by `ra_gate.py map-context`
   - **Caveat Notice**:
     > **AI SESSION SNAPSHOT — VERIFY BEFORE TRUSTING**: This context map was written by an AI session (`<agent-id>` at `<timestamp>`). It accelerates orientation so future agents do not need to re-discover the system from scratch, **but it may be incomplete, mistaken, or outdated if code has changed**. Always run `ra_gate.py status` to check for modified file hashes and verify the live code of any node on your target path before editing.
