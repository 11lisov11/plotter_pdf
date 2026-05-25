from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable, Optional, Tuple

from src.plotter_backend.geometry.arc_fit import arc_center_from_radius

_TOKEN_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


def _values(tokens: list[tuple[str, str]], letter: str) -> list[float]:
    result: list[float] = []
    target = letter.upper()
    for axis, raw in tokens:
        if axis.upper() != target:
            continue
        try:
            result.append(float(raw))
        except ValueError:
            continue
    return result


def strip_gcode_comments(line: str) -> str:
    raw = str(line or "").split(";", 1)[0]
    out: list[str] = []
    depth = 0
    for ch in raw:
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip()


def pen_down_from_z_level(cur_z: float, z_up: float, z_down: float) -> bool:
    rng = abs(float(z_down) - float(z_up))
    if rng <= 1e-9:
        return True
    tol = max(0.05, rng * 0.18)
    if z_down >= z_up:
        return cur_z >= (z_down - tol)
    return cur_z <= (z_down + tol)


def gcode_draw_bounds(
    gcode_path: Path,
    *,
    z_up: float,
    z_down: float,
    points_distance: Callable[[Tuple[float, float], Tuple[float, float]], float],
    arc_extents_xy: Callable[[Tuple[float, float], Tuple[float, float], Tuple[float, float], bool], Tuple[float, float, float, float]],
) -> Optional[Tuple[float, float, float, float]]:
    cur_x = 0.0
    cur_y = 0.0
    cur_z = float(z_up)
    abs_mode = True
    ijk_abs = False
    pen_down = pen_down_from_z_level(cur_z, z_up, z_down)
    last_motion: Optional[int] = None

    min_x = math.inf
    max_x = -math.inf
    min_y = math.inf
    max_y = -math.inf

    def _expand(x0: float, x1: float, y0: float, y1: float) -> None:
        nonlocal min_x, max_x, min_y, max_y
        min_x = min(min_x, x0)
        max_x = max(max_x, x1)
        min_y = min(min_y, y0)
        max_y = max(max_y, y1)

    with gcode_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            body = strip_gcode_comments(raw)
            if not body:
                continue

            motion: Optional[int] = None
            tokens = _TOKEN_RE.findall(body)
            for gval in _values(tokens, "G"):
                if abs(gval - 90.0) <= 1e-9:
                    abs_mode = True
                elif abs(gval - 91.0) <= 1e-9:
                    abs_mode = False
                elif abs(gval - 90.1) <= 1e-9:
                    ijk_abs = True
                elif abs(gval - 91.1) <= 1e-9:
                    ijk_abs = False
                elif abs(gval - 0.0) <= 1e-9:
                    motion = 0
                elif abs(gval - 1.0) <= 1e-9:
                    motion = 1
                elif abs(gval - 2.0) <= 1e-9:
                    motion = 2
                elif abs(gval - 3.0) <= 1e-9:
                    motion = 3
            if motion is None:
                motion = last_motion
            else:
                last_motion = motion
            has_g92 = any(abs(gval - 92.0) <= 1e-9 for gval in _values(tokens, "G"))

            for mval_raw in _values(tokens, "M"):
                mval = int(round(mval_raw))
                if abs(float(mval_raw) - float(mval)) > 1e-9:
                    continue
                if mval == 3:
                    pen_down = True
                elif mval == 5:
                    pen_down = False

            z_values = _values(tokens, "Z")
            x_values = _values(tokens, "X")
            y_values = _values(tokens, "Y")
            if has_g92:
                if x_values:
                    cur_x = x_values[-1]
                if y_values:
                    cur_y = y_values[-1]
                if z_values:
                    cur_z = z_values[-1]
                    pen_down = pen_down_from_z_level(cur_z, z_up, z_down)
                continue

            if z_values:
                z_val = z_values[-1]
                cur_z = z_val if abs_mode else (cur_z + z_val)
                pen_down = pen_down_from_z_level(cur_z, z_up, z_down)

            i_values = _values(tokens, "I")
            j_values = _values(tokens, "J")
            r_values = _values(tokens, "R")
            has_xy = bool(x_values or y_values)
            tx = cur_x
            ty = cur_y
            if x_values:
                xv = x_values[-1]
                tx = xv if abs_mode else (cur_x + xv)
            if y_values:
                yv = y_values[-1]
                ty = yv if abs_mode else (cur_y + yv)

            if pen_down and has_xy and motion in {1, 2, 3}:
                if motion in {2, 3}:
                    if i_values or j_values or r_values:
                        try:
                            if i_values or j_values:
                                i_val = i_values[-1] if i_values else 0.0
                                j_val = j_values[-1] if j_values else 0.0
                                center = (i_val, j_val) if ijk_abs else (cur_x + i_val, cur_y + j_val)
                            else:
                                center = arc_center_from_radius((cur_x, cur_y), (tx, ty), r_values[-1], cw=(motion == 2))
                            if center is None:
                                _expand(min(cur_x, tx), max(cur_x, tx), min(cur_y, ty), max(cur_y, ty))
                            elif points_distance((cur_x, cur_y), (tx, ty)) <= 1e-6:
                                r = math.hypot(cur_x - center[0], cur_y - center[1])
                                _expand(center[0] - r, center[0] + r, center[1] - r, center[1] + r)
                            else:
                                ex0, ex1, ey0, ey1 = arc_extents_xy((cur_x, cur_y), (tx, ty), center, cw=(motion == 2))
                                _expand(ex0, ex1, ey0, ey1)
                        except Exception:
                            _expand(min(cur_x, tx), max(cur_x, tx), min(cur_y, ty), max(cur_y, ty))
                    else:
                        _expand(min(cur_x, tx), max(cur_x, tx), min(cur_y, ty), max(cur_y, ty))
                else:
                    _expand(min(cur_x, tx), max(cur_x, tx), min(cur_y, ty), max(cur_y, ty))

            cur_x, cur_y = tx, ty

    if not math.isfinite(min_x):
        return None
    return (float(min_x), float(max_x), float(min_y), float(max_y))

