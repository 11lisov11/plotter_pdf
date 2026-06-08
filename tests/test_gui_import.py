import importlib.util

import pytest


def test_gui_modules_import():
    import plotter_app.app_entry  # noqa: F401
    import plotter_app.settings  # noqa: F401


@pytest.mark.gui
def test_pyside6_import_or_skip():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 not installed")
    import plotter_app.main_window  # noqa: F401
