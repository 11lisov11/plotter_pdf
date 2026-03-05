from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest import mock

from plotter_studio.core import protocol


class ProtocolControlTests(unittest.TestCase):
    def test_probe_connection_uses_fast_probe_profile(self) -> None:
        class _Backend:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, list[str], dict[str, object]]] = []

            def grbl_send_manual_commands(self, com: str, baud: str, commands: list[str], **kwargs):
                self.calls.append((com, baud, list(commands), dict(kwargs)))
                return True, "ok"

        bridge = protocol.BackendBridge(Path.cwd())
        backend = _Backend()
        logs: list[str] = []

        with mock.patch.object(bridge, "_backend", return_value=backend):
            ok, text = bridge.probe_connection("COM11", "115200", logs.append)

        self.assertTrue(ok)
        self.assertEqual(text, "ok")
        self.assertEqual(len(backend.calls), 1)
        com, baud, commands, kwargs = backend.calls[0]
        self.assertEqual(com, "COM11")
        self.assertEqual(baud, "115200")
        self.assertEqual(commands, ["$X", "$I", "?", "$$"])
        self.assertTrue(bool(kwargs.get("soft_reset_first")))
        self.assertTrue(bool(kwargs.get("read_tail")))
        self.assertAlmostEqual(float(kwargs.get("serial_timeout_s", 0.0)), 0.60, places=6)
        self.assertAlmostEqual(float(kwargs.get("reset_delay_s", 0.0)), 0.35, places=6)
        self.assertGreaterEqual(len(logs), 1)

    def test_probe_connection_falls_back_for_legacy_backend_signature(self) -> None:
        class _LegacyBackend:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, list[str], bool, bool]] = []

            def grbl_send_manual_commands(
                self,
                com: str,
                baud: str,
                commands: list[str],
                *,
                soft_reset_first: bool = False,
                read_tail: bool = True,
            ):
                self.calls.append((com, baud, list(commands), soft_reset_first, read_tail))
                return True, "legacy-ok"

        bridge = protocol.BackendBridge(Path.cwd())
        backend = _LegacyBackend()

        with mock.patch.object(bridge, "_backend", return_value=backend):
            ok, text = bridge.probe_connection("COM3", "9600", lambda *_: None)

        self.assertTrue(ok)
        self.assertEqual(text, "legacy-ok")
        self.assertEqual(len(backend.calls), 1)
        com, baud, commands, soft_reset_first, read_tail = backend.calls[0]
        self.assertEqual(com, "COM3")
        self.assertEqual(baud, "9600")
        self.assertEqual(commands, ["$X", "$I", "?", "$$"])
        self.assertTrue(soft_reset_first)
        self.assertTrue(read_tail)

    def test_probe_connection_times_out_for_hanging_backend_call(self) -> None:
        class _HangingBackend:
            def __init__(self) -> None:
                self.calls = 0

            def grbl_send_manual_commands(self, com: str, baud: str, commands: list[str], **kwargs):
                self.calls += 1
                time.sleep(0.60)
                return True, "late-ok"

        bridge = protocol.BackendBridge(Path.cwd())
        backend = _HangingBackend()

        ok, text = bridge._run_manual_commands_with_timeout(
            backend,
            "COM7",
            "115200",
            ["$I"],
            kwargs={"soft_reset_first": True, "read_tail": True},
            timeout_s=0.05,
        )
        self.assertFalse(ok)
        self.assertIn("timed out", text.lower())

    def test_probe_connection_includes_exception_class_on_backend_error(self) -> None:
        class SerialFailure(Exception):
            pass

        class _FailingBackend:
            def grbl_send_manual_commands(self, com: str, baud: str, commands: list[str], **kwargs):
                raise SerialFailure("port unavailable")

        bridge = protocol.BackendBridge(Path.cwd())
        backend = _FailingBackend()

        with mock.patch.object(bridge, "_backend", return_value=backend):
            ok, text = bridge.probe_connection("COM7", "115200", lambda *_: None)

        self.assertFalse(ok)
        self.assertIn("SerialFailure", text)
        self.assertIn("port unavailable", text)

    def test_manual_commands_forwards_flags(self) -> None:
        class _Backend:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, list[str], dict[str, object]]] = []

            def grbl_send_manual_commands(self, com: str, baud: str, commands: list[str], **kwargs):
                self.calls.append((com, baud, list(commands), dict(kwargs)))
                return True, "tail"

        bridge = protocol.BackendBridge(Path.cwd())
        backend = _Backend()

        with mock.patch.object(bridge, "_backend", return_value=backend):
            ok, text = bridge.manual_commands(
                "COM9",
                "230400",
                ["G21", "G90"],
                soft_reset_first=True,
                read_tail=False,
            )

        self.assertTrue(ok)
        self.assertEqual(text, "tail")
        self.assertEqual(len(backend.calls), 1)
        com, baud, commands, kwargs = backend.calls[0]
        self.assertEqual(com, "COM9")
        self.assertEqual(baud, "230400")
        self.assertEqual(commands, ["G21", "G90"])
        self.assertEqual(kwargs, {"soft_reset_first": True, "read_tail": False})

    def test_manual_commands_returns_typed_error_on_backend_exception(self) -> None:
        class _Backend:
            def grbl_send_manual_commands(self, *_args, **_kwargs):
                raise RuntimeError("manual channel unavailable")

        bridge = protocol.BackendBridge(Path.cwd())
        with mock.patch.object(bridge, "_backend", return_value=_Backend()):
            ok, text = bridge.manual_commands("COM4", "115200", ["$I"])

        self.assertFalse(ok)
        self.assertIn("RuntimeError", text)
        self.assertIn("manual channel unavailable", text)

    def test_emergency_stop_returns_typed_error_on_backend_exception(self) -> None:
        class _Backend:
            def grbl_send_manual_commands(self, *_args, **_kwargs):
                raise ValueError("estop transport failure")

        bridge = protocol.BackendBridge(Path.cwd())
        with mock.patch.object(bridge, "_backend", return_value=_Backend()):
            ok, text = bridge.emergency_stop("COM8", "115200", lambda *_args: None)

        self.assertFalse(ok)
        self.assertIn("ValueError", text)
        self.assertIn("estop transport failure", text)


if __name__ == "__main__":
    unittest.main()
