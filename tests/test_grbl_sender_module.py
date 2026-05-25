from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.plotter_backend.errors import SerialTransportError, ToolDependencyError
from src.plotter_backend.machine import grbl_sender


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def readline(self) -> str:
        if not self._lines:
            return ""
        return self._lines.pop(0)


class _FakeProc:
    def __init__(self, lines: list[str], rc: int) -> None:
        self.stdout = _FakeStdout(lines)
        self._rc = int(rc)

    def wait(self) -> int:
        return self._rc


class GrblSenderModuleTests(unittest.TestCase):
    def test_find_nearest_g0_xy_line(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_find_") as td:
            root = Path(td)
            gcode = root / "test.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 X0 Y0",
                        "G1 X10 Y0",
                        "G0 X20 Y20",
                        "G0 X5 Y6",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            line = grbl_sender.find_nearest_g0_xy_line(gcode, x=5.2, y=6.1)
            self.assertEqual(line, 6)

    def test_find_nearest_g0_xy_line_accepts_common_gcode_variants(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_find_variants_") as td:
            root = Path(td)
            gcode = root / "test.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "  g00 x0 y0",
                        "G1 X10 Y0",
                        "G00 X20 Y20 ; far travel",
                        "g0 X+5.2 Y6.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            line = grbl_sender.find_nearest_g0_xy_line(gcode, x=5.2, y=6.1)
            self.assertEqual(line, 6)

    def test_find_nearest_g0_xy_line_accepts_compact_and_modal_g0(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_find_compact_") as td:
            root = Path(td)
            gcode = root / "test.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0X0Y0",
                        "X5.2Y6.",
                        "G1X10Y10",
                        "X5Y6",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            line = grbl_sender.find_nearest_g0_xy_line(gcode, x=5.1, y=6.1)
            self.assertEqual(line, 4)

    def test_find_nearest_g0_xy_line_respects_relative_xy_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_find_relative_") as td:
            root = Path(td)
            gcode = root / "test.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 X0 Y0",
                        "G91 G0 X10 Y0",
                        "G0 X5 Y0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            line = grbl_sender.find_nearest_g0_xy_line(gcode, x=15.1, y=0.0)
            self.assertEqual(line, 5)

    def test_find_nearest_g0_xy_line_treats_g92_as_coordinate_reset_not_travel(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_find_g92_") as td:
            root = Path(td)
            gcode = root / "test.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 X10 Y0",
                        "G92 X0 Y0",
                        "G0 X20 Y0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            line = grbl_sender.find_nearest_g0_xy_line(gcode, x=0.0, y=0.0)
            self.assertEqual(line, 3)

    def test_write_resume_file_writes_preamble_and_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_resume_") as td:
            root = Path(td)
            src = root / "source.nc"
            dst = root / "resume.nc"
            src.write_text("G21\nG90\nG0 X1 Y1\nG1 X2 Y2\n", encoding="utf-8")

            grbl_sender.write_resume_file(
                src,
                dst,
                start_line=3,
                z_up=0.0,
                safe_lift_feed=900.0,
                z_delay_up=0.05,
            )

            text = dst.read_text(encoding="utf-8")
            self.assertIn("G0 Z0.0000 F900.0", text)
            self.assertIn("; AUTO-RESUME from line 3 of source.nc", text)
            self.assertIn("G0 X1 Y1", text)
            self.assertIn("G1 X2 Y2", text)

    def test_write_resume_file_strips_g92_from_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_resume_g92_") as td:
            root = Path(td)
            src = root / "source.nc"
            dst = root / "resume.nc"
            src.write_text(
                "\n".join(
                    [
                        "G21",
                        "G92 Z4.0000",
                        "G0 Z0",
                        "G92Z0.0000 ; compact reset must not be resumed",
                        "G0 X1 Y1",
                        "G1 X2 Y2",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            grbl_sender.write_resume_file(
                src,
                dst,
                start_line=1,
                z_up=0.0,
                safe_lift_feed=900.0,
                z_delay_up=0.05,
            )

            lines = [
                line
                for line in dst.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("; AUTO-RESUME")
            ]
            self.assertFalse(any("G92" in line.replace(" ", "").upper() for line in lines))
            self.assertIn("G0 X1 Y1", lines)
            self.assertIn("G1 X2 Y2", lines)

    def test_write_resume_file_restores_relative_distance_mode_before_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_resume_g91_") as td:
            root = Path(td)
            src = root / "source.nc"
            dst = root / "resume.nc"
            src.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 X0 Y0",
                        "G91",
                        "G0 X10 Y0",
                        "G1 X1 Y0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            grbl_sender.write_resume_file(
                src,
                dst,
                start_line=5,
                z_up=0.0,
                safe_lift_feed=900.0,
                z_delay_up=0.05,
            )

            lines = dst.read_text(encoding="utf-8").splitlines()
            self.assertLess(lines.index("G91"), lines.index("; AUTO-RESUME from line 5 of source.nc"))
            self.assertLess(lines.index("; AUTO-RESUME from line 5 of source.nc"), lines.index("G0 X10 Y0"))

    def test_write_resume_file_restores_absolute_ijk_mode_before_arc_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_resume_g901_") as td:
            root = Path(td)
            src = root / "source.nc"
            dst = root / "resume.nc"
            src.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G90.1",
                        "G0 X0 Y0",
                        "G2 X10 Y0 I5 J0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            grbl_sender.write_resume_file(
                src,
                dst,
                start_line=5,
                z_up=0.0,
                safe_lift_feed=900.0,
                z_delay_up=0.05,
            )

            lines = dst.read_text(encoding="utf-8").splitlines()
            self.assertLess(lines.index("G90.1"), lines.index("; AUTO-RESUME from line 5 of source.nc"))
            self.assertLess(lines.index("; AUTO-RESUME from line 5 of source.nc"), lines.index("G2 X10 Y0 I5 J0"))

    def test_find_nearest_g0_xy_line_ignores_coordinates_inside_parentheses(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_find_comment_") as td:
            root = Path(td)
            gcode = root / "test.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 X0 Y0",
                        "G1 X10 Y0",
                        "G0 X20 Y20 (X5 Y5 old position)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            line = grbl_sender.find_nearest_g0_xy_line(gcode, x=5.0, y=5.0)
            self.assertEqual(line, 3)

    def test_send_to_grbl_returns_sender_plot_time_from_stdout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_ok_") as td:
            root = Path(td)
            gcode = root / "source.nc"
            gcode.write_text("G21\nG90\nG0 X0 Y0\n", encoding="utf-8")
            logs: list[str] = []

            fake_proc = _FakeProc(["hello\n", "PLOT_TIME_SECONDS=12.5\n"], rc=0)
            with mock.patch("src.plotter_backend.machine.grbl_sender.subprocess.Popen", return_value=fake_proc):
                result = grbl_sender.send_to_grbl(
                    gcode,
                    "COM6",
                    "115200",
                    logs.append,
                    root_dir=Path.cwd(),
                    ensure_local_tmp_root=lambda: root,
                    grbl_wait_for_idle=lambda *_args, **_kwargs: None,
                    grbl_get_wpos_xyz=lambda *_args, **_kwargs: (0.0, 0.0, 0.0),
                    z_up=0.0,
                    safe_lift_feed=1000.0,
                    z_delay_up=0.05,
                )

            self.assertAlmostEqual(result, 12.5, places=6)
            self.assertTrue(any("Sending to Grbl" in line for line in logs))
            self.assertTrue(any("PLOT_TIME_SECONDS=12.5" in line for line in logs))

    def test_send_to_grbl_auto_resume_after_first_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_resume_run_") as td:
            root = Path(td)
            gcode = root / "source.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 X0 Y0",
                        "G1 X10 Y0",
                        "G0 X5 Y5",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            logs: list[str] = []
            wait_calls: list[tuple[str, str]] = []

            popen_calls = [
                _FakeProc(["error: alarm\n"], rc=1),
                _FakeProc(["PLOT_TIME_SECONDS=2.0\n"], rc=0),
            ]
            with mock.patch("src.plotter_backend.machine.grbl_sender.subprocess.Popen", side_effect=popen_calls):
                result = grbl_sender.send_to_grbl(
                    gcode,
                    "COM9",
                    "115200",
                    logs.append,
                    auto_resume=True,
                    max_resume_attempts=1,
                    root_dir=Path.cwd(),
                    ensure_local_tmp_root=lambda: root,
                    grbl_wait_for_idle=lambda port, baud, _logger: wait_calls.append((port, baud)),
                    grbl_get_wpos_xyz=lambda *_args, **_kwargs: (5.1, 5.0, 0.0),
                    z_up=0.0,
                    safe_lift_feed=800.0,
                    z_delay_up=0.04,
                )

            self.assertGreaterEqual(result, 2.0)
            self.assertEqual(wait_calls, [("COM9", "115200")])
            self.assertTrue(any("Auto-resume" in line for line in logs))
            self.assertTrue(any(root.glob("resume_source_from_*.nc")))

    def test_send_to_grbl_raises_tool_dependency_error_when_sender_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_missing_") as td:
            root = Path(td)
            gcode = root / "source.nc"
            gcode.write_text("G21\nG90\n", encoding="utf-8")

            with self.assertRaises(ToolDependencyError):
                grbl_sender.send_to_grbl(
                    gcode,
                    "COM6",
                    "115200",
                    lambda _line: None,
                    root_dir=root,
                    ensure_local_tmp_root=lambda: root,
                    grbl_wait_for_idle=lambda *_args, **_kwargs: None,
                    grbl_get_wpos_xyz=lambda *_args, **_kwargs: (0.0, 0.0, 0.0),
                    z_up=0.0,
                    safe_lift_feed=1000.0,
                    z_delay_up=0.05,
                )

    def test_send_to_grbl_raises_serial_transport_error_on_sender_rc(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_err_") as td:
            root = Path(td)
            gcode = root / "source.nc"
            gcode.write_text("G21\nG90\n", encoding="utf-8")
            fake_proc = _FakeProc(["error: alarm\n"], rc=2)
            with mock.patch("src.plotter_backend.machine.grbl_sender.subprocess.Popen", return_value=fake_proc):
                with self.assertRaises(SerialTransportError) as ctx:
                    grbl_sender.send_to_grbl(
                        gcode,
                        "COM6",
                        "115200",
                        lambda _line: None,
                        root_dir=Path.cwd(),
                        ensure_local_tmp_root=lambda: root,
                        grbl_wait_for_idle=lambda *_args, **_kwargs: None,
                        grbl_get_wpos_xyz=lambda *_args, **_kwargs: (0.0, 0.0, 0.0),
                        z_up=0.0,
                        safe_lift_feed=1000.0,
                        z_delay_up=0.05,
                        auto_resume=False,
                    )
                self.assertIn("Sender error code: 2", str(ctx.exception))

    def test_send_to_grbl_raises_serial_transport_error_when_stdout_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_stdout_") as td:
            root = Path(td)
            gcode = root / "source.nc"
            gcode.write_text("G21\nG90\n", encoding="utf-8")
            fake_proc = _FakeProc([], rc=0)
            fake_proc.stdout = None
            with mock.patch("src.plotter_backend.machine.grbl_sender.subprocess.Popen", return_value=fake_proc):
                with self.assertRaises(SerialTransportError):
                    grbl_sender.send_to_grbl(
                        gcode,
                        "COM6",
                        "115200",
                        lambda _line: None,
                        root_dir=Path.cwd(),
                        ensure_local_tmp_root=lambda: root,
                        grbl_wait_for_idle=lambda *_args, **_kwargs: None,
                        grbl_get_wpos_xyz=lambda *_args, **_kwargs: (0.0, 0.0, 0.0),
                        z_up=0.0,
                        safe_lift_feed=1000.0,
                        z_delay_up=0.05,
                    )

    def test_send_to_grbl_raises_serial_transport_error_when_popen_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_grbl_sender_popen_") as td:
            root = Path(td)
            gcode = root / "source.nc"
            gcode.write_text("G21\nG90\n", encoding="utf-8")
            with mock.patch(
                "src.plotter_backend.machine.grbl_sender.subprocess.Popen",
                side_effect=OSError("access denied"),
            ):
                with self.assertRaises(SerialTransportError) as ctx:
                    grbl_sender.send_to_grbl(
                        gcode,
                        "COM6",
                        "115200",
                        lambda _line: None,
                        root_dir=Path.cwd(),
                        ensure_local_tmp_root=lambda: root,
                        grbl_wait_for_idle=lambda *_args, **_kwargs: None,
                        grbl_get_wpos_xyz=lambda *_args, **_kwargs: (0.0, 0.0, 0.0),
                        z_up=0.0,
                        safe_lift_feed=1000.0,
                        z_delay_up=0.05,
                    )
                self.assertIn("Failed to start sender process", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
