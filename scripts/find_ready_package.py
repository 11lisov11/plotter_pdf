from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.plotter_backend.jobs.ready_package_selector import (  # noqa: E402,F401
    ReadyPackageSelection,
    _normalize_item,
    _normalize_kind,
    clean_report_value,
    find_first_ready_package,
    main,
)


if __name__ == "__main__":
    raise SystemExit(main())
