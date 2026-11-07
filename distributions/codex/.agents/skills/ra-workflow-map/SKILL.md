---
name: ra-workflow-map
description: Map the full multi-hop (-N to +N) workflow, blast radius, PROTECTED_WORKING innocent functions, and BC-xxx behavioral contracts in research/WORKFLOW_MAP.md. Use when exploring how a subsystem works, before editing complex flows, or when proving Symptom != Culprit.
---

# RA Workflow, Context & Blast-Radius Mapping (`ra-workflow-map`)

Use this skill standalone (or as Stage 1 of `research-anything` / Phase 2 of `ra-systemic-debug`) whenever you need to understand a multi-hop workflow and lock its blast radius before making changes.

## 1. Go Beyond Surface Data & 1-Hop Neighbors
Never read only the target function and its immediate caller/callee. Trace the complete end-to-end subgraph and record it in `research/WORKFLOW_MAP.md`:
- **Hop `-N`..`-1` (Upstream Producers & State Mutators)**: Where data, flags, retries, and counters originate.
- **Shared State / Ledgers / Caches**: What mutable state connects upstream hops to downstream hops.
- **Hop `0` (Target / Accused Node)**: The function under investigation.
- **Hop `+1`..`+N` (Downstream Consumers & Multi-Cycle Loopback)**: What consumes the output and what happens on subsequent cycles/frames.

## 2. Prove Culprit vs. Innocent Victim (`Symptom != Culprit`)
- Verify whether working functions along the chain are innocent victims receiving corrupted upstream state.
- Mark every verified innocent function as **`PROTECTED_WORKING`** so neither you nor any subagent modifies it.

## 3. Lock Existing Behavioral Contracts (`BC-001`, `BC-002`...)
- Explicitly list every existing working guarantee in `research/WORKFLOW_MAP.md` (`- **BC-001**: ...`) so fixing or adding one feature never causes a whack-a-mole regression elsewhere.

## 4. Pre-Edit / Pre-Creation Justification
Fill out Section 4 of `research/WORKFLOW_MAP.md`:
1. **WHAT** you plan to edit or create (and what is locked as `PROTECTED_WORKING`).
2. **WHY** edit this exact node (proof of root cause).
3. **WHY** create a new function/module (proof no existing function in the map already owns this responsibility).
4. **WHAT** the $N$-hop blast radius is across the full workflow loop.

## 5. Stamp the Session Snapshot & SHA-256 File Hashes
```bash
python "~/.agents/skills/research-anything/scripts/ra_gate.py" map-context \
  --workspace "." \
  --agent "WORKFLOW_MAPPER" \
  --files <file1> <file2> \
  --protected <file:func_a>
```
Future sessions reading `WORKFLOW_MAP.md` see the exact timestamp, agent provenance, and automatic `[STALE / HASH CHANGED]` warnings if any mapped file was modified since the snapshot.
