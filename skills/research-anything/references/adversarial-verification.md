# Real-Environment `.log` Telemetry, Watchdog & Boundary Verification (Stages 3 & 4)

In **RA (`research-anything`)**, standard AI "unit tests" (`test_xyz.py`, mocked unit tests, or isolated synthetic test runners that run for 30 minutes in a fantasy bubble) are **strictly banned**. Synthetic tests pass in isolation while the real system immediately breaks or hangs in production.

Instead, **RA treats every piece of code as real deployment code wired to a structured `.log` spine (`scripts/ra_log_engine.py`)**, verifying behavior directly from **real-environment `.log` traces**.

---

## 1. Why Synthetic Tests Are Trash vs. Real-Environment `.log` Truth

| Failure Mode of AI Unit Tests | The RA Production `.log` Solution (`ra_log_engine.py`) |
| :--- | :--- |
| Spends 30 minutes writing & running mocked tests that don't reflect the real environment. | **Hard Watchdog Runner (`ra_log_engine.py run --timeout-sec 60`)**: Runs the actual environment/workflow and kills/logs `[STUCK]` immediately if any step hangs. |
| Logs bare `"PASS"` or `"test ok"` with zero insight into actual runtime values or flow. | **Mandatory Functional + Value `.log` Schema**: Every hop logs `flow=caller->callee`, `role="..."`, `inputs={...}`, `state_before={...}`, `state_after={...}`, `delta={...}`, `output={...}`, `contract=BC-xxx`, and `elapsed_ms`. |
| Hangs silently when a loop, recognition step, or async wait fails to resolve. | **Built-in `[STUCK]` Telemetry**: Logs the exact condition being waited on (`waiting_on`), current live variable values, and state snapshot at the exact hop where execution stalled. |

---

## 2. Mandatory Stage 3 Rule: Wire Production `.log` Telemetry Into Every Flow Hop

When writing or modifying code in Stage 3, **silent code and lazy `print("ok")` statements are forbidden**. Inject or import `RALogger`:

```bash
python "<RA_DIR>/scripts/ra_log_engine.py" inject-sdk \
  --workspace "." \
  --lang python \
  --dest "research/sandbox/H001_slug"
```
*(Supports `--lang python | js | esm | ts | php | laravel`; `ts` writes an ES-module `ra_logger.ts`)*

Every function, branch decision, and state mutation along the workflow must log:
1. **`[PASS]` (`logger.log_pass(...)` or `@logger.trace_step(...)`)**:
   - Exact `flow` (`caller_file:func:line->curr_file:func:line`)
   - Exact `role` (functional purpose of this step)
   - Exact `inputs`, `state_before`, `state_after` (auto-computing `delta`), and `output`
   - `contract` (`BC-001`, etc., or `logger.assert_contract("BC-001", ...)`)
2. **`[DECISION]` (`logger.log_decision(...)`)**:
   - Exact branch condition, evaluated threshold values, and which branch was taken.
3. **`[STUCK]` (`logger.log_stuck(...)`)**:
   - Emitted whenever a polling/retry/recognition step exceeds its millisecond threshold or iteration cap—recording *what* it is waiting on and *current live values*.
4. **`[FAIL]` (`logger.log_fail(...)`)**:
   - Emitted with the upstream caller, broken invariant reason, and full variable snapshot.

---

## 3. Mandatory Stage 4 Rule: Real-Environment Execution & `.log` Audit

1. **Execute in the Real Environment Under the Watchdog Timer**:
   ```bash
   python "<RA_DIR>/scripts/ra_log_engine.py" run \
     --workspace "." \
     --hypothesis "H001_slug" \
     --timeout-sec 60 \
     -- <real-environment-execution-command and args>
   ```
2. **Audit the Real `.log` File (`ra_log_engine.py audit`)**:
   ```bash
   python "<RA_DIR>/scripts/ra_log_engine.py" audit \
     --workspace "." \
     --hypothesis "H001_slug"
   ```
   `ra_log_engine.py audit` automatically rejects the run if:
   - Any `[PASS]` line is "AI slop" (missing `flow=caller->callee`, missing functional `role`, or missing runtime `inputs`/`state_before`/`state_after` values).
   - Any hop recorded `[STUCK]` or `[FAIL]`.
   - Any Existing Behavioral Contract (`BC-xxx` in `research/WORKFLOW_MAP.md`) was not verified in the `.log`.

---

## 4. Domain-Specific Real-Environment Stress Vectors (Logged to `.log`)

While running in the real environment, stress-test boundary conditions and log the exact runtime values into `.log`:
- **Algorithms / Bots / Game Loops / Systems**: Multi-cycle runs verifying state resets, recognition thresholds, idempotency (`BC-xxx` once-per-cycle guarantees), and watchdog `[STUCK]` recovery.
- **Web / Backend / Laravel / APIs**: Real request-to-database-to-queue-to-response flow with live payload values and state diffs logged at every hop.
- **ML / Neural Networks**: Per-layer gradient norms, activation ranges, and loss transitions logged as structured `[PASS]`/`[FAIL]` telemetry over real batches.
- **Encryption / Security / Hardware**: Real test-vector inputs, entropy/avalanche metrics, and thermal/timing envelopes logged with exact numerical values.
