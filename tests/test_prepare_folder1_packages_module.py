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
