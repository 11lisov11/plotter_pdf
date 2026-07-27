from __future__ import annotations

import sys
from typing import Optional

from src import plotter_pdf_drawer as backend
from src.plotter_backend import cli_entry
from src.plotter_backend.jobs import self_check_cli


class _BackendProxy:
    def __getattr__(self, name: str):
        return getattr(backend, name)

    def __setattr__(self, name: str, value) -> None:
        # Runtime CLI overrides must change the actual backend globals used by
        # geometry/G-code functions, not create shadow attributes on the proxy.
        setattr(backend, name, value)


CLI_BACKEND = _BackendProxy()


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "self-check":
        return self_check_cli.main(args[1:])
    return cli_entry.run_cli_main(CLI_BACKEND, argv)


if __name__ == "__main__":
    raise SystemExit(main())
