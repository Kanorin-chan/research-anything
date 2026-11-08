---
name: ra-anti-cheese
description: Cryptographically seal legitimate AXIOMATIC_PRIMITIVES, scan code for hardcoded lookup tables and symptom-swallowing band-aids, and forge project-local .py hooks and the cold-eyes ra-reviewer agent. Use when auditing code integrity or setting up project guardrails.
---

# RA Anti-Cheese, Axiom Seal & Project Guardrail Forge (`ra-anti-cheese`)

Use this skill standalone (or during Stage 0/3/5/7 of `research-anything`) to enforce zero-cheese, zero-band-aid engineering, expose polluted vibe-code in existing projects, and run cold-eyes diff verification.

## 0. Mid-Project / Vibe-Coded Intake: Expose Band-Aids, Fake Data & Polluted Pipes (`--scan-project`)
When joining a project that did **not** use RA from the beginning (or after previous AI sessions left behind hidden shortcuts), scan the entire codebase to generate a **Truth-Path Recovery Plan (`research/TRUTH_PATH_AUDIT.md`)**:
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_cheese_audit.py" \
  --workspace "." \
  --scan-project
```
Exposes all existing band-aids (`except: pass`, `@ts-ignore`, `setTimeout` race hacks), fake/mocked data identifiers (`mockData`, `fake_data`, `dummyData`), unfinished stubs (`TODO`, `FIXME`, `NotImplementedError`), and silent data pollution (`nan_to_num`, `fillna(0)`) so the AI can systematically replace every shortcut with a production-tier pipe.

## 1. Seal Legitimate `AXIOMATIC_PRIMITIVES` (`seal-axioms`)
Never label foundational mathematical/structural constants (e.g., operator symbols like `=`, physical constants, dimensional bounds) as `# hardcoded data`. Place them in a dedicated `axioms` module and seal them with SHA-256:
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_gate.py" seal-axioms \
  --workspace "." \
  --file "<path/to/axioms.py>"
```

## 2. Run the Automated Anti-Cheese, Data-Pollution & Protected-Node Scanner (`ra_cheese_audit.py`)
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_cheese_audit.py" \
  --workspace "." \
  --hypothesis "STANDALONE" \
  --files <optional_explicit_files...> \
  --emit-review-brief
```
Fails immediately if it detects:
1. Modification or deletion of any sealed `AXIOMATIC_PRIMITIVES` file.
2. **`[PROTECTED_NODE_TAMPERED]`**: Any AST/byte modification to an innocent `PROTECTED_WORKING` function (`Symptom != Culprit` lock).
3. **`[DATA_POLLUTION_LEAK]` & `[DATA_POLLUTION_MASKING]`**: Production/model code referencing evaluation ground-truth identifiers (`ground_truth`, `golden_output`, `expected_results`) or silently coercing upstream `NaN`/`Null` corruption into synthetic zeros (`nan_to_num`, `fillna(0)`).
4. Poison comments (`# hardcoded`, `# hack`, `# band-aid`, `# temporary fix`, or bare `# untrusted` without a citation).
5. Symptom-swallowing band-aids (`except: pass`, `except Exception: pass`, empty `catch {}`).
6. AST-level algorithmic fraud (`>= 4` branches of `if input == const: return const` or unsealed constant lookup dicts with `> 20` entries).
7. When `--emit-review-brief` is passed, writes `research/DATA_POLLUTION_REVIEW_BRIEF.md` highlighting numeric clamping/rescaling (`np.clip`, `torch.clamp`, `min`/`max`) and in-place input/state mutations (`global`, `arg[...] =`) so you can fork a cold-eyes reviewer subagent (`ra_context_harness.py fork --subagent ColdEyes_DataReviewer`) to catch semantic cheese.

## 3. Forge Project-Local Skill, `.py` Hooks & Cold-Eyes `ra-reviewer` (`ra_forge.py`)
Generate a custom project-local skill, executable `research/harness/project_harness.py` (CLI + Claude Code `PreToolUse`/`PostToolUse`/`Stop` hooks), and a cold-eyes `ra-reviewer` agent:
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_forge.py" \
  --workspace "." \
  --name "<project-slug>" \
  --domain "<domain>"

python research/harness/project_harness.py check-all --workspace "."
```
