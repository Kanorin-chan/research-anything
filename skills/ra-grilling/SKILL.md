---
name: ra-grilling
description: Grill the user relentlessly about a plan, project, decision, or architecture until every branch of the design tree is resolved. Use when the user wants to talk through an idea, stress-test their thinking, or uses 'grill' / 'talk about the project' trigger phrases.
---

# RA Grilling (`ra-grilling`)

Interview the user relentlessly until you reach a complete, shared understanding of the project, feature, or mechanism. Map the problem space as a **design tree**: every decision branches into the downstream decisions that depend on it.

## 1. Zero-Repeat Question Rule (Facts Are Your Job, Decisions Are the User's)
- Finding *facts* from the codebase, reference images, or docs is **your job, never the user's**.
- Before asking any round of questions, run `ra_gate.py check-question --workspace "."` (or dispatch a read-only subagent with a fresh context window) to inspect the filesystem, `GLOSSARY.md`, `reference/`, `assets/`, and `research/` files.
- Never ask the user a question that is already answered in a reference image, file, or past report.
- Only put genuine **design decisions and trade-offs** to the user.

## 2. Work the Frontier in Rounds
The **frontier** is every decision whose prerequisites are already settled: the questions you can ask *right now* without guessing at answers you haven't heard yet.
- Ask the current frontier in one round, numbering each question and providing your **recommended answer** with first-principles reasoning.
- Format every round like so:

```markdown
❓ **Q1** - **<question title>**: <question body, concrete options, and trade-offs>

➡️ **Recommended**: <your recommended answer and why>

---

❓ **Q2** - **<question title>**: <question body, concrete options, and trade-offs>

➡️ **Recommended**: <your recommended answer and why>
```

- Word each question so replying **"yes"** accepts your recommended answer.
- Wait for the user's answers before asking the next round. Each answer reshapes the design tree and unlocks the next frontier.
- The session is complete when the frontier is empty (every branch of the design tree visited, zero silent assumptions left). Do not write code until the user confirms shared understanding.

## 3. Mandatory Anti-Rabbit-Hole Branches (Never Leave a Mechanism Without a Stop Rule)
Before declaring the frontier empty on any plan, tracker, parser, or heuristic, ensure your design tree has explicitly locked these 5 branches (and recorded them via `ra_gate.py stop-rule`):
1. **What It Is Actually For (Reliable vs. Weak Split)**: What decision does this metric/component drive, which parts are *already* 100% reliable, and what is the single weak part?
2. **Success Criteria (Full-Load + Error Asymmetry + Speed)**: How accurate must it be on the **hardest/crowded unseen cases** (not just light/easy cases), which error direction is worse (False Positive vs. False Negative), and what is the runtime budget?
3. **Hard Stop Rule (Kill-Switch Round Limit)**: After how many failed unseen-test rounds (e.g., `1` or `2` rounds) do we **stop** tweaking this heuristic instead of looping `fail -> fix -> retest` forever?
4. **"If It Never Works" Pivot Plan (Ground-Truth Fallback)**: If the heuristic hits the Stop Rule, what deterministic/UI-native source of truth replaces it (e.g., tapping/reading the authoritative UI card, reading the end-of-run summary table, or leaning on already-reliable metrics) so the main rebuild **never waits on a brittle side-quest**?
5. **When the Whole Rebuild / Project Stops**: What is the end-to-end win condition across multiple real runs + user sign-off?
