---
name: ra-log-verify
description: Wire production-grade RALogger telemetry, execute real-environment workflows under an OS watchdog timer, and audit .log traces for [PASS]/[DECISION]/[STUCK]/[FAIL] hops and BC-xxx behavioral contracts. Use when verifying code in the real environment instead of writing mocked unit tests.
---

# RA Production `.log` Telemetry, Watchdog & Flow Auditor (`ra-log-verify`)

Use this skill standalone (or during Stage 3/4 of `research-anything` / `ra-systemic-debug`) to verify code in the real environment with full hop-by-hop telemetry instead of wasting 30 minutes on mocked synthetic unit tests.

## 1. Inject or Wire `RALogger` (`Python`, `JS/TS`, `PHP`)
Silent code and bare `print("ok")` statements are banned. Inject the zero-dependency `RALogger` SDK:
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_log_engine.py" inject-sdk \
  --workspace "." \
  --lang python \
  --dest "research/sandbox/STANDALONE"
```
Every wired hop records:
`flow="caller->callee"`, functional `role`, runtime `inputs`, `state_before`, `state_after`, `delta`, `output`, `contract="BC-001"`, `elapsed_ms`, and status (`[PASS]`, `[DECISION]`, `[STUCK]`, or `[FAIL]`).

## 2. Run in the Real Environment Under the Hard OS Watchdog
Prevent 30-minute hangs by running the real command under `ra_log_engine.py run` (automatically terminates hung processes and appends a `[STUCK]` record with live stdout/stderr state):
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_log_engine.py" run \
  --workspace "." \
  --hypothesis "STANDALONE" \
  --timeout-sec 60 \
  -- <real-run-command and args>
```
`--` runs the program directly (no shell; leading `NAME=value` sets env vars). `--cmd "<string>"` still works but goes through the platform shell (`cmd.exe` on Windows). Each run writes its own `research/sandbox/<hyp>/logs/run_<timestamp>.log` (also passed to the program as `$RA_LOG_FILE`). Exit codes: the program's own, `124` watchdog kill, `127` program not found.

## 3. Audit the Generated `.log` Trace
Audits the latest run's log by default (`--log-file` only accepts logs written by `run`). Verify that every hop logged concrete variable deltas, `0` `[STUCK]`/`[FAIL]` events occurred, and `100%` of `BC-xxx` behavioral contracts from `research/WORKFLOW_MAP.md` held:
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_log_engine.py" audit \
  --workspace "." \
  --hypothesis "STANDALONE"
```

## 4. Anti-Lazy-Retry & Mandatory First-Principles Re-Evaluation Gate (`ra_gate.py re-evaluate`)
**Spamming "let's retry" or nudging a threshold and re-running after a failed attempt is BANNED.**
When a fix attempt fails in `ra_log_engine.py run` or `audit`, `ra_log_engine.py` engages a **Retry Lock** (and hashes your current code files). It will block any subsequent `run` until you:
1. Run `ra_gate.py re-evaluate` with a real mathematical/structural diagnosis (lazy phrases like `"let's retry"`, `"tweak threshold"`, or `"maybe flaky"` are rejected):
   ```bash
   python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_gate.py" re-evaluate \
     --workspace "." \
     --component "<component_slug>" \
     --why-failed "<Mathematical/structural proof of WHY the previous calculation failed>" \
     --new-calculation "<New equation/structural change, OR the next approach family if this one plateaued>" \
     --why-different "<Why this new calculation deterministically separates the failure case>"
   ```
2. Actually modify the code to implement the new calculation (re-running with an identical code SHA-256 is blocked!).
3. If `failed_rounds` reaches your `stop-rule` limit, `re-evaluate` triggers the **Hard Stop Rule** and forces you onto the `"If It Never Works"` Pivot Plan.
4. **Plateau lock (automatic).** Print `RA_SCORE=<number>` from every run and pass `--approach <family>` (and `--unseen` on held-out data). Three rounds without a score, two rounds below the stop rule's `--min-gain`, or the per-approach round cap lock all runs until a fresh subagent's `COLD_REVIEW_<n>.md` is registered with `ra_gate.py cold-review --file <f> --reviewer <id> [--next-approach <family>]`.
5. **Plateau = switch, not tweak.** Two rounds under the minimum gain, a baseline that beats you, or a miss on unseen data means the approach has plateaued. Go to the next approach family in the Option Sweep (`REPORT.md` Section 3); a deeper version of the same approach is not a new calculation.
