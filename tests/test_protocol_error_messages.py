from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plotter_studio.core.protocol import BackendBridge
from src.plotter_backend.errors import ToolDependencyError


class _WordFailBackend:
    def word_to_pdf(self, *_args, **_kwargs) -> None:
        raise ToolDependencyError("pywin32 is missing")


class ProtocolErrorMessageTests(unittest.TestCase):
    def test_resolve_method3_source_pdf_includes_exception_class(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_proto_err_") as td:
            root = Path(td)
            docx = root / "sample.docx"
            docx.write_text("docx", encoding="utf-8")
            work = root / "work"
            work.mkdir(parents=True, exist_ok=True)
            bridge = BackendBridge(root)

            ok, pdf_src, msg = bridge._resolve_method3_source_pdf(
                backend=_WordFailBackend(),
                input_path=docx,
                body_font="Marck Script",
                formula_font="Times New Roman",
                work_dir=work,
                log=lambda _line: None,
            )

            self.assertFalse(ok)
            self.assertIsNone(pdf_src)
            self.assertIn("ToolDependencyError", msg)
            self.assertIn("pywin32 is missing", msg)


if __name__ == "__main__":
    unittest.main()

