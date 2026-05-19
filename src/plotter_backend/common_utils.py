from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Pattern, Tuple


def force_utf8_stdio(*, sys_module=sys) -> None:
    try:
        if hasattr(sys_module.stdout, "reconfigure"):
            sys_module.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys_module.stderr, "reconfigure"):
            sys_module.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def strip_unpaired_surrogates(text: str, replacement: str = " ") -> str:
    if not text:
        return ""
    repl = replacement if replacement is not None else ""
    out: List[str] = []
    for ch in str(text):
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            out.append(repl)
        else:
            out.append(ch)
    return "".join(out)


def safe_log_text(value: object) -> str:
    try:
        text = strip_unpaired_surrogates(str(value), replacement="?")
    except Exception:
        text = "<log-format-error>"
    try:
        return text.encode("utf-8", errors="backslashreplace").decode("utf-8", errors="replace")
    except Exception:
        try:
            return text.encode("ascii", errors="backslashreplace").decode("ascii", errors="replace")
        except Exception:
            return "<log-encode-error>"


def repair_mojibake_text(text: str) -> str:
    """Repair common UTF-8 bytes decoded as cp1251, leaving normal text unchanged."""
    if not text:
        return ""
    s = str(text)
    markers = ("Р", "С", "Ð", "Ñ", "В°", "в„", "вЂ")
    if not any(marker in s for marker in markers):
        return s
    candidates: list[str] = []
    for src_encoding in ("cp1251", "latin1"):
        try:
            candidates.append(s.encode(src_encoding, errors="strict").decode("utf-8", errors="strict"))
        except Exception:
            continue

    def _badness(value: str) -> int:
        return sum(value.count(marker) for marker in markers) + value.count("\ufffd") * 4

    best = min(candidates + [s], key=_badness)
    return best if _badness(best) < _badness(s) else s


def clean_report_value(value: Any) -> Any:
    if isinstance(value, str):
        return repair_mojibake_text(strip_unpaired_surrogates(value, replacement="?"))
    if isinstance(value, list):
        return [clean_report_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(clean_report_value(item) for item in value)
    if isinstance(value, dict):
        return {clean_report_value(key): clean_report_value(item) for key, item in value.items()}
    return value


def safe_logger(logger):
    if not callable(logger):
        return lambda _msg: None

    def _emit(msg: object) -> None:
        text = safe_log_text(msg)
        try:
            logger(text)
        except Exception:
            pass

    return _emit


def resolve_bundle_root(*, file_path: str, sys_module=sys) -> Path:
    meipass = getattr(sys_module, "_MEIPASS", "")
    if meipass:
        return Path(str(meipass)).resolve()
    return Path(file_path).resolve().parent.parent


def resolve_work_root(bundle_root: Path, *, sys_module=sys) -> Path:
    if getattr(sys_module, "frozen", False):
        return Path(sys_module.executable).resolve().parent
    return bundle_root


def load_axis_profile(backend: Any) -> None:
    defaults = {
        "axis": {
            "invert_x": False,
            "invert_y": False,
        },
        "meaning": {
            "x_positive": "right",
            "y_positive": "down",
            "notes": "Default plotter profile: X+ = right, Y+ = down.",
        },
    }

    data = defaults
    for profile_path in [backend.AXIS_PROFILE_PATH, backend.AXIS_PROFILE_FALLBACK_PATH]:
        if not profile_path.exists():
            continue
        try:
            loaded = json.loads(profile_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = {**defaults, **loaded}
                if "axis" in loaded and isinstance(loaded["axis"], dict):
                    axis = data["axis"]
                    axis.update(loaded["axis"])
                    data["axis"] = axis
                break
        except Exception:
            data = defaults

    axis = data.get("axis", {})
    backend.AXIS_INVERT_X = bool(axis.get("invert_x", False))
    backend.AXIS_INVERT_Y = bool(axis.get("invert_y", False))


def tag_name(tag: str, *, tag_re: Pattern[str]) -> str:
    return tag_re.sub(r"\1", tag) if "}" in tag else tag


def parse_floats(text: str, *, float_re: Pattern[str]) -> List[float]:
    return [float(v) for v in float_re.findall(text)]


def parse_length(value: str, *, length_re: Pattern[str]) -> Optional[Tuple[float, str]]:
    match = length_re.match(value.strip())
    if not match:
        return None
    return float(match.group(1)), match.group(2).lower() if match.group(2) else "px"


def unit_to_mm(value: float, unit: str) -> float:
    if unit in {"px", ""}:
        return value * 25.4 / 96.0
    if unit == "mm":
        return value
    if unit == "cm":
        return value * 10.0
    if unit == "in":
        return value * 25.4
    if unit == "pt":
        return value * 25.4 / 72.0
    if unit == "pc":
        return value * 25.4 / 6.0
    return value
