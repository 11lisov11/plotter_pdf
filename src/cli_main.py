from __future__ import annotations

from typing import Optional

from src import plotter_pdf_drawer as backend
from src.plotter_backend import cli_entry


class _BackendProxy:
    def __getattr__(self, name: str):
        return getattr(backend, name)


CLI_BACKEND = _BackendProxy()


def main(argv: Optional[list[str]] = None) -> int:
    if argv and len(argv) > 0 and argv[0] == "self-check":
        from src.plotter_backend.jobs.self_check_cli import main as self_check_main

        return self_check_main(argv[1:])
    return cli_entry.run_cli_main(CLI_BACKEND, argv)
