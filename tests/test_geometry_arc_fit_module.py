from __future__ import annotations

import math
import unittest

from src.plotter_backend.geometry import arc_fit as arc_fit_mod


class GeometryArcFitModuleTests(unittest.TestCase):
    def test_solve_3x3(self) -> None:
        mat = [
            [1.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 4.0],
        ]
        vec = [3.0, 8.0, 20.0]
        sol = arc_fit_mod.solve_3x3(mat, vec)
        self.assertEqual(sol, (3.0, 4.0, 5.0))

    def test_fit_circle_kasa(self) -> None:
        pts = [
            (1.0, 0.0),
            (0.0, 1.0),
            (-1.0, 0.0),
            (0.0, -1.0),
        ]
        fit = arc_fit_mod.fit_circle_kasa(pts)
        self.assertIsNotNone(fit)
        cx, cy, r, max_err = fit or (999.0, 999.0, 999.0, 999.0)
        self.assertAlmostEqual(cx, 0.0, places=6)
        self.assertAlmostEqual(cy, 0.0, places=6)
        self.assertAlmostEqual(r, 1.0, places=6)
        self.assertLessEqual(max_err, 1e-6)

    def test_unwrap_angles(self) -> None:
        wrapped = [math.radians(170.0), math.radians(-175.0), math.radians(-170.0)]
        out = arc_fit_mod.unwrap_angles(wrapped)
        self.assertEqual(len(out), 3)
        self.assertGreater(out[1], out[0])
        self.assertGreater(out[2], out[1])

    def test_polyline_is_near_line(self) -> None:
        near_line = [(0.0, 0.0), (1.0, 0.01), (2.0, -0.01), (3.0, 0.0)]
        bent = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
        self.assertTrue(arc_fit_mod.polyline_is_near_line(near_line, tol_mm=0.05))
        self.assertFalse(arc_fit_mod.polyline_is_near_line(bent, tol_mm=0.05))

    def test_polyline_fit_arc(self) -> None:
        pts = []
        for deg in range(0, 91, 15):
            a = math.radians(float(deg))
            pts.append((10.0 * math.cos(a), 10.0 * math.sin(a)))
        fit = arc_fit_mod.polyline_fit_arc(
            pts,
            tol_mm=0.2,
            arc_min_radius_mm=1.0,
            arc_min_sweep_deg=10.0,
        )
        self.assertIsNotNone(fit)
        cw, center, radius, sweep = fit or (False, (999.0, 999.0), 0.0, 0.0)
        self.assertFalse(cw)
        self.assertAlmostEqual(center[0], 0.0, places=1)
        self.assertAlmostEqual(center[1], 0.0, places=1)
        self.assertAlmostEqual(radius, 10.0, places=1)
        self.assertGreater(sweep, 0.0)

    def test_arc_extents_xy(self) -> None:
        x_min, x_max, y_min, y_max = arc_fit_mod.arc_extents_xy(
            start=(1.0, 0.0),
            end=(0.0, 1.0),
            center=(0.0, 0.0),
            cw=False,
        )
        self.assertAlmostEqual(x_min, 0.0, places=6)
        self.assertAlmostEqual(x_max, 1.0, places=6)
        self.assertAlmostEqual(y_min, 0.0, places=6)
        self.assertAlmostEqual(y_max, 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
