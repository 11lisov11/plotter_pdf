from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend.gcode import finalize as gcode_finalize


class GcodeFinalizeModuleTests(unittest.TestCase):
    def test_make_final_with_preamble_includes_expected_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_finalize_") as td:
            root = Path(td)
            prepared = root / "prepared.nc"
            final = root / "final.nc"
            prepared.write_text("G1 X1.000 Y2.000 F500\n", encoding="utf-8")

            gcode_finalize.make_final_with_preamble(
                prepared,
                final,
                z_up=0.0,
                safe_lift_feed=900.0,
                z_delay_up=0.05,
                home_x=0.0,
                home_y=0.0,
                feed_travel=5000.0,
                go_home_before_draw=True,
                go_home_after_draw=True,
            )

            lines = [line.strip() for line in final.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(lines[0], "$X")
            self.assertIn("$1=255", lines[:6])
            self.assertIn("G21", lines[:8])
            self.assertIn("G90", lines[:8])
            self.assertTrue(any(line.startswith("G1 X1.000 Y2.000") for line in lines))
            self.assertIn("M5", lines[-4:])
            self.assertNotIn("$1=0", lines)

    def test_make_final_with_preamble_respects_home_flags(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_finalize_home_") as td:
            root = Path(td)
            prepared = root / "prepared.nc"
            final = root / "final.nc"
            prepared.write_text("G1 X2 Y3\n", encoding="utf-8")

            gcode_finalize.make_final_with_preamble(
                prepared,
                final,
                z_up=1.0,
                safe_lift_feed=1000.0,
                z_delay_up=0.1,
                home_x=10.0,
                home_y=20.0,
                feed_travel=3000.0,
                go_home_before_draw=False,
                go_home_after_draw=False,
            )

            text = final.read_text(encoding="utf-8")
            self.assertNotIn("X10.0000 Y20.0000", text)
            self.assertNotIn("$1=0", text)

    def test_make_final_with_preamble_can_explicitly_release_steppers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_finalize_release_") as td:
            root = Path(td)
            prepared = root / "prepared.nc"
            final = root / "final.nc"
            prepared.write_text("G1 X2 Y3\n", encoding="utf-8")

            gcode_finalize.make_final_with_preamble(
                prepared,
                final,
                z_up=1.0,
                safe_lift_feed=1000.0,
                z_delay_up=0.1,
                home_x=10.0,
                home_y=20.0,
                feed_travel=3000.0,
                go_home_before_draw=False,
                go_home_after_draw=False,
                release_steppers_after_draw=True,
            )

            lines = [line.strip() for line in final.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(lines[-1], "$1=0")


if __name__ == "__main__":
    unittest.main()

