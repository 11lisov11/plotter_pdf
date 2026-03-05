from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend.gcode import preflight as gcode_preflight


class GcodePreflightModuleTests(unittest.TestCase):
    def test_preflight_disabled_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_disabled_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G1 X1 Y1\n", encoding="utf-8")
            ok, msg = gcode_preflight.preflight_check_gcode(
                gcode,
                lambda *_args: None,
                preflight_enabled=False,
                preflight_max_gcode_lines=100,
                preflight_max_travel_to_draw_ratio=5.0,
                preflight_bounds_margin_mm=0.0,
                z_up=0.0,
                z_down=11.9,
                bounds=None,
                work_area_bounds=lambda: (0.0, 100.0, 0.0, 100.0),
                summarize_gcode_file=lambda _path: (1, 1, 0, (1.0, 1.0, 1.0, 1.0)),
                gcode_draw_bounds=lambda *_args: (1.0, 1.0, 1.0, 1.0),
            )
            self.assertTrue(ok)
            self.assertEqual(msg, "disabled")

    def test_preflight_rejects_empty_or_invalid_gcode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_empty_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("", encoding="utf-8")
            ok, msg = gcode_preflight.preflight_check_gcode(
                gcode,
                lambda *_args: None,
                preflight_enabled=True,
                preflight_max_gcode_lines=100,
                preflight_max_travel_to_draw_ratio=5.0,
                preflight_bounds_margin_mm=0.0,
                z_up=0.0,
                z_down=11.9,
                bounds=None,
                work_area_bounds=lambda: (0.0, 100.0, 0.0, 100.0),
                summarize_gcode_file=lambda _path: (0, 0, 0, (0.0, 0.0, 0.0, 0.0)),
                gcode_draw_bounds=lambda *_args: None,
            )
            self.assertFalse(ok)
            self.assertIn("empty or invalid", msg)

    def test_preflight_emits_warning_for_high_travel_ratio(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_ratio_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G1 X1 Y1\n", encoding="utf-8")
            logs: list[str] = []
            ok, msg = gcode_preflight.preflight_check_gcode(
                gcode,
                logs.append,
                preflight_enabled=True,
                preflight_max_gcode_lines=100,
                preflight_max_travel_to_draw_ratio=0.5,
                preflight_bounds_margin_mm=0.0,
                z_up=0.0,
                z_down=11.9,
                bounds=(0.0, 100.0, 0.0, 100.0),
                work_area_bounds=lambda: (0.0, 100.0, 0.0, 100.0),
                summarize_gcode_file=lambda _path: (10, 2, 3, (1.0, 2.0, 1.0, 2.0)),
                gcode_draw_bounds=lambda *_args: (1.0, 2.0, 1.0, 2.0),
            )
            self.assertTrue(ok)
            self.assertIn("ok:", msg)
            self.assertTrue(any("high travel ratio" in line for line in logs))

    def test_preflight_fails_when_draw_bounds_exceed_area(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_bounds_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G1 X1 Y1\n", encoding="utf-8")
            ok, msg = gcode_preflight.preflight_check_gcode(
                gcode,
                lambda *_args: None,
                preflight_enabled=True,
                preflight_max_gcode_lines=100,
                preflight_max_travel_to_draw_ratio=5.0,
                preflight_bounds_margin_mm=0.0,
                z_up=0.0,
                z_down=11.9,
                bounds=(0.0, 20.0, 0.0, 20.0),
                work_area_bounds=lambda: (0.0, 20.0, 0.0, 20.0),
                summarize_gcode_file=lambda _path: (5, 2, 1, (1.0, 2.0, 1.0, 2.0)),
                gcode_draw_bounds=lambda *_args: (-1.0, 30.0, 0.0, 5.0),
            )
            self.assertFalse(ok)
            self.assertIn("geometry exceeds active area", msg)


if __name__ == "__main__":
    unittest.main()

