from __future__ import annotations

import os
from pathlib import Path

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

import plotter_app.main_window as main_window_module
from plotter_app.main_window import MainWindow


def _make_pdf(path: Path, label: str) -> None:
    document = fitz.open()
    page = document.new_page(width=210.0 / 25.4 * 72.0, height=297.0 / 25.4 * 72.0)
    page.draw_rect(fitz.Rect(20.0, 20.0, page.rect.width - 20.0, page.rect.height - 20.0))
    page.insert_text((50.0, 80.0), label, fontsize=24.0)
    document.save(path)
    document.close()


def test_gui_builds_two_pdf_a3_layout_after_reorder_and_rotation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main_window_module, "save_gui_settings", lambda _settings: None)
    app = QApplication.instance() or QApplication([])
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    missing = tmp_path / "deleted.pdf"
    _make_pdf(first, "FIRST")
    _make_pdf(second, "SECOND")

    window = MainWindow()
    try:
        window.file_list.clear()
        window.vm.set_layout_items([(missing, 0, 0), (first, 0, 0)])
        window._restore_items()
        assert window.file_list.count() == 1

        window._add_list_item(second, 0, 0)
        window.file_list.setCurrentRow(1)
        window._rotate_selected(90)
        window._move_selected(-1)

        items = window._items()
        assert items == [(second, 0, 90), (first, 0, 0)]

        window.output_edit.setText(str(tmp_path / "job"))
        window.sheet_combo.setCurrentIndex(window.sheet_combo.findData("a3"))
        window.layout_combo.setCurrentIndex(window.layout_combo.findData("auto"))
        window._run_layout_preview()
        app.processEvents()

        previews = list((tmp_path / "job").glob("*_layout_a3_preview.pdf"))
        assert len(previews) == 1
        assert window.preview_view.scene() is not None
        assert window.preview_view.scene().items()
        assert "layout_a3" in window.preview_caption.text().lower()
    finally:
        window.close()
