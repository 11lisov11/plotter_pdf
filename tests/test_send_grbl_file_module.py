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


if __name__ == "__main__":
    unittest.main()
