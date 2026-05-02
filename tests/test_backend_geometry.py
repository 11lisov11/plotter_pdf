from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path
import base64
import io

from src import plotter_pdf_drawer as backend
from PIL import Image


class BackendGeometryTests(unittest.TestCase):
    @staticmethod
    def _rect(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]

    def test_compute_pass_shift_for_two_columns(self) -> None:
        old = (backend.PASS_COLS, backend.PASS_ROWS, backend.PASS_COL, backend.PASS_ROW)
        try:
            backend.PASS_COLS = 2
            backend.PASS_ROWS = 1
            backend.PASS_ROW = 1

            backend.PASS_COL = 1
            shift_x_1, shift_y_1, info_1 = backend.compute_pass_shift(
                source_w_mm=400.0,
                source_h_mm=280.0,
                window_w_mm=200.0,
                window_h_mm=280.0,
            )
            backend.PASS_COL = 2
            shift_x_2, shift_y_2, info_2 = backend.compute_pass_shift(
                source_w_mm=400.0,
                source_h_mm=280.0,
                window_w_mm=200.0,
                window_h_mm=280.0,
            )

            self.assertEqual(info_1["col"], 1)
            self.assertEqual(info_2["col"], 2)
            self.assertAlmostEqual(shift_y_1, 0.0, places=6)
            self.assertAlmostEqual(shift_y_2, 0.0, places=6)
            self.assertAlmostEqual(shift_x_1, -shift_x_2, places=6)
            self.assertGreater(shift_x_1, 0.0)
            self.assertLess(shift_x_2, 0.0)
        finally:
            backend.PASS_COLS, backend.PASS_ROWS, backend.PASS_COL, backend.PASS_ROW = old

    def test_transform_polylines_for_active_sheet_pass_rotates_a3_second_pass_180_and_raises_y_by_3mm(self) -> None:
        old_cfg = dict(backend.ACTIVE_SHEET_CONFIG)
        old_pass = (backend.PASS_COLS, backend.PASS_ROWS, backend.PASS_COL, backend.PASS_ROW)
        try:
            backend.ACTIVE_SHEET_CONFIG = {
                "sheet_format": "a3",
                "sheet_width_mm": 420.0,
                "sheet_height_mm": 297.0,
                "anchor": "lower_left",
                "offset_x_mm": 0.0,
                "offset_y_mm": 0.0,
            }
            backend.PASS_COLS = 2
            backend.PASS_ROWS = 1
            backend.PASS_COL = 2
            backend.PASS_ROW = 1
            with mock.patch.object(backend, "work_area_bounds", return_value=(0.0, 180.0, -280.0, 0.0)):
                out = backend.transform_polylines_for_active_sheet_pass(
                    [[(0.0, -280.0), (180.0, 0.0)]],
                    logger=None,
                )
            self.assertEqual(out, [[(180.0, 3.0), (0.0, -277.0)]])
        finally:
            backend.ACTIVE_SHEET_CONFIG = old_cfg
            backend.PASS_COLS, backend.PASS_ROWS, backend.PASS_COL, backend.PASS_ROW = old_pass

    def test_plan_tiled_passes_reports_two_pass_scale(self) -> None:
        plan = backend.plan_tiled_passes_for_sheet(420.0, 297.0)
        self.assertIn("max_two_pass_scale", plan)
        self.assertGreater(float(plan["max_two_pass_scale"]), 0.0)
        self.assertIn("nx", plan)
        self.assertIn("ny", plan)

    def test_apply_handwriting_font_updates_text_nodes(self) -> None:
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm">
  <text x="1" y="5" style="font-size:4px;fill:#000000">abc</text>
</svg>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.svg"
            path.write_text(svg, encoding="utf-8")
            changed = backend.apply_handwriting_font(path, "Segoe Script", logger=lambda *_: None)
            self.assertEqual(changed, 1)
            txt = path.read_text(encoding="utf-8")
            self.assertIn("Segoe Script", txt)

    def test_normalize_image_contour_mode_defaults_to_legacy(self) -> None:
        old_word_only = backend.IMAGE_CONTOUR_WORD_ONLY
        try:
            backend.IMAGE_CONTOUR_WORD_ONLY = True
            self.assertEqual(backend.normalize_image_contour_mode("invalid"), "word_only")
            backend.IMAGE_CONTOUR_WORD_ONLY = False
            self.assertEqual(backend.normalize_image_contour_mode("invalid"), "always")
        finally:
            backend.IMAGE_CONTOUR_WORD_ONLY = old_word_only

    def test_image_contours_enabled_for_input_mode_matrix(self) -> None:
        old_enabled = backend.IMAGE_CONTOUR_ENABLED
        old_mode = backend.IMAGE_CONTOUR_MODE
        try:
            backend.IMAGE_CONTOUR_ENABLED = True

            backend.IMAGE_CONTOUR_MODE = "off"
            self.assertFalse(backend.image_contours_enabled_for_input(False))
            self.assertFalse(backend.image_contours_enabled_for_input(True))

            backend.IMAGE_CONTOUR_MODE = "always"
            self.assertTrue(backend.image_contours_enabled_for_input(False))
            self.assertTrue(backend.image_contours_enabled_for_input(True))

            backend.IMAGE_CONTOUR_MODE = "word_only"
            self.assertFalse(backend.image_contours_enabled_for_input(False))
            self.assertTrue(backend.image_contours_enabled_for_input(True))
        finally:
            backend.IMAGE_CONTOUR_ENABLED = old_enabled
            backend.IMAGE_CONTOUR_MODE = old_mode

    def test_image_hatch_enabled_for_input_mode_matrix(self) -> None:
        old_enabled = backend.IMAGE_TONE_HATCH_ENABLED
        old_word_only = backend.IMAGE_TONE_HATCH_WORD_ONLY
        old_mode = backend.IMAGE_CONTOUR_MODE
        old_handwriting = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.IMAGE_TONE_HATCH_ENABLED = True
            backend.IMAGE_TONE_HATCH_WORD_ONLY = True
            backend.HANDWRITING_TEXT_ENABLED = False

            backend.IMAGE_CONTOUR_MODE = "off"
            self.assertFalse(backend.image_hatch_enabled_for_input(False))
            self.assertFalse(backend.image_hatch_enabled_for_input(True))

            backend.IMAGE_CONTOUR_MODE = "always"
            self.assertFalse(backend.image_hatch_enabled_for_input(False))
            self.assertTrue(backend.image_hatch_enabled_for_input(True))

            backend.IMAGE_CONTOUR_MODE = "word_only"
            self.assertFalse(backend.image_hatch_enabled_for_input(False))
            self.assertTrue(backend.image_hatch_enabled_for_input(True))
        finally:
            backend.IMAGE_TONE_HATCH_ENABLED = old_enabled
            backend.IMAGE_TONE_HATCH_WORD_ONLY = old_word_only
            backend.IMAGE_CONTOUR_MODE = old_mode
            backend.HANDWRITING_TEXT_ENABLED = old_handwriting

    def test_analyze_embedded_image_profile_detects_formula_like_raster(self) -> None:
        if backend.np is None:
            self.skipTest("numpy unavailable")
        img = backend.np.full((48, 420, 3), 255, dtype=backend.np.uint8)
        img[10:12, 20:380] = 0
        img[14:30, 60:64] = 0
        img[14:30, 180:184] = 0
        img[14:30, 300:304] = 0
        profile = backend._analyze_embedded_image_profile(img)
        self.assertEqual(profile.get("kind"), "formula")
        self.assertTrue(bool(profile.get("line_art")))
        self.assertTrue(bool(profile.get("formula_like")))

    def test_analyze_embedded_image_profile_detects_small_line_art_raster(self) -> None:
        if backend.np is None:
            self.skipTest("numpy unavailable")
        img = backend.np.full((180, 300, 3), 255, dtype=backend.np.uint8)
        img[20:160, 150:154] = 0
        img[150:154, 40:260] = 0
        profile = backend._analyze_embedded_image_profile(img)
        self.assertEqual(profile.get("kind"), "lineart")
        self.assertTrue(bool(profile.get("line_art")))
        self.assertTrue(bool(profile.get("small_line_art")))

    def test_extract_image_contour_items_handles_leading_decimal_matrix_transform(self) -> None:
        if backend.cv2 is None or backend.np is None:
            self.skipTest("opencv/numpy unavailable")

        image = Image.new("RGB", (20, 10), "white")
        for x in range(2, 18):
            image.putpixel((x, 5), (0, 0, 0))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="100mm" height="50mm" viewBox="0 0 100 50">
  <g transform="matrix(.5,0,0,.5,10,5)">
    <image width="20" height="10" xlink:href="data:image/png;base64,{png_b64}"/>
  </g>
</svg>
"""
        old_enabled = backend.IMAGE_CONTOUR_ENABLED
        old_mode = backend.IMAGE_CONTOUR_MODE
        old_handwriting = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.IMAGE_CONTOUR_ENABLED = True
            backend.IMAGE_CONTOUR_MODE = "always"
            backend.HANDWRITING_TEXT_ENABLED = True
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "sample.svg"
                path.write_text(svg, encoding="utf-8")
                items = backend.extract_image_contour_items(path, logger=lambda *_: None)
            self.assertTrue(items)
            bounds = backend.bounds_path_items(items)
            self.assertIsNotNone(bounds)
            min_x, max_x, min_y, max_y = bounds
            self.assertLess(max_x, 30.0)
            self.assertLess(max_y, 20.0)
            self.assertGreaterEqual(min_x, 9.0)
            self.assertGreaterEqual(min_y, 4.0)
        finally:
            backend.IMAGE_CONTOUR_ENABLED = old_enabled
            backend.IMAGE_CONTOUR_MODE = old_mode
            backend.HANDWRITING_TEXT_ENABLED = old_handwriting

    def test_extract_image_contour_items_uses_configured_edge_mode_for_formula_like_raster(self) -> None:
        image = Image.new("RGB", (4, 4), "white")
        image.putpixel((1, 1), (0, 0, 0))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="10mm" height="10mm" viewBox="0 0 10 10">
  <image width="4" height="4" xlink:href="data:image/png;base64,{png_b64}"/>
</svg>
"""
        old_enabled = backend.IMAGE_CONTOUR_ENABLED
        old_mode = backend.IMAGE_CONTOUR_MODE
        old_handwriting = backend.HANDWRITING_TEXT_ENABLED
        old_formula_mode = backend.IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE
        try:
            backend.IMAGE_CONTOUR_ENABLED = True
            backend.IMAGE_CONTOUR_MODE = "always"
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE = "edge"
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "sample.svg"
                path.write_text(svg, encoding="utf-8")
                with (
                    mock.patch.object(
                        backend,
                        "_analyze_embedded_image_profile",
                        return_value={"kind": "formula", "line_art": True, "formula_like": True},
                    ),
                    mock.patch.object(backend, "_extract_image_centerline_paths_px", return_value=[]),
                    mock.patch.object(backend, "_extract_image_centerline_paths_px_autotrace", return_value=[]),
                    mock.patch.object(
                        backend,
                        "_extract_image_edge_contours_px",
                        return_value=[[(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)]],
                    ) as edge_mock,
                ):
                    items = backend.extract_image_contour_items(path, logger=lambda *_: None)
            self.assertTrue(edge_mock.called)
            self.assertTrue(items)
            self.assertTrue(items[0].closed)
        finally:
            backend.IMAGE_CONTOUR_ENABLED = old_enabled
            backend.IMAGE_CONTOUR_MODE = old_mode
            backend.HANDWRITING_TEXT_ENABLED = old_handwriting
            backend.IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE = old_formula_mode

    def test_extract_image_contour_items_prefers_formula_ocr_route_when_available(self) -> None:
        image = Image.new("RGB", (40, 10), "black")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="10mm" height="4mm" viewBox="0 0 10 4">
  <image width="40" height="10" xlink:href="data:image/png;base64,{png_b64}"/>
</svg>
"""
        old_enabled = backend.IMAGE_CONTOUR_ENABLED
        old_mode = backend.IMAGE_CONTOUR_MODE
        old_handwriting = backend.HANDWRITING_TEXT_ENABLED
        old_formula_ocr = backend.IMAGE_CONTOUR_FORMULA_OCR_ENABLED
        try:
            backend.IMAGE_CONTOUR_ENABLED = True
            backend.IMAGE_CONTOUR_MODE = "always"
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.IMAGE_CONTOUR_FORMULA_OCR_ENABLED = True
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "sample.svg"
                path.write_text(svg, encoding="utf-8")
                with (
                    mock.patch.object(
                        backend,
                        "_analyze_embedded_image_profile",
                        return_value={"kind": "formula", "line_art": True, "formula_like": True},
                    ),
                    mock.patch.object(
                        backend.formula_image_ocr_mod,
                        "rapidocr_available",
                        return_value=True,
                    ),
                    mock.patch.object(
                        backend.formula_image_ocr_mod,
                        "ocr_formula_image",
                        return_value=backend.formula_image_ocr_mod.FormulaOCRResult(
                            lines=(
                                backend.formula_image_ocr_mod.FormulaOCRLine(
                                    text="P=Re(S)",
                                    confidence=0.93,
                                    bbox_px=(0.0, 0.0, 40.0, 10.0),
                                ),
                            ),
                            confidence=0.93,
                            variant="orig",
                            engine="rapidocr",
                        ),
                    ),
                    mock.patch.object(
                        backend,
                        "_render_singleline_text_polylines_ttf",
                        return_value=[[(0.0, 0.0), (5.0, 0.0)]],
                    ) as render_mock,
                    mock.patch.object(backend, "_extract_image_centerline_paths_px_autotrace", return_value=[]) as auto_mock,
                    mock.patch.object(backend, "_extract_image_centerline_paths_px", return_value=[]) as center_mock,
                ):
                    items = backend.extract_image_contour_items(path, logger=lambda *_: None)
            self.assertTrue(render_mock.called)
            self.assertFalse(auto_mock.called)
            self.assertFalse(center_mock.called)
            self.assertTrue(items)
            self.assertFalse(items[0].closed)
        finally:
            backend.IMAGE_CONTOUR_ENABLED = old_enabled
            backend.IMAGE_CONTOUR_MODE = old_mode
            backend.HANDWRITING_TEXT_ENABLED = old_handwriting
            backend.IMAGE_CONTOUR_FORMULA_OCR_ENABLED = old_formula_ocr

    def test_extract_image_contour_items_uses_threshold_floor_for_light_line_art(self) -> None:
        image = Image.new("RGB", (20, 20), "white")
        image.putpixel((10, 10), (190, 190, 190))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="10mm" height="10mm" viewBox="0 0 10 10">
  <image width="20" height="20" xlink:href="data:image/png;base64,{png_b64}"/>
</svg>
"""
        old_enabled = backend.IMAGE_CONTOUR_ENABLED
        old_mode = backend.IMAGE_CONTOUR_MODE
        old_handwriting = backend.HANDWRITING_TEXT_ENABLED
        old_formula_mode = backend.IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE
        try:
            backend.IMAGE_CONTOUR_ENABLED = True
            backend.IMAGE_CONTOUR_MODE = "always"
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE = "edge"
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "sample.svg"
                path.write_text(svg, encoding="utf-8")
                with (
                    mock.patch.object(
                        backend,
                        "_analyze_embedded_image_profile",
                        return_value={
                            "kind": "lineart",
                            "line_art": True,
                            "formula_like": False,
                            "small_line_art": False,
                            "dark_ratio": 0.02,
                        },
                    ),
                    mock.patch.object(
                        backend,
                        "_extract_image_centerline_paths_px_autotrace",
                        return_value=[[(0.0, 0.0), (5.0, 0.0)]],
                    ) as center_mock,
                ):
                    backend.extract_image_contour_items(path, logger=lambda *_: None)
            self.assertTrue(center_mock.called)
            self.assertEqual(
                center_mock.call_args.kwargs.get("threshold_floor"),
                int(backend.IMAGE_CONTOUR_LINEART_THRESHOLD_MIN),
            )
        finally:
            backend.IMAGE_CONTOUR_ENABLED = old_enabled
            backend.IMAGE_CONTOUR_MODE = old_mode
            backend.HANDWRITING_TEXT_ENABLED = old_handwriting
            backend.IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE = old_formula_mode

    def test_extract_image_contour_items_upscales_small_line_art_before_tracing(self) -> None:
        image = Image.new("RGB", (20, 12), "white")
        image.putpixel((10, 6), (0, 0, 0))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="10mm" height="10mm" viewBox="0 0 10 10">
  <image width="20" height="12" xlink:href="data:image/png;base64,{png_b64}"/>
</svg>
"""
        old_enabled = backend.IMAGE_CONTOUR_ENABLED
        old_mode = backend.IMAGE_CONTOUR_MODE
        old_handwriting = backend.HANDWRITING_TEXT_ENABLED
        old_autotrace = backend.IMAGE_CONTOUR_LINEART_AUTOTRACE
        try:
            backend.IMAGE_CONTOUR_ENABLED = True
            backend.IMAGE_CONTOUR_MODE = "always"
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.IMAGE_CONTOUR_LINEART_AUTOTRACE = True
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "sample.svg"
                path.write_text(svg, encoding="utf-8")
                with (
                    mock.patch.object(
                        backend,
                        "_analyze_embedded_image_profile",
                        return_value={
                            "kind": "lineart",
                            "line_art": True,
                            "formula_like": False,
                            "small_line_art": True,
                            "dark_ratio": 0.02,
                        },
                    ),
                    mock.patch.object(
                        backend,
                        "_extract_image_centerline_paths_px_autotrace",
                        return_value=[[(0.0, 0.0), (5.0, 0.0)]],
                    ) as center_mock,
                ):
                    backend.extract_image_contour_items(path, logger=lambda *_: None)
            self.assertTrue(center_mock.called)
            traced_img = center_mock.call_args.args[0]
            self.assertGreater(int(traced_img.shape[1]), 20)
            self.assertGreater(int(traced_img.shape[0]), 12)
        finally:
            backend.IMAGE_CONTOUR_ENABLED = old_enabled
            backend.IMAGE_CONTOUR_MODE = old_mode
            backend.HANDWRITING_TEXT_ENABLED = old_handwriting
            backend.IMAGE_CONTOUR_LINEART_AUTOTRACE = old_autotrace

    def test_extract_image_hough_circles_px_detects_small_line_art_nodes(self) -> None:
        if backend.cv2 is None or backend.np is None:
            self.skipTest("opencv/numpy unavailable")
        img = backend.np.full((189, 309, 3), 255, dtype=backend.np.uint8)
        backend.cv2.circle(img, (21, 148), 9, (205, 205, 205), thickness=1)
        backend.cv2.circle(img, (141, 167), 9, (205, 205, 205), thickness=1)
        backend.cv2.circle(img, (143, 21), 9, (205, 205, 205), thickness=1)
        backend.cv2.circle(img, (287, 148), 9, (205, 205, 205), thickness=1)
        polys = backend._extract_image_hough_circles_px(img)
        self.assertGreaterEqual(len(polys), 4)
        self.assertTrue(all(len(poly) >= 10 for poly in polys[:4]))

    def test_extract_image_contour_items_adds_hough_circles_for_small_line_art(self) -> None:
        if backend.cv2 is None or backend.np is None:
            self.skipTest("opencv/numpy unavailable")
        img = backend.np.full((189, 309, 3), 255, dtype=backend.np.uint8)
        for center in ((21, 148), (141, 167), (143, 21), (287, 148)):
            backend.cv2.circle(img, center, 9, (205, 205, 205), thickness=1)
        ok, encoded = backend.cv2.imencode(".png", img)
        self.assertTrue(bool(ok))
        png_b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="30mm" height="20mm" viewBox="0 0 30 20">
  <image width="30" height="20" xlink:href="data:image/png;base64,{png_b64}"/>
</svg>
"""
        old_enabled = backend.IMAGE_CONTOUR_ENABLED
        old_mode = backend.IMAGE_CONTOUR_MODE
        old_handwriting = backend.HANDWRITING_TEXT_ENABLED
        old_autotrace = backend.IMAGE_CONTOUR_LINEART_AUTOTRACE
        try:
            backend.IMAGE_CONTOUR_ENABLED = True
            backend.IMAGE_CONTOUR_MODE = "always"
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.IMAGE_CONTOUR_LINEART_AUTOTRACE = False
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "sample.svg"
                path.write_text(svg, encoding="utf-8")
                with (
                    mock.patch.object(
                        backend,
                        "_analyze_embedded_image_profile",
                        return_value={
                            "kind": "lineart",
                            "line_art": True,
                            "formula_like": False,
                            "small_line_art": True,
                            "dark_ratio": 0.02,
                        },
                    ),
                    mock.patch.object(backend, "_extract_image_centerline_paths_px_autotrace", return_value=[]),
                    mock.patch.object(backend, "_extract_image_centerline_paths_px", return_value=[]),
                    mock.patch.object(backend, "_extract_image_edge_contours_px", return_value=[]),
                ):
                    items = backend.extract_image_contour_items(path, logger=lambda *_: None)
            closed = [it for it in items if bool(getattr(it, "closed", False))]
            self.assertGreaterEqual(len(closed), 4)
            self.assertTrue(all(len(it.points) >= 10 for it in closed[:4]))
        finally:
            backend.IMAGE_CONTOUR_ENABLED = old_enabled
            backend.IMAGE_CONTOUR_MODE = old_mode
            backend.HANDWRITING_TEXT_ENABLED = old_handwriting
            backend.IMAGE_CONTOUR_LINEART_AUTOTRACE = old_autotrace

    def test_cluster_small_fill_items_for_single_stroke_groups_nested_contours(self) -> None:
        items = [
            backend.PathItem(
                points=self._rect(0.0, 0.0, 4.0, 6.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=10,
            ),
            backend.PathItem(
                points=self._rect(1.0, 2.0, 3.0, 4.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=11,
            ),
            backend.PathItem(
                points=self._rect(20.0, 0.0, 24.0, 6.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=12,
            ),
        ]
        clusters = backend.cluster_small_fill_items_for_single_stroke(items)
        norm = [tuple(sorted(c)) for c in clusters]
        self.assertIn((0, 1), norm)
        self.assertNotIn((0, 1, 2), norm)

    def test_to_drawing_polylines_uses_cluster_centerline_and_skips_consumed(self) -> None:
        items = [
            backend.PathItem(
                points=self._rect(0.0, 0.0, 4.0, 6.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=1,
            ),
            backend.PathItem(
                points=self._rect(1.0, 2.0, 3.0, 4.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=2,
            ),
            backend.PathItem(
                points=[(10.0, 10.0), (20.0, 10.0)],
                closed=False,
                is_fill=False,
                is_stroke=True,
                source_id=3,
            ),
        ]
        synthetic_centerline = [[(0.5, 0.5), (3.5, 5.5)]]
        with (
            mock.patch.object(backend, "cluster_small_fill_items_for_single_stroke", return_value=[[0, 1]]),
            mock.patch.object(backend, "centerline_fill_group", return_value=synthetic_centerline),
            mock.patch.object(backend, "centerline_is_usable", return_value=True),
        ):
            out = backend.to_drawing_polylines(items)

        self.assertEqual(len(out), 2)
        self.assertIn(synthetic_centerline[0], out)
        self.assertIn(items[2].points, out)
        self.assertNotIn(items[0].points, out)
        self.assertNotIn(items[1].points, out)

    def test_apply_word_handwriting_font_restores_math_runs(self) -> None:
        class _Font:
            def __init__(self) -> None:
                self.Name = ""
                self.NameAscii = ""
                self.NameFarEast = ""
                self.NameOther = ""

        class _Range:
            def __init__(self) -> None:
                self.Font = _Font()

        class _OMathItem:
            def __init__(self) -> None:
                self.Range = _Range()

        class _OMaths:
            def __init__(self, count: int) -> None:
                self.Count = count
                self._items = [_OMathItem() for _ in range(count)]

            def Item(self, i: int) -> _OMathItem:
                return self._items[i - 1]

        class _Doc:
            def __init__(self) -> None:
                self.Content = _Range()
                self.OMaths = _OMaths(3)

        old_keep_math = backend.HANDWRITING_WORD_KEEP_MATH
        try:
            backend.HANDWRITING_WORD_KEEP_MATH = True
            doc = _Doc()
            ok, restored = backend.apply_word_handwriting_font(doc, "Segoe Script", logger=lambda *_: None)
            self.assertTrue(ok)
            self.assertEqual(restored, 3)
            self.assertEqual(doc.Content.Font.Name, "Segoe Script")
            for i in range(1, doc.OMaths.Count + 1):
                self.assertEqual(doc.OMaths.Item(i).Range.Font.Name, "Cambria Math")
        finally:
            backend.HANDWRITING_WORD_KEEP_MATH = old_keep_math

    def test_preflight_check_gcode_pass_and_fail_bounds(self) -> None:
        old_active = backend.ACTIVE_WORK_AREA_BOUNDS
        try:
            backend.ACTIVE_WORK_AREA_BOUNDS = (0.0, 100.0, -100.0, 0.0)
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                ok_path = td_path / "ok.nc"
                ok_path.write_text(
                    "\n".join(
                        [
                            "G21",
                            "G90",
                            "G0 X10 Y-10",
                            "G1 X20 Y-20 F800",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                ok, msg = backend.preflight_check_gcode(ok_path, logger=lambda *_: None)
                self.assertTrue(ok, msg)

                bad_path = td_path / "bad.nc"
                bad_path.write_text(
                    "\n".join(
                        [
                            "G21",
                            "G90",
                            "G0 X10 Y-10",
                            "G1 X20 Y10 F800",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                ok2, msg2 = backend.preflight_check_gcode(bad_path, logger=lambda *_: None)
                self.assertFalse(ok2)
                self.assertIn("exceeds active area", msg2)
        finally:
            backend.ACTIVE_WORK_AREA_BOUNDS = old_active

    def test_preflight_ignores_home_travel_with_pen_up(self) -> None:
        old_active = backend.ACTIVE_WORK_AREA_BOUNDS
        old_z_up = backend.Z_UP
        old_z_down = backend.Z_DOWN
        try:
            backend.ACTIVE_WORK_AREA_BOUNDS = (0.0, 100.0, -100.0, -10.0)
            backend.Z_UP = 0.0
            backend.Z_DOWN = 10.0
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                path = td_path / "home_travel.nc"
                path.write_text(
                    "\n".join(
                        [
                            "G21",
                            "G90",
                            "G0 Z0",
                            "G0 X10 Y-20",
                            "G0 Z10",
                            "G1 X40 Y-20 F800",
                            "G0 Z0",
                            "G0 X0 Y0",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                ok, msg = backend.preflight_check_gcode(path, logger=lambda *_: None)
                self.assertTrue(ok, msg)
        finally:
            backend.ACTIVE_WORK_AREA_BOUNDS = old_active
            backend.Z_UP = old_z_up
            backend.Z_DOWN = old_z_down

    def test_rewrite_duplicate_draw_segments_as_penup_travel(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dup.nc"
            path.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 Z0",
                        "G0 X0 Y0",
                        "G1 Z11.9",
                        "G1 X10 Y0 F12000",
                        "G1 X0 Y0",
                        "G1 X0 Y10",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            changed = backend.rewrite_duplicate_draw_segments_as_penup_travel(
                path,
                z_up=0.0,
                z_down=11.9,
                feed_travel=15000.0,
                z_feed=8000.0,
            )

            text = path.read_text(encoding="utf-8")
            self.assertEqual(changed, 1)
            self.assertIn("G0 X0.0000 Y0.0000 F15000.0", text)
            self.assertEqual(text.count("G1 X0 Y0"), 0)

    def test_extract_image_tone_hatch_segments_px_simple(self) -> None:
        if backend.cv2 is None or backend.np is None:
            self.skipTest("opencv/numpy unavailable")
        img = backend.np.full((32, 32), 255, dtype=backend.np.uint8)
        img[10:22, 8:24] = 40
        segs = backend._extract_image_tone_hatch_segments_px(
            img,
            step_px=3,
            min_seg_px=4,
            max_paths=200,
        )
        self.assertGreater(len(segs), 0)
        self.assertTrue(all(len(s) == 2 for s in segs))

    def test_humanize_pencil_polylines_changes_curvy_stroke_but_keeps_endpoints(self) -> None:
        old_enabled = backend.PENCIL_NATURAL_STROKES_ENABLED
        old_only_hw = backend.PENCIL_NATURAL_ONLY_HANDWRITING
        try:
            backend.PENCIL_NATURAL_STROKES_ENABLED = True
            backend.PENCIL_NATURAL_ONLY_HANDWRITING = False
            poly = [(0.0, 0.0), (2.0, 1.6), (4.0, -1.2), (6.0, 1.5), (8.0, 0.0)]
            out = backend.humanize_pencil_polylines([poly], logger=lambda *_: None, handwriting_enabled=False)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0][0], poly[0])
            self.assertEqual(out[0][-1], poly[-1])
            changed = any(backend.points_distance(a, b) > 1e-6 for a, b in zip(out[0], poly[: len(out[0])]))
            self.assertTrue(changed or len(out[0]) != len(poly))
        finally:
            backend.PENCIL_NATURAL_STROKES_ENABLED = old_enabled
            backend.PENCIL_NATURAL_ONLY_HANDWRITING = old_only_hw

    def test_humanize_pencil_polylines_skips_straight_line(self) -> None:
        old_enabled = backend.PENCIL_NATURAL_STROKES_ENABLED
        old_only_hw = backend.PENCIL_NATURAL_ONLY_HANDWRITING
        try:
            backend.PENCIL_NATURAL_STROKES_ENABLED = True
            backend.PENCIL_NATURAL_ONLY_HANDWRITING = False
            straight = [(0.0, 0.0), (10.0, 0.01), (20.0, 0.0), (30.0, 0.0)]
            out = backend.humanize_pencil_polylines([straight], logger=lambda *_: None, handwriting_enabled=False)
            self.assertEqual(out[0], straight)
        finally:
            backend.PENCIL_NATURAL_STROKES_ENABLED = old_enabled
            backend.PENCIL_NATURAL_ONLY_HANDWRITING = old_only_hw

    def test_merge_handwriting_word_strokes_merges_small_same_line_gaps(self) -> None:
        old_join_enable = backend.HANDWRITING_WORD_JOIN_ENABLE
        try:
            backend.HANDWRITING_WORD_JOIN_ENABLE = True
            polylines = [
                [(0.0, 0.0), (1.0, 0.0)],
                [(1.8, 0.1), (2.8, 0.1)],
                [(5.6, 0.0), (6.5, 0.0)],
            ]
            out = backend.merge_handwriting_word_strokes(
                polylines,
                logger=lambda *_: None,
                join_gap_mm=1.2,
                join_max_dy_mm=0.3,
            )
            self.assertEqual(len(out), 2)
            self.assertEqual(out[0][0], polylines[0][0])
            self.assertEqual(out[0][-1], polylines[1][-1])
            self.assertEqual(out[1], polylines[2])
        finally:
            backend.HANDWRITING_WORD_JOIN_ENABLE = old_join_enable

    def test_merge_handwriting_word_strokes_does_not_merge_backward_jump(self) -> None:
        old_join_enable = backend.HANDWRITING_WORD_JOIN_ENABLE
        try:
            backend.HANDWRITING_WORD_JOIN_ENABLE = True
            polylines = [
                [(2.0, 0.0), (3.0, 0.0)],
                [(2.2, 0.1), (1.6, 0.2)],
            ]
            out = backend.merge_handwriting_word_strokes(
                polylines,
                logger=lambda *_: None,
                join_gap_mm=1.0,
                join_max_dy_mm=0.4,
            )
            self.assertEqual(len(out), 2)
        finally:
            backend.HANDWRITING_WORD_JOIN_ENABLE = old_join_enable

    def test_apply_penlift_force_full_lift_uses_full_z_up_travel(self) -> None:
        old_tool_mode = backend.TOOL_MODE
        old_safe = backend.SAFE_PEN_TRAVEL_UP
        old_lift = backend.Z_TRAVEL_LIFT_MM
        try:
            backend.TOOL_MODE = "pen"
            backend.SAFE_PEN_TRAVEL_UP = False
            backend.Z_TRAVEL_LIFT_MM = 3.5
            with tempfile.TemporaryDirectory() as td:
                xy_path = Path(td) / "in.nc"
                pen_path = Path(td) / "out.nc"
                xy_path.write_text("G21\nG90\nG0 X0 Y0\n", encoding="utf-8")
                captured: dict[str, object] = {}

                def _fake_run(*_args, **kwargs):
                    captured.update(kwargs)

                with mock.patch.object(backend.gcode_penlift_mod, "run_penlift_postprocess", side_effect=_fake_run):
                    backend.apply_penlift(xy_path, pen_path, z_down=11.9, force_full_lift=True)

                self.assertAlmostEqual(float(captured["z_travel_lift_mm"]), 12.0, places=6)
        finally:
            backend.TOOL_MODE = old_tool_mode
            backend.SAFE_PEN_TRAVEL_UP = old_safe
            backend.Z_TRAVEL_LIFT_MM = old_lift

    def test_apply_penlift_force_full_lift_wins_in_pencil_mode(self) -> None:
        old_tool_mode = backend.TOOL_MODE
        old_safe = backend.SAFE_PEN_TRAVEL_UP
        old_lift = backend.Z_TRAVEL_LIFT_MM
        try:
            backend.TOOL_MODE = "pencil"
            backend.SAFE_PEN_TRAVEL_UP = False
            backend.Z_TRAVEL_LIFT_MM = 3.5
            with tempfile.TemporaryDirectory() as td:
                xy_path = Path(td) / "in.nc"
                pen_path = Path(td) / "out.nc"
                xy_path.write_text("G21\nG90\nG0 X0 Y0\n", encoding="utf-8")
                captured: dict[str, object] = {}

                def _fake_run(*_args, **kwargs):
                    captured.update(kwargs)

                with mock.patch.object(backend.gcode_penlift_mod, "run_penlift_postprocess", side_effect=_fake_run):
                    backend.apply_penlift(xy_path, pen_path, z_down=11.9, force_full_lift=True)

                self.assertAlmostEqual(float(captured["z_travel_lift_mm"]), 12.0, places=6)
        finally:
            backend.TOOL_MODE = old_tool_mode
            backend.SAFE_PEN_TRAVEL_UP = old_safe
            backend.Z_TRAVEL_LIFT_MM = old_lift

    def test_smooth_handwriting_polylines_preserves_endpoints(self) -> None:
        old_enabled = backend.HANDWRITING_SMOOTH_ENABLED
        try:
            backend.HANDWRITING_SMOOTH_ENABLED = True
            poly = [(0.0, 0.0), (0.6, 0.5), (1.2, -0.3), (1.8, 0.4), (2.4, 0.0)]
            out = backend.smooth_handwriting_polylines([poly], logger=lambda *_: None)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0][0], poly[0])
            self.assertEqual(out[0][-1], poly[-1])
            self.assertGreaterEqual(len(out[0]), 2)
        finally:
            backend.HANDWRITING_SMOOTH_ENABLED = old_enabled

    def test_prune_skeleton_spurs_removes_short_branch(self) -> None:
        if backend.np is None:
            self.skipTest("numpy unavailable")
        sk = backend.np.zeros((9, 9), dtype=backend.np.uint8)
        # main horizontal line
        sk[4, 1:8] = 255
        # short spur upwards
        sk[3, 4] = 255
        sk[2, 4] = 255
        pr = backend._prune_skeleton_spurs(sk, max_len_px=2)
        self.assertEqual(int(pr[2, 4]), 0)
        self.assertEqual(int(pr[4, 4]), 255)
        # The tip must be pruned; one junction-near pixel may remain.
        remaining_col = int((pr[:, 4] > 0).sum())
        self.assertLessEqual(remaining_col, 2)

    def test_likely_handwriting_text_group_heuristic(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 6.0, 8.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=1,
                ),
                backend.PathItem(
                    points=self._rect(1.8, 2.0, 4.2, 5.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=2,
                ),
            ]
            self.assertTrue(backend._likely_handwriting_text_group(group))
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_likely_handwriting_text_group_accepts_wide_low_bbox(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 80.0, 9.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=12,
                )
            ]
            self.assertTrue(backend._likely_handwriting_text_group(group))
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_likely_technical_text_group_heuristic(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = False
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 7.0, 4.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=21,
                ),
                backend.PathItem(
                    points=self._rect(7.3, 0.2, 12.0, 4.1),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=22,
                ),
            ]
            self.assertTrue(backend._likely_technical_text_group(group))
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_centerline_fill_group_ignores_open_polylines(self) -> None:
        if backend.np is None or backend.cv2 is None:
            self.skipTest("opencv/numpy unavailable")
        open_item = backend.PathItem(
            points=[(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 3.0)],
            closed=False,
            is_fill=True,
            is_stroke=False,
            source_id=7,
        )
        out = backend.centerline_fill_group([open_item])
        self.assertEqual(out, [])

    def test_to_drawing_polylines_uses_outline_centerline_in_handwriting_mode(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_outline = backend.HANDWRITING_OUTLINE_CENTERLINE_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.HANDWRITING_OUTLINE_CENTERLINE_ENABLED = True
            items = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 3.0, 6.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=10,
                )
            ]
            synthetic = [[(0.4, 0.2), (1.6, 5.8)]]
            with (
                mock.patch.object(backend, "centerline_fill_group", return_value=synthetic),
                mock.patch.object(backend, "refine_centerline_paths", return_value=synthetic),
            ):
                out = backend.to_drawing_polylines(items)
            self.assertEqual(out, synthetic)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.HANDWRITING_OUTLINE_CENTERLINE_ENABLED = old_outline

    def test_cluster_small_outline_items_for_single_stroke_groups_nested_contours(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_outline = backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED = True
            items = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 4.0, 6.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=10,
                ),
                backend.PathItem(
                    points=self._rect(1.0, 2.0, 3.0, 4.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=11,
                ),
                backend.PathItem(
                    points=self._rect(20.0, 0.0, 24.0, 6.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=12,
                ),
            ]
            clusters = backend.cluster_small_outline_items_for_single_stroke(items)
            norm = [tuple(sorted(c)) for c in clusters]
            self.assertIn((0, 1), norm)
            self.assertNotIn((0, 1, 2), norm)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED = old_outline

    def test_to_drawing_polylines_uses_outline_cluster_centerline(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_outline = backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED = True
            items = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 4.0, 6.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=1,
                ),
                backend.PathItem(
                    points=self._rect(1.0, 2.0, 3.0, 4.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=2,
                ),
            ]
            synthetic = [[(0.8, 0.5), (2.6, 5.6)]]
            with (
                mock.patch.object(backend, "cluster_small_outline_items_for_single_stroke", return_value=[[0, 1]]),
                mock.patch.object(backend, "centerline_fill_group", return_value=synthetic),
                mock.patch.object(backend, "refine_centerline_paths", return_value=synthetic),
                mock.patch.object(backend, "centerline_is_usable", return_value=True),
            ):
                out = backend.to_drawing_polylines(items)
            self.assertEqual(out, synthetic)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED = old_outline

    def test_centerline_quality_ok_for_handwriting_rejects_fragment_noise(self) -> None:
        tiny = [[(0.0, 0.0), (0.15, 0.0)] for _ in range(30)]
        self.assertFalse(backend._centerline_quality_ok_for_handwriting(tiny))

    def test_centerline_quality_ok_for_handwriting_accepts_reasonable_paths(self) -> None:
        good = [
            [(0.0, 0.0), (1.2, 0.1), (2.4, 0.0)],
            [(0.0, 1.0), (1.3, 1.2), (2.7, 1.0)],
            [(0.0, 2.0), (1.4, 1.8), (2.9, 2.0)],
        ]
        self.assertTrue(backend._centerline_quality_ok_for_handwriting(good))

    def test_tiny_handwriting_text_fallback_builds_single_stroke(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 0.7, 0.6),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=101,
                )
            ]
            out = backend.tiny_handwriting_text_fallback(group, [])
            self.assertEqual(len(out), 1)
            self.assertEqual(len(out[0]), 2)
            self.assertGreater(backend.polyline_length(out[0]), 0.0)
            self.assertGreater(backend.points_distance(out[0][0], out[0][-1]), 0.0)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_to_drawing_polylines_uses_tiny_handwriting_fallback_instead_of_contour(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            item = backend.PathItem(
                points=self._rect(0.0, 0.0, 0.7, 0.6),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=202,
            )
            with (
                mock.patch.object(backend, "centerline_fill_group", return_value=[]),
                mock.patch.object(backend, "refine_centerline_paths", return_value=[]),
                mock.patch.object(backend, "centerline_is_usable", return_value=False),
                mock.patch.object(backend, "_centerline_quality_ok_for_handwriting", return_value=False),
            ):
                out = backend.to_drawing_polylines([item])

            self.assertEqual(len(out), 1)
            self.assertEqual(len(out[0]), 2)
            self.assertNotEqual(out[0], item.points)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_to_drawing_polylines_uses_tiny_technical_fallback_instead_of_contour(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = False
            item = backend.PathItem(
                points=self._rect(0.0, 0.0, 0.7, 0.6),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=212,
            )
            with (
                mock.patch.object(backend, "centerline_fill_group", return_value=[]),
                mock.patch.object(backend, "refine_centerline_paths", return_value=[]),
                mock.patch.object(backend, "centerline_is_usable", return_value=False),
                mock.patch.object(backend, "centerline_is_usable_relaxed_small_cluster", return_value=False),
                mock.patch.object(backend, "_centerline_quality_ok_for_technical", return_value=False),
            ):
                out = backend.to_drawing_polylines([item])

            self.assertEqual(len(out), 1)
            self.assertEqual(len(out[0]), 2)
            self.assertNotEqual(out[0], item.points)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_merge_technical_text_strokes_merges_close_tiny_strokes(self) -> None:
        polys = [
            [(0.0, 0.0), (0.7, 0.0)],
            [(1.0, 0.1), (1.6, 0.1)],
            [(4.0, 0.0), (4.8, 0.0)],
        ]
        out = backend.merge_technical_text_strokes(
            polys,
            logger=lambda *_: None,
            join_gap_mm=0.45,
            join_max_dy_mm=0.25,
            join_max_backtrack_mm=0.10,
        )
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0], polys[0][0])
        self.assertEqual(out[0][-1], polys[1][-1])
        self.assertEqual(out[1], polys[2])

    def test_merge_technical_text_strokes_merges_close_tiny_strokes_out_of_order(self) -> None:
        polys = [
            [(0.0, 0.0), (0.7, 0.0)],
            [(4.0, 0.0), (4.8, 0.0)],
            [(1.0, 0.1), (1.6, 0.1)],
        ]
        out = backend.merge_technical_text_strokes(
            polys,
            logger=lambda *_: None,
            join_gap_mm=0.45,
            join_max_dy_mm=0.25,
            join_max_backtrack_mm=0.10,
        )
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0], polys[0][0])
        self.assertEqual(out[0][-1], polys[2][-1])
        self.assertEqual(out[1], polys[1])

    def test_merge_technical_text_strokes_does_not_merge_large_geometry(self) -> None:
        polys = [
            [(0.0, 0.0), (15.0, 0.0)],
            [(15.2, 0.0), (30.0, 0.0)],
        ]
        out = backend.merge_technical_text_strokes(
            polys,
            logger=lambda *_: None,
            join_gap_mm=0.50,
            join_max_dy_mm=0.25,
            join_max_backtrack_mm=0.10,
        )
        self.assertEqual(out, polys)

    def test_force_single_stroke_handwriting_group_uses_centerline_even_if_unusable(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_force = backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 4.0, 5.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=303,
                )
            ]
            center = [[(0.1, 0.1), (2.0, 2.0), (3.9, 4.9)]]
            out = backend.force_single_stroke_handwriting_group(group, center)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0][0], center[0][0])
            self.assertEqual(out[0][-1], center[0][-1])
            self.assertGreater(backend.polyline_length(out[0]), 0.0)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT = old_force

    def test_force_single_stroke_handwriting_group_generates_synthetic_when_empty(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_force = backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 7.0, 4.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=404,
                )
            ]
            out = backend.force_single_stroke_handwriting_group(group, [])
            self.assertEqual(len(out), 1)
            self.assertEqual(len(out[0]), 2)
            self.assertGreater(backend.polyline_length(out[0]), 0.0)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT = old_force

    def test_pick_hershey_font_name_for_text_mixed_scripts(self) -> None:
        self.assertEqual(backend._pick_hershey_font_name_for_text("Segoe Script", "Hello"), "cursive")
        self.assertEqual(backend._pick_hershey_font_name_for_text("Segoe Script", "Привет"), "cyrilc_1")
        self.assertEqual(backend._pick_hershey_font_name_for_text("Monospace", "Русский"), "cyrillic")

    def test_hershey_segments_to_polylines_joins_connected_segments(self) -> None:
        segments = [
            ((0.0, 0.0), (1.0, 0.0)),
            ((1.0, 0.0), (2.0, 0.0)),
            ((5.0, 0.0), (6.0, 0.0)),
        ]
        polylines = backend._hershey_segments_to_polylines(segments)
        self.assertEqual(len(polylines), 2)
        self.assertEqual(polylines[0], [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
        self.assertEqual(polylines[1], [(5.0, 0.0), (6.0, 0.0)])

    def test_trace_skeleton_paths_greedy_follows_simple_line(self) -> None:
        if backend.np is None:
            self.skipTest("numpy unavailable")
        skel = backend.np.zeros((7, 12), dtype=backend.np.uint8)
        skel[3, 2:10] = 255
        paths = backend._trace_skeleton_paths_greedy(skel)
        self.assertTrue(any(len(path) >= 8 for path in paths))

    def test_render_singleline_text_polylines_ttf_returns_strokes(self) -> None:
        font_path = backend._resolve_handwriting_ttf_path("Segoe Script")
        if font_path is None:
            self.skipTest("Segoe Script font not available")
        polylines = backend._render_singleline_text_polylines_ttf(
            "\u041f\u0440\u0438\u0432\u0435\u0442",
            ttf_path=font_path,
            font_size=14.0,
            baseline_x=0.0,
            baseline_y=0.0,
            logger=lambda *_: None,
        )
        self.assertGreater(len(polylines), 0)
        self.assertTrue(all(len(poly) >= 2 for poly in polylines))

    def test_run_autotrace_centerline_on_binary_works_without_pillow(self) -> None:
        if backend.np is None:
            self.skipTest("numpy unavailable")

        binary = backend.np.full((8, 16), 255, dtype=backend.np.uint8)
        binary[3:5, 2:14] = 0
        captured: dict[str, object] = {}

        def _fake_run_cmd(cmd, timeout_s=0.0):
            pbm_path = Path(cmd[-1])
            captured["pbm_exists"] = pbm_path.exists()
            captured["pbm_head"] = pbm_path.read_bytes()[:2]
            captured["timeout_s"] = float(timeout_s)
            return 0, '<svg xmlns="http://www.w3.org/2000/svg"><path d="M 0 0 L 5 0"/></svg>', ""

        with mock.patch.object(backend, "Image", None):
            with mock.patch.object(backend, "run_cmd", side_effect=_fake_run_cmd):
                polylines = backend._run_autotrace_centerline_on_binary(
                    binary,
                    autotrace_exe=Path("autotrace.exe"),
                    error_threshold=2.0,
                    filter_iterations=2,
                    curve_step_px=0.85,
                )

        self.assertTrue(bool(captured.get("pbm_exists")))
        self.assertEqual(captured.get("pbm_head"), b"P4")
        self.assertGreater(len(polylines), 0)
        self.assertGreaterEqual(len(polylines[0]), 2)

    def test_replace_svg_text_with_singleline_ttf_respects_inherited_font_size(self) -> None:
        font_path = backend._resolve_handwriting_ttf_path("Segoe Script")
        if font_path is None:
            self.skipTest("Segoe Script font not available")
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm">
  <g fill="#111111" font-family="Segoe Script" font-size="8">
    <text x="2" y="10">Привет</text>
  </g>
</svg>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.svg"
            path.write_text(svg, encoding="utf-8")
            changed = backend.replace_svg_text_with_singleline_ttf(path, "Segoe Script", logger=lambda *_: None)
            self.assertEqual(changed, 1)
            txt = path.read_text(encoding="utf-8")
            self.assertIn('stroke-width="0.1600"', txt)

    def test_replace_svg_text_with_svg_stroke_fonts_creates_paths(self) -> None:
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="40mm">
  <text x="20" y="20" style="font-size:10px;fill:#000000">Привет мир</text>
</svg>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stroke.svg"
            path.write_text(svg, encoding="utf-8")
            changed = backend.replace_svg_text_with_svg_stroke_fonts(path, "Segoe Script", logger=lambda *_: None)
            self.assertEqual(changed, 1)
            self.assertEqual(backend.svg_text_node_count(path), 0)
            txt = path.read_text(encoding="utf-8")
            self.assertIn('fill="none"', txt)
            root = backend.ET.parse(path).getroot()
            path_count = sum(1 for n in root.iter() if backend.tag_name(n.tag).lower() == "path")
            self.assertGreater(path_count, 0)
            items = backend.extract_polylines(path)
            bounds = backend.bounds_path_items(items)
            self.assertIsNotNone(bounds)
            assert bounds is not None
            self.assertGreater(bounds[1] - bounds[0], 5.0)
            self.assertGreater(bounds[3] - bounds[2], 2.0)

    def test_replace_svg_text_with_svg_stroke_fonts_respects_group_transform(self) -> None:
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="60mm">
  <g transform="translate(30,15)">
    <text x="10" y="20" style="font-size:12px;fill:#000000">AB</text>
  </g>
</svg>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stroke_transform.svg"
            path.write_text(svg, encoding="utf-8")
            changed = backend.replace_svg_text_with_svg_stroke_fonts(path, "Segoe Script", logger=lambda *_: None)
            self.assertEqual(changed, 1)
            items = backend.extract_polylines(path)
            bounds = backend.bounds_path_items(items)
            self.assertIsNotNone(bounds)
            assert bounds is not None
            self.assertGreater(bounds[0], 30.0)
            self.assertGreater(bounds[2], 10.0)

    def test_postprocess_singleline_text_polylines_keeps_geometry(self) -> None:
        src = [
            [(0.0, 0.0), (1.0, 0.05), (2.0, 0.0)],
            [(2.04, 0.01), (3.0, 0.05), (4.0, 0.02)],
        ]
        out = backend._postprocess_singleline_text_polylines(src, font_size=12.0, logger=None)
        self.assertGreaterEqual(len(out), 1)
        self.assertTrue(all(len(poly) >= 2 for poly in out))

    def test_simplify_polyline_allows_collinear_override(self) -> None:
        src = [(0.0, 0.0), (1.0, 0.03), (2.0, 0.0)]
        old_col = backend.POLYLINE_COLLINEAR_EPS
        try:
            backend.POLYLINE_COLLINEAR_EPS = 0.4
            default_simplified = backend.simplify_polyline(src)
            strict_simplified = backend.simplify_polyline(src, collinear_eps=0.001)
            self.assertEqual(len(default_simplified), 2)
            self.assertEqual(len(strict_simplified), 3)
        finally:
            backend.POLYLINE_COLLINEAR_EPS = old_col

    def test_split_text_tokens_keep_spaces_preserves_whitespace(self) -> None:
        tokens = backend._split_text_tokens_keep_spaces("Привет  мир\tEN")
        self.assertEqual(tokens, ["Привет", "  ", "мир", "\t", "EN"])


    def test_collinear_overlap_dedup_removes_retraced_partial_line(self) -> None:
        polylines = [
            [(0.0, 0.0), (10.0, 0.0)],
            [(2.0, 0.01), (8.0, 0.01)],
        ]

        out = backend.deduplicate_collinear_overlaps(polylines, logger=lambda *_: None)

        segment_count = sum(max(0, len(poly) - 1) for poly in out)
        self.assertEqual(segment_count, 1)
        self.assertEqual(out[0], [(0.0, 0.0), (10.0, 0.0)])

    def test_collinear_overlap_dedup_keeps_real_parallel_table_lines(self) -> None:
        polylines = [
            [(0.0, 0.0), (10.0, 0.0)],
            [(0.0, 0.20), (10.0, 0.20)],
        ]

        out = backend.deduplicate_collinear_overlaps(polylines, logger=lambda *_: None)

        self.assertEqual(out, polylines)

    def test_reorder_line_lr_goes_top_to_bottom_then_left_to_right(self) -> None:
        old_mode = backend.DRAW_ORDER_MODE
        old_reorder = backend.REORDER_ENABLED
        old_tol = backend.DRAW_ORDER_LINE_TOL_MM
        try:
            backend.DRAW_ORDER_MODE = "line_lr"
            backend.REORDER_ENABLED = True
            backend.DRAW_ORDER_LINE_TOL_MM = 3.0
            polylines = [
                [(40.0, -100.0), (50.0, -100.0)],  # bottom-right
                [(10.0, -100.0), (20.0, -100.0)],  # bottom-left
                [(35.0, -120.0), (45.0, -120.0)],  # top-right
                [(5.0, -120.0), (15.0, -120.0)],   # top-left
            ]
            out = backend.reorder_polylines(polylines, logger=lambda *_: None)
            self.assertEqual(len(out), 4)
            starts = [poly[0] for poly in out]
            self.assertEqual(starts[0], (5.0, -120.0))
            self.assertEqual(starts[1], (35.0, -120.0))
            self.assertEqual(starts[2], (10.0, -100.0))
            self.assertEqual(starts[3], (40.0, -100.0))
        finally:
            backend.DRAW_ORDER_MODE = old_mode
            backend.REORDER_ENABLED = old_reorder
            backend.DRAW_ORDER_LINE_TOL_MM = old_tol


if __name__ == "__main__":
    unittest.main()
