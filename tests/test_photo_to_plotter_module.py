from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from src.plotter_backend.photo_to_plotter import (
    PhotoPlotConfig,
    WorkArea,
    generate_photo_plot,
    order_polylines_nearest,
)


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
        PhotoPlotConfig(mode="hatch", max_side_px=96, edge_enabled=False, route_optimize=False),
        area,
    )

    assert result.mode == "hatch"
    assert result.polylines
    assert result.stats["polyline_count"] == len(result.polylines)
    for polyline in result.polylines:
        for x, y in polyline:
            assert area.min_x <= x <= area.max_x
            assert area.min_y <= y <= area.max_y


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

