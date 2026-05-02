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
G0 X1.0000 Y-1.0000 F15000
G1 Z11.9000 F700
G1 X2.0000 Y-1.0000 F12000
G0 Z0.0000 F700
G0 X0.0000 Y0.0000 F15000
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


def test_validate_gcode_rejects_first_xy_with_pen_down(tmp_path: Path) -> None:
    gcode_path = tmp_path / "bad_start.gcode"
    gcode_path.write_text("G21\nG90\nG92 Z11.9000\nG1 X10 Y-10\n", encoding="utf-8")

    result = mod.validate_gcode_file(gcode_path)

    assert not result.ok
    assert any("first XY move happens with pen down" in problem for problem in result.problems)


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


def test_validate_variant_writes_ready_to_plot_audit(tmp_path: Path) -> None:
    variant_dir = tmp_path / "variant"
    package_dir = _write_package(variant_dir)
    _write_variant_summary(variant_dir, package_dir)

    payload = mod.validate_variant(variant_dir)

    assert payload["ok"] is True
    assert payload["packages"] == 1
    assert (variant_dir / "_ready_to_plot_audit.json").exists()
    assert (variant_dir / "_ready_to_plot_audit.txt").exists()
