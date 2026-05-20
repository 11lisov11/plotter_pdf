from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import prepare_computer_graphics_variants as mod


def test_prune_package_outputs_keeps_only_a4_files_and_original(tmp_path: Path) -> None:
    package_dir = tmp_path / "Task Name"
    package_dir.mkdir(parents=True)
    source_pdf = tmp_path / "Task Name.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    for name in ("page_01.pdf", "page_01.gcode", "report.json", "summary.csv", "page_01.svg", "page_01.nc"):
        (package_dir / name).write_text(name, encoding="utf-8")
    (package_dir / "logs").mkdir()
    (package_dir / "pages").mkdir()

    mod._prune_package_outputs(package_dir, is_a3=False, source_pdf=source_pdf)

    assert {item.name for item in package_dir.iterdir()} == {"page_01.pdf", "page_01.gcode", "Task Name.pdf"}


def test_prune_package_outputs_keeps_only_a3_files_and_original(tmp_path: Path) -> None:
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

    mod._prune_package_outputs(package_dir, is_a3=True, source_pdf=source_pdf)

    assert {item.name for item in package_dir.iterdir()} == {
        "pass_01.pdf",
        "pass_01.gcode",
        "pass_02.pdf",
        "pass_02.gcode",
        "Task Name.pdf",
    }


def test_prune_package_outputs_keeps_custom_tiled_passes_and_preview(tmp_path: Path) -> None:
    package_dir = tmp_path / "Task Name"
    package_dir.mkdir(parents=True)
    source_pdf = tmp_path / "Task Name.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    for name in (
        "pass_01.pdf",
        "pass_01.gcode",
        "pass_02.pdf",
        "pass_02.gcode",
        "pass_03.pdf",
        "pass_03.gcode",
        "combined_preview.pdf",
        "combined_preview.svg",
        "report.json",
        "summary.csv",
    ):
        (package_dir / name).write_text(name, encoding="utf-8")
    (package_dir / "logs").mkdir()

    mod._prune_package_outputs(package_dir, is_a3=True, is_custom_tiled=True, source_pdf=source_pdf)

    assert {item.name for item in package_dir.iterdir()} == {
        "pass_01.pdf",
        "pass_01.gcode",
        "pass_02.pdf",
        "pass_02.gcode",
        "pass_03.pdf",
        "pass_03.gcode",
        "combined_preview.pdf",
        "Task Name.pdf",
    }
