from __future__ import annotations

import unittest

from src.plotter_backend.geometry import svg_path


class SvgPathGeometryModuleTests(unittest.TestCase):
    def test_parse_path_tokens_parses_basic_sequence(self) -> None:
        tokens = list(svg_path.parse_path_tokens("M 0,0 L 10 5 20 8 z"))
        self.assertEqual(tokens[0][0], "M")
        self.assertEqual(tokens[0][1], [0.0, 0.0])
        self.assertEqual(tokens[1][0], "L")
        self.assertEqual(tokens[1][1], [10.0, 5.0, 20.0, 8.0])
        self.assertEqual(tokens[2], ("z", []))

    def test_parse_path_tokens_raises_on_coordinate_prefix(self) -> None:
        with self.assertRaises(ValueError):
            list(svg_path.parse_path_tokens("10 10 L 20 20"))

    def test_cubic_approx_returns_polyline_ending_at_target(self) -> None:
        pts = svg_path.cubic_approx(
            (0.0, 0.0),
            (0.0, 10.0),
            (10.0, 10.0),
            (10.0, 0.0),
            step=1.0,
        )
        self.assertGreaterEqual(len(pts), 2)
        self.assertAlmostEqual(pts[-1][0], 10.0, places=6)
        self.assertAlmostEqual(pts[-1][1], 0.0, places=6)

    def test_quadratic_approx_returns_polyline_ending_at_target(self) -> None:
        pts = svg_path.quadratic_approx(
            (0.0, 0.0),
            (5.0, 8.0),
            (10.0, 0.0),
            step=1.0,
        )
        self.assertGreaterEqual(len(pts), 2)
        self.assertAlmostEqual(pts[-1][0], 10.0, places=6)
        self.assertAlmostEqual(pts[-1][1], 0.0, places=6)

    def test_arc_to_polyline_returns_endpoint_on_zero_radius(self) -> None:
        pts = svg_path.arc_to_polyline(
            (0.0, 0.0),
            rx=0.0,
            ry=5.0,
            angle_deg=0.0,
            large_arc=0,
            sweep=1,
            p1=(7.0, 3.0),
        )
        self.assertEqual(pts, [(7.0, 3.0)])

    def test_arc_to_polyline_returns_empty_for_identical_endpoints(self) -> None:
        pts = svg_path.arc_to_polyline(
            (1.0, 2.0),
            rx=5.0,
            ry=5.0,
            angle_deg=0.0,
            large_arc=0,
            sweep=1,
            p1=(1.0, 2.0),
        )
        self.assertEqual(pts, [])

    def test_arc_to_polyline_generates_points_for_regular_arc(self) -> None:
        pts = svg_path.arc_to_polyline(
            (0.0, 0.0),
            rx=5.0,
            ry=5.0,
            angle_deg=0.0,
            large_arc=0,
            sweep=1,
            p1=(10.0, 0.0),
            step=0.5,
        )
        self.assertGreater(len(pts), 3)
        self.assertAlmostEqual(pts[-1][0], 10.0, places=3)
        self.assertAlmostEqual(pts[-1][1], 0.0, places=3)


if __name__ == "__main__":
    unittest.main()
