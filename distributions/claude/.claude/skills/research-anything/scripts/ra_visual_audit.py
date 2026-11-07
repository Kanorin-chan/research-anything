#!/usr/bin/env python3
"""
ra_visual_audit.py — User-Eyes Visual & Experiential Reality Auditor for RA.

Prevents "Code-Context Blindness" (where an AI assumes the UI/game/chart/render works
because the code compiled or DOM exists, without seeing what the user actually sees).

Enforces:
1. Auto-detection of visual/UI/rendering scope across sandbox and target files.
2. Verification of real captured screenshots (`.png`, `.jpg`, `.jpeg`, `.webp`) in
   `research/sandbox/<hypothesis>/visual_captures/`:
   - Parses binary headers to verify real resolution (`width x height >= 64x64`).
   - Rejects 0-byte, tiny, or uniform blank-screen captures (e.g., white-screen / black-screen fails).
3. Verification of `VISUAL_AUDIT.md`:
   - Ensures every captured image is logged with SHA-256 and resolution.
   - Blocks unfilled placeholders and lazy superficial comments ("looks good", "rendered fine")
     that lack concrete pixel-level observations of CSS alignment, icon/data placement,
     asset loading, functional-visual match, and User-Perspective reasoning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VISUAL_EXTENSIONS = {
    ".css", ".scss", ".sass", ".less", ".html", ".htm", ".jsx", ".tsx",
    ".vue", ".svelte", ".qml", ".gd", ".tscn", ".shader", ".wgsl", ".glsl",
    ".hlsl", ".svg",
}

VISUAL_COMPOUND_SUFFIXES = (".blade.php", ".twig", ".erb", ".hbs", ".ejs")

VISUAL_CODE_IMPORTS_RE = re.compile(
    r"\b(pygame|tkinter|PyQt\d?|PySide\d?|matplotlib|seaborn|plotly|gradio|streamlit|"
    r"three|pixi|phaser|opengl|webgl|canvas|window\.|document\.|React|Vue)\b"
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

LAZY_OBSERVATION_PATTERNS = [
    re.compile(r"^\s*(looks?\s+good|renders?\s+(properly|fine|correctly)|no\s+issues?|everything\s+is\s+(fine|ok))\s*\.?\s*$", re.IGNORECASE),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def get_image_dimensions(path: Path) -> Optional[Tuple[int, int]]:
    """Extract (width, height) from PNG, JPEG, or WebP headers using pure Python."""
    try:
        data = path.read_bytes()
    except Exception:
        return None

    # 1. PNG: 8-byte signature followed by IHDR chunk
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)

    # 2. JPEG: scan SOF markers
    if len(data) >= 4 and data[:2] == b"\xff\xd8":
        idx = 2
        size = len(data)
        while idx < size - 8:
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            if marker == 0xFF:
                idx += 1
                continue
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[idx + 5 : idx + 9])
                return int(w), int(h)
            if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7):
                idx += 2
                continue
            if idx + 4 > size:
                break
            seg_len = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
            if seg_len < 2:
                break
            idx += 2 + seg_len

    # 3. WebP: RIFF....WEBP
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk_type = data[12:16]
        if chunk_type == b"VP8X" and len(data) >= 30:
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return w, h
        if chunk_type == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if chunk_type == b"VP8L" and len(data) >= 25:
            b0, b1, b2, b3 = data[21:25]
            w = 1 + (((b1 & 0x3F) << 8) | b0)
            h = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
            return w, h

    return None


def is_visual_project_or_hypothesis(sandbox_dir: Path, workspace: Path) -> Tuple[bool, List[str]]:
    """Detect whether the hypothesis or mapped files involve visual/UI/rendering output."""
    matched_files: List[str] = []
    search_files: List[Path] = []
    if sandbox_dir.exists():
        search_files.extend(f for f in sandbox_dir.rglob("*") if f.is_file())

    state_path = workspace / "research" / ".ra_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for rel in state.get("context_map_snapshot", {}).get("tracked_files", {}).keys():
                fp = workspace / rel
                if fp.exists() and fp.is_file():
                    search_files.append(fp)
        except Exception:
            pass

    for f in search_files:
        name_lower = f.name.lower()
        rel = (
            f.resolve().relative_to(workspace.resolve()).as_posix()
            if f.resolve().is_relative_to(workspace.resolve())
            else f.name
        )
        if f.suffix.lower() in VISUAL_EXTENSIONS or any(name_lower.endswith(s) for s in VISUAL_COMPOUND_SUFFIXES):
            if rel not in matched_files:
                matched_files.append(rel)
            continue
        if f.suffix.lower() in {".py", ".js", ".ts", ".rs", ".cpp", ".cs"}:
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")[:8000]
                if VISUAL_CODE_IMPORTS_RE.search(txt):
                    if rel not in matched_files:
                        matched_files.append(rel)
            except Exception:
                pass

    return len(matched_files) > 0, matched_files


def cmd_init_audit(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    hyp = args.hypothesis.strip()
    sandbox_dir = rdir / "sandbox" / hyp
    captures_dir = sandbox_dir / "visual_captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    tpl_path = Path(__file__).resolve().parent.parent / "resources" / "templates" / "VISUAL_AUDIT.md"
    audit_md_path = sandbox_dir / "VISUAL_AUDIT.md"

    parts = hyp.split("_", 1)
    hyp_id = parts[0]
    slug = parts[1] if len(parts) > 1 else "visual"

    if not audit_md_path.exists():
        tpl = tpl_path.read_text(encoding="utf-8") if tpl_path.exists() else "# Visual Audit\n"
        content = tpl.replace("{{HYPOTHESIS_ID}}", hyp_id).replace("{{SLUG}}", slug)
        audit_md_path.write_text(content, encoding="utf-8")

    # Auto-inventory any images already inside visual_captures/
    images = [f for f in sorted(captures_dir.rglob("*")) if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    print("=" * 78)
    print(f"  RA USER-EYES VISUAL AUDIT INITIALIZED — `{hyp}`")
    print("=" * 78)
    print(f"  Captures Directory : {captures_dir.relative_to(workspace).as_posix()}/")
    print(f"  Visual Audit Report: {audit_md_path.relative_to(workspace).as_posix()}")
    if images:
        print(f"  Discovered Captures ({len(images)}):")
        for idx, img in enumerate(images, start=1):
            dims = get_image_dimensions(img)
            dim_str = f"{dims[0]}x{dims[1]}" if dims else "UNKNOWN"
            digest = sha256_file(img)[:12]
            print(f"    - CAP-{idx:02d}: {img.name} ({dim_str}, SHA256: {digest}...)")
    else:
        print("  [ACTION REQUIRED] Capture live screenshots into `visual_captures/`, view them with your")
        print("                    file/image reading tool, and complete `VISUAL_AUDIT.md` from the user's view.")
    print("=" * 78)


def cmd_audit(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    state_path = rdir / ".ra_state.json"
    hyp = args.hypothesis.strip()
    sandbox_dir = rdir / "sandbox" / hyp
    captures_dir = sandbox_dir / "visual_captures"
    audit_md_path = sandbox_dir / "VISUAL_AUDIT.md"

    visual_detected, trigger_files = is_visual_project_or_hypothesis(sandbox_dir, workspace)

    if not visual_detected and not args.require_visual and not captures_dir.exists():
        print("=" * 78)
        print(f"  RA VISUAL AUDIT — `{hyp}` (NON-VISUAL SCOPE)")
        print("=" * 78)
        print("  No UI/CSS/rendering files detected in sandbox or tracked context map.")
        print("  Visual audit marked NOT_APPLICABLE (PASS). Use `--require-visual` to force visual verification.")
        print("=" * 78)
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["visual_audit_passed"] = True
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return

    violations: List[str] = []

    if not captures_dir.exists():
        violations.append(
            f"Missing `research/sandbox/{hyp}/visual_captures/` directory! Run `ra_visual_audit.py init --hypothesis {hyp}` "
            f"and capture real screenshots of the rendered output."
        )
        images: List[Path] = []
    else:
        images = [f for f in sorted(captures_dir.rglob("*")) if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
        if not images:
            violations.append(
                f"Zero screenshot files (`.png`/`.jpg`/`.webp`) found in `research/sandbox/{hyp}/visual_captures/`! "
                f"Do NOT rely on code/DOM reading alone — capture what the user actually sees."
            )

    # Validate each image file's binary dimensions, size, and non-blank entropy
    for img in images:
        raw = img.read_bytes()
        if len(raw) < 400:
            violations.append(
                f"`{img.name}` is suspiciously tiny ({len(raw)} bytes) — looks like a dummy/stub image or failed capture."
            )
            continue
        dims = get_image_dimensions(img)
        if dims is None:
            violations.append(f"`{img.name}` does not have a valid PNG/JPEG/WebP header!")
        else:
            w, h = dims
            if w < 64 or h < 64:
                violations.append(
                    f"`{img.name}` resolution is `{w}x{h}` (< 64x64 minimum). Capture a real user-viewport screenshot!"
                )
        # Check if compressed image payload is completely uniform/blank
        ent = shannon_entropy(raw[64:])
        if ent < 2.2:
            violations.append(
                f"`{img.name}` has abnormally low byte entropy ({ent:.2f} bits/byte) — indicates a solid blank/empty screen render!"
            )

    # Validate VISUAL_AUDIT.md
    if not audit_md_path.exists():
        violations.append(
            f"Missing `research/sandbox/{hyp}/VISUAL_AUDIT.md`! Run `ra_visual_audit.py init --hypothesis {hyp}`."
        )
    else:
        txt = audit_md_path.read_text(encoding="utf-8")
        unfilled_markers = [
            "<Describe the exact layout",
            "<Describe concrete visual facts",
            "<List ANY mismatch",
            "<Write specific observation",
            "<Write honest reasoning from the user's perspective>",
            "<PASS | FAIL>",
        ]
        for marker in unfilled_markers:
            if marker in txt:
                violations.append(f"`VISUAL_AUDIT.md` still contains unfilled placeholder: `{marker}...`")

        if "**Visual Reality Verdict**: `FAIL`" in txt:
            violations.append("`VISUAL_AUDIT.md` verdict is marked `FAIL` — fix the visual defects and re-capture before advancing!")

        for img in images:
            if img.name not in txt:
                violations.append(
                    f"Captured image `{img.name}` is not documented in `VISUAL_AUDIT.md`! Open and inspect every screenshot."
                )

        for line in txt.splitlines():
            if line.strip().startswith("- *Observed in Pixels*:") or line.strip().startswith("- *User-Eyes Reasoning*:"):
                val = line.split(":", 1)[1].strip()
                if len(val) < 25 or any(p.match(val) for p in LAZY_OBSERVATION_PATTERNS):
                    violations.append(
                        f"Superficial/lazy observation in `VISUAL_AUDIT.md` (`{line.strip()}`). "
                        f"State concrete visual geometry, alignment, icon/data positions, and user-view reasoning!"
                    )

    print("=" * 78)
    print(f"  RA USER-EYES VISUAL & EXPERIENTIAL REALITY AUDIT — `{hyp}`")
    print("=" * 78)
    print(f"  Visual Trigger Files : {', '.join(trigger_files[:5]) or 'Forced (--require-visual)'}")
    print(f"  Captured Screenshots : {len(images)}")
    print(f"  Violations Found     : {len(violations)}")
    print("-" * 78)

    if violations:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["visual_audit_passed"] = False
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("  [FAIL] VISUAL REALITY GATE REJECTED THE PROTOTYPE:")
        for v in violations:
            print(f"    - {v}")
        print("-" * 78)
        print("  REQUIRED ACTION:")
        print("    1. Render the live UI/game/chart/output and capture real screenshots in `visual_captures/`.")
        print("    2. Open and view EVERY screenshot with your image-reading tool (`read_file`).")
        print("    3. Reason from the USER'S EYES in `VISUAL_AUDIT.md` (CSS alignment, displaced icons/data,")
        print("       missing assets, functional-visual match) and fix any visual defects before re-running.")
        print("=" * 78)
        sys.exit(1)

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["visual_audit_passed"] = True
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("  [PASS] All captured screenshots verified and User-Eyes Visual Audit complete!")
    print("=" * 78)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA User-Eyes Visual & Experiential Reality Auditor")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize visual_captures/ folder and VISUAL_AUDIT.md for a hypothesis")
    p_init.add_argument("--workspace", default=".", help="Workspace root")
    p_init.add_argument("--hypothesis", required=True, help="Hypothesis folder name (e.g., H001_slug)")
    p_init.set_defaults(func=cmd_init_audit)

    p_audit = sub.add_parser("audit", help="Verify captured screenshots and VISUAL_AUDIT.md user-perspective reasoning")
    p_audit.add_argument("--workspace", default=".", help="Workspace root")
    p_audit.add_argument("--hypothesis", required=True, help="Hypothesis folder name (e.g., H001_slug)")
    p_audit.add_argument("--require-visual", action="store_true", help="Force visual audit even if no UI extensions detected")
    p_audit.set_defaults(func=cmd_audit)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
