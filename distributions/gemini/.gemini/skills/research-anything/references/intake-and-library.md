# Intake, Zero-Repeat Question Protocol & Ground-Truth Library

This reference governs **Stage 0** of **RA (`research-anything`)**: how the agent listens to the user's raw idea, prevents stupid/repeated questions, indexes reference assets, and maintains a strict firewall between speculation (`hypotheses/`) and reality (`library/`).

---

## 1. Conversational Idea Intake (Gather 1-by-1)

When a user brings a new project idea, algorithm concept, hardware layout, material study, or complex system:
1. **Do NOT dump a massive questionnaire** and **do NOT jump straight into writing boilerplate code**.
2. **Let the User Talk 1-by-1**:
   - Listen as the user explains each piece of their idea.
   - Reflect back the structural essence of what they said so they know it is locked in.
   - Ask only sharp, high-leverage questions about *intent* or *trade-offs* when genuine ambiguity exists.
3. **Synthesize into `research/VISION_AND_MISSION.md`**:
   - **Vision**: The ultimate capability, behavior, or discovery the project aims to achieve.
   - **Mission & Non-Negotiables**: Core architectural principles, forbidden shortcuts, and target environment.
   - **Research Tracks**: Decompose the overarching idea into independent, testable research tracks (`Track A`, `Track B`, `Track C`) so each hypothesis tests one fundamental mechanism at a time.

---

## 2. The "Never Ask a Stupid or Repeated Question" Protocol

One of the worst failure modes of AI coding agents is asking the user for information the user already provided earlier, or ignoring reference images/files sitting right in the workspace.

### Rule A: Immediate Asset & Answer Indexing (`research/library/REFERENCES_INDEX.md`)
Whenever the user:
- Sends or points to an image, diagram, screenshot, or datasheet
- Drops files into `reference/`, `references/`, `assets/`, or `docs/`
- Answers a clarifying question in chat

You **must immediately** log an entry in `research/library/REFERENCES_INDEX.md` containing:
- **Asset/Topic ID & Exact Path** (e.g., `reference/cpu_thermal_layout_v2.png`)
- **Visual/Content Summary**: What you observed when reading/viewing the file or image
- **Extracted Hard Constraints**: Exact measurements, connections, formulas, or layout rules derived from it

### Rule B: Mandatory Search Gate Before Asking Any Question
Before you are permitted to ask the user **any** question during research, implementation, or debugging, you **must** execute all four checks:
1. Read `research/VISION_AND_MISSION.md` and `research/INVARIANTS.md`.
2. Read `research/library/REFERENCES_INDEX.md` and scan all directories named `reference/`, `references/`, `assets/`, `docs/`, and `research/library/`. **If image files exist, open and view them with your file-reading tool.**
3. Read `research/LAB_LOG.md` and `research/SELF_LEARNING.md`.
4. Ask yourself: *"Can I answer this question myself by inspecting the workspace or running a 10-second verification script?"*
   - If **YES**, you are **strictly forbidden** from asking the user. Run the check yourself.

---

## 3. The Ground-Truth Library Firewall (`research/library/`)

LLMs frequently confuse their own unverified hypotheses with real-world facts, or hallucinate physical constants, mathematical identities, and hardware specifications from fuzzy memory.

To prevent this, **RA enforces a hard firewall between `research/hypotheses/` and `research/library/`**:

| Directory | Contents | Trust Level |
| :--- | :--- | :--- |
| `research/hypotheses/Hxxx/` | What the agent *thinks* might work and is actively testing. | **Speculative / Under Test** |
| `research/graveyard/Hxxx/` | Approaches proven false in the lab, with exact failure evidence. | **Falsified (Do Not Reuse)** |
| `research/library/` | **Undisputed Ground Truth**: Real-world laws, verified external specs, user-supplied reference truths, and mechanisms that survived 100% of adversarial verification and user graduation sign-off. | **Hard Ground Truth** |

### Strict Library Rules
1. **Never pollute `research/library/` with unverified theories**: Conjectures, untested formulas, and work-in-progress designs belong strictly in `research/hypotheses/`.
2. **Every file in `research/library/` must carry a Provenance Tag** at the top:
   - `[USER_GROUND_TRUTH]`: Provided directly by the user (e.g., reference diagrams, target specs, lab measurements).
   - `[EXTERNAL_VERIFIED_LAW]`: Established mathematical theorem, physical law, or official hardware/API specification (with exact source citation).
   - `[GRADUATED_LAB_TRUTH]`: Internal discovery that survived Stage 3 (Adversarial Break-Testing), Stage 4 (Anti-Cheese Audit), and Stage 6 (User Graduation Sign-Off).
