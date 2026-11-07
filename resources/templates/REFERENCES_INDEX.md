# Ground-Truth Library & User Reference Index

> **Managed by RA (`research-anything`)** — **MANDATORY SEARCH GATE**: Before asking the user ANY question, the agent must inspect this file and all `reference/`, `references/`, `assets/`, `docs/`, and `research/library/` directories (including viewing images!).

## 1. User-Provided Reference Assets & Visuals (`[USER_GROUND_TRUTH]`)

| Ref ID | File / Image Path | Date Indexed | Visual / Content Description | Extracted Hard Constraints & Measurements |
| :--- | :--- | :--- | :--- | :--- |
| `REF-001` | `<e.g., reference/layout.png>` | `<YYYY-MM-DD>` | `<What is shown in the image/file>` | `<Exact dimensions, rules, connections extracted>` |

---

## 2. User Clarifications & Intent Ledger (`[USER_DECISION]`)

| Q&A ID | Topic | User Answer / Decision | Date |
| :--- | :--- | :--- | :--- |
| `QA-001` | `<Topic>` | `<Exact constraint or preference stated by user>` | `<YYYY-MM-DD>` |

---

## 3. Verified External Laws & Priors (`[EXTERNAL_VERIFIED_LAW]`)

| Law / Doc ID | File in `research/library/` | Provenance / Citation | Summary of Ground Truth |
| :--- | :--- | :--- | :--- |
| `LIB-001` | `research/library/<file.md>` | `<Source/Paper/Spec>` | `<Verified formula, physical constant, or spec>` |

---

## 4. Graduated Lab Discoveries (`[GRADUATED_LAB_TRUTH]`)

| Discovery ID | Source Hypothesis | File in `research/library/` | Verified Mechanism & Boundaries |
| :--- | :--- | :--- | :--- |
| `GRAD-001` | `H001_<slug>` | `research/library/<file.md>` | `<Proven mechanism that survived Stage 1, 4, 5, and 7>` |
