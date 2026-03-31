from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2  # type: ignore
import fitz  # type: ignore
import numpy as np  # type: ignore


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "audit_toe_packages.py"
    spec = importlib.util.spec_from_file_location("audit_toe_packages", str(script_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AuditToePackagesModuleTests(unittest.TestCase):
    def test_variant_pack_name(self) -> None:
        mod = _load_module()
        self.assertEqual(mod.variant_pack_name("25"), "TOE_Zadachi_1_2_Variant_25_pack")

    def test_resolve_selected_packs_uses_known_variants(self) -> None:
        mod = _load_module()
        packs = mod.resolve_selected_packs(variants=[], packs=[], all_known=True)
        self.assertEqual(
            [path.name for path in packs],
            [f"TOE_Zadachi_1_2_Variant_{variant}_pack" for variant in mod.KNOWN_VARIANT_NUMBERS],
        )

    def test_page_status_marks_failed_quality_gate_as_weak(self) -> None:
        mod = _load_module()
        item = {
            "selected_layout_similarity": 0.965,
            "selected_overlay_metrics": {"mask_iou": 0.40},
            "selected_quality_gate": {"accepted": False},
        }
        self.assertEqual(mod._page_status(item), "weak")

    def test_severity_score_penalizes_low_similarity_and_failed_gate(self) -> None:
        mod = _load_module()
        weak_item = {
            "selected_layout_similarity": 0.938,
            "selected_overlay_metrics": {"mask_iou": 0.22, "mask_recall": 0.30},
            "selected_quality_gate": {"accepted": False},
            "selected_reason": "reason=region_rescue",
        }
        better_item = {
            "selected_layout_similarity": 0.972,
            "selected_overlay_metrics": {"mask_iou": 0.42, "mask_recall": 0.52},
            "selected_quality_gate": {"accepted": True},
            "selected_reason": "",
        }
        self.assertGreater(mod._severity_score(weak_item), mod._severity_score(better_item))

    def test_build_pack_audit_ranks_pages_by_severity(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_audit_pack_") as td:
            pack_dir = Path(td) / "TOE_Zadachi_1_2_Variant_99_pack"
            (pack_dir / "pages").mkdir(parents=True, exist_ok=True)
            report = {
                "source_pdf": "C:\\plotter_pdf\\TOE_Zadachi_1_2_Variant_99.pdf",
                "page_count": 2,
                "selected_primary_font": "Marck Script",
                "items": [
                    {
                        "page_index": 1,
                        "selected_variant": "always",
                        "source_strategy": "font_first_text_rich",
                        "selected_layout_similarity": 0.972,
                        "selected_overlay_metrics": {"mask_iou": 0.44, "mask_recall": 0.58},
                        "selected_quality_gate": {"accepted": True},
                        "selected_reason": "selection=base",
                    },
                    {
                        "page_index": 2,
                        "selected_variant": "region_safe",
                        "source_strategy": "image_heavy",
                        "selected_layout_similarity": 0.940,
                        "selected_overlay_metrics": {"mask_iou": 0.24, "mask_recall": 0.29},
                        "selected_quality_gate": {"accepted": False},
                        "selected_reason": "reason=region_rescue",
                    },
                ],
            }
            audit = mod.build_pack_audit(pack_dir=pack_dir, report=report, top_k=2)
        self.assertEqual(audit["weak_pages_count"], 1)
        self.assertEqual(audit["top_pages"][0]["page_index"], 2)
        self.assertEqual(audit["top_pages"][0]["status"], "weak")

    def test_largest_hotspot_bbox_norm_detects_component(self) -> None:
        mod = _load_module()
        mask = np.zeros((100, 120), dtype=np.uint8)
        mask[20:50, 40:90] = 1
        bbox = mod._largest_hotspot_bbox_norm(mask)
        assert bbox is not None
        x0, x1, y0, y1 = bbox
        self.assertLess(x0, 0.40)
        self.assertGreater(x1, 0.70)
        self.assertLess(y0, 0.25)
        self.assertGreater(y1, 0.45)

    def test_build_page_audit_writes_hotspot_when_overlay_exists(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_audit_hotspot_") as td:
            root = Path(td)
            pack_dir = root / "TOE_Zadachi_1_2_Variant_99_pack"
            pages_dir = pack_dir / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            source_pdf = root / "source.pdf"
            preview_pdf = pages_dir / "page_01.pdf"
            for pdf_path in (source_pdf, preview_pdf):
                doc = fitz.open()
                page = doc.new_page(width=595, height=842)
                page.insert_text((72, 72), "test", fontsize=12)
                doc.save(pdf_path)
                doc.close()
            overlay = np.full((900, 900, 3), 255, dtype=np.uint8)
            overlay[250:360, 320:500] = (220, 40, 40)
            overlay_path = pages_dir / "page_01_overlay.png"
            cv2.imwrite(str(overlay_path), overlay)
            item = {
                "_source_pdf": str(source_pdf),
                "page_index": 1,
                "selected_variant": "always",
                "source_strategy": "font_first_text_rich",
                "selected_layout_similarity": 0.94,
                "selected_overlay_metrics": {"mask_iou": 0.31, "mask_recall": 0.41},
                "selected_quality_gate": {"accepted": False},
                "selected_reason": "selection=base",
            }
            row = mod.build_page_audit(pack_dir=pack_dir, item=item)
            self.assertIn("hotspot", row)
            self.assertTrue(Path(str(row["hotspot"]["image"])).exists())

    def test_main_writes_audit_files(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_audit_main_") as td:
            root = Path(td)
            pack_dir = root / "TOE_Zadachi_1_2_Variant_99_pack"
            pack_dir.mkdir(parents=True, exist_ok=True)
            report = {
                "source_pdf": "C:\\plotter_pdf\\TOE_Zadachi_1_2_Variant_99.pdf",
                "page_count": 1,
                "selected_primary_font": "Marck Script",
                "items": [
                    {
                        "page_index": 1,
                        "selected_variant": "always",
                        "source_strategy": "font_first_text_rich",
                        "selected_layout_similarity": 0.972,
                        "selected_overlay_metrics": {"mask_iou": 0.44, "mask_recall": 0.58},
                        "selected_quality_gate": {"accepted": True},
                        "selected_reason": "selection=base",
                    }
                ],
            }
            (pack_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
            old_root = mod.PROJECT_ROOT
            try:
                mod.PROJECT_ROOT = root
                rc = mod.main(["--pack", pack_dir.name, "--top-k", "1"])
            finally:
                mod.PROJECT_ROOT = old_root
            self.assertEqual(rc, 0)
            self.assertTrue((pack_dir / "audit.json").exists())
            self.assertTrue((pack_dir / "audit.txt").exists())


if __name__ == "__main__":
    unittest.main()
