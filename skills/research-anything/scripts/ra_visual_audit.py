#!/usr/bin/env python3
"""
ra_visual_audit.py — User-Eyes Visual, Provided-Asset & Experiential Reality Auditor for RA.

Prevents "Code-Context Blindness" (where an AI assumes the UI/game/chart/render works
because the code compiled or DOM exists, or ignores/misfits the user's provided assets).

Enforces:
1. Auto-detection of visual/UI/rendering scope across sandbox and target files.
2. Provided-Asset Discovery, Usage & Fit Auditing:
   - Scans workspace & sandbox asset folders (`assets/`, `public/`, `static/`, `icons/`,
     `images/`, `img/`, `sprites/`, `textures/`, `media/`, `ui/`, `reference/`, etc.).
   - Extracts native `WxH` dimensions and aspect ratios (`W:H`) for `.png`, `.jpg`, `.jpeg`,
     `.webp`, `.gif`, `.bmp`, `.ico`, and `.svg` (`viewBox`/`width`/`height`) so the agent
     fits every asset/icon into a properly proportioned slot without stretching or clipping.
   - Cross-checks prototype code against provided assets to catch:
     a) **Ignored Provided Assets**: Provided assets exist on disk, but the AI ignored them
        and rendered bare CSS boxes, text, or emoji instead.
     b) **Hallucinated / Broken Asset Paths**: Code references `assets/foo.png` that does
        not exist on disk (auto-suggests closest real provided asset).
     c) **Dummy Placeholder URLs**: Code uses `placehold.co` / `via.placeholder.com` /
        `picsum.photos` instead of real assets.
3. Verification of real captured screenshots (`.png`, `.jpg`, `.jpeg`, `.webp`) in
   `research/sandbox/<hypothesis>/visual_captures/`:
   - Parses binary headers to verify real resolution (`width x height >= 64x64`).
   - Rejects 0-byte, tiny, or uniform blank-screen captures (Shannon byte entropy `< 2.2`).
4. Verification of `VISUAL_AUDIT.md`:
   - Ensures every captured image and provided asset fit is logged.
   - Blocks unfilled placeholders and lazy superficial comments ("looks good", "rendered fine")
     that lack concrete pixel-level observations of CSS alignment, provided-asset usage &
     container fit, data placement, functional-visual match, and User-Perspective reasoning.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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

ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".gif", ".bmp", ".avif",
    ".ttf", ".otf", ".woff", ".woff2", ".glb", ".gltf", ".obj", ".atlas",
}

DEFAULT_ASSET_DIR_NAMES = {
    "assets", "asset", "public", "static", "icons", "icon", "images", "image",
    "img", "sprites", "sprite", "textures", "texture", "media", "ui", "art",
    "fonts", "font", "reference", "references", "skins", "themes",
}

EXCLUDED_ASSET_SCAN_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".claude", ".agents", ".gemini", "visual_captures", "graveyard",
    "context_snapshots", "hypotheses", "library", "harness", "logs",
}

CODE_SCAN_EXTENSIONS = {
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".js", ".jsx",
    ".ts", ".tsx", ".vue", ".svelte", ".py", ".php", ".rb", ".rs",
    ".gd", ".tscn", ".qml", ".json", ".yaml", ".yml", ".xml", ".md",
}

ASSET_PATH_REF_RE = re.compile(
    r"""(?:src|href|url|icon|image|texture|sprite|background|poster|load_image|load|open|preload)\s*(?:=|\()\s*['"]?([^'"\)\s<>]+?\.(?:png|jpe?g|webp|svg|ico|gif|bmp|avif|ttf|otf|woff2?|glb|gltf|atlas))['"]?""",
    re.IGNORECASE,
)

QUOTED_ASSET_STRING_RE = re.compile(
    r"""['"]([^'"\n\r<>]+?\.(?:png|jpe?g|webp|svg|ico|gif|bmp|avif|ttf|otf|woff2?|glb|gltf|atlas))['"]""",
    re.IGNORECASE,
)

DUMMY_PLACEHOLDER_URL_RE = re.compile(
    r"https?://(?:via\.placeholder\.com|placehold\.co|picsum\.photos|dummyimage\.com|placekitten\.com|lorempixel\.com)\b",
    re.IGNORECASE,
)

LAZY_OBSERVATION_PATTERNS = [
    re.compile(
        r"^\s*(looks?\s+good|renders?\s+(properly|fine|correctly)|no\s+issues?|everything\s+is\s+(fine|ok))\s*\.?\s*$",
        re.IGNORECASE,
    ),
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


def simplify_aspect_ratio(w: int, h: int) -> str:
    if w <= 0 or h <= 0:
        return "UNKNOWN"
    g = math.gcd(w, h)
    rw, rh = w // g, h // g
    if rw > 64 or rh > 64:
        return f"{w / h:.2f}:1"
    return f"{rw}:{rh}"


def get_image_dimensions(path: Path) -> Optional[Tuple[int, int]]:
    """Extract (width, height) from PNG, JPEG, WebP, GIF, BMP, ICO, or SVG headers using pure Python."""
    suffix = path.suffix.lower()
    if suffix == ".svg":
        try:
            txt = path.read_text(encoding="utf-8", errors="ignore")[:4096]
            vb = re.search(
                r'viewBox\s*=\s*["\']\s*[-+]?\d*\.?\d+[\s,]+[-+]?\d*\.?\d+[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)',
                txt,
                re.IGNORECASE,
            )
            if vb:
                return max(1, int(float(vb.group(1)))), max(1, int(float(vb.group(2))))
            wm = re.search(r'\bwidth\s*=\s*["\'](\d+(?:\.\d+)?)(?:px)?["\']', txt, re.IGNORECASE)
            hm = re.search(r'\bheight\s*=\s*["\'](\d+(?:\.\d+)?)(?:px)?["\']', txt, re.IGNORECASE)
            if wm and hm:
                return max(1, int(float(wm.group(1)))), max(1, int(float(hm.group(1))))
        except Exception:
            return None
        return None

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

    # 4. GIF: GIF87a / GIF89a
    if len(data) >= 10 and data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return int(w), int(h)

    # 5. BMP: BM
    if len(data) >= 26 and data[:2] == b"BM":
        w, h = struct.unpack("<ii", data[18:26])
        return abs(int(w)), abs(int(h))

    # 6. ICO: 00 00 01 00
    if len(data) >= 8 and data[:4] == b"\x00\x00\x01\x00":
        w = data[6] or 256
        h = data[7] or 256
        return int(w), int(h)

    return None


def discover_provided_assets(
    workspace: Path,
    sandbox_dir: Optional[Path] = None,
    extra_asset_dirs: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Scan workspace and sandbox for provided visual/media/font/3D assets.
    Returns metadata for each discovered asset: relative path, filename, dimensions, aspect ratio, size.
    """
    workspace = workspace.resolve()
    candidate_roots: List[Path] = []

    # 1. Explicit extra directories passed via CLI
    for d in extra_asset_dirs or []:
        p = (workspace / d).resolve()
        if p.exists():
            candidate_roots.append(p)

    # 2. Conventional asset directories in workspace and sandbox
    search_bases = [workspace]
    if sandbox_dir and sandbox_dir.exists():
        search_bases.append(sandbox_dir.resolve())

    for base in search_bases:
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            if child.name in EXCLUDED_ASSET_SCAN_DIRS:
                continue
            if child.name.lower() in DEFAULT_ASSET_DIR_NAMES:
                candidate_roots.append(child)
            # Also check 1 level deeper (e.g., src/assets, src/icons, public/images, resources/assets)
            if child.name.lower() in {"src", "app", "client", "frontend", "web", "resources", "res"}:
                for subchild in sorted(child.iterdir()):
                    if subchild.is_dir() and subchild.name.lower() in DEFAULT_ASSET_DIR_NAMES:
                        candidate_roots.append(subchild)

    seen_paths: Set[Path] = set()
    assets: List[Dict[str, Any]] = []

    for root in candidate_roots:
        files_iter = [root] if root.is_file() else sorted(root.rglob("*"))
        for f in files_iter:
            if not f.is_file():
                continue
            resolved = f.resolve()
            rel_parts = (
                resolved.relative_to(workspace).parts
                if resolved.is_relative_to(workspace)
                else (resolved.name,)
            )
            if any(part in EXCLUDED_ASSET_SCAN_DIRS for part in rel_parts):
                continue
            if f.suffix.lower() not in ASSET_EXTENSIONS:
                continue
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            rel = (
                resolved.relative_to(workspace).as_posix()
                if resolved.is_relative_to(workspace)
                else resolved.name
            )
            dims = get_image_dimensions(resolved)
            dim_str = f"{dims[0]}x{dims[1]}" if dims else "N/A"
            aspect_str = simplify_aspect_ratio(dims[0], dims[1]) if dims else "N/A"
            assets.append(
                {
                    "path": rel,
                    "abs_path": resolved,
                    "name": resolved.name,
                    "stem": resolved.stem,
                    "ext": resolved.suffix.lower(),
                    "dimensions": dim_str,
                    "aspect_ratio": aspect_str,
                    "bytes": resolved.stat().st_size,
                }
            )

    return assets


def collect_code_files_for_asset_scan(workspace: Path, sandbox_dir: Optional[Path]) -> List[Path]:
    """Collect prototype/UI code files in sandbox and tracked workspace files."""
    files: List[Path] = []
    seen: Set[Path] = set()

    if sandbox_dir and sandbox_dir.exists():
        for f in sorted(sandbox_dir.rglob("*")):
            if not f.is_file():
                continue
            if "visual_captures" in f.parts or "logs" in f.parts:
                continue
            if f.name in {"VISUAL_AUDIT.md", "ra_logger.py", "ra_logger.js", "RALogger.php"}:
                continue
            if f.suffix.lower() in CODE_SCAN_EXTENSIONS or any(
                f.name.lower().endswith(s) for s in VISUAL_COMPOUND_SUFFIXES
            ):
                r = f.resolve()
                if r not in seen:
                    seen.add(r)
                    files.append(r)

    state_path = workspace / "research" / ".ra_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for rel in state.get("context_map_snapshot", {}).get("tracked_files", {}).keys():
                fp = (workspace / rel).resolve()
                if fp.exists() and fp.is_file() and fp not in seen:
                    seen.add(fp)
                    files.append(fp)
        except Exception:
            pass

    return files


def audit_asset_usage_and_paths(
    workspace: Path,
    sandbox_dir: Optional[Path],
    provided_assets: List[Dict[str, Any]],
    required_assets: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Cross-check code files against discovered provided assets:
      1. Mark which provided assets are referenced in code vs. ignored (`UNUSED_PROVIDED_ASSET`).
      2. Detect broken/hallucinated asset paths referenced in code that do not exist on disk.
      3. Detect dummy external placeholder URLs (`placehold.co`, `via.placeholder.com`, etc.).
    """
    code_files = collect_code_files_for_asset_scan(workspace, sandbox_dir)
    combined_code_blobs: List[Tuple[str, str]] = []
    for cf in code_files:
        try:
            rel_cf = cf.relative_to(workspace).as_posix() if cf.is_relative_to(workspace) else cf.name
            combined_code_blobs.append((rel_cf, cf.read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            pass

    # 1. Check which provided assets are referenced in code
    used_assets: List[Dict[str, Any]] = []
    unused_assets: List[Dict[str, Any]] = []

    for asset in provided_assets:
        name = asset["name"]
        rel_path = asset["path"]
        # Strip leading folder like sandbox prefix if referenced relatively inside sandbox
        sandbox_rel = None
        if sandbox_dir and asset["abs_path"].is_relative_to(sandbox_dir.resolve()):
            sandbox_rel = asset["abs_path"].relative_to(sandbox_dir.resolve()).as_posix()

        referenced_in: List[str] = []
        for rel_cf, text in combined_code_blobs:
            if name in text or rel_path in text or (sandbox_rel and sandbox_rel in text):
                referenced_in.append(rel_cf)

        asset["referenced_in"] = referenced_in
        if referenced_in:
            used_assets.append(asset)
        else:
            unused_assets.append(asset)

    # 2. Scan code for broken/non-existent asset references & dummy placeholder URLs
    broken_references: List[Dict[str, Any]] = []
    dummy_placeholders: List[str] = []
    provided_names = [a["name"] for a in provided_assets] + [a["path"] for a in provided_assets]

    seen_broken: Set[Tuple[str, str]] = set()
    for rel_cf, text in combined_code_blobs:
        if Path(rel_cf).suffix.lower() == ".md":
            continue
        cf_dir = (workspace / rel_cf).parent

        for dm in DUMMY_PLACEHOLDER_URL_RE.finditer(text):
            dummy_placeholders.append(f"`{rel_cf}` uses dummy placeholder service `{dm.group(0)}` instead of real assets")

        candidates: Set[str] = set()
        for m in ASSET_PATH_REF_RE.finditer(text):
            candidates.add(m.group(1).strip())
        for m in QUOTED_ASSET_STRING_RE.finditer(text):
            candidates.add(m.group(1).strip())

        for raw_ref in sorted(candidates):
            # Ignore URLs, data URIs, template expressions, or logger/script names
            if (
                raw_ref.startswith(("http://", "https://", "data:", "//", "{", "$", "<"))
                or "{{" in raw_ref
                or "${" in raw_ref
                or "%" in raw_ref
            ):
                continue
            clean_ref = raw_ref.split("?")[0].split("#")[0]
            if clean_ref.startswith("res://"):
                clean_ref = clean_ref[len("res://") :]
            clean_ref_lstrip = clean_ref.lstrip("/")

            # Check possible resolution locations: relative to code file, relative to sandbox, relative to workspace, or matching a provided asset
            possible_paths = [
                (cf_dir / clean_ref),
                (cf_dir / clean_ref_lstrip),
                (workspace / clean_ref_lstrip),
                (workspace / "public" / clean_ref_lstrip),
                (workspace / "static" / clean_ref_lstrip),
                (workspace / "assets" / clean_ref_lstrip),
            ]
            if sandbox_dir:
                possible_paths.extend(
                    [
                        (sandbox_dir / clean_ref_lstrip),
                        (sandbox_dir / "public" / clean_ref_lstrip),
                        (sandbox_dir / "assets" / clean_ref_lstrip),
                    ]
                )

            exists_on_disk = any(p.exists() and p.is_file() for p in possible_paths)
            if not exists_on_disk:
                # Also check if basename matches a provided asset inside a mounted static root
                ref_name = Path(clean_ref_lstrip).name
                if any(a["name"] == ref_name and clean_ref.startswith("/") for a in provided_assets):
                    exists_on_disk = True

            if not exists_on_disk and (rel_cf, clean_ref) not in seen_broken:
                seen_broken.add((rel_cf, clean_ref))
                close = difflib.get_close_matches(Path(clean_ref).name, provided_names, n=2, cutoff=0.4)
                suggestion = f" (Did you mean provided asset: `{', '.join(close)}`?)" if close else ""
                broken_references.append(
                    {
                        "file": rel_cf,
                        "ref": raw_ref,
                        "message": f"`{rel_cf}` references non-existent asset `{raw_ref}`{suggestion}",
                    }
                )

    # 3. Check explicit required assets (--require-assets)
    missing_required: List[str] = []
    for req in required_assets or []:
        req_clean = req.strip()
        if not req_clean:
            continue
        matched = [
            a for a in provided_assets if a["name"] == req_clean or a["path"].endswith(req_clean)
        ]
        if not matched:
            missing_required.append(f"Required asset `{req_clean}` was not found on disk!")
        elif not any(a["referenced_in"] for a in matched):
            missing_required.append(
                f"Required provided asset `{req_clean}` (`{matched[0]['path']}`, {matched[0]['dimensions']}) "
                f"is NOT used anywhere in the prototype code!"
            )

    return {
        "provided_assets": provided_assets,
        "used_assets": used_assets,
        "unused_assets": unused_assets,
        "broken_references": broken_references,
        "dummy_placeholders": dummy_placeholders,
        "missing_required": missing_required,
    }


def format_provided_assets_markdown_table(provided_assets: List[Dict[str, Any]]) -> str:
    if not provided_assets:
        return (
            "| Asset Path | Type | Native Resolution (`WxH`) | Aspect Ratio (`W:H`) | Code Usage Status |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| *(No pre-existing asset files detected in workspace asset folders)* | `N/A` | `N/A` | `N/A` | `N/A` |"
        )
    lines = [
        "| Asset Path | Type | Native Resolution (`WxH`) | Aspect Ratio (`W:H`) | Code Usage Status |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for a in provided_assets[:40]:
        refs = a.get("referenced_in", [])
        status = f"`USED` (in `{', '.join(refs[:2])}`)" if refs else "`UNUSED_PROVIDED_ASSET` (Verify why or wire it!)"
        lines.append(
            f"| `{a['path']}` | `{a['ext']}` | `{a['dimensions']}` | `{a['aspect_ratio']}` | {status} |"
        )
    return "\n".join(lines)


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


def cmd_scan_assets(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    sandbox_dir = (rdir / "sandbox" / args.hypothesis.strip()) if args.hypothesis else None
    provided = discover_provided_assets(workspace, sandbox_dir, args.assets_dir)
    report = audit_asset_usage_and_paths(workspace, sandbox_dir, provided, args.require_assets)

    print("=" * 78)
    print("  RA PROVIDED-ASSET DISCOVERY, USAGE & FIT SCANNER")
    print("=" * 78)
    print(f"  Discovered Provided Assets : {len(provided)}")
    print(f"  Assets Wired in Code       : {len(report['used_assets'])}")
    print(f"  Unused Provided Assets     : {len(report['unused_assets'])}")
    print(f"  Broken Asset Paths in Code : {len(report['broken_references'])}")
    print("-" * 78)
    if provided:
        print("  PROVIDED ASSETS (NATIVE RESOLUTION & ASPECT RATIO FOR CONTAINER FITTING):")
        for a in provided[:30]:
            refs = a.get("referenced_in", [])
            tag = f"[USED in {', '.join(refs[:2])}]" if refs else "[UNUSED — NOT WIRED IN CODE]"
            print(
                f"    - {a['path']} | {a['dimensions']} (Aspect {a['aspect_ratio']}) | {tag}"
            )
    else:
        print("  (No provided asset files discovered in conventional workspace/sandbox folders.)")

    if report["broken_references"]:
        print("-" * 78)
        print("  [ALERT] BROKEN / HALLUCINATED ASSET PATHS IN CODE:")
        for br in report["broken_references"]:
            print(f"    - {br['message']}")

    if report["dummy_placeholders"]:
        print("-" * 78)
        print("  [ALERT] DUMMY PLACEHOLDER URLS DETECTED:")
        for dp in report["dummy_placeholders"]:
            print(f"    - {dp}")
    print("=" * 78)


def cmd_init_audit(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    hyp = args.hypothesis.strip()
    sandbox_dir = rdir / "sandbox" / hyp
    captures_dir = sandbox_dir / "visual_captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    provided = discover_provided_assets(workspace, sandbox_dir, args.assets_dir)
    audit_asset_usage_and_paths(workspace, sandbox_dir, provided, [])

    tpl_path = Path(__file__).resolve().parent.parent / "resources" / "templates" / "VISUAL_AUDIT.md"
    audit_md_path = sandbox_dir / "VISUAL_AUDIT.md"

    parts = hyp.split("_", 1)
    hyp_id = parts[0]
    slug = parts[1] if len(parts) > 1 else "visual"

    assets_table_md = format_provided_assets_markdown_table(provided)

    if not audit_md_path.exists():
        tpl = tpl_path.read_text(encoding="utf-8") if tpl_path.exists() else "# Visual Audit\n"
        content = (
            tpl.replace("{{HYPOTHESIS_ID}}", hyp_id)
            .replace("{{SLUG}}", slug)
            .replace("{{PROVIDED_ASSETS_TABLE}}", assets_table_md)
        )
        audit_md_path.write_text(content, encoding="utf-8")

    # Auto-inventory any images already inside visual_captures/
    images = [f for f in sorted(captures_dir.rglob("*")) if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    print("=" * 78)
    print(f"  RA USER-EYES VISUAL & ASSET-FIT AUDIT INITIALIZED — `{hyp}`")
    print("=" * 78)
    print(f"  Captures Directory : {captures_dir.relative_to(workspace).as_posix()}/")
    print(f"  Visual Audit Report: {audit_md_path.relative_to(workspace).as_posix()}")
    print(f"  Provided Assets    : {len(provided)} discovered in workspace/sandbox")
    for a in provided[:10]:
        refs = a.get("referenced_in", [])
        status = f"USED ({', '.join(refs[:2])})" if refs else "UNUSED"
        print(f"    - Asset: {a['path']} ({a['dimensions']}, Aspect {a['aspect_ratio']}) -> [{status}]")
    if images:
        print(f"  Discovered Captures ({len(images)}):")
        for idx, img in enumerate(images, start=1):
            dims = get_image_dimensions(img)
            dim_str = f"{dims[0]}x{dims[1]}" if dims else "UNKNOWN"
            digest = sha256_file(img)[:12]
            print(f"    - CAP-{idx:02d}: {img.name} ({dim_str}, SHA256: {digest}...)")
    else:
        print("  [ACTION REQUIRED] Wire provided assets with proper aspect-ratio fit, capture live")
        print("                    screenshots into `visual_captures/`, view them (`read_file`), and")
        print("                    complete `VISUAL_AUDIT.md` from the user's view.")
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
    provided = discover_provided_assets(workspace, sandbox_dir, args.assets_dir)
    asset_report = audit_asset_usage_and_paths(workspace, sandbox_dir, provided, args.require_assets)

    if (
        not visual_detected
        and not args.require_visual
        and not captures_dir.exists()
        and not asset_report["broken_references"]
        and not asset_report["missing_required"]
    ):
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

    # 1. Check broken asset paths, dummy placeholder URLs, and ignored provided assets
    for br in asset_report["broken_references"]:
        violations.append(f"[BROKEN_ASSET_PATH] {br['message']}")

    for dp in asset_report["dummy_placeholders"]:
        violations.append(f"[DUMMY_ASSET_PLACEHOLDER] {dp}")

    for mr in asset_report["missing_required"]:
        violations.append(f"[MISSING_REQUIRED_ASSET] {mr}")

    audit_txt = audit_md_path.read_text(encoding="utf-8") if audit_md_path.exists() else ""

    if provided and len(asset_report["used_assets"]) == 0 and not args.allow_unused_assets:
        if "INTENTIONALLY_UNUSED_ASSET:" not in audit_txt:
            sample_names = ", ".join(
                f"`{a['path']}` ({a['dimensions']})" for a in provided[:5]
            )
            violations.append(
                f"[IGNORED_PROVIDED_ASSETS] Workspace provides {len(provided)} asset(s) ({sample_names}), "
                f"but ZERO provided assets are referenced in your prototype code! Wire the user's provided "
                f"assets/icons and fit them properly instead of substituting bare CSS boxes/emoji."
            )

    # 2. Check captured screenshots in visual_captures/
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

    # 3. Validate VISUAL_AUDIT.md
    if not audit_md_path.exists():
        violations.append(
            f"Missing `research/sandbox/{hyp}/VISUAL_AUDIT.md`! Run `ra_visual_audit.py init --hypothesis {hyp}`."
        )
    else:
        txt = audit_txt
        unfilled_markers = [
            "<Confirm that all relevant provided assets",
            "<Verify how each provided asset/icon fits",
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
                        f"State concrete visual geometry, alignment, provided-asset fit/aspect-ratio, and user-view reasoning!"
                    )

    print("=" * 78)
    print(f"  RA USER-EYES VISUAL, PROVIDED-ASSET & REALITY AUDIT — `{hyp}`")
    print("=" * 78)
    print(f"  Visual Trigger Files : {', '.join(trigger_files[:5]) or 'Forced (--require-visual)'}")
    print(
        f"  Provided Assets      : {len(provided)} discovered ({len(asset_report['used_assets'])} wired, "
        f"{len(asset_report['unused_assets'])} unused, {len(asset_report['broken_references'])} broken refs)"
    )
    print(f"  Captured Screenshots : {len(images)}")
    print(f"  Violations Found     : {len(violations)}")
    print("-" * 78)

    if violations:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["visual_audit_passed"] = False
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("  [FAIL] VISUAL & PROVIDED-ASSET REALITY GATE REJECTED THE PROTOTYPE:")
        for v in violations:
            print(f"    - {v}")
        print("-" * 78)
        print("  REQUIRED ACTION:")
        print("    1. Wire all provided user/project assets & icons (no broken paths, no fake emoji/CSS boxes).")
        print("    2. Fit each asset/icon to its container respecting native aspect ratio (`WxH`, `object-fit`).")
        print("    3. Render the live output and capture real screenshots in `visual_captures/`.")
        print("    4. Open and view EVERY screenshot (`read_file`) and complete `VISUAL_AUDIT.md`.")
        print("=" * 78)
        sys.exit(1)

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["visual_audit_passed"] = True
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("  [PASS] Provided assets, container fit, and captured screenshots verified!")
    print("=" * 78)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RA User-Eyes Visual, Provided-Asset & Experiential Reality Auditor")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser(
        "scan-assets",
        help="Scan workspace/sandbox for provided assets, native WxH/aspect ratios, unused assets, and broken code paths",
    )
    p_scan.add_argument("--workspace", default=".", help="Workspace root")
    p_scan.add_argument("--hypothesis", default=None, help="Optional hypothesis folder name (e.g., H001_slug)")
    p_scan.add_argument("--assets-dir", nargs="*", default=[], help="Additional asset directories to scan")
    p_scan.add_argument("--require-assets", nargs="*", default=[], help="Specific asset filenames that must be wired")
    p_scan.set_defaults(func=cmd_scan_assets)

    p_init = sub.add_parser("init", help="Initialize visual_captures/ folder and VISUAL_AUDIT.md for a hypothesis")
    p_init.add_argument("--workspace", default=".", help="Workspace root")
    p_init.add_argument("--hypothesis", required=True, help="Hypothesis folder name (e.g., H001_slug)")
    p_init.add_argument("--assets-dir", nargs="*", default=[], help="Additional asset directories to scan")
    p_init.set_defaults(func=cmd_init_audit)

    p_audit = sub.add_parser("audit", help="Verify provided-asset usage/fit, captured screenshots, and VISUAL_AUDIT.md")
    p_audit.add_argument("--workspace", default=".", help="Workspace root")
    p_audit.add_argument("--hypothesis", required=True, help="Hypothesis folder name (e.g., H001_slug)")
    p_audit.add_argument("--require-visual", action="store_true", help="Force visual audit even if no UI extensions detected")
    p_audit.add_argument("--assets-dir", nargs="*", default=[], help="Additional asset directories to scan")
    p_audit.add_argument("--require-assets", nargs="*", default=[], help="Specific asset filenames that must be wired")
    p_audit.add_argument("--allow-unused-assets", action="store_true", help="Do not fail if provided assets are unused")
    p_audit.set_defaults(func=cmd_audit)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
