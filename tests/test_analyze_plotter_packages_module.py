from __future__ import annotations

import json
import csv
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


def test_analyze_gcode_respects_spindle_pen_control(tmp_path: Path) -> None:
    gcode = tmp_path / "spindle.nc"
    gcode.write_text(
        "\n".join(
            [
                "G21",
                "G90",
                "G0 X0 Y0",
                "M3S1000",
                "G1X10Y0",
                "M5",
                "G1 X20 Y0",
                "M3",
                "G1 X20.1 Y0",
                "M5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = analyzer.analyze_gcode_file(gcode)

    assert metrics.g1_moves == 3
    assert metrics.draw_moves == 2
    assert metrics.pen_down_strokes == 2
    assert metrics.z_cycles == 0
    assert metrics.short_segments_lt_035_mm == 1
    assert metrics.tiny_strokes_lt_08_mm == 1
    assert metrics.point_like_strokes == 1
    assert metrics.draw_length_mm == 10.1


def test_analyze_gcode_respects_absolute_ijk_arc_mode(tmp_path: Path) -> None:
    gcode = tmp_path / "abs_ijk_arc.nc"
    gcode.write_text(
        "\n".join(
            [
                "G21",
                "G90",
                "G90.1",
                "G0 X10 Y0",
                "M3",
                "G3 X0 Y10 I0 J0",
                "M5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = analyzer.analyze_gcode_file(gcode)

    assert metrics.g3_moves == 1
    assert metrics.draw_moves == 1
    assert metrics.draw_length_mm == 15.708


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


def test_unique_files_by_content_reports_skipped_mirror_duplicates(tmp_path: Path) -> None:
    keep_nc = tmp_path / "a.nc"
    mirror_gcode = tmp_path / "pages" / "a.gcode"
    other_nc = tmp_path / "b.nc"
    mirror_gcode.parent.mkdir()
    keep_nc.write_text("G90\nG0 X0 Y0\n", encoding="utf-8")
    mirror_gcode.write_text("G90\nG0 X0 Y0\n", encoding="utf-8")
    other_nc.write_text("G90\nG0 X1 Y1\n", encoding="utf-8")

    unique, groups = analyzer.unique_files_by_content([keep_nc, mirror_gcode, other_nc])

    assert unique == [keep_nc, other_nc]
    assert groups == [
        {
            "kept": str(keep_nc),
            "duplicates": [str(mirror_gcode)],
            "count": 2,
        }
    ]


def test_collect_ready_package_roots_uses_variant_summary_and_skips_loose_dirs(tmp_path: Path) -> None:
    variant = tmp_path / "Компьютерная графика" / "22 вариант"
    package = variant / "ready_pack"
    loose = variant / "old_loose"
    package.mkdir(parents=True)
    loose.mkdir()
    (package / "summary.csv").write_text("item,ok\npage_01,True\n", encoding="utf-8")
    (loose / "page_01.gcode").write_text("G90\nG0 X0 Y0\n", encoding="utf-8")
    stale_package_dir = tmp_path / "old_root" / variant.name / package.name
    with (variant / "_prepared_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["package_dir", "task", "item"])
        writer.writeheader()
        writer.writerow({"package_dir": str(stale_package_dir), "task": package.name, "item": "page_01"})

    roots = analyzer.collect_ready_package_roots([variant])

    assert roots == [package]


def test_main_accepts_positional_gcode_files(tmp_path: Path, capsys) -> None:
    gcode = tmp_path / "job.nc"
    gcode.write_text("G90\nG0 X0 Y0\nG1 X1 Y0\n", encoding="utf-8")

    rc = analyzer.main([str(gcode), "--no-write"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["roots"] == [str(gcode)]
    assert payload["summary"]["files"] == 1


def test_main_unique_content_mode_summarizes_only_unique_files(tmp_path: Path, capsys) -> None:
    keep_nc = tmp_path / "a.nc"
    mirror_gcode = tmp_path / "pages" / "a.gcode"
    other_nc = tmp_path / "b.nc"
    mirror_gcode.parent.mkdir()
    keep_nc.write_text("G90\nG0 X0 Y0\nG1 X1 Y0\n", encoding="utf-8")
    mirror_gcode.write_text("G90\nG0 X0 Y0\nG1 X1 Y0\n", encoding="utf-8")
    other_nc.write_text("G90\nG0 X0 Y0\nG1 X2 Y0\n", encoding="utf-8")

    rc = analyzer.main([str(tmp_path), "--unique-content", "--no-write"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unique_content"] is True
    assert payload["files_seen"] == 3
    assert payload["files_analyzed"] == 2
    assert payload["duplicate_files_skipped"] == 1
    assert payload["summary"]["files"] == 2


def test_main_ready_only_ignores_loose_variant_outputs(tmp_path: Path, capsys) -> None:
    variant = tmp_path / "Компьютерная графика" / "22 вариант"
    package = variant / "ready_pack"
    loose = variant / "old_loose"
    package.mkdir(parents=True)
    loose.mkdir()
    (package / "page_01.gcode").write_text("G90\nG0 X0 Y0\nG1 X1 Y0\n", encoding="utf-8")
    (loose / "page_01.gcode").write_text("G90\nG0 X0 Y0\nG1 X99 Y0\n", encoding="utf-8")
    with (variant / "_prepared_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["package_dir", "task", "item"])
        writer.writeheader()
        writer.writerow({"package_dir": str(package), "task": package.name, "item": "page_01"})

    rc = analyzer.main([str(variant), "--ready-only", "--no-write"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready_only"] is True
    assert payload["scan_roots"] == [str(package)]
    assert payload["files_seen"] == 1
    assert payload["files"][0]["path"] == str(package / "page_01.gcode")


def test_main_default_root_is_computer_graphics(tmp_path: Path, monkeypatch, capsys) -> None:
    default_root = tmp_path / "Компьютерная графика"
    default_root.mkdir()
    (default_root / "job.nc").write_text("G90\nG0 X0 Y0\nG1 X1 Y0\n", encoding="utf-8")
    monkeypatch.setattr(analyzer, "PROJECT_ROOT", tmp_path)

    rc = analyzer.main(["--no-write"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["roots"] == [str(default_root)]
    assert payload["summary"]["files"] == 1


def test_main_returns_error_when_no_gcode_files_found(tmp_path: Path, capsys) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    rc = analyzer.main(["--root", str(empty_root), "--no-write"])

    assert rc == 2
    assert "No .nc/.gcode files found" in capsys.readouterr().out
