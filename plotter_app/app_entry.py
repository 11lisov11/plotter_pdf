from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plotter PDF GUI")
    parser.add_argument("--self-check", action="store_true", help="Run self-check in console and exit")
    args = parser.parse_args(argv)
    if args.self_check:
        from src.plotter_backend.jobs.self_check_cli import main as self_check_main
        return self_check_main([])
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print(f"PySide6 is not installed: {exc}. Install with: pip install -e .[gui]")
        return 2
    from .main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(); window.show()
    return int(app.exec())

if __name__ == "__main__":
    raise SystemExit(main())
