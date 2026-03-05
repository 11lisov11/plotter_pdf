from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from .polyline import points_distance

Point = Tuple[float, float]
Polyline = Sequence[Point]


def point_line_distance(point: Point, line_a: Point, line_b: Point) -> float:
    x0, y0 = point
    x1, y1 = line_a
    x2, y2 = line_b
    dx = x2 - x1
    dy = y2 - y1
    den = dx * dx + dy * dy
    if den <= 1e-18:
        return points_distance(point, line_a)
    t = ((x0 - x1) * dx + (y0 - y1) * dy) / den
    t = max(0.0, min(1.0, t))
    px = x1 + t * dx
    py = y1 + t * dy
    return points_distance(point, (px, py))


def path_is_closed(poly: Polyline, eps: float = 1e-6) -> bool:
    return len(poly) >= 4 and points_distance(poly[0], poly[-1]) <= eps


def rdp_simplify_open(poly: Polyline, eps: float) -> List[Point]:
    if eps <= 0.0 or len(poly) < 3:
        return list(poly)

    keep = [False] * len(poly)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(poly) - 1)]

    while stack:
        a_i, b_i = stack.pop()
        ax, ay = poly[a_i]
        bx, by = poly[b_i]
        max_d = -1.0
        max_i = -1
        for i in range(a_i + 1, b_i):
            d = point_line_distance(poly[i], (ax, ay), (bx, by))
            if d > max_d:
                max_d = d
                max_i = i
        if max_d > eps and max_i != -1:
            keep[max_i] = True
            stack.append((a_i, max_i))
            stack.append((max_i, b_i))

    out = [p for i, p in enumerate(poly) if keep[i]]
    return out if len(out) >= 2 else list(poly)


def rdp_simplify_polyline(poly: Polyline, eps: float) -> List[Point]:
    if eps <= 0.0 or len(poly) < 3:
        return list(poly)

    if not path_is_closed(poly):
        return rdp_simplify_open(poly, eps)

    ring = list(poly[:-1])
    if len(ring) < 4:
        return list(poly)

    best_i = 0
    best_score = -1.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[(i - 1) % n]
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        ux, uy = (x0 - x1), (y0 - y1)
        vx, vy = (x2 - x1), (y2 - y1)
        un = math.hypot(ux, uy)
        vn = math.hypot(vx, vy)
        if un <= 1e-9 or vn <= 1e-9:
            continue
        dot = max(-1.0, min(1.0, (ux * vx + uy * vy) / (un * vn)))
        score = -dot
        if score > best_score:
            best_score = score
            best_i = i

    rotated = ring[best_i:] + ring[:best_i]
    simplified = rdp_simplify_open(rotated, eps)
    if len(simplified) < 3:
        return list(poly)
    if points_distance(simplified[0], simplified[-1]) <= 1e-6:
        return simplified
    return simplified + [simplified[0]]


def simplify_polyline(
    poly: Polyline,
    eps: float = 1e-6,
    *,
    collinear_eps: Optional[float] = None,
    simplify_enabled: bool = True,
    default_collinear_eps: float = 0.0,
    backtrack_spike_max_mm: float = 0.0,
) -> List[Point]:
    if not poly:
        return []
    if not simplify_enabled:
        return list(poly)

    out: List[Point] = [poly[0]]
    for p in poly[1:]:
        if points_distance(out[-1], p) > eps:
            out.append(p)

    if len(out) >= 3 and backtrack_spike_max_mm > 0:
        collapsed: List[Point] = []
        for p in out:
            if (
                len(collapsed) >= 2
                and points_distance(collapsed[-2], p) <= eps
                and points_distance(collapsed[-2], collapsed[-1]) <= backtrack_spike_max_mm
            ):
                collapsed.pop()
                continue
            collapsed.append(p)
        out = collapsed

    if len(out) < 3:
        return out

    col = [out[0]]
    col_eps = float(default_collinear_eps if collinear_eps is None else max(0.0, collinear_eps))
    for p in out[1:]:
        if len(col) >= 2:
            last = col[-1]
            prev = col[-2]
            if point_line_distance(last, prev, p) <= col_eps:
                col[-1] = p
                continue
        col.append(p)

    if len(col) < 2:
        return col
    cleaned = [col[0]]
    for p in col[1:]:
        if points_distance(cleaned[-1], p) > eps:
            cleaned.append(p)
    return cleaned

