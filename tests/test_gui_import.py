from __future__ import annotations

from plotter_app.app_entry import build_parser, main


def test_gui_help_parser_imports_without_pyside() -> None:
    parser = build_parser()
    args = parser.parse_args(["--self-check"])
    assert args.self_check is True


def test_gui_help_exits_success_without_pyside(capsys) -> None:
    assert main(["--help"]) == 0
    assert "Plotter PDF" in capsys.readouterr().out
