from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .core.plotter_controller import PlotterController
from .ui.main_window import MainWindow


def _resolve_bundle_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(str(meipass)).resolve()
    return Path(__file__).resolve().parent.parent


def _resolve_project_root() -> Path:
    # Keep runtime artifacts in a stable location for PyInstaller --onefile.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def create_application(bundle_root: Path) -> QApplication:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("PlotterStudio")
    app.setOrganizationName("PlotterStudio")
    icon_path = bundle_root / "plotter_studio" / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def main() -> int:
    bundle_root = _resolve_bundle_root()
    project_root = _resolve_project_root()
    app = create_application(bundle_root)
    controller = PlotterController(project_root)
    window = MainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

