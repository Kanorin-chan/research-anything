# User-Eyes Visual & Experiential Reality Validation

This reference governs how **RA (`research-anything`)** eliminates **"Code-Context Blindness"**—the failure mode where an AI agent only reads code, DOM text, or terminal logs (or glances superficially at a screenshot) and claims a feature works while the user sees broken CSS, displaced icons/data, missing assets, or the wrong visual display for a function.

---

## 1. The Core Problem: "What the AI Reads" $\neq$ "What the User Sees"

Standard AI agents fail on visual, UI, game, layout, and rendering tasks in two ways:
1. **Blind Code/DOM Assumption**: The agent writes CSS/UI/render code, sees zero syntax errors or sees a DOM node present in HTML, and assumes the visual layout is valid without ever rendering and capturing the screen.
2. **Superficial Image Reading ("Confirmation Bias Vision")**: Even when the agent takes a screenshot, it looks only to confirm *"something rendered"* and says *"Looks good!"*—ignoring overlapping labels, a displaced icon, an unloaded image placeholder, `undefined`/`NaN` text, or a button displaying the wrong state.

---

## 2. Mandatory 4-Step User-Eyes Visual Validation Protocol

Whenever a hypothesis, bug fix, or feature touches **any visual, UI, layout, game frame, shader, chart, or interactive surface**, you (or a dedicated **Visual Inspector Subagent**) must execute all four steps before concluding Stage 4/5:

### Step 1: Initialize & Capture Multi-State Screenshots (`visual_captures/`)
Initialize the visual audit workspace for the active hypothesis:
```bash
python "~/.gemini/skills/research-anything/scripts/ra_visual_audit.py" init \
  --workspace "." \
  --hypothesis "Hxxx_<slug>"
```
Launch/render the live output (via headless browser, Playwright, window/frame capture, or canvas render) and save real screenshots into `research/sandbox/Hxxx_<slug>/visual_captures/`:
- **`CAP-01` (Baseline / Initial Load)**: What the user sees immediately upon opening/rendering.
- **`CAP-02` (Active Function / Loaded Data State)**: What the user sees after data populates or after triggering the target function.
- **`CAP-03` (Boundary / Stress State)**: Long text, empty data, dense items, or alternate viewport/resolution.

### Step 2: Open Every Capture & Bridge "AI Intent" vs. "User Pixels"
You **must** open every captured `.png`/`.jpg`/`.webp` file using your file/image reading tool (`read_file`) and compare:
- **What I (the AI) thought my code drew** vs. **What is literally visible in the pixels**.
- Never write vague summaries like *"UI rendered properly."* State concrete visual facts (exact element positions, bounding boxes, margins, alignment, colors, and legibility).

### Step 3: Run the Hostile 5-Point User-Eyes Defect Checklist (`VISUAL_AUDIT.md`)
Assume the visual output is broken until you disprove all five defect categories in `research/sandbox/Hxxx_<slug>/VISUAL_AUDIT.md`:

| Defect Category | What You Must Actively Hunt For in the Screenshot Pixels |
| :--- | :--- |
| **1. CSS, Geometry & Alignment** | Misaligned columns/rows, displaced icons or badges, overlapping text, clipped containers, unintended scrollbars, broken flex/grid wrapping, off-center elements. |
| **2. Asset, Icon & Media Loading** | Broken image icons, missing SVG/font glyphs, blank/white/black canvases, stuck loading spinners, unrendered shaders, 404 placeholder boxes. |
| **3. Data Placement & Formatting** | Displaced data (value rendered in the wrong card/column), raw template keys (`{{item.name}}`), `NaN`, `undefined`, `null`, `[object Object]`, or truncated numbers. |
| **4. Functional-Visual Truth Match** | Does the displayed image/icon/state *actually* match the function that was triggered? (e.g., if Function B is active, is it showing Function B's image and state, or accidentally showing Function A's image?). |
| **5. User-Perspective Walkthrough** | *"Stepping completely out of code context and looking strictly through the user's eyes: is this actually valid? Did we really do this right from the user's view?"* |

### Step 4: Run the Automated Visual Reality Gate (`ra_visual_audit.py audit`)
```bash
python "~/.gemini/skills/research-anything/scripts/ra_visual_audit.py" audit \
  --workspace "." \
  --hypothesis "Hxxx_<slug>"
```
`ra_visual_audit.py` automatically rejects the stage transition if:
- Visual/UI/rendering files were touched without real screenshots in `visual_captures/`.
- Any screenshot is tiny (`< 64x64`), corrupted, or a uniform blank screen (low byte entropy).
- `VISUAL_AUDIT.md` contains unfilled placeholders or lazy superficial phrases (*"looks good"*, *"rendered fine"*, *"no issues"*) instead of concrete pixel-level observations and user-perspective reasoning.
