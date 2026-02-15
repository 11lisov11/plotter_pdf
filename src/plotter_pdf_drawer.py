#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import argparse
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
from typing import Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
AXIS_PROFILE_PATH = CONFIG_DIR / "axis_profile.json"

DEFAULT_COM_PORT = "COM6"
DEFAULT_BAUD = "115200"
Z_UP = 0.0
Z_DOWN = 11.9
Z_DELAY = 0.03

# Pen lift mode for GRBL output: 'z' (G0 Z..), or 'spindle' (M3/M5) for pen servo/servo via spindle.
PEN_LIFT_MODE = "z"
PEN_SPINDLE_SPEED = 1000

FEED_TRAVEL = 10000.0
FEED_DRAW = 10000.0
SEGMENT_TOLERANCE_MM = 8.0
MAX_ARC_SEGMENT_MM = 12.0
CURVE_SEGMENT_MM = 2.5
POLYLINE_COLLINEAR_EPS = 0.40
FILL_HATCH_ENABLED = True
FILL_HATCH_SPACING_MM = 2.0
FILL_HATCH_ANGLE_DEG = 45.0
FILL_HATCH_MIN_AREA_MM2 = 55.0
FILL_HATCH_MIN_SIDE_MM = 3.0
FILL_HATCH_MIN_SEGMENT_MM = 0.5
AXIS_INVERT_X = False
AXIS_INVERT_Y = False
WORK_AREA_MIN_X = 0.0
WORK_AREA_MAX_X = 180.0
WORK_AREA_MIN_Y = -280.0
WORK_AREA_MAX_Y = 0.0
WORK_AREA_MARGIN = 5.0
WORK_AREA_FRAME_MARGIN = 3.0
WORK_OFFSET_X_MM = 0.0
WORK_OFFSET_Y_MM = 0.0
FIT_TO_WORK_AREA = True
ALLOW_UPSCALE_TO_WORK_AREA = True
WORK_AREA_EPS = 1e-6

INKSCAPE_CANDIDATES = [
    r"C:\Program Files\Inkscape\bin\inkscape.com",
    r"C:\Program Files (x86)\Inkscape\bin\inkscape.com",
    "inkscape.com",
    r"C:\Program Files\Inkscape\bin\inkscape.exe",
    r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe",
    "inkscape",
]
PDFTOCAIRO_CANDIDATES = [
    "pdftocairo",
]

CMD_END_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")
FLOAT_RE = re.compile(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
TRANSFORM_RE = re.compile(r"(\w+)\(([^)]*)\)")
TAG_RE = re.compile(r".*}\s*(.*)")
VIEWBOX_RE = re.compile(r"\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
LENGTH_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z%]*)\s*$")


@dataclass
class PathItem:
    points: List[Tuple[float, float]]
    closed: bool
    is_fill: bool
    is_stroke: bool
    source_id: int = -1


def load_axis_profile() -> None:
    defaults = {
        "axis": {
            "invert_x": False,
            "invert_y": False,
        },
        "meaning": {
            "x_positive": "right",
            "y_positive": "down",
            "notes": "Default plotter profile: X+ = right, Y+ = down.",
        },
    }

    global AXIS_INVERT_X, AXIS_INVERT_Y
    data = defaults
    if AXIS_PROFILE_PATH.exists():
        try:
            loaded = json.loads(AXIS_PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = {**defaults, **loaded}
                # merge nested maps explicitly
                if "axis" in loaded and isinstance(loaded["axis"], dict):
                    axis = data["axis"]
                    axis.update(loaded["axis"])
                    data["axis"] = axis
        except Exception:
            # Keep defaults for safety; no throw.
            data = defaults

    axis = data.get("axis", {})
    AXIS_INVERT_X = bool(axis.get("invert_x", False))
    AXIS_INVERT_Y = bool(axis.get("invert_y", False))


load_axis_profile()


def tag_name(tag: str) -> str:
    return TAG_RE.sub(r"\1", tag) if "}" in tag else tag


def parse_floats(text: str) -> List[float]:
    return [float(v) for v in FLOAT_RE.findall(text)]


def parse_length(value: str) -> Optional[Tuple[float, str]]:
    m = LENGTH_RE.match(value.strip())
    if not m:
        return None
    return float(m.group(1)), m.group(2).lower() if m.group(2) else "px"


def unit_to_mm(value: float, unit: str) -> float:
    if unit in {"px", ""}:
        return value * 25.4 / 96.0
    if unit == "mm":
        return value
    if unit == "cm":
        return value * 10.0
    if unit == "in":
        return value * 25.4
    if unit == "pt":
        return value * 25.4 / 72.0
    if unit == "pc":
        return value * 25.4 / 6.0
    return value


def run_cmd(cmd: List[str], cwd: Optional[Path] = None, timeout_s: Optional[float] = None) -> Tuple[int, str, str]:
    run_kwargs = {"shell": False}
    if sys.platform.startswith("win") and hasattr(subprocess, "CREATE_NO_WINDOW"):
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        **run_kwargs,
    )
    return result.returncode, result.stdout, result.stderr


def find_inkscape() -> str:
    for candidate in INKSCAPE_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return str(Path(found))
        if Path(candidate).is_file():
            return str(Path(candidate))
    raise RuntimeError("Inkscape not found. Install and add it to PATH.")


def find_pdftocairo() -> str:
    for candidate in PDFTOCAIRO_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return str(Path(found))
        if Path(candidate).is_file():
            return str(Path(candidate))
    raise RuntimeError("pdftocairo not found.")


def detect_com_port(preferred: str = DEFAULT_COM_PORT) -> str:
    try:
        import serial.tools.list_ports
    except Exception:
        return preferred

    candidates = [preferred.upper(), "COM6", "COM5", "COM4", "COM3", "COM7", "COM8", "COM9", "COM10"]
    available = {p.device.upper(): p.device for p in serial.tools.list_ports.comports()}
    for candidate in candidates:
        if candidate in available:
            return available[candidate]
    if available:
        return next(iter(available.values()))
    return preferred


def get_inkscape_version(exe: str) -> Tuple[int, int, int]:
    rc, out, err = run_cmd([exe, "--version"], timeout_s=10.0)
    text = (out + "\n" + err).strip()
    m = re.search(r"Inkscape\s*v?(\d+)\.(\d+)(?:\.(\d+))?", text, re.IGNORECASE)
    if not m:
        return 1, 0, 0
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3) or 0)
    return major, minor, patch

def mat_mul(m1: Tuple[float, float, float, float, float, float], m2: Tuple[float, float, float, float, float, float]):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def mat_apply(m: Tuple[float, float, float, float, float, float], p: Tuple[float, float]) -> Tuple[float, float]:
    x, y = p
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def parse_transform(value: str) -> Tuple[float, float, float, float, float, float]:
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, raw in TRANSFORM_RE.findall(value):
        params = parse_floats(raw)
        if not params:
            continue
        if name == "matrix" and len(params) == 6:
            op = tuple(params)
        elif name == "translate":
            tx = params[0]
            ty = params[1] if len(params) > 1 else 0.0
            op = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale":
            sx = params[0]
            sy = params[1] if len(params) > 1 else params[0]
            op = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate":
            angle = math.radians(params[0])
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            if len(params) >= 3:
                cx, cy = params[1], params[2]
                op = (
                    cos_a, sin_a, -sin_a, cos_a,
                    cx - cos_a * cx + sin_a * cy,
                    cy - sin_a * cx - cos_a * cy,
                )
            else:
                op = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
        elif name == "skewX":
            a = math.radians(params[0])
            op = (1.0, 0.0, math.tan(a), 1.0, 0.0, 0.0)
        elif name == "skewY":
            a = math.radians(params[0])
            op = (1.0, math.tan(a), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        matrix = mat_mul(matrix, op)
    return matrix


def infer_scale(root: ET.Element) -> float:
    viewbox = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    width = root.attrib.get("width", "100")
    height = root.attrib.get("height", "100")

    if not viewbox:
        return 1.0
    vb = VIEWBOX_RE.match(viewbox.strip())
    if not vb:
        return 1.0
    vb_w = float(vb.group(3))
    vb_h = float(vb.group(4))

    w_info = parse_length(width)
    h_info = parse_length(height)
    if w_info and h_info and vb_w and vb_h:
        w_mm = unit_to_mm(w_info[0], w_info[1])
        h_mm = unit_to_mm(h_info[0], h_info[1])
        sx = w_mm / vb_w
        sy = h_mm / vb_h
        return (sx + sy) * 0.5
    return 1.0


def parse_path_tokens(path_d: str) -> Iterable[Tuple[str, List[float]]]:
    tokens = [t for t in re.split(r"([MmLlHhVvCcSsQqTtAaZz])", path_d) if t and not t.isspace()]
    if not tokens:
        return
    cmd: Optional[str] = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if CMD_END_RE.fullmatch(token):
            cmd = token
            i += 1
            if cmd in "Zz":
                yield cmd, []
            continue
        if cmd is None:
            raise ValueError("Path starts with coordinates")
        params: List[float] = []
        while i < len(tokens) and not CMD_END_RE.fullmatch(tokens[i]):
            params.extend(parse_floats(tokens[i]))
            i += 1
        yield cmd, params


def cubic_approx(p0, p1, p2, p3, step=CURVE_SEGMENT_MM) -> List[Tuple[float, float]]:
    def bezier_point(a, b, c, d, t):
        mt = 1.0 - t
        return (
            mt * mt * mt * a[0] + 3 * mt * mt * t * b[0] + 3 * mt * t * t * c[0] + t * t * t * d[0],
            mt * mt * mt * a[1] + 3 * mt * mt * t * b[1] + 3 * mt * t * t * c[1] + t * t * t * d[1],
        )

    length = max(
        math.hypot(p3[0] - p0[0], p3[1] - p0[1]),
        0.0001,
    )
    n = max(2, int(math.ceil(length / step)) + 1)
    return [bezier_point(p0, p1, p2, p3, i / n) for i in range(1, n + 1)]


def quadratic_approx(p0, p1, p2, step=CURVE_SEGMENT_MM) -> List[Tuple[float, float]]:
    def bezier_point(a, b, c, t):
        mt = 1.0 - t
        return (
            mt * mt * a[0] + 2 * mt * t * b[0] + t * t * c[0],
            mt * mt * a[1] + 2 * mt * t * b[1] + t * t * c[1],
        )

    length = max(
        math.hypot(p2[0] - p0[0], p2[1] - p0[1]),
        0.0001,
    )
    n = max(2, int(math.ceil(length / step)) + 1)
    return [bezier_point(p0, p1, p2, i / n) for i in range(1, n + 1)]


def arc_to_polyline(p0, rx, ry, angle_deg, large_arc, sweep, p1, step=0.35) -> List[Tuple[float, float]]:
    x1, y1 = p0
    x2, y2 = p1
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(angle_deg % 360)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    rx = abs(rx)
    ry = abs(ry)
    if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
        # SVG arc with identical start/end is treated as a full ellipse.
        steps = max(12, int((2 * math.pi * max(rx, ry)) / max(step, 0.1)))
        pts = []
        for i in range(1, steps + 1):
            t = 2 * math.pi * i / steps
            x = (x1 - rx * math.cos(phi)) + rx * math.cos(t) * math.cos(phi) - ry * math.sin(t) * math.sin(phi)
            y = (y1 - rx * math.sin(phi)) + rx * math.cos(t) * math.sin(phi) + ry * math.sin(t) * math.cos(phi)
            pts.append((x, y))
        return pts

    dx2 = (x1 - x2) / 2.0
    dy2 = (y1 - y2) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    sign = -1.0 if bool(large_arc) == bool(sweep) else 1.0
    sq = max(0.0, (rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p) / (rx * rx * y1p * y1p + ry * ry * x1p * x1p))
    cpx = sign * math.sqrt(sq) * (rx * y1p / ry)
    cpy = sign * math.sqrt(sq) * (-ry * x1p / rx)

    cx = cos_phi * cpx - sin_phi * cpy + (x1 + x2) / 2.0
    cy = sin_phi * cpx + cos_phi * cpy + (y1 + y2) / 2.0

    v1x = (x1p - cpx) / rx
    v1y = (y1p - cpy) / ry
    v2x = (-x1p - cpx) / rx
    v2y = (-y1p - cpy) / ry
    theta1 = math.atan2(v1y, v1x)
    delta = math.atan2(v1x * v2y - v1y * v2x, v1x * v2x + v1y * v2y)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    if sweep and delta < 0:
        delta += 2 * math.pi

    arc_len = abs(delta) * max(rx, ry)
    n = max(1, int(math.ceil(arc_len / max(step, 0.1))))
    n = max(n, 1)
    pts = []
    for i in range(1, n + 1):
        t = theta1 + delta * (i / n)
        x = cx + rx * math.cos(t) * cos_phi - ry * math.sin(t) * sin_phi
        y = cy + rx * math.cos(t) * sin_phi + ry * math.sin(t) * cos_phi
        pts.append((x, y))
    return pts


def apply_style_filter(style: Optional[str], tag: str) -> bool:
    if not style:
        return True
    if tag == "path":
        data = {k.strip().lower(): v.strip().lower() for k, _, v in (part.partition(":") for part in style.split(";")) if k.strip()}
        stroke = data.get("stroke", "none").lower()
        fill = data.get("fill", "none").lower()
        if stroke == "none" and fill == "none":
            return False
    return True


def read_style_dict(style: Optional[str]) -> dict:
    if not style:
        return {}
    return {k.strip().lower(): v.strip().lower() for k, _, v in (part.partition(":") for part in style.split(";")) if k.strip()}


def parse_color_to_rgb_like(value: str) -> Optional[Tuple[float, float, float, float]]:
    if not value:
        return None
    v = value.strip().lower()
    if v in {"none", "transparent"}:
        return None
    if v in {"white", "#fff", "#ffffff"}:
        return 1.0, 1.0, 1.0, 1.0
    if v.startswith("#") and len(v) == 7:
        try:
            r = int(v[1:3], 16) / 255.0
            g = int(v[3:5], 16) / 255.0
            b = int(v[5:7], 16) / 255.0
            return r, g, b, 1.0
        except Exception:
            return None
    if v.startswith("rgb"):
        m = re.match(r"rgba?\(([^)]+)\)", v)
        if not m:
            return None
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) < 3:
            return None
        try:
            is_pct = "%" in parts[0] or "%" in parts[1] or "%" in parts[2]
            nums = [float(p.rstrip("%")) for p in parts[:3]]
            if is_pct:
                return (nums[0] / 100.0, nums[1] / 100.0, nums[2] / 100.0, 1.0)
            return (nums[0] / 255.0, nums[1] / 255.0, nums[2] / 255.0, 1.0)
        except Exception:
            return None
    return None


def style_value(style: dict, element: ET.Element, key: str) -> str:
    value = style.get(key)
    if value is not None:
        return value.strip().lower()
    return element.attrib.get(key, "").strip().lower()


def is_none_style(value: Optional[str]) -> bool:
    return value in (None, "", "none", "transparent")


def parse_style_flags(style: dict, element: ET.Element, tag: str) -> Tuple[bool, bool]:
    # Returns tuple (has_stroke, has_fill)
    has_stroke = False
    has_fill = False
    if tag == "line":
        stroke = style_value(style, element, "stroke")
        has_stroke = not is_none_style(stroke)
        fill_val = style_value(style, element, "fill")
        has_fill = not is_none_style(fill_val) and fill_val not in {"", "none"}
        if is_none_style(stroke) and is_none_style(fill_val):
            has_stroke = True
        return has_stroke, has_fill

    stroke = style_value(style, element, "stroke")
    fill = style_value(style, element, "fill")

    if tag in {"rect", "polygon", "polyline", "circle", "ellipse", "path"}:
        if is_none_style(stroke):
            has_stroke = False
        else:
            has_stroke = True

        if fill == "" and tag == "path":
            # Inkscape/path defaults often imply fill unless explicitly set; this helps text outlines after convert.
            has_fill = True
        else:
            has_fill = not is_none_style(fill)

    else:
        has_stroke = not is_none_style(stroke)
        has_fill = not is_none_style(fill)

    # Explicitly ensure a drawable path.
    if not has_stroke and not has_fill and tag in {"line", "polyline", "polygon", "rect", "circle", "ellipse", "path"}:
        has_stroke = True
    return has_stroke, has_fill


def is_nearly_white_fill(elem: ET.Element) -> bool:
    style = read_style_dict(elem.attrib.get("style"))
    fill = style.get("fill", elem.attrib.get("fill", "")).strip().lower()
    if not fill:
        return False
    rgb = parse_color_to_rgb_like(fill)
    if rgb is None:
        return False
    r, g, b, _ = rgb
    if min(r, g, b) < 0.99:
        return False
    opacity = style.get("fill-opacity", elem.attrib.get("fill-opacity", "1")).strip()
    try:
        if float(opacity) < 0.2:
            return False
    except Exception:
        pass
    return True


def is_axis_aligned_rectangle(poly: List[Tuple[float, float]]) -> bool:
    if len(poly) != 5 or poly[0] != poly[-1]:
        return False
    pts = poly[:-1]
    if len({pt for pt in pts}) != 4:
        return False
    xs = {round(p[0], 5) for p in pts}
    ys = {round(p[1], 5) for p in pts}
    if len(xs) != 2 or len(ys) != 2:
        return False
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        if abs(x1 - x2) > 1e-6 and abs(y1 - y2) > 1e-6:
            return False
    return True


def root_page_size_mm(root: ET.Element) -> Tuple[float, float]:
    vb = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if vb:
        m = VIEWBOX_RE.match(vb.strip())
        if m:
            return float(m.group(3)), float(m.group(4))
    width = parse_length(root.attrib.get("width", "0"))
    height = parse_length(root.attrib.get("height", "0"))
    if width and height:
        return unit_to_mm(width[0], width[1]), unit_to_mm(height[0], height[1])
    return 0.0, 0.0


def is_full_page_white_fill_rect(poly: List[Tuple[float, float]], elem: ET.Element, page_w: float, page_h: float) -> bool:
    if not is_axis_aligned_rectangle(poly):
        return False
    if tag_name(elem.tag) != "path":
        return False
    if not is_nearly_white_fill(elem):
        return False
    style = read_style_dict(elem.attrib.get("style"))
    stroke = (style.get("stroke") or elem.attrib.get("stroke") or "").strip().lower()
    if stroke not in {"", "none"}:
        return False
    if abs(page_w) < 1e-6 or abs(page_h) < 1e-6:
        return False
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    area_ratio = ((max(xs) - min(xs)) * (max(ys) - min(ys))) / (page_w * page_h)
    return 0.95 <= area_ratio <= 1.05


def point_line_distance(point: Tuple[float, float], line_a: Tuple[float, float], line_b: Tuple[float, float]) -> float:
    x, y = point
    x1, y1 = line_a
    x2, y2 = line_b
    vx = x2 - x1
    vy = y2 - y1
    wx = x - x1
    wy = y - y1
    vv = vx * vx + vy * vy
    if vv < 1e-12:
        return points_distance(point, line_a)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    px = x1 + t * vx
    py = y1 + t * vy
    return points_distance(point, (px, py))


def path_is_closed(poly: List[Tuple[float, float]], eps: float = 1e-6) -> bool:
    return len(poly) >= 4 and points_distance(poly[0], poly[-1]) <= eps


def polygon_area(poly: List[Tuple[float, float]]) -> float:
    if len(poly) < 3:
        return 0.0
    area = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def polygon_bbox(poly: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), max(xs), min(ys), max(ys)


def rotate_point(point: Tuple[float, float], angle_rad: float) -> Tuple[float, float]:
    x, y = point
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (
        x * cos_a + y * sin_a,
        -x * sin_a + y * cos_a,
    )


def rotate_polyline(poly: List[Tuple[float, float]], angle_rad: float) -> List[Tuple[float, float]]:
    if angle_rad == 0.0:
        return list(poly)
    return [rotate_point(p, angle_rad) for p in poly]


def intersects_for_scanline(edges: List[Tuple[Tuple[float, float], Tuple[float, float]]], y: float) -> List[float]:
    xs: List[float] = []
    for p1, p2 in edges:
        x1, y1 = p1
        x2, y2 = p2
        if y1 == y2:
            continue
        if y1 <= y < y2 or y2 <= y < y1:
            t = (y - y1) / (y2 - y1)
            xs.append(x1 + t * (x2 - x1))
    return sorted(xs)


def should_hatch_polygon(poly: List[Tuple[float, float]], closed: bool) -> bool:
    if not closed or len(poly) < 4:
        return False
    if not FILL_HATCH_ENABLED:
        return False

    # Work with unique endpoints.
    ring = poly[:-1] if path_is_closed(poly) else list(poly)
    if len(ring) < 4:
        return False

    area = abs(polygon_area(ring))
    if area < FILL_HATCH_MIN_AREA_MM2:
        return False
    min_x, max_x, min_y, max_y = polygon_bbox(ring)
    if (max_x - min_x) < FILL_HATCH_MIN_SIDE_MM or (max_y - min_y) < FILL_HATCH_MIN_SIDE_MM:
        return False
    return True


def hatch_polygon(
    contours: List[List[Tuple[float, float]]],
    spacing: float = FILL_HATCH_SPACING_MM,
    angle_deg: float = FILL_HATCH_ANGLE_DEG,
    min_segment: float = FILL_HATCH_MIN_SEGMENT_MM,
) -> List[List[Tuple[float, float]]]:
    if spacing <= 0:
        return []
    angle_rad = math.radians(angle_deg)

    valid_contours = [c[:-1] if path_is_closed(c) else c for c in contours if len(c) >= 3]
    if not valid_contours:
        return []

    rotated = [rotate_polyline(c, angle_rad) for c in valid_contours]
    edges: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for poly in rotated:
        if len(poly) < 2:
            continue
        for i in range(len(poly)):
            p1 = poly[i]
            p2 = poly[(i + 1) % len(poly)]
            if p1 == p2:
                continue
            edges.append((p1, p2))

    if not edges:
        return []

    min_x = min(p[0] for e in edges for p in e)
    max_x = max(p[0] for e in edges for p in e)
    min_y = min(p[1] for e in edges for p in e)
    max_y = max(p[1] for e in edges for p in e)
    if not math.isfinite(min_x + max_x + min_y + max_y):
        return []

    out: List[List[Tuple[float, float]]] = []
    # Keep a tiny margin to reduce duplicates from boundary coincidences.
    scan_y = min_y + 1e-6
    while scan_y <= max_y - 1e-6:
        xs = intersects_for_scanline(edges, scan_y)
        if len(xs) % 2 == 1:
            xs = xs[:-1]
        for i in range(0, len(xs), 2):
            if i + 1 >= len(xs):
                break
            x1, x2 = xs[i], xs[i + 1]
            if (x2 - x1) < min_segment:
                continue
            p1 = rotate_point((x1, scan_y), -angle_rad)
            p2 = rotate_point((x2, scan_y), -angle_rad)
            if points_distance(p1, p2) >= min_segment:
                out.append([p1, p2])
        scan_y += spacing
    return out


def simplify_polyline(poly: List[Tuple[float, float]], eps: float = 1e-6) -> List[Tuple[float, float]]:
    if not poly:
        return []
    out: List[Tuple[float, float]] = [poly[0]]
    for p in poly[1:]:
        if points_distance(out[-1], p) > eps:
            out.append(p)

    # Reduce collinear noise from text/vector import and tiny font artifacts.
    if len(out) < 3:
        return out
    col = [out[0]]
    for p in out[1:]:
        if len(col) >= 2:
            last = col[-1]
            prev = col[-2]
            if point_line_distance(last, prev, p) <= POLYLINE_COLLINEAR_EPS:
                col[-1] = p
                continue
        col.append(p)

    # Ensure path tail still ends in same direction; cleanup duplicate points after collinear pass.
    if len(col) < 2:
        return col
    cleaned = [col[0]]
    for p in col[1:]:
        if points_distance(cleaned[-1], p) > eps:
            cleaned.append(p)
    return cleaned


def parse_points(points_text: str) -> List[Tuple[float, float]]:
    nums = parse_floats(points_text)
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def transform_points(points: List[Tuple[float, float]], matrix: Tuple[float, float, float, float, float, float], scale: float) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for x, y in points:
        tx, ty = mat_apply(matrix, (x, y))
        out.append((tx * scale, ty * scale))
    return out


def bounds_polylines(polylines: List[List[Tuple[float, float]]]) -> Tuple[float, float, float, float]:
    min_x = min((p[0] for poly in polylines for p in poly), default=0.0)
    max_x = max((p[0] for poly in polylines for p in poly), default=0.0)
    min_y = min((p[1] for poly in polylines for p in poly), default=0.0)
    max_y = max((p[1] for poly in polylines for p in poly), default=0.0)
    return min_x, max_x, min_y, max_y


def work_area_bounds() -> Tuple[float, float, float, float]:
    min_x = min(WORK_AREA_MIN_X + WORK_OFFSET_X_MM, WORK_AREA_MAX_X + WORK_OFFSET_X_MM)
    max_x = max(WORK_AREA_MIN_X + WORK_OFFSET_X_MM, WORK_AREA_MAX_X + WORK_OFFSET_X_MM)
    min_y = min(WORK_AREA_MIN_Y + WORK_OFFSET_Y_MM, WORK_AREA_MAX_Y + WORK_OFFSET_Y_MM)
    max_y = max(WORK_AREA_MIN_Y + WORK_OFFSET_Y_MM, WORK_AREA_MAX_Y + WORK_OFFSET_Y_MM)
    return min_x, max_x, min_y, max_y


def clamp_to_work_area(
    x: float,
    y: float,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> Tuple[float, float]:
    return (
        min(max(x, min_x), max_x),
        min(max(y, min_y), max_y),
    )


def point_in_work_area(x: float, y: float, min_x: float, max_x: float, min_y: float, max_y: float, eps: float = WORK_AREA_EPS) -> bool:
    return (min_x - eps) <= x <= (max_x + eps) and (min_y - eps) <= y <= (max_y + eps)


def clip_segment_to_rect(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    dx = x2 - x1
    dy = y2 - y1
    t0 = 0.0
    t1 = 1.0

    def upd(p: float, q: float, current_t0: float, current_t1: float) -> Optional[Tuple[float, float]]:
        if abs(p) < 1e-15:
            if q < 0.0:
                return None
            return current_t0, current_t1
        t = q / p
        if p < 0.0:
            if t > current_t1:
                return None
            return max(current_t0, t), current_t1
        if p > 0.0:
            if t < current_t0:
                return None
            return current_t0, min(current_t1, t)
        return current_t0, current_t1

    # Left
    r = upd(-(dx), x1 - min_x, t0, t1)
    if r is None:
        return None
    t0, t1 = r

    # Right
    r = upd(dx, max_x - x1, t0, t1)
    if r is None:
        return None
    t0, t1 = r

    # Bottom
    r = upd(-(dy), y1 - min_y, t0, t1)
    if r is None:
        return None
    t0, t1 = r

    # Top
    r = upd(dy, max_y - y1, t0, t1)
    if r is None:
        return None
    t0, t1 = r

    if t0 > t1:
        return None

    x_start = x1 + dx * t0
    y_start = y1 + dy * t0
    x_end = x1 + dx * t1
    y_end = y1 + dy * t1
    return (x_start, y_start), (x_end, y_end)


def clip_polylines_to_work_area(
    polylines: List[List[Tuple[float, float]]],
    logger=print,
) -> List[List[Tuple[float, float]]]:
    min_x, max_x, min_y, max_y = work_area_bounds()
    clipped_all: List[List[Tuple[float, float]]] = []
    dropped_segments = 0
    written_segments = 0

    for poly in polylines:
        if len(poly) < 2:
            continue
        out_poly: List[Tuple[float, float]] = []
        for i in range(1, len(poly)):
            x1, y1 = poly[i - 1]
            x2, y2 = poly[i]
            clipped = clip_segment_to_rect(x1, y1, x2, y2, min_x, max_x, min_y, max_y)
            if clipped is None:
                dropped_segments += 1
                if out_poly:
                    if len(out_poly) >= 2:
                        clipped_all.append(out_poly)
                    out_poly = []
                continue

            (cx1, cy1), (cx2, cy2) = clipped
            cx1, cy1 = clamp_to_work_area(cx1, cy1, min_x, max_x, min_y, max_y)
            cx2, cy2 = clamp_to_work_area(cx2, cy2, min_x, max_x, min_y, max_y)
            # Close and restart if next visible piece doesn't touch current one.
            if not point_in_work_area(cx1, cy1, min_x, max_x, min_y, max_y):
                dropped_segments += 1
                if out_poly and len(out_poly) >= 2:
                    clipped_all.append(out_poly)
                out_poly = []
                continue

            if not out_poly:
                out_poly = [(cx1, cy1)]

            if points_distance((cx1, cy1), out_poly[-1]) > 1e-6:
                clipped_all.append(out_poly)
                out_poly = [(cx1, cy1)]

            if points_distance((cx2, cy2), out_poly[-1]) > 1e-6:
                out_poly.append((cx2, cy2))
                written_segments += 1

        if len(out_poly) >= 2:
            clipped_all.append(out_poly)

    if logger:
        if dropped_segments:
            logger(f"Work area clipping: kept {written_segments} visible segments, dropped {dropped_segments} out-of-area segments.")
    return clipped_all


def fit_polylines_to_area(
    polylines: List[List[Tuple[float, float]]],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    logger=print,
) -> List[List[Tuple[float, float]]]:
    if not polylines or not FIT_TO_WORK_AREA:
        return polylines

    w = max_x - min_x
    h = max_y - min_y
    if w <= 0.0 or h <= 0.0:
        return polylines

    area_w = max(1.0, WORK_AREA_MAX_X - WORK_AREA_MIN_X)
    area_h = max(1.0, WORK_AREA_MAX_Y - WORK_AREA_MIN_Y)
    usable_w = max(1.0, area_w - 2 * WORK_AREA_MARGIN)
    usable_h = max(1.0, area_h - 2 * WORK_AREA_MARGIN)

    raw_scale = min(usable_w / w, usable_h / h)
    scale = raw_scale if ALLOW_UPSCALE_TO_WORK_AREA else min(1.0, raw_scale)
    scaled_w = w * scale
    scaled_h = h * scale

    tx = WORK_AREA_MIN_X + WORK_AREA_MARGIN + (usable_w - scaled_w) / 2.0 - min_x * scale
    ty = WORK_AREA_MIN_Y + WORK_AREA_MARGIN + (usable_h - scaled_h) / 2.0 - min_y * scale

    if scale < 0.999999 or abs(tx) > 1e-9 or abs(ty) > 1e-9:
        if logger:
            logger(
                f"Fit to work area: scale={scale:.4f}, translate=({tx:.3f},{ty:.3f}), "
                f"from ({min_x:.3f}, {min_y:.3f})-({max_x:.3f}, {max_y:.3f})"
            )

    out: List[List[Tuple[float, float]]] = []
    for poly in polylines:
        out.append([((x * scale) + tx, (y * scale) + ty) for x, y in poly])
    return out


def get_path_polylines(
    element: ET.Element,
    matrix: Tuple[float, float, float, float, float, float],
    scale: float,
    source_id: int = -1,
) -> List[PathItem]:
    tag = tag_name(element.tag)
    result: List[PathItem] = []
    style = read_style_dict(element.attrib.get("style"))
    has_stroke, has_fill = parse_style_flags(style, element, tag)
    if not has_stroke and not has_fill:
        return result
    if not apply_style_filter(element.attrib.get("style"), tag):
        return result

    cur_matrix = matrix

    def add_item(points: List[Tuple[float, float]]):
        if len(points) < 2:
            return
        result.append(
            PathItem(
                points=transform_points(points, cur_matrix, scale),
                closed=path_is_closed(points),
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        )

    if tag == "path":
        d = element.attrib.get("d", "")
        if not d:
            return result
        x = y = 0.0
        sx = sy = 0.0
        polyline: List[Tuple[float, float]] = []
        last_cubic = None
        last_quadratic = None
        last_cmd = ""

        for cmd, params in parse_path_tokens(d):
            prev_cmd = last_cmd
            if not params and cmd.lower() == "z":
                if polyline:
                    polyline.append((sx, sy))
                    add_item(polyline)
                    polyline = []
                last_cubic = None
                last_quadratic = None
                x, y = sx, sy
                last_cmd = cmd
                continue

            if cmd in "mM":
                if len(params) < 2:
                    continue
                xi = 0
                first = True
                while xi + 1 < len(params):
                    nx = params[xi]
                    ny = params[xi + 1]
                    if cmd == "m":
                        x += nx
                        y += ny
                    else:
                        x = nx
                        y = ny
                    if first:
                        if polyline:
                            add_item(polyline)
                        polyline = [(x, y)]
                        sx, sy = x, y
                        first = False
                    else:
                        polyline.append((x, y))
                    xi += 2
                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue
            if cmd in "zZ":
                if polyline:
                    polyline.append((sx, sy))
                    add_item(polyline)
                    polyline = []
                x, y = sx, sy
                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "lL":
                for i in range(0, len(params), 2):
                    nx, ny = params[i], params[i + 1]
                    if cmd == "l":
                        x += nx
                        y += ny
                    else:
                        x = nx
                        y = ny
                    polyline.append((x, y))
                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "hH":
                for nx in params:
                    if cmd == "h":
                        x += nx
                    else:
                        x = nx
                    polyline.append((x, y))
                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "vV":
                for ny in params:
                    if cmd == "v":
                        y += ny
                    else:
                        y = ny
                    polyline.append((x, y))
                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "cC":
                for i in range(0, len(params), 6):
                    p1 = (params[i], params[i + 1])
                    p2 = (params[i + 2], params[i + 3])
                    p3 = (params[i + 4], params[i + 5])
                    if cmd == "c":
                        p1 = (x + p1[0], y + p1[1])
                        p2 = (x + p2[0], y + p2[1])
                        p3 = (x + p3[0], y + p3[1])
                    pts = cubic_approx((x, y), p1, p2, p3, CURVE_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = p3
                    last_cubic = p2
                    last_quadratic = None
                    last_cmd = cmd
                continue

            if cmd in "sS":
                for i in range(0, len(params), 4):
                    p1 = (params[i], params[i + 1])
                    p2 = (params[i + 2], params[i + 3])
                    if prev_cmd.lower() in "cs":
                        x1, y1 = x, y
                        x2, y2 = last_cubic if last_cubic is not None else (x, y)
                        p0 = (2 * x1 - x2, 2 * y1 - y2)
                    else:
                        p0 = (x, y)
                    if cmd == "s":
                        p1 = (x + p1[0], y + p1[1])
                        p2 = (x + p2[0], y + p2[1])
                    else:
                        p2 = (p2[0], p2[1])
                    pts = cubic_approx((x, y), p0, p1, p2, CURVE_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = p2
                    last_cubic = p1
                    last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "qQ":
                for i in range(0, len(params), 4):
                    p1 = (params[i], params[i + 1])
                    p2 = (params[i + 2], params[i + 3])
                    if cmd == "q":
                        p1 = (x + p1[0], y + p1[1])
                        p2 = (x + p2[0], y + p2[1])
                    pts = quadratic_approx((x, y), p1, p2, CURVE_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = p2
                    last_quadratic = p1
                    last_cubic = None
                last_cmd = cmd
                continue

            if cmd in "tT":
                for i in range(0, len(params), 2):
                    p2 = (params[i], params[i + 1])
                    if prev_cmd.lower() in "qt":
                        q1 = last_quadratic if last_quadratic is not None else (x, y)
                        p1 = (2 * x - q1[0], 2 * y - q1[1])
                    else:
                        p1 = (x, y)
                    if cmd == "t":
                        p2 = (x + p2[0], y + p2[1])
                    pts = quadratic_approx((x, y), p1, p2, CURVE_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = p2
                    last_quadratic = p1
                    last_cubic = None
                last_cmd = cmd
                continue

            if cmd in "aA":
                for i in range(0, len(params), 7):
                    rx, ry, rot, laf, sf, nx, ny = params[i : i + 7]
                    ex, ey = nx, ny
                    if cmd == "a":
                        ex += x
                        ey += y
                    pts = arc_to_polyline((x, y), rx, ry, rot, int(laf), int(sf), (ex, ey), MAX_ARC_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = ex, ey
                    last_cubic = None
                    last_quadratic = None
                last_cmd = cmd
                continue

            last_cmd = cmd
        if polyline:
            add_item(polyline)
        return result

    if tag == "line":
        x1 = float(element.attrib.get("x1", "0"))
        y1 = float(element.attrib.get("y1", "0"))
        x2 = float(element.attrib.get("x2", "0"))
        y2 = float(element.attrib.get("y2", "0"))
        return [
            PathItem(
                points=transform_points([(x1, y1), (x2, y2)], cur_matrix, scale),
                closed=False,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    if tag == "polyline":
        pts = parse_points(element.attrib.get("points", ""))
        if not pts:
            return []
        return [
            PathItem(
                points=transform_points(pts, cur_matrix, scale),
                closed=False,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    if tag == "polygon":
        pts = parse_points(element.attrib.get("points", ""))
        if pts:
            pts = pts + [pts[0]]
            return [
                PathItem(
                    points=transform_points(pts, cur_matrix, scale),
                    closed=True,
                    is_fill=has_fill,
                    is_stroke=has_stroke,
                    source_id=source_id,
                )
            ]
        return []

    if tag == "rect":
        x = float(element.attrib.get("x", "0"))
        y = float(element.attrib.get("y", "0"))
        w = float(element.attrib.get("width", "0"))
        h = float(element.attrib.get("height", "0"))
        if w == 0 or h == 0:
            return []
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
        return [
            PathItem(
                points=transform_points(pts, cur_matrix, scale),
                closed=True,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    if tag == "circle":
        cx = float(element.attrib.get("cx", "0"))
        cy = float(element.attrib.get("cy", "0"))
        r = float(element.attrib.get("r", "0"))
        if r <= 0:
            return []
        steps = max(12, int((2 * math.pi * r) / max(MAX_ARC_SEGMENT_MM, 0.1)))
        pts = []
        for i in range(steps + 1):
            a = 2 * math.pi * i / steps
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return [
            PathItem(
                points=transform_points(pts, cur_matrix, scale),
                closed=True,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    if tag == "ellipse":
        cx = float(element.attrib.get("cx", "0"))
        cy = float(element.attrib.get("cy", "0"))
        rx = float(element.attrib.get("rx", "0"))
        ry = float(element.attrib.get("ry", "0"))
        if rx <= 0 or ry <= 0:
            return []
        r = max(rx, ry)
        steps = max(12, int((2 * math.pi * r) / max(MAX_ARC_SEGMENT_MM, 0.1)))
        pts = []
        for i in range(steps + 1):
            a = 2 * math.pi * i / steps
            pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        return [
            PathItem(
                points=transform_points(pts, cur_matrix, scale),
                closed=True,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    return result


def extract_polylines(svg_path: Path) -> List[PathItem]:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    scale = infer_scale(root)
    page_w_mm, page_h_mm = root_page_size_mm(root)
    out: List[PathItem] = []
    source_seq = 0

    SKIP_CONTAINER_TAGS = {
        "defs",
        "clipPath",
        "mask",
        "pattern",
        "symbol",
        "marker",
    }

    def walk(
        node: ET.Element,
        matrix=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    ):
        tag = tag_name(node.tag)
        if tag in SKIP_CONTAINER_TAGS:
            return

        local_transform = parse_transform(node.attrib.get("transform", ""))
        cur_matrix = mat_mul(matrix, local_transform)

        if node.attrib.get("display", "").strip().lower() == "none":
            return
        if node.attrib.get("visibility", "").strip().lower() in {"hidden", "collapse"}:
            return

        nonlocal source_seq
        source_id = source_seq
        source_seq += 1
        new_polys = get_path_polylines(node, cur_matrix, scale, source_id=source_id)
        if node.tag and tag_name(node.tag) == "path":
            for poly in new_polys:
                if is_full_page_white_fill_rect(poly.points, node, page_w_mm * scale, page_h_mm * scale):
                    continue
                out.append(poly)
        else:
            out.extend(new_polys)
        for child in list(node):
            walk(child, cur_matrix)

    walk(root)

    normalized: List[PathItem] = []
    for item in out:
        poly = item.points
        if len(poly) < 2:
            continue
        cleaned: List[Tuple[float, float]] = []
        for p in poly:
            x, y = p
            if AXIS_INVERT_X:
                x = -x
            if AXIS_INVERT_Y:
                y = -y
            cleaned.append((x, y))
        cleaned = simplify_polyline(cleaned)
        if len(cleaned) < 2:
            continue
        item.points = cleaned
        item.closed = path_is_closed(cleaned)
        normalized.append(item)

    deduped: List[PathItem] = []
    seen = set()
    for item in normalized:
        poly = item.points
        if not poly:
            continue
        key = tuple((round(x, 4), round(y, 4)) for x, y in poly)
        rev = tuple(reversed(key))
        norm_key = key if key < rev else rev
        if norm_key in seen:
            continue
        seen.add(norm_key)
        deduped.append(item)
    return deduped


def to_drawing_polylines(items: List[PathItem]) -> List[List[Tuple[float, float]]]:
    grouped = {}
    for item in items:
        group_key = (item.source_id, bool(item.is_fill), item.is_stroke)
        grouped.setdefault(group_key, []).append(item)

    out: List[List[Tuple[float, float]]] = []
    for (source_id, is_fill, is_stroke), group in grouped.items():
        _ = source_id

        if not is_stroke and not is_fill:
            continue

        # Fill-only regions are converted to hatch fill when possible.
        if is_fill and not is_stroke:
            closed_contours = [it.points for it in group if it.closed]
            if closed_contours and all(should_hatch_polygon(it.points, it.closed) for it in group):
                hatch_lines = hatch_polygon(
                    [it.points for it in group if it.closed],
                    spacing=FILL_HATCH_SPACING_MM,
                    angle_deg=FILL_HATCH_ANGLE_DEG,
                    min_segment=FILL_HATCH_MIN_SEGMENT_MM,
                )
                if hatch_lines:
                    out.extend(hatch_lines)
                    continue

        for item in group:
            if len(item.points) >= 2:
                out.append(item.points)

    return out


def translate_polylines(polylines: List[List[Tuple[float, float]]], dx: float, dy: float) -> List[List[Tuple[float, float]]]:
    if dx == 0.0 and dy == 0.0:
        return polylines
    return [[(x + dx, y + dy) for x, y in poly] for poly in polylines]

def points_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def write_xy_gcode(output: Path, polylines: List[List[Tuple[float, float]]], feed_travel: float, feed_draw: float) -> None:
    lines = [
        "G21",
        "G90",
        f"G0 Z{Z_UP:.4f}",
    ]
    pos = None
    for poly in polylines:
        if len(poly) < 2:
            continue
        # Always start each polyline with a G0 move, even if start point
        # equals current position. This keeps pen state transitions explicit.
        lines.append(f"G0 X{poly[0][0]:.4f} Y{poly[0][1]:.4f} F{feed_travel:.1f}")
        pos = poly[0]
        drew = False
        for pt in poly[1:]:
            if pos is not None and points_distance(pt, pos) <= 1e-9:
                continue
            if not drew:
                lines.append(f"G1 X{pt[0]:.4f} Y{pt[1]:.4f} F{feed_draw:.1f}")
                drew = True
            else:
                lines.append(f"G1 X{pt[0]:.4f} Y{pt[1]:.4f}")
            pos = pt
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_area_frame_polylines() -> List[List[Tuple[float, float]]]:
    x0 = WORK_AREA_MIN_X + WORK_AREA_FRAME_MARGIN + WORK_OFFSET_X_MM
    x1 = WORK_AREA_MAX_X - WORK_AREA_FRAME_MARGIN + WORK_OFFSET_X_MM
    y0 = WORK_AREA_MIN_Y + WORK_AREA_FRAME_MARGIN + WORK_OFFSET_Y_MM
    y1 = WORK_AREA_MAX_Y - WORK_AREA_FRAME_MARGIN + WORK_OFFSET_Y_MM
    if x1 <= x0 or y1 <= y0:
        return []
    tick = min(8.0, (x1 - x0) * 0.06, (y1 - y0) * 0.06)
    return [
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
        [(x0, y0), (x0 + tick, y0)],
        [(x0, y0), (x0, y0 + tick)],
        [(x1, y0), (x1 - tick, y0)],
        [(x1, y0), (x1, y0 + tick)],
        [(x0, y1), (x0 + tick, y1)],
        [(x0, y1), (x0, y1 - tick)],
        [(x1, y1), (x1 - tick, y1)],
        [(x1, y1), (x1, y1 - tick)],
    ]


def build_area_corner_mark_polylines(mark_size: float = 2.0) -> List[List[Tuple[float, float]]]:
    x_left = min(WORK_AREA_MIN_X, WORK_AREA_MAX_X) + WORK_OFFSET_X_MM
    x_right = max(WORK_AREA_MIN_X, WORK_AREA_MAX_X) + WORK_OFFSET_X_MM
    y_bottom = max(WORK_AREA_MIN_Y, WORK_AREA_MAX_Y) + WORK_OFFSET_Y_MM
    y_top = min(WORK_AREA_MIN_Y, WORK_AREA_MAX_Y) + WORK_OFFSET_Y_MM

    if mark_size <= 0 or x_right <= x_left or y_bottom <= y_top:
        return []

    dx = min(mark_size, abs(x_right - x_left) / 8.0, abs(y_bottom - y_top) / 8.0)
    if dx <= 0.0:
        return []

    corners = [
        (x_left, y_top),
        (x_right, y_top),
        (x_right, y_bottom),
        (x_left, y_bottom),
    ]

    marks: List[List[Tuple[float, float]]] = []
    for cx, cy in corners:
        dir_x = 1.0 if abs(cx - x_left) < 1e-9 else -1.0
        dir_y = 1.0 if abs(cy - y_top) < 1e-9 else -1.0
        marks.append([(cx, cy), (cx + dir_x * dx, cy)])
        marks.append([(cx, cy), (cx, cy + dir_y * dx)])
    return marks


def apply_penlift(xy_gcode: Path, pen_gcode: Path) -> None:
    script = ROOT_DIR / "src" / "penlift_postprocess.py"
    cmd = [
        sys.executable,
        str(script),
        str(xy_gcode),
        "--output",
        str(pen_gcode),
        "--z-down",
        f"{Z_DOWN:.3f}",
        "--z-up",
        f"{Z_UP:.4f}",
        "--mode",
        PEN_LIFT_MODE,
        "--spindle-speed",
        str(PEN_SPINDLE_SPEED),
        "--delay",
        f"{Z_DELAY:.2f}",
    ]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"PenLift postprocess error: {err.strip() or out.strip()}")


def pdf_to_svg(pdf_path: Path, svg_path: Path, logger) -> None:
    logger("Converting PDF -> SVG ...")
    # Prefer pdftocairo first: it exports SVG from PDF in headless mode without any UI.
    try:
        cairo = find_pdftocairo()
        cairo_prefix = svg_path.with_suffix("")
        cmd = [cairo, "-svg", "-f", "1", "-l", "1", str(pdf_path), str(cairo_prefix)]
        logger(f"Trying pdftocairo: {' '.join(cmd)}")
        rc, out, err = run_cmd(cmd)
        if rc == 0:
            candidates = []
            base = cairo_prefix
            if str(base).endswith(".svg"):
                base = base.with_suffix("")
            if base.suffix:
                candidates.append(base.with_suffix(".svg"))
            candidates.append(base)
            candidates.append(Path(f"{base}-1"))
            candidates.append(Path(f"{base}-1.svg"))
            candidates.extend(sorted(base.parent.glob(f"{base.name}*")))
            for candidate in candidates:
                if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
                    if candidate != svg_path:
                        if svg_path.exists():
                            svg_path.unlink()
                        candidate.replace(svg_path)
                    logger("Converted PDF with pdftocairo.")
                    return
        logger(f"pdftocairo failed, fallback to Inkscape. { (out + '\\n' + err).strip() }")
    except Exception as e:
        logger(f"pdftocairo check failed, fallback to Inkscape: {e}")

    exe = find_inkscape()
    logger(f"Using Inkscape: {exe}")
    major, _, _ = get_inkscape_version(exe)
    # Prefer headless export flags for the detected version to avoid opening GUI.
    if major >= 1:
        candidates = [
            [
                exe,
                "--batch-process",
                "--export-type=svg",
                "--export-area-page",
                "--export-overwrite",
                f"--export-filename={svg_path}",
                "--pdf-page=1",
                "--pdf-poppler",
                str(pdf_path),
            ],
            [
                exe,
                "--batch-process",
                "--export-type=svg",
                "--export-area-page",
                "--export-overwrite",
                f"--export-filename={svg_path}",
                "--pdf-page=1",
                str(pdf_path),
            ],
            [
                exe,
                "--batch-process",
                "--actions=select-all;object-to-path;export-text-to-path",
                "--export-overwrite",
                "--export-area-page",
                f"--export-filename={svg_path}",
                "--pdf-page=1",
                str(pdf_path),
            ],
            [
                exe,
                "--batch-process",
                "--actions=select-all;object-to-path;export-text-to-path",
                "--export-overwrite",
                "--export-area-page",
                "--export-plain-svg",
                f"--export-filename={svg_path}",
                "--pdf-page=1",
                str(pdf_path),
            ],
        ]
    else:
        candidates = [
            [
                exe,
                "--export-area-page",
                f"--export-plain-svg={svg_path}",
                str(pdf_path),
            ],
            [
                exe,
                "-D",
                "--export-plain-svg",
                str(svg_path),
                str(pdf_path),
            ],
            [
                exe,
                "-z",
                "-l",
                str(svg_path),
                str(pdf_path),
            ],
        ]

    last_error = ""
    for i, cmd in enumerate(candidates, start=1):
        logger(f"Inkscape command #{i}: {' '.join([Path(str(cmd[0])).name] + [str(x) for x in cmd[1:]])}")
        rc, out, err = run_cmd(cmd)
        if rc == 0 and svg_path.exists() and svg_path.stat().st_size > 0:
            return
        block = (out + "\n" + err).strip()
        logger(f"Inkscape command #{i} failed or produced empty SVG: {block}")
        if block:
            last_error = block

    raise RuntimeError(f"Inkscape failed to export SVG. {last_error}".strip() or "Unknown error")

def make_final_with_preamble(prepared_gcode: Path, final_gcode: Path) -> None:
    lines = [
        "$X",
        "$1=255",
        "G21",
        "G90",
        f"G92 Z{Z_UP:.4f}",
        "",
    ]
    g = prepared_gcode.read_text(encoding="utf-8", errors="ignore")
    trailer = ["", "M5", "$1=0"]
    final_gcode.write_text("\n".join(lines) + g + "\n".join(trailer) + "\n", encoding="utf-8")


def send_to_grbl(gcode_file: Path, com: str, baud: str, logger) -> None:
    sender = ROOT_DIR / "src" / "send_grbl_file.py"
    if not sender.exists():
        raise RuntimeError("send_grbl_file.py not found")
    cmd = [sys.executable, str(sender), com, baud, str(gcode_file)]
    logger("Sending to Grbl ...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout is None:
        raise RuntimeError("Failed to read sender output")
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        logger(line.strip())
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"Sender error code: {rc}")

def run_pipeline(
    input_path: Path,
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    try:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            svg_path = work / "source.svg"
            xy_path = work / "path_xy.gcode"
            pen_path = work / "path_pen.gcode"
            final_path = work / "path_final.gcode"

            ext = input_path.suffix.lower()
            if ext == ".svg":
                svg_path = input_path
                if svg_path is None or not svg_path.exists():
                    return False, "Input SVG file not found."
            else:
                pdf_to_svg(input_path, svg_path, log)

            log("Extracting paths from SVG ...")
            path_items = extract_polylines(svg_path)
            if not path_items:
                return False, "No drawable paths found in file."
            polylines = to_drawing_polylines(path_items)
            if not polylines:
                return False, "No drawable geometry found after fill/stroke analysis."
            min_x, max_x, min_y, max_y = bounds_polylines(polylines)
            polylines = fit_polylines_to_area(polylines, min_x, max_x, min_y, max_y, logger=log)
            polylines = translate_polylines(polylines, WORK_OFFSET_X_MM, WORK_OFFSET_Y_MM)
            polylines = clip_polylines_to_work_area(polylines, logger=log)
            if not polylines:
                return False, "No drawable geometry remains after clipping to work area."
            write_xy_gcode(xy_path, polylines, FEED_TRAVEL, FEED_DRAW)
            log("Applying pen-up / pen-down ...")
            apply_penlift(xy_path, pen_path)
            make_final_with_preamble(pen_path, final_path)
            if send_to_plotter:
                send_to_grbl(final_path, com, baud, log)
                return_msg = f"Done: {input_path.name} sent."
            else:
                target = output_path or input_path.with_name(f"{input_path.stem}_prepared.nc")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(final_path.read_text(encoding="utf-8"), encoding="utf-8")
                log(f"Saved: {target}")
                return_msg = f"Done: prepared file saved to {target}"
            return True, return_msg
    except Exception as exc:
        return False, f"Error: {exc}"


def run_frame_pipeline(
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    try:
        frame = build_area_frame_polylines()
        if not frame:
            return False, "Invalid work area limits."
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            xy_path = work / "work_area_xy.gcode"
            pen_path = work / "work_area_pen.gcode"
            final_path = work / "work_area_final.gcode"

            frame = clip_polylines_to_work_area(frame, logger=log)
            write_xy_gcode(xy_path, frame, FEED_TRAVEL, FEED_DRAW)
            log("Applying pen-up / pen-down ...")
            apply_penlift(xy_path, pen_path)
            make_final_with_preamble(pen_path, final_path)
            if send_to_plotter:
                send_to_grbl(final_path, com, baud, log)
                return_msg = "Done: work area frame sent."
            else:
                target = output_path or Path("work_area_frame_prepared.nc")
                target.write_text(final_path.read_text(encoding="utf-8"), encoding="utf-8")
                log(f"Saved: {target}")
                return_msg = f"Done: work area frame saved to {target}"
        return True, return_msg
    except Exception as exc:
        return False, f"Error: {exc}"


def run_corner_calibration_pipeline(
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
    mark_size: float = 2.0,
) -> Tuple[bool, str]:
    try:
        frame = build_area_frame_polylines()
        marks = build_area_corner_mark_polylines(mark_size=mark_size)
        if not frame and not marks:
            return False, "Invalid work area limits."

        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            xy_path = work / "corner_xy.gcode"
            pen_path = work / "corner_pen.gcode"
            final_path = work / "corner_final.gcode"

            all_paths: List[List[Tuple[float, float]]] = []
            all_paths.extend(frame)
            all_paths.extend(marks)

            all_paths = clip_polylines_to_work_area(all_paths, logger=log)
            if not all_paths:
                return False, "No geometry after clipping work area."

            write_xy_gcode(xy_path, all_paths, FEED_TRAVEL, FEED_DRAW)
            log("Applying pen-up / pen-down ...")
            apply_penlift(xy_path, pen_path)
            make_final_with_preamble(pen_path, final_path)

            if send_to_plotter:
                send_to_grbl(final_path, com, baud, log)
                return_msg = "Done: 4-corner calibration sent."
            else:
                target = output_path or Path("corner_calibration_prepared.nc")
                target.write_text(final_path.read_text(encoding="utf-8"), encoding="utf-8")
                log(f"Saved: {target}")
                return_msg = f"Done: calibration file saved to {target}"
        return True, return_msg
    except Exception as exc:
        return False, f"Error: {exc}"

class PlotterApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PDF -> Plotter")
        self.root.geometry("680x430")
        self.com_port = detect_com_port(DEFAULT_COM_PORT)

        self.queue: Queue[str] = Queue()
        self.busy = False

        top = tk.Frame(self.root)
        top.pack(fill="x", padx=12, pady=12)
        self.select_btn = tk.Button(top, text="Choose PDF and Draw", command=self._pick_and_start, font=("Segoe UI", 11))
        self.select_btn.pack(side="left")
        self.frame_btn = tk.Button(top, text="Draw Work Area Frame", command=self._draw_area_frame, font=("Segoe UI", 11))
        self.frame_btn.pack(side="left", padx=8)
        self.calibrate_btn = tk.Button(
            top,
            text="Calibrate 4 Corners",
            command=self._calibrate_corners,
            font=("Segoe UI", 11),
        )
        self.calibrate_btn.pack(side="left", padx=8)
        mode_info = "M3/M5" if PEN_LIFT_MODE == "spindle" else f"Z ({Z_UP}-{Z_DOWN})"
        tk.Label(top, text=f"COM: {self.com_port}, Baud: {DEFAULT_BAUD}, Pen: {mode_info}", anchor="w").pack(side="left", padx=10)

        self.status = tk.Label(self.root, text="Waiting for file", anchor="w")
        self.status.pack(fill="x", padx=12, pady=(0, 8))

        self.log = scrolledtext.ScrolledText(self.root, height=16)
        self.log.pack(expand=True, fill="both", padx=12, pady=(0, 12))

        self._add_log("Ready. Click button and choose PDF.")
        self.root.after(100, self._flush_log)

    def _add_log(self, msg: str):
        self.queue.put(msg)

    def _flush_log(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                self.log.insert("end", f"{msg}\n")
                self.log.see("end")
        except Empty:
            pass
        self.root.after(100, self._flush_log)

    def _set_status(self, msg: str):
        self.status.config(text=msg)

    def _pick_and_start(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")], title="Select PDF")
        if not path:
            return
        self.busy = True
        self.select_btn.config(state="disabled")
        self.frame_btn.config(state="disabled")
        self._set_status("Running...")
        self._add_log(f"File: {path}")
        threading.Thread(target=self._worker, args=(Path(path),), daemon=True).start()

    def _draw_area_frame(self):
        if self.busy:
            return
        self.busy = True
        self.select_btn.config(state="disabled")
        self.frame_btn.config(state="disabled")
        self.calibrate_btn.config(state="disabled")
        self._set_status("Running frame...")
        self._add_log("Drawing safe work area frame.")
        threading.Thread(target=self._frame_worker, daemon=True).start()

    def _calibrate_corners(self):
        if self.busy:
            return
        self.busy = True
        self.select_btn.config(state="disabled")
        self.frame_btn.config(state="disabled")
        self.calibrate_btn.config(state="disabled")
        self._set_status("Running corner calibration...")
        self._add_log("Drawing 4-corner calibration marks.")
        threading.Thread(target=self._calibrate_corners_worker, daemon=True).start()

    def _worker(self, input_path: Path):
        ok, msg = run_pipeline(input_path, self._add_log, self.com_port)
        self._add_log(msg)
        self.root.after(
            0,
            lambda: self._finish(ok),
        )

    def _frame_worker(self):
        ok, msg = run_frame_pipeline(self._add_log, self.com_port)
        self._add_log(msg)
        self.root.after(0, lambda: self._finish(ok))

    def _calibrate_corners_worker(self):
        ok, msg = run_corner_calibration_pipeline(self._add_log, self.com_port, mark_size=2.0)
        self._add_log(msg)
        self.root.after(0, lambda: self._finish(ok))

    def _finish(self, ok: bool):
        self.busy = False
        self.select_btn.config(state="normal")
        self.frame_btn.config(state="normal")
        self.calibrate_btn.config(state="normal")
        if ok:
            self._set_status("Done: file sent")
            messagebox.showinfo("Done", "File sent to plotter.")
        else:
            self._set_status("Error.")

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="PDF/SVG -> Plotter converter")
    parser.add_argument("input", nargs="?", help="Path to PDF or SVG file")
    parser.add_argument("--frame", action="store_true", help="Draw work area frame")
    parser.add_argument("--calibrate-corners", action="store_true", help="Draw work area frame and corner marks for calibration")
    parser.add_argument("--com", default=None, help="COM port (default detect)")
    parser.add_argument("--baud", default=DEFAULT_BAUD, help="Baud rate")
    parser.add_argument("--dry-run", action="store_true", help="Generate G-code and save file without sending to plotter")
    parser.add_argument("--output", default=None, help="Output file when --dry-run is set")
    parser.add_argument("--corner-mark-size", type=float, default=2.0, help="Corner mark size in mm")
    args = parser.parse_args()
    com = detect_com_port(DEFAULT_COM_PORT if args.com is None else args.com)

    if args.frame:
        ok, msg = run_frame_pipeline(
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=Path(args.output) if args.output else None,
        )
        print(msg)
        return 0 if ok else 1

    if args.calibrate_corners:
        ok, msg = run_corner_calibration_pipeline(
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=Path(args.output) if args.output else None,
            mark_size=args.corner_mark_size,
        )
        print(msg)
        return 0 if ok else 1

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Input not found: {input_path}")
            return 2
        if input_path.suffix.lower() not in {".pdf", ".svg"}:
            print(f"Unsupported file type: {input_path.suffix}. Use .pdf or .svg.")
            return 3
        ok, msg = run_pipeline(
            input_path,
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=Path(args.output) if args.output else None,
        )
        print(msg)
        return 0 if ok else 1

    app = PlotterApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
