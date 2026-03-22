from __future__ import annotations

import types
import unittest

from src.plotter_backend.errors import SerialTransportError
from src.plotter_backend.machine import grbl_probe


class _Backend:
    SerialTransportError = SerialTransportError

    def __init__(self) -> None:
        self._status = ""
        self._offsets = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    def _grbl_readline_ascii(self, _ser) -> str:
        return ""

    def _open_serial_no_reset(self, _port, _baud, *, timeout_s=0.0):
        return types.SimpleNamespace(close=lambda: None)

    def _grbl_status_line(self, _ser, *, timeout_s=0.0) -> str:
        return self._status

    def _parse_grbl_triplet(self, tag: str, text: str):
        return grbl_probe.parse_grbl_triplet(tag, text)

    def _grbl_query_offsets(self, _ser):
        return self._offsets


class GrblProbeModuleTests(unittest.TestCase):
    def test_parse_grbl_triplet_parses_values(self) -> None:
        values = grbl_probe.parse_grbl_triplet("WPos", "<Idle|WPos:1.25,-2.50,0.00|FS:0,0>")
        self.assertEqual(values, (1.25, -2.5, 0.0))

    def test_grbl_get_wpos_xyz_uses_reported_wpos(self) -> None:
        backend = _Backend()
        backend._status = "<Idle|WPos:5.0,6.0,0.0|FS:0,0>"
        self.assertEqual(grbl_probe.grbl_get_wpos_xyz(backend, "COM6", "115200"), (5.0, 6.0, 0.0))

    def test_grbl_get_wpos_xyz_falls_back_to_mpos_minus_offsets(self) -> None:
        backend = _Backend()
        backend._status = "<Idle|MPos:15.0,26.0,3.0|FS:0,0>"
        backend._offsets = ((10.0, 20.0, 1.0), (1.0, 2.0, 0.5))
        self.assertEqual(grbl_probe.grbl_get_wpos_xyz(backend, "COM6", "115200"), (4.0, 4.0, 1.5))
