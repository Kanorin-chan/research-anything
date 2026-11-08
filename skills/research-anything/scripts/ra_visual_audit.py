#!/usr/bin/env python3
"""
ra_visual_audit.py — User-Eyes Visual, Provided-Asset & Experiential Reality Auditor for RA.

Prevents "Code-Context Blindness" (where an AI assumes the UI/game/chart/render works
because the code compiled or DOM exists, or ignores/misfits the user's provided assets).

Enforces:
1. Auto-detection of visual/UI/rendering scope across sandbox and target files (and, in
   STANDALONE mode, the project's own source files).
2. Provided-Asset Discovery, Usage & Fit Auditing:
   - Scans workspace & sandbox asset folders (`assets/`, `public/`, `static/`, `icons/`,
     `images/`, `img/`, `sprites/`, `textures/`, `media/`, `ui/`, `reference/`, etc.).
   - Extracts native `WxH` dimensions and aspect ratios (`W:H`) for `.png`, `.jpg`, `.jpeg`,
     `.webp`, `.gif`, `.bmp`, `.ico` (largest image), and `.svg` (root `width`/`height`,
     else `viewBox`) so the agent fits every asset/icon into a properly proportioned slot.
   - Cross-checks code against provided assets. An asset counts as used only when a real
     path reference (quoted string, `src=`/`href=`/`url(...)`, `key: value`) resolves to it —
     relative to the file, the workspace, `public/`/`static/` roots, or the `@/` / `~/` aliases.
     Docs (`.md`, `.txt`, ...) never count. This catches:
     a) **Ignored Provided Assets**: Provided assets exist on disk, but the AI ignored them
        and rendered bare CSS boxes, text, or emoji instead.
     b) **Hallucinated / Broken Asset Paths**: Code references `assets/foo.png` that does
        not exist on disk (auto-suggests closest real provided asset).
     c) **Dummy Placeholder URLs**: Code uses `placehold.co` / `via.placeholder.com` /
        `picsum.photos` instead of real assets.
3. Verification of real captured screenshots (`.png`, `.jpg`, `.jpeg`, `.webp`) in
   `research/sandbox/<hypothesis>/visual_captures/`:
   - Parses binary headers to verify real resolution (`width x height >= 64x64`).
   - Rejects 0-byte, tiny, or blank-screen captures by decoded-pixel variance (Pillow when
     installed; else a pure-stdlib PNG decoder; else bytes-per-pixel), naming the method used.
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
import os
import re
import struct
import sys
import zlib
from collections import Counter
from itertools import accumulate
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

try:  # optional: exact pixel statistics for every format
    from PIL import Image as _PILImage
except Exception:  # pragma: no cover - stdlib fallback below
    _PILImage = None

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

# Same pruning as ra_cheese_audit.py (case-insensitive directory names).
PRUNED_DIR_NAMES = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "jspm_packages", "venv", ".venv", "env",
    "virtualenv", "site-packages", "__pycache__", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    "dist", "build", "builds", "out", "target", "obj", "bin", "library", "temp", ".gradle", ".next", ".nuxt",
    ".svelte-kit", ".dart_tool", ".expo", "vendor", "third_party", "third-party", "thirdparty", "external",
    "coverage", "pods", "research", ".agents", ".claude", ".codex", ".gemini",
}
TEST_DIR_NAMES = {
    "test", "tests", "__tests__", "__mocks__", "spec", "specs", "testdata", "test_data", "fixtures", "androidtest",
}
# Sandboxes live under research/, so asset and sandbox walks keep it but skip RA's own bookkeeping dirs.
EXCLUDED_ASSET_SCAN_DIRS = (PRUNED_DIR_NAMES - {"research"}) | {
    "visual_captures", "graveyard", "context_snapshots", "hypotheses", "harness", "logs",
}

CODE_SCAN_EXTENSIONS = {
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".js", ".mjs", ".cjs", ".jsx",
    ".ts", ".tsx", ".vue", ".svelte", ".py", ".php", ".rb", ".rs", ".cs", ".kt", ".dart",
    ".gd", ".tscn", ".qml", ".json", ".yaml", ".yml", ".xml",
}
DOC_EXTENSIONS = {".md", ".markdown", ".rst", ".txt", ".adoc"}
UI_SOURCE_EXTENSIONS = VISUAL_EXTENSIONS | {".js", ".mjs", ".cjs", ".ts"}
SKIPPED_CODE_FILE_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock"}
RA_SDK_FILE_NAMES = {"visual_audit.md", "ra_logger.py", "ra_logger.js", "ra_logger.ts", "ra_logger.mjs", "ralogger.php"}
MAX_CODE_FILE_BYTES = 2_000_000

_ASSET_EXT_ALT = r"png|jpe?g|webp|svg|ico|gif|bmp|avif|ttf|otf|woff2?|glb|gltf|atlas"

ASSET_PATH_REF_RE = re.compile(
    r"""(?:src|href|url|icon|image|texture|sprite|background|poster|load_image|load|open|preload)\s*(?:=|\()\s*['"]?([^'"\)\s<>]+?\.(?:"""
    + _ASSET_EXT_ALT + r"""))['"]?(?![\w.])""",
    re.IGNORECASE,
)

QUOTED_ASSET_STRING_RE = re.compile(
    r"""['"`]([^'"`\n\r<>]+?\.(?:""" + _ASSET_EXT_ALT + r"""))(?:[?#][^'"`\n\r<>]*)?['"`]""",
    re.IGNORECASE,
)

# `icon: images/logo.png` / `icon = images/logo.png` in YAML/INI/TOML-ish configs.
KEY_VALUE_ASSET_RE = re.compile(
    r"""^\s*[\w.\-]+\s*[:=]\s*([^\s'"#]+\.(?:""" + _ASSET_EXT_ALT + r"""))\s*$""",
    re.IGNORECASE | re.MULTILINE,
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

# Blank-capture thresholds: max per-channel std-dev, and share of pixels within +-6 of the dominant luminance.
BLANK_MAX_STDDEV = 4.0
BLANK_DOMINANT_SHARE = 0.999
BLANK_MAX_BYTES_PER_PIXEL = 0.02
STDLIB_PNG_MAX_RAW_BYTES = 24_000_000


def _utf8_console() -> None:
    # Windows consoles default to cp932/cp1252, which cannot print the report's dashes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _ra_common():
    # The script dir is not on sys.path under `python -I`.
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import ra_common

    return ra_common


def _mark_passed(state: Dict[str, Any], workspace: Path, hyp: str) -> None:
    state["visual_audit_passed"] = True
    state.setdefault("pass_fingerprints", {})["visual_audit_passed"] = _ra_common().code_fingerprint(workspace, state, hyp)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def simplify_aspect_ratio(w: float, h: float) -> str:
    if w <= 0 or h <= 0:
        return "UNKNOWN"
    if not (isinstance(w, int) and isinstance(h, int)):
        return f"{w / h:.2f}:1"
    g = math.gcd(w, h)
    rw, rh = w // g, h // g
    if rw > 64 or rh > 64:
        return f"{w / h:.2f}:1"
    return f"{rw}:{rh}"


# --------------------------------------------------------------------------- dimensions

_SVG_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_SVG_UNIT_PX = {"": 1.0, "px": 1.0, "pt": 4 / 3, "pc": 16.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4}


def _clean_num(v: float) -> Any:
    return int(round(v)) if abs(v - round(v)) < 1e-6 else round(v, 3)


def _svg_dimensions(path: Path) -> Optional[Tuple[Any, Any]]:
    """Root <svg> size: absolute width/height win, else viewBox (scaled by one absolute side if present)."""
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")[:2_000_000]
    except OSError:
        return None
    txt = re.sub(r"<!--.*?-->", "", txt, flags=re.DOTALL)
    m = re.search(r"<svg\b([^>]*)>", txt, re.IGNORECASE)
    if not m:
        return None
    attrs = m.group(1)

    def attr(name: str) -> Optional[str]:
        am = re.search(rf"""(?<![\w:\-]){name}\s*=\s*["']([^"']*)["']""", attrs, re.IGNORECASE)
        return am.group(1).strip() if am else None

    def absolute(value: Optional[str]) -> Optional[float]:
        vm = re.fullmatch(rf"({_SVG_NUM})\s*(px|pt|pc|in|cm|mm)?", value or "", re.IGNORECASE)
        if not vm:
            return None  # %, em, auto...: relative, not an intrinsic size
        px = float(vm.group(1)) * _SVG_UNIT_PX[(vm.group(2) or "").lower()]
        return px if px > 0 else None

    w, h = absolute(attr("width")), absolute(attr("height"))
    if w and h:
        return _clean_num(w), _clean_num(h)
    nums = re.findall(_SVG_NUM, attr("viewBox") or "")
    if len(nums) == 4 and float(nums[2]) > 0 and float(nums[3]) > 0:
        vw, vh = float(nums[2]), float(nums[3])
        if w:
            return _clean_num(w), _clean_num(w * vh / vw)
        if h:
            return _clean_num(h * vw / vh), _clean_num(h)
        return _clean_num(vw), _clean_num(vh)
    return None


def get_image_dimensions(path: Path) -> Optional[Tuple[Any, Any]]:
    """Extract (width, height) from PNG, JPEG, WebP, GIF, BMP, ICO, or SVG headers using pure Python."""
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return _svg_dimensions(path)

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

    # 6. ICO: 00 00 01 00 + one 16-byte directory entry per image; report the largest
    if len(data) >= 22 and data[:4] == b"\x00\x00\x01\x00":
        count = struct.unpack("<H", data[4:6])[0]
        sizes = [
            (data[6 + 16 * i] or 256, data[7 + 16 * i] or 256)
            for i in range(count)
            if 6 + 16 * i + 2 <= len(data)
        ]
        if sizes:
            return max(sizes, key=lambda s: s[0] * s[1])

    return None


# --------------------------------------------------------------------------- blank-capture detection

_SWAR_MASKS: Dict[int, Tuple[int, int]] = {}


def _add_rows(a: bytes, b: bytes) -> bytes:
    """Bytewise (a + b) & 0xFF without a Python loop (SWAR on one big int)."""
    n = len(a)
    if n not in _SWAR_MASKS:
        hi = int.from_bytes(b"\x80" * n, "little")
        _SWAR_MASKS[n] = (hi, hi ^ int.from_bytes(b"\xff" * n, "little"))
    hi, lo = _SWAR_MASKS[n]
    x, y = int.from_bytes(a, "little"), int.from_bytes(b, "little")
    return (((x & lo) + (y & lo)) ^ ((x ^ y) & hi)).to_bytes(n, "little")


def _unfilter_png(raw: bytes, height: int, stride: int, bpp: int) -> List[bytes]:
    rows: List[bytes] = []
    prev = bytes(stride)
    pos = 0
    for _ in range(height):
        ft, line = raw[pos], raw[pos + 1 : pos + 1 + stride]
        pos += stride + 1
        if ft == 0:
            cur = line
        elif ft == 1:
            out = bytearray(line)
            for c in range(bpp):
                out[c::bpp] = bytes(v & 0xFF for v in accumulate(line[c::bpp]))
            cur = bytes(out)
        elif ft == 2:
            cur = _add_rows(line, prev)
        elif ft in (3, 4):
            out = bytearray(line)
            for k in range(stride):
                a = out[k - bpp] if k >= bpp else 0
                b = prev[k]
                if ft == 3:
                    out[k] = (line[k] + ((a + b) >> 1)) & 0xFF
                else:
                    c = prev[k - bpp] if k >= bpp else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    out[k] = (line[k] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
            cur = bytes(out)
        else:
            raise ValueError(f"bad PNG filter {ft}")
        rows.append(cur)
        prev = cur
    return rows


def _stdlib_png_samples(data: bytes) -> Optional[List[Tuple[int, int, int]]]:
    """Decode a non-interlaced 8/16-bit PNG with zlib and return sampled RGB pixels (None if unsupported)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, palette, ihdr = 8, [], b"", None
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body[:13])
        elif ctype == b"PLTE":
            palette = body
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if not ihdr:
        return None
    w, h, depth, color, _, _, interlace = ihdr
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if not channels or interlace or depth not in (8, 16) or (color == 3 and depth != 8):
        return None
    bpp = channels * depth // 8
    stride = w * bpp
    if h * (stride + 1) > STDLIB_PNG_MAX_RAW_BYTES:
        return None
    rows = _unfilter_png(zlib.decompress(b"".join(idat)), h, stride, bpp)

    step = max(1, math.ceil(math.sqrt(w * h / 300_000)))
    samples: List[Tuple[int, int, int]] = []
    for row in rows[::step]:
        if depth == 16:
            row = row[0::2]  # high byte of each sample
        px = channels
        if color == 3:
            idx = row[::step]
            samples.extend((palette[3 * i], palette[3 * i + 1], palette[3 * i + 2]) for i in idx if 3 * i + 2 < len(palette))
        elif color in (0, 4):
            g = row[0::px][::step]
            samples.extend(zip(g, g, g))
        else:
            samples.extend(zip(row[0::px][::step], row[1::px][::step], row[2::px][::step]))
    return samples


def _blank_verdict(sd_max: float, dominant: float, method: str) -> Tuple[bool, str]:
    blank = sd_max < BLANK_MAX_STDDEV or dominant >= BLANK_DOMINANT_SHARE
    return blank, f"pixel std-dev {sd_max:.2f}, {dominant * 100:.2f}% one colour [{method}]"


def _stats_from_hists(channel_hists: List[List[int]], lum_hist: List[int], method: str) -> Tuple[bool, str]:
    sds = []
    for hist in channel_hists:
        n = sum(hist) or 1
        mean = sum(i * c for i, c in enumerate(hist)) / n
        sds.append(math.sqrt(sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / n))
    n = sum(lum_hist) or 1
    mode = max(range(256), key=lambda i: lum_hist[i])
    dominant = sum(lum_hist[max(0, mode - 6) : mode + 7]) / n
    return _blank_verdict(max(sds), dominant, method)


def measure_blankness(path: Path, raw: bytes, dims: Optional[Tuple[Any, Any]]) -> Tuple[Optional[bool], str]:
    """(is_blank, evidence). Method: Pillow pixels > stdlib PNG pixels > bytes-per-pixel."""
    pil_note = ""
    if _PILImage is not None:
        try:
            with _PILImage.open(path) as im:
                rgb = im.convert("RGB")
                hist = rgb.histogram()
                lum = rgb.convert("L").histogram()
            return _stats_from_hists([hist[0:256], hist[256:512], hist[512:768]], lum, "Pillow pixel variance")
        except Exception as exc:  # unreadable to Pillow: fall back and say why
            pil_note = f"; Pillow could not decode it: {exc}"
    try:
        samples = _stdlib_png_samples(raw)
    except (zlib.error, ValueError, IndexError, struct.error):
        samples = None
    if samples:
        chans = [[0] * 256 for _ in range(3)]
        lum = [0] * 256
        for c, cnt in Counter(samples).items():
            for k in range(3):
                chans[k][c[k]] += cnt
            lum[(c[0] * 299 + c[1] * 587 + c[2] * 114) // 1000] += cnt
        return _stats_from_hists(chans, lum, "stdlib PNG pixel variance" + pil_note)
    if dims and dims[0] * dims[1] > 0:
        bpp = len(raw) / (dims[0] * dims[1])
        return bpp < BLANK_MAX_BYTES_PER_PIXEL, (
            f"{bpp:.4f} bytes/pixel [bytes-per-pixel estimate; install Pillow for a pixel check{pil_note}]"
        )
    return None, "not measured (unknown dimensions)" + pil_note


# --------------------------------------------------------------------------- walking

def _prune(cur: str, dirs: List[str], excluded: Set[str], skip_tests: bool) -> List[str]:
    kept = []
    for d in dirs:
        dl = d.lower()
        if dl in excluded or (dl.startswith(".") and dl != ".github") or dl.endswith(".egg-info"):
            continue
        if skip_tests and dl in TEST_DIR_NAMES:
            continue
        if os.path.isfile(os.path.join(cur, d, "pyvenv.cfg")):  # a venv under any name
            continue
        kept.append(d)
    return sorted(kept)


def _walk_files(root: Path, excluded: Set[str], skip_tests: bool) -> Iterator[Path]:
    for cur, dirs, files in os.walk(root):
        dirs[:] = _prune(cur, dirs, excluded, skip_tests)
        for f in sorted(files):
            yield Path(cur, f)


def _is_code_file(f: Path) -> bool:
    name = f.name.lower()
    if name in SKIPPED_CODE_FILE_NAMES or name in RA_SDK_FILE_NAMES or ".min." in name:
        return False
    return f.suffix.lower() in CODE_SCAN_EXTENSIONS or any(name.endswith(s) for s in VISUAL_COMPOUND_SUFFIXES)


def _is_relative(p: Path, base: Path) -> bool:
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


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
            if not child.is_dir() or child.name.lower() in EXCLUDED_ASSET_SCAN_DIRS:
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
        files_iter = [root] if root.is_file() else _walk_files(root, EXCLUDED_ASSET_SCAN_DIRS, skip_tests=False)
        for f in files_iter:
            if f.suffix.lower() not in ASSET_EXTENSIONS or not f.is_file():
                continue
            resolved = f.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            rel = resolved.relative_to(workspace).as_posix() if _is_relative(resolved, workspace) else resolved.name
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


def _tracked_files(workspace: Path) -> List[Path]:
    state_path = workspace / "research" / ".ra_state.json"
    if not state_path.exists():
        return []
    try:
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    out = []
    for rel in state.get("context_map_snapshot", {}).get("tracked_files", {}).keys():
        fp = (workspace / rel).resolve()
        if fp.is_file():
            out.append(fp)
    return out


def collect_code_files_for_asset_scan(
    workspace: Path, sandbox_dir: Optional[Path], standalone: bool = False
) -> List[Tuple[Path, bool]]:
    """(file, found only by the project walk): sandbox code + tracked files, plus project source when standalone.

    Docs never count.
    """
    files: List[Tuple[Path, bool]] = []
    seen: Set[Path] = set()

    def add(f: Path, project_only: bool = False) -> None:
        if f.suffix.lower() in DOC_EXTENSIONS or not _is_code_file(f):
            return
        r = f.resolve()
        if r in seen:
            return
        try:
            if r.stat().st_size > MAX_CODE_FILE_BYTES:
                return
        except OSError:
            return
        seen.add(r)
        files.append((r, project_only))

    if sandbox_dir and sandbox_dir.exists():
        for f in _walk_files(sandbox_dir, EXCLUDED_ASSET_SCAN_DIRS, skip_tests=False):
            add(f)
    for f in _tracked_files(workspace):
        add(f)
    if standalone:
        for f in _walk_files(workspace, PRUNED_DIR_NAMES, skip_tests=True):
            add(f, project_only=True)
    return files


# --------------------------------------------------------------------------- reference resolution

def _extract_asset_refs(text: str) -> Set[str]:
    refs: Set[str] = set()
    for rx in (ASSET_PATH_REF_RE, QUOTED_ASSET_STRING_RE, KEY_VALUE_ASSET_RE):
        for m in rx.finditer(text):
            ref = m.group(1).strip()
            # Prose in a string ("Click logo.png to open") is not a path.
            if ref and (not re.search(r"\s", ref) or "/" in ref):
                refs.add(ref)
    return refs


def _is_dynamic_or_external(ref: str) -> bool:
    low = ref.lower()
    if low.startswith(("res://", "user://", "~/")):
        return False
    if "://" in low or low.startswith(("data:", "//", "{", "$", "<", "~", "mailto:")):
        return True  # URL, data URI, template, or `~pkg/...` node_modules import
    return any(tok in ref for tok in ("{", "}", "(", ")", "%", "*"))


def _resolve_asset_ref(
    ref: str,
    code_file: Path,
    workspace: Path,
    sandbox_dir: Optional[Path],
    by_path: Dict[str, Dict[str, Any]],
    by_name: Dict[str, List[Dict[str, Any]]],
) -> Tuple[bool, List[Dict[str, Any]], bool]:
    """(exists, provided assets it points at, its folder exists). Tries file-relative, root, public/static, aliases."""
    clean = ref.split("?")[0].split("#")[0].replace("\\", "/")
    for prefix in ("res://", "user://"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
    bases: List[Tuple[Path, str]] = []
    if clean.startswith(("@/", "~/")):
        rest = clean[2:]
        bases += [(workspace / "src", rest), (workspace, rest)]
    elif clean.startswith("@") and "/" in clean:
        alias, rest = clean[1:].split("/", 1)  # e.g. @assets/x -> src/assets/x
        bases += [(workspace / "src" / alias, rest), (workspace / alias, rest)]
    elif clean.startswith("/"):
        rest = clean.lstrip("/")
        roots = [workspace, workspace / "public", workspace / "static"]
        if sandbox_dir:
            roots += [sandbox_dir, sandbox_dir / "public", sandbox_dir / "static"]
        bases += [(r, rest) for r in roots]
    else:
        rest = clean
        bases.append((code_file.parent, rest))
        roots = [workspace, workspace / "public", workspace / "static", workspace / "assets"]
        if sandbox_dir:
            roots += [sandbox_dir, sandbox_dir / "public", sandbox_dir / "assets"]
        bases += [(r, rest) for r in roots]

    dir_exists = False
    for base, rel in bases:
        try:
            cand = (base / rel).resolve()
            if not cand.is_file():
                dir_exists = dir_exists or cand.parent.is_dir()
                continue
        except (OSError, ValueError):
            continue
        hit = by_path.get(str(cand))
        return True, [hit] if hit else [], True

    # Not on disk as written: match a provided asset by path suffix (or bare filename).
    norm = re.sub(r"^(?:\.{1,2}/|/|[@~][\w-]*/)+", "", clean)
    if not norm:
        return False, [], dir_exists
    if "/" in norm:
        hits = [a for p, a in by_path.items() if a["path"] == norm or a["path"].endswith("/" + norm)]
    else:
        hits = by_name.get(norm, [])
    return bool(hits), hits, dir_exists


def audit_asset_usage_and_paths(
    workspace: Path,
    sandbox_dir: Optional[Path],
    provided_assets: List[Dict[str, Any]],
    required_assets: Optional[List[str]] = None,
    standalone: bool = False,
) -> Dict[str, Any]:
    """
    Cross-check code files against discovered provided assets:
      1. Mark which provided assets are referenced in code vs. ignored (`UNUSED_PROVIDED_ASSET`).
      2. Detect broken/hallucinated asset paths referenced in code that do not exist on disk.
      3. Detect dummy external placeholder URLs (`placehold.co`, `via.placeholder.com`, etc.).
    """
    workspace = workspace.resolve()
    sandbox_res = sandbox_dir.resolve() if sandbox_dir else None
    code_files = collect_code_files_for_asset_scan(workspace, sandbox_res, standalone)

    by_path = {str(a["abs_path"]): a for a in provided_assets}
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for a in provided_assets:
        by_name.setdefault(a["name"], []).append(a)
        a["referenced_in"] = []
    provided_names = [a["name"] for a in provided_assets] + [a["path"] for a in provided_assets]
    provided_lower = {a["name"].lower() for a in provided_assets}

    broken_references: List[Dict[str, Any]] = []
    dummy_placeholders: List[str] = []
    for cf, project_only in code_files:
        rel_cf = cf.relative_to(workspace).as_posix() if _is_relative(cf, workspace) else cf.name
        try:
            text = cf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > 4000 and len(text) / (text.count("\n") + 1) > 300:
            continue  # minified bundle
        # Project-walk data files (JSON dumps, scripts that write images) name outputs, not wired assets.
        ui_source = cf.suffix.lower() in UI_SOURCE_EXTENSIONS or cf.name.lower().endswith(VISUAL_COMPOUND_SUFFIXES)

        for dm in DUMMY_PLACEHOLDER_URL_RE.finditer(text):
            dummy_placeholders.append(f"`{rel_cf}` uses dummy placeholder service `{dm.group(0)}` instead of real assets")

        can_break = not project_only or ui_source
        for raw_ref in sorted(_extract_asset_refs(text)):
            if _is_dynamic_or_external(raw_ref):
                continue
            # Cheap skip: cannot be broken here and its filename is no provided asset's.
            if not can_break and raw_ref.replace("\\", "/").split("?")[0].rsplit("/", 1)[-1].lower() not in provided_lower:
                continue
            exists, hits, dir_exists = _resolve_asset_ref(raw_ref, cf, workspace, sandbox_res, by_path, by_name)
            for a in hits:
                if rel_cf not in a["referenced_in"]:
                    a["referenced_in"].append(rel_cf)
            if not exists and (not project_only or (ui_source and dir_exists)):
                close = difflib.get_close_matches(Path(raw_ref).name, provided_names, n=2, cutoff=0.4)
                suggestion = f" (Did you mean provided asset: `{', '.join(close)}`?)" if close else ""
                broken_references.append(
                    {
                        "file": rel_cf,
                        "ref": raw_ref,
                        "message": f"`{rel_cf}` references non-existent asset `{raw_ref}`{suggestion}",
                    }
                )

    used_assets = [a for a in provided_assets if a["referenced_in"]]
    unused_assets = [a for a in provided_assets if not a["referenced_in"]]

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
        "code_files_scanned": len(code_files),
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


def is_visual_project_or_hypothesis(sandbox_dir: Path, workspace: Path, standalone: bool = False) -> Tuple[bool, List[str]]:
    """Detect whether the hypothesis, mapped files (or, standalone, the project) involve visual/UI/rendering output."""
    workspace = workspace.resolve()
    matched_files: List[str] = []
    search_files: List[Path] = []
    if sandbox_dir.exists():
        search_files.extend(_walk_files(sandbox_dir, EXCLUDED_ASSET_SCAN_DIRS, skip_tests=False))
    search_files.extend(_tracked_files(workspace))
    if standalone:
        search_files.extend(_walk_files(workspace, PRUNED_DIR_NAMES, skip_tests=True))

    seen: Set[Path] = set()
    candidate_exts = VISUAL_EXTENSIONS | {".py", ".js", ".mjs", ".ts", ".rs", ".cpp", ".cs"}
    for f in search_files:
        name_l = f.name.lower()
        if f.suffix.lower() not in candidate_exts and not name_l.endswith(VISUAL_COMPOUND_SUFFIXES):
            continue
        r = f.resolve()
        if r in seen or r.name.lower() in RA_SDK_FILE_NAMES:
            continue
        seen.add(r)
        name_lower = r.name.lower()
        rel = r.relative_to(workspace).as_posix() if _is_relative(r, workspace) else r.name
        if r.suffix.lower() in VISUAL_EXTENSIONS or any(name_lower.endswith(s) for s in VISUAL_COMPOUND_SUFFIXES):
            matched_files.append(rel)
            continue
        if r.suffix.lower() in {".py", ".js", ".mjs", ".ts", ".rs", ".cpp", ".cs"}:
            try:
                with r.open("r", encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read(8000)
                if VISUAL_CODE_IMPORTS_RE.search(txt):
                    matched_files.append(rel)
            except OSError:
                continue

    return len(matched_files) > 0, matched_files


def _is_standalone(hyp: Optional[str]) -> bool:
    return not hyp or hyp.strip().upper() == "STANDALONE"


def cmd_scan_assets(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    rdir = workspace / "research"
    sandbox_dir = (rdir / "sandbox" / args.hypothesis.strip()) if args.hypothesis else None
    standalone = _is_standalone(args.hypothesis)
    provided = discover_provided_assets(workspace, sandbox_dir, args.assets_dir)
    report = audit_asset_usage_and_paths(workspace, sandbox_dir, provided, args.require_assets, standalone)

    print("=" * 78)
    print("  RA PROVIDED-ASSET DISCOVERY, USAGE & FIT SCANNER")
    print("=" * 78)
    scope = "project source + sandbox + tracked files" if standalone else "sandbox + tracked files"
    print(f"  Code Files Scanned         : {report['code_files_scanned']} ({scope}; docs ignored)")
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
    audit_asset_usage_and_paths(workspace, sandbox_dir, provided, [], _is_standalone(hyp))

    tpl_path = Path(__file__).resolve().parent.parent / "resources" / "templates" / "VISUAL_AUDIT.md"
    audit_md_path = sandbox_dir / "VISUAL_AUDIT.md"

    parts = hyp.split("_", 1)
    hyp_id = parts[0]
    slug = parts[1] if len(parts) > 1 else "visual"

    assets_table_md = format_provided_assets_markdown_table(provided)

    if not audit_md_path.exists():
        tpl = tpl_path.read_text(encoding="utf-8-sig") if tpl_path.exists() else "# Visual Audit\n"
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
    standalone = _is_standalone(hyp)
    sandbox_dir = rdir / "sandbox" / hyp
    captures_dir = sandbox_dir / "visual_captures"
    audit_md_path = sandbox_dir / "VISUAL_AUDIT.md"

    visual_detected, trigger_files = is_visual_project_or_hypothesis(sandbox_dir, workspace, standalone)
    provided = discover_provided_assets(workspace, sandbox_dir, args.assets_dir)
    asset_report = audit_asset_usage_and_paths(workspace, sandbox_dir, provided, args.require_assets, standalone)

    if (
        not visual_detected
        and not args.require_visual
        and not captures_dir.exists()
        and not asset_report["broken_references"]
        and not asset_report["missing_required"]
    ):
        scope = "project source, sandbox or tracked context map" if standalone else "sandbox or tracked context map"
        print("=" * 78)
        print(f"  RA VISUAL AUDIT — `{hyp}` (NON-VISUAL SCOPE)")
        print("=" * 78)
        print(f"  No UI/CSS/rendering files detected in {scope}.")
        print("  Visual audit marked NOT_APPLICABLE (PASS). Use `--require-visual` to force visual verification.")
        print("=" * 78)
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            _mark_passed(state, workspace, hyp)
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

    audit_txt = audit_md_path.read_text(encoding="utf-8-sig") if audit_md_path.exists() else ""

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

    # Validate each image file's binary dimensions, size, and decoded-pixel blankness
    blank_checks: List[str] = []
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
        blank, evidence = measure_blankness(img, raw, dims)
        blank_checks.append(f"{img.name}: {evidence}")
        if blank:
            violations.append(
                f"`{img.name}` is (nearly) uniform — {evidence} — indicates a blank/empty screen render!"
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

    if trigger_files:
        trigger_label = ", ".join(trigger_files[:5]) + (f" (+{len(trigger_files) - 5} more)" if len(trigger_files) > 5 else "")
    elif args.require_visual:
        trigger_label = "none detected — forced by --require-visual"
    elif captures_dir.exists():
        trigger_label = "none detected — audited because visual_captures/ exists"
    else:
        trigger_label = "none detected — audited because of broken/missing asset references"

    print("=" * 78)
    print(f"  RA USER-EYES VISUAL, PROVIDED-ASSET & REALITY AUDIT — `{hyp}`")
    print("=" * 78)
    print(f"  Visual Trigger Files : {trigger_label}")
    print(
        f"  Provided Assets      : {len(provided)} discovered ({len(asset_report['used_assets'])} wired, "
        f"{len(asset_report['unused_assets'])} unused, {len(asset_report['broken_references'])} broken refs)"
    )
    print(f"  Captured Screenshots : {len(images)}")
    for bc in blank_checks:
        print(f"    - {bc}")
    print(f"  Violations Found     : {len(violations)}")
    print("-" * 78)

    if violations:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
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
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        _mark_passed(state, workspace, hyp)
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
    p_scan.add_argument(
        "--hypothesis", default=None,
        help="Optional hypothesis folder name (e.g., H001_slug); omitted or STANDALONE also scans the project's source",
    )
    p_scan.add_argument("--assets-dir", nargs="*", default=[], help="Additional asset directories to scan")
    p_scan.add_argument("--require-assets", nargs="*", default=[], help="Specific asset filenames that must be wired")
    p_scan.set_defaults(func=cmd_scan_assets)

    p_init = sub.add_parser("init", help="Initialize visual_captures/ folder and VISUAL_AUDIT.md for a hypothesis")
    p_init.add_argument("--workspace", default=".", help="Workspace root")
    p_init.add_argument("--hypothesis", default="STANDALONE", help="Hypothesis folder name (e.g., H001_slug) or STANDALONE")
    p_init.add_argument("--assets-dir", nargs="*", default=[], help="Additional asset directories to scan")
    p_init.set_defaults(func=cmd_init_audit)

    p_audit = sub.add_parser("audit", help="Verify provided-asset usage/fit, captured screenshots, and VISUAL_AUDIT.md")
    p_audit.add_argument("--workspace", default=".", help="Workspace root")
    p_audit.add_argument(
        "--hypothesis", default="STANDALONE",
        help="Hypothesis folder name (e.g., H001_slug) or STANDALONE (also scans the project's source)",
    )
    p_audit.add_argument("--require-visual", action="store_true", help="Force visual audit even if no UI extensions detected")
    p_audit.add_argument("--assets-dir", nargs="*", default=[], help="Additional asset directories to scan")
    p_audit.add_argument("--require-assets", nargs="*", default=[], help="Specific asset filenames that must be wired")
    p_audit.add_argument("--allow-unused-assets", action="store_true", help="Do not fail if provided assets are unused")
    p_audit.set_defaults(func=cmd_audit)

    return p


def main() -> None:
    _utf8_console()
    parser = build_parser()
    args = parser.parse_args()
    if not Path(args.workspace).is_dir():
        print(f"[RA VISUAL AUDIT] ERROR: Workspace directory not found: {Path(args.workspace).resolve()}", file=sys.stderr)
        sys.exit(2)
    args.func(args)


if __name__ == "__main__":
    main()
