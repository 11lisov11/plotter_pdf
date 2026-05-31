from __future__ import annotations

import unittest
from unittest import mock

from src import cli_main


class CliMainModuleTests(unittest.TestCase):
    def test_main_delegates_to_cli_entry_with_proxy_backend(self) -> None:
        with mock.patch.object(cli_main.cli_entry, "run_cli_main", return_value=7) as run_cli_main:
            rc = cli_main.main(["--plan-sheet"])

        self.assertEqual(rc, 7)
        run_cli_main.assert_called_once()
        backend_arg, argv_arg = run_cli_main.call_args.args
        self.assertIs(backend_arg, cli_main.CLI_BACKEND)
        self.assertEqual(argv_arg, ["--plan-sheet"])


if __name__ == "__main__":
    unittest.main()
