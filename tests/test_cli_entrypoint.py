from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest import mock

from src import plotter_pdf_drawer as backend


class CliEntrypointTests(unittest.TestCase):
    def test_cli_backend_proxy_writes_back_to_module_globals(self) -> None:
        original = backend.PENCIL_BASE_Z_DOWN
        try:
            proxy = backend._CliBackendProxy()
            proxy.PENCIL_BASE_Z_DOWN = 7.5
            self.assertEqual(backend.PENCIL_BASE_Z_DOWN, 7.5)
            self.assertEqual(proxy.PENCIL_BASE_Z_DOWN, 7.5)
        finally:
            backend.PENCIL_BASE_Z_DOWN = original

    def test_should_exit_after_pencil_maintenance_only_when_no_other_actions(self) -> None:
        args = mock.Mock(
            frame=False,
            calibrate_corners=False,
            pencil_wear_test=False,
            input=None,
            plan_sheet=False,
        )
        self.assertTrue(backend._should_exit_after_pencil_maintenance(args, did_pencil_command=True))
        args.input = "sample.pdf"
        self.assertFalse(backend._should_exit_after_pencil_maintenance(args, did_pencil_command=True))

    def test_main_pencil_status_exits_before_sheet_setup(self) -> None:
        with (
            mock.patch.object(backend, "load_pencil_profile", return_value={}),
            mock.patch.object(backend, "apply_pencil_profile"),
            mock.patch.object(backend, "show_pencil_status") as show_status,
            mock.patch.object(backend, "configure_active_work_area") as configure_sheet,
            mock.patch.object(backend, "detect_com_port") as detect_com,
            mock.patch.object(backend, "apply_quality_profile") as apply_quality,
        ):
            rc = backend.main(["--pencil-status"])

        self.assertEqual(rc, 0)
        show_status.assert_called_once()
        configure_sheet.assert_not_called()
        detect_com.assert_not_called()
        apply_quality.assert_not_called()

    def test_main_plan_sheet_accepts_custom_argv_and_returns_zero(self) -> None:
        with (
            mock.patch.object(backend, "load_pencil_profile", return_value={}),
            mock.patch.object(backend, "apply_pencil_profile"),
            mock.patch.object(backend, "configure_active_work_area"),
            mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(420.0, 297.0)),
            mock.patch.object(
                backend,
                "plan_tiled_passes_for_sheet",
                return_value={
                    "nx": 2,
                    "ny": 1,
                    "passes": 2,
                    "rotated": False,
                    "max_two_pass_scale": 1.0,
                },
            ),
            mock.patch.object(backend, "work_area_bounds", return_value=(0.0, 180.0, -295.0, -15.0)),
            mock.patch.object(backend, "detect_com_port", return_value="COM6") as detect_com,
            mock.patch.object(backend, "apply_quality_profile"),
            mock.patch.object(backend, "quality_state", return_value="mock-profile"),
            mock.patch("builtins.print"),
        ):
            rc = backend.main(["--plan-sheet", "--sheet-format", "a3"])

        self.assertEqual(rc, 0)
        detect_com.assert_called_once_with(None)

    def test_main_frame_dry_run_uses_path_output_and_disables_sender(self) -> None:
        with (
            mock.patch.object(backend, "load_pencil_profile", return_value={}),
            mock.patch.object(backend, "apply_pencil_profile"),
            mock.patch.object(backend, "configure_active_work_area"),
            mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(210.0, 297.0)),
            mock.patch.object(backend, "detect_com_port", return_value="COM9"),
            mock.patch.object(backend, "apply_quality_profile"),
            mock.patch.object(backend, "quality_state", return_value="mock-profile"),
            mock.patch.object(backend, "run_frame_pipeline", return_value=(True, "ok")) as run_frame,
            mock.patch("builtins.print"),
        ):
            rc = backend.main(["--frame", "--dry-run", "--output", "out.nc", "--com", "COM9"])

        self.assertEqual(rc, 0)
        kwargs = run_frame.call_args.kwargs
        self.assertEqual(kwargs["com"], "COM9")
        self.assertFalse(bool(kwargs["send_to_plotter"]))
        self.assertEqual(kwargs["output_path"], Path("out.nc"))

    def test_main_corner_calibration_fast_profile_passes_short_lift_flag(self) -> None:
        with (
            mock.patch.object(backend, "load_pencil_profile", return_value={}),
            mock.patch.object(backend, "apply_pencil_profile"),
            mock.patch.object(backend, "configure_active_work_area"),
            mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(180.0, 280.0)),
            mock.patch.object(backend, "detect_com_port", return_value="COM6"),
            mock.patch.object(backend, "apply_quality_profile"),
            mock.patch.object(backend, "quality_state", return_value="mock-profile"),
            mock.patch.object(backend, "run_corner_calibration_pipeline", return_value=(True, "ok")) as run_calibration,
            mock.patch("builtins.print"),
        ):
            rc = backend.main(["--calibrate-corners", "--dry-run", "--calibration-profile", "fast"])

        self.assertEqual(rc, 0)
        self.assertTrue(run_calibration.call_args.kwargs["fast"])

    def test_main_without_action_returns_usage_error(self) -> None:
        with (
            mock.patch("builtins.print") as print_mock,
            mock.patch.object(argparse.ArgumentParser, "print_help") as print_help,
            mock.patch.object(backend, "configure_active_work_area") as configure_sheet,
            mock.patch.object(backend, "detect_com_port") as detect_com,
            mock.patch.object(backend, "apply_quality_profile") as apply_quality,
        ):
            rc = backend.main([])

        self.assertEqual(rc, 2)
        print_help.assert_called_once()
        configure_sheet.assert_not_called()
        detect_com.assert_not_called()
        apply_quality.assert_not_called()
        self.assertIn(
            mock.call("No action specified. Use explicit CLI commands shown above."),
            print_mock.mock_calls,
        )


if __name__ == "__main__":
    unittest.main()
