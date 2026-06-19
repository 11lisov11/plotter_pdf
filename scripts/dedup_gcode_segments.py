from __future__ import annotations

import argparse
from pathlib import Path

from stitch_gcode_polylines import nearest_order, read_draw_polylines, write_gcode


def _segment_key(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    precision: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    first = (round(a[0], precision), round(a[1], precision))
    second = (round(b[0], precision), round(b[1], precision))
    if second < first:
        first, second = second, first
    return first, second


def dedup_segments(
    polylines: list[list[tuple[float, float]]],
    *,
    precision: int,
) -> tuple[list[list[tuple[float, float]]], int, int]:
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    output: list[list[tuple[float, float]]] = []
    kept = 0
    dropped = 0

    for polyline in polylines:
        current: list[tuple[float, float]] = []
        for start, end in zip(polyline, polyline[1:]):
            key = _segment_key(start, end, precision=precision)
            if key in seen:
                dropped += 1
                if len(current) >= 2:
                    output.append(current)
                current = []
                continue
            seen.add(key)
            kept += 1
            if not current:
                current = [start, end]
            elif current[-1] == start:
                current.append(end)
            else:
                if len(current) >= 2:
                    output.append(current)
                current = [start, end]
        if len(current) >= 2:
            output.append(current)

    return output, kept, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove exactly duplicated G-code draw segments.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--precision", type=int, default=2, help="Coordinate rounding precision for duplicate detection.")
    parser.add_argument("--feed-travel", type=float, default=15000.0)
    parser.add_argument("--feed-draw", type=float, default=2200.0)
    parser.add_argument("--z-down", type=float, default=11.9)
    args = parser.parse_args()

    source = read_draw_polylines(args.input)
    deduped, kept, dropped = dedup_segments(source, precision=args.precision)
    ordered = nearest_order(deduped)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_gcode(
        args.output,
        ordered,
        feed_travel=args.feed_travel,
        feed_draw=args.feed_draw,
        z_down=args.z_down,
    )
    args.output.with_suffix(".gcode").write_text(args.output.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"source_polylines={len(source)}")
    print(f"deduped_polylines={len(ordered)}")
    print(f"kept_segments={kept}")
    print(f"dropped_duplicate_segments={dropped}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
