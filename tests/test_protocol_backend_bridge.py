from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fitz  # type: ignore

import plotter_studio.core.protocol as protocol_mod
from plotter_studio.core.protocol import BackendBridge
from src import plotter_pdf_drawer as backend_mod
from src.plotter_backend.errors import ToolDependencyError


class _PreviewBackend:
    Z_UP = 0.0
    Z_DOWN = 10.0

    @staticmethod
    def work_area_bounds():
        return (0.0, 180.0, -295.0, -15.0)


class _Port:
    def __init__(self, device: str) -> None:
        self.device = device


class ProtocolBackendBridgeTests(unittest.TestCase):
    def test_allow_method3_detail_thick_multipass_respects_exact_geometry_mode(self) -> None:
        backend = type("_Backend", (), {"EXACT_GEOMETRY_MODE": True})()
        allow, reason = protocol_mod._allow_method3_detail_thick_multipass(backend)
        self.assertFalse(allow)
        self.assertEqual(reason, "exact_geometry_mode")

    def test_compose_method3_multipass_hybrid_canvas_keeps_detail_one_to_one(self) -> None:
        polys = [
            [(20.5, 5.5), (415.5, 5.5)],
            [(415.5, 5.5), (415.5, 292.5)],
            [(20.5, 5.5), (20.5, 292.5)],
            [(20.5, 292.5), (415.5, 292.5)],
            [(20.5, 5.5), (380.3, 5.5), (380.3, 231.9), (20.5, 231.9), (20.5, 5.5)],
        ]
        out, detail_paths, info = protocol_mod._compose_method3_multipass_hybrid_canvas_mm(
            polys,
            page_w_mm=421.096,
            page_h_mm=298.148,
            crop_left_mm=0.0,
            crop_right_mm=0.0,
            crop_top_mm=0.0,
            crop_bottom_mm=0.0,
            target_w_mm=360.0,
            target_h_mm=280.0,
        )
        self.assertTrue(bool(info.get("applied")))
        self.assertEqual(detail_paths, 1)
        detail_poly = out[-1]
        xs = [p[0] for p in detail_poly]
        ys = [p[1] for p in detail_poly]
        self.assertAlmostEqual(max(xs) - min(xs), 359.8, places=3)
        self.assertAlmostEqual(max(ys) - min(ys), 226.4, places=3)
        self.assertAlmostEqual(float(out[0][0][0]), 0.0, places=6)
        self.assertAlmostEqual(float(out[0][-1][0]), 360.0, places=6)

    def test_backend_raises_when_script_is_missing_and_import_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_backend_missing_") as td:
            root = Path(td)
            bridge = BackendBridge(root)
            with mock.patch.dict("sys.modules", {"src": None}):
                with self.assertRaisesRegex(ToolDependencyError, "Backend script not found"):
                    bridge._backend()

    def test_backend_raises_when_spec_load_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_backend_spec_") as td:
            root = Path(td)
            src_dir = root / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / "plotter_pdf_drawer.py").write_text("DEFAULT_BAUD='115200'\n", encoding="utf-8")
            bridge = BackendBridge(root)
            with (
                mock.patch.dict("sys.modules", {"src": None}),
                mock.patch("plotter_studio.core.protocol.importlib.util.spec_from_file_location", return_value=None),
            ):
                with self.assertRaisesRegex(ToolDependencyError, "Cannot load backend module"):
                    bridge._backend()

    def test_backend_fallback_loads_module_and_caches_default_baud(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_backend_ok_") as td:
            root = Path(td)
            src_dir = root / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / "plotter_pdf_drawer.py").write_text(
                "\n".join(
                    [
                        "DEFAULT_BAUD='230400'",
                        "PENCIL_BASE_Z_DOWN=11.0",
                        "Z_UP=1.0",
                        "def detect_com_port(preferred=None):",
                        "    return preferred or 'COM8'",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            bridge = BackendBridge(root)
            with mock.patch.dict("sys.modules", {"src": None}):
                mod = bridge._backend()
            self.assertEqual(getattr(mod, "DEFAULT_BAUD", ""), "230400")
            self.assertEqual(bridge.detect_com_port("COM9"), "COM9")
            self.assertEqual(bridge.default_baud(), "230400")
            self.assertGreater(bridge.z_down_sign(), 0.0)

    def test_list_com_ports_sorts_and_filters(self) -> None:
        bridge = BackendBridge(Path.cwd())
        with mock.patch(
            "plotter_studio.core.protocol.list_ports.comports",
            return_value=[_Port("COM7"), _Port(""), _Port("COM2")],
        ):
            ports = bridge.list_com_ports()
        self.assertEqual(ports, ["COM2", "COM7"])

    def test_default_baud_uses_cache_when_backend_attribute_missing(self) -> None:
        bridge = BackendBridge(Path.cwd())
        bridge._backend_module = object()
        self.assertEqual(bridge.default_baud(), "115200")

    def test_build_vector_preview_returns_error_when_gcode_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_prev_missing_") as td:
            root = Path(td)
            bridge = BackendBridge(root)
            ok, msg = bridge._build_vector_preview_from_gcode(
                root / "missing.nc",
                root / "out.svg",
                root / "out.pdf",
                backend=_PreviewBackend(),
                log=lambda *_args: None,
            )
            self.assertFalse(ok)
            self.assertIn("G-code file not found", msg)

    def test_build_vector_preview_returns_error_when_no_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_prev_empty_") as td:
            root = Path(td)
            gcode = root / "in.nc"
            gcode.write_text("G21\nG90\n", encoding="utf-8")
            bridge = BackendBridge(root)
            with mock.patch("plotter_studio.core.protocol._gcode_to_polylines", return_value=[]):
                ok, msg = bridge._build_vector_preview_from_gcode(
                    gcode,
                    root / "out.svg",
                    root / "out.pdf",
                    backend=_PreviewBackend(),
                    log=lambda *_args: None,
                )
            self.assertFalse(ok)
            self.assertIn("no drawable paths", msg)

    def test_build_vector_preview_uses_work_area_canvas_bounds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_prev_canvas_") as td:
            root = Path(td)
            gcode = root / "in.nc"
            gcode.write_text("G21\nG90\nG0 Z0\nG1 Z10\nG1 X10 Y-20\nG1 X20 Y-30\n", encoding="utf-8")
            bridge = BackendBridge(root)
            ok, msg = bridge._build_vector_preview_from_gcode(
                gcode,
                root / "out.svg",
                root / "out.pdf",
                backend=_PreviewBackend(),
                log=lambda *_args: None,
            )
            self.assertTrue(ok, msg)
            with fitz.open(root / "out.pdf") as pdf:
                rect = pdf[0].rect
            self.assertAlmostEqual(rect.width, (180.0 + 4.0) * 72.0 / 25.4, places=1)
            self.assertAlmostEqual(rect.height, (280.0 + 4.0) * 72.0 / 25.4, places=1)

    def test_method3_centerline_raises_when_autotrace_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_ctrace_missing_") as td:
            root = Path(td)
            bridge = BackendBridge(root)

            class _NoAutotraceBackend:
                @staticmethod
                def _resolve_autotrace_executable():
                    return None

            gray = backend_mod.np.full((6, 6), 255, dtype=backend_mod.np.uint8)
            with self.assertRaisesRegex(ToolDependencyError, "autotrace.exe not found"):
                bridge._run_method3_centerline_page(_NoAutotraceBackend(), gray, lambda *_args: None)

    def test_method3_centerline_selects_non_empty_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_ctrace_ok_") as td:
            root = Path(td)
            bridge = BackendBridge(root)
            gray = backend_mod.np.full((24, 24), 255, dtype=backend_mod.np.uint8)
            gray[10:12, 3:20] = 0

            with (
                mock.patch.object(backend_mod, "_resolve_autotrace_executable", return_value=Path("autotrace.exe")),
                mock.patch.object(
                    backend_mod,
                    "_run_autotrace_centerline_on_binary",
                    return_value=[[(0.0, 0.0), (5.0, 0.0), (12.0, 0.0)]],
                ),
            ):
                polys, thr = bridge._run_method3_centerline_page(backend_mod, gray, lambda *_args: None)
            self.assertTrue(polys)
            self.assertGreaterEqual(thr, 1)

    def test_method3_split_masks_and_graphics_outline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_masks_") as td:
            root = Path(td)
            bridge = BackendBridge(root)
            gray = backend_mod.np.full((120, 120), 255, dtype=backend_mod.np.uint8)
            backend_mod.cv2.rectangle(gray, (5, 5), (95, 80), 0, thickness=-1)
            backend_mod.cv2.rectangle(gray, (100, 100), (102, 102), 0, thickness=-1)

            text_mask, graphics_mask = bridge._split_method3_text_graphics_masks(backend_mod, gray, 128)
            self.assertGreater(int(backend_mod.np.count_nonzero(text_mask)), 0)
            self.assertGreater(int(backend_mod.np.count_nonzero(graphics_mask)), 0)
            outlines = bridge._extract_graphics_outline_polylines_px(backend_mod, graphics_mask)
            self.assertTrue(outlines)

    def test_prepare_method3_page_rejects_unsupported_extension(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_m3_ext_") as td:
            root = Path(td)
            bridge = BackendBridge(root)
            txt = root / "in.txt"
            txt.write_text("x", encoding="utf-8")
            ok, msg = bridge._prepare_method3_page(
                backend=backend_mod,
                input_path=txt,
                source_page_index=1,
                body_font="Marck Script",
                formula_font="Times New Roman",
                output_svg=root / "out.svg",
                output_pdf=root / "out.pdf",
                output_nc=None,
                log=lambda *_args: None,
            )
            self.assertFalse(ok)
            self.assertIn("supports .doc/.docx/.pdf", msg)

    def test_prepare_method3_page_checks_source_page_range(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_m3_range_") as td:
            root = Path(td)
            bridge = BackendBridge(root)
            src_pdf = root / "source.pdf"
            src_pdf.write_bytes(b"%PDF-1.4\n")
            ok, msg = bridge._prepare_method3_page(
                backend=backend_mod,
                input_path=src_pdf,
                source_page_index=2,
                body_font="Marck Script",
                formula_font="Times New Roman",
                output_svg=root / "out.svg",
                output_pdf=root / "out.pdf",
                output_nc=None,
                log=lambda *_args: None,
                source_pdf_path=src_pdf,
                source_page_count=1,
            )
            self.assertFalse(ok)
            self.assertIn("out of range", msg)

    def test_prepare_method3_page_success_with_mocked_external_steps(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_m3_ok_") as td:
            root = Path(td)
            bridge = BackendBridge(root)
            src_pdf = root / "source.pdf"
            src_pdf.write_bytes(b"%PDF-1.4\n")
            out_svg = root / "out.svg"
            out_pdf = root / "out.pdf"
            out_nc = root / "out.nc"
            sample_gray = backend_mod.np.full((100, 80), 255, dtype=backend_mod.np.uint8)
            sample_gray[20:22, 5:60] = 0

            def _fake_run_cmd(cmd, timeout_s=0.0):
                _ = timeout_s
                for arg in cmd:
                    if str(arg).startswith("--export-filename="):
                        target = Path(str(arg).split("=", 1)[1])
                        if "--export-type=png" in cmd:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            backend_mod.cv2.imwrite(str(target), sample_gray)
                            return 0, "", ""
                        if "--export-type=pdf" in cmd:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(b"%PDF-1.4\n")
                            return 0, "", ""
                return 0, "", ""

            def _fake_pipeline(_input_path, _log, **kwargs):
                target = Path(kwargs["output_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("G21\nG90\nG1 X1 Y1\n", encoding="utf-8")
                return True, "ok"

            with (
                mock.patch.object(backend_mod, "ensure_local_tmp_root", return_value=root),
                mock.patch.object(backend_mod, "find_inkscape", return_value="inkscape.exe"),
                mock.patch.object(backend_mod, "run_cmd", side_effect=_fake_run_cmd),
                mock.patch.object(bridge, "_run_method3_centerline_page", return_value=([[(0.0, 0.0), (6.0, 0.0)]], 128)),
                mock.patch.object(
                    bridge,
                    "_split_method3_text_graphics_masks",
                    return_value=(
                        backend_mod.np.zeros((100, 80), dtype=backend_mod.np.uint8),
                        backend_mod.np.zeros((100, 80), dtype=backend_mod.np.uint8),
                    ),
                ),
                mock.patch.object(bridge, "_extract_graphics_outline_polylines_px", return_value=[]),
                mock.patch.object(backend_mod, "run_pipeline_with_corner_calibration", side_effect=_fake_pipeline),
            ):
                ok, msg = bridge._prepare_method3_page(
                    backend=backend_mod,
                    input_path=src_pdf,
                    source_page_index=1,
                    body_font="Marck Script",
                    formula_font="Times New Roman",
                    output_svg=out_svg,
                    output_pdf=out_pdf,
                    output_nc=out_nc,
                    log=lambda *_args: None,
                    source_pdf_path=src_pdf,
                    source_page_count=1,
                )

            self.assertTrue(ok, msg)
            self.assertEqual(msg, "")
            self.assertTrue(out_svg.exists())
            self.assertTrue(out_pdf.exists())
            self.assertTrue(out_nc.exists())


if __name__ == "__main__":
    unittest.main()
