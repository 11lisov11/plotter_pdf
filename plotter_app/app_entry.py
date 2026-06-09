from __future__ import annotations

import argparse
import sys
from typing import Optional


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Графический интерфейс Plotter PDF")
    parser.add_argument("--self-check", action="store_true", help="Запустить самопроверку в консоли и выйти.")
    return parser


def _has_console_stdout() -> bool:
    return sys.stdout is not None and hasattr(sys.stdout, "write")


def main(argv: Optional[list[str]] = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    if "--help" in args_list or "-h" in args_list:
        if _has_console_stdout():
            try:
                parser.print_help()
            except Exception:
                pass
        return 0
    args = parser.parse_args(args_list)
    if args.self_check:
        from src.plotter_backend.jobs.self_check_cli import main as self_check_main

        return self_check_main([])
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        print(f"Для GUI нужен PySide6. Установите: pip install -e \".[gui]\" ({type(exc).__name__}: {exc})")
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
