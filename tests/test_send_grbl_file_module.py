from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src import send_grbl_file


class _FakeSerial:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))

    def flush(self) -> None:
        return None

    def readline(self) -> bytes:
        return b"ok\n"


class _FakeIdleSerial(_FakeSerial):
    def __init__(self) -> None:
        super().__init__()
        self._status_pending = False

    def write(self, data: bytes) -> None:
        super().write(data)
        if data == b"?":
            self._status_pending = True

    def readline(self) -> bytes:
        if self._status_pending:
            self._status_pending = False
            return b"<Idle|MPos:0.000,0.000,0.000|FS:0,0>\n"
        return b"ok\n"


class SendGrblFileModuleTests(unittest.TestCase):
    def test_release_axes_forces_pen_up_before_motor_release(self) -> None:
        ser = _FakeSerial()

        send_grbl_file.release_axes(ser, sleep=False, wait=False)

        cmds = [raw.decode("ascii").strip() for raw in ser.writes]
        self.assertIn("G92 Z4.0000", cmds)
        self.assertIn("G0 Z0.0000 F800.0", cmds)
        self.assertIn("$1=0", cmds)
        self.assertLess(cmds.index("G92 Z4.0000"), cmds.index("G0 Z0.0000 F800.0"))
        self.assertLess(cmds.index("G0 Z0.0000 F800.0"), cmds.index("$1=0"))

    def test_release_axes_returns_home_before_motor_release(self) -> None:
        ser = _FakeSerial()

        send_grbl_file.release_axes(ser, sleep=False, wait=False)

        cmds = [raw.decode("ascii").strip() for raw in ser.writes]
        self.assertIn("G0 X0.0000 Y0.0000 F900.0", cmds)
        self.assertIn("$1=0", cmds)
        self.assertLess(cmds.index("G0 Z0.0000 F800.0"), cmds.index("G0 X0.0000 Y0.0000 F900.0"))
        self.assertLess(cmds.index("G0 X0.0000 Y0.0000 F900.0"), cmds.index("$1=0"))

    def test_release_axes_waits_for_home_idle_before_motor_release(self) -> None:
        ser = _FakeIdleSerial()

        send_grbl_file.release_axes(ser, sleep=False, wait=True)

        cmds = [raw.decode("ascii").strip() for raw in ser.writes]
        self.assertIn("?", cmds)
        self.assertLess(cmds.index("G0 X0.0000 Y0.0000 F900.0"), cmds.index("?"))
        self.assertLess(cmds.index("?"), cmds.index("$1=0"))

    def test_main_refuses_duplicate_sender_for_same_port_and_file(self) -> None:
        with (
            mock.patch.object(Path, "exists", return_value=True),
            mock.patch.object(
                send_grbl_file,
                "_find_conflicting_sender_processes",
                return_value=[(123, "python src\\send_grbl_file.py COM6 115200 D:\\job.nc")],
            ),
            mock.patch.object(send_grbl_file, "open_grbl") as open_grbl,
        ):
            rc = send_grbl_file.main(["send_grbl_file.py", "COM6", "115200", "D:\\job.nc"])

        self.assertEqual(rc, 4)
        open_grbl.assert_not_called()

    def test_find_conflicting_sender_processes_matches_relative_file_command(self) -> None:
        proc_payload = (
            '[{"ProcessId":123,'
            '"CommandLine":"python D:\\\\plotter_pdf\\\\src\\\\send_grbl_file.py COM6 115200 job.nc"}]'
        )

        with (
            mock.patch.object(send_grbl_file.os, "name", "nt"),
            mock.patch.object(send_grbl_file.os, "getpid", return_value=999),
            mock.patch.object(
                send_grbl_file.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=proc_payload),
            ),
        ):
            conflicts = send_grbl_file._find_conflicting_sender_processes("COM6", Path(r"D:\plotter_pdf\job.nc"))

        self.assertEqual(conflicts, [(123, r"python D:\plotter_pdf\src\send_grbl_file.py COM6 115200 job.nc")])

    def test_find_conflicting_sender_processes_avoids_substring_matches(self) -> None:
        proc_payload = (
            "["
            '{"ProcessId":123,'
            '"CommandLine":"python D:\\\\plotter_pdf\\\\src\\\\send_grbl_file.py COM60 115200 D:\\\\plotter_pdf\\\\job.nc"},'
            '{"ProcessId":124,'
            '"CommandLine":"python D:\\\\plotter_pdf\\\\src\\\\send_grbl_file.py COM6 115200 D:\\\\plotter_pdf\\\\oldjob.nc"},'
            '{"ProcessId":125,'
            '"CommandLine":"python D:\\\\plotter_pdf\\\\src\\\\send_grbl_file.py COM6 115200 D:\\\\plotter_pdf\\\\job.nc"}'
            "]"
        )

        with (
            mock.patch.object(send_grbl_file.os, "name", "nt"),
            mock.patch.object(send_grbl_file.os, "getpid", return_value=999),
            mock.patch.object(
                send_grbl_file.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=proc_payload),
            ),
        ):
            conflicts = send_grbl_file._find_conflicting_sender_processes("COM6", Path(r"D:\plotter_pdf\job.nc"))

        self.assertEqual(conflicts, [(125, r"python D:\plotter_pdf\src\send_grbl_file.py COM6 115200 D:\plotter_pdf\job.nc")])


if __name__ == "__main__":
    unittest.main()
