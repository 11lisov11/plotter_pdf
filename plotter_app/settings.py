from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "input_path": "",
    "output_dir": "_plotter_jobs",
    "com": "",
    "baud": "115200",
    "machine_profile": "a4_desktop",
    "calibration_layout": "sheet",
    "sheet_format": "a4",
    "sheet_width_mm": None,
    "sheet_height_mm": None,
    "sheet_anchor": "center",
    "sheet_offset_x_mm": 0.0,
    "sheet_offset_y_mm": 0.0,
    "pass_cols": 1,
    "pass_rows": 1,
    "pass_col": 1,
    "pass_row": 1,
    "tool": "pen",
    "handwriting": False,
    "quality": "normal",
    "draw_order": "auto",
    "open_preview": False,
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_settings_path() -> Path:
    return project_root() / "config" / "gui_settings.json"


def load_gui_settings(path: Path | None = None) -> dict[str, Any]:
    target = path or default_settings_path()
    data = dict(DEFAULT_SETTINGS)
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:
            return data
    return data


def save_gui_settings(settings: dict[str, Any], path: Path | None = None) -> Path:
    target = path or default_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(DEFAULT_SETTINGS)
    payload.update(settings)
    target.write_text(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    return value
