from plotter_app.settings import load_settings, save_settings
from src.plotter_backend.jobs.models import JobSettings


def test_gui_settings_roundtrip(tmp_path):
    path = tmp_path / "gui_settings.json"
    save_settings(JobSettings(input_path="a.svg", com="COM7"), path)
    loaded = load_settings(path)
    assert loaded.input_path == "a.svg"
    assert loaded.com == "COM7"
