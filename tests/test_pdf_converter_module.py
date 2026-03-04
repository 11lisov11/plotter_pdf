from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend.converters import pdf_converter


class PdfConverterModuleTests(unittest.TestCase):
    def test_build_inkscape_pdf_to_svg_candidates_for_modern_versions(self) -> None:
        pdf = Path("C:/tmp/source.pdf")
        svg = Path("C:/tmp/out.svg")
        cmds = pdf_converter.build_inkscape_pdf_to_svg_candidates(
            "inkscape.exe",
            pdf,
            svg,
            get_inkscape_version=lambda _exe: (1, 3, 2),
        )
        self.assertEqual(len(cmds), 4)
        self.assertIn("--export-type=svg", cmds[0])
        self.assertIn("--pdf-poppler", cmds[0])

    def test_build_inkscape_pdf_to_svg_candidates_for_legacy_versions(self) -> None:
        pdf = Path("C:/tmp/source.pdf")
        svg = Path("C:/tmp/out.svg")
        cmds = pdf_converter.build_inkscape_pdf_to_svg_candidates(
            "inkscape.exe",
            pdf,
            svg,
            get_inkscape_version=lambda _exe: (0, 92, 5),
        )
        self.assertEqual(len(cmds), 3)
        self.assertTrue(any("--export-plain-svg" in " ".join(cmd) for cmd in cmds))

    def test_ensure_generated_svg_exists_moves_best_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_pdf_conv_") as td:
            root = Path(td)
            prefix = root / "source_prefix"
            candidate = Path(f"{prefix}-1.svg")
            target = root / "final.svg"
            candidate.write_text("<svg/>", encoding="utf-8")

            logs: list[str] = []
            ok = pdf_converter.ensure_generated_svg_exists(prefix, target, logs.append)

            self.assertTrue(ok)
            self.assertTrue(target.exists())
            self.assertFalse(candidate.exists())
            self.assertTrue(any("Using generated SVG" in line for line in logs))

    def test_ensure_generated_svg_exists_returns_false_without_candidates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_pdf_conv_empty_") as td:
            root = Path(td)
            prefix = root / "missing"
            target = root / "missing.svg"
            ok = pdf_converter.ensure_generated_svg_exists(prefix, target, lambda *_args: None)
            self.assertFalse(ok)

    def test_score_svg_quality_returns_inf_for_empty_geometry(self) -> None:
        score, details = pdf_converter.score_svg_quality(
            Path("C:/tmp/empty.svg"),
            extract_polylines=lambda _path: [],
            to_drawing_polylines=lambda _items: [],
            points_distance=lambda _a, _b: 0.0,
            svg_page_size_mm=lambda _path: (0.0, 0.0),
            bounds_path_items=lambda _items: None,
        )
        self.assertEqual(score, float("inf"))
        self.assertEqual(details, "no paths")

    def test_score_svg_quality_returns_finite_for_simple_polyline(self) -> None:
        items = [object()]
        polylines = [[(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]]
        score, details = pdf_converter.score_svg_quality(
            Path("C:/tmp/simple.svg"),
            extract_polylines=lambda _path: items,
            to_drawing_polylines=lambda _items: polylines,
            points_distance=lambda a, b: ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5,
            svg_page_size_mm=lambda _path: (20.0, 20.0),
            bounds_path_items=lambda _items: (0.0, 10.0, 0.0, 5.0),
        )
        self.assertTrue(score < float("inf"))
        self.assertIn("score=", details)
        self.assertIn("seg=", details)


if __name__ == "__main__":
    unittest.main()
