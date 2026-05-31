from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable, Tuple


_TOKEN_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


def _strip_comments(line: str) -> str:
    line = str(line or "").split(";", 1)[0]
    out: list[str] = []
    depth = 0
    for ch in line:
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip()


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


def summarize_gcode_file(
    gcode_path: Path,
    *,
    points_distance: Callable[[Tuple[float, float], Tuple[float, float]], float],
    arc_extents_xy: Callable[
        [Tuple[float, float], Tuple[float, float], Tuple[float, float], bool],
        Tuple[float, float, float, float],
    ],
) -> Tuple[int, int, int, Tuple[float, float, float, float]]:
    total_lines = 0
    draw_moves = 0
    travel_moves = 0
    min_x = math.inf
    max_x = -math.inf
    min_y = math.inf
    max_y = -math.inf

    cur_x = None
    cur_y = None
    last_motion = None
    abs_mode = True
    ijk_abs = False

    with gcode_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = _strip_comments(raw)
            if not line:
                continue
            total_lines += 1

            tokens = _TOKEN_RE.findall(line)
            g_values = _values(tokens, "G")
            code = last_motion
            for gval in g_values:
                if abs(gval - 90.0) <= 1e-9:
                    abs_mode = True
                    continue
                if abs(gval - 91.0) <= 1e-9:
                    abs_mode = False
                    continue
                if abs(gval - 90.1) <= 1e-9:
                    ijk_abs = True
                    continue
                if abs(gval - 91.1) <= 1e-9:
                    ijk_abs = False
                    continue
                rounded = int(round(gval))
                if abs(gval - rounded) > 1e-9:
                    continue
                if rounded in {0, 1, 2, 3}:
                    code = rounded
                    last_motion = rounded

            x_values = _values(tokens, "X")
            y_values = _values(tokens, "Y")
            i_values = _values(tokens, "I")
            j_values = _values(tokens, "J")
            x = x_values[-1] if x_values else None
            y = y_values[-1] if y_values else None
            i = i_values[-1] if i_values else None
            j = j_values[-1] if j_values else None
            has_xy = bool(x_values or y_values)
            if cur_x is None:
                tx = x
            elif x is None:
                tx = cur_x
            else:
                tx = x if abs_mode else (cur_x + x)
            if cur_y is None:
                ty = y
            elif y is None:
                ty = cur_y
            else:
                ty = y if abs_mode else (cur_y + y)

            # Update bounds. For G2/G3, include arc bulge (not just endpoints).
            if code in {2, 3} and cur_x is not None and cur_y is not None and tx is not None and ty is not None and i is not None and j is not None:
                start = (cur_x, cur_y)
                end = (tx, ty)
                center = (i, j) if ijk_abs else (cur_x + i, cur_y + j)
                if points_distance(start, end) <= 1e-6:
                    r = math.hypot(start[0] - center[0], start[1] - center[1])
                    ax0, ax1, ay0, ay1 = (center[0] - r, center[0] + r, center[1] - r, center[1] + r)
                else:
                    ax0, ax1, ay0, ay1 = arc_extents_xy(start, end, center, cw=(code == 2))
                min_x = min(min_x, ax0)
                max_x = max(max_x, ax1)
                min_y = min(min_y, ay0)
                max_y = max(max_y, ay1)
                cur_x, cur_y = end
            elif has_xy and tx is not None and ty is not None:
                min_x = min(min_x, tx)
                max_x = max(max_x, tx)
                min_y = min(min_y, ty)
                max_y = max(max_y, ty)
                cur_x, cur_y = tx, ty

            if has_xy and code in {1, 2, 3}:
                draw_moves += 1
            elif has_xy and code == 0:
                travel_moves += 1

    if min_x == math.inf:
        return total_lines, draw_moves, travel_moves, (0.0, 0.0, 0.0, 0.0)
    return total_lines, draw_moves, travel_moves, (min_x, max_x, min_y, max_y)

