from __future__ import annotations

from plotter_app.settings import load_gui_settings, save_gui_settings


def test_gui_settings_roundtrip(tmp_path) -> None:
    path = tmp_path / "gui_settings.json"
    saved_path = save_gui_settings({"com": "COM7", "sheet_format": "a3"}, path)
    loaded = load_gui_settings(saved_path)
    assert loaded["com"] == "COM7"
    assert loaded["sheet_format"] == "a3"
    assert "baud" in loaded
