from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import plotter_pdf_drawer as backend
from src.plotter_backend.errors import SerialTransportError, ToolDependencyError


class BackendErrorMappingTests(unittest.TestCase):
    def test_format_backend_exception_for_backend_error(self) -> None:
        msg = backend._format_backend_exception(ToolDependencyError("missing tool"))  # type: ignore[attr-defined]
        self.assertIn("ToolDependencyError", msg)
        self.assertIn("missing tool", msg)

    def test_format_backend_exception_for_generic_error(self) -> None:
        msg = backend._format_backend_exception(RuntimeError("generic failure"))  # type: ignore[attr-defined]
        self.assertEqual(msg, "Error[RuntimeError]: generic failure")

    def test_run_frame_pipeline_surfaces_backend_error_class(self) -> None:
        with mock.patch.object(backend, "build_area_frame_polylines", side_effect=ToolDependencyError("no frame source")):
            ok, msg = backend.run_frame_pipeline(lambda *_args: None, send_to_plotter=False)
        self.assertFalse(ok)
        self.assertIn("ToolDependencyError", msg)
        self.assertIn("no frame source", msg)

    def test_run_corner_calibration_pipeline_surfaces_generic_error_class(self) -> None:
        with mock.patch.object(backend, "build_area_corner_mark_polylines", side_effect=RuntimeError("mark build failed")):
            ok, msg = backend.run_corner_calibration_pipeline(lambda *_args: None, send_to_plotter=False)
        self.assertFalse(ok)
        self.assertEqual(msg, "Error[RuntimeError]: mark build failed")

    def test_run_pipeline_surfaces_conversion_error_class(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_err_map_conv_") as td:
            root = Path(td)
            source = root / "input.pdf"
            output = root / "prepared.nc"
            source.write_bytes(b"%PDF-1.4\n")
            with mock.patch.object(backend, "pdf_to_svg", side_effect=ToolDependencyError("pdftocairo missing")):
                ok, msg = backend.run_pipeline(source, lambda *_args: None, send_to_plotter=False, output_path=output)
        self.assertFalse(ok)
        self.assertIn("ToolDependencyError", msg)
        self.assertIn("pdftocairo missing", msg)

    def test_run_pipeline_surfaces_generic_exception_class(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_err_map_gen_") as td:
            root = Path(td)
            source = root / "input.pdf"
            output = root / "prepared.nc"
            source.write_bytes(b"%PDF-1.4\n")
            with mock.patch.object(backend, "pdf_to_svg", side_effect=RuntimeError("unexpected backend failure")):
                ok, msg = backend.run_pipeline(source, lambda *_args: None, send_to_plotter=False, output_path=output)
        self.assertFalse(ok)
        self.assertEqual(msg, "Error[RuntimeError]: unexpected backend failure")

    def test_grbl_wait_for_idle_timeout_is_serial_transport_error(self) -> None:
        class _Ser:
            def close(self) -> None:
                return None

        with mock.patch.object(backend, "_open_serial_no_reset", return_value=_Ser()):
            with self.assertRaises(SerialTransportError) as ctx:
                backend.grbl_wait_for_idle("COM6", "115200", lambda *_args: None, timeout_s=-1.0)
        self.assertIn("Timeout waiting for GRBL to become Idle", str(ctx.exception))

    def test_grbl_get_wpos_xyz_missing_status_is_serial_transport_error(self) -> None:
        class _Ser:
            def close(self) -> None:
                return None

        with (
            mock.patch.object(backend, "_open_serial_no_reset", return_value=_Ser()),
            mock.patch.object(backend, "_grbl_status_line", return_value="<Run|FS:0,0>"),
        ):
            with self.assertRaises(SerialTransportError) as ctx:
                backend.grbl_get_wpos_xyz("COM6", "115200")
        self.assertIn("Cannot read GRBL position", str(ctx.exception))

    def test_grbl_helpers_wrap_serial_open_failure(self) -> None:
        with mock.patch.object(backend, "_open_serial_no_reset", side_effect=OSError("port denied")):
            with self.assertRaises(SerialTransportError) as wait_ctx:
                backend.grbl_wait_for_idle("COM6", "115200", lambda *_args: None, timeout_s=0.01)
            with self.assertRaises(SerialTransportError) as pos_ctx:
                backend.grbl_get_wpos_xyz("COM6", "115200")
        self.assertIn("Cannot open GRBL serial", str(wait_ctx.exception))
        self.assertIn("Cannot open GRBL serial", str(pos_ctx.exception))


if __name__ == "__main__":
    unittest.main()
