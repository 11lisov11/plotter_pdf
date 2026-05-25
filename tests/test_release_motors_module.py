from __future__ import annotations

import unittest
from unittest import mock

from src import release_motors


class _FakeSerial:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.in_waiting = 1
        self.closed = False
        self._status_pending = False

    def open(self) -> None:
        return None

    def reset_input_buffer(self) -> None:
        return None

    def reset_output_buffer(self) -> None:
        return None

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))
        if data == b"?":
            self._status_pending = True

    def flush(self) -> None:
        return None

    def readline(self) -> bytes:
        if self._status_pending:
            self._status_pending = False
            return b"<Idle|MPos:0.000,0.000,0.000|FS:0,0>\n"
        return b"ok\n"

    def close(self) -> None:
        self.closed = True


class ReleaseMotorsModuleTests(unittest.TestCase):
    def test_release_motors_returns_home_before_motor_release(self) -> None:
        fake = _FakeSerial()

        with (
            mock.patch.object(release_motors.serial, "Serial", return_value=fake),
            mock.patch.object(release_motors.time, "sleep", return_value=None),
        ):
            rc = release_motors.main(["release_motors.py", "COM6", "115200"])

        self.assertEqual(rc, 0)
        cmds = [raw.decode("ascii").strip() for raw in fake.writes]
        self.assertIn("G0 Z0.0000 F800.0", cmds)
        self.assertIn("G0 X0.0000 Y0.0000 F900.0", cmds)
        self.assertIn("?", cmds)
        self.assertIn("$1=0", cmds)
        self.assertLess(cmds.index("G0 Z0.0000 F800.0"), cmds.index("G0 X0.0000 Y0.0000 F900.0"))
        self.assertLess(cmds.index("G0 X0.0000 Y0.0000 F900.0"), max(idx for idx, cmd in enumerate(cmds) if cmd == "?"))
        self.assertLess(cmds.index("G0 X0.0000 Y0.0000 F900.0"), cmds.index("$1=0"))
        self.assertLess(max(idx for idx, cmd in enumerate(cmds) if cmd == "?"), cmds.index("$1=0"))
        self.assertTrue(fake.closed)

    def test_release_motors_does_not_release_when_idle_is_not_confirmed(self) -> None:
        fake = _FakeSerial()

        with (
            mock.patch.object(release_motors.serial, "Serial", return_value=fake),
            mock.patch.object(release_motors.time, "sleep", return_value=None),
            mock.patch.object(release_motors, "_wait_for_idle", return_value=False),
        ):
            rc = release_motors.main(["release_motors.py", "COM6", "115200"])

        cmds = [raw.decode("ascii").strip() for raw in fake.writes]
        self.assertEqual(rc, 1)
        self.assertIn("G0 X0.0000 Y0.0000 F900.0", cmds)
        self.assertNotIn("$1=0", cmds)
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
