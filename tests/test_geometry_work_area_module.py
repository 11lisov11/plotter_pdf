from __future__ import annotations

import unittest

from src.plotter_backend.geometry import work_area as work_area_mod


class GeometryWorkAreaModuleTests(unittest.TestCase):
    def test_base_work_area_bounds_normalizes_axes_with_offsets(self) -> None:
        bounds = work_area_mod.base_work_area_bounds(
            work_area_min_x=180.0,
            work_area_max_x=0.0,
            work_area_min_y=0.0,
            work_area_max_y=-280.0,
            work_offset_x_mm=2.0,
            work_offset_y_mm=-3.0,
        )
        self.assertEqual(bounds, (2.0, 182.0, -283.0, -3.0))

    def test_work_area_bounds_prefers_active_and_normalizes_order(self) -> None:
        bounds = work_area_mod.work_area_bounds(
            active_work_area_bounds=(100.0, 0.0, -10.0, -200.0),
            base_work_area_bounds_fn=lambda: (1.0, 2.0, 3.0, 4.0),
        )
        self.assertEqual(bounds, (0.0, 100.0, -200.0, -10.0))

    def test_work_area_bounds_uses_base_when_active_missing(self) -> None:
        bounds = work_area_mod.work_area_bounds(
            active_work_area_bounds=None,
            base_work_area_bounds_fn=lambda: (0.0, 180.0, -300.0, 0.0),
        )
        self.assertEqual(bounds, (0.0, 180.0, -300.0, 0.0))

    def test_configure_active_work_area_custom_center(self) -> None:
        bounds = work_area_mod.configure_active_work_area(
            sheet_format="custom",
            sheet_width_mm=100.0,
            sheet_height_mm=100.0,
            anchor="center",
            offset_x_mm=0.0,
            offset_y_mm=0.0,
            base_bounds=(0.0, 200.0, -300.0, 0.0),
            sheet_presets_mm={"work": None, "a4": (210.0, 297.0)},
            sheet_anchor_choices=("center", "lower_left", "upper_left", "lower_right", "upper_right"),
            logger=None,
        )
        self.assertEqual(bounds, (50.0, 150.0, -200.0, -100.0))

    def test_configure_active_work_area_uses_overlap_for_oversize_sheet(self) -> None:
        logs: list[str] = []
        bounds = work_area_mod.configure_active_work_area(
            sheet_format="custom",
            sheet_width_mm=400.0,
            sheet_height_mm=500.0,
            anchor="lower_left",
            offset_x_mm=12.0,
            offset_y_mm=8.0,
            base_bounds=(0.0, 200.0, -300.0, 0.0),
            sheet_presets_mm={"work": None, "a4": (210.0, 297.0)},
            sheet_anchor_choices=("center", "lower_left", "upper_left", "lower_right", "upper_right"),
            logger=logs.append,
        )
        self.assertEqual(bounds, (12.0, 200.0, -292.0, 0.0))
        self.assertTrue(any("larger than workspace" in msg for msg in logs))
        self.assertTrue(any("sheet_bounds" in msg for msg in logs))

    def test_configure_active_work_area_partial_overlap_for_shifted_sheet(self) -> None:
        bounds = work_area_mod.configure_active_work_area(
            sheet_format="custom",
            sheet_width_mm=100.0,
            sheet_height_mm=100.0,
            anchor="lower_left",
            offset_x_mm=150.0,
            offset_y_mm=0.0,
            base_bounds=(0.0, 200.0, -300.0, 0.0),
            sheet_presets_mm={"work": None, "a4": (210.0, 297.0)},
            sheet_anchor_choices=("center", "lower_left", "upper_left", "lower_right", "upper_right"),
            logger=None,
        )
        self.assertEqual(bounds, (150.0, 200.0, -300.0, -200.0))

    def test_configure_active_work_area_raises_when_sheet_has_no_overlap(self) -> None:
        with self.assertRaises(ValueError):
            work_area_mod.configure_active_work_area(
                sheet_format="custom",
                sheet_width_mm=100.0,
                sheet_height_mm=100.0,
                anchor="lower_left",
                offset_x_mm=250.0,
                offset_y_mm=0.0,
                base_bounds=(0.0, 200.0, -300.0, 0.0),
                sheet_presets_mm={"work": None, "a4": (210.0, 297.0)},
                sheet_anchor_choices=("center", "lower_left", "upper_left", "lower_right", "upper_right"),
                logger=None,
            )

    def test_configure_active_work_area_raises_on_unknown_format(self) -> None:
        with self.assertRaises(ValueError):
            work_area_mod.configure_active_work_area(
                sheet_format="bad_format",
                sheet_width_mm=None,
                sheet_height_mm=None,
                anchor="center",
                offset_x_mm=0.0,
                offset_y_mm=0.0,
                base_bounds=(0.0, 200.0, -300.0, 0.0),
                sheet_presets_mm={"work": None, "a4": (210.0, 297.0)},
                sheet_anchor_choices=("center", "lower_left", "upper_left", "lower_right", "upper_right"),
                logger=None,
            )

    def test_configure_active_work_area_raises_on_unknown_anchor(self) -> None:
        with self.assertRaises(ValueError):
            work_area_mod.configure_active_work_area(
                sheet_format="work",
                sheet_width_mm=None,
                sheet_height_mm=None,
                anchor="bad_anchor",
                offset_x_mm=0.0,
                offset_y_mm=0.0,
                base_bounds=(0.0, 200.0, -300.0, 0.0),
                sheet_presets_mm={"work": None, "a4": (210.0, 297.0)},
                sheet_anchor_choices=("center", "lower_left", "upper_left", "lower_right", "upper_right"),
                logger=None,
            )


if __name__ == "__main__":
    unittest.main()
