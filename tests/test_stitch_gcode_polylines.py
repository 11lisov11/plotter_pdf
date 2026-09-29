from __future__ import annotations

from pathlib import Path

from scripts.stitch_gcode_polylines import read_draw_polylines


def test_read_draw_polylines_detects_a2_negative_z_profile(tmp_path: Path) -> None:
    source = tmp_path / "a2.nc"
    source.write_text(
        "G90\nG92 Z1\nG1 X0 Y0\nG1 Z-5\nG1 X10 Y20\nG1 Z1\n",
        encoding="utf-8",
    )

    assert read_draw_polylines(source) == [[(0.0, 0.0), (10.0, 20.0)]]
