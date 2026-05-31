from __future__ import annotations

import math
import re
import tempfile
import unittest
from pathlib import Path

from src import plotter_pdf_drawer as backend


class GcodeGoldenPropertiesTests(unittest.TestCase):
    def test_make_final_with_preamble_and_trailer_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_preamble_") as td:
            root = Path(td)
            prepared = root / "prepared.nc"
            final = root / "final.nc"
            prepared.write_text("G1 X1.000 Y1.000 F500\n", encoding="utf-8")

            backend.make_final_with_preamble(prepared, final)
            lines = [line.strip() for line in final.read_text(encoding="utf-8").splitlines() if line.strip()]

            self.assertGreater(len(lines), 6)
            self.assertEqual(lines[0], "$X")
            self.assertIn("$1=255", lines[:6])
            self.assertIn("G21", lines[:8])
            self.assertIn("G90", lines[:8])
            self.assertTrue(any(line.startswith("G1 X1.000 Y1.000") for line in lines))
            self.assertIn("M5", lines[-4:])
            self.assertNotIn("$1=0", lines)

    def test_svg_pipeline_output_has_finite_in_area_draw_bounds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_bounds_") as td:
            root = Path(td)
            svg_path = root / "sample.svg"
            out_nc = root / "prepared.nc"
            svg_path.write_text(
                (
                    "<svg xmlns='http://www.w3.org/2000/svg' width='40mm' height='30mm' viewBox='0 0 40 30'>"
                    "<path d='M 2 2 L 38 2 L 38 28 L 2 28 Z' stroke='black' fill='none' stroke-width='0.4'/>"
                    "</svg>"
                ),
                encoding="utf-8",
            )

            ok, msg = backend.run_pipeline(svg_path, lambda *_args: None, send_to_plotter=False, output_path=out_nc)
            self.assertTrue(ok, msg)
            self.assertTrue(out_nc.exists())

            preflight_ok, preflight_msg = backend.preflight_check_gcode(out_nc, logger=lambda *_args: None)
            self.assertTrue(preflight_ok, preflight_msg)

            coord_re = re.compile(r"\b([XYZ])([-+]?(?:\d+(?:\.\d*)?|\.\d+))\b")
            gcode_text = out_nc.read_text(encoding="utf-8", errors="ignore")
            values = [float(match.group(2)) for match in coord_re.finditer(gcode_text)]
            self.assertTrue(values, "Expected at least one X/Y/Z coordinate in generated G-code")
            self.assertTrue(all(math.isfinite(v) for v in values), "Found non-finite coordinate values")

            draw_bounds = backend._gcode_draw_bounds(  # type: ignore[attr-defined]
                out_nc,
                z_up=float(backend.Z_UP),
                z_down=float(backend.Z_DOWN),
            )
            self.assertIsNotNone(draw_bounds)
            x0, x1, y0, y1 = draw_bounds or (0.0, 0.0, 0.0, 0.0)
            min_x, max_x, min_y, max_y = backend.work_area_bounds()
            margin = max(0.0, float(backend.PREFLIGHT_BOUNDS_MARGIN_MM)) + 1e-6
            self.assertGreaterEqual(x0, min_x - margin)
            self.assertLessEqual(x1, max_x + margin)
            self.assertGreaterEqual(y0, min_y - margin)
            self.assertLessEqual(y1, max_y + margin)


if __name__ == "__main__":
    unittest.main()

