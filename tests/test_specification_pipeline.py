from __future__ import annotations

from pathlib import Path

import fitz

from scripts import prepare_plotter_ready_new_algorithm as algorithm


def test_specification_format_header_is_not_filtered_as_service_text() -> None:
    line = {
        "text": "Формат",
        "bbox_mm": [20.8, 8.4, 26.2, 18.0],
    }

    assert algorithm._is_service_text(line, []) is False


def test_bottom_format_label_remains_service_text() -> None:
    line = {
        "text": "Формат A4",
        "bbox_mm": [165.0, 291.0, 205.0, 296.0],
    }

    assert algorithm._is_service_text(line, []) is True


def test_specification_clean_background_requires_reliable_text_layer(tmp_path: Path) -> None:
    logs: list[str] = []

    result = algorithm._specification_clean_background_from_source(
        tmp_path / "not-opened.pdf",
        [],
        logs,
    )

    assert result is None
    assert any("no reliable extractable text" in entry for entry in logs)


def test_specification_does_not_reuse_stale_clean_source(tmp_path: Path) -> None:
    pack = tmp_path / "Спецификация_pack"
    pack.mkdir()
    source = pack / "source.pdf"
    stale = pack / "a4_clean_source.pdf"
    source.write_bytes(b"source")
    stale.write_bytes(b"stale")

    selected = algorithm._clean_source_background_for_pack(pack, source, {})

    assert selected is None


def test_specification_clean_background_removes_vector_text_residue(tmp_path: Path) -> None:
    source = tmp_path / "specification.pdf"
    document = fitz.open()
    page = document.new_page(width=595.0, height=842.0)
    page.draw_line(fitz.Point(40.0, 120.0), fitz.Point(555.0, 120.0))
    page.draw_line(fitz.Point(80.0, 52.0), fitz.Point(105.0, 48.0))
    page.insert_text(fitz.Point(78.0, 58.0), "Details", fontsize=14.0)
    document.save(source)
    document.close()

    text_lines, _found, _skipped = algorithm._text_lines_for_source(source)
    logs: list[str] = []
    result = algorithm._specification_clean_background_from_source(source, text_lines, logs)

    assert result is not None
    geometry, meta, _page_w_mm, _page_h_mm = result
    assert meta["removed_background_text_segments"] >= 1
    assert any(
        abs(polyline[0][1] - polyline[-1][1]) <= 0.05
        and abs(polyline[-1][0] - polyline[0][0]) >= 150.0
        for polyline in geometry
    )


def test_underlined_specification_heading_keeps_horizontal_position() -> None:
    geometry = [
        [(110.0, 25.0), (180.0, 25.0)],
        [(122.0, 38.0), (164.0, 38.0)],
        [(110.0, 45.0), (180.0, 45.0)],
    ]
    lines = [
        {
            "text": "Детали",
            "bbox_mm": [126.0, 30.0, 160.0, 36.0],
        }
    ]
    rules = algorithm._horizontal_table_rules_from_polylines(geometry)
    logs: list[str] = []

    adjusted_geometry, adjusted_lines = algorithm._adjust_specification_underlined_heading_layout(
        geometry,
        lines,
        rules,
        logs,
    )

    assert adjusted_lines[0]["bbox_mm"][0] == 126.0
    assert adjusted_lines[0]["bbox_mm"][2] == 160.0
    assert adjusted_geometry[1][0][0] == 122.0
    assert adjusted_geometry[1][1][0] == 164.0
    heading_center = (adjusted_lines[0]["bbox_mm"][1] + adjusted_lines[0]["bbox_mm"][3]) * 0.5
    underline_y = adjusted_geometry[1][0][1]
    assert 25.0 < heading_center < 45.0
    assert underline_y > adjusted_lines[0]["bbox_mm"][3]


def test_specification_name_and_quantity_are_split_into_columns() -> None:
    lines = [
        {
            "text": "Втулка 1",
            "bbox_mm": [111.0, 85.2, 180.56, 92.5],
        },
        {
            "text": "1",
            "bbox_mm": [176.6, 77.2, 180.56, 84.5],
        },
        {
            "text": "Винт М16",
            "bbox_mm": [111.0, 101.2, 133.0, 108.5],
        },
    ]

    split = algorithm._split_specification_name_quantity_lines(lines)

    assert [line["text"] for line in split] == ["Втулка", "1", "1", "Винт М16"]
    assert split[0]["bbox_mm"][2] <= 169.5
    assert split[1]["bbox_mm"][0] == 176.6
    assert split[1]["bbox_mm"][2] == 180.56


def test_specification_long_name_keeps_internal_numbers_and_splits_trailing_quantity() -> None:
    lines = [
        {
            "text": "Картон А1 ГОСТ 9774-74 1",
            "bbox_mm": [111.0, 149.2, 180.56, 156.5],
        }
    ]

    split = algorithm._split_specification_name_quantity_lines(lines)

    assert [line["text"] for line in split] == ["Картон А1 ГОСТ 9774-74", "1"]
    assert split[0]["bbox_mm"][2] <= 169.5
    assert split[1]["bbox_mm"][0] >= 170.0


def test_specification_fit_uses_physical_page_when_geometry_has_missing_gutter(tmp_path: Path) -> None:
    source = tmp_path / "Спецификация_pack" / "source.pdf"
    build = algorithm.SourceBuild(
        source_pdf=source,
        page_w_mm=210.0,
        page_h_mm=297.0,
        polylines=[
            [(20.0, 0.0), (205.0, 0.0)],
            [(205.0, 0.0), (205.0, 297.0)],
            [(205.0, 297.0), (20.0, 297.0)],
        ],
        geometry_polylines=3,
        text_polylines=0,
        text_lines_found=0,
        text_lines_rendered=0,
        text_lines_skipped=0,
        missing_chars=[],
        logs=[],
        artifacts={},
    )

    final_polylines, fit_meta = algorithm._prepare_a4_page(build, algorithm.Settings(), [])

    assert fit_meta["content_scale"] <= round(180.0 / 210.0, 6)
    assert fit_meta["source_page_fit_bbox"] == [0.0, 0.0, 210.0, 297.0]
    bounds = algorithm._bounds(final_polylines)
    assert bounds[2] - bounds[0] < 180.0


def test_specification_preview_is_drawn_from_final_nc_in_paper_orientation(tmp_path: Path) -> None:
    nc_path = tmp_path / "plotter.nc"
    nc_path.write_text(
        "\n".join(
            [
                "G90",
                "G0 Z0.000",
                "G0 X10.000 Y-20.000",
                "G1 Z11.900",
                "G1 X30.000 Y-20.000",
                "G0 Z0.000",
            ]
        ),
        encoding="utf-8",
    )
    preview_path = tmp_path / "plot_preview.pdf"

    algorithm._write_specification_preview_from_final_gcode(
        nc_path,
        preview_path,
        algorithm.Settings(),
    )

    with fitz.open(preview_path) as document:
        page = document[0]
        assert abs(page.rect.width * algorithm.lff_text.PT_TO_MM - 180.0) < 0.1
        assert abs(page.rect.height * algorithm.lff_text.PT_TO_MM - 280.0) < 0.1
        drawings = page.get_drawings()
        assert drawings
        assert any(drawing["rect"].width > 0.0 for drawing in drawings)
