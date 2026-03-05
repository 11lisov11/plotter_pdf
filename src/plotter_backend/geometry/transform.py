from __future__ import annotations

import math
import re
from typing import List, Sequence, Tuple

Transform = Tuple[float, float, float, float, float, float]
Point = Tuple[float, float]

_FLOAT_RE = re.compile(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_TRANSFORM_RE = re.compile(r"(\w+)\(([^)]*)\)")


def _parse_floats(text: str) -> List[float]:
    return [float(v) for v in _FLOAT_RE.findall(text or "")]


def mat_mul(m1: Transform, m2: Transform) -> Transform:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a2 * a1 + c2 * b1,
        b2 * a1 + d2 * b1,
        a2 * c1 + c2 * d1,
        b2 * c1 + d2 * d1,
        a2 * e1 + c2 * f1 + e2,
        b2 * e1 + d2 * f1 + f2,
    )


def mat_apply(m: Transform, p: Point) -> Point:
    x, y = p
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def parse_transform(value: str) -> Transform:
    matrix: Transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, raw in _TRANSFORM_RE.findall(value or ""):
        params = _parse_floats(raw)
        if not params:
            continue
        if name == "matrix" and len(params) == 6:
            op: Transform = tuple(params)  # type: ignore[assignment]
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
                    cos_a,
                    sin_a,
                    -sin_a,
                    cos_a,
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


def parse_points(points_text: str) -> List[Point]:
    nums = _parse_floats(points_text)
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def transform_points(points: Sequence[Point], matrix: Transform, scale: float) -> List[Point]:
    out: List[Point] = []
    factor = float(scale)
    for x, y in points:
        tx, ty = mat_apply(matrix, (x, y))
        out.append((tx * factor, ty * factor))
    return out

