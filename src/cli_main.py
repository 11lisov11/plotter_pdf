from __future__ import annotations

from typing import Optional

from src import plotter_pdf_drawer as backend
from src.plotter_backend import cli_entry


class _BackendProxy:
    def __getattr__(self, name: str):
        return getattr(backend, name)

    def __setattr__(self, name: str, value) -> None:
        setattr(backend, name, value)


CLI_BACKEND = _BackendProxy()


def main(argv: Optional[list[str]] = None) -> int:
    return cli_entry.run_cli_main(CLI_BACKEND, argv)
