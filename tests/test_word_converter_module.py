from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend.converters import word_converter
from src.plotter_backend.errors import PipelineValidationError


class WordConverterModuleTests(unittest.TestCase):
    def test_normalize_word_font_name_from_ttf_stem(self) -> None:
        name = word_converter.normalize_word_font_name(r"C:\fonts\ofont.ru_Marck_Script.ttf", default="Fallback")
        self.assertEqual(name, "ofont.ru_Marck_Script")

    def test_apply_word_handwriting_font_restores_math_runs(self) -> None:
        class _Font:
            def __init__(self) -> None:
                self.Name = ""
                self.NameAscii = ""
                self.NameFarEast = ""
                self.NameOther = ""

        class _Range:
            def __init__(self) -> None:
                self.Font = _Font()

        class _OMathItem:
            def __init__(self) -> None:
                self.Range = _Range()

        class _OMaths:
            def __init__(self, count: int) -> None:
                self.Count = count
                self._items = [_OMathItem() for _ in range(count)]

            def Item(self, i: int) -> _OMathItem:
                return self._items[i - 1]

        class _Doc:
            def __init__(self) -> None:
                self.Content = _Range()
                self.OMaths = _OMaths(2)

        doc = _Doc()
        ok, restored = word_converter.apply_word_handwriting_font(
            doc,
            "Segoe Script",
            logger=lambda *_args: None,
            normalize_handwriting_font_name=lambda value: value,
            handwriting_word_keep_math=True,
            math_font=None,
        )
        self.assertTrue(ok)
        self.assertEqual(restored, 2)
        self.assertEqual(doc.Content.Font.Name, "Segoe Script")
        self.assertEqual(doc.OMaths.Item(1).Range.Font.Name, "Cambria Math")
        self.assertEqual(doc.OMaths.Item(2).Range.Font.Name, "Cambria Math")

    def test_word_to_pdf_rejects_non_word_extension(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_word_mod_ext_") as td:
            root = Path(td)
            source = root / "source.txt"
            source.write_text("x", encoding="utf-8")
            output = root / "out.pdf"

            with self.assertRaises(PipelineValidationError):
                word_converter.word_to_pdf(
                    source,
                    output,
                    lambda _msg: None,
                    normalize_handwriting_font_name=lambda value: value,
                    pdf_text_questionmark_metrics=lambda *_args, **_kwargs: None,
                    handwriting_word_max_qmark_count=3,
                    handwriting_word_max_qmark_ratio=0.3,
                    handwriting_word_keep_math=False,
                    wait_until_path_unlocked_fn=lambda *_args, **_kwargs: True,
                )


if __name__ == "__main__":
    unittest.main()
