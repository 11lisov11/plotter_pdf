from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable, Tuple


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

    x_re = re.compile(r"\bX(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    y_re = re.compile(r"\bY(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    i_re = re.compile(r"\bI(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    j_re = re.compile(r"\bJ(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    g_re = re.compile(r"\bG(\d+)")

    cur_x = None
    cur_y = None

    with gcode_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith(";") or line.startswith("("):
                continue
            total_lines += 1

            g_match = g_re.search(line)
            if g_match:
                code = int(g_match.group(1))
            else:
                code = None

            sx = x_re.search(line)
            sy = y_re.search(line)
            x = float(sx.group(1)) if sx else None
            y = float(sy.group(1)) if sy else None
            si = i_re.search(line)
            sj = j_re.search(line)

            # Update bounds. For G2/G3, include arc bulge (not just endpoints).
            if code in {2, 3} and cur_x is not None and cur_y is not None and x is not None and y is not None and si and sj:
                i = float(si.group(1))
                j = float(sj.group(1))
                start = (cur_x, cur_y)
                end = (x, y)
                center = (cur_x + i, cur_y + j)
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
            elif x is not None and y is not None:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                cur_x, cur_y = x, y

            if code in {1, 2, 3}:
                draw_moves += 1
            elif code == 0:
                travel_moves += 1

    if min_x == math.inf:
        return total_lines, draw_moves, travel_moves, (0.0, 0.0, 0.0, 0.0)
    return total_lines, draw_moves, travel_moves, (min_x, max_x, min_y, max_y)

