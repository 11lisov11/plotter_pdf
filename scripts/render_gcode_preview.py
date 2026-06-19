from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Iterable

import fitz


COMMAND_RE = re.compile(r"^\s*(G0|G00|G1|G01|G2|G02|G3|G03)\b", re.IGNORECASE)
WORD_RE = re.compile(r"([A-Z])(-?\d+(?:\.\d+)?)", re.IGNORECASE)


def _clean_line(line: str) -> str:
    return line.split(";", 1)[0].strip().upper()


def _numbers(line: str) -> dict[str, float]:
    return {key.upper(): float(value) for key, value in WORD_RE.findall(line)}


def _transform_point(
    x: float,
    y: float,
    *,
    transform: str,
    work_min_x: float,
    work_min_y: float,
    work_width: float,
    work_height: float,
) -> tuple[float, float]:
    if transform == "machine":
        return x, y
    if transform == "plotter_xy_mirror":
        return work_width - (x - work_min_x), work_min_y - y
    if transform == "plotter_y_mirror":
        return x - work_min_x, work_min_y - y
    if transform == "plotter_x_mirror":
        return work_width - (x - work_min_x), y
    raise ValueError(f"Unknown transform: {transform}")


def parse_draw_segments(
    gcode_path: Path,
    *,
    transform: str,
    work_min_x: float,
    work_min_y: float,
    work_width: float,
    work_height: float,
) -> tuple[list[tuple[float, float, float, float]], list[tuple[float, float]]]:
    x: float | None = None
    y: float | None = None
    pen_down = False
    saw_z = False
    segments: list[tuple[float, float, float, float]] = []
    points: list[tuple[float, float]] = []

    for raw in gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = _clean_line(raw)
        if not line:
            continue

        values = _numbers(line)
        if "Z" in values:
            saw_z = True
            pen_down = values["Z"] > 1.0

        match = COMMAND_RE.match(line)
        if not match:
            continue

        command = match.group(1).upper()
        nx = values.get("X", x)
        ny = values.get("Y", y)
        if nx is None or ny is None:
            x, y = nx, ny
            continue

        should_draw = command in {"G1", "G01", "G2", "G02", "G3", "G03"} and (pen_down or not saw_z)
        if should_draw and x is not None and y is not None:
            if abs(nx - x) > 1e-9 or abs(ny - y) > 1e-9:
                x1, y1 = _transform_point(
                    x,
                    y,
                    transform=transform,
                    work_min_x=work_min_x,
                    work_min_y=work_min_y,
                    work_width=work_width,
                    work_height=work_height,
                )
                x2, y2 = _transform_point(
                    nx,
                    ny,
                    transform=transform,
                    work_min_x=work_min_x,
                    work_min_y=work_min_y,
                    work_width=work_width,
                    work_height=work_height,
                )
                segments.append((x1, y1, x2, y2))
                points.extend([(x1, y1), (x2, y2)])

        x, y = nx, ny

    return segments, points


def _bounds(points: Iterable[tuple[float, float]]) -> tuple[float, float, float, float]:
    pts = list(points)
    if not pts:
        return 0.0, 0.0, 0.0, 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _draw_preview(
    *,
    segments: list[tuple[float, float, float, float]],
    output_pdf: Path,
    output_png: Path,
    title: str,
    work_width: float,
    work_height: float,
    points: list[tuple[float, float]],
) -> None:
    work_bounds = (0.0, -work_height, work_width, 0.0)
    data_bounds = _bounds(points)
    min_x = min(work_bounds[0], data_bounds[0]) - 8.0
    min_y = min(work_bounds[1], data_bounds[1]) - 8.0
    max_x = max(work_bounds[2], data_bounds[2]) + 8.0
    max_y = max(work_bounds[3], data_bounds[3]) + 8.0

    scale = 2.4
    margin = 24.0
    width = (max_x - min_x) * scale + margin * 2.0
    height = (max_y - min_y) * scale + margin * 2.0

    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(0, 0, width, height), color=(1, 1, 1), fill=(1, 1, 1))

    def point(x: float, y: float) -> fitz.Point:
        return fitz.Point(margin + (x - min_x) * scale, margin + (max_y - y) * scale)

    page.draw_rect(
        fitz.Rect(point(0.0, 0.0), point(work_width, -work_height)),
        color=(1.0, 0.35, 0.0),
        width=0.8,
        dashes="[4 3] 0",
    )
    for x1, y1, x2, y2 in segments:
        page.draw_line(point(x1, y1), point(x2, y2), color=(0, 0, 0), width=0.34)

    page.insert_text(fitz.Point(24, 16), title, fontsize=8, color=(0.1, 0.2, 0.8))
    page.insert_text(
        point(2.0, -work_height + 7.0),
        f"work area {work_width:g}x{work_height:g} mm",
        fontsize=7,
        color=(1.0, 0.35, 0.0),
    )

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_pdf)
    page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(output_png)
    doc.close()


def render_gcode_preview(
    gcode_path: Path,
    *,
    output_prefix: Path | None,
    transform: str,
    work_width: float,
    work_height: float,
    work_min_x: float = 0.0,
    work_min_y: float = -285.0,
) -> tuple[Path, Path, tuple[float, float, float, float], int]:
    if output_prefix is None:
        output_prefix = gcode_path.with_suffix("")
    output_pdf = output_prefix.with_name(output_prefix.name + f"_{transform}_preview.pdf")
    output_png = output_prefix.with_name(output_prefix.name + f"_{transform}_preview.png")

    segments, points = parse_draw_segments(
        gcode_path,
        transform=transform,
        work_min_x=work_min_x,
        work_min_y=work_min_y,
        work_width=work_width,
        work_height=work_height,
    )
    bounds = _bounds(points)
    title = f"{gcode_path.name} | transform={transform}"
    _draw_preview(
        segments=segments,
        output_pdf=output_pdf,
        output_png=output_png,
        title=title,
        work_width=work_width,
        work_height=work_height,
        points=points,
    )
    return output_pdf, output_png, bounds, len(segments)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render final G-code to PDF/PNG before sending it to a plotter.")
    parser.add_argument("gcode", type=Path)
    parser.add_argument("--output-prefix", type=Path, default=None)
    parser.add_argument(
        "--paper-transform",
        choices=("machine", "plotter_xy_mirror", "plotter_y_mirror", "plotter_x_mirror"),
        default="plotter_y_mirror",
        help=(
            "machine = raw G-code coordinates; plotter_y_mirror = observed paper orientation "
            "for the current plotter setup; plotter_xy_mirror / plotter_x_mirror are diagnostics."
        ),
    )
    parser.add_argument("--work-width", type=float, default=180.0)
    parser.add_argument("--work-height", type=float, default=280.0)
    parser.add_argument("--work-min-x", type=float, default=0.0)
    parser.add_argument(
        "--work-min-y",
        type=float,
        default=-285.0,
        help="Machine Y coordinate of the top calibration edge. Default matches corner calibration: -285.",
    )
    args = parser.parse_args()

    output_pdf, output_png, bounds, segment_count = render_gcode_preview(
        args.gcode,
        output_prefix=args.output_prefix,
        transform=args.paper_transform,
        work_width=args.work_width,
        work_height=args.work_height,
        work_min_x=args.work_min_x,
        work_min_y=args.work_min_y,
    )
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    outside = (
        bounds[0] < -1e-6
        or bounds[2] > args.work_width + 1e-6
        or bounds[1] < -args.work_height - 1e-6
        or bounds[3] > 1e-6
    )

    print(f"segments={segment_count}")
    print(f"bounds=x({bounds[0]:.3f},{bounds[2]:.3f}) y({bounds[1]:.3f},{bounds[3]:.3f}) size=({width:.3f},{height:.3f})")
    print(f"outside_work_area={'yes' if outside else 'no'}")
    print(f"pdf={output_pdf}")
    print(f"png={output_png}")
    return 2 if outside else 0


if __name__ == "__main__":
    raise SystemExit(main())
