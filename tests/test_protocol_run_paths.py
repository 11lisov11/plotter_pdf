from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plotter_studio.core.protocol import BackendBridge, SheetConfig


class _FakeCtx:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.progress: list[tuple[int, str]] = []
        self.active_procs: list[object] = []

    def check_canceled(self) -> None:
        return None

    def set_active_process(self, proc) -> None:
        self.active_procs.append(proc)

    def emit_log(self, text: str) -> None:
        self.logs.append(text)

    def emit_progress(self, value: int, text: str = "") -> None:
        self.progress.append((value, text))


class _FakeBackend:
    def __init__(self, tmp_root: Path) -> None:
        self.tmp_root = tmp_root
        self.subprocess = subprocess
        self.DEFAULT_BAUD = "115200"
        self.DEFAULT_QUALITY_PROFILE = "normal"
        self.FEED_TRAVEL = 1000.0
        self.FEED_DRAW = 500.0
        self.Z_UP = 0.0
        self.Z_DOWN = 11.9
        self.PASS_COLS = 1
        self.PASS_ROWS = 1
        self.PASS_COL = 1
        self.PASS_ROW = 1
        self.EXACT_GEOMETRY_MODE = False
        self.SAFE_PEN_TRAVEL_UP = True
        self.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.0
        self.HANDWRITING_TEXT_ENABLED = False
        self.HANDWRITING_FONT_FAMILY = "Marck Script"
        self.HANDWRITING_CYRILLIC_FONT_FAMILY = "Marck Script"
        self.HANDWRITING_SINGLELINE_TTF_BACKEND = "autotrace3"
        self.HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED = True
        self.IMAGE_CONTOUR_MODE = "always"
        self.IMAGE_CONTOUR_ENABLED = True
        self.IMAGE_CONTOUR_WORD_ONLY = False
        self.USE_INKSCAPE_PDF_IMPORT = True
        self.configured_sheet: dict[str, object] = {}
        self.quality_calls: list[tuple[str, bool]] = []
        self.pipeline_calls: list[dict[str, object]] = []
        self.tool_mode = "pen"

    def configure_active_work_area(self, **kwargs) -> None:
        self.configured_sheet = dict(kwargs)

    def apply_quality_profile(self, quality: str, force_text_to_path: bool) -> None:
        self.quality_calls.append((quality, bool(force_text_to_path)))

    def quality_state(self) -> str:
        return "quality-state"

    def _resolve_handwriting_ttf_path(self, _name: str):
        return Path(self.tmp_root / "dummy.ttf")

    def ensure_local_tmp_root(self) -> Path:
        path = self.tmp_root / "_tmp_local"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def detect_com_port(self, _preferred):
        return "COM6"

    def run_pipeline_with_corner_calibration(
        self,
        input_path,
        log,
        *,
        com,
        baud,
        send_to_plotter,
        output_path,
        skip_calibration,
        skip_confirmation,
        corner_mark_size,
        feed_travel,
        feed_draw,
        auto_resume,
    ):
        self.pipeline_calls.append(
            {
                "input_path": Path(input_path),
                "com": com,
                "baud": baud,
                "send_to_plotter": bool(send_to_plotter),
                "output_path": Path(output_path),
                "skip_calibration": bool(skip_calibration),
                "skip_confirmation": bool(skip_confirmation),
                "corner_mark_size": float(corner_mark_size),
                "feed_travel": float(feed_travel),
                "feed_draw": float(feed_draw),
                "auto_resume": bool(auto_resume),
            }
        )
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("G21\nG90\nG0 X0 Y0\nG1 X1 Y1\n", encoding="utf-8")
        log("fake backend pipeline complete")
        return True, "Pipeline done"


class ProtocolRunPathTests(unittest.TestCase):
    def test_run_draw_svg_configures_flags_and_pipeline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_draw_") as td:
            root = Path(td)
            input_svg = root / "input.svg"
            input_svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            backend = _FakeBackend(root)
            bridge = BackendBridge(root)
            ctx = _FakeCtx()

            with (
                mock.patch.object(bridge, "_backend", return_value=backend),
                mock.patch.object(bridge, "_build_vector_preview_from_gcode", return_value=(True, "")),
            ):
                ok, msg = bridge.run_draw(
                    ctx=ctx,
                    input_path=input_svg,
                    com_port="COM6",
                    baud="115200",
                    sheet=SheetConfig(sheet_format="a4"),
                    tool_mode="pen",
                    calibrate_before_draw=False,
                    render_mode="drawing",
                    quality_profile="high",
                    force_text_to_path=True,
                    handwriting_enabled=False,
                    handwriting_font="Marck Script",
                    handwriting_formula_font="Times New Roman",
                    image_contours_mode="invalid-mode",
                    source_page_index=1,
                    source_all_pages=False,
                    exact_geometry_mode=False,
                    safe_travel_lift=False,
                    strict_one_to_one=True,
                    log=ctx.emit_log,
                )

            self.assertTrue(ok, msg)
            self.assertIn("Preview ready:", msg)
            self.assertEqual(getattr(backend, "TOOL_MODE", None), "pen")
            self.assertTrue(backend.pipeline_calls)
            call = backend.pipeline_calls[-1]
            self.assertTrue(call["skip_calibration"])
            self.assertTrue(call["send_to_plotter"])
            self.assertEqual(str(call["com"]), "COM6")
            self.assertEqual(backend.quality_calls[-1], ("high", True))
            self.assertTrue(backend.EXACT_GEOMETRY_MODE)
            self.assertFalse(backend.SAFE_PEN_TRAVEL_UP)
            self.assertAlmostEqual(float(backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW), 1.0, places=6)
            self.assertEqual(backend.IMAGE_CONTOUR_MODE, "always")
            self.assertTrue(backend.IMAGE_CONTOUR_ENABLED)
            self.assertFalse(backend.IMAGE_CONTOUR_WORD_ONLY)
            self.assertFalse(backend.USE_INKSCAPE_PDF_IMPORT)

    def test_run_draw_returns_warning_when_preview_build_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_draw_warn_") as td:
            root = Path(td)
            input_svg = root / "input.svg"
            input_svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            backend = _FakeBackend(root)
            bridge = BackendBridge(root)
            ctx = _FakeCtx()

            with (
                mock.patch.object(bridge, "_backend", return_value=backend),
                mock.patch.object(bridge, "_build_vector_preview_from_gcode", return_value=(False, "preview-failed")),
            ):
                ok, msg = bridge.run_draw(
                    ctx=ctx,
                    input_path=input_svg,
                    com_port="COM6",
                    baud="115200",
                    sheet=SheetConfig(sheet_format="a4"),
                    tool_mode="pen",
                    calibrate_before_draw=True,
                    render_mode="drawing",
                    quality_profile="normal",
                    force_text_to_path=False,
                    handwriting_enabled=False,
                    handwriting_font="Marck Script",
                    handwriting_formula_font="Times New Roman",
                    image_contours_mode="always",
                    source_page_index=1,
                    source_all_pages=False,
                    exact_geometry_mode=True,
                    safe_travel_lift=True,
                    strict_one_to_one=False,
                    log=ctx.emit_log,
                )

            self.assertTrue(ok)
            self.assertIn("Preview generation warning: preview-failed", msg)
            self.assertTrue(backend.pipeline_calls)
            self.assertFalse(backend.pipeline_calls[-1]["skip_calibration"])

    def test_run_preview_returns_error_when_preview_build_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_prev_") as td:
            root = Path(td)
            input_svg = root / "input.svg"
            input_svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            backend = _FakeBackend(root)
            bridge = BackendBridge(root)
            ctx = _FakeCtx()

            with (
                mock.patch.object(bridge, "_backend", return_value=backend),
                mock.patch.object(bridge, "_build_vector_preview_from_gcode", return_value=(False, "preview-broken")),
            ):
                ok, msg = bridge.run_preview(
                    ctx=ctx,
                    input_path=input_svg,
                    sheet=SheetConfig(sheet_format="a4"),
                    tool_mode="pencil",
                    render_mode="handwriting",
                    quality_profile="fast",
                    force_text_to_path=True,
                    handwriting_enabled=True,
                    handwriting_font="Marck Script",
                    handwriting_formula_font="Times New Roman",
                    image_contours_mode="word_only",
                    source_page_index=1,
                    source_all_pages=False,
                    exact_geometry_mode=True,
                    safe_travel_lift=True,
                    strict_one_to_one=False,
                    log=ctx.emit_log,
                )

            self.assertFalse(ok)
            self.assertEqual(msg, "preview-broken")
            self.assertTrue(backend.pipeline_calls)
            call = backend.pipeline_calls[-1]
            self.assertFalse(call["send_to_plotter"])
            self.assertTrue(call["skip_calibration"])
            self.assertEqual(str(call["com"]), "COM6")
            self.assertEqual(getattr(backend, "TOOL_MODE", None), "pencil")
            self.assertTrue(backend.HANDWRITING_TEXT_ENABLED)
            self.assertEqual(backend.IMAGE_CONTOUR_MODE, "word_only")
            self.assertTrue(backend.IMAGE_CONTOUR_ENABLED)
            self.assertTrue(backend.IMAGE_CONTOUR_WORD_ONLY)
            self.assertFalse(backend.USE_INKSCAPE_PDF_IMPORT)

    def test_run_draw_method3_all_pages_calls_sheet_swap_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_method3_pages_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            input_pdf.write_bytes(b"%PDF-1.4\n")
            backend = _FakeBackend(root)
            bridge = BackendBridge(root)
            ctx = _FakeCtx()

            sent_pages: list[Path] = []

            def _send_to_grbl(path, _com, _baud, _log, *, sleep_after, auto_resume):
                sent_pages.append(Path(path))
                self.assertTrue(sleep_after)
                self.assertFalse(auto_resume)
                return 1.0

            backend.send_to_grbl = _send_to_grbl  # type: ignore[attr-defined]

            def _prepare_method3_page(*_args, **kwargs):
                out_svg = Path(kwargs["output_svg"])
                out_pdf = Path(kwargs["output_pdf"])
                out_nc = Path(kwargs["output_nc"])
                out_svg.write_text("<svg/>", encoding="utf-8")
                out_pdf.write_bytes(b"%PDF-1.4\n")
                out_nc.write_text("G21\nG90\nG1 X1 Y1\n", encoding="utf-8")
                return True, "ok"

            pauses: list[tuple[int, int]] = []

            with (
                mock.patch.object(bridge, "_backend", return_value=backend),
                mock.patch.object(bridge, "_resolve_method3_source_pdf", return_value=(True, input_pdf, "")),
                mock.patch.object(bridge, "_probe_pdf_page_count", return_value=3),
                mock.patch.object(bridge, "_prepare_method3_page", side_effect=_prepare_method3_page),
            ):
                ok, msg = bridge.run_draw(
                    ctx=ctx,
                    input_path=input_pdf,
                    com_port="COM6",
                    baud="115200",
                    sheet=SheetConfig(sheet_format="a4"),
                    tool_mode="pen",
                    calibrate_before_draw=False,
                    render_mode="handwriting",
                    quality_profile="normal",
                    force_text_to_path=False,
                    handwriting_enabled=True,
                    handwriting_font="Marck Script",
                    handwriting_formula_font="Times New Roman",
                    image_contours_mode="always",
                    source_page_index=1,
                    source_all_pages=True,
                    exact_geometry_mode=False,
                    safe_travel_lift=True,
                    strict_one_to_one=False,
                    log=ctx.emit_log,
                    sheet_swap_confirm=lambda completed, total: pauses.append((completed, total)) or True,
                )

            self.assertTrue(ok, msg)
            self.assertEqual(len(sent_pages), 3)
            self.assertEqual(pauses, [(1, 3), (2, 3)])

    def test_run_draw_method3_all_pages_cancels_on_sheet_swap_decline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_method3_cancel_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            input_pdf.write_bytes(b"%PDF-1.4\n")
            backend = _FakeBackend(root)
            bridge = BackendBridge(root)
            ctx = _FakeCtx()

            sent_pages: list[Path] = []

            def _send_to_grbl(path, _com, _baud, _log, *, sleep_after, auto_resume):
                sent_pages.append(Path(path))
                self.assertTrue(sleep_after)
                self.assertFalse(auto_resume)
                return 1.0

            backend.send_to_grbl = _send_to_grbl  # type: ignore[attr-defined]

            def _prepare_method3_page(*_args, **kwargs):
                out_svg = Path(kwargs["output_svg"])
                out_pdf = Path(kwargs["output_pdf"])
                out_nc = Path(kwargs["output_nc"])
                out_svg.write_text("<svg/>", encoding="utf-8")
                out_pdf.write_bytes(b"%PDF-1.4\n")
                out_nc.write_text("G21\nG90\nG1 X1 Y1\n", encoding="utf-8")
                return True, "ok"

            pauses: list[tuple[int, int]] = []

            with (
                mock.patch.object(bridge, "_backend", return_value=backend),
                mock.patch.object(bridge, "_resolve_method3_source_pdf", return_value=(True, input_pdf, "")),
                mock.patch.object(bridge, "_probe_pdf_page_count", return_value=4),
                mock.patch.object(bridge, "_prepare_method3_page", side_effect=_prepare_method3_page),
            ):
                ok, msg = bridge.run_draw(
                    ctx=ctx,
                    input_path=input_pdf,
                    com_port="COM6",
                    baud="115200",
                    sheet=SheetConfig(sheet_format="a4"),
                    tool_mode="pen",
                    calibrate_before_draw=False,
                    render_mode="handwriting",
                    quality_profile="normal",
                    force_text_to_path=False,
                    handwriting_enabled=True,
                    handwriting_font="Marck Script",
                    handwriting_formula_font="Times New Roman",
                    image_contours_mode="always",
                    source_page_index=1,
                    source_all_pages=True,
                    exact_geometry_mode=False,
                    safe_travel_lift=True,
                    strict_one_to_one=False,
                    log=ctx.emit_log,
                    sheet_swap_confirm=lambda completed, total: pauses.append((completed, total)) and False,
                )

            self.assertFalse(ok)
            self.assertIn("Canceled during sheet replacement", msg)
            self.assertEqual(pauses, [(1, 4)])
            self.assertEqual(len(sent_pages), 1)

    def test_run_draw_method3_all_pages_requires_sheet_swap_callback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_method3_need_pause_cb_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            input_pdf.write_bytes(b"%PDF-1.4\n")
            backend = _FakeBackend(root)
            bridge = BackendBridge(root)
            ctx = _FakeCtx()

            with (
                mock.patch.object(bridge, "_backend", return_value=backend),
                mock.patch.object(bridge, "_resolve_method3_source_pdf", return_value=(True, input_pdf, "")),
                mock.patch.object(bridge, "_probe_pdf_page_count", return_value=3),
            ):
                ok, msg = bridge.run_draw(
                    ctx=ctx,
                    input_path=input_pdf,
                    com_port="COM6",
                    baud="115200",
                    sheet=SheetConfig(sheet_format="a4"),
                    tool_mode="pen",
                    calibrate_before_draw=False,
                    render_mode="handwriting",
                    quality_profile="normal",
                    force_text_to_path=False,
                    handwriting_enabled=True,
                    handwriting_font="Marck Script",
                    handwriting_formula_font="Times New Roman",
                    image_contours_mode="always",
                    source_page_index=1,
                    source_all_pages=True,
                    exact_geometry_mode=False,
                    safe_travel_lift=True,
                    strict_one_to_one=False,
                    log=ctx.emit_log,
                    sheet_swap_confirm=None,
                )

            self.assertFalse(ok)
            self.assertIn("Sheet swap confirmation callback is required", msg)


if __name__ == "__main__":
    unittest.main()
