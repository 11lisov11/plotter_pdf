from __future__ import annotations

import unittest
from unittest import mock

from src import release_motors


class _FakeSerial:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.in_waiting = 1
        self.closed = False

    def open(self) -> None:
        return None

    def reset_input_buffer(self) -> None:
        return None

    def reset_output_buffer(self) -> None:
        return None

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))

    def flush(self) -> None:
        return None

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
        self.assertIn("$1=0", cmds)
        self.assertLess(cmds.index("G0 Z0.0000 F800.0"), cmds.index("G0 X0.0000 Y0.0000 F900.0"))
        self.assertLess(cmds.index("G0 X0.0000 Y0.0000 F900.0"), cmds.index("$1=0"))
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
