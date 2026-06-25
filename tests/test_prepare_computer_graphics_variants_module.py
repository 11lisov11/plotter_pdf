from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import prepare_computer_graphics_variants as mod


def test_copy_source_pdf_to_package_keeps_a4_audit_files(tmp_path: Path) -> None:
    package_dir = tmp_path / "Task Name"
    package_dir.mkdir(parents=True)
    source_pdf = tmp_path / "Task Name.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    for name in ("page_01.pdf", "page_01.gcode", "report.json", "summary.csv", "page_01.svg", "page_01.nc"):
        (package_dir / name).write_text(name, encoding="utf-8")
    (package_dir / "logs").mkdir()
    (package_dir / "pages").mkdir()

    mod._copy_source_pdf_to_package(package_dir, source_pdf=source_pdf)

    assert {"page_01.pdf", "page_01.gcode", "report.json", "summary.csv", "logs", "pages", "Task Name.pdf"} <= {
        item.name for item in package_dir.iterdir()
    }


def test_copy_source_pdf_to_package_keeps_a3_audit_files(tmp_path: Path) -> None:
    package_dir = tmp_path / "Task Name"
    package_dir.mkdir(parents=True)
    source_pdf = tmp_path / "Task Name.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    for name in (
        "pass_01.pdf",
        "pass_01.gcode",
        "pass_02.pdf",
        "pass_02.gcode",
        "combined_preview.pdf",
        "report.json",
    ):
        (package_dir / name).write_text(name, encoding="utf-8")
    (package_dir / "logs").mkdir()

    mod._copy_source_pdf_to_package(package_dir, source_pdf=source_pdf)

    assert {
        "pass_01.pdf",
        "pass_01.gcode",
        "pass_02.pdf",
        "pass_02.gcode",
        "combined_preview.pdf",
        "report.json",
        "logs",
        "Task Name.pdf",
    } <= {item.name for item in package_dir.iterdir()}


def test_iter_variant_dirs_skips_service_folders_by_default(tmp_path: Path) -> None:
    variant = tmp_path / "9 вариант"
    service = tmp_path / "новый тест букв"
    empty = tmp_path / "Маховики"
    variant.mkdir()
    service.mkdir()
    empty.mkdir()

    assert mod._iter_variant_dirs(tmp_path, set()) == [variant]
    assert mod._iter_variant_dirs(tmp_path, {service.name.casefold()}) == [service]
