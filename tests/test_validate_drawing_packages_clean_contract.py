from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import validate_drawing_packages as validator


def test_collect_variant_dirs_accepts_clean_packages_without_legacy_summary(tmp_path: Path) -> None:
    variant = tmp_path / "9 вариант"
    (variant / "drawing_pack").mkdir(parents=True)

    assert validator.collect_variant_dirs([tmp_path]) == [variant.resolve()]


def test_minimal_package_validator_reads_canonical_plotter_nc(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "drawing_pack"
    package.mkdir()
    plotter = package / "plotter.nc"
    plotter.write_text("G0 X0 Y0\n", encoding="utf-8")
    expected = validator.GcodeValidation(ok=True, lines=1, motor_release_seen=True)
    monkeypatch.setattr(validator, "validate_gcode_file", lambda path, work_area: expected)

    result = validator.validate_minimal_package(package)

    assert result.ok is True
    assert result.gcode == {"plotter.nc": expected}


def test_minimal_package_keeps_overlap_metrics_as_non_blocking_warning(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "drawing_pack"
    package.mkdir()
    (package / "plotter.nc").write_text("G0 X0 Y0\n", encoding="utf-8")
    measured = validator.GcodeValidation(
        ok=False,
        lines=1,
        problems=["plotter.nc: collinear overlapping draw segments=7"],
    )
    monkeypatch.setattr(validator, "validate_gcode_file", lambda path, work_area: measured)

    result = validator.validate_minimal_package(package)

    assert result.ok is True
    assert result.problems == []
    assert result.warnings == ["plotter.nc: plotter.nc: collinear overlapping draw segments=7"]
