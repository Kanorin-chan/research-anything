# User-Eyes Visual, Asset-Fit & Experiential Reality Audit: {{HYPOTHESIS_ID}}

> **Managed by RA (`research-anything`) — Anti-"Code-Vision" & Provided-Asset Gate**
> AI agents routinely assume that because code compiled or DOM nodes exist, the screen looks right—or they completely ignore the user's provided assets/icons, hallucinate broken asset filenames, or squish/stretch an asset into the wrong container size.
> **Rule**: You must verify every provided asset is properly used and fitted, capture real visual outputs (`.png`/`.jpg`/`.webp`), open and view every image with your file/vision tool, and interrogate the pixels from the **User's Point of View**. Vague claims like *"looks good"* or *"rendered properly"* will fail `ra_visual_audit.py`.

---

## 1. Captured Visual Evidence Inventory
Place all captured screenshots/frames inside `research/sandbox/{{HYPOTHESIS_ID}}_{{SLUG}}/visual_captures/`:

| Capture ID | Image File Path | State / Viewport Captured | Resolution (`WxH`) | File SHA-256 |
| :--- | :--- | :--- | :--- | :--- |
| `CAP-01` | `visual_captures/<initial_or_baseline.png>` | `<e.g., Initial load / Default state>` | `<WxH>` | `<sha256>` |
| `CAP-02` | `visual_captures/<after_action_or_data.png>` | `<e.g., After triggering function / Data populated>` | `<WxH>` | `<sha256>` |
| `CAP-03` | `visual_captures/<edge_or_stress_state.png>` | `<e.g., Long text / Empty state / Narrow viewport>` | `<WxH>` | `<sha256>` |

---

## 2. Provided Assets Inventory, Usage & Container-Fit Audit
`ra_visual_audit.py` automatically scans workspace asset directories (`assets/`, `public/`, `static/`, `icons/`, `images/`, `sprites/`, `reference/`, etc.) to detect provided assets, check if your code actually uses them, and verify their native dimensions/aspect ratios:

{{PROVIDED_ASSETS_TABLE}}

- **Provided Asset Usage & Selection Verification**:
  <Confirm that all relevant provided assets/icons are wired into the UI/render (no ignored user assets, no fake CSS boxes/emoji substitutes, and zero hallucinated/broken asset paths)>
- **Asset & Icon Container Fit, Scale & Aspect-Ratio Verification**:
  <Verify how each provided asset/icon fits its slot in the rendered pixels: native aspect ratio preserved (not stretched/squished), proper `object-fit` / scaling, not clipped or overflowing its parent container, and visually balanced next to labels/controls>

---

## 3. "What AI Intended" vs. "What the User Literally Sees"
Compare your code's intent against the literal pixels in the captured image(s):

- **AI Code Intent (What I Thought My Code Would Render)**:
  <Describe the exact layout, icon placement, data binding, and visual state your code tried to produce>
- **Literal Pixel Observation (What Is Actually Visible When Viewing `CAP-01`..`CAP-0N`)**:
  <Describe concrete visual facts observed in the image: exact positions, relative alignment, colors, text legibility, icon locations, and loaded images>
- **Discrepancies Detected Between Intent and Pixels**:
  <List ANY mismatch, even a 4px misalignment, wrong icon, stretched asset, clipped label, or missing asset—or explain how you verified zero discrepancy>

---

## 4. Hostile 5-Point User-Eyes Defect Checklist
Inspect the captured images specifically looking for these 5 classes of visual bugs:

1. **CSS, Geometry & Layout Alignment**:
   - *Check*: Are any elements overlapping, clipped, overflowing containers, misaligned, or pushed off-screen?
   - *Observed in Pixels*: <Write specific observation of container bounds, margins, and alignment>
2. **Provided Asset Usage, Icon Fit & Media Loading**:
   - *Check*: Did you use the user's provided assets/icons (instead of ignoring them or using emoji/placeholder boxes)? Did every asset load without 404/broken icons, and does every asset/icon fit its target slot with the right aspect ratio, scale, and alignment?
   - *Observed in Pixels*: <Write specific observation of every provided icon/image asset, its rendered dimensions/aspect ratio, and how it fits inside its container>
3. **Data Placement & Value Validity**:
   - *Check*: Is every data field in the right slot/column, formatted properly, with zero `undefined`, `NaN`, `null`, `[object Object]`, or raw template strings?
   - *Observed in Pixels*: <Write specific observation of the rendered data values and their positions>
4. **Functional-Visual State Match**:
   - *Check*: Does the visual display *actually* match the function/state currently active (e.g., right image/icon for the selected function, active tab highlighted, disabled button visually distinct)?
   - *Observed in Pixels*: <Write specific observation proving visual state matches functional state>
5. **User-Perspective Cognitive Walkthrough ("Stepping Into the User's Shoes")**:
   - *Question*: *"If I know nothing about the source code and I am the user looking at this screen right now, does this look complete, intuitive, properly fitted with the real assets, and bug-free?"*
   - *User-Eyes Reasoning*: <Write honest reasoning from the user's perspective>

---

## 5. Visual Audit Verdict
- **Visual Reality Verdict**: `<PASS | FAIL>`
- **Defects Found & Fixed Before Sign-Off**: `<None, or list exact visual/asset-fit bugs caught via screenshot inspection and how they were fixed>`
