from __future__ import annotations

import argparse
import math
import re
from pathlib import Path


COMMAND_RE = re.compile(r"^\s*(G0|G00|G1|G01|G2|G02|G3|G03)\b", re.IGNORECASE)
WORD_RE = re.compile(r"([A-Z])(-?\d+(?:\.\d+)?)", re.IGNORECASE)


def _clean_line(line: str) -> str:
    return line.split(";", 1)[0].strip().upper()


def _words(line: str) -> dict[str, float]:
    return {key.upper(): float(value) for key, value in WORD_RE.findall(line)}


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def read_draw_polylines(path: Path) -> list[list[tuple[float, float]]]:
    x: float | None = None
    y: float | None = None
    pen_down = False
    current: list[tuple[float, float]] = []
    polylines: list[list[tuple[float, float]]] = []

    def finish() -> None:
        nonlocal current
        if len(current) >= 2:
            cleaned = [current[0]]
            for point in current[1:]:
                if _dist(cleaned[-1], point) > 0.005:
                    cleaned.append(point)
            if len(cleaned) >= 2:
                polylines.append(cleaned)
        current = []

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        values = _words(line)

        if "Z" in values:
            next_pen_down = values["Z"] > 1.0
            if pen_down and not next_pen_down:
                finish()
            pen_down = next_pen_down

        match = COMMAND_RE.match(line)
        if not match:
            continue
        command = match.group(1).upper()
        nx = values.get("X", x)
        ny = values.get("Y", y)
        if nx is None or ny is None:
            x, y = nx, ny
            continue

        if command in {"G0", "G00"} and pen_down:
            finish()
        elif command in {"G1", "G01", "G2", "G02", "G3", "G03"} and pen_down and x is not None and y is not None:
            if _dist((x, y), (nx, ny)) > 0.005:
                if not current:
                    current = [(x, y), (nx, ny)]
                else:
                    current.append((nx, ny))
        x, y = nx, ny

    finish()
    return polylines


def stitch_polylines(
    polylines: list[list[tuple[float, float]]],
    *,
    eps: float,
) -> list[list[tuple[float, float]]]:
    remaining = [list(poly) for poly in polylines if len(poly) >= 2]
    stitched: list[list[tuple[float, float]]] = []

    while remaining:
        poly = remaining.pop()
        changed = True
        while changed:
            changed = False
            start = poly[0]
            end = poly[-1]
            best_index: int | None = None
            best_mode: str | None = None
            best_dist = eps
            for index, other in enumerate(remaining):
                candidates = (
                    ("end_start", _dist(end, other[0])),
                    ("end_end", _dist(end, other[-1])),
                    ("start_end", _dist(start, other[-1])),
                    ("start_start", _dist(start, other[0])),
                )
                for mode, distance in candidates:
                    if distance <= best_dist:
                        best_index = index
                        best_mode = mode
                        best_dist = distance
            if best_index is None or best_mode is None:
                continue

            other = remaining.pop(best_index)
            if best_mode == "end_start":
                poly.extend(other[1:])
            elif best_mode == "end_end":
                poly.extend(reversed(other[:-1]))
            elif best_mode == "start_end":
                poly = other[:-1] + poly
            elif best_mode == "start_start":
                poly = list(reversed(other[1:])) + poly
            changed = True
        stitched.append(poly)

    return stitched


def nearest_order(polylines: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    remaining = [list(poly) for poly in polylines if len(poly) >= 2]
    ordered: list[list[tuple[float, float]]] = []
    position = (0.0, 0.0)
    while remaining:
        best_index = 0
        best_reverse = False
        best_distance = float("inf")
        for index, poly in enumerate(remaining):
            for reverse, endpoint in ((False, poly[0]), (True, poly[-1])):
                distance = _dist(position, endpoint)
                if distance < best_distance:
                    best_index = index
                    best_reverse = reverse
                    best_distance = distance
        poly = remaining.pop(best_index)
        if best_reverse:
            poly = list(reversed(poly))
        ordered.append(poly)
        position = poly[-1]
    return ordered


def write_gcode(
    path: Path,
    polylines: list[list[tuple[float, float]]],
    *,
    feed_travel: float,
    feed_draw: float,
    z_down: float,
) -> None:
    lines = [
        "$X",
        "$1=255",
        "G21",
        "G90",
        "G92 Z4.0000",
        "G0 Z0.0000 F800.0",
        "G4 P0.06",
        "G92 Z0.0000",
        "G0 Z0.0000 F800.0",
        "G21",
        "G90",
        "G17",
        "G91.1",
        "G0 Z0.0000",
    ]
    for polyline in polylines:
        sx, sy = polyline[0]
        lines.append(f"G0 X{sx:.3f} Y{sy:.3f} F{feed_travel:.1f}")
        lines.append(f"G1 Z{z_down:.4f} F2500.0")
        lines.append("G4 P0.02")
        first = True
        for x, y in polyline[1:]:
            if first:
                lines.append(f"G1 X{x:.3f} Y{y:.3f} F{feed_draw:.1f}")
                first = False
            else:
                lines.append(f"G1 X{x:.3f} Y{y:.3f}")
        lines.append("G0 Z0.0000 F2500.0")
        lines.append("G4 P0.02")
    lines.extend(["G0 X0.000 Y0.000 F15000.0", "G0 Z0.0000 F800.0"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stitch fragmented G-code draw polylines by matching endpoints.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--eps", type=float, default=0.05)
    parser.add_argument("--feed-travel", type=float, default=15000.0)
    parser.add_argument("--feed-draw", type=float, default=2200.0)
    parser.add_argument("--z-down", type=float, default=11.9)
    args = parser.parse_args()

    source = read_draw_polylines(args.input)
    stitched = stitch_polylines(source, eps=args.eps)
    ordered = nearest_order(stitched)
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
    print(f"stitched_polylines={len(stitched)}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
