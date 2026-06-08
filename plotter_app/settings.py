from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.plotter_backend.jobs.models import JobSettings

DEFAULT_SETTINGS_PATH = Path("config/gui_settings.json")
DEFAULT_TEMPLATE_PATH = Path("config/gui_settings.default.json")


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> JobSettings:
    template = DEFAULT_TEMPLATE_PATH if DEFAULT_TEMPLATE_PATH.exists() else None
    source = path if path.exists() else template
    if source is None:
        return JobSettings()
    data = json.loads(source.read_text(encoding="utf-8"))
    allowed = set(JobSettings.__dataclass_fields__)
    return JobSettings(**{k: v for k, v in data.items() if k in allowed})


def save_settings(settings: JobSettings, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")


def as_jsonable(settings: JobSettings) -> dict[str, Any]:
    return asdict(settings)
