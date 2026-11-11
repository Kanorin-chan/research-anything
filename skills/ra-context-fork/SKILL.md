---
name: ra-context-fork
description: Manage Read-Once -> Fork-Many context snapshots, 1-concurrency subagent baton relays through your own harness's native sub-agent tool, portable session handoffs, and automatic hash-drift snapshot eviction. Use when delegating tasks to subagents, forking context, or handing off a session.
---

# RA Context Forking, Baton Relay & Handoff (`ra-context-fork`)

Use this skill standalone (or during Stage 1/3 of `research-anything`) to prevent Main-Agent context bloat and stop sibling subagents from redundantly re-reading the codebase.

## 1. Read Once $\rightarrow$ Fork Many (`create` & `fork`)

When multiple subagents (`Subagent_A`, `Subagent_B`) need the same project or subsystem context, compile it **once** into a snapshot:

```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_context_harness.py" create \
  --workspace "." \
  --id "SNAP_WORKFLOW" \
  --tier "WORKFLOW_SLICE" \
  --files <file1> <file2> \
  --summary "<compiled workflow map, PROTECTED_WORKING nodes, and BC-xxx contracts>"
```

### The 3 Snapshot Tiers & Automatic Throw-Away (Eviction) Rules:
- **`BASE_FRAMEWORK` (Tier 1)**: Domain/framework rules, `GLOSSARY.md`, `INVARIANTS.md` (`max_reuses=25`, `ttl=1440m`).
- **`WORKFLOW_SLICE` (Tier 2)**: Subsystem `-N` to `+N` hop map, `PROTECTED_WORKING` nodes, `BC-xxx` contracts, and file SHA-256 hashes (`max_reuses=6`, `ttl=180m`). **Automatically thrown away (`EVICTED`) on `HASH_DRIFT`** the moment any tracked file is edited.
- **`TASK_EPHEMERAL` (Tier 3)**: 1-task delta (`max_reuses=1`, `ttl=30m`). **Thrown away immediately** after 1 fork.

---

## 2. Fork to a Subagent with Your Own Harness's Native Tool

Enforce the **Task-Sizing Rule** (`REAL_RD` = strictly **1 atomic task per subagent**; `TRIVIAL_BATCH` = small surface tweaks like CSS/icon/label changes allowed together) and the **1-Concurrency Baton Relay**:

```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_context_harness.py" fork \
  --workspace "." \
  --snapshots "SNAP_WORKFLOW" \
  --subagent "Subagent_A" \
  --task-type "REAL_RD" \
  --task "<single-atomic-task>"
```

`fork` writes the brief `research/context_snapshots/forks/FORK_Subagent_A.md` and prints how to hand it to your own harness's native sub-agent tool (Claude Code: the `Agent` tool; OpenCode: the `subagent` tool). Point a fresh worker at the brief; never send a new task into another worker's session.

The native tool is free only on your own model: no `model=` override. Other models, other harnesses, and CLI forms (your own harness's too) need `ra_gate.py allow-agent` with the user's exact words naming that agent first. Only then does `fork` print their command, with the granted model's `-m`. Never list model catalogues to pick one.

RA supports OpenCode, Claude Code, Codex and Antigravity/Gemini.

---

## 3. Reclaim the 1-Concurrency Baton & Auto-Evict Stale Snapshots (`return-baton`)

The brief ends with the worker-handover questions. `Subagent_A`'s report `research/context_snapshots/reports/REPORT_Subagent_A.md` must answer every one of them under a heading `## Handover answers`:

```markdown
## Handover answers
1. Yes: I ran it on research/data/real_scan.csv (the real capture), result 0.84.
2. ...one answer per numbered question, each with a reason or a fact...
```

Then reclaim the baton (which also auto-evicts any snapshots whose tracked files changed via `HASH_DRIFT`). `--status COMPLETED` refuses a report without those answers:

```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_context_harness.py" return-baton \
  --workspace "." \
  --subagent "Subagent_A" \
  --status COMPLETED \
  --report-file "research/context_snapshots/reports/REPORT_Subagent_A.md"
```

A worker that finished through the native tool without `return-baton` is checked at the review instead: `ra_gate.py review` refuses until its report carries `## Handover answers`, or the REVIEW file carries them under `## Handover answers (<worker>)`.

---

## 4. Portable Session Handoff (`handoff`)

When the user switches harness, moves directories, or saves state for another session, generate a portable handoff file (saved to the OS temp directory by default, pointing to `GLOSSARY.md`, `WORKFLOW_MAP.md`, `INVARIANTS.md`, and active snapshots by path):

```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_context_harness.py" handoff \
  --workspace "." \
  --focus "<what the next session will focus on>" \
  --summary "<concise summary of decisions and current state>" \
  --suggested-skills "ra-systemic-debug" "ra-log-verify"
```
