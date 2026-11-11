# RA Field Experts: design

Date: 2026-11-11 · Target: RA v1.6.0 · Status: draft for Kano's approval

## 1. Why this exists

RA goes blind while it works. In Kano's words: "when RA works, it tends be be blind. like hes working on one things. and it already has its own "way" right?" Sub-agents don't fix this. They only see what the blind manager writes in their brief, so they inherit the same blind spot.

The deeper cause, also from Kano: the model already has the knowledge, but it never fires because nothing in the context points at it. "if llm already have the knowledge, but llm cant build it, because the context was never loaded." "those knowledge either weight too less, your neural network wasnt able to fires on it." The result is "llm tend to stuck. build a half working system."

What fixes it: **listing loads the shelf.** "i had to ask you: in sorting algo: tell me every existing algo." Once every method in a field is written down, the model can't ignore it: "now you have all sorting algo in your list. written in paper. and you cant ignore that because it was there."

So this feature makes RA summon experts from different fields, with the context injected. Each expert writes out its field's full catalogue, then proposes its best approach and argues for it. The proposals get ranked, and the ranking becomes RA's fallback ladder.

The user-facing goal: "the main agent should provide solution instead, not just let user Think of what can do. We want to help people to stress less." The user brings the idea and some technical parts, "and rest should be handle by the llm."

Evidence from the 11-08 cooptd analysis: a fresh agent given the stuck state dropped the dead end at once, and 5/5 fresh agents produced 3-5 distinct approach families. The ideas exist. The main agent's own sweep is written from inside its anchor. This feature moves the sweep out of the manager's head.

## 2. What it is (and how it differs from `perspectives`)

A new RA sub-skill, **`ra-field-experts`** (name is my call, see §9), plus gate and hook changes in `research-anything`. Kano: "we build in instead of using perspective. and its a little different from perspective."

- `perspectives` brings in viewpoints to **react to** something that exists: critics, stakeholders, "what would X think". It judges.
- `ra-field-experts` brings in **domain experts to compete with solutions** before anything is chosen. Each one argues "why my field's approach is better, logically". It generates rival options, ranks them, and keeps the losers as fallbacks.

Kano's examples, all in scope (RA is not code-only):
- Algorithm: "should using sorting > their branches better in this? or do signal processing. or pathfinding."
- Design: "curtain design. 5 different with diff skill set and pattern design. suggest their best."
- Software: "on a system proposed; each agent propse why their framework better; and why use them."
- Research: "each propose why their skills/function are better. why. logically. ranks them. if option A fail, always can fallback to option B."

## 3. Goals, non-goals, anti-goals

**Goals**
1. At the two required moments (§4), RA cannot move on until a panel of field experts has run, been ranked, and been registered.
2. Each expert loads its field's knowledge by **listing it by name first**, then proposes.
3. The ranking feeds the existing machinery: the Option Sweep families, the `--if-never-works` fallback, `ceiling` estimates, and the next family after a cold-review `SWITCH`.
4. "Everyone says no" produces build targets, not a dead end (§5.5).
5. Works on every harness RA supports. Gate checks live in `ra_gate.py`, not only in Claude Code hooks.

**Non-goals**
- Not replacing `perspectives`, the cold reviewer, or review meetings. Those stay as they are.
- Not making the experts write code. They think and propose. Builders build.
- Not changing the plateau lock or the scoreboard.

**Anti-goals** (failure even if it technically works)
- **Experts that agree.** If two experts propose the same approach, the fields weren't distinct. That panel failed.
- **Generic personas.** "You are a signal processing expert" plus a vague answer is the failure mode. The catalogue of concrete names is the whole point.
- **Handing the choice back to the user.** The Autonomy Contract stands: RA races the top options, it doesn't ask "A or B?".
- **A token burst on every small decision.** Required only at the two moments. Optional use is 1-2 small experts.
- **A blind manager ranking its own experts.** The manager is the anchored one (§5.4).

## 4. When it runs

Kano: "its not a "must: but require to at this two. other times still can trigger like why not. one or two small agent with different perspective helps."

| Trigger | When | Required? | Panel size |
|---|---|---|---|
| `PURPOSE` | Start of a new project: "whats your purpose of this idea." The idea "came from weird places … our brain tell us there are possibility of making it. but we dont know anything technical. there goes your part. research. find. and work on it." | **Yes**, gate-enforced | 3-5 experts + 1 ranker |
| `CORE_MECHANIC` | Mid-project, a decision that shapes the architecture: "core mechanics/function. that deciding the whole architecture. everything builds around it." | **Yes**, gate-enforced | 3-5 experts + 1 ranker |
| `ADHOC` | Any other time the manager wants other eyes | No | 1-2 experts, ranker optional |

**Deciding what counts as a core mechanic** (my call): Section 3 of `REPORT.md` gets a line `Core mechanic: YES|NO: <reason>`.
- The first hypothesis (the brick) is always YES.
- A NO needs a written reason. The reason is shown on the lab board, and the cold reviewer is told to challenge it. This stops the blind manager from quietly labelling everything NO.

## 5. How a panel runs

### 5.1 Open the panel (manager)
`ra_gate.py panel-open --id P001 --slug <name> --trigger PURPOSE|CORE_MECHANIC|ADHOC [--hypothesis Hxxx] --fields "<a>; <b>; <c>"`

The manager first answers Kano's question, "who are in the field of study", and writes `research/panels/P001_<slug>/FIELDS.md`. For each field: why it could own this problem. Fields must be different families (e.g. sorting, signal processing, pathfinding), not variants of one.

### 5.2 Brief and dispatch the experts (manager)
One brief per field from a new template, `resources/templates/EXPERT_BRIEF.md`. "each of the agent are spawn with dedicated "profession" and they are limited to work on their sector point of view."

The brief contains: the profession, the aim (from `VISION_AND_MISSION.md`), the exact question, the `INVARIANTS.md` rules, and the output format in §5.3. For a core mechanic, attach the existing `WORKFLOW_SLICE` snapshot so the expert knows the real system. Experts get no project history and no manager opinions. That's what keeps them unanchored.

Dispatch goes through `ra_context_harness.py fork`, so it works on Claude Code, OpenCode, Codex and Antigravity. On 1-concurrency setups (local Qwen) the experts run one after another as a baton relay.

### 5.3 What each expert writes
File: `research/panels/P001_<slug>/EXPERT_<field-slug>.md`. Required parts, in this order:

1. `FIELD: <name>`
2. `CATALOGUE:` **list first, then think.** Every method, technique, algorithm, pattern, library or paper in the field that relates to the question, **by its real name**, one line each. Gate tripwire: at least 8 named entries (my number, the builder may tune it). Category names ("tree-based methods") don't count.
3. `FITS:` which catalogue entries could apply here, and why.
4. `PROPOSAL:` the field's best answer, with `Predicted outcome:`, `Pros:`, `Cons:`, `Fit:` (suitability for this project), and `What it takes to build:`. Kano: "it ranks based on their predicted outcome. pros and cons. and buitability."
5. `VERDICT: YES | NO | PARTIAL`
6. If NO or PARTIAL: `WHY_NOT:` lines, each tagged `REAL_LIMIT` or `PRACTICAL_LIMIT`, each with an `ESCAPE:` (§5.5).
7. `OUTSIDE MY FIELD:` optional. If the expert spots an approach from another field, it names it here and does not argue for it.

### 5.4 Rank (fresh ranker, not the manager)
My call: a fresh sub-agent ranks, because the manager is the anchored party. It reads only `FIELDS.md` and the expert files, and writes `research/panels/P001_<slug>/RANKING.md` with:

- `RANK <n>: <field>: <approach>`, with predicted outcome, pros, cons and fit, best first.
- `HYBRIDS:` combinations across fields worth trying. Kano: "i want to sorta make a algo of A + B. merging this two."
- `FALLBACK:` the ordered ladder. "if option A fail, always can fallback to option B."
- `MISSING FIELD:` optional, at most one. If the ranker sees a field nobody covered, one more expert runs before the ranking is final.
- For `PURPOSE` panels: `WHY IT EXISTS:` the idea's purpose against the catalogues: what gap it fills, what it borrows, and where it beats the existing methods. Kano: "if i were creating a new algo. i must know why mine exist, and purpose. so getting the whole list, propose my idea."

Register it with `ra_gate.py panel --file research/panels/P001_<slug>/RANKING.md`. The gate validates the format: required lines, at least 3 ranks for required panels, every rank naming a field that has an expert file, and an expert file with ≥ 8 catalogue entries behind every field.

### 5.5 When everyone says no
Kano: "if all expert in the field say no. is it the end? no. We still can make possibility. like learn from them. why cant. and what makes sense. creating a new framework, function, architecture, library. everything is possible." His example is game physics, which nobody believed in until people built engines, libraries and frameworks for it, "and here we are. physic engine are general in all places".

Every `WHY_NOT` is sorted into one of two kinds:
- `REAL_LIMIT`: proven, or physics. The `ESCAPE` names the assumption to drop. Example: comparison sorts are proven unable to beat n log n, and radix sort gets around that by not comparing.
- `PRACTICAL_LIMIT`: too slow, too costly, or nobody has tried. The `ESCAPE` names what would have to be built: a new library, framework, function or architecture.

If every expert says NO, the ranking's `FALLBACK` is replaced by `BUILD TARGETS:` (from the practical limits) and `ASSUMPTIONS TO DROP:` (from the real limits). The next hypothesis builds the top target. A panel that is all NO is valid and registrable, not a blocker.

## 6. How the ranking plugs into RA

- **Option Sweep:** for a `CORE_MECHANIC` hypothesis, Section 3's ≥ 3 families must include the panel's top 3 ranks. The gate checks that the names appear.
- **Fallback:** `stop-rule --if-never-works` should name the next rank. When a cold review says `SWITCH`, the board shows the next unused rank as the next family.
- **Ceiling:** an expert's predicted outcome is the starting basis for `ra_gate.py ceiling --basis "panel P001, expert <field>"`.
- **The builder carries the shelf** (my reading of "written in paper, can't ignore it"): the worker brief for the chosen approach includes the winning expert's `CATALOGUE` and `PROPOSAL` verbatim, so the builder is primed with the same names. The names are short, so this is cheap.
- **Board:** `ra_gate.py board` lists open and registered panels, the current rank in use, the remaining fallbacks, and every `Core mechanic: NO` reason.
- **Decisions:** registering a panel writes a `decide` entry to `research/DECISIONS.md` (rank 1 chosen, alternatives = the rest).

## 7. Gate and hook changes

**`ra_gate.py`** (works on every harness)
- New commands: `panel-open`, `panel` (register a ranking). `status` and `board` show panels.
- Stage 0 → 1: blocked for a **new** project until a `PURPOSE` panel is registered. Today this transition has no checks.
- Stage 2 exit: if `Core mechanic: YES`, blocked until a `CORE_MECHANIC` panel for this hypothesis is registered and the Option Sweep includes its top 3. If NO, blocked without a reason.
- Existing projects (e.g. `F:\cooptd-rebuild`, already past Stage 0): no retroactive Stage 0 block. `resume` prints that no `PURPOSE` panel exists and recommends running one. The core-mechanic rule applies from their next hypothesis.

**`ra_hooks.py`** (Claude Code; also the forge-armed project hooks)
- **Known conflict:** today the PreToolUse hook blocks any new Agent dispatch while a worker's report is unreviewed. A panel of 3-5 experts would block after the first report, and always on 1-concurrency setups. Fix: while a panel is open, its expected expert names (from `panel-open`) and its ranker are exempt from the review-pending block. Registering the ranking with `ra_gate.py panel` counts as their review meeting and clears them.
- No other hook changes. The manager still may not write code. Experts and the ranker write only `.md` under `research/panels/`.

## 8. Files touched (for the plan)

- New: `skills/ra-field-experts/SKILL.md` (+ `agents/openai.yaml`, matching the other sub-skills): the panel procedure, optional-use triggers, the brief rules.
- New templates in `resources/templates/`: `EXPERT_BRIEF.md`, `EXPERT_REPORT.md`, `PANEL_RANKING.md`, `FIELDS.md`.
- `SKILL.md` (root, mirrored by the installer): Product Loop step 5 (the sweep comes from a panel for core mechanics), Stage 0 (`PURPOSE` panel), Stage 2 (core-mechanic line), red flags ("Option Sweep families that all come from one field").
- `resources/templates/HYPOTHESIS_REPORT.md`: the `Core mechanic:` line in Section 3.
- `scripts/ra_gate.py`, `scripts/ra_common.py` (panel state, exemption list), `scripts/ra_hooks.py` (exemption).
- `install.py`: add `ra-field-experts` to `ALL_SKILLS`.
- `skills/ra-ask/SKILL.md`: add the new skill to the router.
- `README.md`: new section and commands. Version → 1.6.0.
- Verification as in 1.4 and 1.5: a scenario run of the gate (new project blocked at Stage 0 until a panel exists; core-mechanic block; all-NO panel registers; panel experts not blocked by review-pending), plus an end-to-end `claude -p` run on the installed skill.

## 9. Who decided what

**Kano decided:** everything quoted above, in particular: built into RA, not `perspectives`; the manager names the fields; one profession per expert, limited to its field; list-first priming; ranking by predicted outcome, pros, cons and suitability; the A-to-B fallback; A + B merging; "all say no" is not the end; required at the start (purpose) and at core mechanics, optional elsewhere with 1-2 small agents; real testing later on a different project ("we fix the skill first").

**My calls (Kano can overrule):** the name `ra-field-experts`; a fresh ranker instead of the manager; `Core mechanic: YES|NO` with the brick always YES and NO needing a reason; the 8-entry catalogue tripwire; 3-5 experts at required moments; `REAL_LIMIT` / `PRACTICAL_LIMIT` sorting; the builder carrying the winning catalogue; no retroactive Stage 0 block on existing projects; file layout under `research/panels/`.

**Left to the builder:** exact gate message wording; validation regexes; state-file schema; how `panel-open` names the expert workers so the hook can match them; scenario-test structure.

## 10. Builder-check resolutions (2026-11-11)

Ships as **v1.7.0, after the safety harness** (`2026-11-11-safety-harness-design.md`, v1.6.0). It reuses that harness's identity, injection templates and dispatch rules.

**Kano's answers:**
- **Past failures reach experts and the manager as asked-back questions, built from the lab reports.** "these all should already written into lab report no? more like the main agent wont read or find that file … there goes the hook/injection context … using a "asking back" like: "Do you think this skill/function is worth try after x amount"". The scripts pull the graveyard and scoreboard facts (`X tried, scored 0.31, failed because Y`) into every expert brief and into the review-meeting injection, with no manager reasoning. An expert may re-propose X only by explaining how it avoids Y.
- **Memory and research together, plus a self-check before handover.** "memory + research should being together. even you might did that, like making a same algo A, change name to algo B, and faking data … are you sure you are making the correcting? double check. List down your own factor and reason why. > hand over to main agent." Experts list from memory first, then check the names the proposal relies on. Before handover they answer the `expert-handover` injection (Answer level): names checked vs memory-only, the nearest existing method and the concrete difference, their own factors and reasons. `panel` refuses an expert file without those answers.
- **Identity and agent permissions** became their own part (the safety harness).

**My calls (from the 9 reviewer questions):**
1. **Panels only for full RA projects.** Stage 0 gating covers every exit (`advance`, `map-context`, `new-hypothesis`), but only on workspaces created by `ra_gate.py init` for a new idea. Workspaces made by `/ra-workflow-map` or `/ra-systemic-debug` are exempt, and so are their bug-fix hypotheses.
2. **A panel belongs to a mechanic, not a hypothesis.** Key = the stop-rule `--component` slug. Later hypotheses on the same component inherit it. The next unused rank is the default for `--if-never-works` and after a cold-review `SWITCH`. The reviewer may name another rank or a hybrid, but must say which. A new panel runs only when the ladder is used up.
3. **The `PURPOSE` panel counts for H001.** `WHY IT EXISTS` goes into `VISION_AND_MISSION.md`. The ranks become H001's Option Sweep and mark INVENTORY parts KNOWN/UNKNOWN. "No gap found" is a vision question, so RA asks the user once, with its recommendation.
4. **Expert inputs:** a fresh session (never a native session fork), aim, question, invariants, and the bare-facts failure list. No `SELF_LEARNING` narrative, no directives beyond invariants, no manager notes. `ra_context_harness.py fork` gets an `--expert` mode that does this and doesn't require a snapshot at Stage 0.
5. **NO and PARTIAL:** NO proposals don't take a rank. A required panel needs ≥ 3 viable ranks, or else its empty sweep slots are filled from `BUILD TARGETS`. An all-NO core panel in Stage 2 rewrites the current hypothesis's sweep to the build targets.
6. **The gate checks that experts really ran:** `panel` requires a fork record and a returned baton for every expert and for the ranker.
7. **Challenging `Core mechanic: NO`:** the cold review gets an optional `CORE MECHANIC: YES` line. It forces a panel before the next hypothesis on that component. Verdicts and the plateau lock stay unchanged.
8. **Duplicates:** the ranker writes `DUPLICATE: <field> = <field>`. With fewer than 3 distinct ranks left, `panel` refuses registration and tells the manager to add one expert from a new field.
9. **Unchecked names** carry `[MEMORY]` until verified (`[CHECKED: <source>]`). Only the winning proposal's names must be `[CHECKED]` before Stage 2 exit.
