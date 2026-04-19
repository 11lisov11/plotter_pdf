from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.plotter_backend.converters import cad_converter
from src.plotter_backend.errors import ConversionError, PipelineValidationError, ToolDependencyError


class CadConverterModuleTests(unittest.TestCase):
    def test_kompas_print_to_pdf_prefers_pdf2d_converter(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_cad_pdf2d_") as td:
            root = Path(td)
            source = root / "source.frw"
            output = root / "out.pdf"
            converter_dll = root / "Pdf2d.dll"
            source.write_text("cad-source", encoding="utf-8")
            converter_dll.write_text("dll", encoding="utf-8")
            logs: list[str] = []

            class FakeConverter:
                def Convert(self, _src: str, target: str, _command: int, _show_param: bool):
                    Path(target).write_bytes(b"%PDF-1.6\n")
                    return 1

            class FakePrintJob:
                def Clear(self) -> None:
                    return None

                def AddSheets(self, *_args) -> None:
                    return None

                def Execute(self, _target: str):
                    raise AssertionError("PrintJob should not be used when Pdf2d converter succeeds")

            class FakeApp:
                def __init__(self) -> None:
                    self.PrintJob = FakePrintJob()

                def Converter(self, library: str):
                    self.library = library
                    return FakeConverter()

                def Quit(self) -> None:
                    return None

            fake_client = SimpleNamespace(
                gencache=SimpleNamespace(
                    EnsureDispatch=mock.Mock(side_effect=RuntimeError("ensure failed"))
                ),
                Dispatch=mock.Mock(return_value=FakeApp()),
            )
            fake_win32com = SimpleNamespace(client=fake_client)
            fake_pythoncom = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)

            with mock.patch.object(cad_converter, "KOMPAS_PDF2D_DLLS", (converter_dll,)):
                with mock.patch.dict(
                    "sys.modules",
                    {
                        "win32com": fake_win32com,
                        "win32com.client": fake_client,
                        "pythoncom": fake_pythoncom,
                    },
                ):
                    cad_converter.kompas_print_to_pdf(source, output, logs.append)

            self.assertTrue(output.exists())
            self.assertTrue(any("Pdf2d.Convert" in line for line in logs))

    def test_kompas_print_to_pdf_falls_back_to_dispatch_when_ensure_dispatch_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_cad_dispatch_fb_") as td:
            root = Path(td)
            source = root / "source.frw"
            output = root / "out.pdf"
            source.write_text("cad-source", encoding="utf-8")
            logs: list[str] = []

            class FakePrintJob:
                def Clear(self) -> None:
                    return None

                def AddSheets(self, *_args) -> None:
                    return None

                def Execute(self, target: str):
                    Path(target).write_bytes(b"%PDF-1.4\n")
                    return True

            class FakeApp:
                def __init__(self) -> None:
                    self.PrintJob = FakePrintJob()

                def Quit(self) -> None:
                    return None

            fake_client = SimpleNamespace(
                gencache=SimpleNamespace(
                    EnsureDispatch=mock.Mock(side_effect=RuntimeError("ensure failed"))
                ),
                Dispatch=mock.Mock(return_value=FakeApp()),
            )
            fake_win32com = SimpleNamespace(client=fake_client)
            fake_pythoncom = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)

            with mock.patch.dict(
                "sys.modules",
                {
                    "win32com": fake_win32com,
                    "win32com.client": fake_client,
                    "pythoncom": fake_pythoncom,
                },
            ):
                cad_converter.kompas_print_to_pdf(source, output, logs.append)

            self.assertTrue(output.exists())
            self.assertTrue(any("dispatch fallback" in line for line in logs))

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
