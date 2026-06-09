from __future__ import annotations

from plotter_app.app_entry import build_parser


def test_gui_help_parser_imports_without_pyside() -> None:
    parser = build_parser()
    args = parser.parse_args(["--self-check"])
    assert args.self_check is True
