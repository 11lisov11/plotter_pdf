from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from src.plotter_backend.jobs import draw_job, preview_job, prepare_job
from src.plotter_backend.jobs.models import JobResult, JobSettings


class JobViewModel:
    def __init__(self, settings: JobSettings | None = None):
        self.settings = settings or JobSettings()
        self.preflight_ok = False
        self.busy = False
        self.hardware_confirmed = False
        self.last_result: JobResult | None = None
        self.logs: list[str] = []

    def log(self, message: str) -> None:
        self.logs.append(str(message))

    def can_preview(self) -> bool:
        return bool(self.settings.input_path) and not self.busy

    def can_generate(self) -> bool:
        return self.can_preview()

    def can_draw(self) -> bool:
        return bool(self.settings.input_path and self.settings.com and self.preflight_ok and self.hardware_confirmed and not self.busy)

    def update_settings(self, **kwargs) -> None:
        self.settings = replace(self.settings, **kwargs)
        if "input_path" in kwargs or "com" in kwargs:
            self.preflight_ok = False

    def refresh_com_ports(self) -> list[str]:
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except Exception as exc:
            self.log(f"COM detection unavailable: {exc}")
            return []

    def run_preview(self, runner: Callable[[JobSettings, Callable[[str], None]], JobResult] = preview_job) -> JobResult:
        self.busy = True
        try:
            result = runner(self.settings, self.log)
            self.last_result = result
            self.preflight_ok = result.ok and bool(result.gcode_path)
            return result
        finally:
            self.busy = False

    def run_generate(self, runner: Callable[[JobSettings, Callable[[str], None]], JobResult] = prepare_job) -> JobResult:
        return self.run_preview(runner)

    def run_draw(self, runner=draw_job) -> JobResult:
        if not self.can_draw():
            return JobResult(False, "Draw is blocked by GUI safety gate.", errors=["draw_blocked"])
        self.busy = True
        try:
            result = runner(self.settings, self.log, confirmed=True)
            self.last_result = result
            return result
        finally:
            self.busy = False

    def open_output_folder(self) -> Path:
        return self.settings.normalized_output_dir()
