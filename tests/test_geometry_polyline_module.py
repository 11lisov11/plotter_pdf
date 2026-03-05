from __future__ import annotations

import unittest

from src.plotter_backend.geometry import polyline as polyline_mod


class GeometryPolylineModuleTests(unittest.TestCase):
    def test_points_distance(self) -> None:
        self.assertAlmostEqual(polyline_mod.points_distance((0.0, 0.0), (3.0, 4.0)), 5.0, places=6)

    def test_polyline_length_for_short_and_regular_polyline(self) -> None:
        self.assertEqual(polyline_mod.polyline_length([]), 0.0)
        self.assertEqual(polyline_mod.polyline_length([(1.0, 2.0)]), 0.0)
        length = polyline_mod.polyline_length([(0.0, 0.0), (3.0, 4.0), (6.0, 8.0)])
        self.assertAlmostEqual(length, 10.0, places=6)

    def test_total_draw_length_mm_ignores_single_point_items(self) -> None:
        total = polyline_mod.total_draw_length_mm(
            [
                [(0.0, 0.0), (0.0, 2.0)],
                [(5.0, 5.0)],
                [(0.0, 0.0), (3.0, 4.0)],
            ]
        )
        self.assertAlmostEqual(total, 7.0, places=6)

    def test_bounds_polylines(self) -> None:
        b = polyline_mod.bounds_polylines(
            [
                [(-1.0, 2.0), (3.0, 5.0)],
                [(10.0, -4.0), (6.0, 7.0)],
            ]
        )
        self.assertEqual(b, (-1.0, 10.0, -4.0, 7.0))
        self.assertEqual(polyline_mod.bounds_polylines([]), (0.0, 0.0, 0.0, 0.0))

    def test_translate_polylines(self) -> None:
        src = [[(0.0, 0.0), (2.0, 3.0)], [(-1.0, 5.0)]]
        shifted = polyline_mod.translate_polylines(src, 1.5, -2.0)
        self.assertEqual(shifted, [[(1.5, -2.0), (3.5, 1.0)], [(0.5, 3.0)]])
        self.assertEqual(polyline_mod.translate_polylines(src, 0.0, 0.0), src)


if __name__ == "__main__":
    unittest.main()
