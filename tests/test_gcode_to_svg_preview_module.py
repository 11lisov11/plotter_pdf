from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import gcode_to_svg_preview as preview


class GcodeToSvgPreviewModuleTests(unittest.TestCase):
    def test_parse_words_handles_compact_grbl_words(self) -> None:
        words = preview._parse_words("G1X10.5Y-2.0F1.2e3M3S1000")  # type: ignore[attr-defined]

        self.assertEqual(words.get("X"), 10.5)
        self.assertEqual(words.get("Y"), -2.0)
        self.assertEqual(words.get("F"), 1200.0)
        self.assertEqual(words.get("S"), 1000.0)
        self.assertNotIn("G", words)
        self.assertNotIn("M", words)

    def test_split_comment_preserves_words_after_parenthetical_comment(self) -> None:
        body = preview._split_comment("G1 X10 (ignore X99) Y-2 ; tail")  # type: ignore[attr-defined]

        words = preview._parse_words(body)  # type: ignore[attr-defined]

        self.assertEqual(words.get("X"), 10.0)
        self.assertEqual(words.get("Y"), -2.0)

    def test_gcode_to_polylines_handles_compact_modal_spindle_gcode(self) -> None:
        lines = [
            "G90",
            "G0X0Y0",
            "M3S1000",
            "G1X10Y0",
            "X10Y5",
            "M5",
            "G0X20Y20",
        ]

        polylines = preview.gcode_to_polylines(lines, z_up=0.0, z_down=11.9)

        self.assertEqual(polylines, [[(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]])

    def test_gcode_to_polylines_keeps_coordinates_after_parenthetical_comment(self) -> None:
        lines = [
            "G90",
            "G0 X0 Y0",
            "M3",
            "G1 X10 (inline note) Y-2",
            "M5",
        ]

        polylines = preview.gcode_to_polylines(lines, z_up=0.0, z_down=11.9)

        self.assertEqual(polylines, [[(0.0, 0.0), (10.0, -2.0)]])

    def test_gcode_to_polylines_supports_r_word_arc_motion(self) -> None:
        lines = [
            "G90",
            "G0 X10 Y0",
            "M3",
            "G3 X0 Y10 R10",
            "M5",
        ]

        polylines = preview.gcode_to_polylines(lines, z_up=0.0, z_down=11.9)

        self.assertEqual(len(polylines), 1)
        self.assertGreater(len(polylines[0]), 2)
        self.assertAlmostEqual(polylines[0][0][0], 10.0, places=6)
        self.assertAlmostEqual(polylines[0][-1][0], 0.0, places=6)
        self.assertAlmostEqual(polylines[0][-1][1], 10.0, places=6)

    def test_gcode_to_polylines_treats_g92_as_coordinate_reset_not_motion(self) -> None:
        lines = [
            "G90",
            "G0 X10 Y0",
            "M3",
            "G1 X20 Y0",
            "G92 X0 Y100",
            "M5",
        ]

        polylines = preview.gcode_to_polylines(lines, z_up=0.0, z_down=11.9)

        self.assertEqual(polylines, [[(10.0, 0.0), (20.0, 0.0)]])

    def test_gcode_to_polylines_splits_polyline_after_g92_coordinate_reset(self) -> None:
        lines = [
            "G90",
            "G0 X10 Y0",
            "M3",
            "G1 X20 Y0",
            "G92 X0 Y0",
            "G1 X5 Y0",
            "M5",
        ]

        polylines = preview.gcode_to_polylines(lines, z_up=0.0, z_down=11.9)

        self.assertEqual(polylines, [[(10.0, 0.0), (20.0, 0.0)], [(0.0, 0.0), (5.0, 0.0)]])

    def test_main_writes_svg_for_compact_gcode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preview_compact_") as td:
            root = Path(td)
            gcode = root / "compact.nc"
            out = root / "compact.svg"
            gcode.write_text(
                "\n".join(
                    [
                        "G90",
                        "G0X0Y0",
                        "M3S1000",
                        "G1X10Y0",
                        "X10Y5",
                        "M5",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = preview.main(["gcode_to_svg_preview.py", str(gcode), "-o", str(out), "--z-up", "0", "--z-down", "11.9"])

            self.assertEqual(exit_code, 0)
            svg = out.read_text(encoding="utf-8")
            self.assertIn("<path", svg)
            self.assertIn("10.0000 -5.0000", svg)
            self.assertNotIn("translate(0,--", svg)


if __name__ == "__main__":
    unittest.main()
