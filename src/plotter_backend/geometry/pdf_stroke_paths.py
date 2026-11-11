"""Read original PDF drawing strokes without SVG conversion or text outlines."""

from __future__ import annotations

import math
import re
from pathlib import Path

import fitz

Point = tuple[float, float]
Polyline = list[Point]
PT_TO_MM = 25.4 / 72.0


def _distance_to_chord(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return math.dist(point, a)
    return abs(dx * (point[1] - a[1]) - dy * (point[0] - a[0])) / length


def _midpoint(a: Point, b: Point) -> Point:
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def _cubic(a: Point, b: Point, c: Point, d: Point, tolerance: float, depth: int = 0) -> Polyline:
    # Also constrain control-polygon excess: collinear reversing curves must
    # not collapse to a chord merely because their perpendicular error is zero.
    excess = math.dist(a, b) + math.dist(b, c) + math.dist(c, d) - math.dist(a, d)
    if (max(_distance_to_chord(b, a, d), _distance_to_chord(c, a, d)) <= tolerance
            and excess <= tolerance) or depth >= 20:
        return [a, d]
    ab, bc, cd = _midpoint(a, b), _midpoint(b, c), _midpoint(c, d)
    abc, bcd = _midpoint(ab, bc), _midpoint(bc, cd)
    middle = _midpoint(abc, bcd)
    return _cubic(a, ab, abc, middle, tolerance, depth + 1)[:-1] + _cubic(middle, bcd, cd, d, tolerance, depth + 1)


def _dash_paths(paths: list[Polyline], descriptor: str) -> list[Polyline]:
    match = re.fullmatch(r"\s*\[([^]]*)\]\s*([-+\d.eE]+)\s*", descriptor)
    if match is None:
        raise ValueError(f"Unsupported PDF dash descriptor: {descriptor!r}")
    pattern = [max(float(v) * PT_TO_MM, 0.01) for v in match[1].split()]
    if not pattern:
        return paths
    if len(pattern) % 2:
        pattern *= 2
    phase = float(match[2]) * PT_TO_MM % sum(pattern)
    result = []
    for path in paths:
        index, remaining_phase = 0, phase
        while remaining_phase >= pattern[index] - 1e-10:
            remaining_phase -= pattern[index]
            index = (index + 1) % len(pattern)
        remaining = pattern[index] - remaining_phase
        current: Polyline = []
        for a, b in zip(path, path[1:]):
            length = math.dist(a, b)
            if length < 1e-10:
                continue
            used = 0.0
            while used < length - 1e-10:
                portion = min(remaining, length - used)
                start = tuple(a[k] + (b[k] - a[k]) * used / length for k in (0, 1))
                end = tuple(a[k] + (b[k] - a[k]) * (used + portion) / length for k in (0, 1))
                if index % 2 == 0:
                    if not current:
                        current = [start]
                    current.append(end)
                used += portion
                remaining -= portion
                if remaining <= 1e-9:
                    if current:
                        result.append(current)
                        current = []
                    index = (index + 1) % len(pattern)
                    remaining = pattern[index]
        if current:
            result.append(current)
    return result


def _fill_small_shapes(paths: list[Polyline], spacing: float = 0.18) -> list[Polyline]:
    """Even-odd horizontal hatch for small filled dimension arrowheads."""
    vertices = [point for path in paths for point in path]
    if not vertices:
        return []
    x0, x1 = min(p[0] for p in vertices), max(p[0] for p in vertices)
    y0, y1 = min(p[1] for p in vertices), max(p[1] for p in vertices)
    if max(x1 - x0, y1 - y0) > 15:
        # Large filled backgrounds are not drawing strokes; their existing
        # outlines, if stroked, are retained by the caller.
        return []
    edges = []
    for path in paths:
        closed = path if path[0] == path[-1] else [*path, path[0]]
        edges.extend(zip(closed, closed[1:]))
    result = []
    y = y0 + spacing / 2
    while y < y1:
        crossings = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                           for a, b in edges if (a[1] <= y < b[1]) or (b[1] <= y < a[1]))
        for left, right in zip(crossings[::2], crossings[1::2]):
            if right - left > 1e-6:
                result.append([(left, y), (right, y)])
        y += spacing
    return result


def native_pdf_strokes(pdf: Path, *, page_index: int = 0, tolerance_mm: float = 0.02) -> list[Polyline]:
    """PDF paths only. PDF text stays with the existing single-line recognizer."""
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError("Curve tolerance must be positive millimeters")
    output = []
    with fitz.open(pdf) as document:
        page = document[page_index]

        def point(value) -> Point:
            p = fitz.Point(value) * page.rotation_matrix
            return p.x * PT_TO_MM, p.y * PT_TO_MM

        for drawing in page.get_drawings():
            chains: list[Polyline] = []
            current: Polyline = []
            for item in drawing["items"]:
                command = item[0]
                if command == "l":
                    piece = [point(item[1]), point(item[2])]
                elif command == "c":
                    piece = _cubic(*(point(p) for p in item[1:5]), tolerance_mm)
                elif command == "qu":
                    quad = item[1]
                    piece = [point(p) for p in (quad.ul, quad.ur, quad.lr, quad.ll, quad.ul)]
                elif command == "re":
                    rect = item[1]
                    piece = [point(p) for p in (rect.tl, rect.tr, rect.br, rect.bl, rect.tl)]
                else:
                    raise ValueError(f"Unsupported PDF path command {command!r}; refusing to drop geometry")
                if current and math.dist(current[-1], piece[0]) < 1e-7:
                    current.extend(piece[1:])
                else:
                    if len(current) > 1:
                        chains.append(current)
                    current = piece
            if len(current) > 1:
                if drawing.get("closePath") and math.dist(current[0], current[-1]) > 1e-7:
                    current.append(current[0])
                chains.append(current)
            color, fill = drawing.get("color"), drawing.get("fill")
            kind = drawing["type"]
            if "s" in kind and color is not None and min(color) < 0.98:
                output.extend(_dash_paths(chains, drawing.get("dashes") or "[] 0"))
            if "f" in kind and fill is not None and min(fill) < 0.98:
                output.extend(_fill_small_shapes(chains))
    if not output:
        raise ValueError("No native vector strokes in this PDF; use the image recognition route instead")
    return output
