from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


BUILTIN_MACHINE_PROFILES: dict[str, dict[str, Any]] = {
    "a4_desktop": {
        "name": "a4_desktop",
        "label": "Станок 1 — настольный плоттер A4",
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
        "connection": {
            "protocol": "grbl_1_1",
            "baud": "115200",
        },
        "motion": {
            "feed_travel_mm_min": 15000.0,
            "feed_draw_mm_min": 12000.0,
            "home_x_mm": 0.0,
            "home_y_mm": 0.0,
            "go_home_before_draw": True,
            "go_home_after_draw": True,
        },
        "pen": {
            "lift_mode": "z",
            "z_up_mm": 0.0,
            "z_down_mm": 11.9,
            "z_feed_down_approach_mm_min": 700.0,
            "z_feed_down_touch_mm_min": 180.0,
            "z_feed_up_mm_min": 700.0,
            "z_feed_up_final_mm_min": 220.0,
            "safe_lift_feed_mm_min": 800.0,
            "z_soft_down_mm": 0.8,
            "z_soft_up_mm": 0.5,
            "z_travel_lift_mm": 3.5,
            "safe_travel_up": False,
            "startup_force_lift_mm": 4.0,
            "fast_handwriting_profile": True,
            "technical_pen_profile": True,
        },
    },
    "a2_corexy": {
        "name": "a2_corexy",
        "label": "Станок 2 — плоттер A2 CoreXY",
        "kinematics": "CoreXY",
        "work_area": {
            "min_x_mm": 0.0,
            "max_x_mm": 390.0,
            "min_y_mm": 0.0,
            "max_y_mm": 580.0,
            "offset_x_mm": 0.0,
            "offset_y_mm": 0.0,
            "origin": "lower_left",
            "x_positive": "right",
            "y_positive": "up",
        },
        "paper": {
            "default_sheet": "a2",
            "source_mirror_y": True,
            "a2_mm": [420.0, 594.0],
            "inactive_short_side_mm": 30.0,
            "inactive_long_side_mm": 14.0,
        },
        "connection": {
            "protocol": "grbl_1_1",
            "baud": "115200",
            "usb_driver": "CH340",
            "port_hints": ["CH340", "wch.cn", "USB-SERIAL"],
        },
        "motion": {
            "feed_travel_mm_min": 3200.0,
            "feed_draw_mm_min": 1500.0,
            "controlled_g1_motion": True,
            "home_x_mm": 0.0,
            "home_y_mm": 0.0,
            "go_home_before_draw": True,
            "go_home_after_draw": True,
        },
        "pen": {
            "lift_mode": "z",
            "z_up_mm": 1.0,
            "z_down_mm": -5.0,
            "z_feed_down_approach_mm_min": 2000.0,
            "z_feed_down_touch_mm_min": 2000.0,
            "z_feed_up_mm_min": 2000.0,
            "z_feed_up_final_mm_min": 2000.0,
            "safe_lift_feed_mm_min": 2000.0,
            "z_soft_down_mm": 0.0,
            "z_soft_up_mm": 0.0,
            "z_travel_lift_mm": 4.0,
            "safe_travel_up": True,
            "startup_force_lift_mm": 0.0,
            "fast_handwriting_profile": False,
            "technical_pen_profile": False,
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
        # Windows editors and PowerShell commonly save JSON with an UTF-8 BOM.
        # Accept both forms so the packaged profile can always be loaded.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
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
