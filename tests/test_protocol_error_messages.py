from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plotter_studio.core.protocol import BackendBridge
from src.plotter_backend.errors import ToolDependencyError


class _WordFailBackend:
    def word_to_pdf(self, *_args, **_kwargs) -> None:
        raise ToolDependencyError("pywin32 is missing")


class _PreviewBackend:
    Z_UP = 0.0
    Z_DOWN = 10.0


class _ResetFailBackend:
    def reset_pencil_state_after_sharpen(self, *_args, **_kwargs) -> None:
        raise RuntimeError("state file locked")


class _ProbeBackend:
    pass


class ProtocolErrorMessageTests(unittest.TestCase):
    def test_resolve_method3_source_pdf_includes_exception_class(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_err_") as td:
            root = Path(td)
            docx = root / "sample.docx"
            docx.write_text("docx", encoding="utf-8")
            work = root / "work"
            work.mkdir(parents=True, exist_ok=True)
            bridge = BackendBridge(root)

            ok, pdf_src, msg = bridge._resolve_method3_source_pdf(
                backend=_WordFailBackend(),
                input_path=docx,
                body_font="Marck Script",
                formula_font="Times New Roman",
                work_dir=work,
                log=lambda _line: None,
            )

            self.assertFalse(ok)
            self.assertIsNone(pdf_src)
            self.assertIn("ToolDependencyError", msg)
            self.assertIn("pywin32 is missing", msg)

    def test_build_vector_preview_error_includes_exception_class(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_prev_err_") as td:
            root = Path(td)
            bridge = BackendBridge(root)
            gcode = root / "in.nc"
            svg = root / "out.svg"
            pdf = root / "out.pdf"
            gcode.write_text("G21\nG90\nG1 X1 Y1\n", encoding="utf-8")

            with mock.patch("plotter_studio.core.protocol._gcode_to_polylines", side_effect=ValueError("bad gcode")):
                ok, msg = bridge._build_vector_preview_from_gcode(
                    gcode,
                    svg,
                    pdf,
                    backend=_PreviewBackend(),
                    log=lambda *_args: None,
                )

            self.assertFalse(ok)
            self.assertIn("ValueError", msg)
            self.assertIn("bad gcode", msg)

    def test_reset_pencil_after_sharpen_error_includes_exception_class(self) -> None:
        bridge = BackendBridge(Path.cwd())
        with mock.patch.object(bridge, "_backend", return_value=_ResetFailBackend()):
            ok, msg = bridge.reset_pencil_after_sharpen(lambda *_args: None)
        self.assertFalse(ok)
        self.assertIn("RuntimeError", msg)
        self.assertIn("state file locked", msg)

    def test_probe_connection_appends_bluetooth_hint(self) -> None:
        bridge = BackendBridge(Path.cwd())
        with mock.patch.object(bridge, "_backend", return_value=_ProbeBackend()):
            with mock.patch.object(
                bridge,
                "_run_manual_commands_with_timeout",
                return_value=(False, "Cannot open COM11 @ 115200: OSError(22, device missing)"),
            ):
                with mock.patch(
                    "plotter_studio.core.protocol.build_serial_open_hint",
                    return_value="Bluetooth SPP hint: COM11 is a ghost port. Use COM6 now.",
                ):
                    ok, msg = bridge.probe_connection("COM11", "115200", lambda *_args: None)

        self.assertFalse(ok)
        self.assertIn("Cannot open COM11", msg)
        self.assertIn("ghost port", msg)
        self.assertIn("COM6", msg)


if __name__ == "__main__":
    unittest.main()
