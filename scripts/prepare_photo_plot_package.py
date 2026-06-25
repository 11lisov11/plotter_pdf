from __future__ import annotations

import argparse
import csv
import json
import math
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
    classic_photo_quality_preset,
    generate_photo_plot,
    hatch_photo_quality_preset,
    polylines_bounds,
    sketch_photo_quality_preset,
)


MM_TO_PT = 72.0 / 25.4
Polyline = list[tuple[float, float]]


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


def _strip_gcode_comments(line: str) -> str:
    if ";" in line:
        line = line.split(";", 1)[0]
    while "(" in line and ")" in line and line.index("(") < line.index(")"):
        start = line.index("(")
        end = line.index(")", start)
        line = line[:start] + line[end + 1 :]
    return line.strip()


def _parse_gcode_words(line: str) -> dict[str, float | str]:
    words: dict[str, float | str] = {}
    for raw in line.replace("\t", " ").split():
        if not raw:
            continue
        key = raw[0].upper()
        value = raw[1:]
        if key in {"G", "M"}:
            words[key] = f"{key}{value}"
            continue
        try:
            words[key] = float(value)
        except ValueError:
            continue
    return words


def _pen_is_down(z: float | None) -> bool:
    if z is None:
        return False
    z_up = float(backend.Z_UP)
    z_down = float(backend.Z_DOWN)
    return abs(float(z) - z_down) <= abs(float(z) - z_up)


def _arc_points(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    *,
    clockwise: bool,
    max_step_mm: float = 1.0,
) -> list[tuple[float, float]]:
    sx, sy = start
    ex, ey = end
    cx, cy = center
    radius = math.hypot(sx - cx, sy - cy)
    if radius <= 1e-9:
        return [end]
    a0 = math.atan2(sy - cy, sx - cx)
    a1 = math.atan2(ey - cy, ex - cx)
    if clockwise:
        sweep = a1 - a0
        while sweep >= -1e-9:
            sweep -= 2.0 * math.pi
    else:
        sweep = a1 - a0
        while sweep <= 1e-9:
            sweep += 2.0 * math.pi
    if math.hypot(ex - sx, ey - sy) <= 1e-6:
        sweep = -2.0 * math.pi if clockwise else 2.0 * math.pi
    steps = max(8, int(math.ceil(abs(sweep) * radius / max(0.2, float(max_step_mm)))))
    points: list[tuple[float, float]] = []
    for idx in range(1, steps + 1):
        a = a0 + sweep * (idx / steps)
        points.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
    return points


def gcode_draw_polylines(gcode_path: Path) -> list[Polyline]:
    """Reconstruct drawn XY strokes from final pen-lift G-code for exact preview."""
    polylines: list[Polyline] = []
    current: Polyline | None = None
    x = y = z = None
    motion = "G0"
    absolute_xy = True
    for raw in gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = _strip_gcode_comments(raw)
        if not line or line.startswith("$"):
            continue
        words = _parse_gcode_words(line)
        g_word = words.get("G")
        code = str(g_word).upper() if g_word is not None else None
        if code in {"G90", "G91"}:
            absolute_xy = code == "G90"
            continue
        if code in {"G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"}:
            if code in {"G0", "G00"}:
                motion = "G0"
            elif code in {"G1", "G01"}:
                motion = "G1"
            elif code in {"G2", "G02"}:
                motion = "G2"
            elif code in {"G3", "G03"}:
                motion = "G3"
        elif code is not None or not any(axis in words for axis in ("X", "Y", "Z")):
            continue

        old_x, old_y, old_z = x, y, z
        next_x = x
        next_y = y
        next_z = z
        if "X" in words:
            vx = float(words["X"])
            next_x = vx if absolute_xy or x is None else x + vx
        if "Y" in words:
            vy = float(words["Y"])
            next_y = vy if absolute_xy or y is None else y + vy
        if "Z" in words:
            vz = float(words["Z"])
            next_z = vz if absolute_xy or z is None else z + vz

        was_down = _pen_is_down(old_z)
        xy_changed = old_x is not None and old_y is not None and next_x is not None and next_y is not None and (
            abs(next_x - old_x) > 1e-9 or abs(next_y - old_y) > 1e-9
        )
        draw_motion = motion in {"G1", "G2", "G3"}
        if was_down and xy_changed and draw_motion:
            if current is None:
                current = [(float(old_x), float(old_y))]
            if motion in {"G2", "G3"} and "I" in words and "J" in words:
                center = (float(old_x) + float(words["I"]), float(old_y) + float(words["J"]))
                current.extend(
                    _arc_points(
                        (float(old_x), float(old_y)),
                        (float(next_x), float(next_y)),
                        center,
                        clockwise=(motion == "G2"),
                    )
                )
            else:
                current.append((float(next_x), float(next_y)))

        x, y, z = next_x, next_y, next_z
        is_down = _pen_is_down(z)
        if is_down and not was_down and x is not None and y is not None:
            current = [(float(x), float(y))]
        elif was_down and not is_down:
            if current is not None and len(current) >= 2:
                polylines.append(current)
            current = None

    if current is not None and len(current) >= 2:
        polylines.append(current)
    return polylines


def write_svg_polylines(path: Path, polylines: list[Polyline], work_area: WorkArea) -> None:
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
    for poly in polylines:
        if len(poly) < 2:
            continue
        pts = " ".join(_svg_point(x + x_shift, y + y_shift) for x, y in poly)
        lines.append(f'<polyline points="{pts}"/>')
    lines.extend(["</g>", "</svg>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_svg_preview(path: Path, result: PhotoPlotResult, work_area: WorkArea) -> None:
    write_svg_polylines(path, result.polylines, work_area)


def write_pdf_polylines(path: Path, polylines: list[Polyline], work_area: WorkArea) -> None:
    width_mm = float(work_area.max_x) - float(work_area.min_x)
    height_mm = float(work_area.max_y) - float(work_area.min_y)
    doc = fitz.open()
    page = doc.new_page(width=width_mm * MM_TO_PT, height=height_mm * MM_TO_PT)
    shape = page.new_shape()
    x_shift = -float(work_area.min_x)
    y_shift = -float(work_area.max_y)
    for poly in polylines:
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


def write_pdf_preview(path: Path, result: PhotoPlotResult, work_area: WorkArea) -> None:
    write_pdf_polylines(path, result.polylines, work_area)


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
    gcode_svg_path = out_dir / "photo_gcode_preview.svg"
    gcode_pdf_path = out_dir / "photo_gcode_preview.pdf"
    xy_path = out_dir / "photo_plot.xy.gcode"
    pen_path = out_dir / "photo_plot.pen.gcode"
    gcode_path = out_dir / "photo_plot.gcode"
    nc_path = out_dir / "photo_plot.nc"
    report_path = out_dir / "report.json"
    summary_path = out_dir / "summary.csv"

    write_svg_preview(svg_path, result, work_area)
    write_pdf_preview(pdf_path, result, work_area)
    backend.write_xy_gcode(xy_path, result.polylines, feed_travel, feed_draw, micro_stroke_feed=False)
    # Photo routes are not handwriting: short-travel merge creates visible connector
    # strokes across faces/backgrounds. Keep every inter-path travel as a true pen-up move.
    backend.apply_penlift(xy_path, pen_path, handwriting_mode=False, force_full_lift=True)
    backend.make_final_with_preamble(pen_path, gcode_path)
    nc_path.write_text(gcode_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

    gcode_polylines = gcode_draw_polylines(gcode_path)
    write_svg_polylines(gcode_svg_path, gcode_polylines, work_area)
    write_pdf_polylines(gcode_pdf_path, gcode_polylines, work_area)

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
            "gcode_svg_preview": str(gcode_svg_path),
            "gcode_pdf_preview": str(gcode_pdf_path),
            "gcode": str(gcode_path),
            "nc": str(nc_path),
            "xy_gcode": str(xy_path),
            "pen_gcode": str(pen_path),
            "summary": str(summary_path),
        },
        "preflight": {"ok": preflight_ok, "message": preflight_msg},
        "references": [
            "https://github.com/LingDong-/linedraw",
            "https://jwalk.io/projects/PySquiggleDraw.html",
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
        description="Prepare a standalone photo-to-plotter package using pencil sketch, classic, hatch, scribble, or portrait rendering."
    )
    parser.add_argument("image", type=Path, help="Input photo/image file.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output package directory.")
    parser.add_argument("--mode", choices=["sketch", "classic", "hatch", "scribble", "portrait"], default=PhotoPlotConfig().mode)
    parser.add_argument(
        "--photo-quality",
        choices=["fast", "normal", "detailed"],
        default="normal",
        help="Photo quality preset: fast is shortest, normal is balanced, detailed keeps more pencil detail.",
    )
    parser.add_argument("--margin-mm", type=float, default=5.0)
    parser.add_argument("--target-width-mm", type=float, default=None)
    parser.add_argument("--target-height-mm", type=float, default=None)
    parser.add_argument("--max-side-px", type=int, default=None)
    parser.add_argument("--contrast", type=float, default=1.12)
    parser.add_argument("--gamma", type=float, default=1.05)
    parser.add_argument("--blur-px", type=int, default=3)
    parser.add_argument("--hatch-spacing-mm", type=float, default=None)
    parser.add_argument("--hatch-levels", default=None, help="Comma-separated darkness thresholds, e.g. 0.18,0.34,0.50,0.66")
    parser.add_argument("--hatch-angles", default=None, help="Comma-separated hatch angles in degrees, e.g. 0,45,-45,90")
    parser.add_argument("--classic-spacing-mm", type=float, default=None)
    parser.add_argument("--classic-levels", default=None, help="Comma-separated classic darkness thresholds, e.g. 0.16,0.28,0.40,0.54,0.68,0.80")
    parser.add_argument("--classic-angles", default=None, help="Comma-separated classic hatch angles in degrees, e.g. 0,45,-45,90,22.5,-22.5")
    parser.add_argument("--classic-smooth-sigma-px", type=float, default=None)
    parser.add_argument("--sketch-stroke-spacing-mm", type=float, default=None)
    parser.add_argument("--sketch-stroke-length-mm", type=float, default=None)
    parser.add_argument("--sketch-threshold", type=float, default=None)
    parser.add_argument("--sketch-density", type=float, default=None)
    parser.add_argument("--sketch-density-gamma", type=float, default=None)
    parser.add_argument("--sketch-min-center-distance-mm", type=float, default=None)
    parser.add_argument("--sketch-tone-line-spacing-mm", type=float, default=PhotoPlotConfig().sketch_tone_line_spacing_mm)
    parser.add_argument("--sketch-tone-step-mm", type=float, default=PhotoPlotConfig().sketch_tone_step_mm)
    parser.add_argument("--sketch-tone-amplitude-mm", type=float, default=PhotoPlotConfig().sketch_tone_amplitude_mm)
    parser.add_argument("--no-sketch-tonal-contours", action="store_true", help="Disable soft tonal contour lines in sketch mode.")
    parser.add_argument("--sketch-contour-levels", default=None, help="Comma-separated sketch contour thresholds, e.g. 0.16,0.28,0.42,0.58")
    parser.add_argument("--sketch-pencil-edges", action="store_true", help="Use OpenCV pencilSketch as the edge-detail source.")
    parser.add_argument("--min-segment-mm", type=float, default=None)
    parser.add_argument("--merge-gap-mm", type=float, default=0.55)
    parser.add_argument("--no-edges", action="store_true", help="Disable Canny edge detail overlay.")
    parser.add_argument("--edge-min-length-mm", type=float, default=None)
    parser.add_argument("--scribble-line-spacing-mm", type=float, default=1.25)
    parser.add_argument("--scribble-step-mm", type=float, default=None)
    parser.add_argument("--scribble-amplitude-mm", type=float, default=1.6)
    parser.add_argument("--scribble-threshold", type=float, default=PhotoPlotConfig().scribble_threshold)
    parser.add_argument("--portrait-stroke-spacing-mm", type=float, default=PhotoPlotConfig().portrait_stroke_spacing_mm)
    parser.add_argument("--portrait-stroke-length-mm", type=float, default=PhotoPlotConfig().portrait_stroke_length_mm)
    parser.add_argument("--portrait-threshold", type=float, default=PhotoPlotConfig().portrait_threshold)
    parser.add_argument("--portrait-jitter-mm", type=float, default=None)
    parser.add_argument("--portrait-seed", type=int, default=PhotoPlotConfig().portrait_seed)
    parser.add_argument("--no-portrait-cleanup", action="store_true", help="Disable portrait background/component cleanup.")
    parser.add_argument("--portrait-cleanup-threshold", type=float, default=PhotoPlotConfig().portrait_cleanup_threshold)
    parser.add_argument("--portrait-min-component-area-mm2", type=float, default=PhotoPlotConfig().portrait_min_component_area_mm2)
    parser.add_argument("--portrait-mask-dilate-mm", type=float, default=PhotoPlotConfig().portrait_mask_dilate_mm)
    parser.add_argument("--portrait-sampling", choices=["blue_noise", "grid"], default=PhotoPlotConfig().portrait_sampling)
    parser.add_argument("--portrait-density", type=float, default=PhotoPlotConfig().portrait_density)
    parser.add_argument("--portrait-min-center-distance-mm", type=float, default=PhotoPlotConfig().portrait_min_center_distance_mm)
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
    base_config = PhotoPlotConfig()
    if args.mode == "classic":
        quality_defaults = classic_photo_quality_preset(args.photo_quality)
    elif args.mode == "hatch":
        quality_defaults = hatch_photo_quality_preset(args.photo_quality)
    elif args.mode == "sketch":
        quality_defaults = sketch_photo_quality_preset(args.photo_quality)
    else:
        quality_defaults = {}
    max_side_px = int(
        args.max_side_px if args.max_side_px is not None else quality_defaults.get("max_side_px", base_config.max_side_px)
    )
    hatch_spacing_mm = float(
        args.hatch_spacing_mm
        if args.hatch_spacing_mm is not None
        else quality_defaults.get("hatch_spacing_mm", base_config.hatch_spacing_mm)
    )
    hatch_levels = _parse_csv_floats(
        args.hatch_levels,
        tuple(quality_defaults.get("hatch_levels", base_config.hatch_levels)),
    )
    hatch_angles_deg = _parse_csv_floats(
        args.hatch_angles,
        tuple(quality_defaults.get("hatch_angles_deg", base_config.hatch_angles_deg)),
    )
    classic_spacing_mm = float(
        args.classic_spacing_mm
        if args.classic_spacing_mm is not None
        else quality_defaults.get("classic_spacing_mm", base_config.classic_spacing_mm)
    )
    classic_levels = _parse_csv_floats(
        args.classic_levels,
        tuple(quality_defaults.get("classic_levels", base_config.classic_levels)),
    )
    classic_angles_deg = _parse_csv_floats(
        args.classic_angles,
        tuple(quality_defaults.get("classic_angles_deg", base_config.classic_angles_deg)),
    )
    classic_smooth_sigma_px = float(
        args.classic_smooth_sigma_px
        if args.classic_smooth_sigma_px is not None
        else quality_defaults.get("classic_smooth_sigma_px", base_config.classic_smooth_sigma_px)
    )
    edge_min_length_mm = float(
        args.edge_min_length_mm
        if args.edge_min_length_mm is not None
        else quality_defaults.get("edge_min_length_mm", base_config.edge_min_length_mm)
    )
    sketch_stroke_spacing_mm = float(
        args.sketch_stroke_spacing_mm
        if args.sketch_stroke_spacing_mm is not None
        else quality_defaults.get("sketch_stroke_spacing_mm", base_config.sketch_stroke_spacing_mm)
    )
    sketch_stroke_length_mm = float(
        args.sketch_stroke_length_mm
        if args.sketch_stroke_length_mm is not None
        else quality_defaults.get("sketch_stroke_length_mm", base_config.sketch_stroke_length_mm)
    )
    sketch_threshold = float(
        args.sketch_threshold
        if args.sketch_threshold is not None
        else quality_defaults.get("sketch_threshold", base_config.sketch_threshold)
    )
    sketch_density = float(
        args.sketch_density
        if args.sketch_density is not None
        else quality_defaults.get("sketch_density", base_config.sketch_density)
    )
    sketch_density_gamma = float(
        args.sketch_density_gamma
        if args.sketch_density_gamma is not None
        else quality_defaults.get("sketch_density_gamma", base_config.sketch_density_gamma)
    )
    sketch_min_center_distance_mm = float(
        args.sketch_min_center_distance_mm
        if args.sketch_min_center_distance_mm is not None
        else quality_defaults.get("sketch_min_center_distance_mm", base_config.sketch_min_center_distance_mm)
    )
    sketch_contour_levels = _parse_csv_floats(
        args.sketch_contour_levels,
        tuple(quality_defaults.get("sketch_contour_levels", base_config.sketch_contour_levels)),
    )
    min_segment_mm = float(
        args.min_segment_mm
        if args.min_segment_mm is not None
        else quality_defaults.get("min_segment_mm", base_config.min_segment_mm)
    )
    scribble_step_mm = float(
        args.scribble_step_mm
        if args.scribble_step_mm is not None
        else quality_defaults.get("scribble_step_mm", base_config.scribble_step_mm)
    )
    portrait_jitter_mm = float(
        args.portrait_jitter_mm
        if args.portrait_jitter_mm is not None
        else quality_defaults.get("portrait_jitter_mm", base_config.portrait_jitter_mm)
    )
    config = PhotoPlotConfig(
        mode=args.mode,
        margin_mm=args.margin_mm,
        target_width_mm=args.target_width_mm,
        target_height_mm=args.target_height_mm,
        max_side_px=max_side_px,
        contrast=args.contrast,
        gamma=args.gamma,
        blur_px=args.blur_px,
        hatch_spacing_mm=hatch_spacing_mm,
        hatch_levels=hatch_levels,
        hatch_angles_deg=hatch_angles_deg,
        classic_spacing_mm=classic_spacing_mm,
        classic_levels=classic_levels,
        classic_angles_deg=classic_angles_deg,
        classic_smooth_sigma_px=classic_smooth_sigma_px,
        sketch_stroke_spacing_mm=sketch_stroke_spacing_mm,
        sketch_stroke_length_mm=sketch_stroke_length_mm,
        sketch_threshold=sketch_threshold,
        sketch_density=sketch_density,
        sketch_density_gamma=sketch_density_gamma,
        sketch_min_center_distance_mm=sketch_min_center_distance_mm,
        sketch_tone_line_spacing_mm=args.sketch_tone_line_spacing_mm,
        sketch_tone_step_mm=args.sketch_tone_step_mm,
        sketch_tone_amplitude_mm=args.sketch_tone_amplitude_mm,
        sketch_tonal_contours=not bool(args.no_sketch_tonal_contours),
        sketch_contour_levels=sketch_contour_levels,
        sketch_pencil_edges=bool(args.sketch_pencil_edges),
        min_segment_mm=min_segment_mm,
        merge_gap_mm=args.merge_gap_mm,
        edge_enabled=not bool(args.no_edges),
        edge_min_length_mm=edge_min_length_mm,
        scribble_line_spacing_mm=args.scribble_line_spacing_mm,
        scribble_step_mm=scribble_step_mm,
        scribble_amplitude_mm=args.scribble_amplitude_mm,
        scribble_threshold=args.scribble_threshold,
        portrait_stroke_spacing_mm=args.portrait_stroke_spacing_mm,
        portrait_stroke_length_mm=args.portrait_stroke_length_mm,
        portrait_threshold=args.portrait_threshold,
        portrait_jitter_mm=portrait_jitter_mm,
        portrait_seed=args.portrait_seed,
        portrait_cleanup_enabled=not bool(args.no_portrait_cleanup),
        portrait_cleanup_threshold=args.portrait_cleanup_threshold,
        portrait_min_component_area_mm2=args.portrait_min_component_area_mm2,
        portrait_mask_dilate_mm=args.portrait_mask_dilate_mm,
        portrait_sampling=args.portrait_sampling,
        portrait_density=args.portrait_density,
        portrait_min_center_distance_mm=args.portrait_min_center_distance_mm,
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
