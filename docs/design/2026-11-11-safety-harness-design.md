# RA Safety Harness: design

Date: 2026-11-11 · Target: RA v1.6.0 (before Field Experts, v1.7.0) · Status: approved to build ("you build it according")

## 1. Why this exists

There are three failures, all seen on real runs:

1. **Wrong identity.** On 2026-11-11, Qwen (OpenCode, `F:\My Project`) stamped `--agent "claude-opus-5-5"` on every gate call. It copied the name from records Opus wrote on 11-10. The lab records now credit Opus for Qwen's decisions. `--agent` is free text, and nothing checks it.
2. **Agents using other agents.** Kano: "To disallow one's to use another's without user permission … you are not allow to go and find what agent we have in user's pc. suddenly you use "agy" (antigravity) without my permission for you. or qwen suddenly uses claude code … i know llm will do that when it discover." RA itself invites this today. `ra_context_harness.py` prints ready-made dispatch commands for every harness (`:663`), and `detect_platform()` falls back to `shutil.which` (`:114-119`), which is discovery on the user's PC.
3. **Deletes.** "especially those rm-f or what removing, data. must have main agent to go tru, with injection: you are about to run a rm-f or removing an item. double check item on remove is safe to remove "sandbox" not user's pc's data."

Plus the injection rule that applies everywhere: "when i say inject and hook, you should write in a proper templates, with generic question that inject to the AI. a full templates." The questions are things like "did you check before submitting? / are you sure you did not fake a data / is this function working as inteded? / is these feature looks reasonable?"

## 2. Goals, non-goals, anti-goals

**Goals**
1. Every RA record names the agent that really ran, worked out by the scripts and not typed by the model.
2. No agent launches, or goes looking for, another harness or model without a recorded user permission.
3. No delete happens outside the sandbox without a check, and every delete can be recovered.
4. Every injection is a template file with real questions. The important ones must be answered in writing before the gate continues.
5. Works on Claude Code (hooks) **and** OpenCode (permission rules + the RA scripts), and degrades to the scripts alone anywhere else.

**Non-goals:** sandboxing the OS; blocking a determined user; changing the plateau lock, review meetings or the manager code-edit block.

**Anti-goals:** blocking normal file work inside the workspace (reading, writing, `git status`); asking Kano about every `rm` of a temp file inside `research/sandbox/`; templates so long the model skims them.

## 3. What the harnesses can actually do (verified 2026-11-11)

- **Claude Code:** skill frontmatter hooks plus forge-armed project hooks (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`). It can block any tool call and inject text. The session id is in the env (`CLAUDE_CODE_SESSION_ID`) and the hook payload. The model is in the session transcript.
- **OpenCode 2.2.7:** sets `OPENCODE=1` and `OPENCODE_SESSION_ID` in the shell environment. The session's model is in `~/.local/share/opencode/opencode.db` (`session_v2.model`, JSON `{"id","providerID"}`). File plugins must `export default { id, setup }` (v2 shape). The published plugin SDK (1.19.5) has **no pre-tool-call hook**, so the old `tool.execute.before` is not accepted for file plugins. Agents carry permission rules `{action, resource, effect: allow|ask|deny}`, visible in `opencode debug agents`.
- **Everything else (Codex, Antigravity):** only what RA's own scripts print and refuse.

So there are three layers: the **scripts** (all harnesses), **Claude hooks**, and **OpenCode permission rules**.

## 4. Identity

New module code in `scripts/ra_common.py`: `resolve_identity() -> {"harness", "model", "session", "source"}`.

- **OpenCode** (`OPENCODE=1`): read the model for `OPENCODE_SESSION_ID` from `opencode.db`, read-only (`$XDG_DATA_HOME` or `~/.local/share/opencode/`). Result: `opencode:llamacpp/qwen3.8-flash-next`.
- **Claude Code** (`CLAUDECODE=1`): read the last assistant `message.model` from the transcript for `CLAUDE_CODE_SESSION_ID`, or use `model` from the hook payload when there is one. Result: `claude-code:claude-opus-5-5`.
- **Codex / Antigravity:** harness from env, model from the harness's config if readable, else `unknown`.
- **Nested harnesses** (both env sets present): the harness nearest in the parent-process chain wins. On Windows use `Get-CimInstance Win32_Process`, never `wmic`. If unsure, record both.
- **Never guess.** If the model can't be read, write `<harness>:unknown`.

Every RA script that writes `--agent` (gate, harness, forge, log engine) uses the resolved identity. `--agent` stays accepted but becomes `agent_claimed`. If the claim differs from the resolved name, the record keeps both and the script prints `[RA] You wrote --agent X, but you are Y. Records use Y.` The `session-start` injection tells the agent who it is.

## 5. Agent permissions

**File:** `research/AGENT_PERMISSIONS.json` (per project; my call):
```json
{"allow": [{"agent": "opencode:llamacpp/qwen3.8-flash-next", "use": true,
            "quote": "<Kano's exact words>", "source": "<when/where>", "granted": "<iso time>"}]}
```
**Commands:** `ra_gate.py allow-agent --agent <harness:model> --quote "<exact user words>" --source "..."` and `revoke-agent --agent ...`, mirroring `directive`. A grant needs a user quote. Kano's example of a valid grant: "to use opencode qwen 3.8 flash as one of your subagent".

**Default, with no grant:** the current harness's own native sub-agents only (Claude Code's Agent tool; OpenCode's subagent tool). Nothing else.

**Enforcement**
- **Scripts:** `detect_platform()` reads env only; no `shutil.which`, which is the discovery Kano banned. `ra_context_harness.py` prints dispatch commands **only for the current harness**, plus any granted ones. `--platform <other>` without a grant is refused, with the `before-other-agent` injection.
- **Claude hook** (PreToolUse on Bash and PowerShell): block commands that launch another agent CLI (`claude`, `opencode`, `codex`, `agy`, `antigravity`, `gemini`, also behind a full path, `npx`, `cmd /c`, `pwsh -c`) unless granted. Also block lookups of them (`where`, `which`, `Get-Command`, `command -v`, `ls` of their install folders). Exception: the current harness's own CLI for read-only `--version` / `--help`.
- **OpenCode:** the forge writes project permission rules that deny those command patterns (`effect: deny`). `allow-agent` rewrites the rule for a granted agent. Verify by checking that `opencode debug agents` lists the rules and that a probe command is refused. The exact config syntax is the builder's to confirm against 2.2.7.

## 6. Delete guard: one door

All deletes go through **`ra_gate.py remove --path <p> [--path ...] --answers <file>`**. "must have main agent to go tru": workers can't delete. They list what should go in their report, and the manager runs `remove` (my reading).

`remove` does the following:
- **Resolves real paths**, following symlinks and junctions and normalising `~1` short names.
- **Inside `research/`:** allowed, except the protected records: `DIRECTIVES.md`, `DECISIONS.md`, `LAB_LOG.md`, `INVARIANTS.md`, `VISION_AND_MISSION.md`, `graveyard/`, `reviews/`, hypothesis `REPORT.md`s, `AGENT_PERMISSIONS.json`, `.ra_state.json`.
- **Elsewhere in the workspace:** needs `--user-quote "<exact words>"`.
- **Outside the workspace:** refused, always.
- **Never actually deletes:** it moves to `research/.trash/<timestamp>/` with a manifest, so everything is recoverable. Logs to `LAB_LOG.md`.
- **Answer level:** needs the `before-delete` answers file with every question answered (§7).

**Blocking the other doors**
- **Claude hook:** blocks `rm`, `rmdir`, `del`, `erase`, `rd`, `Remove-Item` (and `ri`, `rm` aliases), `git clean`, `git reset --hard`, `git checkout -- .`, `find … -delete`, and Python/Node one-liners calling `rmtree` / `unlink` / `remove` / `rmSync`. It injects `before-delete` and points to `ra_gate.py remove`. Worker sessions (hook payload has `agent_id`) are blocked even from `remove`.
- **OpenCode:** permission rules deny the same patterns.

## 7. Injection templates

**Location:** `resources/injections/<moment>.md`. Each file has frontmatter `moment`, `level: remind|answer`, `placeholders`, then numbered questions. A renderer in `ra_common.py` (`render_injection(moment, **facts)`) fills `{placeholders}` with live facts. A missing fact prints `{unknown: name}`, never a silent blank. Kano can edit the questions without touching Python.

**Two levels (my call; it follows the memory note "only a named rule + worked example moves a model"):**
- `remind`: injected only.
- `answer`: the gate stops until `research/answers/<moment>_<n>.md` answers every numbered question. A bare "yes", "ok" or "done" doesn't count, and an answer must give a reason or a fact.

| Moment | Level | Fires (Claude hook / every harness via the scripts) |
|---|---|---|
| `session-start` | remind | SessionStart and after compaction / `status`, `resume` |
| `worker-handover` | answer | worker report returns / `return-baton` |
| `review-meeting` | answer | before the next dispatch / `review` |
| `before-build` | remind | Stage 2 → 3 / `advance` |
| `before-delete` | answer | delete command blocked / `remove` |
| `before-other-agent` | answer | other-agent launch blocked / `--platform <other>`, `allow-agent` |
| `before-graduation` | answer | `graduate` |
| `worker-dispatch` | remind | Agent/subagent call / `fork` |
| `expert-handover` | answer | (v1.7 field experts) / `panel` |

**Question content.** The builder writes the full templates and Kano reviews them.
- **Worker handover:** Did you run it on real data? Is any data made up, padded or copied from the example? Is any "new" method a renamed existing one, and if so, which? Does it work as intended, as checked by what? List your factors and reasons. Where are you sure, and where are you guessing?
- **Review meeting** (asking back, with lab-report facts filled in): "`{approach}` has had `{rounds}` rounds, best `{best}`, against target `{target}`. Is it worth another try? Why, in numbers?" "What does the graveyard say was tried before: `{graveyard_facts}`?"
- **Before build:** Does this serve the purpose in `VISION_AND_MISSION.md`? Would a user find this feature reasonable?
- **Before delete:** Kano's four (inside the sandbox / does anything depend on it / is it the user's data / can it be recovered).
- **Before other agent:** Which grant covers `{agent}`? Quote the user's words. If none, stop.
- **Before graduation:** Does it work as intended, for the user, on data it never saw? Was anything faked? What would the user notice first?
- **Worker dispatch:** One fresh worker per task. Reusing a worker's session is allowed only for the same worker continuing its own task. This is the 2026-11-11 Qwen case: a new task was sent into `Subagent_TESTSET`'s session under a new name.

## 8. Files touched

- `scripts/ra_common.py`: `resolve_identity`, `render_injection`, the answers checker, permission load/save, the delete-path classifier.
- `scripts/ra_gate.py`: `allow-agent`, `revoke-agent`, `remove`. Answer-level checks in `review`, `advance`, `graduate`. Identity everywhere `--agent` is written.
- `scripts/ra_context_harness.py`: env-only `detect_platform`, own-harness-only dispatch output, the grant check, identity.
- `scripts/ra_hooks.py`: PreToolUse Bash/PowerShell classifier (other-agent launch or lookup, delete), injection rendering, the worker-delete block.
- `scripts/ra_forge.py`: also writes OpenCode project permission rules.
- `scripts/ra_log_engine.py`, `ra_cheese_audit.py`, `ra_crawler.py`: identity for any `--agent` they record.
- New: `resources/injections/*.md` (9 templates).
- `SKILL.md`: a short "Safety harness" section (identity, permissions, one door for deletes, templates). Every `rm`-style instruction in SKILL.md and the references changes to `ra_gate.py remove`.
- `README.md`, version → 1.6.0.

## 9. Verification (before claiming done)

1. **Unit:** the classifier on a fixed list of commands, both what must block and what must pass (e.g. `rm -rf research/sandbox/x` blocked outside `remove`; `git status` passes; `C:\...\claude.exe -p` blocked; `cat claude_notes.md` passes). The path classifier covers `~1` short names, junctions, `..` and other drives. The renderer covers missing facts.
2. **Scenario:** a gate run in a temp workspace: `remove` of a sandbox file goes to `.trash`; a protected record is refused; an outside path is refused; an answer file with "yes" is refused; `allow-agent` without a quote is refused.
3. **Live Claude Code:** `claude -p` on the installed skill tries `rm -rf` and `claude --version` lookups and is blocked with the template.
4. **Live OpenCode + Qwen** (Kano: "qwen open code is free now. test a few scenario later"): identity resolves to `opencode:llamacpp/qwen3.8-flash-next`; `--agent claude-opus-5-5` is overridden; launching `claude` is denied by the rule; `rm` is denied and `ra_gate.py remove` works.

## 10. Who decided what

**Kano:** everything quoted. In particular: agents know their own names; no use of another agent without user permission (a `use=true` grant from his words); no discovery of agents on the PC; deletes go through the manager with an injected check that it's sandbox and not user data; injections are full template files of generic questions; build it, then test scenarios with OpenCode + Qwen.

**My calls:** per-project permissions file; `remove` moves to `.trash` instead of deleting; the protected-record list; the remind/answer levels and which moments are Answer; the nearest-ancestor rule for nested harnesses; blocking agent-CLI lookups in the Claude hook; workers can't use `remove`; v1.6 safety harness before v1.7 field experts.

**Left to the builder:** the exact OpenCode permission config syntax (verified live); the classifier's regexes; the template wording (Kano reviews it); the answers-file format details.
