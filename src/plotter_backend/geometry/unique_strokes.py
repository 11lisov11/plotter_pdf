"""Remove retracing on the writer's coordinate grid, without fuzzy snapping.

Direction-independent integer line keys handle different subdivisions and
partial overlap. Distinct parallel lines and isolated crossings stay distinct.
The first traversal owns each interval; source order/direction are preserved.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Iterable

Point = tuple[float, float]


def unique_strokes(polylines: Iterable[Iterable[Point]], *, precision: int = 3) -> list[list[Point]]:
    if not isinstance(precision, int) or not 0 <= precision <= 8:
        raise ValueError("Coordinate precision must be between 0 and 8")
    scale = 10 ** precision
    covered: dict[tuple[int, int, int], list[tuple[int, int]]] = {}
    result: list[list[Point]] = []

    def quantize(point):
        values = tuple(float(v) for v in point)
        if len(values) != 2 or not all(math.isfinite(v) for v in values):
            raise ValueError("Expected finite XY coordinates")
        # Match fixed-decimal NC serialization, including halfway rounding.
        return tuple(int(round(float(f"{v:.{precision}f}") * scale)) for v in values)

    for polyline in polylines:
        points = [quantize(p) for p in polyline]
        current: list[tuple[int, int]] = []

        def flush():
            nonlocal current
            if len(current) > 1:
                result.append([(x / scale, y / scale) for x, y in current])
            current = []

        for a, b in zip(points, points[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            divisor = math.gcd(abs(dx), abs(dy))
            if not divisor:
                continue
            ux, uy = dx // divisor, dy // divisor
            if ux < 0 or (ux == 0 and uy < 0):
                ux, uy = -ux, -uy
            key = (ux, uy, ux * a[1] - uy * a[0])
            ta, tb = ux * a[0] + uy * a[1], ux * b[0] + uy * b[1]
            lo, hi = sorted((ta, tb))
            intervals = covered.setdefault(key, [])
            start = bisect_left(intervals, (lo,))
            if start and intervals[start - 1][1] >= lo:
                start -= 1
            cursor = lo
            pieces = []
            for left, right in intervals[start:]:
                if left >= hi:
                    break
                if right <= cursor:
                    continue
                if left > cursor:
                    pieces.append((cursor, min(left, hi)))
                cursor = max(cursor, right)
                if cursor >= hi:
                    break
            if cursor < hi:
                pieces.append((cursor, hi))
            if not pieces:
                flush()
                continue

            # Store the union, not just identical endpoint pairs.
            stop = start
            merged_lo, merged_hi = lo, hi
            while stop < len(intervals) and intervals[stop][0] <= merged_hi:
                merged_lo = min(merged_lo, intervals[stop][0])
                merged_hi = max(merged_hi, intervals[stop][1])
                stop += 1
            intervals[start:stop] = [(merged_lo, merged_hi)]

            norm2 = ux * ux + uy * uy

            def at(t):
                # All interval endpoints belong to this integer lattice line.
                step, remainder = divmod(t - ta, norm2)
                if remainder:
                    raise ValueError("Invalid integer line interval")
                return a[0] + step * ux, a[1] + step * uy

            directed = pieces if ta < tb else [(right, left) for left, right in reversed(pieces)]
            for begin, end in directed:
                first, last = at(begin), at(end)
                if current and current[-1] != first:
                    flush()
                if not current:
                    current = [first]
                current.append(last)
                if last != b:
                    # Never join across an interval removed as already drawn.
                    flush()
        flush()
    return result
