from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_pdf_handwriting_acceptance.py"
    spec = importlib.util.spec_from_file_location("pdf_acceptance_script", str(script_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PdfAcceptanceScriptModuleTests(unittest.TestCase):
    def test_parse_pages(self) -> None:
        mod = _load_module()
        pages = mod._parse_pages("1, 2,5")
        self.assertEqual(pages, [1, 2, 5])

    def test_build_report_comparison(self) -> None:
        mod = _load_module()
        baseline = {
            "input_pdf": "a.pdf",
            "pages": [
                {
                    "page": 1,
                    "runtime_s": 12.0,
                    "gcode_metrics": {
                        "segments_duplicate_ratio": 0.001,
                        "segments_tiny_ratio": 0.010,
                        "segments_short_ratio": 0.150,
                    },
                }
            ],
        }
        current = {
            "input_pdf": "a.pdf",
            "pages": [
                {
                    "page": 1,
                    "runtime_s": 10.0,
                    "gcode_metrics": {
                        "segments_duplicate_ratio": 0.0008,
                        "segments_tiny_ratio": 0.006,
                        "segments_short_ratio": 0.130,
                    },
                }
            ],
        }

        cmp_data = mod.build_report_comparison(baseline, current)
        self.assertEqual(cmp_data["matched_pages"], 1)
        self.assertEqual(len(cmp_data["rows"]), 1)
        row = cmp_data["rows"][0]
        self.assertAlmostEqual(float(row["duplicate_ratio_delta"]), -0.0002, places=6)
        self.assertAlmostEqual(float(row["tiny_ratio_delta"]), -0.004, places=6)
        self.assertAlmostEqual(float(row["short_ratio_delta"]), -0.02, places=6)
        self.assertAlmostEqual(float(row["runtime_s_delta"]), -2.0, places=6)


if __name__ == "__main__":
    unittest.main()

