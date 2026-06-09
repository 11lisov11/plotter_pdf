from __future__ import annotations

from dataclasses import asdict

from .models import JobResult, JobSettings
from .prepare_job import prepare_gcode_job


def preview_job(settings: JobSettings) -> JobResult:
    preview_settings = JobSettings(**asdict(settings))
    preview_settings.preview = True
    preview_settings.dry_run = True
    return prepare_gcode_job(preview_settings)
