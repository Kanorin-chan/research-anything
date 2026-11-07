---
name: ra-ask
description: Ask which RA skill or partial/full flow fits your situation. A router over the skills in this repo.
disable-model-invocation: true
---

# Ask RA (`ra-ask`)

You don't need to run all 8 stages of `research-anything` every time. **RA is a composable super-skill suite**—you can invoke just one slice (like a project conversation, a multi-hop workflow map, or a systemic root-cause bug fix) or run the full 8-stage invention track.

Before stating what a skill does or skipping a step, read that skill's `SKILL.md`.

---

## 0. Joining a Mid-Flight, Vibe-Coded, or Polluted Project (`--scan-project` Truth-Path Recovery)

Most projects don't start with RA from day 1 — they arrive half-finished, vibe-coded across multiple AI sessions, or full of hidden band-aids, mocked/fake data, and silent bypasses.
Whenever you are dropped into an **existing project** where the user isn't sure why things are failing or what previous AI sessions broke, **first run the Truth-Path Project Scanner**:
```bash
python "~/.gemini/skills/research-anything/scripts/ra_cheese_audit.py" --workspace "." --scan-project
```
This classifies the project (`FRESH_GREENFIELD`, `POLLUTED_VIBE_CODE_NEEDS_TRUTH_PATH`, `UNFINISHED_HALF_WIRED`, or `CLEAN_PRODUCTION_TIER`) and generates **`research/TRUTH_PATH_AUDIT.md`**, exposing:
1. **Hidden Band-Aids (`[EXPOSED_BANDAID]`)**: `except: pass`, empty `catch {}`, `@ts-ignore` / `type: ignore`, and `setTimeout` race-condition hacks.
2. **Fake / Mocked / Hardcoded Data (`[EXPOSED_FAKE_DATA]`)**: `mockData`, `fake_data`, `dummyData`, or placeholder arrays left inside production code.
3. **Data Pollution & Silent Coercion (`[DATA_POLLUTION_*]`)**: Silent `nan_to_num` / `fillna(0)` masking upstream corruption or ground-truth leakage.
4. **Unfinished Stubs (`[EXPOSED_UNFINISHED_STUB]`)**: `TODO`, `FIXME`, `NotImplementedError`.

Then chain **`/ra-workflow-map`** (lock innocent working functions) $\rightarrow$ **`/ra-systemic-debug`** (replace every exposed band-aid and fake data stub with a real production pipe).

---

## 1. Just Talk About the Project (No Code Yet)

- **`/ra-talk`** *(User-invoked)* — **Stateful Project Conversation, Grilling & Shared Language**:
  - Reach for `/ra-talk` whenever you want to **talk through a project, sharpen an idea, or align on design decisions and terminology** before touching code.
  - First runs the **Zero-Repeat Question Gate** (`ra_gate.py check-question`) so the agent reads your existing `GLOSSARY.md`, `reference/`, `assets/`, and `research/VISION_AND_MISSION.md` before asking anything.
  - Then calls `"ra-grilling"` (frontier design-tree interview rounds) and `"ra-domain-modeling"` (updating `GLOSSARY.md`, `research/VISION_AND_MISSION.md`, `research/INVARIANTS.md`, and ADRs inline).
  - **Stops cleanly when the frontier is empty**—never writes code unless you ask to transition into a build or R&D flow.

---

## 2. Something Is Broken: Systemic Root-Cause Debugging (Never Patch a Band-Aid)

- **`/ra-systemic-debug`** *(Model-invoked or User-invocable)* — **6-Phase Systemic Multi-Hop Root-Cause Debugger**:
  - Reach for `/ra-systemic-debug` whenever something is broken, regressing, or behaving unexpectedly and you want it **fixed from the true upstream root cause—never with a symptom band-aid**.
  - **Phase 1 (Real `.log` Feedback Loop First)**: Refuses to guess until `ra_log_engine.py run` reproduces the failure in the real environment with `[FAIL]`/`[STUCK]` + variable deltas (no 30-minute fake unit tests).
  - **Phase 2 (`Symptom != Culprit` & `-N` to `+N` Hop Trace)**: Maps upstream producers, shared state/ledgers, and downstream consumers in `research/WORKFLOW_MAP.md`. Proves whether the blamed function is actually an innocent victim and locks it as **`PROTECTED_WORKING`** (`ra_gate.py map-context --protected ...`).
  - **Phase 3 (Lock Behavioral Contracts `BC-xxx`)**: Locks existing working guarantees so fixing Bug B never triggers a whack-a-mole regression on Behavior A.
  - **Phase 4 (3–5 Ranked Falsifiable Hypotheses)**: States explicit predictions before instrumenting.
  - **Phase 5 (Root-Cause Pipe Replacement — Zero Band-Aids)**: Bans `try/except: pass`, `if x is None` crash-site guards, arbitrary clamping, or extra boolean flags. Replaces the broken upstream mechanism and proves `0` `[FAIL]`/`[STUCK]` hops + `100%` `BC-xxx` contracts via `ra_log_engine.py audit` & `ra_cheese_audit.py`.

---

## 3. Partial Standalone Engineering Slices

Use any of these skills on their own when you only need one specific capability:

- **`/ra-workflow-map`**: **Map `-N` to `+N` Hop Workflow & Blast Radius Only**. Traces upstream producers $\rightarrow$ shared state $\rightarrow$ target node $\rightarrow$ downstream consumers in `research/WORKFLOW_MAP.md`, marks `PROTECTED_WORKING` functions, locks `BC-xxx` contracts, and stamps SHA-256 file hashes (`ra_gate.py map-context`).
- **`/ra-context-fork`**: **Read-Once $\rightarrow$ Fork-Many Context Snapshots, 1-Concurrency Baton & Portable Handoff**. Creates shared snapshots (`BASE_FRAMEWORK`, `WORKFLOW_SLICE`, `TASK_EPHEMERAL`), forks bounded 1-task packets to subagents across **OpenCode (`opencode`)**, **Claude Code (`claude`)**, **Codex (`codex`)**, and **Antigravity/Gemini (`agy`)**, manages the 1-concurrency baton, writes portable `/handoff` files (`ra_context_harness.py handoff`), and auto-evicts stale snapshots on `HASH_DRIFT`.
- **`/ra-log-verify`**: **Production `.log` Telemetry Spine, OS Watchdog & Flow Auditor**. Injects `RALogger` (`Python`/`JS`/`TS`/`PHP`), runs the real command under an OS watchdog timer (`ra_log_engine.py run --timeout-sec 60`), and audits `[PASS]`/`[DECISION]`/`[STUCK]`/`[FAIL]` hops and `BC-xxx` contracts (`ra_log_engine.py audit`).
- **`/ra-visual-audit`**: **User-Eyes Visual, Provided-Asset & Container-Fit Gate**. Scans workspace asset folders for provided assets and native `WxH` aspect ratios (`ra_visual_audit.py scan-assets`), catches ignored provided assets (`[IGNORED_PROVIDED_ASSETS]`) or broken asset paths (`[BROKEN_ASSET_PATH]`), and audits real rendered screenshots (`ra_visual_audit.py audit`).
- **`/ra-anti-cheese`**: **Axiom Seal, Anti-Cheese AST Scanner & Self-Forging Harness/Reviewer**. Seals legitimate `AXIOMATIC_PRIMITIVES` (`ra_gate.py seal-axioms`), scans for lookup tables / hardcoded branches / band-aids (`ra_cheese_audit.py`), and forges `project_harness.py` + `ra-reviewer` (`ra_forge.py`).

---

## 4. Full End-to-End Zero-Shot Invention & R&D

- **`/research-anything`**: **The Full 8-Stage Super-Skill (`STAGE_0` $\rightarrow$ `STAGE_7`)**.
  - Use when inventing a brand-new algorithm, neural network architecture, custom cryptography primitive, game engine mechanic, hardware/CPU layout, or material/geometric system from first principles where off-the-shelf boilerplate fails.

---

## 5. Phase Boundaries & Context Hygiene

At the boundary between any two phases (e.g., `/ra-talk` $\rightarrow$ `/ra-workflow-map` $\rightarrow$ `/ra-context-fork` $\rightarrow$ implementation), read [PHASE-BOUNDARIES.md](./PHASE-BOUNDARIES.md) to choose in strict order between:
1. **Continue** (keep primary-source reasoning in the smart zone)
2. **`/ra-context-fork` Snapshot + 1-Concurrency Subagent Baton** (read once, fork bounded 1-task slices to subagents)
3. **`/clear`** (when prior exploration is 100% disposable)
4. **`ra_context_harness.py handoff`** (when switching harnesses like `Claude <-> Codex <-> OpenCode <-> AGY` or switching directories)
5. **`/compact`** (last resort when staying in the same session past the smart zone)
