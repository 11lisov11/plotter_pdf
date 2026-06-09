from __future__ import annotations

import unittest

from src.plotter_backend.geometry import sheet_tiling as tiling_mod


class GeometrySheetTilingModuleTests(unittest.TestCase):
    def test_plan_tiled_passes_for_sheet(self) -> None:
        plan = tiling_mod.plan_tiled_passes_for_sheet(420.0, 297.0, area_w_mm=200.0, area_h_mm=280.0)
        self.assertIn("nx", plan)
        self.assertIn("ny", plan)
        self.assertIn("max_two_pass_scale", plan)
        self.assertGreater(float(plan["max_two_pass_scale"]), 0.0)

    def test_resolve_sheet_size_mm_custom_and_preset(self) -> None:
        presets = {"work": None, "a4": (210.0, 297.0)}
        self.assertEqual(
            tiling_mod.resolve_sheet_size_mm(
                sheet_format="custom",
                sheet_width_mm=100.0,
                sheet_height_mm=200.0,
                sheet_presets_mm=presets,
                work_area_size_mm=(160.0, 200.0),
            ),
            (100.0, 200.0),
        )
        self.assertEqual(
            tiling_mod.resolve_sheet_size_mm(
                sheet_format="a4",
                sheet_width_mm=None,
                sheet_height_mm=None,
                sheet_presets_mm=presets,
                work_area_size_mm=(160.0, 200.0),
            ),
            (210.0, 297.0),
        )
        self.assertEqual(
            tiling_mod.resolve_sheet_size_mm(
                sheet_format="work",
                sheet_width_mm=None,
                sheet_height_mm=None,
                sheet_presets_mm=presets,
                work_area_size_mm=(160.0, 200.0),
            ),
            (160.0, 200.0),
        )

    def test_resolve_sheet_size_mm_raises_for_invalid_cases(self) -> None:
        presets = {"work": None}
        with self.assertRaises(ValueError):
            tiling_mod.resolve_sheet_size_mm(
                sheet_format="custom",
                sheet_width_mm=None,
                sheet_height_mm=200.0,
                sheet_presets_mm=presets,
                work_area_size_mm=(160.0, 200.0),
            )
        with self.assertRaises(ValueError):
            tiling_mod.resolve_sheet_size_mm(
                sheet_format="unknown",
                sheet_width_mm=None,
                sheet_height_mm=None,
                sheet_presets_mm=presets,
                work_area_size_mm=(160.0, 200.0),
            )

    def test_tile_window_start(self) -> None:
        self.assertAlmostEqual(tiling_mod.tile_window_start(400.0, 200.0, 0, 2), 0.0, places=6)
        self.assertAlmostEqual(tiling_mod.tile_window_start(400.0, 200.0, 1, 2), 200.0, places=6)
        self.assertAlmostEqual(tiling_mod.tile_window_start(400.0, 200.0, 5, 2), 200.0, places=6)

    def test_compute_pass_shift(self) -> None:
        shift_x_1, shift_y_1, info_1 = tiling_mod.compute_pass_shift(
            400.0,
            280.0,
            200.0,
            280.0,
            pass_cols=2,
            pass_rows=1,
            pass_col=1,
            pass_row=1,
        )
        shift_x_2, shift_y_2, info_2 = tiling_mod.compute_pass_shift(
            400.0,
            280.0,
            200.0,
            280.0,
            pass_cols=2,
            pass_rows=1,
            pass_col=2,
            pass_row=1,
        )
        self.assertEqual(info_1["col"], 1)
        self.assertEqual(info_2["col"], 2)
        self.assertAlmostEqual(shift_y_1, 0.0, places=6)
        self.assertAlmostEqual(shift_y_2, 0.0, places=6)
        self.assertAlmostEqual(shift_x_1, -shift_x_2, places=6)

    def test_sheet_pass_rotation_deg_requires_180_for_a3_second_pass(self) -> None:
        self.assertEqual(
            tiling_mod.sheet_pass_rotation_deg(
                sheet_format="a3",
                pass_cols=2,
                pass_rows=1,
                pass_col=2,
                pass_row=1,
            ),
            180,
        )

    def test_sheet_pass_rotation_deg_is_zero_for_other_passes(self) -> None:
        self.assertEqual(
            tiling_mod.sheet_pass_rotation_deg(
                sheet_format="a3",
                pass_cols=2,
                pass_rows=1,
                pass_col=1,
                pass_row=1,
            ),
            0,
        )

    def test_sheet_pass_post_translation_mm_requires_configured_a3_second_pass_shift(self) -> None:
        self.assertEqual(
            tiling_mod.sheet_pass_post_translation_mm(
                sheet_format="a3",
                pass_cols=2,
                pass_rows=1,
                pass_col=2,
                pass_row=1,
            ),
            (0.0, tiling_mod.A3_SECOND_PASS_POST_SHIFT_Y_MM),
        )
        self.assertEqual(tiling_mod.A3_SECOND_PASS_POST_SHIFT_Y_MM, 4.0)

    def test_sheet_pass_post_translation_mm_is_zero_for_other_passes(self) -> None:
        self.assertEqual(
            tiling_mod.sheet_pass_post_translation_mm(
                sheet_format="a3",
                pass_cols=2,
                pass_rows=1,
                pass_col=1,
                pass_row=1,
            ),
            (0.0, 0.0),
        )
        self.assertEqual(
            tiling_mod.sheet_pass_post_translation_mm(
                sheet_format="a4",
                pass_cols=2,
                pass_rows=1,
                pass_col=2,
                pass_row=1,
            ),
            (0.0, 0.0),
        )
        self.assertEqual(
            tiling_mod.sheet_pass_rotation_deg(
                sheet_format="a4",
                pass_cols=2,
                pass_rows=1,
                pass_col=2,
                pass_row=1,
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
