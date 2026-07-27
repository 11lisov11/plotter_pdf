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

    def test_run_corner_calibration_pipeline_forces_full_lift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_err_map_cal_") as td:
            root = Path(td)
            captured: dict[str, object] = {}

            def _fake_write_xy(path, _polys, _ft, _fd):
                Path(path).write_text("G21\nG90\nG0 X0 Y0\nG1 X1 Y0\n", encoding="utf-8")

            def _fake_penlift(_xy, pen, **kwargs):
                captured.update(kwargs)
                Path(pen).write_text("G0 Z0\nG0 X0 Y0\n", encoding="utf-8")

            def _fake_finalize(_prepared, final):
                Path(final).write_text("G0 Z0\n", encoding="utf-8")

            with (
                mock.patch.object(backend, "ensure_local_tmp_root", return_value=root),
                mock.patch.object(backend, "build_area_corner_mark_polylines", return_value=[[(0.0, 0.0), (1.0, 0.0)]]),
                mock.patch.object(backend, "clip_polylines_to_work_area", side_effect=lambda polys, logger=None: polys),
                mock.patch.object(backend, "write_xy_gcode", side_effect=_fake_write_xy),
                mock.patch.object(backend, "apply_penlift", side_effect=_fake_penlift),
                mock.patch.object(backend, "make_final_with_preamble", side_effect=_fake_finalize),
            ):
                ok, msg = backend.run_corner_calibration_pipeline(lambda *_args: None, send_to_plotter=False)
            self.assertTrue(ok, msg)
            self.assertTrue(bool(captured.get("force_full_lift")))
            self.assertEqual(captured.get("z_down"), backend.Z_DOWN)

    def test_apply_penlift_uses_active_profile_z_down_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_dynamic_z_") as td:
            root = Path(td)
            xy_path = root / "xy.nc"
            pen_path = root / "pen.nc"
            xy_path.write_text("G21\nG90\n", encoding="utf-8")
            with (
                mock.patch.object(backend, "Z_DOWN", -4.0),
                mock.patch.object(backend.gcode_penlift_mod, "run_penlift_postprocess") as postprocess,
            ):
                backend.apply_penlift(xy_path, pen_path)

            self.assertEqual(postprocess.call_args.kwargs["z_down"], -4.0)

    def test_rewrite_rapid_moves_as_controlled_preserves_feed_and_other_commands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_controlled_motion_") as td:
            path = Path(td) / "a2.nc"
            path.write_text("G0 X10 Y20 F1500\nG00 Z0 F2000\nG1 X20 Y20 F1500\n", encoding="utf-8")

            changed = backend.rewrite_rapid_moves_as_controlled(path)
            text = path.read_text(encoding="utf-8")

            self.assertEqual(changed, 2)
            self.assertIn("G1 X10 Y20 F1500", text)
            self.assertIn("G1 Z0 F2000", text)
            self.assertEqual(text.count("G1 X20 Y20 F1500"), 1)

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
