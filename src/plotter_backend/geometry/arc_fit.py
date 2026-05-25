from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from .polyline import points_distance
from .simplify import point_line_distance

Point = Tuple[float, float]
Polyline = Sequence[Point]


def solve_3x3(mat: Sequence[Sequence[float]], vec: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    a = [list(row) for row in mat]
    b = list(vec)

    n = 3
    for col in range(n):
        pivot = col
        pivot_val = abs(a[col][col])
        for r in range(col + 1, n):
            v = abs(a[r][col])
            if v > pivot_val:
                pivot = r
                pivot_val = v
        if pivot_val < 1e-12:
            return None
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            b[col], b[pivot] = b[pivot], b[col]

        div = a[col][col]
        for r in range(col + 1, n):
            factor = a[r][col] / div
            if abs(factor) < 1e-18:
                continue
            for c in range(col, n):
                a[r][c] -= factor * a[col][c]
            b[r] -= factor * b[col]

    x = [0.0, 0.0, 0.0]
    for r in range(n - 1, -1, -1):
        s = b[r]
        for c in range(r + 1, n):
            s -= a[r][c] * x[c]
        if abs(a[r][r]) < 1e-12:
            return None
        x[r] = s / a[r][r]
    return float(x[0]), float(x[1]), float(x[2])


def fit_circle_kasa(points: Polyline) -> Optional[Tuple[float, float, float, float]]:
    if len(points) < 3:
        return None

    s_xx = s_xy = s_x = 0.0
    s_yy = s_y = 0.0
    s_b = s_xb = s_yb = 0.0
    n = 0
    for x, y in points:
        b = -(x * x + y * y)
        s_xx += x * x
        s_xy += x * y
        s_x += x
        s_yy += y * y
        s_y += y
        s_b += b
        s_xb += x * b
        s_yb += y * b
        n += 1

    mat = [
        [s_xx, s_xy, s_x],
        [s_xy, s_yy, s_y],
        [s_x, s_y, float(n)],
    ]
    vec = [s_xb, s_yb, s_b]
    sol = solve_3x3(mat, vec)
    if sol is None:
        return None

    d, e, f = sol
    cx = -d * 0.5
    cy = -e * 0.5
    rr = cx * cx + cy * cy - f
    if rr <= 1e-12 or not math.isfinite(rr):
        return None
    r = math.sqrt(rr)

    max_err = 0.0
    for x, y in points:
        err = abs(math.hypot(x - cx, y - cy) - r)
        if err > max_err:
            max_err = err
    return float(cx), float(cy), float(r), float(max_err)


def unwrap_angles(angles: Sequence[float]) -> List[float]:
    if not angles:
        return []
    out = [float(angles[0])]
    two_pi = 2.0 * math.pi
    for a in angles[1:]:
        v = float(a)
        prev = out[-1]
        while v - prev > math.pi:
            v -= two_pi
        while v - prev < -math.pi:
            v += two_pi
        out.append(v)
    return out


def arc_extents_xy(start: Point, end: Point, center: Point, cw: bool) -> Tuple[float, float, float, float]:
    cx, cy = center
    x0, y0 = start
    x1, y1 = end
    r = math.hypot(x0 - cx, y0 - cy)
    if r <= 1e-12:
        return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)

    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)

    if cw:
        while a1 > a0:
            a1 -= 2.0 * math.pi
    else:
        while a1 < a0:
            a1 += 2.0 * math.pi

    def in_sweep(a: float) -> bool:
        v = a
        while v - a0 > math.pi:
            v -= 2.0 * math.pi
        while v - a0 < -math.pi:
            v += 2.0 * math.pi
        if cw:
            while v < a1:
                v += 2.0 * math.pi
            return a1 <= v <= a0
        while v > a1:
            v -= 2.0 * math.pi
        return a0 <= v <= a1

    xs = [x0, x1]
    ys = [y0, y1]
    for ang in (0.0, 0.5 * math.pi, math.pi, 1.5 * math.pi):
        if in_sweep(ang):
            xs.append(cx + r * math.cos(ang))
            ys.append(cy + r * math.sin(ang))
    return min(xs), max(xs), min(ys), max(ys)


def _arc_sweep_radians(start: Point, end: Point, center: Point, cw: bool) -> float:
    x0, y0 = start
    x1, y1 = end
    cx, cy = center
    if math.hypot(x1 - x0, y1 - y0) <= 1e-12:
        return 2.0 * math.pi
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if cw:
        sweep = a0 - a1
        if sweep <= 0.0:
            sweep += 2.0 * math.pi
    else:
        sweep = a1 - a0
        if sweep <= 0.0:
            sweep += 2.0 * math.pi
    return abs(float(sweep))


def arc_center_from_radius(start: Point, end: Point, radius_word: float, cw: bool) -> Optional[Point]:
    """Resolve a G-code R-word arc center.

    Positive R selects the minor arc, negative R selects the major arc. Full
    circles cannot be represented by R-word arcs, so coincident endpoints return
    None and callers should fall back to endpoint bounds/length.
    """

    x0, y0 = start
    x1, y1 = end
    radius_raw = float(radius_word)
    radius = abs(radius_raw)
    chord = math.hypot(x1 - x0, y1 - y0)
    if radius <= 1e-12 or chord <= 1e-12:
        return None
    if chord > 2.0 * radius + 1e-9:
        return None

    mx = (x0 + x1) * 0.5
    my = (y0 + y1) * 0.5
    half = chord * 0.5
    h_sq = max(0.0, radius * radius - half * half)
    h = math.sqrt(h_sq)
    nx = -(y1 - y0) / chord
    ny = (x1 - x0) / chord
    candidates = [(mx + nx * h, my + ny * h)]
    if h > 1e-12:
        candidates.append((mx - nx * h, my - ny * h))

    want_major = radius_raw < 0.0
    best = candidates[0]
    for center in candidates:
        sweep = _arc_sweep_radians(start, end, center, cw)
        is_major = sweep > math.pi + 1e-9
        if is_major == want_major:
            return center
        best = center
    return best


def polyline_is_near_line(poly: Polyline, tol_mm: float) -> bool:
    if len(poly) < 3:
        return False
    a = poly[0]
    b = poly[-1]
    if points_distance(a, b) < 1e-9:
        return False
    max_d = 0.0
    for p in poly[1:-1]:
        d = point_line_distance(p, a, b)
        if d > max_d:
            max_d = d
            if max_d > tol_mm:
                return False
    return True


def polyline_fit_arc(
    poly: Polyline,
    tol_mm: float,
    *,
    arc_min_radius_mm: float,
    arc_min_sweep_deg: float,
) -> Optional[Tuple[bool, Point, float, float]]:
    if len(poly) < 3:
        return None

    pts = list(poly)
    if points_distance(pts[0], pts[-1]) <= 1e-6:
        pts = pts[:-1]
    if len(pts) < 3:
        return None

    fit = fit_circle_kasa(pts)
    if fit is None:
        return None
    cx, cy, r, max_err = fit
    if r < float(arc_min_radius_mm):
        return None
    if max_err > tol_mm:
        return None

    angles = [math.atan2(y - cy, x - cx) for x, y in pts]
    unwrapped = unwrap_angles(angles)
    sweep = unwrapped[-1] - unwrapped[0]
    if abs(sweep) < math.radians(float(arc_min_sweep_deg)):
        return None

    cw = sweep < 0.0
    return cw, (cx, cy), r, sweep
