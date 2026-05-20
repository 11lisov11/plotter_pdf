from __future__ import annotations

import argparse
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "_tmp" / "algorithm_baseline"
TOKEN_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


@dataclass(frozen=True)
class GcodeAlgorithmMetrics:
    path: str
    total_lines: int
    g0_moves: int
    g1_moves: int
    g2_moves: int
    g3_moves: int
    draw_moves: int
    travel_moves: int
    draw_length_mm: float
    travel_length_mm: float
    travel_to_draw_ratio: float
    short_segments_lt_035_mm: int
    tiny_strokes_lt_08_mm: int
    point_like_strokes: int
    pen_down_strokes: int
    z_cycles: int


def strip_comments(line: str) -> str:
    raw = str(line or "").split(";", 1)[0]
    out: list[str] = []
    depth = 0
    for ch in raw:
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip()


def values(tokens: list[tuple[str, str]], letter: str) -> list[float]:
    target = letter.upper()
    out: list[float] = []
    for axis, value in tokens:
        if axis.upper() != target:
            continue
        try:
            out.append(float(value))
        except ValueError:
            continue
    return out


def _arc_length(x0: float, y0: float, x1: float, y1: float, i: float, j: float, *, cw: bool) -> float:
    cx = x0 + i
    cy = y0 + j
    radius = math.hypot(x0 - cx, y0 - cy)
    if radius <= 1e-9:
        return math.hypot(x1 - x0, y1 - y0)
    if math.hypot(x1 - x0, y1 - y0) <= 1e-9:
        return 2.0 * math.pi * radius
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if cw:
        sweep = a0 - a1
        if sweep <= 0.0:
            sweep += 2.0 * math.pi
    else:
        sweep = a1 - a0
        if sweep <= 0.0:
            sweep += 2.0 * math.pi
    return abs(radius * sweep)


def analyze_gcode_file(path: Path, *, z_down_threshold: float = 1.0) -> GcodeAlgorithmMetrics:
    total_lines = 0
    motion_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    draw_moves = 0
    travel_moves = 0
    draw_length_mm = 0.0
    travel_length_mm = 0.0
    short_segments = 0
    stroke_lengths: list[float] = []
    current_stroke_mm = 0.0
    pen_down_strokes = 0
    z_cycles = 0

    cur_x: float | None = None
    cur_y: float | None = None
    cur_z: float | None = None
    last_motion: int | None = None
    abs_mode = True
    pen_down = False
    ever_saw_z = False

    def close_stroke() -> None:
        nonlocal current_stroke_mm
        if current_stroke_mm > 0.0:
            stroke_lengths.append(current_stroke_mm)
            current_stroke_mm = 0.0

    with Path(path).open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = strip_comments(raw)
            if not line:
                continue
            total_lines += 1
            tokens = TOKEN_RE.findall(line)
            if not tokens:
                continue

            for gval in values(tokens, "G"):
                if abs(gval - 90.0) <= 1e-9:
                    abs_mode = True
                    continue
                if abs(gval - 91.0) <= 1e-9:
                    abs_mode = False
                    continue
                rounded = int(round(gval))
                if abs(gval - rounded) <= 1e-9 and rounded in {0, 1, 2, 3}:
                    last_motion = rounded

            code = last_motion
            x_vals = values(tokens, "X")
            y_vals = values(tokens, "Y")
            z_vals = values(tokens, "Z")
            i_vals = values(tokens, "I")
            j_vals = values(tokens, "J")

            if z_vals:
                ever_saw_z = True
                z_raw = z_vals[-1]
                next_z = z_raw if (abs_mode or cur_z is None) else cur_z + z_raw
                next_pen_down = next_z > float(z_down_threshold)
                if next_pen_down and not pen_down:
                    z_cycles += 1
                if pen_down and not next_pen_down:
                    close_stroke()
                pen_down = next_pen_down
                cur_z = next_z

            has_xy = bool(x_vals or y_vals)
            if not has_xy or code not in {0, 1, 2, 3}:
                continue

            motion_counts[code] += 1
            x_raw = x_vals[-1] if x_vals else None
            y_raw = y_vals[-1] if y_vals else None
            next_x = cur_x if x_raw is None else (x_raw if (abs_mode or cur_x is None) else cur_x + x_raw)
            next_y = cur_y if y_raw is None else (y_raw if (abs_mode or cur_y is None) else cur_y + y_raw)

            if cur_x is None or cur_y is None or next_x is None or next_y is None:
                cur_x, cur_y = next_x, next_y
                continue

            if code in {2, 3} and i_vals and j_vals:
                seg_len = _arc_length(cur_x, cur_y, next_x, next_y, i_vals[-1], j_vals[-1], cw=(code == 2))
            else:
                seg_len = math.hypot(next_x - cur_x, next_y - cur_y)

            is_draw = code in {1, 2, 3} and (pen_down or not ever_saw_z)
            if is_draw:
                draw_moves += 1
                draw_length_mm += seg_len
                current_stroke_mm += seg_len
                if seg_len < 0.35 and seg_len > 1e-9:
                    short_segments += 1
                if current_stroke_mm == seg_len:
                    pen_down_strokes += 1
            elif code == 0:
                travel_moves += 1
                travel_length_mm += seg_len
                if pen_down:
                    close_stroke()
            cur_x, cur_y = next_x, next_y

    close_stroke()
    tiny_strokes = sum(1 for length in stroke_lengths if 0.0 < length < 0.8)
    point_like = sum(1 for length in stroke_lengths if 0.0 < length < 0.15)
    ratio = travel_length_mm / draw_length_mm if draw_length_mm > 1e-9 else 0.0
    return GcodeAlgorithmMetrics(
        path=str(Path(path)),
        total_lines=int(total_lines),
        g0_moves=int(motion_counts[0]),
        g1_moves=int(motion_counts[1]),
        g2_moves=int(motion_counts[2]),
        g3_moves=int(motion_counts[3]),
        draw_moves=int(draw_moves),
        travel_moves=int(travel_moves),
        draw_length_mm=round(draw_length_mm, 3),
        travel_length_mm=round(travel_length_mm, 3),
        travel_to_draw_ratio=round(ratio, 6),
        short_segments_lt_035_mm=int(short_segments),
        tiny_strokes_lt_08_mm=int(tiny_strokes),
        point_like_strokes=int(point_like),
        pen_down_strokes=int(pen_down_strokes),
        z_cycles=int(z_cycles),
    )


def collect_gcode_files(roots: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        root = Path(root)
        if root.is_file() and root.suffix.lower() in {".nc", ".gcode"}:
            found.append(root)
            continue
        if not root.exists() or not root.is_dir():
            continue
        for suffix in ("*.nc", "*.gcode"):
            found.extend(path for path in root.rglob(suffix) if path.is_file())
    return sorted(set(found), key=lambda p: str(p).casefold())


def summarize(metrics: list[GcodeAlgorithmMetrics]) -> dict[str, object]:
    return {
        "files": len(metrics),
        "total_lines": sum(item.total_lines for item in metrics),
        "draw_length_mm": round(sum(item.draw_length_mm for item in metrics), 3),
        "travel_length_mm": round(sum(item.travel_length_mm for item in metrics), 3),
        "pen_down_strokes": sum(item.pen_down_strokes for item in metrics),
        "z_cycles": sum(item.z_cycles for item in metrics),
        "short_segments_lt_035_mm": sum(item.short_segments_lt_035_mm for item in metrics),
        "tiny_strokes_lt_08_mm": sum(item.tiny_strokes_lt_08_mm for item in metrics),
        "point_like_strokes": sum(item.point_like_strokes for item in metrics),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure plotter G-code topology without modifying packages.")
    parser.add_argument("paths", nargs="*", help="Variant/package directories or .nc/.gcode files.")
    parser.add_argument("--root", action="append", default=[], help="Variant/package directory or .nc/.gcode file.")
    parser.add_argument("--output", default=None, help="Output JSON path. Defaults to _tmp/algorithm_baseline/<timestamp>.json.")
    parser.add_argument("--no-write", action="store_true", help="Print JSON only; do not write a report file.")
    args = parser.parse_args(argv)

    roots = [Path(item) for item in [*args.root, *args.paths]] if (args.root or args.paths) else [PROJECT_ROOT / "Компьютерная графика"]
    files = collect_gcode_files(roots)
    if not files:
        print(
            "No .nc/.gcode files found under: "
            + ", ".join(str(path) for path in roots)
        )
        return 2
    metrics = [analyze_gcode_file(path) for path in files]
    payload = {
        "generated_at_unix": int(time.time()),
        "roots": [str(path) for path in roots],
        "summary": summarize(metrics),
        "files": [asdict(item) for item in metrics],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.no_write:
        print(text)
        return 0
    output = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"algorithm_baseline_{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")
    print(f"saved: {output}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
