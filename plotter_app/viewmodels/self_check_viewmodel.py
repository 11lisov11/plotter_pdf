from __future__ import annotations

from src.plotter_backend.jobs.self_check import format_report, run_self_check


class SelfCheckViewModel:
    def __init__(self):
        self.exit_code: int | None = None
        self.report: dict | None = None

    def run(self) -> str:
        self.exit_code, self.report = run_self_check()
        return format_report(self.report)
