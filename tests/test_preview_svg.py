from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plotter_studio.core import protocol


class PreviewSvgTests(unittest.TestCase):
    def test_gcode_to_polylines_respects_z_state(self) -> None:
        lines = [
            "G21",
            "G90",
            "G0 Z0",
            "G0 X0 Y0",
            "G1 Z10 F400",
            "G1 X10 Y0 F900",
            "G1 X10 Y10",
            "G0 Z0",
            "G0 X0 Y0",
        ]
        polylines = protocol._gcode_to_polylines(lines, z_up=0.0, z_down=10.0)
        self.assertEqual(len(polylines), 1)
        self.assertGreaterEqual(len(polylines[0]), 3)
        self.assertAlmostEqual(polylines[0][0][0], 0.0, places=4)
        self.assertAlmostEqual(polylines[0][-1][1], 10.0, places=4)

    def test_write_svg_preview_creates_valid_svg(self) -> None:
        polylines = [[(0.0, 0.0), (20.0, 0.0), (20.0, -15.0)]]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "preview.svg"
            protocol._write_svg_preview(polylines, out)
            text = out.read_text(encoding="utf-8")
            self.assertIn("<svg", text)
            self.assertIn("<path", text)
            self.assertIn("viewBox=", text)

    def test_gcode_to_polylines_ignores_partial_lift_travel(self) -> None:
        lines = [
            "G21",
            "G90",
            "G0 Z0",
            "G0 X0 Y0",
            "G1 Z12.0 F200",
            "G1 X10 Y0 F800",
            # Partial lift for travel (not full Z-up).
            "G1 Z9.0 F500",
            "G0 X40 Y40 F3000",
            "G1 Z12.0 F200",
            "G1 X50 Y40 F800",
            "G0 Z0",
        ]
        polylines = protocol._gcode_to_polylines(lines, z_up=0.0, z_down=12.0)
        self.assertEqual(len(polylines), 2)
        self.assertAlmostEqual(polylines[0][0][0], 0.0, places=4)
        self.assertAlmostEqual(polylines[0][-1][0], 10.0, places=4)
        self.assertAlmostEqual(polylines[1][0][0], 40.0, places=4)
        self.assertAlmostEqual(polylines[1][-1][0], 50.0, places=4)

    def test_gcode_to_polylines_supports_spindle_pen_mode(self) -> None:
        lines = [
            "G21",
            "G90",
            "G0 X0 Y0",
            "M3 S1000",
            "G1 X10 Y0 F800",
            "M5",
            "G0 X20 Y0",
            "M3 S1000",
            "G1 X30 Y0 F800",
            "M5",
        ]
        polylines = protocol._gcode_to_polylines(lines, z_up=0.0, z_down=12.0)
        self.assertEqual(len(polylines), 2)
        self.assertAlmostEqual(polylines[0][0][0], 0.0, places=4)
        self.assertAlmostEqual(polylines[0][-1][0], 10.0, places=4)
        self.assertAlmostEqual(polylines[1][0][0], 20.0, places=4)
        self.assertAlmostEqual(polylines[1][-1][0], 30.0, places=4)


if __name__ == "__main__":
    unittest.main()
