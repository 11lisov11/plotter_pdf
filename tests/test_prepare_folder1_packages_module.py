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

    def test_analyze_gcode_reports_fragmentation_metrics(self) -> None:
        mod = _load_module()
        z_up = float(mod.backend.Z_UP)
        z_down = float(mod.backend.Z_DOWN)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.nc"
            path.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        f"G0 Z{z_up:.4f}",
                        "G0 X0.0000 Y0.0000",
                        f"G1 Z{z_down:.4f} F1000.0",
                        "G1 X0.1000 Y0.0000 F1000.0",
                        f"G0 Z{z_up:.4f}",
                        "G0 X1.0000 Y0.0000",
                        f"G1 Z{z_down:.4f} F1000.0",
                        "G1 X1.2000 Y0.0000 F1000.0",
                        "G1 X2.0000 Y0.0000 F1000.0",
                        f"G0 Z{z_up:.4f}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            metrics = mod._analyze_gcode(path)

        self.assertEqual(metrics["pen_down_strokes"], 2)
        self.assertEqual(metrics["segments_total"], 3)
        self.assertEqual(metrics["short_segments_lt_035_mm"], 2)
        self.assertEqual(metrics["micro_segments_lt_015_mm"], 1)
        self.assertEqual(metrics["tiny_strokes_lt_08_mm"], 1)
        self.assertEqual(metrics["point_like_strokes"], 1)
        self.assertGreater(float(metrics["avg_stroke_length_mm"]), 0.0)

    def test_candidate_source_fidelity_score_rewards_similarity_and_crop(self) -> None:
        mod = _load_module()
        low = mod._candidate_source_fidelity_score(
            {
                "layout_similarity": 0.94,
                "source_crop_iou": 0.03,
                "source_crop_corr": -0.10,
            }
        )
        high = mod._candidate_source_fidelity_score(
            {
                "layout_similarity": 0.95,
                "source_crop_iou": 0.12,
                "source_crop_corr": 0.25,
            }
        )
        self.assertGreater(high, low)

    def test_prepare_kompas_a4_clean_bbox_fit_uses_clean_bbox_not_source_page(self) -> None:
        mod = _load_module()
        frame = [
            (20.0, 5.0),
            (205.0, 5.0),
            (205.0, 292.0),
            (20.0, 292.0),
            (20.0, 5.0),
        ]
        inner = [(70.0, 90.0), (120.0, 90.0)]
        logs: list[str] = []

        prepared, meta = mod._prepare_kompas_a4_clean_bbox_fit_polylines([frame, inner], logs=logs)

        self.assertTrue(meta["applied"])
        self.assertEqual(meta["clipped_segments"], 0)
        self.assertAlmostEqual(meta["content_scale"], 180.0 / 185.0, places=6)
        self.assertEqual(
            prepared[0],
            [(0.0, -5.0), (180.0, -5.0), (180.0, -285.0), (0.0, -285.0), (0.0, -5.0)],
        )
        prepared_lengths = [round(mod._polyline_length(poly), 3) for poly in prepared[1:]]
        self.assertIn(round(50.0 * (180.0 / 185.0), 3), prepared_lengths)
        self.assertTrue(any("source-page fit disabled" in line for line in logs))

    def test_prepare_kompas_a4_clean_bbox_fit_dedups_inner_line_on_work_frame(self) -> None:
        mod = _load_module()
        frame = [
            (20.0, 5.0),
            (205.0, 5.0),
            (205.0, 292.0),
            (20.0, 292.0),
            (20.0, 5.0),
        ]
        inner_on_left_frame = [(20.0, 80.0), (20.0, 140.0)]

        prepared, meta = mod._prepare_kompas_a4_clean_bbox_fit_polylines([frame, inner_on_left_frame], logs=[])

        self.assertTrue(meta["applied"])
        left_frame_like = []
        for poly in prepared:
            for a, b in zip(poly, poly[1:]):
                if abs(float(a[0])) <= 1e-6 and abs(float(b[0])) <= 1e-6:
                    left_frame_like.append((a, b))
        self.assertEqual(len(left_frame_like), 1)

    def test_strip_outer_bbox_frame_ignores_text_above_frame(self) -> None:
        mod = _load_module()
        frame = [
            (20.0, 5.0),
            (205.0, 5.0),
            (205.0, 292.0),
            (20.0, 292.0),
            (20.0, 5.0),
        ]
        text_above_frame = [(35.0, 1.0), (75.0, 3.0)]

        _stripped, meta = mod._strip_outer_bbox_frame_segments([frame, text_above_frame])

        self.assertTrue(meta["applied"])
        self.assertEqual(meta["source_bbox"], [20.0, 5.0, 205.0, 292.0])

    def test_kompas_text_poly_candidate_preserves_table_lines(self) -> None:
        mod = _load_module()
        text_regions = [(50.0, 250.0, 75.0, 258.0)]

        glyph_fragment = [(54.0, 252.0), (54.4, 252.5), (54.8, 252.0)]
        glyph_fragment_below_pdf_bbox = [(54.0, 260.5), (54.4, 261.0), (54.8, 260.5)]
        table_line = [(40.0, 254.0), (90.0, 254.0)]

        self.assertTrue(mod._kompas_text_poly_candidate_mm(glyph_fragment, text_regions=text_regions))
        self.assertTrue(mod._kompas_text_poly_candidate_mm(glyph_fragment_below_pdf_bbox, text_regions=text_regions))
        self.assertFalse(mod._kompas_text_poly_candidate_mm(table_line, text_regions=text_regions))

    def test_reroute_kompas_text_replaces_outline_fragments_with_single_line_text(self) -> None:
        mod = _load_module()
        source_pdf = Path("drawing.pdf")
        glyph_fragment = [(54.0, 252.0), (54.4, 252.5), (54.8, 252.0)]
        geometry_line = [(40.0, 254.0), (90.0, 254.0)]
        rendered_text = [[(50.0, 253.0), (70.0, 253.0)]]

        with mock.patch.object(
            mod,
            "_extract_kompas_plot_text_lines_from_pdf",
            return_value=[{"text": "K1", "bbox_mm": (50.0, 250.0, 75.0, 258.0)}],
        ), mock.patch.object(
            mod,
            "_render_pdf_text_lines_polylines_in_place",
            return_value=rendered_text,
        ):
            logs: list[str] = []
            out, meta = mod._reroute_kompas_text_polylines(
                [glyph_fragment, geometry_line],
                source_pdf=source_pdf,
                page_index=0,
                logger=logs.append,
            )

        self.assertNotIn(glyph_fragment, out)
        self.assertIn(geometry_line, out)
        self.assertIn(rendered_text[0], out)
        self.assertEqual(meta["kompas_text_lines"], 1.0)
        self.assertEqual(meta["kompas_text_removed"], 1.0)
        self.assertEqual(meta["kompas_text_rendered"], 1.0)
        self.assertTrue(any("KOMPAS text reroute" in line for line in logs))

    def test_reroute_kompas_text_places_single_line_on_visible_outline_bbox(self) -> None:
        mod = _load_module()
        source_pdf = Path("drawing.pdf")
        pdf_bbox = (30.0, 1.5, 80.0, 12.0)
        visible_outline = [(34.0, 12.5), (45.0, 16.0), (60.0, 13.0)]
        rendered_text = [[(34.0, 14.0), (60.0, 14.0)]]

        def fake_render(lines, **_kwargs):
            self.assertEqual(lines[0]["bbox_mm"], (34.0, 12.5, 60.0, 16.0))
            return rendered_text

        with mock.patch.object(
            mod,
            "_extract_kompas_plot_text_lines_from_pdf",
            return_value=[{"text": "M400", "bbox_mm": pdf_bbox}],
        ), mock.patch.object(
            mod,
            "_render_pdf_text_lines_polylines_in_place",
            side_effect=fake_render,
        ):
            out, meta = mod._reroute_kompas_text_polylines(
                [visible_outline],
                source_pdf=source_pdf,
                page_index=0,
                logger=lambda _msg: None,
            )

        self.assertEqual(out, rendered_text)
        self.assertEqual(meta["kompas_text_removed"], 1.0)

    def test_kompas_preserve_source_text_region_keeps_stamp_and_top_designation(self) -> None:
        mod = _load_module()

        self.assertTrue(
            mod._kompas_preserve_source_text_region_mm(
                (30.0, 1.5, 80.0, 12.0),
                page_h_mm=298.0,
                archive_cutoff_x_mm=14.5,
            )
        )
        self.assertTrue(
            mod._kompas_preserve_source_text_region_mm(
                (121.0, 240.0, 170.0, 251.0),
                page_h_mm=298.0,
                archive_cutoff_x_mm=14.5,
            )
        )
        self.assertFalse(
            mod._kompas_preserve_source_text_region_mm(
                (96.0, 31.0, 106.0, 39.0),
                page_h_mm=298.0,
                archive_cutoff_x_mm=14.5,
            )
        )

    def test_candidate_fragmentation_score_penalizes_tiny_and_pointlike_strokes(self) -> None:
        mod = _load_module()
        good = mod._candidate_fragmentation_score(
            {
                "segments_total": 100,
                "pen_down_strokes": 20,
                "tiny_strokes_lt_08_mm": 2,
                "point_like_strokes": 1,
            }
        )
        bad = mod._candidate_fragmentation_score(
            {
                "segments_total": 100,
                "pen_down_strokes": 1500,
                "tiny_strokes_lt_08_mm": 60,
                "point_like_strokes": 30,
            }
        )
        self.assertGreater(good, bad)

    def test_drawing_quality_score_combines_layout_fidelity_and_fragmentation(self) -> None:
        mod = _load_module()
        weak = mod._drawing_quality_score(
            layout_similarity=0.94,
            source_fidelity_score=0.60,
            fragmentation_score=0.91,
        )
        strong = mod._drawing_quality_score(
            layout_similarity=0.95,
            source_fidelity_score=0.82,
            fragmentation_score=0.97,
        )
        self.assertIsNotNone(weak)
        self.assertIsNotNone(strong)
        self.assertGreater(float(strong), float(weak))

    def test_should_reroute_title_block_text_only_for_large_computer_graphics_sheets(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="title_block_reroute_rule_") as td:
            root = Path(td)
            cg_dir = root / "Компьютерная графика" / "22 вариант"
            cg_dir.mkdir(parents=True, exist_ok=True)
            a3_pdf = cg_dir / "МЧ00.60.00.00 СБ Вентиль.pdf"
            doc = mod.fitz.open()
            page = doc.new_page(width=1190, height=842)
            page.insert_text((900, 760), "МЧ00.60.00.00")
            page.insert_text((900, 780), "Вентиль")
            page.insert_text((900, 800), "Сборочный чертеж")
            page.insert_text((900, 820), "Лит. Масса Масштаб")
            page.insert_text((900, 835), "Лист 1")
            doc.save(a3_pdf)
            doc.close()

            a4_pdf = cg_dir / "МЧ00.60.00.03 Втулка.pdf"
            doc = mod.fitz.open()
            page = doc.new_page(width=595, height=842)
            page.insert_text((430, 760), "МЧ00.60.00.03")
            page.insert_text((430, 780), "Втулка")
            page.insert_text((430, 800), "Масштаб")
            doc.save(a4_pdf)
            doc.close()

            with mock.patch.object(
                mod,
                "_extract_title_block_text_lines_from_pdf",
                side_effect=[
                    [{"text": "x", "bbox_mm": (1.0, 1.0, 2.0, 2.0)} for _ in range(6)],
                    [{"text": "x", "bbox_mm": (1.0, 1.0, 2.0, 2.0)} for _ in range(6)],
                ],
            ):
                self.assertTrue(mod._should_reroute_title_block_text(a3_pdf))
                self.assertFalse(mod._should_reroute_title_block_text(a4_pdf))

    def test_build_sheet_preview_centers_compact_source_page(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gcode_path = root / "sample.nc"
            ref_pdf = root / "ref.pdf"
            out_svg = root / "out.svg"
            out_pdf = root / "out.pdf"
            gcode_path.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 Z0.0000",
                        "G1 Z11.9000 F1000.0",
                        "G1 X180.0000 Y-15.0000 F1000.0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            ref_pdf.write_bytes(b"%PDF-1.4\n")
            captured: dict[str, object] = {}

            def _capture_svg(polys, *_args, **_kwargs):
                captured["polys"] = polys

            with mock.patch.object(mod, "_gcode_to_polylines", return_value=[[(0.0, 0.0), (180.0, 280.0)]]), \
                mock.patch.object(mod, "_pdf_first_page_size_mm", return_value=(186.097, 286.089)), \
                mock.patch.object(mod, "_pdf_visible_bbox_mm", return_value=(0.176, 0.176, 185.657, 285.736)), \
                mock.patch.object(mod, "_write_svg_preview", side_effect=_capture_svg), \
                mock.patch.object(mod, "_render_polylines_pdf", return_value=None):
                logs: list[str] = []
                ok, msg = mod._build_sheet_preview_from_gcode(
                    gcode_path=gcode_path,
                    reference_pdf=ref_pdf,
                    out_svg=out_svg,
                    out_pdf=out_pdf,
                    logs=logs,
                )

            self.assertTrue(ok, msg)
            self.assertTrue(any("centered on compact source page bbox" in line for line in logs))
            shifted = captured["polys"]
            self.assertAlmostEqual(shifted[0][0][0], 3.0485, places=3)
            self.assertAlmostEqual(shifted[0][0][1], 3.0445, places=3)

    def test_condition_image_rect_filter_accepts_only_small_thumbnails(self) -> None:
        mod = _load_module()
        self.assertTrue(mod._is_small_condition_image_rect_mm(5.0, 5.0, 40.0, 34.0))
        self.assertTrue(mod._is_small_condition_image_rect_mm(200.0, 250.0, 233.5, 277.0))
        self.assertFalse(mod._is_small_condition_image_rect_mm(5.0, 5.0, 90.0, 34.0))
        self.assertFalse(mod._is_small_condition_image_rect_mm(5.0, 5.0, 40.0, 80.0))
        self.assertFalse(mod._is_small_condition_image_rect_mm(5.0, 5.0, 10.0, 10.0))

    def test_variant4_nachert_a4_preserves_source_header_route(self) -> None:
        mod = _load_module()
        self.assertTrue(
            mod._preserve_nachert_header_source_for_variant(
                Path(r"C:\plotter_pdf\Начерт\4 варинт\_generated_pdf\Задача 4.pdf")
            )
        )
        self.assertTrue(
            mod._preserve_nachert_header_source_for_variant(
                Path(r"C:\plotter_pdf\Начерт\1 вариант\Задача 1_pack\source_kompas.pdf")
            )
        )
        self.assertFalse(
            mod._preserve_nachert_header_source_for_variant(
                Path(r"C:\plotter_pdf\Начерт\24 варинт\Задача 4.pdf")
            )
        )

    def test_a3_header_band_image_rect_filter_accepts_wide_top_banner(self) -> None:
        mod = _load_module()
        self.assertTrue(
            mod._is_a3_header_band_image_rect_mm(
                10.0,
                13.5,
                195.5,
                53.8,
                page_w_mm=420.0,
                page_h_mm=297.0,
            )
        )
        self.assertFalse(
            mod._is_a3_header_band_image_rect_mm(
                25.0,
                13.5,
                195.5,
                53.8,
                page_w_mm=420.0,
                page_h_mm=297.0,
            )
        )

    def test_force_a3_two_pass_for_large_sheet_matches_corpus_only(self) -> None:
        mod = _load_module()
        self.assertTrue(
            mod._force_a3_two_pass_for_large_sheet(
                Path(r"C:\plotter_pdf\Компьютерная графика\МЧ00.01.00.01 Корпус.pdf")
            )
        )
        self.assertFalse(
            mod._force_a3_two_pass_for_large_sheet(
                Path(r"C:\plotter_pdf\Компьютерная графика\МЧ00.01.00.00 СБ Клапан перепускной.pdf")
            )
        )
        self.assertFalse(
            mod._force_a3_two_pass_for_large_sheet(
                Path(r"C:\plotter_pdf\Начерт\24 варинт\Задача 10.pdf")
            )
        )

    def test_force_a4_single_page_for_drawing_disabled(self) -> None:
        mod = _load_module()
        self.assertTrue(
            mod._force_a4_single_page_for_drawing(
                Path(r"C:\plotter_pdf\Компьютерная графика\МЧ00.01.00.02 Крышка.pdf")
            )
        )
        self.assertFalse(
            mod._force_a4_single_page_for_drawing(
                Path(r"C:\plotter_pdf\Компьютерная графика\МЧ00.01.00.01 Корпус.pdf")
            )
        )
        self.assertFalse(
            mod._force_a4_single_page_for_drawing(
                Path(r"C:\plotter_pdf\Компьютерная графика\Втулка.pdf")
            )
        )

    def test_detect_a3_header_miniature_crop_px_finds_left_thumbnail(self) -> None:
        mod = _load_module()
        img = mod.Image.new("L", (1200, 260), 255)
        draw = mod.ImageDraw.Draw(img)
        draw.rectangle((25, 20, 75, 70), outline=0, width=3)
        draw.rectangle((120, 55, 300, 235), outline=0, width=4)
        draw.line((300, 0, 300, 259), fill=0, width=5)
        draw.text((420, 70), "header text", fill=0)
        crop = mod._detect_a3_header_miniature_crop_px(img)
        self.assertIsNotNone(crop)
        x0, y0, x1, y1 = crop
        self.assertLess(x0, 180)
        self.assertGreater(x1, 260)
        self.assertLess(x1, 320)
        self.assertLess(y0, 80)
        self.assertGreater(y1, 200)

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

    def test_normalize_technical_point_boxes_replaces_larger_supported_square_marker_and_skips_nested_duplicate(self) -> None:
        mod = _load_module()
        outer = [
            (76.8482, 174.7894),
            (80.2352, 174.7894),
            (80.2352, 178.2613),
            (76.8482, 178.2613),
            (76.8482, 174.7894),
        ]
        inner = [
            (77.3500, 175.3200),
            (79.7100, 175.3200),
            (79.7100, 177.6900),
            (77.3500, 177.6900),
            (77.3500, 175.3200),
        ]
        support = [(74.0, 176.5), (83.0, 176.5)]
        out, meta = mod._normalize_technical_point_boxes(
            [support, outer, inner],
            page_w_mm=420.0,
            page_h_mm=297.0,
        )
        self.assertGreaterEqual(meta["point_boxes_replaced"], 2.0)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], support)
        x0, y0, x1, y1 = mod._poly_bbox_mm(out[1])
        self.assertLess(x1 - x0, 1.0)
        self.assertLess(y1 - y0, 1.0)

    def test_normalize_technical_point_boxes_converts_compact_arrowhead_polygon_to_v_stroke(self) -> None:
        mod = _load_module()
        arrow_poly = [
            (172.2609, 244.9782),
            (172.4212, 245.3397),
            (172.8365, 245.2856),
            (173.2037, 244.6137),
            (172.8089, 244.1948),
            (172.4474, 244.3840),
            (172.2609, 244.9782),
        ]
        support = [(171.0, 244.8), (174.8, 244.8)]
        out, meta = mod._normalize_technical_point_boxes(
            [support, arrow_poly],
            page_w_mm=420.0,
            page_h_mm=500.0,
        )
        self.assertGreaterEqual(meta["point_boxes_replaced"], 1.0)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], support)
        self.assertEqual(len(out[1]), 3)

    def test_normalize_technical_point_boxes_drops_supported_arrow_bbox_artifact(self) -> None:
        mod = _load_module()
        support_a = [(76.7212, 174.6200), (79.1767, 179.0234)]
        support_b = [(76.7212, 174.6200), (80.2352, 178.2613)]
        support_c = [(75.7051, 175.3821), (78.2877, 173.4768)]
        bbox_artifact = [
            (76.8059, 174.7470),
            (79.3884, 174.7470),
            (79.3884, 179.0234),
            (76.8059, 179.0234),
            (76.8059, 174.7470),
        ]
        out, meta = mod._normalize_technical_point_boxes(
            [support_a, support_b, support_c, bbox_artifact],
            page_w_mm=420.0,
            page_h_mm=500.0,
        )
        self.assertGreaterEqual(meta["point_boxes_replaced"], 1.0)
        self.assertEqual(out, [support_a, support_b, support_c])

    def test_normalize_technical_point_boxes_drops_supported_arrow_bbox_artifact_outside_detail_band(self) -> None:
        mod = _load_module()
        support_a = [(135.5073, 256.9006), (137.0427, 259.0021), (138.9726, 261.6874)]
        support_b = [(135.7645, 258.2502), (139.0120, 261.7242)]
        support_c = [(137.2122, 263.0729), (139.5989, 261.2746)]
        bbox_artifact = [
            (136.5079, 257.4737),
            (138.9729, 257.4737),
            (138.9729, 261.6016),
            (136.5079, 261.6016),
            (136.5079, 257.4737),
        ]
        out, meta = mod._normalize_technical_point_boxes(
            [support_a, support_b, support_c, bbox_artifact],
            page_w_mm=420.0,
            page_h_mm=297.0,
        )
        self.assertGreaterEqual(meta["point_boxes_replaced"], 1.0)
        self.assertEqual(out, [support_a, support_b, support_c])

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

    def test_maybe_reanchor_a3_clean_source_polylines_shifts_hybrid_canvas_into_source_bbox(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (360.0, 0.0), (360.0, 280.0), (0.0, 280.0), (0.0, 0.0)],
            [(120.0, 60.0), (180.0, 60.0)],
        ]
        shifted, changed = mod._maybe_reanchor_a3_clean_source_polylines(
            polys,
            ref_bbox_mm=(0.0, 6.614, 410.243, 296.922),
        )
        self.assertTrue(changed)
        x0, y0, x1, y1 = mod._polys_bbox_mm(shifted)
        self.assertAlmostEqual(x0, 25.1215, places=3)
        self.assertAlmostEqual(y0, 6.6140, places=3)
        self.assertAlmostEqual(x1, 385.1215, places=3)
        self.assertAlmostEqual(y1, 286.6140, places=3)

    def test_maybe_reanchor_a3_clean_source_polylines_keeps_regular_page_layout_unchanged(self) -> None:
        mod = _load_module()
        polys = [
            [(20.5, 5.5), (415.5, 5.5), (415.5, 292.6), (20.5, 292.6), (20.5, 5.5)],
        ]
        shifted, changed = mod._maybe_reanchor_a3_clean_source_polylines(
            polys,
            ref_bbox_mm=(0.353, 0.353, 420.518, 297.494),
        )
        self.assertFalse(changed)
        self.assertEqual(shifted, polys)

    def test_clip_polyline_max_x_trims_spill_but_keeps_left_segment(self) -> None:
        mod = _load_module()
        poly = [(5.0, 10.0), (20.0, 10.0), (45.0, 12.0)]
        clipped = mod._clip_polyline_max_x_mm(poly, 18.0)
        self.assertEqual(len(clipped), 1)
        x0, _y0, x1, _y1 = mod._poly_bbox_mm(clipped[0])
        self.assertAlmostEqual(x0, 5.0, places=3)
        self.assertAlmostEqual(x1, 18.0, places=3)
        self.assertGreaterEqual(len(clipped[0]), 2)

    def test_cleanup_a4_header_gutter_artifacts_removes_only_tiny_gap_segments(self) -> None:
        mod = _load_module()
        polys = [
            [(46.6, 258.7), (48.1, 258.7)],
            [(49.4, 264.8), (50.8, 264.7)],
            [(55.2, 266.1), (55.6, 266.1)],
            [(60.4, 268.5), (63.8, 271.0), (65.0, 271.2)],
            [(0.0, 288.0), (171.0, 288.0)],
        ]
        cleaned, removed = mod._cleanup_a4_header_gutter_artifacts(
            polys,
            header_thumb_x1_mm=47.56,
            header_text_x0_mm=59.4,
            top_band_y1_mm=295.0,
        )
        self.assertEqual(removed, 3)
        self.assertEqual(len(cleaned), 2)
        self.assertIn(polys[3], cleaned)
        self.assertIn(polys[4], cleaned)

    def test_ensure_a4_header_bottom_separator_adds_missing_long_line(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (171.0, 0.0)],
            [(0.0, 35.4), (59.4, 35.4)],
        ]
        header_lines = [
            {"text": "demo", "bbox_mm": (60.0, 8.0, 150.0, 44.0)},
        ]
        updated, added = mod._ensure_a4_header_bottom_separator(
            polys,
            header_lines=header_lines,
            src_y0=0.0,
            header_scale_y=1.0,
            target_w_mm=180.0,
        )
        self.assertTrue(added)
        sep = self._find_poly_bbox(
            mod,
            updated,
            lambda box: abs(box[1] - 48.0) <= 0.05 and abs(box[3] - 48.0) <= 0.05 and box[2] >= 170.0,
        )
        self.assertAlmostEqual(sep[0], 0.0, places=3)

    def test_ensure_a4_header_bottom_separator_skips_when_line_exists(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (171.0, 0.0)],
            [(0.0, 48.0), (171.0, 48.0)],
        ]
        header_lines = [
            {"text": "demo", "bbox_mm": (60.0, 8.0, 150.0, 44.0)},
        ]
        updated, added = mod._ensure_a4_header_bottom_separator(
            polys,
            header_lines=header_lines,
            src_y0=0.0,
            header_scale_y=1.0,
            target_w_mm=180.0,
        )
        self.assertFalse(added)
        self.assertEqual(len(updated), 2)

    def test_remove_a4_header_thumb_full_width_duplicate_drops_only_full_span_line(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 48.2), (59.4, 48.2)],
            [(20.4, 48.0), (59.4, 48.0)],
            [(0.0, 48.0), (171.0, 48.0)],
        ]
        updated, removed = mod._remove_a4_header_thumb_full_width_duplicate(
            polys,
            header_thumb_x1_mm=59.4,
            separator_y_mm=48.0,
        )
        self.assertEqual(removed, 2)
        self.assertEqual(len(updated), 1)
        self.assertIn(polys[2], updated)

    def test_dedupe_a4_header_band_axis_lines_removes_close_parallel_duplicates(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (60.0, 0.0)],
            [(0.0, 0.55), (59.8, 0.55)],
            [(28.0, 0.0), (28.0, 30.0)],
            [(28.45, 0.0), (28.45, 29.8)],
            [(8.0, 10.0), (8.0, 24.0)],
            [(10.0, 12.0), (12.0, 12.0)],
        ]

        updated, removed = mod._dedupe_a4_header_band_axis_lines(
            polys,
            top_band_y1_mm=35.0,
        )

        self.assertEqual(removed, 2)
        self.assertEqual(len(updated), 4)
        self.assertIn(polys[0], updated)
        self.assertIn(polys[2], updated)
        self.assertIn(polys[4], updated)
        self.assertIn(polys[5], updated)

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
            [(0.0, 0.0), (28.8, 0.0)],
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
        thumb_divider_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: abs(box[0] - 76.0) <= 0.1 and abs(box[2] - 76.0) <= 0.1 and box[3] >= 29.0,
        )
        thumb_top_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: abs(box[1]) <= 0.1 and abs(box[3]) <= 0.1 and abs(box[2] - 76.0) <= 0.1,
        )
        text_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: box[0] >= 83.0 and box[1] >= 18.0 and box[3] <= 24.5,
        )
        self.assertAlmostEqual(info["header_thumb_target_w"], 76.0, places=2)
        self.assertAlmostEqual(thumb_line_bbox[2] - thumb_line_bbox[0], 14.0, places=2)
        self.assertAlmostEqual(thumb_divider_bbox[0], 76.0, places=2)
        self.assertAlmostEqual(thumb_top_bbox[2] - thumb_top_bbox[0], 76.0, places=2)
        self.assertGreaterEqual(text_bbox[0], 83.0)
        self.assertAlmostEqual(info["header_text_scale_x"], 0.84, places=2)
        self.assertAlmostEqual(info["header_thumb_content_scale_x"], 1.0, places=2)

    def test_compose_a4_hybrid_frame_scales_thumb_overlay_with_thumb_content(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (100.0, 0.0)],
            [(0.0, 0.0), (28.8, 0.0)],
            [(28.8, 18.0), (28.8, 30.0)],
            [(65.0, 18.0), (75.0, 24.0), (85.0, 18.0)],
        ]
        overlay = [[(4.0, 8.0), (20.0, 8.0)]]
        with (
            mock.patch.object(mod, "_detect_a4_title_box_mm", return_value={}),
            mock.patch.object(mod, "_is_detail_polyline_mm", return_value=False),
        ):
            transformed, info = mod._compose_a4_hybrid_frame_polylines(
                polys,
                page_w_mm=210.0,
                page_h_mm=297.0,
                target_w_mm=180.0,
                target_h_mm=280.0,
                extra_frame_polys=overlay,
                header_thumb_target_min_w_mm=76.0,
                header_text_gap_mm=7.0,
                header_text_scale_x=0.84,
                header_thumb_content_scale_x=2.0,
            )
        overlay_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: abs(box[1] - 8.0) <= 0.1 and abs(box[3] - 8.0) <= 0.1 and abs((box[2] - box[0]) - 32.0) <= 0.1,
        )
        self.assertAlmostEqual(overlay_bbox[0], 8.0, places=2)
        self.assertAlmostEqual(overlay_bbox[2] - overlay_bbox[0], 32.0, places=2)

    def test_compose_a4_hybrid_frame_can_fit_thumb_overlay_to_box(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (100.0, 0.0)],
            [(0.0, 0.0), (28.8, 0.0)],
            [(28.8, 18.0), (28.8, 30.0)],
            [(65.0, 18.0), (75.0, 24.0), (85.0, 18.0)],
        ]
        overlay = [[(2.0, 10.0), (18.0, 10.0)]]
        with (
            mock.patch.object(mod, "_detect_a4_title_box_mm", return_value={}),
            mock.patch.object(mod, "_is_detail_polyline_mm", return_value=False),
        ):
            transformed, info = mod._compose_a4_hybrid_frame_polylines(
                polys,
                page_w_mm=210.0,
                page_h_mm=297.0,
                target_w_mm=180.0,
                target_h_mm=280.0,
                extra_frame_polys=overlay,
                header_thumb_target_min_w_mm=64.0,
                fit_thumb_overlay_to_box=True,
            )
        overlay_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: box[0] >= 2.0 and box[2] <= 62.5 and (box[2] - box[0]) > 40.0 and abs(box[1] - box[3]) <= 0.1,
        )
        self.assertGreater(info["header_thumb_target_w"], 50.0)
        self.assertGreater(overlay_bbox[2] - overlay_bbox[0], 40.0)

    def test_variant1_header_defaults_expand_thumb_and_reduce_text(self) -> None:
        mod = _load_module()
        self.assertGreater(mod._A4_HEADER_VARIANT1_THUMB_TARGET_MIN_W_MM, mod._A4_HEADER_THUMB_TARGET_MIN_W_MM)
        self.assertGreater(mod._A4_HEADER_VARIANT1_TEXT_GAP_MM, mod._A4_HEADER_TEXT_GAP_MM)
        self.assertLess(mod._A4_HEADER_VARIANT1_TEXT_SCALE, mod._A4_HEADER_TEXT_SCALE)

    def test_compose_a4_hybrid_frame_can_preserve_header_band_layout(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (100.0, 0.0)],
            [(0.0, 0.0), (28.8, 0.0)],
            [(28.8, 0.0), (28.8, 30.0)],
            [(10.0, 20.0), (24.0, 20.0)],
            [(65.0, 18.0), (75.0, 24.0), (85.0, 18.0)],
        ]
        with (
            mock.patch.object(mod, "_detect_a4_title_box_mm", return_value={}),
            mock.patch.object(mod, "_is_detail_polyline_mm", return_value=False),
        ):
            transformed, info = mod._compose_a4_hybrid_frame_polylines(
                polys,
                page_w_mm=210.0,
                page_h_mm=297.0,
                target_w_mm=100.0,
                target_h_mm=100.0,
                preserve_header_band_layout=True,
            )
        divider_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: abs(box[0] - (28.8 * (100.0 / 210.0))) <= 0.1 and abs(box[2] - (28.8 * (100.0 / 210.0))) <= 0.1 and box[3] <= 11.0,
        )
        text_bbox = self._find_poly_bbox(
            mod,
            transformed,
            lambda box: 30.0 <= box[0] <= 32.0 and 6.0 <= box[1] <= 8.5,
        )
        self.assertAlmostEqual(divider_bbox[0], 28.8 * (100.0 / 210.0), places=2)
        self.assertAlmostEqual(text_bbox[0], 65.0 * (100.0 / 210.0), places=2)
        self.assertAlmostEqual(info["header_text_dst_x0"], info["header_text_src_x0"] * (100.0 / 210.0), places=2)
        self.assertAlmostEqual(info["header_text_scale_x"], 100.0 / 210.0, places=2)

    def test_compute_a4_header_thumb_content_scale_x_shrinks_to_fit(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (28.8, 0.0)],
            [(2.0, 8.0), (66.0, 12.0), (60.0, 18.0)],
            [(35.0, 12.0), (90.0, 12.0), (90.0, 20.0)],
        ]
        scale = mod._compute_a4_header_thumb_content_scale_x(
            polys,
            src_x0=0.0,
            src_y0=0.0,
            header_text_src_x0=80.0,
            header_thumb_target_w_mm=60.0,
            default_scale_x=1.0,
        )
        self.assertLess(scale, 1.0)
        self.assertAlmostEqual(scale, 59.0 / 66.0, places=3)

    def test_strip_a4_header_thumb_source_content_polys_keeps_only_frame(self) -> None:
        mod = _load_module()
        polys = [
            [(0.0, 0.0), (28.8, 0.0)],
            [(28.8, 0.0), (28.8, 30.0)],
            [(2.0, 8.0), (22.0, 8.0), (22.0, 22.0)],
            [(31.0, 10.0), (35.0, 10.0), (35.0, 14.0)],
            [(40.0, 18.0), (60.0, 18.0)],
        ]
        kept, removed = mod._strip_a4_header_thumb_source_content_polys(
            polys,
            src_x0=0.0,
            src_y0=0.0,
            header_thumb_divider_x=28.8,
            header_text_src_x0=32.8,
        )
        self.assertEqual(removed, 2)
        self.assertIn(polys[0], kept)
        self.assertIn(polys[1], kept)
        self.assertIn(polys[4], kept)
        self.assertNotIn(polys[2], kept)
        self.assertNotIn(polys[3], kept)

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

    def test_prepare_drawing_package_selects_best_a4_candidate_by_similarity(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="nachert_best_a4_") as td:
            root = Path(td)
            source_pdf = root / "source.pdf"
            doc = mod.fitz.open()
            doc.new_page(width=595, height=842)
            doc.save(source_pdf)
            doc.close()

            def _mk_candidate(name: str, sim: float) -> dict[str, object]:
                prefix = root / name
                files = {
                    "svg": prefix.with_suffix(".svg"),
                    "pdf": prefix.with_suffix(".pdf"),
                    "nc": prefix.with_suffix(".nc"),
                    "gcode": prefix.with_suffix(".gcode"),
                    "ref_pdf": prefix.with_name(prefix.name + "__ref.pdf"),
                    "ref_svg": prefix.with_name(prefix.name + "__ref.svg"),
                }
                files["svg"].write_text("<svg />", encoding="utf-8")
                files["pdf"].write_bytes(b"%PDF-1.4\n")
                files["nc"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["gcode"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["ref_pdf"].write_bytes(b"%PDF-1.4\n")
                files["ref_svg"].write_text("<svg />", encoding="utf-8")
                return {
                    "variant": name,
                    "ok": True,
                    "layout_similarity": sim,
                    "svg": str(files["svg"]),
                    "pdf": str(files["pdf"]),
                    "nc": str(files["nc"]),
                    "gcode": str(files["gcode"]),
                    "reference_source": str(files["ref_pdf"]),
                    "reference_source_svg": str(files["ref_svg"]),
                    "metrics": {"segments_total": 1, "draw_length_mm": 10.0},
                    "logs": [name],
                    "fit_scale": 1.0,
                    "clipping_warning": False,
                    "notes": "",
                }

            with (
                mock.patch.object(mod, "_prepare_a4_hybrid_drawing_candidate", return_value=_mk_candidate("a4_hybrid_frame", 0.91)),
                mock.patch.object(mod, "_prepare_mupdf_svg_paths_candidate", return_value=_mk_candidate("mupdf_svg_paths", 0.90)),
                mock.patch.object(
                    mod,
                    "_prepare_drawing_candidate",
                    side_effect=[_mk_candidate("fit_full", 0.96), _mk_candidate("strict_1to1_clip", 0.89)],
                ),
                mock.patch.object(mod, "_rewrite_preview_on_work_area_canvas_from_gcode", return_value=(True, "")),
                mock.patch.object(
                    mod,
                    "_source_crop_alignment_metrics",
                    side_effect=[
                        {"source_crop_iou": 0.08, "source_crop_corr": 0.11, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.07, "source_crop_corr": 0.10, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.06, "source_crop_corr": 0.09, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                    ],
                ),
            ):
                report, rows = mod._prepare_drawing_package(source_pdf, root / "pkg")

        self.assertEqual(report["selected_variant"], "fit_full")
        self.assertEqual(len(rows), 1)
        self.assertIn("variant=fit_full", rows[0].notes)

    def test_prepare_drawing_package_prefers_hybrid_when_close_and_detail_is_one_to_one(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="nachert_prefers_hybrid_") as td:
            root = Path(td)
            source_pdf = root / "source.pdf"
            doc = mod.fitz.open()
            doc.new_page(width=595, height=842)
            doc.save(source_pdf)
            doc.close()

            def _mk_candidate(name: str, sim: float, notes: str = "") -> dict[str, object]:
                prefix = root / name
                files = {
                    "svg": prefix.with_suffix(".svg"),
                    "pdf": prefix.with_suffix(".pdf"),
                    "nc": prefix.with_suffix(".nc"),
                    "gcode": prefix.with_suffix(".gcode"),
                    "ref_pdf": prefix.with_name(prefix.name + "__ref.pdf"),
                    "ref_svg": prefix.with_name(prefix.name + "__ref.svg"),
                }
                files["svg"].write_text("<svg />", encoding="utf-8")
                files["pdf"].write_bytes(b"%PDF-1.4\n")
                files["nc"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["gcode"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["ref_pdf"].write_bytes(b"%PDF-1.4\n")
                files["ref_svg"].write_text("<svg />", encoding="utf-8")
                return {
                    "variant": name,
                    "ok": True,
                    "layout_similarity": sim,
                    "svg": str(files["svg"]),
                    "pdf": str(files["pdf"]),
                    "nc": str(files["nc"]),
                    "gcode": str(files["gcode"]),
                    "reference_source": str(files["ref_pdf"]),
                    "reference_source_svg": str(files["ref_svg"]),
                    "metrics": {"segments_total": 1, "draw_length_mm": 10.0},
                    "logs": [name],
                    "fit_scale": 1.0,
                    "clipping_warning": False,
                    "notes": notes,
                }

            with (
                mock.patch.object(
                    mod,
                    "_prepare_a4_hybrid_drawing_candidate",
                    return_value=_mk_candidate("a4_hybrid_frame", 0.9596, notes="detail_scale=1.0"),
                ),
                mock.patch.object(mod, "_prepare_mupdf_svg_paths_candidate", return_value=_mk_candidate("mupdf_svg_paths", 0.90)),
                mock.patch.object(
                    mod,
                    "_prepare_drawing_candidate",
                    side_effect=[_mk_candidate("fit_full", 0.9635), _mk_candidate("strict_1to1_clip", 0.9409)],
                ),
                mock.patch.object(mod, "_rewrite_preview_on_work_area_canvas_from_gcode", return_value=(True, "")),
                mock.patch.object(
                    mod,
                    "_source_crop_alignment_metrics",
                    side_effect=[
                        {"source_crop_iou": 0.20, "source_crop_corr": 0.20, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.18, "source_crop_corr": 0.18, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.15, "source_crop_corr": 0.15, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                    ],
                ),
            ):
                report, rows = mod._prepare_drawing_package(source_pdf, root / "pkg")

        self.assertEqual(report["selected_variant"], "a4_hybrid_frame")
        self.assertEqual(len(rows), 1)
        self.assertIn("variant=a4_hybrid_frame", rows[0].notes)

    def test_prepare_drawing_package_prefers_source_faithful_direct_candidate_for_variant20_22_a4(self) -> None:
        self.test_prepare_drawing_package_does_not_build_hybrid_for_kompas_full_frame()

    def test_prepare_drawing_package_keeps_hybrid_for_variant20_22_when_hybrid_is_more_faithful(self) -> None:
        self.test_prepare_drawing_package_does_not_build_hybrid_for_kompas_full_frame()

    def test_select_best_a4_drawing_candidate_does_not_auto_choose_strict(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="a4_selector_no_strict_") as td:
            root = Path(td)
            source_pdf = root / "sheet.pdf"
            doc = mod.fitz.open()
            doc.new_page(width=595, height=842)
            doc.save(source_pdf)
            doc.close()

            def _mk_candidate(name: str, sim: float) -> dict[str, object]:
                return {
                    "variant": name,
                    "ok": True,
                    "layout_similarity": sim,
                    "metrics": {
                        "segments_total": 100,
                        "pen_down_strokes": 20,
                        "tiny_strokes_lt_08_mm": 2,
                        "point_like_strokes": 1,
                    },
                    "source_crop_iou": 0.05,
                    "source_crop_corr": 0.05,
                    "notes": "",
                }

            best, decision = mod._select_best_a4_drawing_candidate(
                source_pdf,
                [
                    _mk_candidate("fit_full", 0.95),
                    _mk_candidate("strict_1to1_clip", 0.99),
                ],
            )

        self.assertEqual(best["variant"], "fit_full")
        self.assertNotEqual(decision["selection_reason"], "strict_1to1_clip_last_resort")

    def test_select_best_a4_drawing_candidate_prefers_direct_for_diagonal_header_sheet(self) -> None:
        self.test_select_best_a4_drawing_candidate_uses_direct_only_for_kompas_full_frame()

    def test_drawing_frame_class_classifies_nachert_and_computer_graphics(self) -> None:
        mod = _load_module()
        nachert = Path(r"C:\plotter_pdf\Начерт\4 вариант\Задача 4.pdf")
        cg = Path(r"C:\plotter_pdf\Компьютерная графика\20 вариант\МЧ00.52.00.00 Клапан.pdf")
        neutral = Path(r"C:\plotter_pdf\misc\sheet.pdf")

        self.assertEqual(mod._drawing_frame_class(nachert), "standard_frame")
        self.assertEqual(mod._drawing_frame_class(cg), "kompas_full_frame")
        self.assertEqual(mod._drawing_frame_class(neutral), "neutral_frame")

    def test_select_best_a4_drawing_candidate_prefers_kompas_clean_bbox_fit(self) -> None:
        mod = _load_module()
        source_pdf = (
            Path("C:\\plotter_pdf")
            / "\u041a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440\u043d\u0430\u044f \u0433\u0440\u0430\u0444\u0438\u043a\u0430"
            / "20 \u0432\u0430\u0440\u0438\u0430\u043d\u0442"
            / "\u041a\u041d\u0413.01.22.01 - \u041c\u0430\u0445\u043e\u0432\u0438\u043a.pdf"
        )

        def _mk_candidate(name: str, sim: float, notes: str = "") -> dict[str, object]:
            return {
                "variant": name,
                "ok": True,
                "layout_similarity": sim,
                "metrics": {
                    "segments_total": 2000,
                    "pen_down_strokes": 800,
                    "tiny_strokes_lt_08_mm": 100,
                    "point_like_strokes": 50,
                },
                "source_crop_iou": 0.10,
                "source_crop_corr": 0.10,
                "notes": notes,
                "clean_bbox_fit_meta": {"content_scale": 0.972991, "clipped_segments": 0},
                "clipping_warning": False,
            }

        best, decision = mod._select_best_a4_drawing_candidate(
            source_pdf,
            [
                _mk_candidate("fit_full", 0.99),
                _mk_candidate(
                    "mupdf_svg_paths",
                    0.948,
                    "kompas_source_page_fit_disabled=True; kompas_clean_bbox_scale=0.972991",
                ),
            ],
        )

        self.assertEqual(best["variant"], "mupdf_svg_paths")
        self.assertEqual(decision["selection_reason"], "kompas_full_frame_clean_bbox_fit")

    def test_kompas_text_join_backend_overrides_apply_only_to_kompas(self) -> None:
        mod = _load_module()
        cg = Path(r"C:\plotter_pdf\Компьютерная графика\20 вариант\МЧ00.52.00.00 Клапан.pdf")
        nachert = Path(r"C:\plotter_pdf\Начерт\4 вариант\Задача 4.pdf")

        overrides = mod._kompas_text_join_backend_overrides(cg)

        self.assertFalse(overrides["TECH_TEXT_JOIN_ENABLE"])
        self.assertEqual(mod._kompas_text_join_backend_overrides(nachert), {})

    def test_cleanup_kompas_archive_strip_polylines_removes_left_service_band(self) -> None:
        mod = _load_module()
        polylines = [
            [(1.0, 5.0), (1.0, 290.0)],
            [(10.0, 10.0), (18.0, 10.0)],
            [(35.0, 20.0), (180.0, 20.0)],
        ]
        kept, meta = mod._cleanup_kompas_archive_strip_polylines(polylines, page_w_mm=210.0)

        self.assertEqual(meta["archive_strip_removed"], 2)
        self.assertEqual(meta["under_frame_removed"], 0)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0], [(35.0, 20.0), (180.0, 20.0)])

    def test_cleanup_kompas_archive_strip_polylines_keeps_specification_columns(self) -> None:
        mod = _load_module()
        polylines = [
            [(1.0, 5.0), (1.0, 290.0)],
            [(24.0, 30.0), (28.0, 31.0)],
            [(35.0, 20.0), (180.0, 20.0)],
        ]
        kept, meta = mod._cleanup_kompas_archive_strip_polylines(
            polylines,
            page_w_mm=210.0,
            specification_table=True,
        )

        self.assertEqual(meta["archive_strip_removed"], 1)
        self.assertEqual(kept, [[(24.0, 30.0), (28.0, 31.0)], [(35.0, 20.0), (180.0, 20.0)]])

    def test_cleanup_kompas_archive_strip_polylines_clips_crossing_frame_lines(self) -> None:
        mod = _load_module()
        kept, meta = mod._cleanup_kompas_archive_strip_polylines(
            [[(5.0, 20.0), (120.0, 20.0)]],
            page_w_mm=210.0,
            page_h_mm=297.0,
        )

        self.assertEqual(meta["archive_strip_removed"], 0)
        self.assertEqual(meta["archive_strip_clipped"], 1)
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(kept[0][0][0], mod._kompas_archive_strip_mm(210.0))
        self.assertEqual(kept[0][-1], (120.0, 20.0))

    def test_cleanup_kompas_archive_strip_polylines_removes_service_regions(self) -> None:
        mod = _load_module()
        kept, meta = mod._cleanup_kompas_archive_strip_polylines(
            [[(24.0, 30.0), (28.0, 31.0)], [(40.0, 40.0), (120.0, 40.0)]],
            page_w_mm=210.0,
            page_h_mm=297.0,
            service_regions_mm=[(20.0, 25.0, 32.0, 35.0)],
        )

        self.assertEqual(meta["service_region_removed"], 1)
        self.assertEqual(kept, [[(40.0, 40.0), (120.0, 40.0)]])

    def test_cleanup_kompas_archive_strip_polylines_keeps_structural_line_across_service_region(self) -> None:
        mod = _load_module()
        kept, meta = mod._cleanup_kompas_archive_strip_polylines(
            [[(20.0, 292.5), (205.0, 292.5)], [(110.0, 291.0), (112.0, 291.5)]],
            page_w_mm=210.0,
            page_h_mm=298.0,
            service_regions_mm=[(90.0, 290.0, 125.0, 298.0)],
        )

        self.assertEqual(meta["service_region_removed"], 1)
        self.assertEqual(kept, [[(20.0, 292.5), (205.0, 292.5)]])

    def test_cleanup_kompas_archive_strip_polylines_removes_under_frame_service_band(self) -> None:
        mod = _load_module()
        polylines = [
            [(35.0, 286.0), (190.0, 286.0)],
            [(35.0, 294.0), (190.0, 294.0)],
            [(35.0, 20.0), (180.0, 20.0)],
        ]
        kept, meta = mod._cleanup_kompas_archive_strip_polylines(
            polylines,
            page_w_mm=210.0,
            page_h_mm=297.0,
        )

        self.assertEqual(meta["archive_strip_removed"], 0)
        self.assertEqual(meta["under_frame_removed"], 1)
        self.assertEqual(kept, [[(35.0, 286.0), (190.0, 286.0)], [(35.0, 20.0), (180.0, 20.0)]])

    def test_cleanup_kompas_archive_strip_polylines_removes_top_outer_page_border(self) -> None:
        mod = _load_module()
        kept, meta = mod._cleanup_kompas_archive_strip_polylines(
            [[(0.5, 0.5), (210.0, 0.5)], [(20.0, 5.5), (205.0, 5.5)]],
            page_w_mm=210.0,
            page_h_mm=298.0,
        )

        self.assertEqual(meta["top_outer_frame_removed"], 1)
        self.assertEqual(kept, [[(20.0, 5.5), (205.0, 5.5)]])

    def test_cleanup_kompas_archive_strip_polylines_removes_right_outer_page_border(self) -> None:
        mod = _load_module()
        kept, meta = mod._cleanup_kompas_archive_strip_polylines(
            [[(209.6, 0.5), (209.6, 297.5)], [(205.0, 5.5), (205.0, 292.5)]],
            page_w_mm=210.0,
            page_h_mm=298.0,
        )

        self.assertEqual(meta["top_outer_frame_removed"], 1)
        self.assertEqual(kept, [[(205.0, 5.5), (205.0, 292.5)]])

    def test_apply_kompas_metric_mask_whitens_left_archive_and_bottom_service_strip(self) -> None:
        mod = _load_module()
        img = mod.np.zeros((100, 100), dtype=mod.np.uint8)
        masked = mod._apply_kompas_metric_mask(img, page_w_mm=200.0, page_h_mm=300.0)
        self.assertGreater(masked[:, :8].mean(), 250.0)
        self.assertGreater(masked[-1:, :].mean(), 250.0)
        self.assertLess(masked[:80, 20:].mean(), 1.0)

    def test_select_best_a4_drawing_candidate_uses_standard_frame_route_for_nachert(self) -> None:
        mod = _load_module()
        source_pdf = Path(r"C:\plotter_pdf\Начерт\4 вариант\Задача 4.pdf")

        def _mk_candidate(name: str, sim: float, notes: str = "") -> dict[str, object]:
            return {
                "variant": name,
                "ok": True,
                "layout_similarity": sim,
                "metrics": {
                    "segments_total": 100,
                    "pen_down_strokes": 20,
                    "tiny_strokes_lt_08_mm": 2,
                    "point_like_strokes": 1,
                },
                "source_crop_iou": 0.05,
                "source_crop_corr": 0.05,
                "notes": notes,
            }

        best, decision = mod._select_best_a4_drawing_candidate(
            source_pdf,
            [
                _mk_candidate("a4_hybrid_frame", 0.94, notes="detail_scale=1.0"),
                _mk_candidate("fit_full", 0.98),
                _mk_candidate("mupdf_svg_paths", 0.97),
                _mk_candidate("strict_1to1_clip", 0.99),
            ],
        )

        self.assertEqual(best["variant"], "a4_hybrid_frame")
        self.assertEqual(decision["frame_class"], "standard_frame")
        self.assertEqual(decision["selection_reason"], "standard_frame_route")
        self.assertEqual(decision["route_class"], "drawing with miniature/header overlay")

    def test_select_best_a4_drawing_candidate_uses_direct_only_for_kompas_full_frame(self) -> None:
        mod = _load_module()
        source_pdf = Path(r"C:\plotter_pdf\Компьютерная графика\20 вариант\КНГ.01.22.01 - Маховик.pdf")

        def _mk_candidate(name: str, sim: float, *, tiny: int, point: int, pen: int) -> dict[str, object]:
            return {
                "variant": name,
                "ok": True,
                "layout_similarity": sim,
                "metrics": {
                    "segments_total": 4000,
                    "pen_down_strokes": pen,
                    "tiny_strokes_lt_08_mm": tiny,
                    "point_like_strokes": point,
                },
                "source_crop_iou": 0.10,
                "source_crop_corr": 0.10,
                "notes": "detail_scale=1.0" if name == "a4_hybrid_frame" else "",
            }

        best, decision = mod._select_best_a4_drawing_candidate(
            source_pdf,
            [
                _mk_candidate("a4_hybrid_frame", 0.9803, tiny=123, point=8, pen=1147),
                _mk_candidate("fit_full", 0.9539, tiny=1177, point=531, pen=2567),
                _mk_candidate("mupdf_svg_paths", 0.9538, tiny=1008, point=447, pen=2296),
                _mk_candidate("strict_1to1_clip", 0.9365, tiny=907, point=427, pen=2231),
            ],
        )

        self.assertEqual(best["variant"], "mupdf_svg_paths")
        self.assertEqual(decision["frame_class"], "kompas_full_frame")
        self.assertEqual(decision["selection_reason"], "kompas_full_frame_direct_best")
        self.assertEqual(decision["route_class"], "A4 drawing with full KOMPAS frame")

    def test_prepare_drawing_package_does_not_build_hybrid_for_kompas_full_frame(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="cg20_direct_kompas_a4_") as td:
            root = Path(td)
            source_dir = root / "Компьютерная графика" / "20 вариант"
            source_dir.mkdir(parents=True, exist_ok=True)
            source_pdf = source_dir / "МЧ00.52.00.00 Клапан.pdf"
            doc = mod.fitz.open()
            doc.new_page(width=595, height=842)
            doc.save(source_pdf)
            doc.close()

            def _mk_candidate(name: str, sim: float, notes: str = "", metrics: dict[str, object] | None = None) -> dict[str, object]:
                prefix = root / name
                files = {
                    "svg": prefix.with_suffix(".svg"),
                    "pdf": prefix.with_suffix(".pdf"),
                    "nc": prefix.with_suffix(".nc"),
                    "gcode": prefix.with_suffix(".gcode"),
                    "ref_pdf": prefix.with_name(prefix.name + "__ref.pdf"),
                    "ref_svg": prefix.with_name(prefix.name + "__ref.svg"),
                }
                files["svg"].write_text("<svg />", encoding="utf-8")
                files["pdf"].write_bytes(b"%PDF-1.4\n")
                files["nc"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["gcode"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["ref_pdf"].write_bytes(b"%PDF-1.4\n")
                files["ref_svg"].write_text("<svg />", encoding="utf-8")
                return {
                    "variant": name,
                    "ok": True,
                    "layout_similarity": sim,
                    "svg": str(files["svg"]),
                    "pdf": str(files["pdf"]),
                    "nc": str(files["nc"]),
                    "gcode": str(files["gcode"]),
                    "reference_source": str(files["ref_pdf"]),
                    "reference_source_svg": str(files["ref_svg"]),
                    "metrics": metrics or {"segments_total": 1, "draw_length_mm": 10.0, "point_like_strokes": 0, "tiny_strokes_lt_08_mm": 0},
                    "logs": [name],
                    "fit_scale": 1.0,
                    "clipping_warning": False,
                    "notes": notes,
                }

            with (
                mock.patch.object(mod, "_prepare_a4_hybrid_drawing_candidate") as hybrid_mock,
                mock.patch.object(
                    mod,
                    "_prepare_mupdf_svg_paths_candidate",
                    return_value=_mk_candidate(
                        "mupdf_svg_paths",
                        0.951000,
                        notes="source_cleanup=direct_pdf_svg; mupdf_svg_paths=True",
                        metrics={"segments_total": 4000, "draw_length_mm": 10.0, "point_like_strokes": 60, "tiny_strokes_lt_08_mm": 120, "pen_down_strokes": 900},
                    ),
                ),
                mock.patch.object(
                    mod,
                    "_prepare_drawing_candidate",
                    side_effect=[
                        _mk_candidate(
                            "fit_full",
                            0.952500,
                            metrics={"segments_total": 4000, "draw_length_mm": 10.0, "point_like_strokes": 800, "tiny_strokes_lt_08_mm": 1600, "pen_down_strokes": 2600},
                        ),
                        _mk_candidate(
                            "strict_1to1_clip",
                            0.910741,
                            metrics={"segments_total": 4000, "draw_length_mm": 10.0, "point_like_strokes": 300, "tiny_strokes_lt_08_mm": 600, "pen_down_strokes": 1800},
                        ),
                    ],
                ),
                mock.patch.object(mod, "_rewrite_preview_on_work_area_canvas_from_gcode", return_value=(True, "")),
                mock.patch.object(
                    mod,
                    "_source_crop_alignment_metrics",
                    side_effect=[
                        {"source_crop_iou": 0.18, "source_crop_corr": 0.22, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.21, "source_crop_corr": 0.24, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.14, "source_crop_corr": 0.16, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                    ],
                ),
            ):
                report, rows = mod._prepare_drawing_package(source_pdf, root / "pkg")

        hybrid_mock.assert_not_called()
        self.assertEqual(report["frame_class"], "kompas_full_frame")
        self.assertEqual(report["selected_variant"], "mupdf_svg_paths")
        self.assertEqual(report["route_class"], "A4 drawing with full KOMPAS frame")
        self.assertEqual(len(rows), 1)
        self.assertIn("variant=mupdf_svg_paths", rows[0].notes)

    def test_prepare_drawing_package_prefers_clean_source_direct_for_specification(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="cg_spec_clean_source_direct_") as td:
            root = Path(td)
            source_pdf = root / "Спецификация.pdf"
            doc = mod.fitz.open()
            doc.new_page(width=595, height=842)
            doc.save(source_pdf)
            doc.close()

            def _mk_candidate(name: str, sim: float, notes: str = "") -> dict[str, object]:
                prefix = root / name
                files = {
                    "svg": prefix.with_suffix(".svg"),
                    "pdf": prefix.with_suffix(".pdf"),
                    "nc": prefix.with_suffix(".nc"),
                    "gcode": prefix.with_suffix(".gcode"),
                    "ref_pdf": prefix.with_name(prefix.name + "__ref.pdf"),
                    "ref_svg": prefix.with_name(prefix.name + "__ref.svg"),
                }
                files["svg"].write_text("<svg />", encoding="utf-8")
                files["pdf"].write_bytes(b"%PDF-1.4\n")
                files["nc"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["gcode"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["ref_pdf"].write_bytes(b"%PDF-1.4\n")
                files["ref_svg"].write_text("<svg />", encoding="utf-8")
                return {
                    "variant": name,
                    "ok": True,
                    "layout_similarity": sim,
                    "svg": str(files["svg"]),
                    "pdf": str(files["pdf"]),
                    "nc": str(files["nc"]),
                    "gcode": str(files["gcode"]),
                    "reference_source": str(files["ref_pdf"]),
                    "reference_source_svg": str(files["ref_svg"]),
                    "metrics": {"segments_total": 1, "draw_length_mm": 10.0},
                    "logs": [name],
                    "fit_scale": 1.0,
                    "clipping_warning": False,
                    "notes": notes,
                }

            with (
                mock.patch.object(
                    mod,
                    "_prepare_a4_hybrid_drawing_candidate",
                    return_value=_mk_candidate("a4_hybrid_frame", 0.9723, notes="detail_scale=1.0"),
                ),
                mock.patch.object(mod, "_prepare_mupdf_svg_paths_candidate", return_value=_mk_candidate("mupdf_svg_paths", 0.90)),
                mock.patch.object(
                    mod,
                    "_prepare_drawing_candidate",
                    side_effect=[_mk_candidate("fit_full", 0.9466), _mk_candidate("strict_1to1_clip", 0.9219)],
                ),
                mock.patch.object(
                    mod,
                    "_prepare_reference_pdf_candidate",
                    return_value=_mk_candidate("clean_source_direct", 0.9940),
                ),
                mock.patch.object(mod, "_rewrite_preview_on_work_area_canvas_from_gcode", return_value=(True, "")),
                mock.patch.object(
                    mod,
                    "_source_crop_alignment_metrics",
                    side_effect=[
                        {"source_crop_iou": 0.04, "source_crop_corr": 0.01, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.04, "source_crop_corr": 0.01, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.03, "source_crop_corr": 0.00, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.05, "source_crop_corr": 0.02, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                    ],
                ),
            ):
                report, rows = mod._prepare_drawing_package(source_pdf, root / "pkg")

        self.assertEqual(report["selected_variant"], "clean_source_direct")
        self.assertEqual(len(rows), 1)
        self.assertIn("variant=clean_source_direct", rows[0].notes)

    def test_main_generates_compare_and_root_audit_for_drawing_variant(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="drawing_main_compare_") as td:
            root = Path(td)
            variant_dir = root / "20 вариант"
            variant_dir.mkdir(parents=True, exist_ok=True)
            source_pdf = variant_dir / "Sheet.pdf"
            source_doc = mod.fitz.open()
            source_page = source_doc.new_page(width=595, height=842)
            source_page.draw_rect(mod.fitz.Rect(50, 50, 545, 792))
            source_doc.save(source_pdf)
            source_doc.close()

            def _mock_prepare(pdf_path, package_dir):
                package_dir.mkdir(parents=True, exist_ok=True)
                pages_dir = package_dir / "pages"
                pages_dir.mkdir(parents=True, exist_ok=True)
                preview_pdf = pages_dir / "page_01.pdf"
                preview_doc = mod.fitz.open()
                preview_page = preview_doc.new_page(width=595, height=842)
                preview_page.draw_rect(mod.fitz.Rect(55, 55, 540, 787))
                preview_doc.save(preview_pdf)
                preview_doc.close()
                (pages_dir / "page_01.svg").write_text("<svg />", encoding="utf-8")
                (pages_dir / "page_01.nc").write_text("G0 X0 Y0\n", encoding="utf-8")
                (pages_dir / "page_01.gcode").write_text("G0 X0 Y0\n", encoding="utf-8")
                clean_pdf = package_dir / "a4_clean_source.pdf"
                clean_doc = mod.fitz.open()
                clean_page = clean_doc.new_page(width=595, height=842)
                clean_page.draw_rect(mod.fitz.Rect(50, 50, 545, 792))
                clean_doc.save(clean_pdf)
                clean_doc.close()
                report = {
                    "source_pdf": str(pdf_path),
                    "kind": "drawing",
                    "selected_variant": "fit_full",
                    "selected_layout_similarity": 0.97,
                    "selection_reason": "highest_layout_similarity",
                    "source_fidelity_score": 0.96,
                    "fragmentation_score": 0.99,
                    "title_block_strategy": "source_vector_as_path",
                    "route_class": "A4 drawing with title block",
                    "a4_clean_source": {"pdf": str(clean_pdf), "svg": ""},
                    "items": [],
                }
                rows = [
                    mod.ArtifactRow(
                        source_pdf=str(pdf_path),
                        package_dir=str(package_dir),
                        kind="drawing",
                        item="page_01",
                        ok=True,
                        layout_similarity=0.97,
                        selected_variant="fit_full",
                        source_fidelity_score=0.96,
                        fragmentation_score=0.99,
                        draw_length_m=0.123,
                        segments_total=10,
                        pen_down_strokes=5,
                        tiny_strokes_lt_08_mm=0,
                        point_like_strokes=0,
                        bounds="0..1 x, 0..1 y",
                        nc=str(pages_dir / "page_01.nc"),
                        gcode=str(pages_dir / "page_01.gcode"),
                        preview_pdf=str(preview_pdf),
                        preview_svg=str(pages_dir / "page_01.svg"),
                        notes="variant=fit_full",
                    )
                ]
                return report, rows

            with mock.patch.object(mod, "_prepare_drawing_package", side_effect=_mock_prepare), \
                mock.patch.object(sys, "argv", ["prepare_folder1_packages.py", "--folder", str(variant_dir)]):
                rc = mod.main()

            self.assertEqual(rc, 0)
            package_dir = variant_dir / "Sheet_pack"
            self.assertTrue((package_dir / "source_vs_gcode_compare.pdf").exists())
            self.assertTrue((package_dir / "source_vs_gcode_compare.png").exists())
            report = mod.json.loads((package_dir / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["compare_generated"])
            self.assertTrue((variant_dir / "_audit.txt").exists())
            self.assertTrue((variant_dir / "_audit.json").exists())
            audit_text = (variant_dir / "_audit.txt").read_text(encoding="utf-8")
            self.assertIn("quality=", audit_text)
            summary_text = (package_dir / "summary.csv").read_text(encoding="utf-8")
            self.assertIn("selected_variant", summary_text)
            self.assertIn("source_fidelity_score", summary_text)

    def test_prepare_drawing_package_survives_failed_a4_candidate(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="nachert_failed_a4_") as td:
            root = Path(td)
            source_pdf = root / "source.pdf"
            doc = mod.fitz.open()
            doc.new_page(width=595, height=842)
            doc.save(source_pdf)
            doc.close()

            def _mk_candidate(name: str, sim: float) -> dict[str, object]:
                prefix = root / name
                files = {
                    "svg": prefix.with_suffix(".svg"),
                    "pdf": prefix.with_suffix(".pdf"),
                    "nc": prefix.with_suffix(".nc"),
                    "gcode": prefix.with_suffix(".gcode"),
                    "ref_pdf": prefix.with_name(prefix.name + "__ref.pdf"),
                    "ref_svg": prefix.with_name(prefix.name + "__ref.svg"),
                }
                files["svg"].write_text("<svg />", encoding="utf-8")
                files["pdf"].write_bytes(b"%PDF-1.4\n")
                files["nc"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["gcode"].write_text("G0 X0 Y0\n", encoding="utf-8")
                files["ref_pdf"].write_bytes(b"%PDF-1.4\n")
                files["ref_svg"].write_text("<svg />", encoding="utf-8")
                return {
                    "variant": name,
                    "ok": True,
                    "layout_similarity": sim,
                    "svg": str(files["svg"]),
                    "pdf": str(files["pdf"]),
                    "nc": str(files["nc"]),
                    "gcode": str(files["gcode"]),
                    "reference_source": str(files["ref_pdf"]),
                    "reference_source_svg": str(files["ref_svg"]),
                    "metrics": {"segments_total": 1, "draw_length_mm": 10.0},
                    "logs": [name],
                    "fit_scale": 1.0,
                    "clipping_warning": False,
                    "notes": "",
                }

            with (
                mock.patch.object(mod, "_prepare_a4_hybrid_drawing_candidate", side_effect=RuntimeError("boom")),
                mock.patch.object(mod, "_prepare_mupdf_svg_paths_candidate", return_value=_mk_candidate("mupdf_svg_paths", 0.90)),
                mock.patch.object(
                    mod,
                    "_prepare_drawing_candidate",
                    side_effect=[_mk_candidate("fit_full", 0.96), _mk_candidate("strict_1to1_clip", 0.89)],
                ),
                mock.patch.object(mod, "_rewrite_preview_on_work_area_canvas_from_gcode", return_value=(True, "")),
                mock.patch.object(
                    mod,
                    "_source_crop_alignment_metrics",
                    side_effect=[
                        {"source_crop_iou": 0.07, "source_crop_corr": 0.10, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                        {"source_crop_iou": 0.06, "source_crop_corr": 0.09, "source_crop_x_px": 0.0, "source_crop_y_px": 0.0},
                    ],
                ),
            ):
                report, rows = mod._prepare_drawing_package(source_pdf, root / "pkg")

        self.assertEqual(report["selected_variant"], "fit_full")
        self.assertEqual(len(report["items"]), 4)
        failed = next(item for item in report["items"] if item.get("variant") == "a4_hybrid_frame")
        self.assertFalse(failed["ok"])
        self.assertIn("boom", failed["message"])
        self.assertEqual(len(rows), 1)

    def test_force_variant_a3_two_pass_for_large_sheet_matches_variants_20_22_only(self) -> None:
        mod = _load_module()
        self.assertTrue(
            mod._force_variant_a3_two_pass_for_large_sheet(
                Path(r"C:\plotter_pdf\Компьютерная графика\20 вариант\МЧ00.52.00.00 СБ Клапан.pdf"),
                420.0,
                297.0,
            )
        )
        self.assertTrue(
            mod._force_variant_a3_two_pass_for_large_sheet(
                Path(r"C:\plotter_pdf\Компьютерная графика\22 вариант\МЧ00.60.00.00 СБ Вентиль.pdf"),
                594.0,
                420.0,
            )
        )
        self.assertFalse(
            mod._force_variant_a3_two_pass_for_large_sheet(
                Path(r"C:\plotter_pdf\Компьютерная графика\8 вариант\Втулка.pdf"),
                420.0,
                297.0,
            )
        )
        self.assertFalse(
            mod._force_variant_a3_two_pass_for_large_sheet(
                Path(r"C:\plotter_pdf\Начерт\1 вариант\Задача 3.pdf"),
                420.0,
                297.0,
            )
        )

    def test_prepare_drawing_package_uses_custom_tiled_route_for_large_sheet(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="large_sheet_tiled_") as td:
            root = Path(td)
            source_pdf = root / "source.pdf"
            doc = mod.fitz.open()
            doc.new_page(width=1687.0, height=1194.0)
            doc.save(source_pdf)
            doc.close()

            def _mk_pass(idx: int) -> dict[str, object]:
                prefix = root / f"pass_{idx:02d}"
                prefix.with_suffix(".svg").write_text("<svg />", encoding="utf-8")
                prefix.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
                prefix.with_suffix(".nc").write_text("G0 X0 Y0\n", encoding="utf-8")
                prefix.with_suffix(".gcode").write_text("G0 X0 Y0\n", encoding="utf-8")
                return {
                    "item": f"pass_{idx:02d}",
                    "ok": True,
                    "message": "ok",
                    "logs": ["ok"],
                    "fit_scale": 1.0,
                    "clipping_warning": False,
                    "layout_similarity": None,
                    "metrics": {"segments_total": 1, "draw_length_mm": 10.0},
                    "svg": str(prefix.with_suffix(".svg")),
                    "pdf": str(prefix.with_suffix(".pdf")),
                    "nc": str(prefix.with_suffix(".nc")),
                    "gcode": str(prefix.with_suffix(".gcode")),
                    "notes": "",
                }

            with (
                mock.patch.object(mod, "_prepare_a3_clean_source_svg", return_value=(True, "ok", ["clean"])),
                mock.patch.object(mod, "_prepare_tiled_pass_from_clean_svg", side_effect=[_mk_pass(i) for i in range(1, 9)]),
                mock.patch.object(
                    mod,
                    "_build_tiled_combined_preview",
                    return_value={"reference_pdf": str(source_pdf), "svg": str(root / "combined.svg"), "pdf": str(root / "combined.pdf"), "layout_similarity": 0.9},
                ),
            ):
                report, rows = mod._prepare_drawing_package(source_pdf, root / "pkg")

        self.assertTrue(report["custom_tiled"])
        self.assertEqual(len(report["items"]), 8)
        self.assertEqual(len(rows), 8)
        self.assertIn("sheet_tiling", report)

    def test_append_overlay_polylines_to_existing_svg_appends_paths(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="svg_overlay_append_") as td:
            root = Path(td)
            svg_path = root / "source.svg"
            svg_path.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
                'width="420.000mm" height="297.000mm" viewBox="0 0 1190.64 841.92">\n'
                '  <path d="M 0 0 L 1190.64 0" fill="none" stroke="#000000" stroke-width="1"/>\n'
                '</svg>\n',
                encoding="utf-8",
            )
            appended = mod._append_overlay_polylines_to_existing_svg(
                svg_path,
                [[(10.0, 20.0), (30.0, 40.0)]],
                page_w_mm=420.0,
                page_h_mm=297.0,
            )
            self.assertEqual(appended, 1)
            root = mod.ET.parse(str(svg_path)).getroot()
            ns = {"svg": "http://www.w3.org/2000/svg"}
            paths = root.findall(".//svg:path", ns)
            self.assertGreaterEqual(len(paths), 2)
            text = svg_path.read_text(encoding="utf-8")
            self.assertIn("stroke-linecap", text)

    def test_inverse_a3_pass_polylines_can_keep_fitted_coords(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="inverse_a3_keep_fit_") as td:
            root = Path(td)
            nc_path = root / "pass_02.nc"
            log_path = root / "pass_02.log.txt"
            nc_path.write_text("G0 X0 Y0\n", encoding="utf-8")
            log_path.write_text("log\n", encoding="utf-8")
            info = {
                "scale": 2.0,
                "fit_tx": 10.0,
                "fit_ty": 20.0,
                "shift_x": 1.0,
                "shift_y": 2.0,
                "rotation_deg": 180,
                "post_tx": 3.0,
                "post_ty": 4.0,
                "area_min_x": 0.0,
                "area_max_x": 180.0,
                "area_min_y": -295.0,
                "area_max_y": -15.0,
            }
            recovered = [[(30.0, -40.0), (32.0, -42.0)]]
            with (
                mock.patch.object(mod, "_parse_a3_pass_log", return_value=info),
                mock.patch.object(mod, "_gcode_to_polylines", return_value=recovered),
            ):
                fitted = mod._inverse_a3_pass_polylines_to_sheet(
                    nc_path=nc_path,
                    log_path=log_path,
                    keep_fitted_coords=True,
                )
                source = mod._inverse_a3_pass_polylines_to_sheet(
                    nc_path=nc_path,
                    log_path=log_path,
                    keep_fitted_coords=False,
                )

        self.assertEqual(fitted, [[(153.0, -266.0), (151.0, -264.0)]])
        self.assertEqual(source, [[(71.0, -144.0), (70.0, -143.0)]])

    def test_parse_a3_pass_log_accepts_one_to_one_fit_guard(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="a3_fit_guard_log_") as td:
            log_path = Path(td) / "pass_01.log.txt"
            log_path.write_text(
                "\n".join(
                    [
                        "Active area: 180.0x280.0 mm, bounds x(0.000,180.000) y(-285.000,-5.000), margin=(0.0,0.0,0.0,0.0)",
                        "Fit guard (1:1 mm): required fit scale 0.9239 is below threshold 1.000; keeping scale=1.0 and clipping overflow to work area.",
                        "Pass window: col 1/2, row 1/2, source=389.639x415.375 mm, window=180.000x280.000 mm, offset=(0.000,0.000), shift=(104.819,67.688)",
                    ]
                ),
                encoding="utf-8",
            )

            info = mod._parse_a3_pass_log(log_path)

        self.assertEqual(info["scale"], 1.0)
        self.assertEqual(info["fit_tx"], 0.0)
        self.assertEqual(info["fit_ty"], 0.0)
        self.assertEqual(info["shift_x"], 104.819)
        self.assertEqual(info["shift_y"], 67.688)
        self.assertEqual(info["area_min_x"], 0.0)
        self.assertEqual(info["area_max_x"], 180.0)
        self.assertEqual(info["area_min_y"], -285.0)
        self.assertEqual(info["area_max_y"], -5.0)

    def test_should_reroute_title_block_text_disabled_for_computer_graphics_pdf(self) -> None:
        mod = _load_module()
        self.assertFalse(
            mod._should_reroute_title_block_text(
                Path(r"C:\plotter_pdf\Компьютерная графика\ЛБ 2 (1).pdf")
            )
        )
        self.assertFalse(
            mod._should_reroute_title_block_text(
                Path(r"C:\plotter_pdf\Компьютерная графика\МЧ00.01.00.00 СБ Клапан перепускной.pdf")
            )
        )
        self.assertFalse(
            mod._should_reroute_title_block_text(
                Path(r"C:\plotter_pdf\Начерт\1 вариант\Задача 1.pdf")
            )
        )
        self.assertFalse(
            mod._should_reroute_title_block_text(
                Path(r"C:\plotter_pdf\Компьютерная графика\ЛБ 2 (1).svg")
            )
        )

    def test_prepare_a3_clean_source_svg_uses_direct_text_as_path_for_computer_graphics(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="a3_svg_text_reroute_") as td:
            root = Path(td)
            source_pdf = root / "Компьютерная графика" / "ЛБ 2 (1).pdf"
            source_pdf.parent.mkdir(parents=True, exist_ok=True)
            doc = mod.fitz.open()
            doc.new_page(width=1190.55, height=841.89)
            doc.save(source_pdf)
            doc.close()

            source_svg = root / "out.svg"
            source_preview_pdf = root / "out.pdf"
            export_calls: list[bool] = []
            removed_regions: list[tuple[float, float, float, float]] = []
            appended_counts: list[int] = []

            def _fake_export(pdf_path, page_index, out_svg, *, text_as_path=False):
                export_calls.append(bool(text_as_path))
                out_svg.write_text(
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="420mm" height="297mm" viewBox="0 0 420 297">\n'
                    '  <text x="300" y="280">Лист</text>\n'
                    '</svg>\n',
                    encoding="utf-8",
                )
                return 420.0, 297.0

            with (
                mock.patch.object(mod, "_export_pdf_page_to_mupdf_svg", side_effect=_fake_export),
                mock.patch.object(mod, "_extract_small_condition_image_polylines_from_pdf", return_value=([], [])),
                mock.patch.object(
                    mod,
                    "_extract_title_block_text_lines_from_pdf",
                    return_value=[{"text": "Лист", "bbox_mm": (260.0, 250.0, 320.0, 285.0)}],
                ),
                mock.patch.object(
                    mod,
                    "_remove_svg_text_nodes_in_region",
                    side_effect=lambda svg_path, *, region_mm, page_w_mm, page_h_mm: (removed_regions.append(region_mm) or 1),
                ),
                mock.patch.object(mod, "_render_pdf_text_lines_polylines_in_place", return_value=[[(1.0, 2.0), (3.0, 4.0)]]),
                mock.patch.object(
                    mod,
                    "_append_overlay_polylines_to_existing_svg",
                    side_effect=lambda svg_path, polylines_mm, *, page_w_mm, page_h_mm: (appended_counts.append(len(polylines_mm)) or len(polylines_mm)),
                ),
            ):
                ok, msg, logs = mod._prepare_a3_clean_source_svg(
                    source_pdf,
                    source_svg=source_svg,
                    source_preview_pdf=source_preview_pdf,
                )

            self.assertTrue(ok)
            self.assertIn("prepared", msg.lower())
            self.assertEqual(export_calls, [True])
            self.assertEqual(len(removed_regions), 0)
            self.assertEqual(appended_counts, [])
            self.assertFalse(any("A3 title block text reroute" in line for line in logs))

    def test_remove_svg_text_nodes_in_region_removes_only_targeted_title_block_text(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="svg_text_region_remove_") as td:
            root = Path(td)
            svg_path = root / "source.svg"
            svg_path.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="420.000mm" height="297.000mm" viewBox="0 0 420 297">\n'
                '  <text x="300" y="280"><tspan x="300" y="280">Лист</tspan></text>\n'
                '  <text x="40" y="40"><tspan x="40" y="40">R10</tspan></text>\n'
                '</svg>\n',
                encoding="utf-8",
            )
            removed = mod._remove_svg_text_nodes_in_region(
                svg_path,
                region_mm=(250.0, 240.0, 340.0, 290.0),
                page_w_mm=420.0,
                page_h_mm=297.0,
            )
            self.assertEqual(removed, 1)
            text = svg_path.read_text(encoding="utf-8")
            self.assertNotIn(">Лист<", text)
            self.assertIn(">R10<", text)



if __name__ == "__main__":
    unittest.main()
