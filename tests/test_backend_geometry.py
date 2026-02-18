from __future__ import annotations

import unittest

from src import plotter_pdf_drawer as backend


class BackendGeometryTests(unittest.TestCase):
    def test_compute_pass_shift_for_two_columns(self) -> None:
        old = (backend.PASS_COLS, backend.PASS_ROWS, backend.PASS_COL, backend.PASS_ROW)
        try:
            backend.PASS_COLS = 2
            backend.PASS_ROWS = 1
            backend.PASS_ROW = 1

            backend.PASS_COL = 1
            shift_x_1, shift_y_1, info_1 = backend.compute_pass_shift(
                source_w_mm=400.0,
                source_h_mm=280.0,
                window_w_mm=200.0,
                window_h_mm=280.0,
            )
            backend.PASS_COL = 2
            shift_x_2, shift_y_2, info_2 = backend.compute_pass_shift(
                source_w_mm=400.0,
                source_h_mm=280.0,
                window_w_mm=200.0,
                window_h_mm=280.0,
            )

            self.assertEqual(info_1["col"], 1)
            self.assertEqual(info_2["col"], 2)
            self.assertAlmostEqual(shift_y_1, 0.0, places=6)
            self.assertAlmostEqual(shift_y_2, 0.0, places=6)
            self.assertAlmostEqual(shift_x_1, -shift_x_2, places=6)
            self.assertGreater(shift_x_1, 0.0)
            self.assertLess(shift_x_2, 0.0)
        finally:
            backend.PASS_COLS, backend.PASS_ROWS, backend.PASS_COL, backend.PASS_ROW = old

    def test_plan_tiled_passes_reports_two_pass_scale(self) -> None:
        plan = backend.plan_tiled_passes_for_sheet(420.0, 297.0)
        self.assertIn("max_two_pass_scale", plan)
        self.assertGreater(float(plan["max_two_pass_scale"]), 0.0)
        self.assertIn("nx", plan)
        self.assertIn("ny", plan)


if __name__ == "__main__":
    unittest.main()
