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
