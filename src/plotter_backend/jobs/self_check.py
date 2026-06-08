from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path

from .fake_grbl import FakeGrblSerial


def _available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def run_self_check() -> tuple[int, dict]:
    checks: dict = {"core": {}, "optional": {}, "safety": {}, "errors": [], "warnings": []}
    checks["core"].update({"python": sys.version.split()[0], "os": platform.platform(), "cwd": str(Path.cwd())})
    axis = Path("config/axis_profile.json")
    checks["core"]["axis_profile"] = axis.exists()
    for mod in ["src.plotter_pdf_drawer", "src.plotter_backend.gcode.preflight"]:
        checks["core"][mod] = _available(mod)
        if not checks["core"][mod]:
            checks["errors"].append(f"Missing import: {mod}")
    for mod in ["fitz", "serial"]:
        checks["core"][mod] = _available(mod)
        if not checks["core"][mod]:
            checks["errors"].append(f"Missing core dependency: {mod}")
    ports = []
    try:
        from serial.tools import list_ports
        ports = [p.device for p in list_ports.comports()]
    except Exception as exc:
        checks["warnings"].append(f"COM port list unavailable: {exc}")
    checks["core"]["com_ports"] = ports
    checks["optional"] = {
        "inkscape": bool(shutil.which("inkscape")), "pdftocairo": bool(shutil.which("pdftocairo")),
        "word_com": sys.platform.startswith("win") and _available("win32com"),
        "kompas_com": sys.platform.startswith("win") and _available("win32com"),
        "opencv": _available("cv2"), "pyside6": _available("PySide6"),
    }
    fake = FakeGrblSerial()
    fake.open(); fake.write(b"G0 X0\n")
    checks["safety"]["fake_grbl_smoke"] = fake.readline().strip() != b""
    checks["safety"]["hardware_tests_skipped_by_default"] = not (os.environ.get("PLOTTER_HARDWARE") == "1" and os.environ.get("PLOTTER_COM"))
    if checks["errors"]:
        return 1, checks
    if any(not v for v in checks["optional"].values()):
        return 2, checks
    return 0, checks


def format_report(report: dict) -> str:
    lines = ["Plotter PDF self-check"]
    for group in ["core", "optional", "safety"]:
        lines.append(f"\n[{group}]")
        for key, value in report[group].items():
            lines.append(f"- {key}: {value}")
    for key in ["warnings", "errors"]:
        if report.get(key):
            lines.append(f"\n{key.upper()}:")
            lines.extend(f"- {item}" for item in report[key])
    return "\n".join(lines)


def write_json_report(report: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
