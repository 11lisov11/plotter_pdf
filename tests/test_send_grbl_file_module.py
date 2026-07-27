from __future__ import annotations

import unittest

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


class _FakeFluidNcSerial(_FakeSerial):
    def __init__(self) -> None:
        super().__init__()
        self.timeout = 1.0
        self._responses: list[bytes] = []

    def write(self, data: bytes) -> None:
        super().write(data)
        command = data.decode("ascii").strip()
        self._responses.extend((f"{command}\r\n".encode("ascii"), b"ok\r\n"))

    def readline(self) -> bytes:
        return self._responses.pop(0) if self._responses else b""


class SendGrblFileModuleTests(unittest.TestCase):
    def test_release_axes_forces_pen_up_before_motor_release(self) -> None:
        ser = _FakeSerial()

        send_grbl_file.release_axes(ser, sleep=False, wait=False)

        cmds = [raw.decode("ascii").strip() for raw in ser.writes]
        self.assertIn("G92 Z4.0000", cmds)
        self.assertIn("G1 Z0.0000 F800.0", cmds)
        self.assertIn("$1=0", cmds)
        self.assertLess(cmds.index("G92 Z4.0000"), cmds.index("G1 Z0.0000 F800.0"))
        self.assertLess(cmds.index("G1 Z0.0000 F800.0"), cmds.index("$1=0"))

    def test_release_axes_returns_home_before_motor_release(self) -> None:
        ser = _FakeSerial()

        send_grbl_file.release_axes(ser, sleep=False, wait=False)

        cmds = [raw.decode("ascii").strip() for raw in ser.writes]
        self.assertIn("G1 X0.0000 Y0.0000 F900.0", cmds)
        self.assertIn("$1=0", cmds)
        self.assertLess(cmds.index("G1 Z0.0000 F800.0"), cmds.index("G1 X0.0000 Y0.0000 F900.0"))
        self.assertLess(cmds.index("G1 X0.0000 Y0.0000 F900.0"), cmds.index("$1=0"))

    def test_release_axes_waits_for_home_idle_before_motor_release(self) -> None:
        ser = _FakeIdleSerial()

        send_grbl_file.release_axes(ser, sleep=False, wait=True)

        cmds = [raw.decode("ascii").strip() for raw in ser.writes]
        self.assertIn("?", cmds)
        self.assertLess(cmds.index("G1 X0.0000 Y0.0000 F900.0"), cmds.index("?"))
        self.assertLess(cmds.index("?"), cmds.index("$1=0"))

    def test_release_axes_uses_single_cr_for_commands(self) -> None:
        ser = _FakeSerial()

        send_grbl_file.release_axes(ser, sleep=False, wait=False)

        self.assertTrue(all(raw.endswith(b"\r") and not raw.endswith(b"\r\n") for raw in ser.writes))

    def test_stream_uses_single_cr_and_accepts_fluidnc_echo(self) -> None:
        ser = _FakeFluidNcSerial()

        send_grbl_file.stream_lines_to_grbl(ser, ["G21", "G90", "G0 X5 Y5"], rx_buffer_size=32)

        self.assertEqual(ser.writes, [b"G21\r", b"G90\r", b"G0 X5 Y5\r"])

    def test_fluidnc_motor_initialisation_precedes_enable(self) -> None:
        ser = _FakeFluidNcSerial()

        send_grbl_file._initialise_controller_motors(ser, "fluidnc")

        self.assertEqual(ser.writes, [b"$MI\r", b"$ME\r"])

    def test_grbl_motor_initialisation_does_not_send_fluidnc_commands(self) -> None:
        ser = _FakeFluidNcSerial()

        send_grbl_file._initialise_controller_motors(ser, "grbl")

        self.assertEqual(ser.writes, [])

    def test_a2_release_forces_lift_in_negative_z_profile_direction(self) -> None:
        commands = send_grbl_file._safe_pen_up_commands(z_up=0.0, z_down=-4.0, force_lift_mm=4.0)

        self.assertIn("G92 Z-4.0000", commands)
        self.assertIn("G1 Z0.0000 F800.0", commands)
        self.assertNotIn("G92 Z4.0000", commands)


if __name__ == "__main__":
    unittest.main()
