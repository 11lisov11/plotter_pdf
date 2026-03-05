from __future__ import annotations

import math
from typing import Sequence, Tuple

Point = Tuple[float, float]
Polyline = Sequence[Point]
PolylineSet = Sequence[Polyline]


def points_distance(a: Point, b: Point) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def translate_polylines(polylines: PolylineSet, dx: float, dy: float) -> PolylineSet:
    if dx == 0.0 and dy == 0.0:
        return list(polylines)
    return [[(float(x) + float(dx), float(y) + float(dy)) for x, y in poly] for poly in polylines]


def polyline_length(poly: Polyline) -> float:
    if len(poly) < 2:
        return 0.0
    return sum(points_distance(poly[i], poly[i + 1]) for i in range(len(poly) - 1))


def total_draw_length_mm(polylines: PolylineSet) -> float:
    return sum(polyline_length(poly) for poly in polylines if len(poly) >= 2)


def bounds_polylines(polylines: PolylineSet) -> Tuple[float, float, float, float]:
    min_x = min((float(p[0]) for poly in polylines for p in poly), default=0.0)
    max_x = max((float(p[0]) for poly in polylines for p in poly), default=0.0)
    min_y = min((float(p[1]) for poly in polylines for p in poly), default=0.0)
    max_y = max((float(p[1]) for poly in polylines for p in poly), default=0.0)
    return min_x, max_x, min_y, max_y
