from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.plotter_backend.errors import ConversionError
from src.plotter_backend.gcode import penlift as gcode_penlift


class GcodePenliftModuleTests(unittest.TestCase):
    def test_run_penlift_postprocess_builds_command_with_dynamic_and_merge_flags(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_penlift_") as td:
            root = Path(td)
            xy = root / "xy.nc"
            pen = root / "pen.nc"
            script = root / "penlift_postprocess.py"
            xy.write_text("G1 X1 Y1\n", encoding="utf-8")
            pen.write_text("", encoding="utf-8")
            script.write_text("# stub\n", encoding="utf-8")

            captured: dict[str, list[str]] = {}

            def _run_cmd(cmd):
                captured["cmd"] = list(cmd)
                return 0, "ok", ""

            gcode_penlift.run_penlift_postprocess(
                xy,
                pen,
                python_executable="python",
                script_path=script,
                z_down=11.9,
                z_up=0.0,
                pen_lift_mode="z",
                pen_spindle_speed=1000,
                z_delay_down=0.06,
                z_delay_up=0.06,
                z_feed_down_approach=700.0,
                z_feed_down_touch=180.0,
                z_feed_up=700.0,
                z_feed_up_final=220.0,
                z_soft_down_mm=0.8,
                z_soft_up_mm=0.5,
                z_travel_lift_mm=12.0,
                dynamic_z_enable=True,
                dynamic_base_z_down=11.9,
                dynamic_initial_wear_mm=0.2,
                dynamic_wear_mm_per_m=0.3,
                dynamic_z_comp_per_wear=0.7,
                dynamic_z_max_comp_mm=1.2,
                stroke_z_jitter_enable=True,
                stroke_z_jitter_mm=0.1,
                stroke_z_jitter_seed=42,
                merge_short_travel_enable=True,
                merge_short_travel_mm=1.5,
                merge_short_travel_feed=2500.0,
                run_cmd=_run_cmd,
            )

            cmd = captured.get("cmd", [])
            self.assertTrue(cmd)
            self.assertIn("--dynamic-z-enable", cmd)
            self.assertIn("--stroke-z-jitter-enable", cmd)
            self.assertIn("--merge-short-travel-enable", cmd)
            self.assertIn("--z-down", cmd)
            self.assertIn("--z-up", cmd)

    def test_run_penlift_postprocess_raises_conversion_error_on_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_penlift_fail_") as td:
            root = Path(td)
            xy = root / "xy.nc"
            pen = root / "pen.nc"
            script = root / "penlift_postprocess.py"
            xy.write_text("G1 X1 Y1\n", encoding="utf-8")
            pen.write_text("", encoding="utf-8")
            script.write_text("# stub\n", encoding="utf-8")

            with self.assertRaisesRegex(ConversionError, "PenLift postprocess failed"):
                gcode_penlift.run_penlift_postprocess(
                    xy,
                    pen,
                    python_executable="python",
                    script_path=script,
                    z_down=11.9,
                    z_up=0.0,
                    pen_lift_mode="z",
                    pen_spindle_speed=1000,
                    z_delay_down=0.06,
                    z_delay_up=0.06,
                    z_feed_down_approach=700.0,
                    z_feed_down_touch=180.0,
                    z_feed_up=700.0,
                    z_feed_up_final=220.0,
                    z_soft_down_mm=0.8,
                    z_soft_up_mm=0.5,
                    z_travel_lift_mm=12.0,
                    dynamic_z_enable=False,
                    dynamic_base_z_down=None,
                    dynamic_initial_wear_mm=0.0,
                    dynamic_wear_mm_per_m=0.0,
                    dynamic_z_comp_per_wear=0.0,
                    dynamic_z_max_comp_mm=0.0,
                    stroke_z_jitter_enable=False,
                    stroke_z_jitter_mm=0.0,
                    stroke_z_jitter_seed=0,
                    merge_short_travel_enable=False,
                    merge_short_travel_mm=0.0,
                    merge_short_travel_feed=0.0,
                    run_cmd=lambda _cmd: (3, "", "postprocess failed"),
                )

    def test_run_penlift_postprocess_runs_in_process_when_frozen(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_penlift_frozen_") as td:
            root = Path(td)
            xy = root / "xy.nc"
            pen = root / "pen.nc"
            script = root / "penlift_postprocess.py"
            xy.write_text("G21\nG90\nG0 X0 Y0\nG1 X1 Y1 F800\n", encoding="utf-8")
            script.write_text("# bundled script path placeholder\n", encoding="utf-8")

            def _run_cmd(_cmd):
                raise AssertionError("frozen bundle must not launch a subprocess")

            with mock.patch.object(gcode_penlift.sys, "frozen", True, create=True):
                gcode_penlift.run_penlift_postprocess(
                    xy,
                    pen,
                    python_executable="plotter-pdf.exe",
                    script_path=script,
                    z_down=11.9,
                    z_up=0.0,
                    pen_lift_mode="z",
                    pen_spindle_speed=1000,
                    z_delay_down=0.06,
                    z_delay_up=0.06,
                    z_feed_down_approach=700.0,
                    z_feed_down_touch=180.0,
                    z_feed_up=700.0,
                    z_feed_up_final=220.0,
                    z_soft_down_mm=0.8,
                    z_soft_up_mm=0.5,
                    z_travel_lift_mm=12.0,
                    dynamic_z_enable=False,
                    dynamic_base_z_down=None,
                    dynamic_initial_wear_mm=0.0,
                    dynamic_wear_mm_per_m=0.0,
                    dynamic_z_comp_per_wear=0.0,
                    dynamic_z_max_comp_mm=0.0,
                    stroke_z_jitter_enable=False,
                    stroke_z_jitter_mm=0.0,
                    stroke_z_jitter_seed=0,
                    merge_short_travel_enable=False,
                    merge_short_travel_mm=0.0,
                    merge_short_travel_feed=0.0,
                    run_cmd=_run_cmd,
                )

            processed = pen.read_text(encoding="utf-8")
            self.assertIn("G1 Z11.9000", processed)
            self.assertIn("G1 X1 Y1 F800", processed)


if __name__ == "__main__":
    unittest.main()

