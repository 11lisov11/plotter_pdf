from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from src.plotter_backend.photo_to_plotter import (
    PhotoPlotConfig,
    WorkArea,
    classic_photo_quality_preset,
    generate_photo_plot,
    hatch_photo_quality_preset,
    order_polylines_nearest,
    sketch_photo_quality_preset,
)
from scripts.prepare_photo_plot_package import build_photo_plot_package, gcode_draw_polylines


def _write_gradient(path: Path, size: tuple[int, int] = (64, 48)) -> None:
    img = Image.new("L", size, "white")
    for y in range(size[1]):
        for x in range(size[0]):
            v = int(255 * (x / max(1, size[0] - 1)))
            if 16 < x < 48 and 12 < y < 36:
                v = min(v, 80)
            img.putpixel((x, y), v)
    img.save(path)


def test_generate_hatch_photo_plot_stays_inside_work_area(tmp_path: Path) -> None:
    img = tmp_path / "photo.png"
    _write_gradient(img)
    area = WorkArea(min_x=0.0, max_x=180.0, min_y=-280.0, max_y=0.0)
    result = generate_photo_plot(
        img,
        PhotoPlotConfig(
            mode="hatch",
            hatch_spacing_mm=1.2,
            hatch_levels=(0.18, 0.34, 0.50, 0.66),
            max_side_px=96,
            edge_enabled=False,
            route_optimize=False,
        ),
        area,
    )

    assert result.mode == "hatch"
    assert result.polylines
    assert result.stats["polyline_count"] == len(result.polylines)
    for polyline in result.polylines:
        for x, y in polyline:
            assert area.min_x <= x <= area.max_x
            assert area.min_y <= y <= area.max_y


def test_generate_classic_photo_plot_makes_dark_regions_denser(tmp_path: Path) -> None:
    img = Image.new("L", (80, 48), "white")
    for y in range(48):
        for x in range(80):
            img.putpixel((x, y), 35 if x < 40 else 225)
    path = tmp_path / "classic.png"
    img.save(path)

    area = WorkArea(min_x=0.0, max_x=160.0, min_y=-96.0, max_y=0.0)
    result = generate_photo_plot(
        path,
        PhotoPlotConfig(
            mode="classic",
            max_side_px=80,
            margin_mm=0.0,
            edge_enabled=False,
            classic_spacing_mm=3.2,
            classic_levels=(0.12, 0.28, 0.44, 0.60, 0.76),
            route_optimize=False,
        ),
        area,
    )

    assert result.mode == "classic"
    assert result.polylines
    midpoint_x = (result.placement_bounds[0] + result.placement_bounds[1]) * 0.5
    dark_length = 0.0
    light_length = 0.0
    for polyline in result.polylines:
        for a, b in zip(polyline, polyline[1:]):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if (a[0] + b[0]) * 0.5 < midpoint_x:
                dark_length += length
            else:
                light_length += length

    assert dark_length > light_length * 4.0


def test_classic_photo_quality_presets_order_workload() -> None:
    fast = classic_photo_quality_preset("fast")
    normal = classic_photo_quality_preset("normal")
    detailed = classic_photo_quality_preset("detailed")

    assert fast["max_side_px"] < normal["max_side_px"] < detailed["max_side_px"]
    assert fast["classic_spacing_mm"] > normal["classic_spacing_mm"] > detailed["classic_spacing_mm"]
    assert len(fast["classic_levels"]) < len(detailed["classic_levels"])
    assert len(fast["classic_angles_deg"]) < len(detailed["classic_angles_deg"])


def test_hatch_photo_quality_presets_order_workload() -> None:
    fast = hatch_photo_quality_preset("fast")
    normal = hatch_photo_quality_preset("normal")
    detailed = hatch_photo_quality_preset("detailed")

    assert fast["max_side_px"] < normal["max_side_px"] < detailed["max_side_px"]
    assert fast["hatch_spacing_mm"] > normal["hatch_spacing_mm"] > detailed["hatch_spacing_mm"]
    assert len(fast["hatch_levels"]) < len(detailed["hatch_levels"])
    assert fast["hatch_angles_deg"] == normal["hatch_angles_deg"] == detailed["hatch_angles_deg"]


def test_sketch_photo_quality_presets_order_pencil_workload() -> None:
    fast = sketch_photo_quality_preset("fast")
    normal = sketch_photo_quality_preset("normal")
    detailed = sketch_photo_quality_preset("detailed")

    assert fast["max_side_px"] < normal["max_side_px"] < detailed["max_side_px"]
    assert fast["sketch_stroke_spacing_mm"] > normal["sketch_stroke_spacing_mm"] > detailed["sketch_stroke_spacing_mm"]
    assert fast["sketch_density"] < normal["sketch_density"] < detailed["sketch_density"]
    assert len(fast["sketch_contour_levels"]) < len(detailed["sketch_contour_levels"])


def test_generate_scribble_photo_plot_uses_fewer_long_paths(tmp_path: Path) -> None:
    img = tmp_path / "photo.png"
    _write_gradient(img)
    result = generate_photo_plot(
        img,
        PhotoPlotConfig(
            mode="scribble",
            max_side_px=96,
            edge_enabled=False,
            scribble_line_spacing_mm=3.0,
            route_optimize=False,
        ),
    )

    assert result.mode == "scribble"
    assert result.polylines
    assert all(len(polyline) > 2 for polyline in result.polylines)
    assert result.stats["point_count"] > result.stats["polyline_count"]


def test_generate_portrait_photo_plot_uses_short_artist_strokes(tmp_path: Path) -> None:
    img = tmp_path / "photo.png"
    _write_gradient(img)
    result = generate_photo_plot(
        img,
        PhotoPlotConfig(
            mode="portrait",
            max_side_px=96,
            edge_enabled=False,
            portrait_stroke_spacing_mm=4.0,
            portrait_stroke_length_mm=8.0,
            portrait_seed=5,
            route_optimize=False,
        ),
    )

    assert result.mode == "portrait"
    assert result.polylines
    assert result.stats["point_count"] > result.stats["polyline_count"]
    assert result.stats["portrait_content_mask_px"] > 0


def test_portrait_cleanup_drops_small_background_components(tmp_path: Path) -> None:
    img = Image.new("L", (90, 90), "white")
    for y in range(25, 65):
        for x in range(25, 65):
            img.putpixel((x, y), 35)
    for y in range(5, 9):
        for x in range(5, 9):
            img.putpixel((x, y), 20)
    path = tmp_path / "portrait_noise.png"
    img.save(path)

    area = WorkArea(min_x=0.0, max_x=90.0, min_y=-90.0, max_y=0.0)
    result = generate_photo_plot(
        path,
        PhotoPlotConfig(
            mode="portrait",
            max_side_px=90,
            margin_mm=0.0,
            edge_enabled=False,
            portrait_stroke_spacing_mm=3.0,
            portrait_stroke_length_mm=5.0,
            portrait_min_component_area_mm2=80.0,
            portrait_mask_dilate_mm=0.0,
            route_optimize=False,
        ),
        area,
    )

    assert result.polylines
    assert all(not (x < 15 and y > -15) for polyline in result.polylines for x, y in polyline)


def test_portrait_blue_noise_sampling_is_deterministic(tmp_path: Path) -> None:
    img = tmp_path / "photo.png"
    _write_gradient(img)
    config = PhotoPlotConfig(
        mode="portrait",
        max_side_px=96,
        edge_enabled=False,
        portrait_seed=99,
        portrait_sampling="blue_noise",
        portrait_density=0.8,
        route_optimize=False,
    )

    result_a = generate_photo_plot(img, config)
    result_b = generate_photo_plot(img, config)

    assert result_a.polylines == result_b.polylines
    assert result_a.stats["config"]["portrait_sampling"] == "blue_noise"


def test_generate_sketch_photo_plot_preserves_readable_large_tonal_regions(tmp_path: Path) -> None:
    img = tmp_path / "photo.png"
    _write_gradient(img, size=(96, 72))
    result = generate_photo_plot(
        img,
        PhotoPlotConfig(mode="sketch", max_side_px=96, edge_enabled=False, route_optimize=False),
    )

    assert result.mode == "sketch"
    assert result.polylines
    assert result.stats["polyline_count"] < 800
    assert result.stats["draw_length_mm"] > 100.0


def test_nearest_order_can_reverse_segment_to_reduce_travel() -> None:
    polylines = [
        [(0.0, 0.0), (10.0, 0.0)],
        [(20.0, 0.0), (10.1, 0.0)],
        [(20.1, 0.0), (30.0, 0.0)],
    ]

    ordered = order_polylines_nearest(polylines)

    assert ordered[1][0] == (10.1, 0.0)
    travel = math.hypot(ordered[1][0][0] - ordered[0][-1][0], ordered[1][0][1] - ordered[0][-1][1])
    assert travel < 0.2


def test_gcode_preview_parser_uses_only_pen_down_moves(tmp_path: Path) -> None:
    gcode = tmp_path / "photo.gcode"
    gcode.write_text(
        "\n".join(
            [
                "G21",
                "G90",
                "G0 Z0.0000",
                "G0 X0 Y0",
                "G1 Z11.9000",
                "G1 X10 Y0",
                "G1 X10 Y5",
                "G1 Z0.0000",
                "G0 X20 Y20",
                "G1 Z11.9000",
                "G1 X25 Y20",
                "G1 Z0.0000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    polylines = gcode_draw_polylines(gcode)

    assert polylines == [[(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)], [(20.0, 20.0), (25.0, 20.0)]]


def test_photo_package_writes_final_gcode_previews(tmp_path: Path) -> None:
    img = tmp_path / "photo.png"
    _write_gradient(img, size=(48, 48))
    out_dir = tmp_path / "photo_pack"

    report = build_photo_plot_package(
        img,
        out_dir,
        PhotoPlotConfig(mode="hatch", max_side_px=64, edge_enabled=False, hatch_spacing_mm=3.0),
        feed_travel=6000.0,
        feed_draw=4000.0,
    )

    assert report["preflight"]["ok"] is True
    assert Path(report["files"]["gcode_pdf_preview"]).exists()
    assert Path(report["files"]["gcode_svg_preview"]).exists()
    assert Path(report["files"]["gcode"]).exists()
