from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import fitz  # type: ignore


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


if __name__ == "__main__":
    unittest.main()
