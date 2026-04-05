from __future__ import annotations

from pathlib import Path

from scripts import audit_nachert_packages as mod


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
