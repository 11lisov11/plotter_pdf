from __future__ import annotations

from pathlib import Path

from scripts import audit_nachert_packages as mod
from PIL import Image


def test_collect_variant_dirs_accepts_variant_root(tmp_path: Path) -> None:
    variant = tmp_path / "1 вариант"
    variant.mkdir()
    (variant / "_prepared_summary.csv").write_text("source_pdf\n", encoding="utf-8")

    result = mod._collect_variant_dirs(variant)

    assert result == [variant]


def test_collect_variant_dirs_filters_to_summary_dirs(tmp_path: Path) -> None:
    variant1 = tmp_path / "1 вариант"
    variant2 = tmp_path / "24 варинт"
    noise = tmp_path / "_audit"
    variant1.mkdir()
    variant2.mkdir()
    noise.mkdir()
    (variant1 / "_prepared_summary.csv").write_text("source_pdf\n", encoding="utf-8")
    (variant2 / "_prepared_summary.csv").write_text("source_pdf\n", encoding="utf-8")

    result = mod._collect_variant_dirs(tmp_path)

    assert result == [variant1, variant2]


def test_save_package_compare_artifacts_writes_png_and_pdf(tmp_path: Path) -> None:
    panel = Image.new("RGB", (120, 80), "white")

    png_path, pdf_path = mod._save_package_compare_artifacts(tmp_path, panel)

    assert png_path.exists()
    assert pdf_path.exists()
    assert png_path.name == "source_vs_gcode_compare.png"
    assert pdf_path.name == "source_vs_gcode_compare.pdf"


def test_main_returns_error_when_no_prepared_variants_match(tmp_path: Path, capsys) -> None:
    variant = tmp_path / "1 вариант"
    variant.mkdir()
    (variant / "_prepared_summary.csv").write_text("source_pdf\n", encoding="utf-8")

    rc = mod.main(["--root", str(tmp_path), "--only-variant", "missing"])

    assert rc == 2
    assert "No prepared Начерт variant dirs match filter" in capsys.readouterr().out


def test_main_returns_error_when_no_prepared_variants_exist(tmp_path: Path, capsys) -> None:
    (tmp_path / "noise").mkdir()

    rc = mod.main(["--root", str(tmp_path)])

    assert rc == 2
    assert "No prepared Начерт variant dirs found" in capsys.readouterr().out
