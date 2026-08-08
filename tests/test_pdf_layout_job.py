from __future__ import annotations

import json
from pathlib import Path

import fitz

from src.plotter_backend.jobs.models import JobSettings
from src.plotter_backend.jobs.pdf_layout import MM_TO_PT, build_pdf_layout


def _make_pdf(path: Path, width_mm: float, height_mm: float, label: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=width_mm * MM_TO_PT, height=height_mm * MM_TO_PT)
    page.draw_rect(page.rect, color=(0, 0, 0), width=1)
    page.insert_text(fitz.Point(20, 30), label, fontsize=14)
    doc.save(path)
    doc.close()


def test_a3_auto_layout_places_two_a4_pages_side_by_side(tmp_path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _make_pdf(first, 210.0, 297.0, "first")
    _make_pdf(second, 210.0, 297.0, "second")
    build = build_pdf_layout(
        JobSettings(
            input_paths=[str(first), str(second)],
            input_pages=[0, 0],
            input_rotations=[0, 180],
            output_dir=tmp_path,
            sheet_format="a3",
            layout_mode="auto",
        )
    )
    assert build.page_count == 1
    assert build.output_pdf.exists()
    assert build.preview_pdf.exists()
    manifest = json.loads(build.manifest_path.read_text(encoding="utf-8"))
    assert manifest["placements"][0]["grid"]["cols"] == 2
    assert manifest["placements"][0]["grid"]["rows"] == 1
    assert manifest["placements"][1]["rotation_deg"] == 180
    with fitz.open(build.output_pdf) as doc:
        assert doc.page_count == 1
        assert abs(doc[0].rect.width / MM_TO_PT - 420.0) < 0.01
        assert abs(doc[0].rect.height / MM_TO_PT - 297.0) < 0.01


def test_a2_auto_layout_stacks_two_a3_pages(tmp_path) -> None:
    paths = []
    for index in range(2):
        path = tmp_path / f"a3_{index}.pdf"
        _make_pdf(path, 420.0, 297.0, str(index))
        paths.append(str(path))
    build = build_pdf_layout(
        JobSettings(input_paths=paths, input_pages=[0, 0], input_rotations=[0, 0], output_dir=tmp_path, sheet_format="a2")
    )
    manifest = json.loads(build.manifest_path.read_text(encoding="utf-8"))
    assert manifest["placements"][0]["grid"]["cols"] == 1
    assert manifest["placements"][0]["grid"]["rows"] == 2
    for placement in manifest["placements"]:
        x0, y0, x1, y1 = placement["content_rect_mm"]
        assert 0.0 <= x0 <= x1 <= 420.0
        assert 0.0 <= y0 <= y1 <= 594.0


def test_a4_layout_paginates_multiple_inputs(tmp_path) -> None:
    paths = []
    for index in range(2):
        path = tmp_path / f"page_{index}.pdf"
        _make_pdf(path, 210.0, 297.0, str(index))
        paths.append(str(path))
    build = build_pdf_layout(JobSettings(input_paths=paths, output_dir=tmp_path, sheet_format="a4"))
    assert build.page_count == 2
    assert len(build.page_pdf_paths) == 2
    assert all(path.exists() for path in build.page_pdf_paths)
