"""Restore exact stroke connectivity before planning pen-down trails.

Only existing ink is used. In particular, a close endpoint is not enough to
join two strokes: the endpoint must lie exactly on the serialized segment.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .stroke_routing import optimize_pen_paths


def _cells_on_segment(a, b, size):
    """Integer supercover, including cells touched at a grid corner."""
    x, y = a[0] // size, a[1] // size
    end_x, end_y = b[0] // size, b[1] // size
    yield x, y
    dx, dy = b[0] - a[0], b[1] - a[1]
    ax, ay = abs(dx), abs(dy)
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    nx = ((x + 1) * size - a[0]) if dx > 0 else (a[0] - x * size)
    ny = ((y + 1) * size - a[1]) if dy > 0 else (a[1] - y * size)
    while (x, y) != (end_x, end_y):
        # An axis already in its final cell must not advance past the end.
        if x == end_x:
            y += sy
            ny += size
        elif y == end_y:
            x += sx
            nx += size
        else:
            left, right = nx * ay, ny * ax
            if left < right:
                x += sx
                nx += size
            elif left > right:
                y += sy
                ny += size
            else:
                yield x + sx, y
                yield x, y + sy
                x += sx
                y += sy
                nx += size
                ny += size
        yield x, y


def _integer_paths(paths, precision):
    if not isinstance(precision, int) or not 0 <= precision <= 8:
        raise ValueError("Coordinate precision must be between 0 and 8")
    scale = 10 ** precision
    result = []
    for path in paths:
        points = []
        for point in path:
            values = tuple(float(value) for value in point)
            if len(values) != 2 or not all(math.isfinite(v) for v in values):
                raise ValueError("Expected finite XY coordinates")
            q = tuple(int(round(float(f"{v:.{precision}f}") * scale)) for v in values)
            if not points or points[-1] != q:
                points.append(q)
        if len(points) > 1:
            result.append(points)
    return result, scale


def split_touching_strokes(paths, *, precision=3):
    """Expose existing junctions hidden in the interior of a long segment.

    Splitting preserves segment coverage exactly, unlike fuzzy endpoint
    stitching. No crossing coordinates or short gap connectors are invented.
    """
    paths, scale = _integer_paths(paths, precision)
    size = max(1, 2 * scale)
    cells = defaultdict(list)
    for point in sorted({point for path in paths for point in path}):
        cells[point[0] // size, point[1] // size].append(point)
    output = []
    for path in paths:
        current = [path[0]]
        for a, b in zip(path, path[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            norm2 = dx * dx + dy * dy
            inside = set()
            for cell in _cells_on_segment(a, b, size):
                for p in cells.get(cell, ()):
                    px, py = p[0] - a[0], p[1] - a[1]
                    if px * dy == py * dx:
                        distance = px * dx + py * dy
                        if 0 < distance < norm2:
                            inside.add((distance, p))
            current.extend(p for _, p in sorted(inside))
            current.append(b)
        output.append([(x / scale, y / scale) for x, y in current])
    return output


def coalesce_straight_runs(paths, *, precision=3):
    """Remove redundant G1 vertices, never corners, reversals or curve bends."""
    paths, scale = _integer_paths(paths, precision)
    output = []
    for path in paths:
        current = []
        for c in path:
            while len(current) > 1:
                a, b = current[-2:]
                ab = (b[0] - a[0], b[1] - a[1])
                bc = (c[0] - b[0], c[1] - b[1])
                if ab[0] * bc[1] != ab[1] * bc[0]:
                    break
                if ab[0] * bc[0] + ab[1] * bc[1] <= 0:
                    break
                current.pop()
            current.append(c)
        output.append([(x / scale, y / scale) for x, y in current])
    return output


def optimize_drawing_paths(paths, *, precision=3, **motion):
    connected = split_touching_strokes(paths, precision=precision)
    routed = optimize_pen_paths(connected, precision=precision, **motion)
    # Junctions must remain explicit until graph traversal is complete. They
    # can then be removed within a straight pen-down run, not before routing.
    return coalesce_straight_runs(routed, precision=precision)
