from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .core.plotter_controller import PlotterController
from .ui.main_window import MainWindow


def create_application(project_root: Path) -> QApplication:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("PlotterStudio")
    app.setOrganizationName("PlotterStudio")
    icon_path = project_root / "plotter_studio" / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    app = create_application(project_root)
    controller = PlotterController(project_root)
    window = MainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

