from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "toe_package_editor.py"
    spec = importlib.util.spec_from_file_location("toe_package_editor", str(script_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ToePackageEditorModuleTests(unittest.TestCase):
    def test_set_and_clear_override_roundtrip(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_editor_") as td:
            td_path = Path(td)
            pdf_path = td_path / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
            out_dir = td_path / "sample_pack"
            overrides_path = out_dir / "page_overrides.json"

            args = types.SimpleNamespace(
                pdf=str(pdf_path),
                out_dir=str(out_dir),
                overrides_file=str(overrides_path),
                page=12,
                variant_label="lineart_safe",
                font_label="Marck Script",
                image_contours_mode="always",
                notes="manual tweak",
            )
            rc = mod._cmd_set(args)
            self.assertEqual(rc, 0)
            payload = mod._load_overrides_payload(overrides_path)
            self.assertEqual(
                payload["pages"]["12"],
                {
                    "variant_label": "lineart_safe",
                    "font_label": "Marck Script",
                    "image_contours_mode": "always",
                    "notes": "manual tweak",
                },
            )

            clear_args = types.SimpleNamespace(
                pdf=str(pdf_path),
                out_dir=str(out_dir),
                overrides_file=str(overrides_path),
                page=12,
            )
            rc = mod._cmd_clear(clear_args)
            self.assertEqual(rc, 0)
            payload = mod._load_overrides_payload(overrides_path)
            self.assertEqual(payload["pages"], {})

    def test_set_rejects_unknown_variant(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_editor_bad_variant_") as td:
            td_path = Path(td)
            pdf_path = td_path / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
            args = types.SimpleNamespace(
                pdf=str(pdf_path),
                out_dir=str(td_path / "sample_pack"),
                overrides_file="",
                page=3,
                variant_label="bad_variant",
                font_label="Marck Script",
                image_contours_mode="",
                notes="",
            )
            with self.assertRaises(ValueError):
                mod._cmd_set(args)

    def test_suggest_writes_dominating_candidate_override(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory(prefix="toe_editor_suggest_") as td:
            td_path = Path(td)
            pdf_path = td_path / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
            pack_dir = td_path / "sample_pack"
            pack_dir.mkdir(parents=True, exist_ok=True)
            report = {
                "items": [
                    {
                        "page_index": 7,
                        "selected_variant": "always",
                        "selected_font": "Marck Script",
                        "candidates": [
                            {
                                "ok": True,
                                "variant_label": "always",
                                "font_label": "Marck Script",
                                "image_contours_mode": "always",
                                "layout_similarity": 0.94,
                                "overlay_metrics": {"mask_iou": 0.30},
                            },
                            {
                                "ok": True,
                                "variant_label": "lineart_safe",
                                "font_label": "Marck Script",
                                "image_contours_mode": "always",
                                "layout_similarity": 0.941,
                                "overlay_metrics": {"mask_iou": 0.31},
                            },
                        ],
                    }
                ]
            }
            (pack_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
            args = types.SimpleNamespace(
                pdf=str(pdf_path),
                out_dir=str(pack_dir),
                overrides_file="",
                write=str(pack_dir / "suggested.json"),
            )
            rc = mod._cmd_suggest(args)
            self.assertEqual(rc, 0)
            payload = json.loads((pack_dir / "suggested.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["pages"]["7"]["variant_label"], "lineart_safe")


if __name__ == "__main__":
    unittest.main()
