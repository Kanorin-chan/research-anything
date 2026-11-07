---
name: ra-anti-cheese
description: Cryptographically seal legitimate AXIOMATIC_PRIMITIVES, scan code for hardcoded lookup tables and symptom-swallowing band-aids, and forge project-local .py hooks and the cold-eyes ra-reviewer agent. Use when auditing code integrity or setting up project guardrails.
---

# RA Anti-Cheese, Axiom Seal & Project Guardrail Forge (`ra-anti-cheese`)

Use this skill standalone (or during Stage 0/3/5/7 of `research-anything`) to enforce zero-cheese, zero-band-aid engineering and cold-eyes diff verification.

## 1. Seal Legitimate `AXIOMATIC_PRIMITIVES` (`seal-axioms`)
Never label foundational mathematical/structural constants (e.g., operator symbols like `=`, physical constants, dimensional bounds) as `# hardcoded data`. Place them in a dedicated `axioms` module and seal them with SHA-256:
```bash
python "~/.gemini/skills/research-anything/scripts/ra_gate.py" seal-axioms \
  --workspace "." \
  --file "<path/to/axioms.py>"
```

## 2. Run the Automated Anti-Cheese & Band-Aid Scanner (`ra_cheese_audit.py`)
```bash
python "~/.gemini/skills/research-anything/scripts/ra_cheese_audit.py" \
  --workspace "." \
  --hypothesis "STANDALONE" \
  --files <optional_explicit_files...>
```
Fails immediately if it detects:
1. Modification or deletion of any sealed `AXIOMATIC_PRIMITIVES` file.
2. Poison comments (`# hardcoded`, `# hack`, `# band-aid`, `# temporary fix`, or bare `# untrusted` without a citation).
3. Symptom-swallowing band-aids (`except: pass`, `except Exception: pass`, empty `catch {}`).
4. AST-level algorithmic fraud (`>= 4` branches of `if input == const: return const` or unsealed constant lookup dicts with `> 20` entries).

## 3. Forge Project-Local Skill, `.py` Hooks & Cold-Eyes `ra-reviewer` (`ra_forge.py`)
Generate a custom project-local skill, executable `research/harness/project_harness.py` (CLI + Claude Code `PreToolUse`/`PostToolUse`/`Stop` hooks), and a cold-eyes `ra-reviewer` agent:
```bash
python "~/.gemini/skills/research-anything/scripts/ra_forge.py" \
  --workspace "." \
  --name "<project-slug>" \
  --domain "<domain>"

python research/harness/project_harness.py check-all --workspace "."
```
