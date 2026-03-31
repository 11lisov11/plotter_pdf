from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2  # type: ignore
import fitz  # type: ignore
import numpy as np  # type: ignore


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "prepare_toe_handwriting_package.py"
    spec = importlib.util.spec_from_file_location("prepare_toe_handwriting_package", str(script_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrepareToeHandwritingPackageModuleTests(unittest.TestCase):
    def test_filter_candidate_fonts_defaults_to_marck_script(self) -> None:
        mod = _load_module()
        fonts = [
            ("Neucha", Path("neucha.ttf")),
            ("Marck Script", Path("marck.ttf")),
            ("Bad Script", Path("bad.ttf")),
        ]
        filtered = mod._filter_candidate_fonts(fonts, [])
        self.assertEqual(filtered, [("Marck Script", Path("marck.ttf"))])

    def test_filter_candidate_fonts_keeps_requested_labels(self) -> None:
        mod = _load_module()
        fonts = [
            ("Neucha", Path("neucha.ttf")),
            ("Marck Script", Path("marck.ttf")),
        ]
        filtered = mod._filter_candidate_fonts(fonts, ["Neucha"])
        self.assertEqual(filtered, [("Neucha", Path("neucha.ttf"))])

    def test_source_page_visual_profile_marks_image_heavy_svg(self) -> None:
        mod = _load_module()
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm">
  <image x="0" y="0" width="10" height="10" href="data:image/png;base64,AA==" />
  <image x="0" y="0" width="10" height="10" href="data:image/png;base64,AA==" />
  <image x="0" y="0" width="10" height="10" href="data:image/png;base64,AA==" />
  <image x="0" y="0" width="10" height="10" href="data:image/png;base64,AA==" />
  <text x="1" y="2">A</text>
  <path d="M 0 0 L 10 0" />
</svg>
"""
        with tempfile.TemporaryDirectory(prefix="toe_profile_") as td:
            path = Path(td) / "page.svg"
            path.write_text(svg, encoding="utf-8")
            profile = mod._source_page_visual_profile(path)
        self.assertEqual(profile["image_count"], 4)
        self.assertEqual(profile["text_count"], 1)
        self.assertEqual(profile["path_count"], 1)
        self.assertTrue(profile["image_heavy"])

    def test_source_profile_prefers_font_first_for_text_rich_page(self) -> None:
        mod = _load_module()
        self.assertTrue(
            mod._source_profile_prefers_font_first(
                {"text_count": 128, "image_count": 1, "path_count": 359}
            )
        )
        self.assertFalse(
            mod._source_profile_prefers_font_first(
                {"text_count": 12, "image_count": 3, "path_count": 25}
            )
        )

    def test_source_profile_strategy_and_threshold_follow_text_rich_rule(self) -> None:
        mod = _load_module()
        profile = {"text_count": 128, "image_count": 1, "path_count": 359}
        self.assertEqual(mod._source_profile_strategy(profile), "font_first_text_rich")
        self.assertEqual(
            mod._fallback_threshold_for_source_profile(profile),
            mod.TEXT_RICH_FONT_FIRST_FALLBACK_THRESHOLD,
        )

    def test_source_profile_strategy_marks_graph_lineart_profile(self) -> None:
        mod = _load_module()
        profile = {"text_count": 18, "image_count": 8, "path_count": 120}
        self.assertEqual(mod._source_profile_strategy(profile), "graph_lineart")

    def test_pdf_page_ink_ratio_detects_blank_page(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_blank_ratio_") as td:
            blank_pdf = Path(td) / "blank.pdf"
            text_pdf = Path(td) / "text.pdf"
            doc = fitz.open()
            doc.new_page(width=595, height=842)
            doc.save(blank_pdf)
            doc.close()

            doc = fitz.open()
            page = doc.new_page(width=595, height=842)
            page.insert_text((72, 72), "test", fontsize=12)
            doc.save(text_pdf)
            doc.close()

            blank_ratio = mod._pdf_page_ink_ratio(blank_pdf, 1)
            text_ratio = mod._pdf_page_ink_ratio(text_pdf, 1)
        self.assertLess(blank_ratio, mod.BLANK_PAGE_INK_RATIO_MAX)
        self.assertGreater(text_ratio, blank_ratio)

    def test_candidate_score_penalizes_low_iou_on_image_heavy_pages(self) -> None:
        mod = _load_module()
        base = {
            "layout_similarity": 0.95,
            "quality_metrics": {
                "segments_duplicate_ratio": 0.0,
                "segments_tiny_ratio": 0.0,
                "segments_short_ratio": 0.0,
            },
            "source_image_count": 8,
        }
        low_iou = dict(base)
        low_iou["overlay_metrics"] = {"mask_iou": 0.04}
        high_iou = dict(base)
        high_iou["overlay_metrics"] = {"mask_iou": 0.28}
        self.assertGreater(mod._candidate_score(high_iou), mod._candidate_score(low_iou))

    def test_quality_gate_rejects_low_iou_for_image_heavy_page(self) -> None:
        mod = _load_module()
        row = {
            "source_image_count": 6,
            "overlay_metrics": {"mask_iou": 0.03},
            "quality_metrics": {
                "segments_duplicate_ratio": 0.0,
                "segments_tiny_ratio": 0.0,
            },
        }
        gate = mod._quality_gate(row, max_duplicate_ratio=0.002, max_tiny_ratio=0.015)
        self.assertFalse(gate["mask_iou_ok"])
        self.assertFalse(gate["accepted"])

    def test_prefers_raster_safe_for_formula_like_overtraced_page(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.955874,
            "score": 1.195892,
            "overlay_metrics": {"mask_iou": 0.177374, "mask_recall": 0.364116},
            "quality_metrics": {"segments_total": 11637, "draw_length_mm": 9534.5},
        }
        fallback = {
            "ok": True,
            "variant_label": "raster_safe",
            "layout_similarity": 0.955081,
            "score": 0.949151,
            "overlay_metrics": {"mask_iou": 0.057842, "mask_recall": 0.087541},
            "quality_metrics": {"segments_total": 3510, "draw_length_mm": 2215.7},
        }
        self.assertTrue(
            mod._should_prefer_image_heavy_fallback(
                selected=selected,
                fallback=fallback,
                source_profile={"image_heavy": True, "image_count": 40},
            )
        )

    def test_prefers_raster_safe_for_graph_page_with_better_similarity_and_iou(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.968705,
            "score": 1.238723,
            "overlay_metrics": {"mask_iou": 0.264174, "mask_recall": 0.381064},
            "quality_metrics": {"segments_total": 9639, "draw_length_mm": 5696.9},
        }
        fallback = {
            "ok": True,
            "variant_label": "raster_safe",
            "layout_similarity": 0.973600,
            "score": 1.230768,
            "overlay_metrics": {"mask_iou": 0.308928, "mask_recall": 0.398502},
            "quality_metrics": {"segments_total": 14531, "draw_length_mm": 6256.0},
        }
        self.assertTrue(
            mod._should_prefer_image_heavy_fallback(
                selected=selected,
                fallback=fallback,
                source_profile={"image_heavy": True, "image_count": 17},
            )
        )

    def test_prefers_raster_safe_for_graph_page_with_small_iou_loss_but_better_similarity(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.962955,
            "score": 1.240000,
            "overlay_metrics": {"mask_iou": 0.312000, "mask_recall": 0.390000},
            "quality_metrics": {"segments_total": 6200, "draw_length_mm": 4100.0},
        }
        fallback = {
            "ok": True,
            "variant_label": "raster_safe",
            "layout_similarity": 0.969125,
            "score": 1.220000,
            "overlay_metrics": {"mask_iou": 0.297000, "mask_recall": 0.402000},
            "quality_metrics": {"segments_total": 9100, "draw_length_mm": 4600.0},
        }
        self.assertTrue(
            mod._should_prefer_image_heavy_fallback(
                selected=selected,
                fallback=fallback,
                source_profile={"image_heavy": True, "image_count": 13},
            )
        )

    def test_keeps_handwriting_when_fallback_is_clearly_worse(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.968183,
            "score": 1.26759,
            "overlay_metrics": {"mask_iou": 0.326358, "mask_recall": 0.395187},
            "quality_metrics": {"segments_total": 7090, "draw_length_mm": 4805.0},
        }
        fallback = {
            "ok": True,
            "variant_label": "raster_safe",
            "layout_similarity": 0.950584,
            "score": 0.962852,
            "overlay_metrics": {"mask_iou": 0.071587, "mask_recall": 0.098977},
            "quality_metrics": {"segments_total": 2500, "draw_length_mm": 1900.0},
        }
        self.assertFalse(
            mod._should_prefer_image_heavy_fallback(
                selected=selected,
                fallback=fallback,
                source_profile={"image_heavy": True, "image_count": 13},
            )
        )

    def test_prefers_low_similarity_fallback_when_it_improves_page(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.931226,
            "overlay_metrics": {"mask_iou": 0.163448},
        }
        fallback = {
            "ok": True,
            "variant_label": "raster_safe",
            "layout_similarity": 0.945820,
            "overlay_metrics": {"mask_iou": 0.150000},
        }
        self.assertTrue(
            mod._should_prefer_low_similarity_fallback(
                selected=selected,
                fallback=fallback,
            )
        )

    def test_rejects_low_similarity_fallback_when_iou_drop_is_too_large(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.931226,
            "overlay_metrics": {"mask_iou": 0.163448},
        }
        fallback = {
            "ok": True,
            "variant_label": "raster_safe",
            "layout_similarity": 0.945820,
            "overlay_metrics": {"mask_iou": 0.120000},
        }
        self.assertFalse(
            mod._should_prefer_low_similarity_fallback(
                selected=selected,
                fallback=fallback,
            )
        )

    def test_prefers_lineart_rescue_for_small_but_real_gain(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.935857,
            "overlay_metrics": {"mask_iou": 0.310769},
        }
        rescue = {
            "ok": True,
            "variant_label": "lineart_safe",
            "layout_similarity": 0.935996,
            "overlay_metrics": {"mask_iou": 0.311513},
        }
        self.assertTrue(
            mod._should_prefer_lineart_rescue(
                selected=selected,
                rescue=rescue,
            )
        )

    def test_prefers_graph_rescue_for_small_gain_and_small_iou_drop(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.970800,
            "overlay_metrics": {"mask_iou": 0.281000},
        }
        rescue = {
            "ok": True,
            "variant_label": "graph_safe",
            "layout_similarity": 0.971100,
            "overlay_metrics": {"mask_iou": 0.270000},
        }
        self.assertTrue(
            mod._should_prefer_graph_rescue(
                selected=selected,
                rescue=rescue,
            )
        )

    def test_region_boxes_from_candidate_overlays_detects_improved_tile(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_region_boxes_") as td:
            root = Path(td)
            selected_png = root / "selected.png"
            rescue_png = root / "rescue.png"
            selected = np.full((120, 120, 3), 255, dtype=np.uint8)
            rescue = np.full((120, 120, 3), 255, dtype=np.uint8)
            selected[30:60, 40:80] = (220, 40, 40)
            rescue[30:60, 40:80] = (35, 35, 35)
            cv2.imwrite(str(selected_png), selected)
            cv2.imwrite(str(rescue_png), rescue)
            boxes = mod._region_boxes_from_candidate_overlays(
                selected_overlay_png=selected_png,
                rescue_overlay_png=rescue_png,
            )
        self.assertEqual(len(boxes), 1)
        x0, x1, y0, y1 = boxes[0]
        self.assertLess(x0, 0.5)
        self.assertGreater(x1, 0.5)
        self.assertLess(y0, 0.5)
        self.assertGreater(y1, 0.25)

    def test_normalized_boxes_to_poly_regions_maps_into_page_bounds(self) -> None:
        mod = _load_module()
        regions = mod._normalized_boxes_to_poly_regions(
            [(1.0 / 3.0, 2.0 / 3.0, 0.25, 0.50)],
            content_bounds=(10.0, 110.0, -200.0, -20.0),
        )
        self.assertEqual(len(regions), 1)
        x0, x1, y0, y1 = regions[0]
        self.assertGreaterEqual(x0, 10.0)
        self.assertLessEqual(x1, 110.0)
        self.assertGreaterEqual(y0, -200.0)
        self.assertLessEqual(y1, -20.0)
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)

    def test_prefers_region_rescue_for_small_gain_and_small_iou_drop(self) -> None:
        mod = _load_module()
        selected = {
            "variant_label": "always",
            "layout_similarity": 0.958200,
            "overlay_metrics": {"mask_iou": 0.292000},
        }
        rescue = {
            "ok": True,
            "variant_label": "region_safe",
            "layout_similarity": 0.958500,
            "overlay_metrics": {"mask_iou": 0.285000},
        }
        self.assertTrue(
            mod._should_prefer_region_rescue(
                selected=selected,
                rescue=rescue,
            )
        )

    def test_build_lineart_rescue_candidate_passes_backend_overrides(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_lineart_rescue_") as td:
            root = Path(td)
            source_pdf = root / "src.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")
            page_svg = root / "page_01.svg"
            page_svg.write_text("<svg />", encoding="utf-8")
            font_path = root / "font.ttf"
            font_path.write_bytes(b"font")
            captured: dict[str, object] = {}

            def _fake_prepare_toe_page(**kwargs):
                captured.update(kwargs)
                out_prefix = kwargs["prefix"]
                out_prefix.parent.mkdir(parents=True, exist_ok=True)
                svg_path, pdf_path, nc_path, gcode_path = mod.prep._bridge_preview_copy_targets(out_prefix)
                svg_path.write_text("<svg />", encoding="utf-8")
                doc = fitz.open()
                doc.new_page(width=200, height=200)
                doc.save(pdf_path)
                doc.close()
                nc_path.write_text("G21\nG90\nM2\n", encoding="utf-8")
                gcode_path.write_text("G21\nG90\nM2\n", encoding="utf-8")
                return {
                    "item": "page_01",
                    "ok": True,
                    "message": "ok",
                    "logs": [],
                    "font_label": "Marck Script",
                    "font_path": str(font_path),
                    "layout_similarity": 0.94,
                    "metrics": {"segments_total": 1},
                    "svg": str(svg_path),
                    "pdf": str(pdf_path),
                    "nc": str(nc_path),
                    "gcode": str(gcode_path),
                    "notes": "",
                }

            with (
                mock.patch.object(mod.prep, "_prepare_toe_page", side_effect=_fake_prepare_toe_page),
                mock.patch.object(mod, "_compute_quality_metrics", return_value={"segments_total": 1, "segments_duplicate_ratio": 0.0, "segments_tiny_ratio": 0.0}),
                mock.patch.object(mod, "_build_overlay_metrics", return_value={"mask_iou": 0.3, "mask_recall": 0.4, "mask_precision": 0.5}),
            ):
                row = mod._build_lineart_rescue_candidate(
                    source_pdf=source_pdf,
                    page_index=1,
                    page_svg=page_svg,
                    package_dir=root / "pack",
                    font_label="Marck Script",
                    font_path=font_path,
                    source_profile={"image_count": 1, "text_count": 1, "path_count": 1},
                    max_duplicate_ratio=0.002,
                    max_tiny_ratio=0.015,
                    resume=False,
                )

        self.assertTrue(row["ok"])
        self.assertEqual(captured["backend_overrides"], mod.LINEART_RESCUE_BACKEND_OVERRIDES)
        self.assertEqual(row["variant_label"], "lineart_safe")

    def test_build_graph_rescue_candidate_passes_backend_overrides(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_graph_rescue_") as td:
            root = Path(td)
            source_pdf = root / "src.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")
            page_svg = root / "page_01.svg"
            page_svg.write_text("<svg />", encoding="utf-8")
            font_path = root / "font.ttf"
            font_path.write_bytes(b"font")
            captured: dict[str, object] = {}

            def _fake_prepare_toe_page(**kwargs):
                captured.update(kwargs)
                out_prefix = kwargs["prefix"]
                out_prefix.parent.mkdir(parents=True, exist_ok=True)
                svg_path, pdf_path, nc_path, gcode_path = mod.prep._bridge_preview_copy_targets(out_prefix)
                svg_path.write_text("<svg />", encoding="utf-8")
                doc = fitz.open()
                doc.new_page(width=200, height=200)
                doc.save(pdf_path)
                doc.close()
                nc_path.write_text("G21\nG90\nM2\n", encoding="utf-8")
                gcode_path.write_text("G21\nG90\nM2\n", encoding="utf-8")
                return {
                    "item": "page_01",
                    "ok": True,
                    "message": "ok",
                    "logs": [],
                    "font_label": "Marck Script",
                    "font_path": str(font_path),
                    "layout_similarity": 0.971,
                    "metrics": {"segments_total": 1},
                    "svg": str(svg_path),
                    "pdf": str(pdf_path),
                    "nc": str(nc_path),
                    "gcode": str(gcode_path),
                    "notes": "",
                }

            with (
                mock.patch.object(mod.prep, "_prepare_toe_page", side_effect=_fake_prepare_toe_page),
                mock.patch.object(mod, "_compute_quality_metrics", return_value={"segments_total": 1, "segments_duplicate_ratio": 0.0, "segments_tiny_ratio": 0.0}),
                mock.patch.object(mod, "_build_overlay_metrics", return_value={"mask_iou": 0.3, "mask_recall": 0.4, "mask_precision": 0.5}),
            ):
                row = mod._build_graph_rescue_candidate(
                    source_pdf=source_pdf,
                    page_index=1,
                    page_svg=page_svg,
                    package_dir=root / "pack",
                    font_label="Marck Script",
                    font_path=font_path,
                    source_profile={"image_count": 8, "text_count": 18, "path_count": 120},
                    max_duplicate_ratio=0.002,
                    max_tiny_ratio=0.015,
                    resume=False,
                )

        self.assertTrue(row["ok"])
        self.assertEqual(captured["backend_overrides"], mod.GRAPH_RESCUE_BACKEND_OVERRIDES)
        self.assertEqual(row["variant_label"], "graph_safe")

    def test_build_image_heavy_fallback_candidate_passes_page_svg(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_image_heavy_fallback_") as td:
            root = Path(td)
            source_pdf = root / "src.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")
            page_svg = root / "page_01.svg"
            page_svg.write_text("<svg />", encoding="utf-8")
            font_path = root / "font.ttf"
            font_path.write_bytes(b"font")
            captured: dict[str, object] = {}

            def _fake_prepare_toe_raster_fallback(**kwargs):
                captured.update(kwargs)
                out_prefix = kwargs["prefix"]
                out_prefix.parent.mkdir(parents=True, exist_ok=True)
                svg_path, pdf_path, nc_path, gcode_path = mod.prep._bridge_preview_copy_targets(out_prefix)
                svg_path.write_text("<svg />", encoding="utf-8")
                doc = fitz.open()
                doc.new_page(width=200, height=200)
                doc.save(pdf_path)
                doc.close()
                nc_path.write_text("G21\nG90\nM2\n", encoding="utf-8")
                gcode_path.write_text("G21\nG90\nM2\n", encoding="utf-8")
                return {
                    "item": "page_01",
                    "ok": True,
                    "message": "ok",
                    "logs": [],
                    "font_label": "Marck Script",
                    "font_path": str(font_path),
                    "layout_similarity": 0.95,
                    "metrics": {"segments_total": 1},
                    "svg": str(svg_path),
                    "pdf": str(pdf_path),
                    "nc": str(nc_path),
                    "gcode": str(gcode_path),
                    "notes": "",
                }

            with (
                mock.patch.object(mod.prep, "_prepare_toe_raster_fallback", side_effect=_fake_prepare_toe_raster_fallback),
                mock.patch.object(mod, "_compute_quality_metrics", return_value={"segments_total": 1, "segments_duplicate_ratio": 0.0, "segments_tiny_ratio": 0.0}),
                mock.patch.object(mod, "_build_overlay_metrics", return_value={"mask_iou": 0.3, "mask_recall": 0.4, "mask_precision": 0.5}),
            ):
                row = mod._build_image_heavy_fallback_candidate(
                    source_pdf=source_pdf,
                    page_index=1,
                    page_svg=page_svg,
                    package_dir=root / "pack",
                    font_label="Marck Script",
                    font_path=font_path,
                    source_profile={"image_count": 1, "text_count": 1, "path_count": 1},
                    max_duplicate_ratio=0.002,
                    max_tiny_ratio=0.015,
                    resume=False,
                )

        self.assertTrue(row["ok"])
        self.assertEqual(captured["page_svg"], page_svg)
        self.assertEqual(row["variant_label"], "raster_safe")

    def test_prefer_dominating_candidate_promotes_better_similarity_and_iou(self) -> None:
        mod = _load_module()
        selected = {
            "ok": True,
            "variant_label": "always",
            "layout_similarity": 0.953845,
            "overlay_metrics": {"mask_iou": 0.298862},
        }
        better = {
            "ok": True,
            "variant_label": "raster_safe",
            "layout_similarity": 0.959925,
            "overlay_metrics": {"mask_iou": 0.309351},
        }
        out = mod._prefer_dominating_candidate(
            selected=selected,
            page_results=[selected, better],
        )
        self.assertIs(out, better)

    def test_prefer_dominating_candidate_keeps_selected_when_tradeoff_exists(self) -> None:
        mod = _load_module()
        selected = {
            "ok": True,
            "variant_label": "always",
            "layout_similarity": 0.935496,
            "overlay_metrics": {"mask_iou": 0.313178},
        }
        tradeoff = {
            "ok": True,
            "variant_label": "raster_safe",
            "layout_similarity": 0.939933,
            "overlay_metrics": {"mask_iou": 0.293268},
        }
        out = mod._prefer_dominating_candidate(
            selected=selected,
            page_results=[selected, tradeoff],
        )
        self.assertIs(out, selected)

    def test_select_page_result_prefers_raster_safe_for_image_heavy_page_with_better_similarity(self) -> None:
        mod = _load_module()
        base = {
            "ok": True,
            "font_label": "Marck Script",
            "variant_label": "always",
            "layout_similarity": 0.968705,
            "score": 1.238723,
            "source_image_count": 17,
            "quality_metrics": {
                "segments_duplicate_ratio": 0.0,
                "segments_tiny_ratio": 0.01,
                "segments_short_ratio": 0.05,
            },
            "overlay_metrics": {
                "mask_iou": 0.264174,
                "mask_recall": 0.381064,
                "mask_precision": 0.462716,
            },
            "quality_gate": {"accepted": False},
        }
        fallback = {
            "ok": True,
            "font_label": "Marck Script",
            "variant_label": "raster_safe",
            "layout_similarity": 0.973600,
            "score": 1.210000,
            "source_image_count": 17,
            "quality_metrics": {
                "segments_duplicate_ratio": 0.0,
                "segments_tiny_ratio": 0.01,
                "segments_short_ratio": 0.05,
            },
            "overlay_metrics": {
                "mask_iou": 0.308928,
                "mask_recall": 0.398502,
                "mask_precision": 0.578838,
            },
            "quality_gate": {"accepted": True},
        }
        selected = mod._select_page_result(
            primary_label="Marck Script",
            page_results=[base, fallback],
            override_similarity_gain=0.003,
        )
        self.assertEqual(selected["variant_label"], "raster_safe")


if __name__ == "__main__":
    unittest.main()
