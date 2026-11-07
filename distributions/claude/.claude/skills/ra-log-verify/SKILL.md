---
name: ra-log-verify
description: Wire production-grade RALogger telemetry, execute real-environment workflows under an OS watchdog timer, and audit .log traces for [PASS]/[DECISION]/[STUCK]/[FAIL] hops and BC-xxx behavioral contracts. Use when verifying code in the real environment instead of writing mocked unit tests.
---

# RA Production `.log` Telemetry, Watchdog & Flow Auditor (`ra-log-verify`)

Use this skill standalone (or during Stage 3/4 of `research-anything` / `ra-systemic-debug`) to verify code in the real environment with full hop-by-hop telemetry instead of wasting 30 minutes on mocked synthetic unit tests.

## 1. Inject or Wire `RALogger` (`Python`, `JS/TS`, `PHP`)
Silent code and bare `print("ok")` statements are banned. Inject the zero-dependency `RALogger` SDK:
```bash
python "~/.claude/skills/research-anything/scripts/ra_log_engine.py" inject-sdk \
  --workspace "." \
  --lang python \
  --dest "research/sandbox/STANDALONE"
```
Every wired hop records:
`flow="caller->callee"`, functional `role`, runtime `inputs`, `state_before`, `state_after`, `delta`, `output`, `contract="BC-001"`, `elapsed_ms`, and status (`[PASS]`, `[DECISION]`, `[STUCK]`, or `[FAIL]`).

## 2. Run in the Real Environment Under the Hard OS Watchdog
Prevent 30-minute hangs by running the real command under `ra_log_engine.py run` (automatically terminates hung processes and appends a `[STUCK]` record with live stdout/stderr state):
```bash
python "~/.claude/skills/research-anything/scripts/ra_log_engine.py" run \
  --workspace "." \
  --hypothesis "STANDALONE" \
  --timeout-sec 60 \
  --cmd "<real-run-command>"
```

## 3. Audit the Generated `.log` Trace
Verify that every hop logged concrete variable deltas, `0` `[STUCK]`/`[FAIL]` events occurred, and `100%` of `BC-xxx` behavioral contracts from `research/WORKFLOW_MAP.md` held:
```bash
python "~/.claude/skills/research-anything/scripts/ra_log_engine.py" audit \
  --workspace "." \
  --hypothesis "STANDALONE"
```
