from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.plotter_backend.jobs import JobResult, JobSettings, build_pdf_layout_job, draw_job, prepare_gcode_job, preview_job


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
        self.settings.input_paths = [str(value)] if str(value).strip() else []
        self.settings.input_pages = [0] if str(value).strip() else []
        self.settings.input_rotations = [0] if str(value).strip() else []
        self.preflight_ok = False

    def set_layout_items(self, items: list[tuple[str | Path, int, int]], zones: list[str] | None = None) -> None:
        self.settings.input_paths = [str(path) for path, _page, _rotation in items]
        self.settings.input_pages = [int(page) for _path, page, _rotation in items]
        self.settings.input_rotations = [int(rotation) % 360 for _path, _page, rotation in items]
        if zones is not None:
            self.settings.input_zones = [str(zone).strip() for zone in zones[: len(items)]]
        else:
            self.settings.input_zones = self.settings.input_zones[: len(items)]
        self.settings.input_path = Path(items[0][0]) if items else None
        self.preflight_ok = False

    def set_layout_zones(self, zones: list[str]) -> None:
        self.settings.input_zones = [str(zone).strip() for zone in zones[: len(self.settings.input_paths)]]
        self.preflight_ok = False

    def set_output_dir(self, value: str | Path) -> None:
        self.settings.output_dir = Path(value) if str(value).strip() else Path("_plotter_jobs")

    def set_com(self, value: str) -> None:
        self.settings.com = str(value or "").strip() or None

    def set_hardware_confirmed(self, confirmed: bool) -> None:
        self.hardware_confirmed = bool(confirmed)

    def has_input(self) -> bool:
        items = self.settings.normalized_layout_items()
        return bool(items) and all(path.exists() for path, _page, _rotation in items)

    def can_preview(self) -> bool:
        return self.has_input() and not self.operation_running

    def can_generate(self) -> bool:
        return self.can_preview()

    def generation_signature(self) -> tuple[object, ...]:
        settings = self.settings
        return (
            tuple((str(path), page, rotation) for path, page, rotation in settings.normalized_layout_items()),
            tuple(str(zone) for zone in settings.input_zones),
            str(settings.sheet_format),
            settings.sheet_width_mm,
            settings.sheet_height_mm,
            str(settings.sheet_anchor),
            float(settings.sheet_offset_x_mm),
            float(settings.sheet_offset_y_mm),
            int(settings.pass_cols),
            int(settings.pass_rows),
            int(settings.pass_col),
            int(settings.pass_row),
            str(settings.tool),
            bool(settings.handwriting),
            settings.safe_travel_up,
            str(settings.quality),
            str(settings.draw_order),
            str(settings.machine_profile),
            str(settings.calibration_layout),
            str(settings.layout_mode),
            int(settings.layout_page),
            float(settings.layout_margin_mm),
            float(settings.layout_gap_mm),
            str(settings.zone_layout),
            int(settings.output_rotation_deg) % 360,
            bool(settings.mirror_x),
            bool(settings.mirror_y),
        )

    def can_draw(self) -> bool:
        return (
            self.has_input()
            and bool(self.settings.com)
            and bool(self.preflight_ok)
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

    def build_layout_preview(self) -> JobResult:
        return self._run(build_pdf_layout_job)

    def generate_gcode(self) -> JobResult:
        self.settings.preview = False
        self.settings.dry_run = True
        result = self._run(prepare_gcode_job)
        self.preflight_ok = bool(result.ok)
        return result

    def draw(self) -> JobResult:
        if not self.preflight_ok:
            result = JobResult(
                False,
                "Перед рисованием заново сформируйте или проверьте итоговый G-code.",
                output_dir=self.settings.normalized_output_dir(),
                errors=["preflight_required"],
            )
            self.last_result = result
            self.log(result.message)
            return result
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
