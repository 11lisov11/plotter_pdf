from __future__ import annotations

from pathlib import Path

from scripts import render_gcode_preview as preview


def test_parse_draw_segments_supports_negative_pen_down(tmp_path: Path) -> None:
    gcode = tmp_path / "a2.nc"
    gcode.write_text(
        "G21\nG90\nG0 Z0\nG0 X0 Y0\nG1 Z-4\nG1 X10 Y0\nG1 Z0\n",
        encoding="utf-8",
    )

    segments, points = preview.parse_draw_segments(
        gcode,
        transform="machine",
        work_min_x=0.0,
        work_min_y=0.0,
        work_width=390.0,
        work_height=580.0,
        z_up=0.0,
        z_down=-4.0,
    )

    assert segments == [(0.0, 0.0, 10.0, 0.0)]
    assert preview._bounds(points) == (0.0, 0.0, 10.0, 0.0)


def test_positive_a2_work_area_bounds_are_not_reported_outside() -> None:
    work_bounds = preview._transformed_work_bounds(
        transform="machine",
        work_min_x=0.0,
        work_min_y=0.0,
        work_width=390.0,
        work_height=580.0,
    )

    assert work_bounds == (0.0, 0.0, 390.0, 580.0)
    assert not preview._outside_bounds((0.0, 0.0, 390.0, 580.0), work_bounds)
