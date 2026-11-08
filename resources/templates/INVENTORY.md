# Inventory, Triage & Brick

> **Managed by RA.** Filled in Stage 0, before any hypothesis. Nothing gets built from scratch if it is already on this list.

## 1. What We Already Have (Take Stock)
> Every asset, dataset, recording, dump, table, script, model and tool the user provided or the repo holds. Open images and sample files — don't list by filename alone.

| Item | Path | What it is / what it can answer | Used yet? |
| :--- | :--- | :--- | :--- |
| <Asset / data / code / tool> | `<path>` | <what it holds, how much> | <YES / NO — why not> |

## 2. Parts Triage (Known vs. Unknown)
> Split the product into parts. **Known** must be earned: name the existing solution AND the evidence it fits *this* project's constraints. "Looks similar" is not evidence.

| Part | KNOWN / UNKNOWN | Existing solution or why unknown | Evidence it fits (if KNOWN) |
| :--- | :--- | :--- | :--- |
| <part> | <KNOWN / UNKNOWN> | <solution / gap> | <measured fit, doc, test on real data> |

## 3. The Brick (Crudest End-to-End Version That Runs)
> The whole product path running once with the dumbest possible parts. Polish no part until the brick runs.

- **End-to-end path**: <input -> part -> part -> ... -> output the user cares about>
- **Brick status**: <NOT BUILT / RUNS (date, command, result)>
- **Weakest link right now**: <the one part that limits the brick most, with the number that proves it>
