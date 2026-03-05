from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from src import plotter_pdf_drawer as backend


def _is_enabled(flag: str) -> bool:
    return (os.environ.get(flag, "").strip() == "1")


class PipelineDryRunIntegrationTests(unittest.TestCase):
    def test_svg_dry_run_creates_gcode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_svg_dry_") as td:
            root = Path(td)
            svg_path = root / "sample.svg"
            out_nc = root / "sample_prepared.nc"
            svg_path.write_text(
                (
                    "<svg xmlns='http://www.w3.org/2000/svg' width='50mm' height='30mm' viewBox='0 0 50 30'>"
                    "<path d='M 2 2 L 48 2 L 48 28 L 2 28 Z' stroke='black' fill='none' stroke-width='0.5'/>"
                    "</svg>"
                ),
                encoding="utf-8",
            )

            logs: list[str] = []
            ok, msg = backend.run_pipeline(svg_path, logs.append, send_to_plotter=False, output_path=out_nc)

            self.assertTrue(ok, msg)
            self.assertTrue(out_nc.exists(), "Expected prepared gcode file is missing")
            self.assertIn("prepared file saved", msg.lower())
            self.assertTrue(any("G-code stats:" in line for line in logs))

    @unittest.skipUnless(_is_enabled("PLOTTER_ENABLE_EXTENDED_INTEGRATION"), "Extended integration is disabled")
    def test_pdf_dry_run_creates_gcode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_pdf_dry_") as td:
            root = Path(td)
            svg_path = root / "source.svg"
            pdf_path = root / "source.pdf"
            out_nc = root / "source_prepared.nc"
            svg_path.write_text(
                (
                    "<svg xmlns='http://www.w3.org/2000/svg' width='40mm' height='20mm' viewBox='0 0 40 20'>"
                    "<text x='2' y='12' font-size='6'>PDF TEST</text>"
                    "</svg>"
                ),
                encoding="utf-8",
            )

            inkscape = backend.find_inkscape()
            subprocess.run(
                [inkscape, str(svg_path), "--export-type=pdf", f"--export-filename={pdf_path}"],
                check=True,
            )

            logs: list[str] = []
            ok, msg = backend.run_pipeline(pdf_path, logs.append, send_to_plotter=False, output_path=out_nc)
            self.assertTrue(ok, msg)
            self.assertTrue(out_nc.exists(), "Expected prepared gcode file is missing")

    def test_frw_to_pdf_uses_neighbor_pdf_fallback_when_primary_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_cad_fallback_") as td:
            root = Path(td)
            frw_path = root / "source.frw"
            fallback_pdf = root / "source.pdf"
            output_pdf = root / "converted.pdf"
            frw_path.write_text("cad stub", encoding="utf-8")
            fallback_pdf.write_bytes(b"%PDF-1.4\n%fallback-cad-pdf\n")

            logs: list[str] = []
            with (
                mock.patch.object(backend.importlib.util, "find_spec", return_value=object()),
                mock.patch.object(
                    backend,
                    "_kompas_print_to_pdf",
                    side_effect=RuntimeError("KOMPAS not available in test"),
                ),
            ):
                backend.frw_to_pdf(frw_path, output_pdf, logs.append)

            self.assertTrue(output_pdf.exists(), "Expected CAD fallback PDF output is missing")
            self.assertEqual(output_pdf.read_bytes(), fallback_pdf.read_bytes())
            self.assertTrue(any("primary CAD conversion failed" in line for line in logs))
            self.assertTrue(any("RuntimeError" in line for line in logs))
            self.assertTrue(any("Using fallback PDF next to source" in line for line in logs))

    @unittest.skipUnless(_is_enabled("PLOTTER_ENABLE_EXTENDED_INTEGRATION"), "Extended integration is disabled")
    @pytest.mark.word_required
    def test_docx_dry_run_creates_gcode(self) -> None:
        if backend.importlib.util.find_spec("win32com.client") is None:
            self.skipTest("win32com.client is unavailable")

        with tempfile.TemporaryDirectory(prefix="plotter_docx_dry_") as td:
            root = Path(td)
            docx_path = root / "source.docx"
            out_nc = root / "source_prepared.nc"

            import win32com.client  # type: ignore

            app = None
            try:
                app = win32com.client.DispatchEx("Word.Application")
                app.Visible = False
                app.DisplayAlerts = 0
                doc = app.Documents.Add()
                doc.Content.Text = "DOCX dry-run integration test for Plotter Studio."
                doc.SaveAs(str(docx_path.resolve()), FileFormat=16)
                doc.Close(False)
            finally:
                if app is not None:
                    try:
                        app.Quit()
                    except Exception:
                        pass

            logs: list[str] = []
            ok, msg = backend.run_pipeline(docx_path, logs.append, send_to_plotter=False, output_path=out_nc)
            self.assertTrue(ok, msg)
            self.assertTrue(out_nc.exists(), "Expected prepared gcode file is missing")


if __name__ == "__main__":
    unittest.main()
