from __future__ import annotations

import math
from typing import Callable, List, Sequence, Tuple

from .polyline import points_distance
from .simplify import path_is_closed

Point = Tuple[float, float]
Polyline = Sequence[Point]


def polygon_area(poly: Polyline) -> float:
    if len(poly) < 3:
        return 0.0
    area = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def polygon_bbox(poly: Polyline) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), max(xs), min(ys), max(ys)


def rotate_point(point: Point, angle_rad: float) -> Point:
    x, y = point
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (x * cos_a + y * sin_a, -x * sin_a + y * cos_a)


def rotate_polyline(poly: Polyline, angle_rad: float) -> List[Point]:
    if angle_rad == 0.0:
        return list(poly)
    return [rotate_point(p, angle_rad) for p in poly]


def intersects_for_scanline(edges: Sequence[Tuple[Point, Point]], y: float) -> List[float]:
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


def should_hatch_polygon(
    poly: Polyline,
    closed: bool,
    *,
    fill_hatch_enabled: bool,
    fill_hatch_min_area_mm2: float,
    fill_hatch_min_side_mm: float,
    path_is_closed_fn: Callable[[Polyline], bool] | None = None,
) -> bool:
    if not closed or len(poly) < 4:
        return False
    if not fill_hatch_enabled:
        return False

    is_closed = path_is_closed_fn or path_is_closed
    ring = list(poly[:-1]) if is_closed(poly) else list(poly)
    if len(ring) < 4:
        return False

    area = abs(polygon_area(ring))
    if area < float(fill_hatch_min_area_mm2):
        return False
    min_x, max_x, min_y, max_y = polygon_bbox(ring)
    if (max_x - min_x) < float(fill_hatch_min_side_mm) or (max_y - min_y) < float(fill_hatch_min_side_mm):
        return False
    return True


def hatch_polygon(
    contours: Sequence[Polyline],
    *,
    spacing: float,
    angle_deg: float,
    min_segment: float,
    path_is_closed_fn: Callable[[Polyline], bool] | None = None,
) -> List[List[Point]]:
    if spacing <= 0:
        return []
    angle_rad = math.radians(angle_deg)

    is_closed = path_is_closed_fn or path_is_closed
    valid_contours = [list(c[:-1]) if is_closed(c) else list(c) for c in contours if len(c) >= 3]
    if not valid_contours:
        return []

    rotated = [rotate_polyline(c, angle_rad) for c in valid_contours]
    edges: List[Tuple[Point, Point]] = []
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

    out: List[List[Point]] = []
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

