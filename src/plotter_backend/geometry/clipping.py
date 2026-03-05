from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from .polyline import points_distance

Point = Tuple[float, float]
Polyline = Sequence[Point]
ClampFn = Callable[[float, float, float, float, float, float], Point]
PointInRectFn = Callable[[float, float, float, float, float, float], bool]


def clamp_to_rect(x: float, y: float, min_x: float, max_x: float, min_y: float, max_y: float) -> Point:
    return (min(max(x, min_x), max_x), min(max(y, min_y), max_y))


def point_in_rect(
    x: float,
    y: float,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    eps: float = 0.0,
) -> bool:
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
) -> Optional[Tuple[Point, Point]]:
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

    r = upd(-dx, x1 - min_x, t0, t1)
    if r is None:
        return None
    t0, t1 = r
    r = upd(dx, max_x - x1, t0, t1)
    if r is None:
        return None
    t0, t1 = r
    r = upd(-dy, y1 - min_y, t0, t1)
    if r is None:
        return None
    t0, t1 = r
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


def clip_polylines_to_rect(
    polylines: Sequence[Polyline],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    *,
    continuity_eps_mm: float,
    logger=None,
    clamp_fn: ClampFn = clamp_to_rect,
    point_in_rect_fn: PointInRectFn = point_in_rect,
) -> List[List[Point]]:
    clipped_all: List[List[Point]] = []
    dropped_segments = 0
    written_segments = 0

    for poly in polylines:
        if len(poly) < 2:
            continue
        out_poly: List[Point] = []
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
            cx1, cy1 = clamp_fn(cx1, cy1, min_x, max_x, min_y, max_y)
            cx2, cy2 = clamp_fn(cx2, cy2, min_x, max_x, min_y, max_y)

            if not point_in_rect_fn(cx1, cy1, min_x, max_x, min_y, max_y):
                dropped_segments += 1
                if out_poly and len(out_poly) >= 2:
                    clipped_all.append(out_poly)
                out_poly = []
                continue

            if not out_poly:
                out_poly = [(cx1, cy1)]

            if points_distance((cx1, cy1), out_poly[-1]) > continuity_eps_mm:
                clipped_all.append(out_poly)
                out_poly = [(cx1, cy1)]
            else:
                cx1, cy1 = out_poly[-1]

            if points_distance((cx2, cy2), out_poly[-1]) > 1e-6:
                out_poly.append((cx2, cy2))
                written_segments += 1

        if len(out_poly) >= 2:
            clipped_all.append(out_poly)

    if logger and dropped_segments:
        logger(
            f"Work area clipping: kept {written_segments} visible segments, dropped {dropped_segments} out-of-area segments."
        )
    return clipped_all

