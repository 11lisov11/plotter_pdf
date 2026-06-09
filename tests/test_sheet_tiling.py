from __future__ import annotations

from src.plotter_backend.geometry.sheet_tiling import (
    A3_SECOND_PASS_POST_SHIFT_Y_MM,
    sheet_pass_post_translation_mm,
    sheet_pass_rotation_deg,
)


def test_a3_second_pass_canonical_transform() -> None:
    assert sheet_pass_rotation_deg(sheet_format="a3", pass_cols=2, pass_rows=1, pass_col=2, pass_row=1) == 180
    assert sheet_pass_post_translation_mm(
        sheet_format="a3",
        pass_cols=2,
        pass_rows=1,
        pass_col=2,
        pass_row=1,
    ) == (0.0, A3_SECOND_PASS_POST_SHIFT_Y_MM)
