from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QStandardPaths


ORG_NAME = "PlotterStudio"
APP_NAME = "PlotterStudio"


def _app_data_root() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".plotter_studio"
    root.mkdir(parents=True, exist_ok=True)
    return root


def app_data_dir() -> Path:
    return _app_data_root()


def logs_dir() -> Path:
    path = _app_data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file_path() -> Path:
    return logs_dir() / "plotter_studio.log"


def state_snapshot_path() -> Path:
    return _app_data_root() / "last_state.json"


@dataclass
class AppSettingsData:
    com_port: str = "COM11"
    tool_mode: str = "pencil"
    theme_mode: str = "auto"  # auto | light | dark
    sheet_format: str = "a4"  # work | a4 | a3 | notebook | custom
    custom_width_mm: float = 165.0
    custom_height_mm: float = 205.0
    sheet_anchor: str = "lower_left"  # center | lower_left | upper_left | lower_right | upper_right
    sheet_offset_x_mm: float = 0.0
    sheet_offset_y_mm: float = 0.0
    a3_two_pass: bool = False
    a3_pass_index: int = 1
    calibrate_before_draw: bool = True
    z_step_mm: float = 5.0
    z_feed: float = 140.0
    last_file: str = ""
    log_drawer_open: bool = False
    quality_profile: str = "normal"  # fast | normal | high
    force_text_to_path: bool = True
    exact_geometry_mode: bool = True
    safe_travel_lift: bool = True
    strict_one_to_one: bool = False
    last_preview_svg: str = ""


class SettingsStore:
    def __init__(self) -> None:
        self._qsettings = QSettings(ORG_NAME, APP_NAME)

    def load(self) -> AppSettingsData:
        data = AppSettingsData()
        data.com_port = self._qsettings.value("connection/com_port", data.com_port, type=str)
        data.tool_mode = self._qsettings.value("plot/tool_mode", data.tool_mode, type=str)
        data.theme_mode = self._qsettings.value("ui/theme_mode", data.theme_mode, type=str)
        data.sheet_format = self._qsettings.value("sheet/format", data.sheet_format, type=str)
        data.custom_width_mm = self._qsettings.value("sheet/custom_width_mm", data.custom_width_mm, type=float)
        data.custom_height_mm = self._qsettings.value("sheet/custom_height_mm", data.custom_height_mm, type=float)
        data.sheet_anchor = self._qsettings.value("sheet/anchor", data.sheet_anchor, type=str)
        data.sheet_offset_x_mm = self._qsettings.value("sheet/offset_x_mm", data.sheet_offset_x_mm, type=float)
        data.sheet_offset_y_mm = self._qsettings.value("sheet/offset_y_mm", data.sheet_offset_y_mm, type=float)
        data.a3_two_pass = self._qsettings.value("sheet/a3_two_pass", data.a3_two_pass, type=bool)
        data.a3_pass_index = self._qsettings.value("sheet/a3_pass_index", data.a3_pass_index, type=int)
        data.calibrate_before_draw = self._qsettings.value(
            "sheet/calibrate_before_draw", data.calibrate_before_draw, type=bool
        )
        data.z_step_mm = self._qsettings.value("manual/z_step_mm", data.z_step_mm, type=float)
        data.z_feed = self._qsettings.value("manual/z_feed", data.z_feed, type=float)
        data.last_file = self._qsettings.value("file/last_path", data.last_file, type=str)
        data.log_drawer_open = self._qsettings.value("ui/log_drawer_open", data.log_drawer_open, type=bool)
        data.quality_profile = self._qsettings.value("draw/quality_profile", data.quality_profile, type=str)
        data.force_text_to_path = self._qsettings.value("draw/force_text_to_path", data.force_text_to_path, type=bool)
        data.exact_geometry_mode = self._qsettings.value("draw/exact_geometry_mode", data.exact_geometry_mode, type=bool)
        data.safe_travel_lift = self._qsettings.value("draw/safe_travel_lift", data.safe_travel_lift, type=bool)
        data.strict_one_to_one = self._qsettings.value("draw/strict_one_to_one", data.strict_one_to_one, type=bool)
        data.last_preview_svg = self._qsettings.value("draw/last_preview_svg", data.last_preview_svg, type=str)
        if data.sheet_anchor not in {"center", "lower_left", "upper_left", "lower_right", "upper_right"}:
            data.sheet_anchor = "lower_left"
        data.a3_pass_index = 1 if int(data.a3_pass_index) <= 1 else 2
        return data

    def save(self, data: AppSettingsData) -> None:
        self._qsettings.setValue("connection/com_port", data.com_port)
        self._qsettings.setValue("plot/tool_mode", data.tool_mode)
        self._qsettings.setValue("ui/theme_mode", data.theme_mode)
        self._qsettings.setValue("sheet/format", data.sheet_format)
        self._qsettings.setValue("sheet/custom_width_mm", float(data.custom_width_mm))
        self._qsettings.setValue("sheet/custom_height_mm", float(data.custom_height_mm))
        self._qsettings.setValue("sheet/anchor", data.sheet_anchor)
        self._qsettings.setValue("sheet/offset_x_mm", float(data.sheet_offset_x_mm))
        self._qsettings.setValue("sheet/offset_y_mm", float(data.sheet_offset_y_mm))
        self._qsettings.setValue("sheet/a3_two_pass", bool(data.a3_two_pass))
        self._qsettings.setValue("sheet/a3_pass_index", int(data.a3_pass_index))
        self._qsettings.setValue("sheet/calibrate_before_draw", bool(data.calibrate_before_draw))
        self._qsettings.setValue("manual/z_step_mm", float(data.z_step_mm))
        self._qsettings.setValue("manual/z_feed", float(data.z_feed))
        self._qsettings.setValue("file/last_path", data.last_file)
        self._qsettings.setValue("ui/log_drawer_open", bool(data.log_drawer_open))
        self._qsettings.setValue("draw/quality_profile", data.quality_profile)
        self._qsettings.setValue("draw/force_text_to_path", bool(data.force_text_to_path))
        self._qsettings.setValue("draw/exact_geometry_mode", bool(data.exact_geometry_mode))
        self._qsettings.setValue("draw/safe_travel_lift", bool(data.safe_travel_lift))
        self._qsettings.setValue("draw/strict_one_to_one", bool(data.strict_one_to_one))
        self._qsettings.setValue("draw/last_preview_svg", data.last_preview_svg)
        self._qsettings.sync()
        self._save_snapshot_json(data)

    def _save_snapshot_json(self, data: AppSettingsData) -> None:
        path = state_snapshot_path()
        payload: dict[str, Any] = asdict(data)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
