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

    def test_preflight_fails_when_no_pen_down_bounds_exist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_no_pen_down_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G90\nG0 Z0\nG1 X10 Y10\n", encoding="utf-8")
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
                summarize_gcode_file=lambda _path: (3, 1, 1, (0.0, 10.0, 0.0, 10.0)),
                gcode_draw_bounds=lambda *_args: None,
            )

            self.assertFalse(ok)
            self.assertIn("no pen-down drawing bounds", msg)

    def test_preflight_rejects_g92_xy_coordinate_reset(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_g92_xy_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G90\nG92 X0 Y0\nG1 X10 Y10\n", encoding="utf-8")
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
                summarize_gcode_file=lambda _path: (3, 1, 0, (0.0, 10.0, 0.0, 10.0)),
                gcode_draw_bounds=lambda *_args: (0.0, 10.0, 0.0, 10.0),
            )

            self.assertFalse(ok)
            self.assertIn("G92 X/Y coordinate reset is not allowed", msg)

    def test_preflight_rejects_first_xy_with_pen_down(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_first_xy_down_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G90\nG92 Z11.9\nG1 X10 Y10\nG0 Z0\n", encoding="utf-8")
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
                summarize_gcode_file=lambda _path: (4, 1, 0, (0.0, 10.0, 0.0, 10.0)),
                gcode_draw_bounds=lambda *_args: (0.0, 10.0, 0.0, 10.0),
            )

            self.assertFalse(ok)
            self.assertIn("first XY move happens with pen down", msg)

    def test_preflight_rejects_rapid_xy_with_pen_down(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_rapid_down_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G90\nG0 X0 Y0\nG1 Z11.9\nG0 X10 Y10\nG0 Z0\n", encoding="utf-8")
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
                summarize_gcode_file=lambda _path: (5, 1, 1, (0.0, 10.0, 0.0, 10.0)),
                gcode_draw_bounds=lambda *_args: (0.0, 10.0, 0.0, 10.0),
            )

            self.assertFalse(ok)
            self.assertIn("rapid XY travel with pen down", msg)

    def test_preflight_rejects_file_ending_with_pen_down(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_end_down_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G90\nG0 X0 Y0\nG1 Z11.9\nG1 X10 Y10\n", encoding="utf-8")
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
                summarize_gcode_file=lambda _path: (4, 1, 1, (0.0, 10.0, 0.0, 10.0)),
                gcode_draw_bounds=lambda *_args: (0.0, 10.0, 0.0, 10.0),
            )

            self.assertFalse(ok)
            self.assertIn("file ends with pen down", msg)

    def test_preflight_allows_legacy_xy_only_gcode_without_pen_control(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_xy_only_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G90\nG0 X0 Y0 ; Z0 in comment\nG1 X10 Y10 (M3 note)\n", encoding="utf-8")
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
                summarize_gcode_file=lambda _path: (3, 1, 1, (0.0, 10.0, 0.0, 10.0)),
                gcode_draw_bounds=lambda *_args: None,
            )

            self.assertTrue(ok, msg)

    def test_preflight_fails_when_draw_bounds_cannot_be_computed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_preflight_bounds_error_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text("G90\nG1 X10 Y10\n", encoding="utf-8")

            def _raise(*_args):
                raise ValueError("bad gcode")

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
                summarize_gcode_file=lambda _path: (2, 1, 0, (10.0, 10.0, 10.0, 10.0)),
                gcode_draw_bounds=_raise,
            )

            self.assertFalse(ok)
            self.assertIn("cannot compute pen-down draw bounds", msg)


if __name__ == "__main__":
    unittest.main()

