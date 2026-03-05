from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend.converters import cad_converter
from src.plotter_backend.errors import ConversionError, PipelineValidationError, ToolDependencyError


class CadConverterModuleTests(unittest.TestCase):
    def test_wait_for_nonempty_file_true_for_existing_nonempty_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_cad_wait_") as td:
            root = Path(td)
            target = root / "ready.pdf"
            target.write_bytes(b"%PDF-1.4\n")
            self.assertTrue(cad_converter.wait_for_nonempty_file(target, timeout_s=0.3, poll_s=0.05))

    def test_frw_to_pdf_rejects_non_cad_extension(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_cad_ext_") as td:
            root = Path(td)
            source = root / "source.txt"
            source.write_text("x", encoding="utf-8")
            output = root / "out.pdf"

            with self.assertRaises(PipelineValidationError):
                cad_converter.frw_to_pdf(
                    source,
                    output,
                    lambda _line: None,
                    ensure_local_tmp_root=lambda: root,
                )

    def test_frw_to_pdf_uses_neighbor_pdf_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_cad_mod_fb_") as td:
            root = Path(td)
            source = root / "source.frw"
            fallback_pdf = root / "source.pdf"
            output = root / "result.pdf"
            source.write_text("cad-source", encoding="utf-8")
            fallback_pdf.write_bytes(b"%PDF-1.4\n%module-fallback\n")

            logs: list[str] = []

            def _raise_primary(_src: Path, _dst: Path, _logger) -> None:
                raise RuntimeError("mocked kompas failure")

            cad_converter.frw_to_pdf(
                source,
                output,
                logs.append,
                ensure_local_tmp_root=lambda: root,
                find_spec=lambda _name: object(),
                kompas_print_to_pdf_fn=_raise_primary,
            )

            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes(), fallback_pdf.read_bytes())
            self.assertTrue(any("primary CAD conversion failed" in line for line in logs))
            self.assertTrue(any("RuntimeError" in line for line in logs))
            self.assertTrue(any("Using fallback PDF next to source" in line for line in logs))

    def test_frw_to_pdf_requires_pywin32_for_real_conversion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_cad_pywin32_") as td:
            root = Path(td)
            source = root / "source.frw"
            output = root / "result.pdf"
            source.write_text("cad-source", encoding="utf-8")

            with self.assertRaisesRegex(ToolDependencyError, "pywin32 is required"):
                cad_converter.frw_to_pdf(
                    source,
                    output,
                    lambda _line: None,
                    ensure_local_tmp_root=lambda: root,
                    find_spec=lambda _name: None,
                )

    def test_frw_to_pdf_reports_primary_error_class_when_no_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_cad_primary_class_") as td:
            root = Path(td)
            source = root / "source.frw"
            output = root / "result.pdf"
            source.write_text("cad-source", encoding="utf-8")
            logs: list[str] = []

            def _raise_dep(_src: Path, _dst: Path, _logger) -> None:
                raise ToolDependencyError("kompas missing")

            with self.assertRaises(ConversionError) as ctx:
                cad_converter.frw_to_pdf(
                    source,
                    output,
                    logs.append,
                    ensure_local_tmp_root=lambda: root,
                    find_spec=lambda _name: object(),
                    kompas_print_to_pdf_fn=_raise_dep,
                )

            self.assertIn("ToolDependencyError", str(ctx.exception))
            self.assertTrue(any("primary CAD conversion failed" in line for line in logs))
            self.assertTrue(any("ToolDependencyError" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
