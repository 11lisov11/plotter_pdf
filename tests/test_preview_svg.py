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


if __name__ == "__main__":
    unittest.main()
