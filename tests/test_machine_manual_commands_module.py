from __future__ import annotations

import builtins
import unittest
from unittest import mock

from src.plotter_backend.machine import manual_commands


class _FakeSerial:
    def __init__(self) -> None:
        self.port = ""
        self.baudrate = 0
        self.timeout = 0.0
        self.dtr = True
        self.rts = True
        self.open_called = False
        self.closed = False
        self.writes: list[bytes] = []
        self.read_payload = b"ok\n<Idle|MPos:0,0,0>"

    def open(self) -> None:
        self.open_called = True

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))

    def flush(self) -> None:
        return None

    def read(self, _n: int) -> bytes:
        return self.read_payload

    def close(self) -> None:
        self.closed = True


class MachineManualCommandsModuleTests(unittest.TestCase):
    def test_grbl_send_manual_commands_success_with_tail(self) -> None:
        fake = _FakeSerial()
        ok, msg = manual_commands.grbl_send_manual_commands(
            "COM6",
            "115200",
            ["$X", "G21"],
            default_baud="9600",
            read_tail=True,
            soft_reset_first=True,
            serial_factory=lambda: fake,
            wake_delay_s=0.0,
            reset_delay_s=0.0,
            command_delay_s=0.0,
            tail_delay_s=0.0,
        )

        self.assertTrue(ok)
        self.assertIn("Idle", msg)
        self.assertEqual(fake.port, "COM6")
        self.assertEqual(fake.baudrate, 115200)
        self.assertTrue(fake.open_called)
        self.assertTrue(fake.closed)
        self.assertIn(b"\r\n", fake.writes)
        self.assertIn(b"\x18", fake.writes)
        self.assertIn(b"$X\n", fake.writes)
        self.assertIn(b"G21\n", fake.writes)

    def test_grbl_send_manual_commands_success_without_tail(self) -> None:
        fake = _FakeSerial()
        ok, msg = manual_commands.grbl_send_manual_commands(
            "COM6",
            "bad-baud",
            ["G90"],
            default_baud="57600",
            read_tail=False,
            serial_factory=lambda: fake,
            wake_delay_s=0.0,
            command_delay_s=0.0,
        )

        self.assertTrue(ok)
        self.assertEqual(msg, "ok")
        self.assertEqual(fake.baudrate, 57600)

    def test_grbl_send_manual_commands_rejects_empty_port(self) -> None:
        ok, msg = manual_commands.grbl_send_manual_commands(
            "",
            "115200",
            ["$X"],
            default_baud="115200",
            serial_factory=lambda: _FakeSerial(),
        )
        self.assertFalse(ok)
        self.assertEqual(msg, "COM port is empty.")

    def test_grbl_send_manual_commands_returns_exception_class_for_serial_failure(self) -> None:
        def _raise_serial():
            raise RuntimeError("port locked")

        ok, msg = manual_commands.grbl_send_manual_commands(
            "COM3",
            "115200",
            ["$I"],
            default_baud="115200",
            serial_factory=_raise_serial,
        )
        self.assertFalse(ok)
        self.assertIn("RuntimeError", msg)
        self.assertIn("port locked", msg)

    def test_grbl_send_manual_commands_reports_missing_pyserial_as_dependency_error(self) -> None:
        original_import = builtins.__import__

        def _import(name, *args, **kwargs):
            if name == "serial":
                raise ModuleNotFoundError("No module named 'serial'")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=_import):
            ok, msg = manual_commands.grbl_send_manual_commands(
                "COM5",
                "115200",
                ["$I"],
                default_baud="115200",
            )

        self.assertFalse(ok)
        self.assertIn("ToolDependencyError", msg)
        self.assertIn("pyserial not available", msg)

    def test_grbl_send_manual_commands_uses_tcp_transport_for_wifi_endpoint(self) -> None:
        fake = _FakeSerial()
        with mock.patch(
            "src.plotter_backend.machine.grbl_transport.open_grbl_transport",
            return_value=fake,
        ) as open_transport:
            ok, msg = manual_commands.grbl_send_manual_commands(
                "tcp://192.168.1.50:23",
                "115200",
                ["?"],
                default_baud="115200",
            )

        self.assertTrue(ok)
        self.assertIn("ok", msg)
        open_transport.assert_called_once()


if __name__ == "__main__":
    unittest.main()
