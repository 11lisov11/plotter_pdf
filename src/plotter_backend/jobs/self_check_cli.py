from __future__ import annotations

import argparse

from .self_check import format_report, run_self_check, write_json_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plotter PDF environment self-check")
    parser.add_argument("--json-out", help="Write JSON report to this path")
    args = parser.parse_args(argv)
    code, report = run_self_check()
    print(format_report(report))
    if args.json_out:
        write_json_report(report, args.json_out)
        print(f"JSON report: {args.json_out}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
