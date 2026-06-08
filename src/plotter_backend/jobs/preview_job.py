from __future__ import annotations

from typing import Callable

from .models import JobResult, JobSettings
from .prepare_job import prepare_job


def preview_job(settings: JobSettings, logger: Callable[[str], None] | None = None) -> JobResult:
    settings.preview = True
    settings.dry_run = True
    return prepare_job(settings, logger)
