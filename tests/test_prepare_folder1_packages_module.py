from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "prepare_folder1_packages.py"
    spec = importlib.util.spec_from_file_location("prepare_folder1_packages", str(script_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrepareFolder1PackagesModuleTests(unittest.TestCase):
    @staticmethod
    def _find_poly_bbox(
        mod,
        polys: list[list[tuple[float, float]]],
        predicate,
    ) -> tuple[float, float, float, float]:
        for poly in polys:
            box = mod._poly_bbox_mm(poly)
            if predicate(box):
                return box
        raise AssertionError("Expected polyline bbox not found.")

    def test_condition_image_rect_filter_accepts_only_small_thumbnails(self) -> None:
        mod = _load_module()
        self.assertTrue(mod._is_small_condition_image_rect_mm(5.0, 5.0, 40.0, 34.0))
        self.assertTrue(mod._is_small_condition_image_rect_mm(200.0, 250.0, 233.5, 277.0))
        self.assertFalse(mod._is_small_condition_image_rect_mm(5.0, 5.0, 90.0, 34.0))
        self.assertFalse(mod._is_small_condition_image_rect_mm(5.0, 5.0, 40.0, 80.0))
        self.assertFalse(mod._is_small_condition_image_rect_mm(5.0, 5.0, 10.0, 10.0))

    def test_technical_point_box_detection_matches_square_loop(self) -> None:
        mod = _load_module()
        square = [
            (77.5948, 254.9038),
            (79.2036, 254.9038),
            (79.2036, 253.3372),
            (77.5948, 253.3372),
            (77.5948, 254.9038),
        ]
        self.assertTrue(mod._is_technical_point_box_poly(square))
        self.assertFalse(mod._is_technical_point_box_poly(square[:-1]))
        self.assertFalse(
            mod._is_technical_point_box_poly(
                [
                    (0.0, 0.0),
                    (5.0, 0.0),
                    (5.0, 1.0),
                    (0.0, 1.0),
                    (0.0, 0.0),
                ]
            )
        )

    def test_normalize_technical_point_boxes_replaces_square_loop_with_compact_dot(self) -> None:
        mod = _load_module()
        square = [
            (77.5948, 154.9038),
            (79.2036, 154.9038),
            (79.2036, 153.3372),
            (77.5948, 153.3372),
            (77.5948, 154.9038),
        ]
        line = [(76.7904, 150.9238), (78.3992, 154.1417)]
        out, meta = mod._normalize_technical_point_boxes(
            [line, square],
            page_w_mm=210.0,
            page_h_mm=297.0,
        )
        self.assertEqual(len(out), 2)
        self.assertEqual(meta["point_boxes_replaced"], 1.0)
        self.assertEqual(out[0], line)
        self.assertNotEqual(out[1], square)
        x0, y0, x1, y1 = mod._poly_bbox_mm(out[1])
        self.assertLess(x1 - x0, 1.0)
        self.assertLess(y1 - y0, 1.0)
        self.assertTrue(mod._poly_is_closed_mm(out[1]))

    def test_normalize_technical_point_boxes_replaces_supported_repeated_marker_loops(self) -> None:
        mod = _load_module()
        marker = [
            (237.6873, 248.0099),
            (237.8071, 247.6801),
            (237.9174, 247.4852),
            (238.0455, 247.3514),
            (238.1238, 247.3041),
            (238.2084, 247.2727),
            (238.3277, 247.2480),
            (238.7367, 247.1980),
            (238.8936, 247.1930),
            (239.0550, 247.2083),
            (239.1767, 247.2406),
            (239.2831, 247.2952),
            (239.3662, 247.3762),
            (239.4139, 247.4775),
            (239.4233, 247.6214),
            (239.3864, 247.8172),
            (239.1976, 248.3570),
            (238.9536, 249.2347),
            (238.8108, 249.6055),
            (238.6720, 249.8519),
            (238.5798, 249.9712),
            (238.4972, 250.0555),
            (238.4059, 250.1285),
            (238.3053, 250.1892),
            (238.1046, 250.2616),
            (237.8845, 250.2947),
            (237.6886, 250.3083),
            (237.5186, 250.3033),
            (237.3915, 250.2822),
            (237.2827, 250.2412),
            (237.2189, 250.1948),
            (237.1728, 250.1303),
            (237.1343, 250.0210),
            (237.1227, 249.9305),
            (237.1261, 249.8020),
            (237.1790, 249.5340),
            (237.6579, 248.1002),
            (237.6873, 248.0099),
        ]
        # Two supporting lines crossing near the marker center.
        support_a = [(236.0, 248.75), (240.2, 248.75)]
        support_b = [(238.27, 246.8), (238.27, 250.9)]
        polys = [support_a, support_b, marker, [(250.0, 250.0), (251.0, 251.0)], marker.copy(), marker.copy(), marker.copy()]
        out, meta = mod._normalize_technical_point_boxes(
            polys,
            page_w_mm=600.0,
            page_h_mm=600.0,
        )
        self.assertGreaterEqual(meta["point_boxes_replaced"], 1.0)
        self.assertNotEqual(out[2], marker)
        x0, y0, x1, y1 = mod._poly_bbox_mm(out[2])
        self.assertLess(x1 - x0, 1.0)
        self.assertLess(y1 - y0, 1.0)

    def test_fit_overlay_polys_within_source_bounds_shifts_bottom_right_thumbnail_inward(self) -> None:
        mod = _load_module()
        source = [[(0.0, 0.0), (360.0, 0.0), (360.0, 280.0), (0.0, 280.0), (0.0, 0.0)]]
        overlay = [[(196.68, 242.78), (245.87, 242.78), (245.87, 285.54), (196.68, 285.54), (196.68, 242.78)]]
        shifted, meta = mod._fit_overlay_polys_within_source_bounds(source, overlay)
        self.assertEqual(round(meta["shift_x_mm"], 4), 0.0)
        self.assertLess(meta["shift_y_mm"], 0.0)
        x0, y0, x1, y1 = mod._poly_bbox_mm(shifted[0])
        self.assertGreaterEqual(x0, 0.0)
        self.assertLessEqual(x1, 360.0)
        self.assertGreaterEqual(y0, 0.0)
        self.assertLessEqual(y1, 280.0)

    def test_clip_polyline_max_x_trims_spill_but_keeps_left_segment(self) -> None:
        mod = _load_module()
        poly = [(5.0, 10.0), (20.0, 10.0), (45.0, 12.0)]
        clipped = mod._clip_polyline_max_x_mm(poly, 18.0)
        self.assertEqual(len(clipped), 1)
        x0, _y0, x1, _y1 = mod._poly_bbox_mm(clipped[0])
        self.assertAlmostEqual(x0, 5.0, places=3)
        self.assertAlmostEqual(x1, 18.0, places=3)
        self.assertGreaterEqual(len(clipped[0]), 2)

    def test_detect_a4_header_thumb_divider_uses_rightmost_top_band_vertical(self) -> None:
        mod = _load_module()
        polys = [
            [(12.0, 18.0), (12.0, 30.5)],
            [(28.8, 19.0), (28.8, 31.0)],
            [(56.7, 18.2), (56.9, 31.8)],
            [(90.0, 10.0), (130.0, 10.0)],
        ]
        divider = mod._detect_a4_header_thumb_divider_x_mm(polys, src_x0=0.0, src_y0=0.0)
        self.assertAlmostEqual(divider, 56.8, places=1)

    def test_compose_a4_hybrid_frame_caps_header_content_scale_when_frame_expands(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (100.0, 0.0)],
            [(20.0, 5.0), (24.0, 10.0), (28.0, 5.0)],
            [(30.0, 70.0), (80.0, 70.0)],
        ]
        with (
            mock.patch.object(mod, "_detect_a4_title_box_mm", return_value={}),
            mock.patch.object(
                mod,
                "_is_detail_polyline_mm",
                side_effect=lambda poly, **_kwargs: min(float(y) for _x, y in poly) >= 50.0,
            ),
        ):
            transformed, info = mod._compose_a4_hybrid_frame_polylines(
                polys,
                page_w_mm=210.0,
                page_h_mm=297.0,
                target_w_mm=180.0,
                target_h_mm=280.0,
            )
        self.assertAlmostEqual(info["frame_scale_x"], 1.8)
        self.assertAlmostEqual(info["header_scale_x"], 1.0)
        self.assertEqual(info["header_content_paths"], 1.0)
        frame_x1 = mod._poly_bbox_mm(transformed[0])[2]
        header_x1 = mod._poly_bbox_mm(transformed[1])[2]
        detail_x1 = mod._poly_bbox_mm(transformed[2])[2]
        self.assertAlmostEqual(frame_x1, 180.0, places=3)
        self.assertAlmostEqual(header_x1, 28.0, places=3)
        self.assertAlmostEqual(detail_x1, 80.0, places=3)

    def test_compose_a4_hybrid_frame_caps_condition_overlay_scale_when_frame_expands(self) -> None:
        mod = _load_module()
        polys = [[(0.0, 0.0), (100.0, 0.0)], [(30.0, 70.0), (80.0, 70.0)]]
        overlay = [[(6.0, 6.0), (16.0, 6.0), (16.0, 16.0), (6.0, 16.0), (6.0, 6.0)]]
        with (
            mock.patch.object(mod, "_detect_a4_title_box_mm", return_value={}),
            mock.patch.object(
                mod,
                "_is_detail_polyline_mm",
                side_effect=lambda poly, **_kwargs: min(float(y) for _x, y in poly) >= 50.0,
            ),
        ):
            transformed, info = mod._compose_a4_hybrid_frame_polylines(
                polys,
                page_w_mm=210.0,
                page_h_mm=297.0,
                target_w_mm=180.0,
                target_h_mm=280.0,
                extra_frame_polys=overlay,
            )
        overlay_bbox = mod._poly_bbox_mm(transformed[-1])
        self.assertAlmostEqual(info["header_scale_x"], 1.0)
        self.assertEqual(info["header_content_paths"], 1.0)
        self.assertAlmostEqual(overlay_bbox[2] - overlay_bbox[0], 10.0, places=3)
        self.assertAlmostEqual(overlay_bbox[3] - overlay_bbox[1], 10.0 * info["header_scale_y"], places=3)

    def test_compose_a4_hybrid_frame_expands_thumbnail_and_shifts_header_text(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (100.0, 0.0)],
            [(28.8, 18.0), (28.8, 30.0)],
            [(10.0, 20.0), (24.0, 20.0)],
            [(65.0, 18.0), (75.0, 24.0), (85.0, 18.0)],
        ]
        with (
            mock.patch.object(mod, "_detect_a4_title_box_mm", return_value={}),
            mock.patch.object(
                mod,
                "_is_detail_polyline_mm",
                return_value=False,
            ),
        ):
            transformed, info = mod._compose_a4_hybrid_frame_polylines(
                polys,
                page_w_mm=210.0,
                page_h_mm=297.0,
                target_w_mm=180.0,
                target_h_mm=280.0,
            )
        thumb_line_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: abs(box[1] - 20.0) <= 0.05 and abs(box[3] - 20.0) <= 0.05 and abs((box[2] - box[0]) - 14.0) <= 0.05,
        )
        text_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: box[0] > info["header_thumb_target_w"] and box[1] >= 18.0 and box[3] <= 24.5,
        )
        self.assertGreater(info["header_thumb_target_w"], 50.0)
        self.assertAlmostEqual(thumb_line_bbox[2] - thumb_line_bbox[0], 14.0, places=2)
        self.assertGreater(text_bbox[0], info["header_thumb_target_w"])
        self.assertAlmostEqual(info["header_text_scale_x"], 0.92, places=2)
        self.assertEqual(info["header_text_paths"], 1.0)

    def test_compose_a4_hybrid_frame_accepts_variant_specific_header_overrides(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (100.0, 0.0)],
            [(28.8, 18.0), (28.8, 30.0)],
            [(10.0, 20.0), (24.0, 20.0)],
            [(65.0, 18.0), (75.0, 24.0), (85.0, 18.0)],
        ]
        with (
            mock.patch.object(mod, "_detect_a4_title_box_mm", return_value={}),
            mock.patch.object(
                mod,
                "_is_detail_polyline_mm",
                return_value=False,
            ),
        ):
            transformed, info = mod._compose_a4_hybrid_frame_polylines(
                polys,
                page_w_mm=210.0,
                page_h_mm=297.0,
                target_w_mm=180.0,
                target_h_mm=280.0,
                header_thumb_target_min_w_mm=76.0,
                header_text_gap_mm=7.0,
                header_text_scale_x=0.84,
                header_thumb_content_scale_x=1.0,
            )
        thumb_line_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: abs(box[1] - 20.0) <= 0.05 and abs(box[3] - 20.0) <= 0.05 and abs((box[2] - box[0]) - 14.0) <= 0.05,
        )
        text_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: box[0] >= 83.0 and box[1] >= 18.0 and box[3] <= 24.5,
        )
        self.assertAlmostEqual(info["header_thumb_target_w"], 76.0, places=2)
        self.assertAlmostEqual(thumb_line_bbox[2] - thumb_line_bbox[0], 14.0, places=2)
        self.assertGreaterEqual(text_bbox[0], 83.0)
        self.assertAlmostEqual(info["header_text_scale_x"], 0.84, places=2)
        self.assertAlmostEqual(info["header_thumb_content_scale_x"], 1.0, places=2)

    def test_configure_toe_backend_uses_centerline_for_formula_rasters(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_backend_cfg_") as td:
            font_path = Path(td) / "font.ttf"
            font_path.write_bytes(b"font")
            mod._configure_toe_backend(font_path)
        self.assertEqual(mod.backend.IMAGE_CONTOUR_VECTORIZE_MODE, "centerline")
        self.assertEqual(mod.backend.IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE, "centerline")

    def test_prepare_toe_raster_fallback_uses_handdraw_preview(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_raster_fallback_") as td:
            root = Path(td)
            source_pdf = root / "src.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")
            page_svg = root / "page_14_source.svg"
            page_svg.write_text("<svg />", encoding="utf-8")
            prefix = root / "page_14"
            capture: dict[str, object] = {}
            copied: dict[str, object] = {}

            def _fake_bridge_run_preview(**kwargs):
                capture.update(kwargs)
                return True, "ok", ["preview-ok"]

            def _fake_export_pdf_page_to_mupdf_svg(_pdf_path, _page_index, out_svg):
                Path(out_svg).write_text("<svg />", encoding="utf-8")

            def _fake_copy_latest_preview_artifacts(prefix_arg, *, op_id=None):
                copied["prefix"] = prefix_arg
                copied["op_id"] = op_id
                return (
                    root / "page_14.svg",
                    root / "page_14.pdf",
                    root / "page_14.nc",
                    root / "page_14.gcode",
                )

            with (
                mock.patch.object(mod, "_rewrite_pdf_page_text_to_handwritten_pdf", return_value=None),
                mock.patch.object(mod, "_export_pdf_page_to_mupdf_svg", side_effect=_fake_export_pdf_page_to_mupdf_svg),
                mock.patch.object(mod, "_merge_table_like_vectors_into_svg", return_value=6),
                mock.patch.object(mod, "_bridge_run_preview", side_effect=_fake_bridge_run_preview),
                mock.patch.object(
                    mod,
                    "_copy_latest_preview_artifacts",
                    side_effect=_fake_copy_latest_preview_artifacts,
                ),
                mock.patch.object(mod, "_analyze_gcode", return_value={"segments_total": 10}),
                mock.patch.object(mod, "_layout_similarity_pdf", return_value=0.97),
            ):
                row = mod._prepare_toe_raster_fallback(
                    source_pdf=source_pdf,
                    page_index=14,
                    page_svg=page_svg,
                    prefix=prefix,
                    font_label="Neucha",
                    font_path=root / "font.ttf",
                )

        self.assertTrue(row["ok"])
        self.assertEqual(Path(str(capture["input_path"])).suffix.lower(), ".svg")
        self.assertEqual(capture["render_mode"], "handwriting")
        self.assertTrue(capture["handwriting_enabled"])
        self.assertEqual(capture["image_contours_mode"], "always")
        self.assertIn("raster_rewrite_handdraw", row["notes"])
        self.assertIn("formula_font=Times New Roman", row["notes"])
        self.assertIn("table_vector_overlay=enabled", row["notes"])
        self.assertIn("table_vector_overlay_count=6", row["logs"])
        self.assertEqual(copied["prefix"], prefix.parent / f"{prefix.name}__fallback_candidate")
        self.assertIsInstance(copied["op_id"], str)
        self.assertTrue(str(copied["op_id"]).startswith("preview-"))

    def test_preview_artifact_sources_prefers_unique_op_id_files(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_preview_sources_") as td:
            root = Path(td)
            old_root = mod.PROJECT_ROOT
            try:
                mod.PROJECT_ROOT = root
                tmp = root / "_tmp"
                tmp.mkdir(parents=True, exist_ok=True)
                (tmp / "latest_preview.nc").write_text("legacy", encoding="utf-8")
                (tmp / "latest_preview_vector.svg").write_text("<svg />", encoding="utf-8")
                (tmp / "latest_preview_vector.pdf").write_bytes(b"%PDF-1.4\n")
                (tmp / "latest_preview_preview-123.nc").write_text("unique", encoding="utf-8")
                (tmp / "latest_preview_preview-123_vector.svg").write_text("<svg id='u'/>", encoding="utf-8")
                (tmp / "latest_preview_preview-123_vector.pdf").write_bytes(b"%PDF-1.4\n%unique")
                svg_path, pdf_path, nc_path = mod._preview_artifact_sources(op_id="preview-123")
            finally:
                mod.PROJECT_ROOT = old_root
        self.assertEqual(nc_path.name, "latest_preview_preview-123.nc")
        self.assertEqual(svg_path.name, "latest_preview_preview-123_vector.svg")
        self.assertEqual(pdf_path.name, "latest_preview_preview-123_vector.pdf")


if __name__ == "__main__":
    unittest.main()
