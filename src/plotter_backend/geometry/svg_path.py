from __future__ import annotations

import math
import re
from typing import Callable, Iterable, List, Optional, Tuple

Point = Tuple[float, float]

_CMD_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")
_FLOAT_RE = re.compile(r"[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?")


def _parse_floats(text: str) -> List[float]:
    return [float(v) for v in _FLOAT_RE.findall(text)]


def parse_path_tokens(
    path_d: str,
    *,
    parse_floats_fn: Optional[Callable[[str], List[float]]] = None,
) -> Iterable[Tuple[str, List[float]]]:
    tokens = [t for t in re.split(r"([MmLlHhVvCcSsQqTtAaZz])", path_d) if t and not t.isspace()]
    if not tokens:
        return
    parse_numbers = parse_floats_fn or _parse_floats
    cmd: Optional[str] = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if _CMD_RE.fullmatch(token):
            cmd = token
            i += 1
            if cmd in "Zz":
                yield cmd, []
            continue
        if cmd is None:
            raise ValueError("Path starts with coordinates")
        params: List[float] = []
        while i < len(tokens) and not _CMD_RE.fullmatch(tokens[i]):
            params.extend(parse_numbers(tokens[i]))
            i += 1
        yield cmd, params


def cubic_approx(p0: Point, p1: Point, p2: Point, p3: Point, step: float = 4.0) -> List[Point]:
    def bezier_point(a: Point, b: Point, c: Point, d: Point, t: float) -> Point:
        mt = 1.0 - t
        return (
            mt * mt * mt * a[0] + 3.0 * mt * mt * t * b[0] + 3.0 * mt * t * t * c[0] + t * t * t * d[0],
            mt * mt * mt * a[1] + 3.0 * mt * mt * t * b[1] + 3.0 * mt * t * t * c[1] + t * t * t * d[1],
        )

    samples = 10
    prev = p0
    length = 0.0
    for i in range(1, samples + 1):
        t = i / samples
        cur = bezier_point(p0, p1, p2, p3, t)
        length += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        prev = cur
    chord = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    length = max(length, chord, 0.0001)

    seg = max(2, int(math.ceil(length / max(float(step), 0.0001))))
    return [bezier_point(p0, p1, p2, p3, i / seg) for i in range(1, seg + 1)]


def quadratic_approx(p0: Point, p1: Point, p2: Point, step: float = 4.0) -> List[Point]:
    def bezier_point(a: Point, b: Point, c: Point, t: float) -> Point:
        mt = 1.0 - t
        return (
            mt * mt * a[0] + 2.0 * mt * t * b[0] + t * t * c[0],
            mt * mt * a[1] + 2.0 * mt * t * b[1] + t * t * c[1],
        )

    samples = 10
    prev = p0
    length = 0.0
    for i in range(1, samples + 1):
        t = i / samples
        cur = bezier_point(p0, p1, p2, t)
        length += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        prev = cur
    chord = math.hypot(p2[0] - p0[0], p2[1] - p0[1])
    length = max(length, chord, 0.0001)

    seg = max(2, int(math.ceil(length / max(float(step), 0.0001))))
    return [bezier_point(p0, p1, p2, i / seg) for i in range(1, seg + 1)]


def arc_to_polyline(
    p0: Point,
    rx: float,
    ry: float,
    angle_deg: float,
    large_arc: int,
    sweep: int,
    p1: Point,
    step: float = 0.35,
) -> List[Point]:
    x1, y1 = p0
    x2, y2 = p1
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(angle_deg % 360.0)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    rx = abs(float(rx))
    ry = abs(float(ry))
    if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
        return []

    dx2 = (x1 - x2) / 2.0
    dy2 = (y1 - y2) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    sign = -1.0 if bool(large_arc) == bool(sweep) else 1.0
    den = (rx * rx * y1p * y1p + ry * ry * x1p * x1p)
    if den <= 1e-15:
        return [(x2, y2)]
    sq = max(0.0, (rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p) / den)
    if not math.isfinite(sq):
        return [(x2, y2)]
    cpx = sign * math.sqrt(sq) * (rx * y1p / ry)
    cpy = sign * math.sqrt(sq) * (-ry * x1p / rx)

    cx = cos_phi * cpx - sin_phi * cpy + (x1 + x2) / 2.0
    cy = sin_phi * cpx + cos_phi * cpy + (y1 + y2) / 2.0
    if not (math.isfinite(cx) and math.isfinite(cy)):
        return [(x2, y2)]

    v1x = (x1p - cpx) / rx
    v1y = (y1p - cpy) / ry
    v2x = (-x1p - cpx) / rx
    v2y = (-y1p - cpy) / ry
    theta1 = math.atan2(v1y, v1x)
    delta = math.atan2(v1x * v2y - v1y * v2x, v1x * v2x + v1y * v2y)
    if not sweep and delta > 0.0:
        delta -= 2.0 * math.pi
    if sweep and delta < 0.0:
        delta += 2.0 * math.pi

    arc_len = abs(delta) * max(rx, ry)
    n = max(1, int(math.ceil(arc_len / max(float(step), 0.1))))
    pts: List[Point] = []
    for i in range(1, n + 1):
        t = theta1 + delta * (i / n)
        x = cx + rx * math.cos(t) * cos_phi - ry * math.sin(t) * sin_phi
        y = cy + rx * math.cos(t) * sin_phi + ry * math.sin(t) * cos_phi
        if not (math.isfinite(x) and math.isfinite(y)):
            return [(x2, y2)]
        pts.append((x, y))
    return pts
