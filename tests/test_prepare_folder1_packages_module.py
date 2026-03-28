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
    def test_prepare_toe_raster_fallback_uses_handdraw_preview(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_raster_fallback_") as td:
            root = Path(td)
            source_pdf = root / "src.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")
            prefix = root / "page_14"
            capture: dict[str, object] = {}

            def _fake_bridge_run_preview(**kwargs):
                capture.update(kwargs)
                return True, "ok", ["preview-ok"]

            with (
                mock.patch.object(mod, "_rewrite_pdf_page_text_to_handwritten_pdf", return_value=None),
                mock.patch.object(mod, "_bridge_run_preview", side_effect=_fake_bridge_run_preview),
                mock.patch.object(
                    mod,
                    "_copy_latest_preview_artifacts",
                    return_value=(
                        root / "page_14.svg",
                        root / "page_14.pdf",
                        root / "page_14.nc",
                        root / "page_14.gcode",
                    ),
                ),
                mock.patch.object(mod, "_analyze_gcode", return_value={"segments_total": 10}),
                mock.patch.object(mod, "_layout_similarity_pdf", return_value=0.97),
            ):
                row = mod._prepare_toe_raster_fallback(
                    source_pdf=source_pdf,
                    page_index=14,
                    prefix=prefix,
                    font_label="Neucha",
                    font_path=root / "font.ttf",
                )

        self.assertTrue(row["ok"])
        self.assertEqual(capture["render_mode"], "handwriting")
        self.assertTrue(capture["handwriting_enabled"])
        self.assertEqual(capture["image_contours_mode"], "always")
        self.assertIn("raster_rewrite_handdraw", row["notes"])


if __name__ == "__main__":
    unittest.main()
