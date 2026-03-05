from __future__ import annotations

import math
import unittest

from src.plotter_backend.geometry import hatching as hatching_mod


class GeometryHatchingModuleTests(unittest.TestCase):
    def test_polygon_area_and_bbox(self) -> None:
        square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
        self.assertAlmostEqual(hatching_mod.polygon_area(square), 4.0, places=6)
        self.assertEqual(hatching_mod.polygon_bbox(square), (0.0, 2.0, 0.0, 2.0))

    def test_rotate_helpers(self) -> None:
        p = hatching_mod.rotate_point((1.0, 0.0), math.pi / 2.0)
        self.assertAlmostEqual(p[0], 0.0, places=6)
        self.assertAlmostEqual(p[1], -1.0, places=6)
        poly = hatching_mod.rotate_polyline([(1.0, 0.0), (0.0, 1.0)], 0.0)
        self.assertEqual(poly, [(1.0, 0.0), (0.0, 1.0)])

    def test_intersects_for_scanline(self) -> None:
        edges = [
            ((0.0, 0.0), (2.0, 0.0)),
            ((2.0, 0.0), (2.0, 2.0)),
            ((2.0, 2.0), (0.0, 2.0)),
            ((0.0, 2.0), (0.0, 0.0)),
        ]
        xs = hatching_mod.intersects_for_scanline(edges, 1.0)
        self.assertEqual(xs, [0.0, 2.0])

    def test_should_hatch_polygon(self) -> None:
        closed_square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0)]
        self.assertTrue(
            hatching_mod.should_hatch_polygon(
                closed_square,
                True,
                fill_hatch_enabled=True,
                fill_hatch_min_area_mm2=1.0,
                fill_hatch_min_side_mm=0.5,
            )
        )
        self.assertFalse(
            hatching_mod.should_hatch_polygon(
                closed_square,
                True,
                fill_hatch_enabled=False,
                fill_hatch_min_area_mm2=1.0,
                fill_hatch_min_side_mm=0.5,
            )
        )

    def test_hatch_polygon(self) -> None:
        square = [(0.0, 0.0), (3.0, 0.0), (3.0, 2.0), (0.0, 2.0), (0.0, 0.0)]
        out = hatching_mod.hatch_polygon(
            [square],
            spacing=0.5,
            angle_deg=0.0,
            min_segment=0.2,
        )
        self.assertTrue(out)
        self.assertTrue(all(len(seg) == 2 for seg in out))

    def test_hatch_polygon_rejects_non_positive_spacing(self) -> None:
        square = [(0.0, 0.0), (3.0, 0.0), (3.0, 2.0), (0.0, 2.0), (0.0, 0.0)]
        self.assertEqual(
            hatching_mod.hatch_polygon([square], spacing=0.0, angle_deg=0.0, min_segment=0.2),
            [],
        )


if __name__ == "__main__":
    unittest.main()

