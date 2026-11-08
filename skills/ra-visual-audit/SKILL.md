---
name: ra-visual-audit
description: Audit UI, CSS, game, shader, and chart outputs through the User's Eyes, auto-discover provided workspace assets and native aspect ratios (WxH), catch ignored assets or broken asset paths, and verify real rendered screenshots. Use whenever visual, UI, layout, icon, or rendering files are touched.
---

# RA User-Eyes Visual, Provided-Asset & Container-Fit Gate (`ra-visual-audit`)

Use this skill standalone (or during Stage 4/5 of `research-anything`) whenever any UI, CSS, HTML, component, icon, game frame, shader, or chart is created or modified. **Never trust code/DOM reading alone.**

## 1. Scan Provided Assets & Native Aspect Ratios (`scan-assets`)
Before finalizing UI/rendering code, scan the workspace (`assets/`, `public/`, `static/`, `icons/`, `images/`, `sprites/`, `reference/`) for provided assets:
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_visual_audit.py" scan-assets \
  --workspace "." \
  --hypothesis "STANDALONE"
```
- Inspect each discovered asset's **native resolution (`WxH`)** and **aspect ratio (`W:H`)**.
- **Wire the real provided assets/icons** into your UI/render (never ignore user-provided assets to draw lazy CSS boxes, emoji, or `placehold.co` dummy URLs).
- **Fit each asset into a properly proportioned slot** (`object-fit: contain/cover`, matching `aspect-ratio` / container dimensions) so it is never stretched, squished, or clipped.

## 2. Initialize & Capture Real Screenshots (`init`)
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_visual_audit.py" init \
  --workspace "." \
  --hypothesis "STANDALONE"
```
Render the live output and capture real screenshots (`.png`, `.jpg`, `.webp`) into `research/sandbox/<hypothesis>/visual_captures/`.

## 3. Inspect Pixels From the User's Point of View & Run `audit`
Open every screenshot with your image-reading tool (`Read` in Claude Code, `read_file` in Gemini), complete the 5-point User-Eyes & Asset-Fit checklist in `VISUAL_AUDIT.md`, and run the automated gate:
```bash
python "${CLAUDE_SKILL_DIR}/../research-anything/scripts/ra_visual_audit.py" audit \
  --workspace "." \
  --hypothesis "STANDALONE"
```
`ra_visual_audit.py audit` blocks on:
- `[IGNORED_PROVIDED_ASSETS]` (provided assets exist on disk, but `0` are wired in code)
- `[BROKEN_ASSET_PATH]` (code references a non-existent asset filename; suggests closest real asset)
- `[DUMMY_ASSET_PLACEHOLDER]` (`placehold.co`, `via.placeholder.com`, `picsum.photos`)
- Missing, tiny (`< 64x64`), or blank-screen screenshots (Shannon byte entropy `< 2.2`)
- Unfilled placeholders or lazy *"looks good"* observations in `VISUAL_AUDIT.md`.
