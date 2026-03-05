from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import plotter_pdf_drawer as backend
from src.plotter_backend.errors import ToolDependencyError


class BackendDependencyDiscoveryTests(unittest.TestCase):
    def test_find_inkscape_raises_typed_dependency_error_when_missing(self) -> None:
        with (
            mock.patch.object(backend, "INKSCAPE_CANDIDATES", ["Z:/definitely/missing/inkscape.exe"]),
            mock.patch.object(backend.shutil, "which", return_value=None),
        ):
            with self.assertRaises(ToolDependencyError):
                backend.find_inkscape()

    def test_find_pdftocairo_raises_typed_dependency_error_when_missing(self) -> None:
        with (
            mock.patch.object(backend, "PDFTOCAIRO_CANDIDATES", ["Z:/definitely/missing/pdftocairo.exe"]),
            mock.patch.object(backend.shutil, "which", return_value=None),
        ):
            with self.assertRaises(ToolDependencyError):
                backend.find_pdftocairo()

    def test_find_pdftotext_uses_sibling_of_pdftocairo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_dep_discovery_") as td:
            root = Path(td)
            cairo = root / "pdftocairo.exe"
            text = root / "pdftotext.exe"
            cairo.write_text("", encoding="utf-8")
            text.write_text("", encoding="utf-8")

            with (
                mock.patch.object(backend, "PDFTOTEXT_CANDIDATES", ["Z:/definitely/missing/pdftotext.exe"]),
                mock.patch.object(backend.shutil, "which", return_value=None),
                mock.patch.object(backend, "find_pdftocairo", return_value=str(cairo)),
            ):
                resolved = backend.find_pdftotext()

            self.assertEqual(Path(resolved), text)

    def test_find_pdftotext_raises_typed_dependency_error_when_missing(self) -> None:
        with (
            mock.patch.object(backend, "PDFTOTEXT_CANDIDATES", ["Z:/definitely/missing/pdftotext.exe"]),
            mock.patch.object(backend.shutil, "which", return_value=None),
            mock.patch.object(backend, "find_pdftocairo", side_effect=ToolDependencyError("missing cairo")),
        ):
            with self.assertRaises(ToolDependencyError):
                backend.find_pdftotext()


if __name__ == "__main__":
    unittest.main()

