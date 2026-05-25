from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import validate_drawing_packages as mod


VALID_GCODE = """$X
G21
G90
G92 Z4.0000
G0 Z0.0000 F800
G0 X0.0000 Y0.0000 F15000
G0 X1.0000 Y-6.0000 F15000
G1 Z11.9000 F700
G1 X2.0000 Y-6.0000 F12000
G0 Z0.0000 F700
G0 X0.0000 Y0.0000 F15000
M5
$1=0
"""


def _write_package(root: Path, *, report: dict[str, object] | None = None, gcode: str = VALID_GCODE) -> Path:
    package_dir = root / "Drawing_pack"
    package_dir.mkdir(parents=True)
    for rel in (
        "a4_clean_source.pdf",
        "page_01.pdf",
        "source_vs_gcode_compare.pdf",
        "source_vs_gcode_compare.png",
    ):
        (package_dir / rel).write_text("stub", encoding="utf-8")
    (package_dir / "page_01.gcode").write_text(gcode, encoding="utf-8")
    (package_dir / "summary.csv").write_text("item\npage_01\n", encoding="utf-8")
    report_payload = report or {
        "selected_variant": "mupdf_svg_paths",
        "frame_class": "kompas_full_frame",
        "items": [
            {
                "variant": "mupdf_svg_paths",
                "logs": ["clean"],
                "metrics": {"segments_duplicate": 0},
            }
        ],
    }
    (package_dir / "report.json").write_text(json.dumps(report_payload), encoding="utf-8")
    return package_dir


def _write_variant_summary(variant_dir: Path, package_dir: Path) -> None:
    with (variant_dir / "_prepared_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["package_dir", "item"])
        writer.writeheader()
        writer.writerow({"package_dir": str(package_dir), "item": "page_01"})


def test_validate_gcode_accepts_safe_start_and_bounds(tmp_path: Path) -> None:
    gcode_path = tmp_path / "ok.gcode"
    gcode_path.write_text(VALID_GCODE, encoding="utf-8")

    result = mod.validate_gcode_file(gcode_path)

    assert result.ok
    assert result.draw_moves == 1
    assert result.duplicate_segments == 0
    assert result.final_position == (0.0, 0.0, 0.0)
    assert result.motor_release_seen


def test_validate_gcode_rejects_missing_home_and_motor_release(tmp_path: Path) -> None:
    gcode_path = tmp_path / "no_home_no_release.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z0
G0 Z0
G0 X0 Y0
G1 Z11.9
G1 X10 Y-10
G0 Z0
M5
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("does not return home" in problem for problem in result.problems)
    assert any("missing motor release" in problem for problem in result.problems)


def test_validate_gcode_rejects_file_ending_with_pen_down(tmp_path: Path) -> None:
    gcode_path = tmp_path / "pen_down_end.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z0
G0 Z0
G0 X0 Y0
G1 Z11.9
G1 X10 Y-10
G0 X0 Y0
M5
$1=0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("file ends with pen down" in problem for problem in result.problems)


def test_validate_gcode_rejects_old_minus_15mm_work_area_shift(tmp_path: Path) -> None:
    gcode_path = tmp_path / "old_shift.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z0
G0 Z0
G0 X0 Y-15
G1 Z11.9
G1 X180 Y-15
G1 X180 Y-295
G1 X0 Y-295
G1 X0 Y-15
G0 Z0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("outside work area" in problem for problem in result.problems)


def test_validate_gcode_rejects_unshifted_bottom_after_5mm_calibration(tmp_path: Path) -> None:
    gcode_path = tmp_path / "unshifted.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z0
G0 Z0
G0 X0 Y0
G1 Z11.9
G1 X180 Y0
G1 X180 Y-280
G1 X0 Y-280
G1 X0 Y0
G0 Z0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("outside work area" in problem for problem in result.problems)


def test_validate_gcode_rejects_first_xy_with_pen_down(tmp_path: Path) -> None:
    gcode_path = tmp_path / "bad_start.gcode"
    gcode_path.write_text("G21\nG90\nG92 Z11.9000\nG1 X10 Y-10\n", encoding="utf-8")

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("first XY move happens with pen down" in problem for problem in result.problems)


def test_validate_gcode_rejects_first_xy_after_prior_pen_down(tmp_path: Path) -> None:
    gcode_path = tmp_path / "bad_prior_down.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z0
G1 Z11.9000
G1 X10 Y-10
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("first XY move happens with pen down" in problem for problem in result.problems)


def test_validate_gcode_rejects_first_xy_after_compact_g92_pen_down(tmp_path: Path) -> None:
    gcode_path = tmp_path / "bad_compact_g92_down.gcode"
    gcode_path.write_text(
        """G21
G90
G92Z11.9000
G1X10Y-10
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("first XY move happens with pen down" in problem for problem in result.problems)


def test_validate_gcode_rejects_rapid_xy_while_lifting_pen(tmp_path: Path) -> None:
    gcode_path = tmp_path / "bad_lift_travel.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z0
G0 X0 Y-10
G1 Z11.9000
G1 X10 Y-10
G0 X20 Y-20 Z0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("rapid XY travel with pen down" in problem for problem in result.problems)


def test_validate_gcode_rejects_compact_rapid_xy_with_pen_down(tmp_path: Path) -> None:
    gcode_path = tmp_path / "bad_compact_rapid.gcode"
    gcode_path.write_text(
        """G21
G90
G92Z0
G0X0Y0
G1Z11.9000
G0X10Y-10
G0Z0
G0X0Y0
M5
$1=0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("rapid XY travel with pen down" in problem for problem in result.problems)


def test_validate_gcode_does_not_treat_m30_as_pen_down(tmp_path: Path) -> None:
    gcode_path = tmp_path / "program_end.gcode"
    gcode_path.write_text(VALID_GCODE + "M30\n", encoding="utf-8")

    result = mod.validate_gcode_file(gcode_path)

    assert result.ok


def test_validate_gcode_parses_exponent_coordinates(tmp_path: Path) -> None:
    gcode_path = tmp_path / "exp.nc"
    gcode_path.write_text(
        """G21
G90
G92 Z4
G0 Z0 F800
M5
G0 X0 Y-1.0e1
G1 Z11.9
G1 X1.0e1 Y-2.0e1
G0 Z0
M5
G0 X0 Y0
M5
$1=0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert result.ok, result.problems
    assert result.bounds == (0.0, 10.0, -20.0, -10.0)


def test_validate_gcode_respects_relative_xy_mode(tmp_path: Path) -> None:
    gcode_path = tmp_path / "relative_xy.nc"
    gcode_path.write_text(
        """G21
G90
G92 Z4
G0 Z0 F800
M5
G0 X0 Y-10
G1 Z11.9
G91
G1 X10 Y0
G90
G0 Z0
G0 X0 Y0
M5
$1=0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert result.ok, result.problems
    assert result.bounds == (0.0, 10.0, -10.0, -10.0)


def test_validate_gcode_rejects_absolute_ijk_arc_bulge_outside_work_area(tmp_path: Path) -> None:
    gcode_path = tmp_path / "arc_bulge.nc"
    gcode_path.write_text(
        """G21
G90
G90.1
G92 Z4
G0 Z0 F800
M5
G0 X9 Y-10
G1 Z11.9
G2 X21 Y-10 I15 J-10
G0 Z0
G0 X0 Y0
M5
$1=0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert result.bounds is not None
    assert tuple(round(value, 3) for value in result.bounds) == (9.0, 21.0, -10.0, -4.0)
    assert any("outside work area" in problem for problem in result.problems)


def test_validate_gcode_rejects_duplicate_draw_segment(tmp_path: Path) -> None:
    gcode_path = tmp_path / "duplicate.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z4
G0 Z0
G0 X0 Y0
G1 Z11.9
G1 X10 Y-10
G0 Z0
G0 X0 Y0
G1 Z11.9
G1 X10 Y-10
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert result.duplicate_segments == 1


def test_validate_gcode_rejects_partial_collinear_overlap(tmp_path: Path) -> None:
    gcode_path = tmp_path / "partial_overlap.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z4
G0 Z0
G0 X0 Y-10
G1 Z11.9
G1 X10 Y-10
G0 Z0
G0 X2 Y-10
G1 Z11.9
G1 X8 Y-10
G0 Z0
G0 X0 Y0
M5
$1=0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert result.duplicate_segments == 0
    assert result.overlap_segments == 1
    assert any("collinear overlapping draw segments=1" in problem for problem in result.problems)


def test_validate_gcode_rejects_pdf_jitter_collinear_overlap(tmp_path: Path) -> None:
    gcode_path = tmp_path / "jitter_overlap.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z4
G0 Z0
G0 X123.4761 Y-200.4955
G1 Z11.9
G1 X143.4627 Y-200.4955
G0 Z0
G0 X142.5181 Y-200.4132
G1 Z11.9
G1 X141.7319 Y-200.4180
G0 Z0
G0 X0 Y0
M5
$1=0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert result.overlap_segments == 1


def test_validate_gcode_rejects_overlap_when_long_segment_is_seen_first(tmp_path: Path) -> None:
    gcode_path = tmp_path / "long_first_overlap.gcode"
    gcode_path.write_text(
        """G21
G90
G92 Z4
G0 Z0
G0 X74.4331 Y-97.8639
G1 Z11.9
G1 X168.3499 Y-98.8800
G0 Z0
G0 X121.8903 Y-98.3108
G1 Z11.9
G1 X124.6551 Y-98.3120
G0 Z0
G0 X0 Y0
M5
$1=0
""",
        encoding="utf-8",
    )

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert result.overlap_segments == 1


def test_validate_package_checks_optional_nc_alias(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path)
    (package_dir / "page_01.nc").write_text("G21\nG90\nG92 Z11.9000\nG1 X10 Y-10\n", encoding="utf-8")

    result = mod.validate_package(package_dir, [{"package_dir": str(package_dir), "item": "page_01"}])

    assert not result.ok
    assert "page_01.nc" in result.gcode
    assert any("page_01.nc: line" in problem and "first XY move happens with pen down" in problem for problem in result.problems)


def test_validate_package_rejects_stale_valid_nc_alias(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path)
    (package_dir / "page_01.nc").write_text(VALID_GCODE.replace("X2.0000", "X3.0000"), encoding="utf-8")

    result = mod.validate_package(package_dir, [{"package_dir": str(package_dir), "item": "page_01"}])

    assert not result.ok
    assert any("plotter aliases differ for page_01" in problem for problem in result.problems)


def test_validate_package_rejects_unexpected_valid_plotter_file(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path)
    (package_dir / "old_page_01.gcode").write_text(VALID_GCODE, encoding="utf-8")

    result = mod.validate_package(package_dir, [{"package_dir": str(package_dir), "item": "page_01"}])

    assert not result.ok
    assert any("unexpected plotter file old_page_01.gcode" in problem for problem in result.problems)


def test_validate_package_checks_pages_mirror_nc(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path)
    pages_dir = package_dir / "pages"
    pages_dir.mkdir()
    (pages_dir / "page_01.nc").write_text("G21\nG90\nG92 Z11.9000\nG1 X10 Y-10\n", encoding="utf-8")

    result = mod.validate_package(package_dir, [{"package_dir": str(package_dir), "item": "page_01"}])

    assert not result.ok
    assert "pages/page_01.nc" in result.gcode
    assert any(
        "pages/page_01.nc:" in problem and "first XY move happens with pen down" in problem
        for problem in result.problems
    )


def test_validate_package_rejects_kompas_technical_text_join(tmp_path: Path) -> None:
    report = {
        "selected_variant": "mupdf_svg_paths",
        "frame_class": "kompas_full_frame",
        "items": [
            {
                "variant": "mupdf_svg_paths",
                "logs": ["Technical text join: merged 10 short gaps"],
                "metrics": {"segments_duplicate": 0},
            }
        ],
    }
    package_dir = _write_package(tmp_path, report=report)

    result = mod.validate_package(package_dir, [{"package_dir": str(package_dir), "item": "page_01"}])

    assert not result.ok
    assert any("Technical text join" in problem for problem in result.problems)


def test_validate_package_rejects_kompas_text_reroute_log(tmp_path: Path) -> None:
    report = {
        "selected_variant": "mupdf_svg_paths",
        "frame_class": "kompas_full_frame",
        "items": [
            {
                "variant": "mupdf_svg_paths",
                "logs": ["KOMPAS text reroute: removed 12 outline polyline(s)"],
                "metrics": {"segments_duplicate": 0},
            }
        ],
    }
    package_dir = _write_package(tmp_path, report=report)

    result = mod.validate_package(package_dir, [{"package_dir": str(package_dir), "item": "page_01"}])

    assert not result.ok
    assert any("reroutes source text" in problem for problem in result.problems)


def test_validate_package_rejects_kompas_text_reroute_note(tmp_path: Path) -> None:
    report = {
        "selected_variant": "mupdf_svg_paths",
        "frame_class": "kompas_full_frame",
        "items": [
            {
                "variant": "mupdf_svg_paths",
                "logs": ["clean"],
                "notes": "kompas_text_reroute=True; kompas_text_rendered=20",
                "metrics": {"segments_duplicate": 0},
            }
        ],
    }
    package_dir = _write_package(tmp_path, report=report)

    result = mod.validate_package(package_dir, [{"package_dir": str(package_dir), "item": "page_01"}])

    assert not result.ok
    assert any("kompas_text_reroute=True" in problem for problem in result.problems)


def test_validate_package_accepts_four_pass_tiled_package(tmp_path: Path) -> None:
    package_dir = tmp_path / "Tiled_pack"
    package_dir.mkdir()
    for rel in ("report.json", "summary.csv", "source_vs_gcode_compare.pdf", "source_vs_gcode_compare.png", "combined_preview.pdf"):
        (package_dir / rel).write_text("stub", encoding="utf-8")
    report = {
        "selected_variant": "custom_tiled_clean_source",
        "frame_class": "kompas_full_frame",
        "items": [
            {
                "variant": "custom_tiled_clean_source",
                "logs": ["clean"],
                "metrics": {"segments_duplicate": 0},
            }
        ],
    }
    (package_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (package_dir / "summary.csv").write_text("item\npass_01\npass_02\npass_03\npass_04\n", encoding="utf-8")
    rows: list[dict[str, str]] = []
    for idx in range(1, 5):
        name = f"pass_{idx:02d}"
        (package_dir / f"{name}.pdf").write_text("stub", encoding="utf-8")
        (package_dir / f"{name}.gcode").write_text(VALID_GCODE, encoding="utf-8")
        rows.append({"package_dir": str(package_dir), "item": name})

    result = mod.validate_package(package_dir, rows)

    assert result.ok
    assert set(result.gcode) == {"pass_01.gcode", "pass_02.gcode", "pass_03.gcode", "pass_04.gcode"}


def _write_a3_package(tmp_path: Path, clean_source_svg: str) -> Path:
    package_dir = tmp_path / "A3_pack"
    package_dir.mkdir()
    (package_dir / "_candidates").mkdir()
    for rel in (
        "report.json",
        "summary.csv",
        "source_vs_gcode_compare.pdf",
        "source_vs_gcode_compare.png",
        "combined_preview.pdf",
    ):
        (package_dir / rel).write_text("stub", encoding="utf-8")
    report = {
        "selected_variant": "a3_two_pass_clean_source",
        "frame_class": "kompas_full_frame",
        "items": [
            {
                "variant": "a3_two_pass_clean_source",
                "logs": ["clean"],
                "metrics": {"segments_duplicate": 0},
            }
        ],
    }
    (package_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (package_dir / "summary.csv").write_text("item\npass_01\npass_02\n", encoding="utf-8")
    (package_dir / "_candidates" / "a3_clean_source.svg").write_text(clean_source_svg, encoding="utf-8")
    for name in ("pass_01", "pass_02"):
        (package_dir / f"{name}.pdf").write_text("stub", encoding="utf-8")
        (package_dir / f"{name}.gcode").write_text(VALID_GCODE, encoding="utf-8")
    return package_dir


def test_validate_package_rejects_kompas_a3_outer_sheet_frame(tmp_path: Path) -> None:
    package_dir = _write_a3_package(
        tmp_path,
        """<svg xmlns="http://www.w3.org/2000/svg">
<path d="M 24 5.5 L 415.46 5.5 L 415.46 292.52 L 24 292.52 L 24 5.5" />
</svg>""",
    )

    result = mod.validate_package(
        package_dir,
        [{"package_dir": str(package_dir), "item": "pass_01"}, {"package_dir": str(package_dir), "item": "pass_02"}],
    )

    assert not result.ok
    assert any("outer sheet frame" in problem for problem in result.problems)


def test_validate_package_allows_kompas_a3_stamp_bottom_edge(tmp_path: Path) -> None:
    package_dir = _write_a3_package(
        tmp_path,
        """<svg xmlns="http://www.w3.org/2000/svg">
<path d="M 120 20 L 130 40" />
<path d="M 415.46 292.52 L 225.46 292.52" />
</svg>""",
    )

    result = mod.validate_package(
        package_dir,
        [{"package_dir": str(package_dir), "item": "pass_01"}, {"package_dir": str(package_dir), "item": "pass_02"}],
    )

    assert result.ok


def test_validate_variant_writes_ready_to_plot_audit(tmp_path: Path) -> None:
    variant_dir = tmp_path / "variant"
    package_dir = _write_package(variant_dir)
    _write_variant_summary(variant_dir, package_dir)

    payload = mod.validate_variant(variant_dir)

    assert payload["ok"] is True
    assert payload["packages"] == 1
    assert payload["preflight"]["missing_motor_release"] == 0
    assert payload["preflight"]["unsafe_endings"] == 0
    assert (variant_dir / "_ready_to_plot_audit.json").exists()
    assert (variant_dir / "_ready_to_plot_audit.txt").exists()


def test_validate_variant_resolves_relative_package_dir_from_variant(tmp_path: Path) -> None:
    variant_dir = tmp_path / "variant"
    package_dir = _write_package(variant_dir)
    with (variant_dir / "_prepared_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["package_dir", "item"])
        writer.writeheader()
        writer.writerow({"package_dir": package_dir.name, "item": "page_01"})

    payload = mod.validate_variant(variant_dir, write_reports=False)

    assert payload["ok"] is True
    assert payload["packages"] == 1


def test_validate_variant_rejects_package_dir_outside_variant(tmp_path: Path) -> None:
    variant_dir = tmp_path / "variant"
    variant_dir.mkdir()
    outside_package = _write_package(tmp_path / "outside")
    with (variant_dir / "_prepared_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["package_dir", "item"])
        writer.writeheader()
        writer.writerow({"package_dir": str(outside_package), "item": "page_01"})

    payload = mod.validate_variant(variant_dir, write_reports=False)

    assert payload["ok"] is False
    assert payload["packages"] == 0
    problems = payload["failed_packages"][0]["problems"]
    assert any("package_dir outside variant" in problem for problem in problems)


def test_validate_variant_remaps_stale_absolute_package_dir_to_local_variant_package(tmp_path: Path) -> None:
    variant_dir = tmp_path / "variant"
    package_dir = _write_package(variant_dir)
    stale_package_dir = tmp_path / "old_root" / "variant" / package_dir.name
    with (variant_dir / "_prepared_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["package_dir", "item"])
        writer.writeheader()
        writer.writerow({"package_dir": str(stale_package_dir), "item": "page_01"})

    payload = mod.validate_variant(variant_dir, write_reports=False)

    assert payload["ok"] is True
    assert payload["packages"] == 1


def test_validate_variant_does_not_remap_outside_package_with_wrong_variant_parent(tmp_path: Path) -> None:
    variant_dir = tmp_path / "variant"
    package_dir = _write_package(variant_dir)
    stale_package_dir = tmp_path / "old_root" / "other_variant" / package_dir.name
    with (variant_dir / "_prepared_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["package_dir", "item"])
        writer.writeheader()
        writer.writerow({"package_dir": str(stale_package_dir), "item": "page_01"})

    payload = mod.validate_variant(variant_dir, write_reports=False)

    assert payload["ok"] is False
    assert payload["packages"] == 0
    problems = payload["failed_packages"][0]["problems"]
    assert any("package_dir outside variant" in problem for problem in problems)


def test_validate_variant_rejects_empty_prepared_summary(tmp_path: Path) -> None:
    variant_dir = tmp_path / "variant"
    variant_dir.mkdir()
    (variant_dir / "_prepared_summary.csv").write_text("package_dir,item\n", encoding="utf-8")

    payload = mod.validate_variant(variant_dir, write_reports=False)

    assert payload["ok"] is False
    assert payload["packages"] == 0
    assert payload["failed_packages"]
    assert "no packages listed" in payload["failed_packages"][0]["problems"][0]
