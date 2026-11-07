---
name: ra-systemic-debug
description: Systemic multi-hop root-cause debugger that fixes bugs from the upstream root cause and strictly bans symptom band-aids. Use when the user says "debug this", "diagnose", "fix this bug", or reports something broken, regressing, stuck, or failing.
---

# RA Systemic Root-Cause Debugging (`ra-systemic-debug`)

A phase-gated discipline for hard bugs and multi-hop regressions. **Never patch a symptom with a band-aid (`try/except: pass`, `if x is None`, arbitrary clamping, or extra boolean flags), never blindly mutate the function the user blamed (`Symptom != Culprit`), and never waste 30 minutes on mocked synthetic unit tests.**

When exploring the codebase, read `GLOSSARY.md`, `research/INVARIANTS.md`, and `research/WORKFLOW_MAP.md` (if they exist) first. Redact any secrets (`<REDACTED>`) in captured outputs.

---

## Phase 1: Build a Tight Real-Environment `.log` Feedback Loop

**Do not theorize or edit code until you have a fast, deterministic command that reproduces the exact bug in the real environment.**
- **Trash synthetic unit-test marathons (`test_xyz.py` with mocks) are banned.**
- Inject or wire `RALogger` (`ra_log_engine.py inject-sdk --lang <python|js|ts|php>`) and run the real workflow under the OS watchdog timer:
  ```bash
  python "~/.agents/skills/research-anything/scripts/ra_log_engine.py" run \
    --workspace "." \
    --hypothesis "STANDALONE" \
    --timeout-sec 60 \
    --cmd "<real-repro-command>"
  ```
- **Phase 1 Completion Criterion**: You have run one fast, deterministic command in the real environment that goes red (`[FAIL]` or `[STUCK]` in the `.log`, or demonstrates the exact wrong state delta) on the user's reported symptom.
- Shrink the reproduction scenario until every remaining input/step is load-bearing.

---

## Phase 2: Trace `-N` to `+N` Hops & Prove `Symptom != Culprit`

Never inspect only the crash line or the function the user accused. Call the Skill tool with `"ra-workflow-map"` (or populate `research/WORKFLOW_MAP.md` directly) to trace:
`Upstream Producers (-N hops) -> Shared State / Ledgers -> Accused Node (Hop 0) -> Downstream Consumers (+N hops) -> Multi-Cycle Loopback`.

1. **Prove Culprit vs. Innocent Victim (`Symptom != Culprit`)**:
   - Even if the user says *"Function A is broken!"*, verify via `.log` state deltas whether `Function A` is actually working properly and receiving corrupted state from `Function C` upstream.
   - Lock every verified innocent function as **`PROTECTED_WORKING`** so you never mutate working code while fixing the culprit:
     ```bash
     python "~/.agents/skills/research-anything/scripts/ra_gate.py" map-context \
       --workspace "." \
       --agent "DEBUGGER" \
       --files <mapped_files...> \
       --protected <file:innocent_func...>
     ```
2. **Lock Existing Behavioral Contracts (`BC-001`, `BC-002`...)**:
   - Record all existing working behaviors connected to the flow in `research/WORKFLOW_MAP.md` so fixing this bug never causes a secondary whack-a-mole regression elsewhere.
3. **Zero-Trust Comment Check**:
   - Never trust bare comments in code (`# added to fix stuck bug`, `# do not remove`, `# untrusted`). Falsify or verify them with `.log` evidence.

---

## Phase 3: Formulate 3–5 Ranked Falsifiable Hypotheses

Before changing any logic, write **3–5 ranked root-cause hypotheses**. Single-hypothesis debugging anchors on the first plausible guess.
- Every hypothesis must state an explicit **falsifiable prediction**:
  > *"If `<Upstream Node C mutating state X at Hop -2>` is the root cause, then `<observing state_delta at Hop -2>` will show `<exact corruption>`, and `<replacing Pipe C>` will make the symptom at Hop 0 disappear while keeping `BC-001` intact."*

---

## Phase 4: Targeted `.log` Instrumentation

Map each probe to a prediction from Phase 3. Change one variable at a time:
- Log exact `flow="caller->callee"`, `inputs`, `state_before`, `state_after`, `delta`, and `output` at the hop boundaries that distinguish your hypotheses.
- Never "log everything and grep blindly."

---

## Phase 5: Root-Cause Pipe Replacement (Zero Band-Aids)

Once `.log` evidence isolates the true upstream culprit:
1. **Band-Aids Are Strictly Forbidden**:
   - Do **NOT** add `if x is None: return`, `try/except: pass`, arbitrary value clamping, or extra boolean flags at the downstream symptom site.
   - Do **NOT** touch any function locked as `PROTECTED_WORKING`.
2. **Replace the Broken Pipe From First Principles**:
   - Fix the upstream state transition, invariant, or equation where the corruption originates.
3. **Verify in the Real Environment + Negative Control**:
   - Re-run `ra_log_engine.py run` and `ra_log_engine.py audit` to prove:
     - `0` `[FAIL]` and `0` `[STUCK]` hops.
     - `100%` of `BC-xxx` behavioral contracts hold (`CONTRACT_HOLDING`).
   - Run `ra_cheese_audit.py` to confirm zero band-aids or hardcoded lookup branches were introduced.

---

## Phase 6: Cleanup & Self-Learning Record

Before declaring the bug fixed:
- [ ] Original reproduction scenario passes cleanly in `ra_log_engine.py audit`.
- [ ] All `BC-xxx` contracts and `PROTECTED_WORKING` functions remain 100% intact.
- [ ] Record the `Issue : Workflow : Found` triad in `research/SELF_LEARNING.md` (`ra_gate.py learn --issue "..." --workflow "..." --found "..."`) so future sessions never repeat the root-cause pattern.
