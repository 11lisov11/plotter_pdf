from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import plotter_pdf_drawer as backend  # noqa: E402
from src.plotter_backend.photo_to_plotter import (  # noqa: E402
    PhotoPlotConfig,
    PhotoPlotResult,
    WorkArea,
    generate_photo_plot,
    polylines_bounds,
)


MM_TO_PT = 72.0 / 25.4


def _parse_csv_floats(value: str | None, default: tuple[float, ...]) -> tuple[float, ...]:
    if value is None or not str(value).strip():
        return default
    out: list[float] = []
    for part in str(value).split(","):
        part = part.strip()
        if part:
            out.append(float(part))
    return tuple(out) if out else default


def _svg_point(x: float, y: float) -> str:
    return f"{float(x):.3f},{float(-y):.3f}"


def write_svg_preview(path: Path, result: PhotoPlotResult, work_area: WorkArea) -> None:
    width = float(work_area.max_x) - float(work_area.min_x)
    height = float(work_area.max_y) - float(work_area.min_y)
    x_shift = -float(work_area.min_x)
    y_shift = -float(work_area.max_y)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}mm" height="{height:.3f}mm" '
            f'viewBox="0 0 {width:.3f} {height:.3f}">'
        ),
        '<rect x="0" y="0" width="100%" height="100%" fill="white"/>',
        '<g fill="none" stroke="#111" stroke-width="0.22" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for poly in result.polylines:
        if len(poly) < 2:
            continue
        pts = " ".join(_svg_point(x + x_shift, y + y_shift) for x, y in poly)
        lines.append(f'<polyline points="{pts}"/>')
    lines.extend(["</g>", "</svg>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pdf_preview(path: Path, result: PhotoPlotResult, work_area: WorkArea) -> None:
    width_mm = float(work_area.max_x) - float(work_area.min_x)
    height_mm = float(work_area.max_y) - float(work_area.min_y)
    doc = fitz.open()
    page = doc.new_page(width=width_mm * MM_TO_PT, height=height_mm * MM_TO_PT)
    shape = page.new_shape()
    x_shift = -float(work_area.min_x)
    y_shift = -float(work_area.max_y)
    for poly in result.polylines:
        if len(poly) < 2:
            continue
        for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
            p0 = fitz.Point((x0 + x_shift) * MM_TO_PT, (-(y0 + y_shift)) * MM_TO_PT)
            p1 = fitz.Point((x1 + x_shift) * MM_TO_PT, (-(y1 + y_shift)) * MM_TO_PT)
            shape.draw_line(p0, p1)
    shape.finish(color=(0, 0, 0), width=0.22 * MM_TO_PT)
    shape.commit()
    doc.save(path)
    doc.close()


def _copy_source_image(image_path: Path, out_dir: Path) -> Path:
    suffix = image_path.suffix.lower() or ".png"
    dst = out_dir / f"source_image{suffix}"
    if image_path.resolve() != dst.resolve():
        shutil.copyfile(image_path, dst)
    return dst


def _write_summary(path: Path, result: PhotoPlotResult, gcode_stats: tuple[int, int, int, tuple[float, float, float, float]]) -> None:
    lines, draw_moves, travel_moves, bounds = gcode_stats
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "mode",
                "polylines",
                "points",
                "draw_length_mm",
                "gcode_lines",
                "draw_moves",
                "travel_moves",
                "bounds_min_x",
                "bounds_max_x",
                "bounds_min_y",
                "bounds_max_y",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "mode": result.mode,
                "polylines": result.stats["polyline_count"],
                "points": result.stats["point_count"],
                "draw_length_mm": result.stats["draw_length_mm"],
                "gcode_lines": lines,
                "draw_moves": draw_moves,
                "travel_moves": travel_moves,
                "bounds_min_x": f"{bounds[0]:.3f}",
                "bounds_max_x": f"{bounds[1]:.3f}",
                "bounds_min_y": f"{bounds[2]:.3f}",
                "bounds_max_y": f"{bounds[3]:.3f}",
            }
        )


def build_photo_plot_package(
    image_path: Path,
    out_dir: Path,
    config: PhotoPlotConfig,
    *,
    feed_travel: float,
    feed_draw: float,
) -> dict[str, Any]:
    work_area = WorkArea(
        min_x=float(backend.WORK_AREA_MIN_X),
        max_x=float(backend.WORK_AREA_MAX_X),
        min_y=float(backend.WORK_AREA_MIN_Y),
        max_y=float(backend.WORK_AREA_MAX_Y),
    )
    result = generate_photo_plot(image_path, config=config, work_area=work_area)
    if not result.polylines:
        raise RuntimeError("Photo route produced no drawable paths. Try lower thresholds or another mode.")

    out_dir.mkdir(parents=True, exist_ok=True)
    source_copy = _copy_source_image(image_path, out_dir)

    svg_path = out_dir / "photo_preview.svg"
    pdf_path = out_dir / "photo_preview.pdf"
    xy_path = out_dir / "photo_plot.xy.gcode"
    pen_path = out_dir / "photo_plot.pen.gcode"
    gcode_path = out_dir / "photo_plot.gcode"
    nc_path = out_dir / "photo_plot.nc"
    report_path = out_dir / "report.json"
    summary_path = out_dir / "summary.csv"

    write_svg_preview(svg_path, result, work_area)
    write_pdf_preview(pdf_path, result, work_area)
    backend.write_xy_gcode(xy_path, result.polylines, feed_travel, feed_draw)
    backend.apply_penlift(xy_path, pen_path, handwriting_mode=(config.mode == "scribble"), force_full_lift=(config.mode == "hatch"))
    backend.make_final_with_preamble(pen_path, gcode_path)
    nc_path.write_text(gcode_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

    preflight_ok, preflight_msg = backend.preflight_check_gcode(gcode_path, logger=lambda *_args: None)
    if not preflight_ok:
        raise RuntimeError(f"Generated photo G-code failed preflight: {preflight_msg}")

    gcode_stats = backend.summarize_gcode_file(gcode_path)
    _write_summary(summary_path, result, gcode_stats)
    route_bounds = polylines_bounds(result.polylines)
    report = {
        "kind": "photo_plot",
        "source_image": str(source_copy),
        "mode": result.mode,
        "source_size_px": result.source_size_px,
        "processed_size_px": result.processed_size_px,
        "target_size_mm": result.target_size_mm,
        "placement_bounds": result.placement_bounds,
        "route_bounds": [round(v, 3) for v in route_bounds],
        "stats": result.stats,
        "files": {
            "svg_preview": str(svg_path),
            "pdf_preview": str(pdf_path),
            "gcode": str(gcode_path),
            "nc": str(nc_path),
            "xy_gcode": str(xy_path),
            "pen_gcode": str(pen_path),
            "summary": str(summary_path),
        },
        "preflight": {"ok": preflight_ok, "message": preflight_msg},
        "references": [
            "https://github.com/plottertools/hatched",
            "https://github.com/abey79/vpype",
            "https://wiki.evilmadscientist.com/StippleGen",
            "https://github.com/SonarSonic/DrawingBotV3",
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a standalone photo-to-plotter package using hatch or continuous scribble rendering."
    )
    parser.add_argument("image", type=Path, help="Input photo/image file.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output package directory.")
    parser.add_argument("--mode", choices=["hatch", "scribble"], default="hatch")
    parser.add_argument("--margin-mm", type=float, default=5.0)
    parser.add_argument("--target-width-mm", type=float, default=None)
    parser.add_argument("--target-height-mm", type=float, default=None)
    parser.add_argument("--max-side-px", type=int, default=900)
    parser.add_argument("--contrast", type=float, default=1.12)
    parser.add_argument("--gamma", type=float, default=1.05)
    parser.add_argument("--blur-px", type=int, default=3)
    parser.add_argument("--hatch-spacing-mm", type=float, default=1.2)
    parser.add_argument("--hatch-levels", default=None, help="Comma-separated darkness thresholds, e.g. 0.18,0.34,0.50,0.66")
    parser.add_argument("--hatch-angles", default=None, help="Comma-separated hatch angles in degrees, e.g. 0,45,-45,90")
    parser.add_argument("--min-segment-mm", type=float, default=0.8)
    parser.add_argument("--merge-gap-mm", type=float, default=0.55)
    parser.add_argument("--no-edges", action="store_true", help="Disable Canny edge detail overlay.")
    parser.add_argument("--scribble-line-spacing-mm", type=float, default=1.25)
    parser.add_argument("--scribble-step-mm", type=float, default=0.75)
    parser.add_argument("--scribble-amplitude-mm", type=float, default=1.6)
    parser.add_argument("--feed-travel", type=float, default=float(backend.FEED_TRAVEL))
    parser.add_argument("--feed-draw", type=float, default=float(backend.FEED_DRAW))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    image = args.image.resolve()
    if not image.exists() or not image.is_file():
        parser.error(f"image file not found: {image}")
    out_dir = args.out_dir
    if out_dir is None:
        out_dir = PROJECT_ROOT / "_plotter_jobs" / f"{image.stem}_photo_plot_pack"
    config = PhotoPlotConfig(
        mode=args.mode,
        margin_mm=args.margin_mm,
        target_width_mm=args.target_width_mm,
        target_height_mm=args.target_height_mm,
        max_side_px=args.max_side_px,
        contrast=args.contrast,
        gamma=args.gamma,
        blur_px=args.blur_px,
        hatch_spacing_mm=args.hatch_spacing_mm,
        hatch_levels=_parse_csv_floats(args.hatch_levels, PhotoPlotConfig().hatch_levels),
        hatch_angles_deg=_parse_csv_floats(args.hatch_angles, PhotoPlotConfig().hatch_angles_deg),
        min_segment_mm=args.min_segment_mm,
        merge_gap_mm=args.merge_gap_mm,
        edge_enabled=not bool(args.no_edges),
        scribble_line_spacing_mm=args.scribble_line_spacing_mm,
        scribble_step_mm=args.scribble_step_mm,
        scribble_amplitude_mm=args.scribble_amplitude_mm,
    )
    report = build_photo_plot_package(
        image,
        out_dir.resolve(),
        config,
        feed_travel=float(args.feed_travel),
        feed_draw=float(args.feed_draw),
    )
    print(json.dumps({"ok": True, "out_dir": str(out_dir.resolve()), "gcode": report["files"]["gcode"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

