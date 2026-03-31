from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "prepare_toe_variants.py"
    spec = importlib.util.spec_from_file_location("prepare_toe_variants", str(script_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrepareToeVariantsModuleTests(unittest.TestCase):
    def test_variant_pdf_name(self) -> None:
        mod = _load_module()
        self.assertEqual(mod.variant_pdf_name("25"), "TOE_Zadachi_1_2_Variant_25.pdf")

    def test_resolve_selected_pdfs_uses_known_variants(self) -> None:
        mod = _load_module()
        pdfs = mod.resolve_selected_pdfs(variants=[], pdfs=[], all_known=True)
        self.assertEqual(
            [path.name for path in pdfs],
            [f"TOE_Zadachi_1_2_Variant_{variant}.pdf" for variant in mod.KNOWN_VARIANT_NUMBERS],
        )

    def test_resolve_selected_pdfs_deduplicates_inputs(self) -> None:
        mod = _load_module()
        pdfs = mod.resolve_selected_pdfs(
            variants=["25"],
            pdfs=["TOE_Zadachi_1_2_Variant_25.pdf", "TOE_Zadachi_1_2_Variant_11.pdf"],
            all_known=False,
        )
        self.assertEqual(
            [path.name for path in pdfs],
            ["TOE_Zadachi_1_2_Variant_25.pdf", "TOE_Zadachi_1_2_Variant_11.pdf"],
        )

    def test_build_prepare_command_passes_resume_and_font_labels(self) -> None:
        mod = _load_module()
        cmd = mod.build_prepare_command(
            pdf_path=Path("TOE_Zadachi_1_2_Variant_25.pdf"),
            resume=True,
            max_duplicate_ratio=0.002,
            max_tiny_ratio=0.015,
            override_similarity_gain=0.012,
            font_labels=["Marck Script"],
        )
        self.assertIn("--resume", cmd)
        self.assertIn("--font-label", cmd)
        self.assertIn("Marck Script", cmd)
        self.assertIn("TOE_Zadachi_1_2_Variant_25_pack", cmd)


if __name__ == "__main__":
    unittest.main()
