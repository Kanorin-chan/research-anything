# Lead-Orchestrator Delegation, `/fork` Context Controlling & Snapshot Eviction Harness

This reference governs how **RA (`research-anything`)** keeps the Main Agent's context clean, delegates execution to Subagents (even on 1-concurrency local setups), shares context across sibling subagents via `/fork`-style snapshots without re-reading the codebase, and knows **how long to keep a snapshot vs. when to throw it away**.

---

## 1. Main Agent = Lead Orchestrator & Compiler (Never the Heavy Worker)

If the Main Agent reads 40 files, writes sandbox prototypes, debugs stack traces, and runs crawlers inside its own context window, its context rapidly bloats and suffers attention decay.

### A. Strict Role Separation (Whenever Subagents Are Supported)
- **Main Agent (Lead Scientist / Orchestrator)**:
  - Maintains the master state machine (`ra_gate.py`) and Context Snapshot Registry (`ra_context_harness.py`).
  - Decides which snapshot to fork or throw away, dispatches bounded tasks to Subagents, waits for their reports, and compiles verified findings.
  - Performs **as little direct heavy reading/coding work as possible**.
- **Subagents (Focused Execution Workers)**:
  - Execute the heavy reading, workflow tracing, crawling, sandbox prototyping, adversarial break-testing, and code reviewing.

### B. The 1-Concurrency Baton-Pass Relay (For Local / Single-Instance Runs)
Many users run local models or single-concurrency environments where **only 1 agent can run at a time**. Even when concurrency = 1, **always delegate to a subagent** using a strict sequential relay:

```text
[Main Agent] Prepares Forked Snapshot + Bounded Task
      │
      ▼ (Hands Baton & WAITS / IDLE)
[Subagent A] Runs Alone -> Executes Task -> Writes Report -> PAUSES / TERMINATES
      │
      ▼ (Returns Baton)
[Main Agent] Wakes Up -> Audits Report (Zero-Trust) -> Updates Snapshot -> Passes Next Baton
```

### C. Zero-Trust Subagent Supervision ("Expect Subagents to Do Wrongly")
- **Assume every subagent may drift, skip a step, or claim success prematurely.**
- When a subagent returns its report (`ra_context_harness.py return-baton`), the Main Agent must **never** take the subagent's word at face value. Verify the output via:
  1. `python research/harness/project_harness.py check-all` (verifies `PROTECTED_WORKING` nodes and axiom seals were not touched).
  2. `ra_cheese_audit.py` (for Stage 3/4/5 sandbox work).
  3. The dedicated `ra-reviewer` subagent before graduation.

---

## 2. Task Sizing Rule: Preventing Long-Context Subagents

Dumping 7 complex tasks onto a single subagent bloats its context window until it forgets instructions mid-way. `ra_context_harness.py fork` enforces a two-tier task-sizing rule:

| Task Type (`--task-type`) | Examples | Batching Rule |
| :--- | :--- | :--- |
| **`REAL_RD`** *(Default)* | Fixing a bug, tracing a multi-hop workflow, building a sandbox prototype, writing an adversarial break-test, refactoring state logic. | **Strictly 1 Atomic Task per Subagent**. Never stack multiple real tasks onto one subagent. |
| **`TRIVIAL_BATCH`** | Surface tweaks with zero workflow blast radius: *change CSS styling, swap an icon, update a button label, fix typos/formatting*. | **Batching Allowed**. Group small cosmetic/surface tweaks into a single subagent pass. |

---

## 3. Context Controlling & `/fork`-Style Shared Context Retention

Not every subagent needs to re-read every file from scratch—and not every subagent needs the entire project's context.

### Example: Forking Shared Context Across `Subagent A` and `Subagent B`
Suppose `Subagent A` and `Subagent B` are both working on tasks inside a **Laravel** application (or a shared game engine subsystem):
- Both need the **exact same base context**: Laravel framework conventions, project invariants (`INV-xxx`), and the mapped Auth/Queue workflow slice (`WORKFLOW_SLICE`).
- Instead of `Subagent A` reading 25 files AND `Subagent B` re-reading the same 25 files:
  1. **Read Once $\rightarrow$ Create Shared Snapshot**:
     - Compile the shared snapshot once (`laravel_base` + `auth_workflow_slice`) via `ra_context_harness.py create`.
  2. **Fork into Named Subagents Across All 3 Supported Harnesses (`opencode`, `claude`, `agy`)**:
     - **`opencode` (OpenCode CLI)**:
       `opencode run --session "<base_session_id>" --fork --title "Subagent_A" --auto -f "research/context_snapshots/forks/FORK_Subagent_A.md" "..."`
     - **`claude` (Claude Code)**:
       `claude --resume "<base_session_id>" --fork-session --permission-mode acceptEdits -p "..."` OR `Agent(subagent_type="general-purpose", description="Subagent_A", prompt="Read research/context_snapshots/forks/FORK_Subagent_A.md ...")`
     - **`agy` (`Antigravity` / `Gemini`)**:
       `invoke_subagent(Subagents=[{"TypeName": "self", "Role": "Subagent_A", "Workspace": "inherit", "Prompt": "You start with none of the parent conversation. Read <ws>/research/context_snapshots/forks/FORK_Subagent_A.md ..."}])`
     - Fork 1 $\rightarrow$ **`Subagent_A`**: Inherits `laravel_base` + `auth_workflow_slice` + **Task A Delta Only**.
     - Fork 2 $\rightarrow$ **`Subagent_B`**: Inherits `laravel_base` + `auth_workflow_slice` + **Task B Delta Only**.
  3. **Hard Gate in `ra_gate.py`**:
     - `ra_gate.py advance` blocks leaving Stage 1 unless a shared snapshot (`BASE_FRAMEWORK` or `WORKFLOW_SLICE`) is created, and blocks leaving Stage 3 unless at least 1 context fork (`fork`) and baton return (`return-baton`) have completed!

---

## 4. The 3-Tier Context Snapshot Harness (`scripts/ra_context_harness.py`)

To control **what is retained**, **how many times it is reused**, and **when the Main Agent must throw a snapshot away**, RA enforces 3 snapshot tiers:

| Tier (`--tier`) | What It Retains | Default Retention Budget | When Main Agent / Harness MUST Throw It Away (Evict) |
| :--- | :--- | :--- | :--- |
| **1. `BASE_FRAMEWORK`** | Framework/domain knowledge (e.g., Laravel rules, engine architecture), `VISION_AND_MISSION.md`, `INVARIANTS.md` (`INV-xxx`), and crawled skill rules. | Up to **25 forks** or **24 hours** (`1440m`). | **Throw Away When**: `INVARIANTS.md`, framework configuration, or project-local skills are modified (`HASH_DRIFT`). |
| **2. `WORKFLOW_SLICE`** | A specific subsystem's `-N` to `+N` hop map from `WORKFLOW_MAP.md`, `PROTECTED_WORKING` nodes (`Symptom != Culprit`), `BC-xxx` behavioral contracts, and key function signatures. | Up to **6 sibling forks** or **3 hours** (`180m`). | **Throw Away Immediately When**: Any source file in that slice is edited (`HASH_DRIFT`), when `reuse_count >= max_reuses`, or when a hypothesis proves the workflow map had an error. |
| **3. `TASK_EPHEMERAL`** | Single hypothesis (`Hxxx`) equation, sandbox path, or 1-task delta brief. | **1 fork only** (`max_reuses = 1`, `30m`). | **Throw Away Immediately When**: Consumed by 1 subagent fork, when the task finishes, or if the subagent drifted/failed (so dirty reasoning never leaks into the next subagent). |

### CLI Commands for the Main Agent

1. **Create a Shared Context Snapshot (Read Once)**:
   ```bash
   python "<RA_DIR>/scripts/ra_context_harness.py" create \
     --workspace "." \
     --id "laravel_base" \
     --tier BASE_FRAMEWORK \
     --files "composer.json" "research/INVARIANTS.md" \
     --summary "Laravel 11 architecture, service container rules, and locked project invariants."
   ```

2. **Fork Context into `Subagent_A` and `Subagent_B` (Without Re-Reading)**:
   ```bash
   python "<RA_DIR>/scripts/ra_context_harness.py" fork \
     --workspace "." \
     --subagent "Subagent_A" \
     --snapshots "laravel_base" "queue_workflow_slice" \
     --task-type REAL_RD \
     --task "Trace and prototype the upstream producer fix in JobDispatcher::dispatch without touching Worker::run."
   ```
   *(Automatically checks if `laravel_base` or `queue_workflow_slice` has `HASH_DRIFT` or exceeded `max_reuses`—if stale, it **blocks the fork and auto-evicts the snapshot**!)*

3. **Return Baton After Subagent Completes (1-Concurrency Relay)**:
   ```bash
   python "<RA_DIR>/scripts/ra_context_harness.py" return-baton \
     --workspace "." \
     --subagent "Subagent_A"
   ```

4. **Check Snapshot Retention & Auto-Throw-Away Stale Snapshots**:
   ```bash
   python "<RA_DIR>/scripts/ra_context_harness.py" status --workspace "."
   python "<RA_DIR>/scripts/ra_context_harness.py" evict --workspace "." --auto-gc
   ```
