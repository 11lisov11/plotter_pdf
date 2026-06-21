from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import prepare_plotter_ready_new_algorithm as mod


def test_normalize_drawing_mode_auto_detects_nachert_root() -> None:
    root = Path("C:/plotter_pdf/\u041d\u0430\u0447\u0435\u0440\u0442/24 \u0432\u0430\u0440\u0438\u0430\u043d\u0442")

    assert mod._normalize_drawing_mode("auto", root) == "descriptive_geometry"
    assert mod._normalize_drawing_mode("computer_graphics", root) == "computer_graphics"
    assert mod._normalize_drawing_mode("nachert", None) == "descriptive_geometry"
    assert mod._is_descriptive_geometry_mode(mod.Settings(drawing_mode="descriptive_geometry"))
    assert mod._is_computer_graphics_mode(mod.Settings(drawing_mode="computer_graphics"))


def test_dimension_text_height_override_skips_title_block_zone() -> None:
    drawing_dimension = {"text": "R20", "bbox_mm": [50.0, 100.0, 62.0, 102.0], "size": 6.0}
    title_block_dimension = {"text": "R20", "bbox_mm": [150.0, 250.0, 162.0, 252.0], "size": 6.0}

    override = mod._dimension_text_box_height_override_mm(
        drawing_dimension,
        210.0,
        297.0,
        current_box_height_mm=2.0,
        fill=0.86,
    )

    assert override is not None
    assert override > 2.0
    assert (
        mod._dimension_text_box_height_override_mm(
            title_block_dimension,
            210.0,
            297.0,
            current_box_height_mm=2.0,
            fill=0.86,
        )
        is None
    )


def test_center_text_line_in_table_row_uses_neighbor_horizontal_rules() -> None:
    rules = [
        (0.0, 0.0, 50.0),
        (10.0, 0.0, 50.0),
        (20.0, 0.0, 50.0),
    ]
    line = {"text": "12", "bbox_mm": [5.0, 11.0, 20.0, 13.0], "dir": (1.0, 0.0)}

    centered = mod._center_text_line_in_table_row(line, rules)

    assert centered is not line
    assert centered["bbox_mm"] == [5.0, 14.0, 20.0, 16.0]
    assert centered["table_row_centered"]["row_band_mm"] == [10.0, 20.0]
