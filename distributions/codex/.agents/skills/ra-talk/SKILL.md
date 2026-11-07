---
name: ra-talk
description: Stateful project conversation, design interview, and shared-language builder (updates GLOSSARY.md, VISION_AND_MISSION.md, and INVARIANTS.md without writing code).
disable-model-invocation: true
---

# RA Talk — Stateful Project Conversation & Design Grilling (`ra-talk`)

Use this skill when the user wants to **talk through a project, brainstorm a design, sharpen requirements, or align on domain language** without jumping into code or running all 8 R&D stages.

## Mandatory Step 1: Look Before You Ask (`check-question`)
Before asking the user a single question, run the RA Pre-Question Search Gate:
```bash
python "~/.agents/skills/research-anything/scripts/ra_gate.py" check-question --workspace "."
```
Open and read any discovered `GLOSSARY.md`, `research/VISION_AND_MISSION.md`, `research/INVARIANTS.md`, `research/WORKFLOW_MAP.md`, and any images/diagrams in `reference/`, `references/`, `assets/`, or `docs/`. **Never ask the user for a fact that is already on disk.**

## Mandatory Step 2: Run the Interview & Domain-Modeling Primitives
Call the Skill tool twice, for `"ra-grilling"` and `"ra-domain-modeling"`.

## Mandatory Step 3: Persist Decisions Inline & Stop Cleanly
- As decisions and domain terms crystallize during the conversation:
  1. Update `GLOSSARY.md` inline with canonical domain terms.
  2. If `research/` exists (or if the user wants to lock project vision/rules), update `research/VISION_AND_MISSION.md` and `research/INVARIANTS.md` inline.
- **Do NOT write application code during `/ra-talk`.** When every branch of the design frontier is resolved and the user confirms shared understanding, summarize the locked decisions and ask if they want to stop here or move into `/ra-workflow-map`, `/ra-systemic-debug`, or `/research-anything`.
