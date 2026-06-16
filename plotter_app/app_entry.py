from __future__ import annotations

import argparse
import sys
from typing import Optional


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plotter PDF GUI")
    parser.add_argument("--self-check", action="store_true", help="Run self-check in console mode and exit.")
    return parser


def print_help_safely(parser: argparse.ArgumentParser) -> None:
    help_text = parser.format_help()
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.write(help_text)
                stream.flush()
                return
        except Exception:
            continue


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    raw_args = sys.argv[1:] if argv is None else argv
    if any(arg in {"-h", "--help"} for arg in raw_args):
        print_help_safely(parser)
        return 0
    args = parser.parse_args(raw_args)
    if args.self_check:
        from src.plotter_backend.jobs.self_check_cli import main as self_check_main

        return self_check_main([])
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        print(f"PySide6 is required for GUI. Install with: pip install -e \".[gui]\" ({type(exc).__name__}: {exc})")
        return 2
    try:
        from .main_window import MainWindow
    except ImportError:
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from plotter_app.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
