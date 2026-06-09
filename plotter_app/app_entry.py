from __future__ import annotations

import argparse
import sys
from typing import Optional


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plotter PDF GUI")
    parser.add_argument("--self-check", action="store_true", help="Run self-check in console mode and exit.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_check:
        from src.plotter_backend.jobs.self_check_cli import main as self_check_main

        return self_check_main([])
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        print(f"PySide6 is required for GUI. Install with: pip install -e \".[gui]\" ({type(exc).__name__}: {exc})")
        return 2
    from .main_window import MainWindow

    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
