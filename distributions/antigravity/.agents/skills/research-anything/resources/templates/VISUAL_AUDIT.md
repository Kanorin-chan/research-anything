# User-Eyes Visual & Experiential Reality Audit: {{HYPOTHESIS_ID}}

> **Managed by RA (`research-anything`) — Anti-"Code-Vision" Gate**
> AI agents routinely assume that because code compiled or DOM nodes exist, the screen looks right to the user.
> **Rule**: You must capture real visual outputs (`.png`/`.jpg`/`.webp`), open and view every image with your file/vision tool, and interrogate the pixels from the **User's Point of View**. Vague claims like *"looks good"* or *"rendered properly"* will fail `ra_visual_audit.py`.

---

## 1. Captured Visual Evidence Inventory
Place all captured screenshots/frames inside `research/sandbox/{{HYPOTHESIS_ID}}_{{SLUG}}/visual_captures/`:

| Capture ID | Image File Path | State / Viewport Captured | Resolution (`WxH`) | File SHA-256 |
| :--- | :--- | :--- | :--- | :--- |
| `CAP-01` | `visual_captures/<initial_or_baseline.png>` | `<e.g., Initial load / Default state>` | `<WxH>` | `<sha256>` |
| `CAP-02` | `visual_captures/<after_action_or_data.png>` | `<e.g., After triggering function / Data populated>` | `<WxH>` | `<sha256>` |
| `CAP-03` | `visual_captures/<edge_or_stress_state.png>` | `<e.g., Long text / Empty state / Narrow viewport>` | `<WxH>` | `<sha256>` |

---

## 2. "What AI Intended" vs. "What the User Literally Sees"
Compare your code's intent against the literal pixels in the captured image(s):

- **AI Code Intent (What I Thought My Code Would Render)**:
  <Describe the exact layout, icon placement, data binding, and visual state your code tried to produce>
- **Literal Pixel Observation (What Is Actually Visible When Viewing `CAP-01`..`CAP-0N`)**:
  <Describe concrete visual facts observed in the image: exact positions, relative alignment, colors, text legibility, icon locations, and loaded images>
- **Discrepancies Detected Between Intent and Pixels**:
  <List ANY mismatch, even a 4px misalignment, wrong icon, clipped label, or missing asset—or explain how you verified zero discrepancy>

---

## 3. Hostile 5-Point User-Eyes Defect Checklist
Inspect the captured images specifically looking for these 5 classes of visual bugs:

1. **CSS, Geometry & Layout Alignment**:
   - *Check*: Are any elements overlapping, clipped, overflowing containers, misaligned, or pushed off-screen?
   - *Observed in Pixels*: <Write specific observation of container bounds, margins, and alignment>
2. **Asset, Icon & Media Loading**:
   - *Check*: Did every icon, image, font, shader, and canvas actually load and render (no broken image icons, blank boxes, stuck spinners, or missing glyphs)?
   - *Observed in Pixels*: <Write specific observation of every icon and image asset on screen>
3. **Data Placement & Value Validity**:
   - *Check*: Is every data field in the right slot/column, formatted properly, with zero `undefined`, `NaN`, `null`, `[object Object]`, or raw template strings?
   - *Observed in Pixels*: <Write specific observation of the rendered data values and their positions>
4. **Functional-Visual State Match**:
   - *Check*: Does the visual display *actually* match the function/state currently active (e.g., right image/icon for the selected function, active tab highlighted, disabled button visually distinct)?
   - *Observed in Pixels*: <Write specific observation proving visual state matches functional state>
5. **User-Perspective Cognitive Walkthrough ("Stepping Into the User's Shoes")**:
   - *Question*: *"If I know nothing about the source code and I am the user looking at this screen right now, does this look complete, intuitive, and bug-free?"*
   - *User-Eyes Reasoning*: <Write honest reasoning from the user's perspective>

---

## 4. Visual Audit Verdict
- **Visual Reality Verdict**: `<PASS | FAIL>`
- **Defects Found & Fixed Before Sign-Off**: `<None, or list exact visual bugs caught via screenshot inspection and how they were fixed>`
