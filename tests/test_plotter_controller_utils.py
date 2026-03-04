from __future__ import annotations

import unittest

from plotter_studio.core.plotter_controller import PlotterController
from plotter_studio.core.settings import AppSettingsData


class PlotterControllerUtilsTests(unittest.TestCase):
    def test_extract_preview_path_prefers_preview_ready(self) -> None:
        message = (
            "Done | Preview ready: C:\\tmp\\preview.svg | "
            "Preview PDF: C:\\tmp\\preview.pdf"
        )
        out = PlotterController._extract_preview_path(message)
        self.assertEqual(out, r"C:\tmp\preview.svg")

    def test_extract_preview_path_from_pdf_marker(self) -> None:
        message = "Done | PDF: C:\\tmp\\preview.pdf"
        out = PlotterController._extract_preview_path(message)
        self.assertEqual(out, r"C:\tmp\preview.pdf")

    def test_extract_preview_path_from_svg_marker(self) -> None:
        message = "Done | Preview SVG: C:\\tmp\\preview.svg"
        out = PlotterController._extract_preview_path(message)
        self.assertEqual(out, r"C:\tmp\preview.svg")

    def test_extract_preview_path_empty(self) -> None:
        self.assertEqual(PlotterController._extract_preview_path(""), "")
        self.assertEqual(PlotterController._extract_preview_path("   "), "")

    def test_is_grbl_tail_detects_markers(self) -> None:
        self.assertTrue(PlotterController._is_grbl_tail("ok"))
        self.assertTrue(PlotterController._is_grbl_tail("error:2"))
        self.assertTrue(PlotterController._is_grbl_tail("ALARM:1"))
        self.assertTrue(PlotterController._is_grbl_tail("<Idle|MPos:0,0,0>"))
        self.assertTrue(PlotterController._is_grbl_tail("[MSG:Reset to continue]"))

    def test_is_grbl_tail_rejects_random_text(self) -> None:
        self.assertFalse(PlotterController._is_grbl_tail(""))
        self.assertFalse(PlotterController._is_grbl_tail("hello world"))
        self.assertFalse(PlotterController._is_grbl_tail("progress 50%"))

    def test_default_settings_com_port_is_com6(self) -> None:
        data = AppSettingsData()
        self.assertEqual(data.com_port, "COM6")


if __name__ == "__main__":
    unittest.main()

