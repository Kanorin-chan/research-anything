# User-Eyes Visual, Provided-Asset & Experiential Reality Validation

This reference governs how **RA (`research-anything`)** eliminates **"Code-Context Blindness"** and the **"Ignored / Misfitted Provided-Asset Trap"**—the failure modes where an AI agent:
1. Only reads code, DOM text, or terminal logs and claims a UI/game/render works while the user sees broken CSS, displaced icons/data, or blank canvases.
2. **Ignores the user's provided assets/icons** (substituting lazy CSS boxes, text, or emoji instead of wiring the real provided assets), **hallucinates broken asset filenames** that 404, or **squishes/stretches/clips provided assets** into containers with the wrong aspect ratio.

---

## 1. The Core Problem: "What the AI Reads" $\neq$ "What the User Sees"

Standard AI agents fail on visual, UI, game, layout, and rendering tasks in three ways:
1. **Blind Code/DOM Assumption**: The agent writes CSS/UI/render code, sees zero syntax errors or sees a DOM node present in HTML, and assumes the visual layout is valid without ever rendering and capturing the screen.
2. **Ignored or Misfitted Provided Assets**: The user or project provides real assets (`assets/`, `public/`, `icons/`, `sprites/`, `reference/`), and the AI either forgets to use them, types a wrong filename (`assets/close.png` instead of `assets/btn_close_24.svg`), uses external dummy URLs (`placehold.co`), or forces a `16:9` banner or `24x24` icon into a mismatched box that stretches or clips it.
3. **Superficial Image Reading ("Confirmation Bias Vision")**: Even when the agent takes a screenshot, it looks only to confirm *"something rendered"* and says *"Looks good!"*—ignoring overlapping labels, a displaced icon, an unloaded image placeholder, `undefined`/`NaN` text, or a button displaying the wrong state.

---

## 2. Mandatory 5-Step User-Eyes & Provided-Asset Validation Protocol

Whenever a hypothesis, bug fix, or feature touches **any visual, UI, layout, game frame, shader, chart, or interactive surface**, you (or a dedicated **Visual Inspector Subagent**) must execute all five steps before concluding Stage 4/5:

### Step 1: Scan Provided Assets & Native Aspect Ratios (`ra_visual_audit.py scan-assets`)
Before writing or finalizing UI/rendering code, scan the workspace and sandbox for provided assets:
```bash
python "~/.gemini/skills/research-anything/scripts/ra_visual_audit.py" scan-assets \
  --workspace "." \
  --hypothesis "Hxxx_<slug>"
```
- Inspect the discovered assets, their **native resolution (`WxH`)**, and their **aspect ratio (`W:H`)** (supports `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, `.ico`, `.gif`, `.bmp`, fonts, and 3D assets).
- Wire the real provided assets/icons into your code (never substitute emoji, bare CSS shapes, or `placehold.co` dummy URLs when real assets are provided), and size their containers (`width`, `height`, `aspect-ratio`, `object-fit: contain/cover`) to match their native proportions.

### Step 2: Initialize & Capture Multi-State Screenshots (`visual_captures/`)
Initialize the visual audit workspace for the active hypothesis (which also populates the **Provided Assets Inventory Table** in `VISUAL_AUDIT.md`):
```bash
python "~/.gemini/skills/research-anything/scripts/ra_visual_audit.py" init \
  --workspace "." \
  --hypothesis "Hxxx_<slug>"
```
Launch/render the live output (via headless browser, Playwright, window/frame capture, or canvas render) and save real screenshots into `research/sandbox/Hxxx_<slug>/visual_captures/`:
- **`CAP-01` (Baseline / Initial Load)**: What the user sees immediately upon opening/rendering.
- **`CAP-02` (Active Function / Loaded Data State)**: What the user sees after data populates or after triggering the target function.
- **`CAP-03` (Boundary / Stress State)**: Long text, empty data, dense items, or alternate viewport/resolution.

### Step 3: Open Every Capture & Bridge "AI Intent" vs. "User Pixels"
You **must** open every captured `.png`/`.jpg`/`.webp` file using your file/image reading tool (`read_file`) and compare:
- **What I (the AI) thought my code drew** vs. **What is literally visible in the pixels**.
- Never write vague summaries like *"UI rendered properly."* State concrete visual facts (exact element positions, bounding boxes, margins, alignment, asset aspect ratios, colors, and legibility).

### Step 4: Run the Hostile 5-Point User-Eyes Defect Checklist (`VISUAL_AUDIT.md`)
Assume the visual output is broken until you disprove all five defect categories in `research/sandbox/Hxxx_<slug>/VISUAL_AUDIT.md`:

| Defect Category | What You Must Actively Hunt For in the Screenshot Pixels |
| :--- | :--- |
| **1. CSS, Geometry & Alignment** | Misaligned columns/rows, displaced icons or badges, overlapping text, clipped containers, unintended scrollbars, broken flex/grid wrapping, off-center elements. |
| **2. Provided Asset Usage, Icon Fit & Media Loading** | Did you actually use the user's provided assets/icons (no `UNUSED_PROVIDED_ASSET` or emoji stand-ins)? Did every asset load without 404/broken icons, and does every asset/icon fit its target container slot with its native aspect ratio preserved (not squished, stretched, or clipped)? |
| **3. Data Placement & Formatting** | Displaced data (value rendered in the wrong card/column), raw template keys (`{{item.name}}`), `NaN`, `undefined`, `null`, `[object Object]`, or truncated numbers. |
| **4. Functional-Visual Truth Match** | Does the displayed image/icon/state *actually* match the function that was triggered? (e.g., if Function B is active, is it showing Function B's image and state, or accidentally showing Function A's image?). |
| **5. User-Perspective Walkthrough** | *"Stepping completely out of code context and looking strictly through the user's eyes: is this actually valid? Did we really do this right and fit the real assets properly from the user's view?"* |

### Step 5: Run the Automated Visual & Provided-Asset Gate (`ra_visual_audit.py audit`)
```bash
python "~/.gemini/skills/research-anything/scripts/ra_visual_audit.py" audit \
  --workspace "." \
  --hypothesis "Hxxx_<slug>"
```
`ra_visual_audit.py` automatically rejects the stage transition if:
- `[IGNORED_PROVIDED_ASSETS]`: Provided assets exist in the workspace/sandbox, but zero provided assets are referenced in the prototype code (or any `--require-assets` file is unused).
- `[BROKEN_ASSET_PATH]`: Code references an image/icon/font/sprite path that does not exist on disk (auto-suggests the closest real provided asset).
- `[DUMMY_ASSET_PLACEHOLDER]`: Code uses external dummy placeholder URLs (`placehold.co`, `via.placeholder.com`, `picsum.photos`).
- Visual/UI/rendering files were touched without real screenshots in `visual_captures/`.
- Any screenshot is tiny (`< 64x64`), corrupted, or a uniform blank screen (Shannon byte entropy `< 2.2`).
- `VISUAL_AUDIT.md` contains unfilled placeholders or lazy superficial phrases (*"looks good"*, *"rendered fine"*, *"no issues"*) instead of concrete pixel-level observations and user-perspective reasoning.
