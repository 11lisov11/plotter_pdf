"""Offline Plotterfun adapter. Returns clipped millimetre paths, never sends them."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from .photo_to_plotter import PhotoPlotResult, WorkArea, polylines_bounds

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_COMMIT = "faf67d4dadc359a9d5703b0c4e501ea3bbad84d9"
STYLES = {
    "squiggle": "Squiggle", "squiggleLeftRight": "Squiggle Left-Right",
    "spiral": "Spiral", "spiral-page": "Spiral - full A4 field",
    "polyspiral": "Polygon Spiral", "sawtooth": "Sawtooth",
    "stipple": "Stipples - circles", "delaunay": "Delaunay", "linedraw": "Linedraw",
    "mosaic": "Mosaic", "subline": "Subline", "springs": "Springs", "waves": "Waves",
    "needles": "Needles", "implode": "Implode", "halftone": "Halftone", "boxes": "Boxes",
    "dots": "Dots", "jaggy": "Jaggy", "longwave": "Longwave", "linescan": "Linescan",
    "woven": "Woven", "peano": "Peano", "margins": "Margins",
    "stipple-spirals": "Stipples - spirals", "stipple-hexagons": "Stipples - hexagons",
    "stipple-pentagrams": "Stipples - pentagrams", "stipple-snowflakes": "Stipples - snowflakes",
    "tsp": "TSP Art - continuous route",
}
VARIANTS = {
    "stipple-spirals": {"Stipple type": "Spirals"},
    "stipple-hexagons": {"Stipple type": "Hexagons"},
    "stipple-pentagrams": {"Stipple type": "Pentagrams"},
    "stipple-snowflakes": {"Stipple type": "Snowflakes"},
    "tsp": {"TSP Art": True},
}


def node_executable(explicit: str | None = None) -> str:
    candidate = explicit or os.environ.get("PLOTTERFUN_NODE") or shutil.which("node")
    if candidate and Path(candidate).is_file():
        return str(Path(candidate).resolve())
    raise RuntimeError("Node.js is required for local Plotterfun. Install Node.js or set PLOTTERFUN_NODE.")


def _profile(style: str, quality: str) -> dict[str, Any]:
    density = {"fast": 0.7, "normal": 1.0, "detailed": 1.4}[quality]
    profile: dict[str, Any] = {"Brightness": 0, "Contrast": 0}
    if style in {"squiggle", "squiggleLeftRight", "sawtooth", "subline", "springs", "woven"}:
        profile.update({"Line Count": min(190, round(145 * density)), "Amplitude": 2.0})
    if style in {"spiral", "spiral-page"}:
        profile.update({"Spacing": max(0.5, 0.5 / density), "Amplitude": 3.0,
                        "Frequency": 100, "Contrast": 10})
    if style == "polyspiral":
        profile.update({"Spacing": max(0.5, 1.0 / density), "Amplitude": 1.0})
    if style == "linedraw":
        profile.update({"Contour detail": 12, "Hatch scale": 4, "Noise scale": 0.1})
    if style == "mosaic":
        profile.update({"Scale": round(45 * density), "Hatches": 6})
    if style == "halftone":
        profile.update({"Divisions": round(65 * density), "Factor": 70, "Interlaced": True})
    if style == "boxes":
        profile.update({"Box Size": 5, "Box Spacing": max(5, round(7 / density))})
    if style == "dots":
        profile.update({"Resolution": 3})
    if style == "needles":
        profile.update({"Needles": min(10000, round(6500 * density)), "Max Length": 4, "Threshold": 28})
    if style == "implode":
        profile.update({"Rays": round(1800 * density), "Threshold": 75, "Step size": 2})
    if style in {"waves", "longwave", "linescan"}:
        profile.update({"Step size": max(1.0, 3.0 / density), "Spacing": max(1, round(3 / density))})
    if style == "longwave":
        profile.update({"Simplify": 3, "Wave Amplitude": 8, "Direction": "Horizontal"})
    if style == "margins":
        profile.update({"Squiggles": round(4500 * density), "Max Length": 7})
    if style == "peano":
        profile.update({"Order": 6 if quality == "detailed" else 5})
    if style in {"stipple", "delaunay", *VARIANTS}:
        profile.update({"Max Stipples": round(2500 * density), "Max Iterations": 24,
                        "Min dot size": 1.1, "Dot size range": 3.5})
        profile.update(VARIANTS.get(style, {}))
    return profile


def _clip(a, b, width: int, height: int):
    x, y = a
    dx, dy = b[0] - x, b[1] - y
    low, high = 0.0, 1.0
    for p, q in ((-dx, x), (dx, width - x), (-dy, y), (dy, height - y)):
        if abs(p) < 1e-15:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            low = max(low, t)
        else:
            high = min(high, t)
        if low > high:
            return None
    return (x + low * dx, y + low * dy), (x + high * dx, y + high * dy)


def generate_plotterfun(
    image_path: Path | str, style: str, *, work_area: WorkArea | None = None,
    quality: str = "normal", fit: str = "cover", margin_mm: float = 0.0,
    max_side_px: int | None = None, contrast: float = 1.0, gamma: float = 1.0,
    local_contrast_blend: float = 0.0,
    seed: int = 12345, controls: dict[str, Any] | None = None,
    node: str | None = None, timeout_seconds: float = 180,
) -> PhotoPlotResult:
    if style not in STYLES or quality not in {"fast", "normal", "detailed"}:
        raise ValueError("Unknown Plotterfun style or quality")
    if fit not in {"cover", "contain"} or not math.isfinite(margin_mm) or margin_mm < 0:
        raise ValueError("Invalid fit or margin")
    if not all(math.isfinite(v) and v > 0 for v in (contrast, gamma, timeout_seconds)):
        raise ValueError("Contrast, gamma and timeout must be positive finite numbers")
    if not math.isfinite(local_contrast_blend) or not 0 <= local_contrast_blend <= 1:
        raise ValueError("Local contrast blend must be in 0..1")
    area = work_area or WorkArea()
    width_mm = area.max_x - area.min_x - 2 * margin_mm
    height_mm = area.max_y - area.min_y - 2 * margin_mm
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("Margins leave no drawing area")
    with Image.open(image_path) as original:
        source = ImageOps.exif_transpose(original).convert("RGBA")
    white = Image.new("RGBA", source.size, "white")
    white.alpha_composite(source)
    source = white.convert("RGB")
    source_size = source.size
    crop = (0.0, 0.0, float(source.width), float(source.height))
    if fit == "cover":
        aspect = width_mm / height_mm
        if source.width / source.height > aspect:
            cw = source.height * aspect
            crop = ((source.width - cw) / 2, 0.0, (source.width + cw) / 2, float(source.height))
        else:
            ch = source.width / aspect
            crop = (0.0, (source.height - ch) / 2, float(source.width), (source.height + ch) / 2)
    else:
        scale = min(width_mm / source.width, height_mm / source.height)
        width_mm, height_mm = source.width * scale, source.height * scale
    max_side = int(max_side_px or {"fast": 640, "normal": 900, "detailed": 1200}[quality])
    if not 256 <= max_side <= 1600:
        raise ValueError("max_side_px must be in 256..1600")
    pixel_scale = max_side / max(width_mm, height_mm)
    width, height = max(16, round(width_mm * pixel_scale)), max(16, round(height_mm * pixel_scale))
    image = source.resize((width, height), Image.Resampling.LANCZOS, box=crop)
    # With neutral settings send original RGB, exactly as the website does.
    # Do not silently replace it with a brightened/locally equalized grayscale.
    rgba = image.convert("RGBA")
    if contrast != 1 or gamma != 1 or local_contrast_blend:
        gray = np.asarray(image.convert("L"), dtype=np.uint8)
        local = cv2.createCLAHE(clipLimit=1.4, tileGridSize=(8, 8)).apply(gray)
        base = gray.astype(np.float32) / 255.0
        tone = base * (1 - local_contrast_blend) + local.astype(np.float32) / 255.0 * local_contrast_blend
        tone = np.clip((tone - 0.5) * contrast + 0.5, 0, 1) ** gamma
        rgb = np.asarray(image, dtype=np.float32) / 255.0
        gain = (tone + 0.004) / (base + 0.004)
        rgba = Image.fromarray(np.rint(np.clip(rgb * gain[:, :, None], 0, 1) * 255).astype(np.uint8)).convert("RGBA")
    offset_x = offset_y = 0
    canvas_width, canvas_height = width, height
    if style == "spiral-page":
        # Let the UNCHANGED circular worker run on white overscan, then clip
        # to the central photo rectangle. Its spiral now reaches every A4
        # corner without stretching the photo or inventing linking strokes.
        side = int(math.ceil(math.hypot(width, height))) + 96
        offset_x, offset_y = (side - width) // 2, (side - height) // 2
        canvas = Image.new("RGBA", (side, side), "white")
        canvas.alpha_composite(rgba, (offset_x, offset_y))
        rgba = canvas
        canvas_width = canvas_height = side
    request = {
        "algorithm": "stipple" if style in VARIANTS else "spiral" if style == "spiral-page" else style,
        "width": canvas_width, "height": canvas_height,
        "rgba": base64.b64encode(rgba.tobytes()).decode("ascii"),
        "seed": int(seed), "profileControls": _profile(style, quality),
        "controls": controls or {}, "timeoutSeconds": timeout_seconds,
    }
    payload = None
    cache = None
    if request["algorithm"] == "stipple" and not controls:
        request["batchStipples"] = True
        fingerprint = {**request, "adapter_version": 3, "upstream": UPSTREAM_COMMIT}
        fingerprint["profileControls"] = {k: v for k, v in request["profileControls"].items()
                                           if k not in {"Stipple type", "TSP Art"}}
        key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        cache = ROOT / ".plotter_cache" / "plotterfun" / (key + ".json")
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
    if payload is None:
        process = subprocess.run(
            [node_executable(node), str(ROOT / "tools" / "plotterfun_runner.cjs")],
            input=json.dumps(request), text=True, encoding="utf-8", capture_output=True,
            timeout=timeout_seconds + 10, cwd=ROOT,
        )
        if process.returncode:
            raise RuntimeError(f"Plotterfun {style}: {process.stderr[-3000:]}")
        payload = json.loads(process.stdout)
        if cache is not None and payload.get("complete") is True:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload), encoding="utf-8")
    if payload.get("complete") is not True:
        raise RuntimeError("Refusing incomplete Plotterfun output")
    if payload.get("variants") and style in payload["variants"]:
        payload = {**payload, "paths": payload["variants"][style], "config": {
            **payload["config"], "Stipple type": "Circles", "TSP Art": False, **VARIANTS.get(style, {})}}
    x_left = (area.min_x + area.max_x - width_mm) / 2
    y_top = (area.min_y + area.max_y + height_mm) / 2
    sx, sy = width_mm / width, height_mm / height
    polylines = []
    discarded = 0
    for raw in payload["paths"]:
        active = []
        for a, b in zip(raw, raw[1:]):
            if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (*a, *b)):
                discarded += 1
                if len(active) > 1:
                    polylines.append(active)
                active = []
                continue
            a = (a[0] - offset_x, a[1] - offset_y)
            b = (b[0] - offset_x, b[1] - offset_y)
            clipped = _clip(a, b, width, height)
            if clipped is None:
                if len(active) > 1:
                    polylines.append(active)
                active = []
                continue
            p, q = [(x_left + p[0] * sx, y_top - p[1] * sy) for p in clipped]
            if math.dist(p, q) < 1e-7:
                continue
            if active and math.dist(active[-1], p) > 1e-5:
                if len(active) > 1:
                    polylines.append(active)
                active = []
            if not active:
                active = [p]
            active.append(q)
        if len(active) > 1:
            polylines.append(active)
    # A 0.025 mm geometric tolerance removes redundant samples, not tonal layers.
    simplified = []
    for poly in polylines:
        closed = len(poly) > 3 and math.dist(poly[0], poly[-1]) <= 1e-6
        points = [(float(x), float(y)) for x, y in cv2.approxPolyDP(
            np.asarray(poly, dtype=np.float32), 0.025, closed).reshape(-1, 2)] if len(poly) > 3 else poly
        # OpenCV represents a closed contour without repeating its first vertex.
        # The plotter needs that last segment explicitly; previews must not fake it.
        if closed and len(points) >= 3 and math.dist(points[0], points[-1]) > 1e-6:
            points.append(points[0])
        simplified.append(points)
    polylines = simplified
    polylines = [p for p in polylines if len(p) >= 2]
    length = sum(math.dist(a, b) for poly in polylines for a, b in zip(poly, poly[1:]))
    stats = {
        "polyline_count": len(polylines), "point_count": sum(map(len, polylines)),
        "draw_length_mm": round(length, 3), "bounds": list(polylines_bounds(polylines)),
        "engine": "plotterfun", "upstream_commit": UPSTREAM_COMMIT,
        "config": payload["config"], "quality": quality, "seed": seed,
        "fit": fit, "crop_box_source_px": crop, "margin_mm": margin_mm,
        "contrast": contrast, "gamma": gamma, "local_contrast_blend": local_contrast_blend,
        "worker_canvas_px": [canvas_width, canvas_height], "worker_overscan_offset_px": [offset_x, offset_y],
        "discarded_nonfinite_segments": discarded,
    }
    return PhotoPlotResult(
        mode=style, source_size_px=source_size, processed_size_px=(width, height),
        target_size_mm=(width_mm, height_mm),
        placement_bounds=(x_left, x_left + width_mm, y_top - height_mm, y_top),
        polylines=polylines, stats=stats,
    )
