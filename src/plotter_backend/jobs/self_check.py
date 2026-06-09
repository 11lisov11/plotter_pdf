from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from .fake_grbl import FakeGrblController, FakeSerial


CORE_MODULES = ["serial", "fitz", "numpy", "PIL"]
OPTIONAL_MODULES = {
    "opencv": "cv2",
    "PySide6": "PySide6",
    "pywin32": "win32com.client",
    "hershey-fonts": "HersheyFonts",
}


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _list_com_ports() -> list[str]:
    try:
        from serial.tools import list_ports  # type: ignore

        return [str(port.device) for port in list_ports.comports()]
    except Exception:
        return []


def _fake_grbl_smoke() -> dict[str, Any]:
    controller = FakeGrblController()
    fake = FakeSerial(controller)
    fake.open()
    fake.read(4096)
    fake.write(b"$X\n")
    unlock = fake.read(4096).decode("ascii", errors="replace").strip()
    fake.write(b"?\n")
    status = fake.read(4096).decode("ascii", errors="replace").strip()
    fake.close()
    return {"ok": unlock == "ok" and status.startswith("<Idle|"), "unlock": unlock, "status": status}


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def _apply_frozen_bundle_checks(root: Path, core: dict[str, bool], optional: dict[str, bool]) -> None:
    if not getattr(sys, "frozen", False):
        return
    if (root / "PlotterPDF_GUI.exe").exists():
        optional["PySide6"] = True
    if (root / "plotter-pdf.exe").exists():
        for module_name in CORE_MODULES:
            core[module_name] = True
        optional["opencv"] = True
        optional["hershey-fonts"] = True


def run_self_check(*, json_out: Path | None = None) -> tuple[int, dict[str, Any]]:
    root = _runtime_root()
    config_path = root / "config" / "axis_profile.json"
    core = {name: _module_available(name) for name in CORE_MODULES}
    optional = {label: _module_available(module) for label, module in OPTIONAL_MODULES.items()}
    _apply_frozen_bundle_checks(root, core, optional)
    fake = _fake_grbl_smoke()
    hardware_requested = os.environ.get("PLOTTER_HARDWARE") == "1"
    hardware_com = os.environ.get("PLOTTER_COM", "").strip()
    hardware = {
        "requested": hardware_requested,
        "com": hardware_com,
        "skipped": not (hardware_requested and hardware_com),
    }
    critical_errors: list[str] = []
    if sys.version_info < (3, 10):
        critical_errors.append("Нужен Python >= 3.10.")
    if not config_path.exists():
        critical_errors.append(f"Не найден config: {config_path}")
    for module_name, ok in core.items():
        if not ok:
            critical_errors.append(f"Не найден основной модуль: {module_name}")
    if not fake["ok"]:
        critical_errors.append("Встроенная проверка Fake GRBL не прошла.")

    optional_missing = [name for name, ok in optional.items() if not ok]
    exit_code = 1 if critical_errors else (2 if optional_missing else 0)
    report: dict[str, Any] = {
        "ok": not critical_errors,
        "exit_code": exit_code,
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "project_root": str(root),
        "axis_profile": str(config_path),
        "axis_profile_exists": config_path.exists(),
        "core_modules": core,
        "optional_modules": optional,
        "optional_missing": optional_missing,
        "com_ports": _list_com_ports(),
        "fake_grbl": fake,
        "hardware": hardware,
        "errors": critical_errors,
    }
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return exit_code, report


def format_self_check_report(report: dict[str, Any]) -> str:
    lines = [
        "Проверка Plotter PDF",
        f"Ядро: {'ок' if report.get('ok') else 'ошибка'}",
        f"Python: {str(report.get('python', '')).splitlines()[0]}",
        f"ОС: {report.get('platform')}",
        f"Папка запуска: {report.get('cwd')}",
        f"axis_profile.json: {'ок' if report.get('axis_profile_exists') else 'не найден'}",
        f"COM-порты: {', '.join(report.get('com_ports') or []) or 'не найдены'}",
        f"Fake GRBL: {'ок' if (report.get('fake_grbl') or {}).get('ok') else 'ошибка'}",
        f"Аппаратные тесты: {'запрошены' if not (report.get('hardware') or {}).get('skipped') else 'пропущены'}",
    ]
    missing = report.get("optional_missing") or []
    if missing:
        lines.append("Необязательные компоненты отсутствуют: " + ", ".join(str(x) for x in missing))
    errors = report.get("errors") or []
    if errors:
        lines.append("Ошибки:")
        lines.extend(f"- {err}" for err in errors)
    return "\n".join(lines)
