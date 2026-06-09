from __future__ import annotations

from pathlib import Path

from src.plotter_backend.jobs.self_check import format_self_check_report, run_self_check


class SelfCheckViewModel:
    def __init__(self) -> None:
        self.last_exit_code: int | None = None
        self.last_report: dict | None = None
        self.last_text = ""

    def run(self, json_out: Path | None = None) -> tuple[int, str]:
        exit_code, report = run_self_check(json_out=json_out)
        self.last_exit_code = exit_code
        self.last_report = report
        self.last_text = format_self_check_report(report)
        return exit_code, self.last_text
