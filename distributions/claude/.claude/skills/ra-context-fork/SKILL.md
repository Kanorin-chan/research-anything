---
name: ra-context-fork
description: Manage Read-Once -> Fork-Many context snapshots, 1-concurrency subagent baton relays, portable cross-harness handoffs, and automatic hash-drift snapshot eviction across OpenCode, Claude Code, Codex, and Antigravity/Gemini. Use when delegating tasks to subagents, forking context, or handing off a session.
---

# RA Multi-Platform Context Forking, Baton Relay & Handoff (`ra-context-fork`)

Use this skill standalone (or during Stage 1/3 of `research-anything`) to prevent Main-Agent context bloat and stop sibling subagents from redundantly re-reading the codebase.

## 1. Read Once $\rightarrow$ Fork Many (`create` & `fork`)

When multiple subagents (`Subagent_A`, `Subagent_B`) need the same project or subsystem context, compile it **once** into a snapshot:

```bash
python "~/.claude/skills/research-anything/scripts/ra_context_harness.py" create \
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

## 2. Fork to Subagents Across `opencode`, `claude`, `codex`, and `agy`

Enforce the **Task-Sizing Rule** (`REAL_RD` = strictly **1 atomic task per subagent**; `TRIVIAL_BATCH` = small surface tweaks like CSS/icon/label changes allowed together) and the **1-Concurrency Baton Relay**:

```bash
python "~/.claude/skills/research-anything/scripts/ra_context_harness.py" fork \
  --workspace "." \
  --snapshots "SNAP_WORKFLOW" \
  --subagent "Subagent_A" \
  --task-type "REAL_RD" \
  --platform "auto" \
  --task "<single-atomic-task>"
```

`ra_context_harness.py fork` generates `research/context_snapshots/forks/FORK_Subagent_A.md` and outputs ready-to-run dispatch commands for:
- **OpenCode (`opencode`)**: `opencode run --session <id> --fork --title "Subagent_A" --auto -f ...`
- **Claude Code (`claude`)**: `claude --resume <id> --fork-session ...` / `Task(subagent_type="general-purpose", ...)`
- **Codex (`codex`)**: `codex exec resume <id> --full-auto ...` / `codex exec --full-auto ...`
- **Antigravity / Gemini (`agy`)**: `invoke_subagent(TypeName="self", Role="Subagent_A", ...)`

---

## 3. Reclaim the 1-Concurrency Baton & Auto-Evict Stale Snapshots (`return-baton`)

When `Subagent_A` finishes and writes `research/context_snapshots/reports/REPORT_Subagent_A.md`, reclaim the baton (which also auto-evicts any snapshots whose tracked files changed via `HASH_DRIFT`):

```bash
python "~/.claude/skills/research-anything/scripts/ra_context_harness.py" return-baton \
  --workspace "." \
  --subagent "Subagent_A" \
  --report-file "research/context_snapshots/reports/REPORT_Subagent_A.md"
```

---

## 4. Portable Cross-Harness Session Handoff (`handoff`)

When switching harnesses (`Claude <-> Codex <-> OpenCode <-> AGY`), moving directories, or saving state for another session, generate a portable handoff file (saved to the OS temp directory by default, pointing to `GLOSSARY.md`, `WORKFLOW_MAP.md`, `INVARIANTS.md`, and active snapshots by path):

```bash
python "~/.claude/skills/research-anything/scripts/ra_context_harness.py" handoff \
  --workspace "." \
  --focus "<what the next session will focus on>" \
  --summary "<concise summary of decisions and current state>" \
  --suggested-skills "ra-systemic-debug" "ra-log-verify"
```
