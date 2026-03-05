from __future__ import annotations

import unittest
from typing import List, Tuple

from src.plotter_backend.geometry import fitting as fitting_mod


class GeometryFittingModuleTests(unittest.TestCase):
    def test_fit_returns_input_when_disabled(self) -> None:
        src = [[(0.0, 0.0), (10.0, 10.0)]]
        out = fitting_mod.fit_polylines_to_area(
            src,
            0.0,
            10.0,
            0.0,
            10.0,
            fit_to_work_area=False,
            work_area_bounds_fn=lambda: (0.0, 100.0, 0.0, 100.0),
            work_area_margin=0.0,
            allow_upscale_to_work_area=False,
            exact_geometry_mode=False,
            min_fit_scale_for_dimensional_draw=0.8,
            pass_cols=1,
            pass_rows=1,
            compute_pass_shift_fn=lambda *_: (0.0, 0.0, {}),
            logger=None,
        )
        self.assertIs(out, src)

    def test_fit_scales_and_centers_to_work_area(self) -> None:
        src = [[(0.0, 0.0), (200.0, 100.0)]]
        out = fitting_mod.fit_polylines_to_area(
            src,
            0.0,
            200.0,
            0.0,
            100.0,
            fit_to_work_area=True,
            work_area_bounds_fn=lambda: (0.0, 100.0, 0.0, 100.0),
            work_area_margin=0.0,
            allow_upscale_to_work_area=True,
            exact_geometry_mode=False,
            min_fit_scale_for_dimensional_draw=0.8,
            pass_cols=1,
            pass_rows=1,
            compute_pass_shift_fn=lambda *_: (0.0, 0.0, {}),
            logger=None,
        )
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0][0][0], 0.0, places=6)
        self.assertAlmostEqual(out[0][0][1], 25.0, places=6)
        self.assertAlmostEqual(out[0][1][0], 100.0, places=6)
        self.assertAlmostEqual(out[0][1][1], 75.0, places=6)

    def test_fit_uses_dimensional_guard_when_threshold_triggered(self) -> None:
        src = [[(0.0, 0.0), (300.0, 100.0)]]
        logs: List[str] = []
        out = fitting_mod.fit_polylines_to_area(
            src,
            0.0,
            300.0,
            0.0,
            100.0,
            fit_to_work_area=True,
            work_area_bounds_fn=lambda: (0.0, 100.0, 0.0, 100.0),
            work_area_margin=0.0,
            allow_upscale_to_work_area=True,
            exact_geometry_mode=True,
            min_fit_scale_for_dimensional_draw=0.5,
            pass_cols=1,
            pass_rows=1,
            compute_pass_shift_fn=lambda *_: (0.0, 0.0, {}),
            logger=logs.append,
        )
        self.assertEqual(out[0][0], (-100.0, 0.0))
        self.assertEqual(out[0][1], (200.0, 100.0))
        self.assertTrue(any("Fit guard (1:1 mm)" in msg for msg in logs))

    def test_fit_applies_pass_shift_for_multi_pass(self) -> None:
        calls: List[Tuple[float, float, float, float]] = []

        def _pass_shift(src_w: float, src_h: float, win_w: float, win_h: float):
            calls.append((src_w, src_h, win_w, win_h))
            return 10.0, -5.0, {
                "col": 2,
                "cols": 2,
                "row": 1,
                "rows": 1,
                "src_w": src_w,
                "src_h": src_h,
                "win_w": win_w,
                "win_h": win_h,
                "sx": 100.0,
                "sy": 0.0,
            }

        src = [[(0.0, 0.0), (100.0, 50.0)]]
        out = fitting_mod.fit_polylines_to_area(
            src,
            0.0,
            100.0,
            0.0,
            50.0,
            fit_to_work_area=True,
            work_area_bounds_fn=lambda: (0.0, 100.0, 0.0, 100.0),
            work_area_margin=0.0,
            allow_upscale_to_work_area=False,
            exact_geometry_mode=False,
            min_fit_scale_for_dimensional_draw=0.5,
            pass_cols=2,
            pass_rows=1,
            compute_pass_shift_fn=_pass_shift,
            logger=None,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (100.0, 50.0, 100.0, 100.0))
        self.assertEqual(out[0][0], (10.0, 20.0))
        self.assertEqual(out[0][1], (110.0, 70.0))


if __name__ == "__main__":
    unittest.main()
