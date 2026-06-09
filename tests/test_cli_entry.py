from __future__ import annotations

from unittest import mock

from src import cli_main


def test_plotter_pdf_self_check_subcommand_uses_self_check_cli() -> None:
    with mock.patch.object(cli_main.self_check_cli, "main", return_value=0) as self_check:
        assert cli_main.main(["self-check", "--json-out", "report.json"]) == 0
    self_check.assert_called_once_with(["--json-out", "report.json"])
