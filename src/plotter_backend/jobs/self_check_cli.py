from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

try:
    from .self_check import format_self_check_report, run_self_check
except ImportError:
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from src.plotter_backend.jobs.self_check import format_self_check_report, run_self_check


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Проверить окружение Plotter PDF.")
    parser.add_argument("--json-out", default=None, help="Путь для JSON-отчета.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_out = Path(args.json_out) if args.json_out else None
    exit_code, report = run_self_check(json_out=json_out)
    print(format_self_check_report(report))
    if json_out is not None:
        print(f"JSON-отчет: {json_out}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
