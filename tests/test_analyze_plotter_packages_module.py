from __future__ import annotations

from pathlib import Path

from scripts import analyze_plotter_packages as analyzer


def test_analyze_gcode_counts_draw_travel_and_z_cycles(tmp_path: Path) -> None:
    gcode = tmp_path / "job.nc"
    gcode.write_text(
        "\n".join(
            [
                "G21",
                "G90",
                "G0 Z0",
                "G0 X0 Y0",
                "G1 Z11.9",
                "G1 X0.1 Y0 F12000",
                "G1 X2.0 Y0",
                "G0 Z0",
                "G0 X5 Y0",
                "G1 Z11.9",
                "G1 X5.05 Y0",
                "G0 Z0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = analyzer.analyze_gcode_file(gcode)

    assert metrics.g0_moves == 2
    assert metrics.g1_moves == 3
    assert metrics.z_cycles == 2
    assert metrics.pen_down_strokes == 2
    assert metrics.short_segments_lt_035_mm == 2
    assert metrics.tiny_strokes_lt_08_mm == 1
    assert metrics.point_like_strokes == 1
    assert metrics.draw_length_mm == 2.05
    assert metrics.travel_length_mm == 3.0


def test_collect_gcode_files_uses_only_nc_and_gcode(tmp_path: Path) -> None:
    keep_nc = tmp_path / "a.nc"
    keep_gcode = tmp_path / "nested" / "b.gcode"
    skip = tmp_path / "c.txt"
    keep_gcode.parent.mkdir()
    keep_nc.write_text("G0 X0 Y0\n", encoding="utf-8")
    keep_gcode.write_text("G0 X0 Y0\n", encoding="utf-8")
    skip.write_text("x", encoding="utf-8")

    found = analyzer.collect_gcode_files([tmp_path])

    assert found == [keep_nc, keep_gcode]
