from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.plotter_backend.jobs import JobResult, JobSettings, draw_job, prepare_gcode_job, preview_job


class JobViewModel:
    def __init__(self, settings: JobSettings | None = None) -> None:
        self.settings = settings or JobSettings()
        self.preflight_ok = False
        self.operation_running = False
        self.hardware_confirmed = False
        self.last_result: JobResult | None = None
        self.log_lines: list[str] = []

    def log(self, message: str) -> None:
        self.log_lines.append(str(message))

    def set_input_path(self, value: str | Path) -> None:
        self.settings.input_path = Path(value) if str(value).strip() else None
        self.preflight_ok = False

    def set_output_dir(self, value: str | Path) -> None:
        self.settings.output_dir = Path(value) if str(value).strip() else Path("_plotter_jobs")

    def set_com(self, value: str) -> None:
        self.settings.com = str(value or "").strip() or None

    def set_hardware_confirmed(self, confirmed: bool) -> None:
        self.hardware_confirmed = bool(confirmed)

    def has_input(self) -> bool:
        path = self.settings.normalized_input_path()
        return path is not None and path.exists()

    def can_preview(self) -> bool:
        return self.has_input() and not self.operation_running

    def can_generate(self) -> bool:
        return self.can_preview()

    def can_draw(self) -> bool:
        return (
            self.has_input()
            and bool(self.settings.com)
            and bool(self.preflight_ok)
            and bool(self.hardware_confirmed)
            and not self.operation_running
        )

    def _run(self, fn: Callable[[JobSettings], JobResult]) -> JobResult:
        self.operation_running = True
        try:
            result = fn(self.settings)
            self.last_result = result
            self.log(result.message)
            return result
        finally:
            self.operation_running = False

    def run_preview(self) -> JobResult:
        self.settings.preview = True
        self.settings.dry_run = True
        result = self._run(preview_job)
        self.preflight_ok = bool(result.ok)
        return result

    def generate_gcode(self) -> JobResult:
        self.settings.preview = False
        self.settings.dry_run = True
        result = self._run(prepare_gcode_job)
        self.preflight_ok = bool(result.ok)
        return result

    def draw(self) -> JobResult:
        self.settings.preview = False
        self.settings.dry_run = False
        self.operation_running = True
        try:
            result = draw_job(self.settings, confirm_hardware=self.hardware_confirmed)
            self.last_result = result
            self.log(result.message)
            return result
        finally:
            self.operation_running = False
