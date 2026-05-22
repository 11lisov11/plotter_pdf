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
