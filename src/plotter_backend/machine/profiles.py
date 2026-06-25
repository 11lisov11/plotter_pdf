from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


BUILTIN_MACHINE_PROFILES: dict[str, dict[str, Any]] = {
    "a4_desktop": {
        "name": "a4_desktop",
        "label": "Current A4 desktop plotter",
        "work_area": {
            "min_x_mm": 0.0,
            "max_x_mm": 180.0,
            "min_y_mm": -280.0,
            "max_y_mm": 0.0,
            "offset_x_mm": 0.0,
            "offset_y_mm": -5.0,
        },
        "paper": {
            "default_sheet": "a4",
        },
    },
    "a2_corexy": {
        "name": "a2_corexy",
        "label": "A2 CoreXY pen plotter",
        "kinematics": "CoreXY",
        "work_area": {
            "min_x_mm": 0.0,
            "max_x_mm": 390.0,
            "min_y_mm": -590.0,
            "max_y_mm": 0.0,
            "offset_x_mm": 0.0,
            "offset_y_mm": 0.0,
        },
        "paper": {
            "default_sheet": "a2",
            "a2_mm": [420.0, 594.0],
            "inactive_short_side_mm": 30.0,
            "inactive_long_side_mm": 4.0,
        },
    },
}

PROFILE_ALIASES = {
    "current": "a4_desktop",
    "legacy": "a4_desktop",
    "desktop": "a4_desktop",
    "a4": "a4_desktop",
    "a2": "a2_corexy",
    "corexy": "a2_corexy",
    "a2_core_xy": "a2_corexy",
}


def _normalise_name(name: str | None) -> str:
    raw = (name or "a4_desktop").strip().lower().replace("-", "_").replace(" ", "_")
    return PROFILE_ALIASES.get(raw, raw)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_machine_profiles(*paths: str | Path) -> dict[str, dict[str, Any]]:
    profiles = copy.deepcopy(BUILTIN_MACHINE_PROFILES)
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for name, profile in data.get("profiles", {}).items():
            normalised = _normalise_name(name)
            base = profiles.get(normalised, {"name": normalised})
            merged = _deep_merge(base, profile)
            merged["name"] = normalised
            profiles[normalised] = merged
    return profiles


def available_profile_names(*paths: str | Path) -> tuple[str, ...]:
    return tuple(sorted(load_machine_profiles(*paths).keys()))


def resolve_machine_profile(name: str | None, *paths: str | Path) -> dict[str, Any]:
    profiles = load_machine_profiles(*paths)
    normalised = _normalise_name(name)
    if normalised not in profiles:
        available = ", ".join(sorted(profiles))
        raise ValueError(f"Unknown machine profile {name!r}; available: {available}")
    return copy.deepcopy(profiles[normalised])


def profile_work_area(profile: dict[str, Any]) -> dict[str, float]:
    work = profile.get("work_area") or {}
    required = ("min_x_mm", "max_x_mm", "min_y_mm", "max_y_mm")
    missing = [key for key in required if key not in work]
    if missing:
        raise ValueError(f"Machine profile {profile.get('name', '<unnamed>')!r} misses work_area keys: {missing}")
    return {
        "min_x_mm": float(work["min_x_mm"]),
        "max_x_mm": float(work["max_x_mm"]),
        "min_y_mm": float(work["min_y_mm"]),
        "max_y_mm": float(work["max_y_mm"]),
        "offset_x_mm": float(work.get("offset_x_mm", 0.0)),
        "offset_y_mm": float(work.get("offset_y_mm", 0.0)),
    }
