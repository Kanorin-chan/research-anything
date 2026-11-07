# Phase Boundaries & Context Control in RA

A **phase** is a coherent unit of work inside a session: project grilling (`/ra-talk`), workflow & blast-radius mapping (`/ra-workflow-map`), prototype/fix implementation, or `.log`/visual verification.

The **phase boundary** is the gap between two phases. Never compact or clear mid-phase—either continue or fork the remaining atomic tasks to subagents via `ra_context_harness.py`.

---

## The Five Boundary Options (Ordered Decision Tree)

Work top-to-bottom at each phase boundary. The first **YES** wins:

| Priority | Option | What It Does |
| :--- | :--- | :--- |
| **1** | **Continue** | Stay in the current session when you are still well inside the smart zone (~150k tokens) and the next phase needs this phase's verbatim reasoning as a **primary source** (e.g., `/ra-talk` $\rightarrow$ `/ra-workflow-map`). |
| **2** | **`/ra-context-fork` (Snapshot + 1-Concurrency Subagent Baton)** | When the workflow map (`WORKFLOW_SLICE`) or framework rules (`BASE_FRAMEWORK`) are ready and you have bounded tasks to execute: compile a Read-Once snapshot (`ra_context_harness.py create`), fork 1 atomic `REAL_RD` task per subagent (`ra_context_harness.py fork`), and reclaim the baton with a report (`return-baton`). |
| **3** | **`/clear`** | Empty the window when everything in the current session (dead-end exploration, one-off question) is already captured on disk (`WORKFLOW_MAP.md`, `GLOSSARY.md`, `SELF_LEARNING.md`) or 100% disposable. |
| **4** | **Portable `/handoff` (`ra_context_harness.py handoff`)** | Write a portable Markdown handoff file when **switching harnesses** (`OpenCode <-> Claude Code <-> Codex <-> Antigravity/Gemini`), **moving to a new directory**, or **forking a side investigation**. Points to `WORKFLOW_MAP.md`, `INVARIANTS.md`, `GLOSSARY.md`, and active snapshots by path without duplicating them. |
| **5** | **`/compact`** | Last resort when staying in the same session, same harness, and same directory, but approaching the smart-zone limit. |
