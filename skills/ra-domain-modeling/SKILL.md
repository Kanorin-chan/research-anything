---
name: ra-domain-modeling
description: Actively build and sharpen a project's domain model, shared vocabulary (GLOSSARY.md), locked architectural invariants (research/INVARIANTS.md), and ADRs. Use when discussing codebase terminology, resolving overloaded words, or locking project rules.
---

# RA Domain Modeling (`ra-domain-modeling`)

Actively build and sharpen the project's shared domain language and non-negotiable invariants as you converse with the user.

## 1. File Structure

```text
/
├── GLOSSARY.md                     # Ubiquitous domain vocabulary (zero implementation noise)
├── docs/
│   └── adr/
│       └── 0001-<decision>.md      # Hard-to-reverse architectural trade-offs
└── research/
    ├── VISION_AND_MISSION.md       # North Star project vision & tracks
    └── INVARIANTS.md               # Locked project rules (`INV-001`, `INV-002`...)
```

Create files lazily—only when you have resolved terms or invariants to record.

## 2. Active Discipline During Conversation

1. **Challenge Against `GLOSSARY.md` & `INVARIANTS.md`**:
   - When the user uses a term that conflicts with `GLOSSARY.md` or `INVARIANTS.md`, surface it immediately: *"Your glossary defines `Dispatch Ledger` as session-monotonic, but you seem to mean per-frame. Which is it?"*
2. **Sharpen Fuzzy or Overloaded Language**:
   - When one word is doing three jobs (e.g., `"state"`, `"session"`, `"unit"`), propose distinct canonical terms so the codebase and agent prompts stay concise and unambiguous.
3. **Stress-Test With Concrete Edge-Case Scenarios**:
   - Probe boundaries between domain concepts with concrete scenarios (*"What happens when a retry frame arrives after Unit A was already dispatched in the same session?"*).
4. **Cross-Reference With Code (Zero-Trust Comment Rule)**:
   - Check whether the live code matches what is being discussed—and **never blindly trust bare code comments** (`# doesn't work`, `# added to fix stuck bug`) unless backed by empirical `.log` or Lab Report evidence.
5. **Update `GLOSSARY.md` and `research/INVARIANTS.md` Inline**:
   - Capture resolved terms in `GLOSSARY.md` (see [GLOSSARY-FORMAT.md](./GLOSSARY-FORMAT.md)) and non-negotiable architectural laws in `research/INVARIANTS.md` (`- **INV-xxx**: ...`) the moment they crystallize.
6. **Offer ADRs Sparingly**:
   - Only create an ADR (`docs/adr/NNNN-<slug>.md`, see [ADR-FORMAT.md](./ADR-FORMAT.md)) when a decision is **(a) hard to reverse**, **(b) surprising without context**, and **(c) the result of a real trade-off**.
