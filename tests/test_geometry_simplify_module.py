from __future__ import annotations

import unittest

from src.plotter_backend.geometry import simplify as simplify_mod


class GeometrySimplifyModuleTests(unittest.TestCase):
    def test_point_line_distance_handles_degenerate_segment(self) -> None:
        d = simplify_mod.point_line_distance((3.0, 4.0), (0.0, 0.0), (0.0, 0.0))
        self.assertAlmostEqual(d, 5.0, places=6)

    def test_path_is_closed(self) -> None:
        closed = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)]
        open_poly = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        self.assertTrue(simplify_mod.path_is_closed(closed))
        self.assertFalse(simplify_mod.path_is_closed(open_poly))

    def test_rdp_simplify_open_reduces_near_line(self) -> None:
        poly = [(0.0, 0.0), (1.0, 0.01), (2.0, -0.01), (3.0, 0.0)]
        out = simplify_mod.rdp_simplify_open(poly, eps=0.05)
        self.assertEqual(out, [(0.0, 0.0), (3.0, 0.0)])

    def test_rdp_simplify_polyline_keeps_closed_ring(self) -> None:
        poly = [
            (0.0, 0.0),
            (1.0, 0.0),
            (2.0, 0.0),
            (2.0, 1.0),
            (2.0, 2.0),
            (1.0, 2.0),
            (0.0, 2.0),
            (0.0, 1.0),
            (0.0, 0.0),
        ]
        out = simplify_mod.rdp_simplify_polyline(poly, eps=0.2)
        self.assertGreaterEqual(len(out), 4)
        self.assertEqual(out[0], out[-1])
        self.assertLessEqual(len(out), len(poly))

    def test_simplify_polyline_removes_small_backtrack_spike(self) -> None:
        poly = [(0.0, 0.0), (0.05, 0.0), (0.0, 0.0), (1.0, 0.0)]
        out = simplify_mod.simplify_polyline(
            poly,
            eps=1e-6,
            simplify_enabled=True,
            default_collinear_eps=0.0,
            backtrack_spike_max_mm=0.1,
        )
        self.assertEqual(out, [(0.0, 0.0), (1.0, 0.0)])

    def test_simplify_polyline_collinear_override(self) -> None:
        poly = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (2.0, 0.0)]
        out = simplify_mod.simplify_polyline(
            poly,
            eps=1e-6,
            collinear_eps=0.001,
            simplify_enabled=True,
            default_collinear_eps=0.1,
            backtrack_spike_max_mm=0.0,
        )
        self.assertEqual(out, [(0.0, 0.0), (2.0, 0.0)])


if __name__ == "__main__":
    unittest.main()

