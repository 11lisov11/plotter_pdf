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

    def test_try_inkscape_export_success_on_second_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_pdf_ink_") as td:
            root = Path(td)
            pdf_path = root / "source.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            target_svg = root / "out.svg"
            logs: list[str] = []
            calls = {"n": 0}

            def _run_cmd(_cmd):
                calls["n"] += 1
                if calls["n"] == 1:
                    return 1, "", "first failure"
                target_svg.write_text("<svg/>", encoding="utf-8")
                return 0, "", ""

            ok, msg = pdf_converter.try_inkscape_export(
                pdf_path,
                target_svg,
                logs.append,
                find_inkscape=lambda: "C:/tools/inkscape.exe",
                run_cmd=_run_cmd,
                get_inkscape_version=lambda _exe: (1, 3, 0),
            )

            self.assertTrue(ok)
            self.assertEqual(msg, "ok")
            self.assertEqual(calls["n"], 2)
            self.assertTrue(any("Inkscape command #1" in line for line in logs))
            self.assertTrue(any("failed or produced empty SVG" in line for line in logs))

    def test_try_inkscape_export_returns_unavailable_error(self) -> None:
        ok, msg = pdf_converter.try_inkscape_export(
            Path("C:/tmp/in.pdf"),
            Path("C:/tmp/out.svg"),
            lambda *_args: None,
            find_inkscape=lambda: (_ for _ in ()).throw(RuntimeError("missing inkscape")),
            run_cmd=lambda _cmd: (1, "", ""),
            get_inkscape_version=lambda _exe: (1, 0, 0),
        )
        self.assertFalse(ok)
        self.assertIn("ToolDependencyError", msg)
        self.assertIn("Inkscape unavailable", msg)

    def test_try_pdftocairo_export_uses_generated_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_pdf_cairo_") as td:
            root = Path(td)
            pdf_path = root / "source.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            target_svg = root / "out.svg"

            def _run_cmd(cmd):
                prefix = Path(cmd[-1])
                generated = Path(f"{prefix}-1.svg")
                generated.write_text("<svg/>", encoding="utf-8")
                return 0, "", ""

            ok, msg = pdf_converter.try_pdftocairo_export(
                pdf_path,
                target_svg,
                lambda *_args: None,
                find_pdftocairo=lambda: "pdftocairo.exe",
                run_cmd=_run_cmd,
            )

            self.assertTrue(ok)
            self.assertEqual(msg, "ok")
            self.assertTrue(target_svg.exists())

    def test_try_pdftocairo_export_reports_dependency_error_class(self) -> None:
        ok, msg = pdf_converter.try_pdftocairo_export(
            Path("C:/tmp/in.pdf"),
            Path("C:/tmp/out.svg"),
            lambda *_args: None,
            find_pdftocairo=lambda: (_ for _ in ()).throw(RuntimeError("missing pdftocairo")),
            run_cmd=lambda _cmd: (0, "", ""),
        )
        self.assertFalse(ok)
        self.assertIn("ToolDependencyError", msg)
        self.assertIn("pdftocairo unavailable", msg)

    def test_try_pdftocairo_export_reports_conversion_error_when_svg_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_pdf_cairo_missing_svg_") as td:
            root = Path(td)
            pdf_path = root / "source.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            target_svg = root / "out.svg"

            ok, msg = pdf_converter.try_pdftocairo_export(
                pdf_path,
                target_svg,
                lambda *_args: None,
                find_pdftocairo=lambda: "pdftocairo.exe",
                run_cmd=lambda _cmd: (0, "", ""),
            )

            self.assertFalse(ok)
            self.assertIn("ConversionError", msg)
            self.assertIn("produced no SVG output", msg)

    def test_select_best_scored_export_prefers_handwriting_rows(self) -> None:
        scored = [
            ("pdftocairo", Path("c:/tmp/a.svg"), 1.0, "a", True, 0),
            ("inkscape", Path("c:/tmp/b.svg"), 2.0, "b", True, 5),
        ]
        logs: list[str] = []
        best = pdf_converter.select_best_scored_export(scored, logs.append, handwriting_enabled=True)
        self.assertEqual(best[0], "inkscape")
        self.assertTrue(any("forcing converter with editable text" in line for line in logs))

    def test_select_best_scored_export_uses_min_score_when_not_handwriting(self) -> None:
        scored = [
            ("inkscape", Path("c:/tmp/a.svg"), 3.0, "a", True, 5),
            ("pdftocairo", Path("c:/tmp/b.svg"), 1.5, "b", False, 0),
        ]
        best = pdf_converter.select_best_scored_export(scored, lambda *_args: None, handwriting_enabled=False)
        self.assertEqual(best[0], "pdftocairo")

    def test_score_svg_quality_metric_error_includes_exception_class(self) -> None:
        score, details = pdf_converter.score_svg_quality(
            Path("C:/tmp/broken.svg"),
            extract_polylines=lambda _path: (_ for _ in ()).throw(ValueError("cannot parse svg")),
            to_drawing_polylines=lambda _items: [],
            points_distance=lambda _a, _b: 0.0,
            svg_page_size_mm=lambda _path: (0.0, 0.0),
            bounds_path_items=lambda _items: None,
        )
        self.assertEqual(score, float("inf"))
        self.assertIn("metric-error", details)
        self.assertIn("ValueError", details)


if __name__ == "__main__":
    unittest.main()
