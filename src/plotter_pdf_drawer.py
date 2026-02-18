#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import argparse
import tempfile
import threading
import time
import os
import base64
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
from typing import Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:
    cv2 = None
    np = None

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext


def _force_utf8_stdio() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
AXIS_PROFILE_PATH = CONFIG_DIR / "axis_profile.json"
LOCAL_TMP_ROOT = ROOT_DIR / "_tmp"

DEFAULT_COM_PORT = "COM5"
DEFAULT_BAUD = "115200"
Z_UP = 0.0
Z_DOWN = 11.9
# Pen timing (seconds): slightly longer lift delay prevents faint drag lines on dense travel.
Z_DELAY_DOWN = 0.06
Z_DELAY_UP = 0.06
Z_DELAY = Z_DELAY_DOWN
# Soft Z motion profile to avoid pen slamming into paper/top stop.
Z_FEED_DOWN_APPROACH = 700.0
Z_FEED_DOWN_TOUCH = 180.0
Z_FEED_UP = 700.0
Z_FEED_UP_FINAL = 220.0
Z_SOFT_DOWN_MM = 0.8
Z_SOFT_UP_MM = 0.5
# Inter-path lift distance from Z-down towards Z-up.
Z_TRAVEL_LIFT_MM = 3.0
# If enabled, XY travel always uses full Z_UP (safest, fewer accidental marks).
# If disabled, uses reduced inter-path lift (faster, but riskier for weak return springs).
SAFE_PEN_TRAVEL_UP = True

# Pen lift mode for GRBL output: 'z' (G0 Z..), or 'spindle' (M3/M5) for pen servo/servo via spindle.
PEN_LIFT_MODE = "z"
PEN_SPINDLE_SPEED = 1000

SAFE_LIFT_MM = 20.0
SAFE_LIFT_FEED = 800.0
GO_HOME_BEFORE_DRAW = True
GO_HOME_AFTER_DRAW = True
HOME_X = 0.0
HOME_Y = 0.0

# NOTE: GRBL will still respect its $110/$111 max rate caps.
FEED_TRAVEL = 15000.0
FEED_DRAW = 12000.0
SEGMENT_TOLERANCE_MM = 8.0
MAX_ARC_SEGMENT_MM = 14.0
CURVE_SEGMENT_MM = 4.0
POLYLINE_COLLINEAR_EPS = 0.40
EMIT_ARCS = True
ARC_FIT_TOL_MM = 0.20
LINE_FIT_TOL_MM = 0.08
ARC_MIN_RADIUS_MM = 0.6
ARC_MIN_SWEEP_DEG = 10.0
GCODE_COORD_DECIMALS = 4
# GRBL rejects arcs (G2/G3 with I/J) if the implied radius from start->center and end->center mismatch too much
# (commonly "error:33"). This check is strict; be conservative and fall back to G1 segments when in doubt.
GRBL_ARC_RADIUS_MATCH_TOL_MM = 0.002
QUALITY_PROFILE = "normal"
SIMPLIFY_ENABLED = True
STITCH_ENABLED = True
STITCH_EPS_MM = 0.08
STITCH_GAP_EPS_MM = 0.15
STITCH_GAP_MAX_ANGLE_DEG = 20.0
REORDER_ENABLED = True
CONTINUOUS_JOIN_EPS = 0.08
CLIP_CONTINUITY_EPS_MM = 0.02
RDP_SIMPLIFY_EPS_MM = 0.0  # 0 disables. Applied only to non-line/non-arc polylines before emitting G1 segments.
SEGMENT_DEDUP_ENABLED = True
SEGMENT_DEDUP_EPS_MM = 0.01
BACKTRACK_SPIKE_MAX_MM = 0.30
FILL_HATCH_ENABLED = False
FILL_HATCH_SPACING_MM = 2.0
FILL_HATCH_ANGLE_DEG = 45.0
FILL_HATCH_MIN_AREA_MM2 = 55.0
FILL_HATCH_MIN_SIDE_MM = 3.0
FILL_HATCH_MIN_SEGMENT_MM = 0.5
AXIS_INVERT_X = False
AXIS_INVERT_Y = False
WORK_AREA_MIN_X = 0.0
WORK_AREA_MAX_X = 180.0
WORK_AREA_MIN_Y = -280.0
WORK_AREA_MAX_Y = 0.0
WORK_AREA_MARGIN = 0.0
WORK_AREA_FRAME_MARGIN = 0.0
WORK_OFFSET_X_MM = 0.0
# Positive "paper up" is negative Y in our coordinate system (Y goes 0 -> -280).
# Total shift requested: +15mm up from original => -15mm in our Y coordinates.
WORK_OFFSET_Y_MM = -15.0
PAGE_MARGIN_LEFT_MM = 20.0
PAGE_MARGIN_RIGHT_MM = 5.0
PAGE_MARGIN_TOP_MM = 10.0
PAGE_MARGIN_BOTTOM_MM = 5.0
PAGE_MARGIN_ENABLED = True
PAGE_MARGIN_A4_ONLY = True
PAGE_A4_TOL_MM = 6.0
AUTO_TRIM_OUTER_FRAME = True
OUTER_FRAME_MIN_FILL_RATIO = 0.70
OUTER_FRAME_COVER_RATIO = 0.97
OUTER_FRAME_SIDE_RATIO = 0.80
OUTER_FRAME_EDGE_EPS_MM = 0.5
FIT_TO_WORK_AREA = True
ALLOW_UPSCALE_TO_WORK_AREA = True
WORK_AREA_EPS = 1e-6
# If fit-to-area would shrink geometry more than this threshold,
# keep 1:1 mm scale and clip to work area instead of distorting dimensions.
# 0 disables strict 1:1 guard (default behavior: always fit to work area).
MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.0
FORCE_TEXT_TO_PATH = False
DEFAULT_QUALITY_PROFILE = "normal"
EXACT_GEOMETRY_MODE = True
IMAGE_CONTOUR_ENABLED = True
IMAGE_CONTOUR_WORD_ONLY = True
IMAGE_CONTOUR_CANNY_LOW = 70
IMAGE_CONTOUR_CANNY_HIGH = 170
IMAGE_CONTOUR_MIN_PATH_MM = 1.6
IMAGE_CONTOUR_MAX_PATHS_PER_IMAGE = 1200
FILL_CENTERLINE_ENABLED = True
FILL_CENTERLINE_MAX_BBOX_MM = 12.0
FILL_CENTERLINE_MAX_BBOX_AREA_MM2 = 120.0
FILL_CENTERLINE_PX_PER_MM = 22.0
FILL_CENTERLINE_MIN_COMPONENT_PX = 4
FILL_CENTERLINE_MIN_PATH_MM = 0.12
FILL_CENTERLINE_MAX_PATHS_PER_GLYPH = 8
FILL_CENTERLINE_LEN_RATIO_MIN = 0.18
FILL_CENTERLINE_LEN_RATIO_MAX = 0.92
# Small filled arrowheads are better drawn as a single open "V" stroke.
# This improves speed and reduces pen chatter on technical dimensions.
ARROWHEAD_OPT_ENABLED = True
ARROWHEAD_MAX_BBOX_MM = 8.0
ARROWHEAD_MIN_AREA_MM2 = 0.05
ARROWHEAD_MAX_AREA_MM2 = 18.0
ARROWHEAD_MIN_ASPECT = 1.20
ARROWHEAD_MAX_FILL_RATIO = 0.78
ARROWHEAD_MAX_VERTICES = 8
ARROWHEAD_MAX_TIP_ANGLE_DEG = 75.0
ARROWHEAD_SIMPLIFY_EPS_MM = 0.08

# Sheet handling / placement.
DEFAULT_NOTEBOOK_WIDTH_MM = 165.0
DEFAULT_NOTEBOOK_HEIGHT_MM = 205.0
SHEET_PRESETS_MM = {
    "work": None,  # full configured work zone
    "a4": (210.0, 297.0),
    "a3": (420.0, 297.0),
    "notebook": (DEFAULT_NOTEBOOK_WIDTH_MM, DEFAULT_NOTEBOOK_HEIGHT_MM),
}
SHEET_ANCHOR_CHOICES = {"center", "lower_left", "upper_left", "lower_right", "upper_right"}
ACTIVE_WORK_AREA_BOUNDS: Optional[Tuple[float, float, float, float]] = None
# Multi-pass window selection (for large sheets split across several passes).
PASS_COLS = 1
PASS_ROWS = 1
PASS_COL = 1
PASS_ROW = 1

# Tool / pencil wear model.
TOOL_MODE = "pen"  # "pen" | "pencil"
PENCIL_STATE_PATH = CONFIG_DIR / "pencil_state.json"
PENCIL_PROFILE_PATH = CONFIG_DIR / "pencil_profile.json"
PENCIL_WEAR_TEST_LAST_PATH = CONFIG_DIR / "pencil_wear_test_last.json"
PENCIL_BASE_Z_DOWN = Z_DOWN
# Wear estimate: conservative default for HB plotting.
# Reference range (external data): ideal wooden HB core ~0.0034 mm/m,
# thin mechanical leads can be ~0.088..0.25 mm/m depending on diameter/pressure.
# Real plotter behavior is usually between these extremes; tune from CLI.
PENCIL_WEAR_MM_PER_M = 0.010
# Additional Z depth per 1.0 mm accumulated tip wear.
PENCIL_Z_COMP_MM_PER_WEAR_MM = 1.0
PENCIL_MAX_COMP_MM = 0.80
PENCIL_REMIND_WEAR_MM = 1.20
# Additional reminder by traveled draw length from last sharpen.
# 0 disables length-based reminder.
PENCIL_SHARPEN_INTERVAL_M = 0.0

INKSCAPE_CANDIDATES = [
    r"C:\Program Files\Inkscape\bin\inkscape.com",
    r"C:\Program Files (x86)\Inkscape\bin\inkscape.com",
    "inkscape.com",
    r"C:\Program Files\Inkscape\bin\inkscape.exe",
    r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe",
    "inkscape",
]
PDFTOCAIRO_CANDIDATES = [
    "pdftocairo",
]
USE_INKSCAPE_PDF_IMPORT = False

CMD_END_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")
FLOAT_RE = re.compile(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
TRANSFORM_RE = re.compile(r"(\w+)\(([^)]*)\)")
TAG_RE = re.compile(r".*}\s*(.*)")
VIEWBOX_RE = re.compile(r"\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
LENGTH_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z%]*)\s*$")
XLINK_NS = "http://www.w3.org/1999/xlink"


@dataclass
class PathItem:
    points: List[Tuple[float, float]]
    closed: bool
    is_fill: bool
    is_stroke: bool
    source_id: int = -1


def load_axis_profile() -> None:
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

    global AXIS_INVERT_X, AXIS_INVERT_Y
    data = defaults
    if AXIS_PROFILE_PATH.exists():
        try:
            loaded = json.loads(AXIS_PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = {**defaults, **loaded}
                # merge nested maps explicitly
                if "axis" in loaded and isinstance(loaded["axis"], dict):
                    axis = data["axis"]
                    axis.update(loaded["axis"])
                    data["axis"] = axis
        except Exception:
            # Keep defaults for safety; no throw.
            data = defaults

    axis = data.get("axis", {})
    AXIS_INVERT_X = bool(axis.get("invert_x", False))
    AXIS_INVERT_Y = bool(axis.get("invert_y", False))


load_axis_profile()


def tag_name(tag: str) -> str:
    return TAG_RE.sub(r"\1", tag) if "}" in tag else tag


def parse_floats(text: str) -> List[float]:
    return [float(v) for v in FLOAT_RE.findall(text)]


def parse_length(value: str) -> Optional[Tuple[float, str]]:
    m = LENGTH_RE.match(value.strip())
    if not m:
        return None
    return float(m.group(1)), m.group(2).lower() if m.group(2) else "px"


TEXT_NODE_TAGS = {"text", "tspan", "textpath", "flowroot", "flowpara", "flowspan"}


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


def run_cmd(cmd: List[str], cwd: Optional[Path] = None, timeout_s: Optional[float] = None) -> Tuple[int, str, str]:
    run_kwargs = {"shell": False}
    if sys.platform.startswith("win") and hasattr(subprocess, "CREATE_NO_WINDOW"):
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        **run_kwargs,
    )
    return result.returncode, result.stdout, result.stderr


def format_duration_hms(seconds: float) -> str:
    s = max(0.0, float(seconds))
    total = int(round(s))
    h = total // 3600
    m = (total % 3600) // 60
    sec = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def load_pencil_state() -> dict:
    state = {
        "total_draw_m": 0.0,
        "estimated_wear_mm": 0.0,
        "jobs_done": 0,
        "last_draw_m": 0.0,
    }
    try:
        if PENCIL_STATE_PATH.exists():
            loaded = json.loads(PENCIL_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
    except Exception:
        pass

    try:
        state["total_draw_m"] = float(state.get("total_draw_m", 0.0) or 0.0)
        state["estimated_wear_mm"] = float(state.get("estimated_wear_mm", 0.0) or 0.0)
        state["jobs_done"] = int(state.get("jobs_done", 0) or 0)
        state["last_draw_m"] = float(state.get("last_draw_m", 0.0) or 0.0)
    except Exception:
        state = {
            "total_draw_m": 0.0,
            "estimated_wear_mm": 0.0,
            "jobs_done": 0,
            "last_draw_m": 0.0,
        }
    return state


def save_pencil_state(state: dict) -> None:
    PENCIL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENCIL_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pencil_profile() -> dict:
    profile = {
        "base_z_down": float(PENCIL_BASE_Z_DOWN),
        "wear_mm_per_m": float(PENCIL_WEAR_MM_PER_M),
        "z_comp_per_wear": float(PENCIL_Z_COMP_MM_PER_WEAR_MM),
        "max_comp_mm": float(PENCIL_MAX_COMP_MM),
        "remind_wear_mm": float(PENCIL_REMIND_WEAR_MM),
        "sharpen_interval_m": float(PENCIL_SHARPEN_INTERVAL_M),
        "sharpen_count": 0,
        "last_sharpen_iso_utc": "",
        "source": "defaults",
    }
    try:
        if PENCIL_PROFILE_PATH.exists():
            loaded = json.loads(PENCIL_PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                profile.update(loaded)
                profile["source"] = "file"
    except Exception:
        pass

    try:
        profile["base_z_down"] = float(profile.get("base_z_down", PENCIL_BASE_Z_DOWN) or PENCIL_BASE_Z_DOWN)
        profile["wear_mm_per_m"] = max(0.0, float(profile.get("wear_mm_per_m", PENCIL_WEAR_MM_PER_M) or PENCIL_WEAR_MM_PER_M))
        profile["z_comp_per_wear"] = max(0.0, float(profile.get("z_comp_per_wear", PENCIL_Z_COMP_MM_PER_WEAR_MM) or PENCIL_Z_COMP_MM_PER_WEAR_MM))
        profile["max_comp_mm"] = max(0.0, float(profile.get("max_comp_mm", PENCIL_MAX_COMP_MM) or PENCIL_MAX_COMP_MM))
        profile["remind_wear_mm"] = max(0.0, float(profile.get("remind_wear_mm", PENCIL_REMIND_WEAR_MM) or PENCIL_REMIND_WEAR_MM))
        profile["sharpen_interval_m"] = max(0.0, float(profile.get("sharpen_interval_m", PENCIL_SHARPEN_INTERVAL_M) or PENCIL_SHARPEN_INTERVAL_M))
        profile["sharpen_count"] = max(0, int(profile.get("sharpen_count", 0) or 0))
        profile["last_sharpen_iso_utc"] = str(profile.get("last_sharpen_iso_utc", "") or "")
    except Exception:
        profile = {
            "base_z_down": float(PENCIL_BASE_Z_DOWN),
            "wear_mm_per_m": float(PENCIL_WEAR_MM_PER_M),
            "z_comp_per_wear": float(PENCIL_Z_COMP_MM_PER_WEAR_MM),
            "max_comp_mm": float(PENCIL_MAX_COMP_MM),
            "remind_wear_mm": float(PENCIL_REMIND_WEAR_MM),
            "sharpen_interval_m": float(PENCIL_SHARPEN_INTERVAL_M),
            "sharpen_count": 0,
            "last_sharpen_iso_utc": "",
            "source": "defaults",
        }
    return profile


def save_pencil_profile(profile: dict) -> None:
    PENCIL_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENCIL_PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_pencil_profile(profile: dict) -> None:
    global PENCIL_BASE_Z_DOWN
    global PENCIL_WEAR_MM_PER_M
    global PENCIL_Z_COMP_MM_PER_WEAR_MM
    global PENCIL_MAX_COMP_MM
    global PENCIL_REMIND_WEAR_MM
    global PENCIL_SHARPEN_INTERVAL_M
    PENCIL_BASE_Z_DOWN = float(profile.get("base_z_down", PENCIL_BASE_Z_DOWN))
    PENCIL_WEAR_MM_PER_M = max(0.0, float(profile.get("wear_mm_per_m", PENCIL_WEAR_MM_PER_M)))
    PENCIL_Z_COMP_MM_PER_WEAR_MM = max(0.0, float(profile.get("z_comp_per_wear", PENCIL_Z_COMP_MM_PER_WEAR_MM)))
    PENCIL_MAX_COMP_MM = max(0.0, float(profile.get("max_comp_mm", PENCIL_MAX_COMP_MM)))
    PENCIL_REMIND_WEAR_MM = max(0.0, float(profile.get("remind_wear_mm", PENCIL_REMIND_WEAR_MM)))
    PENCIL_SHARPEN_INTERVAL_M = max(0.0, float(profile.get("sharpen_interval_m", PENCIL_SHARPEN_INTERVAL_M)))


def build_pencil_profile_snapshot() -> dict:
    return {
        "base_z_down": float(PENCIL_BASE_Z_DOWN),
        "wear_mm_per_m": float(PENCIL_WEAR_MM_PER_M),
        "z_comp_per_wear": float(PENCIL_Z_COMP_MM_PER_WEAR_MM),
        "max_comp_mm": float(PENCIL_MAX_COMP_MM),
        "remind_wear_mm": float(PENCIL_REMIND_WEAR_MM),
        "sharpen_interval_m": float(PENCIL_SHARPEN_INTERVAL_M),
    }


def save_last_wear_test_report(report: dict) -> None:
    PENCIL_WEAR_TEST_LAST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENCIL_WEAR_TEST_LAST_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def load_last_wear_test_report() -> Optional[dict]:
    try:
        if not PENCIL_WEAR_TEST_LAST_PATH.exists():
            return None
        loaded = json.loads(PENCIL_WEAR_TEST_LAST_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return None


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def reset_pencil_state_after_sharpen(logger=print, *, reason: str = "manual") -> None:
    reset_state = {
        "total_draw_m": 0.0,
        "estimated_wear_mm": 0.0,
        "jobs_done": 0,
        "last_draw_m": 0.0,
    }
    save_pencil_state(reset_state)
    profile = load_pencil_profile()
    profile["sharpen_count"] = max(0, int(profile.get("sharpen_count", 0) or 0)) + 1
    profile["last_sharpen_iso_utc"] = _now_iso_utc()
    profile["last_sharpen_reason"] = str(reason or "manual")
    save_pencil_profile(profile)
    logger("Pencil state reset: wear=0.0 mm, draw=0.0 m (sharpen event recorded).")


def pencil_remaining_to_sharpen_m(state: dict) -> Tuple[float, float, float]:
    by_wear = pencil_remaining_draw_m(state)
    by_interval = float("inf")
    if PENCIL_SHARPEN_INTERVAL_M > 1e-9:
        done_m = max(0.0, float(state.get("total_draw_m", 0.0) or 0.0))
        by_interval = max(0.0, float(PENCIL_SHARPEN_INTERVAL_M) - done_m)
    best = min(by_wear, by_interval)
    return best, by_wear, by_interval


def calibrate_pencil_wear_from_last_test(
    *,
    last_good_stage: int,
    first_bad_stage: int = 0,
    safety_factor: float = 0.90,
    logger=print,
) -> Tuple[bool, str]:
    report = load_last_wear_test_report()
    if not report:
        return False, f"No wear-test report found: {PENCIL_WEAR_TEST_LAST_PATH}"
    stages = report.get("stage_stats")
    if not isinstance(stages, list) or not stages:
        return False, "Invalid wear-test report: missing stage_stats."

    by_stage = {}
    for st in stages:
        try:
            idx = int(st.get("stage", 0))
            by_stage[idx] = st
        except Exception:
            continue
    if last_good_stage not in by_stage:
        return False, f"Stage {last_good_stage} not found in last report."
    if first_bad_stage and first_bad_stage not in by_stage:
        return False, f"Stage {first_bad_stage} not found in last report."

    good_cum_m = max(0.0, float(by_stage[last_good_stage].get("cum_mm", 0.0) or 0.0) / 1000.0)
    if good_cum_m <= 1e-9:
        return False, "Invalid cumulative draw length for selected stage."

    threshold_m = good_cum_m
    if first_bad_stage > 0:
        bad_cum_m = max(0.0, float(by_stage[first_bad_stage].get("cum_mm", 0.0) or 0.0) / 1000.0)
        if bad_cum_m > good_cum_m:
            threshold_m = (good_cum_m + bad_cum_m) * 0.5
    safety = min(max(0.50, float(safety_factor)), 0.99)
    sharpen_interval_m = max(0.20, threshold_m * safety)

    profile = load_pencil_profile()
    profile.update(build_pencil_profile_snapshot())
    remind_wear = max(0.05, float(PENCIL_REMIND_WEAR_MM))
    wear_rate = max(1e-6, remind_wear / max(1e-6, threshold_m))

    profile["wear_mm_per_m"] = float(wear_rate)
    profile["sharpen_interval_m"] = float(sharpen_interval_m)
    profile["last_calibration"] = {
        "at_utc": _now_iso_utc(),
        "report_path": str(PENCIL_WEAR_TEST_LAST_PATH),
        "last_good_stage": int(last_good_stage),
        "first_bad_stage": int(first_bad_stage) if first_bad_stage > 0 else None,
        "good_cum_m": float(good_cum_m),
        "threshold_m": float(threshold_m),
        "safety_factor": float(safety),
        "derived_wear_mm_per_m": float(wear_rate),
        "derived_sharpen_interval_m": float(sharpen_interval_m),
    }
    save_pencil_profile(profile)
    apply_pencil_profile(profile)

    msg = (
        f"Pencil calibration saved: wear_mm_per_m={wear_rate:.5f}, "
        f"sharpen_interval_m={sharpen_interval_m:.2f}, "
        f"threshold_m={threshold_m:.2f} (good_stage={last_good_stage}"
    )
    if first_bad_stage > 0:
        msg += f", bad_stage={first_bad_stage}"
    msg += ")."
    logger(msg)
    return True, msg


def show_pencil_status(logger=print) -> None:
    state = load_pencil_state()
    profile = load_pencil_profile()
    apply_pencil_profile(profile)
    rem_best, rem_wear, rem_interval = pencil_remaining_to_sharpen_m(state)
    rem_best_txt = "inf" if not math.isfinite(rem_best) else f"{rem_best:.2f}"
    rem_wear_txt = "inf" if not math.isfinite(rem_wear) else f"{rem_wear:.2f}"
    rem_interval_txt = "inf" if not math.isfinite(rem_interval) else f"{rem_interval:.2f}"
    logger(
        "Pencil status: "
        f"base_z={PENCIL_BASE_Z_DOWN:.3f}, wear_rate={PENCIL_WEAR_MM_PER_M:.5f} mm/m, "
        f"z_comp={PENCIL_Z_COMP_MM_PER_WEAR_MM:.3f}, max_comp={PENCIL_MAX_COMP_MM:.3f}, "
        f"remind_wear={PENCIL_REMIND_WEAR_MM:.3f}, sharpen_interval_m={PENCIL_SHARPEN_INTERVAL_M:.2f}"
    )
    logger(
        "State: "
        f"draw_total={float(state.get('total_draw_m', 0.0) or 0.0):.2f} m, "
        f"wear={float(state.get('estimated_wear_mm', 0.0) or 0.0):.3f} mm, jobs={int(state.get('jobs_done', 0) or 0)}"
    )
    logger(
        f"Remaining before sharpen: {rem_best_txt} m (wear-rule={rem_wear_txt}, interval-rule={rem_interval_txt})."
    )


def pencil_effective_z_down(base_z_down: float, state: dict) -> Tuple[float, float]:
    wear = max(0.0, float(state.get("estimated_wear_mm", 0.0) or 0.0))
    comp = min(PENCIL_MAX_COMP_MM, wear * PENCIL_Z_COMP_MM_PER_WEAR_MM)
    return base_z_down + comp, comp


def apply_pencil_wear_update(state: dict, draw_length_mm: float) -> dict:
    draw_m = max(0.0, float(draw_length_mm)) / 1000.0
    wear_add = draw_m * max(0.0, float(PENCIL_WEAR_MM_PER_M))
    state["total_draw_m"] = float(state.get("total_draw_m", 0.0) or 0.0) + draw_m
    state["estimated_wear_mm"] = float(state.get("estimated_wear_mm", 0.0) or 0.0) + wear_add
    state["jobs_done"] = int(state.get("jobs_done", 0) or 0) + 1
    state["last_draw_m"] = draw_m
    return state


def pencil_remaining_draw_m(state: dict) -> float:
    wear_now = max(0.0, float(state.get("estimated_wear_mm", 0.0) or 0.0))
    wear_left = max(0.0, float(PENCIL_REMIND_WEAR_MM) - wear_now)
    rate = max(0.0, float(PENCIL_WEAR_MM_PER_M))
    if rate <= 1e-12:
        return float("inf")
    return wear_left / rate


def find_inkscape() -> str:
    for candidate in INKSCAPE_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return str(Path(found))
        if Path(candidate).is_file():
            return str(Path(candidate))
    raise RuntimeError("Inkscape not found. Install and add it to PATH.")


def find_pdftocairo() -> str:
    for candidate in PDFTOCAIRO_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return str(Path(found))
        if Path(candidate).is_file():
            return str(Path(candidate))
    raise RuntimeError("pdftocairo not found.")


def detect_com_port(preferred: Optional[str] = None) -> str:
    try:
        import serial  # type: ignore
        import serial.tools.list_ports  # type: ignore
    except Exception:
        return preferred or DEFAULT_COM_PORT

    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return preferred or DEFAULT_COM_PORT

    available = {p.device.upper(): p.device for p in ports if p.device}

    def _com_num(device: str) -> int:
        m = re.match(r"COM(\d+)$", device.upper())
        if not m:
            return 10**9
        try:
            return int(m.group(1))
        except Exception:
            return 10**9

    def _is_writable(device: str) -> bool:
        try:
            s = serial.Serial(device, 115200, timeout=0.2, write_timeout=0.2)
            s.close()
            return True
        except Exception:
            return False

    # Explicit preference always wins if available.
    if preferred:
        p = available.get(preferred.upper())
        if p:
            return p

    # Auto mode: prefer active Bluetooth SPP ports.
    bt_ports = []
    for p in ports:
        text = " ".join(
            [
                str(getattr(p, "description", "") or ""),
                str(getattr(p, "manufacturer", "") or ""),
                str(getattr(p, "hwid", "") or ""),
            ]
        ).lower()
        if "bluetooth" in text or "rfcomm" in text or "bthenum" in text:
            bt_ports.append(p.device)
    for dev in sorted(set(bt_ports), key=_com_num):
        if _is_writable(dev):
            return dev

    # Fallback preference order for USB/known ports.
    candidates = ["COM6", "COM5", "COM4", "COM3", "COM7", "COM8", "COM9", "COM10"]
    for candidate in candidates:
        dev = available.get(candidate)
        if dev:
            return dev

    # Last resort: first available by COM number.
    devices = sorted((p.device for p in ports if p.device), key=_com_num)
    if devices:
        return devices[0]
    return preferred or DEFAULT_COM_PORT


def get_inkscape_version(exe: str) -> Tuple[int, int, int]:
    rc, out, err = run_cmd([exe, "--version"], timeout_s=10.0)
    text = (out + "\n" + err).strip()
    m = re.search(r"Inkscape\s*v?(\d+)\.(\d+)(?:\.(\d+))?", text, re.IGNORECASE)
    if not m:
        return 1, 0, 0
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3) or 0)
    return major, minor, patch

def mat_mul(m1: Tuple[float, float, float, float, float, float], m2: Tuple[float, float, float, float, float, float]):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a2 * a1 + c2 * b1,
        b2 * a1 + d2 * b1,
        a2 * c1 + c2 * d1,
        b2 * c1 + d2 * d1,
        a2 * e1 + c2 * f1 + e2,
        b2 * e1 + d2 * f1 + f2,
    )


def mat_apply(m: Tuple[float, float, float, float, float, float], p: Tuple[float, float]) -> Tuple[float, float]:
    x, y = p
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def parse_transform(value: str) -> Tuple[float, float, float, float, float, float]:
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, raw in TRANSFORM_RE.findall(value):
        params = parse_floats(raw)
        if not params:
            continue
        if name == "matrix" and len(params) == 6:
            op = tuple(params)
        elif name == "translate":
            tx = params[0]
            ty = params[1] if len(params) > 1 else 0.0
            op = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale":
            sx = params[0]
            sy = params[1] if len(params) > 1 else params[0]
            op = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate":
            angle = math.radians(params[0])
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            if len(params) >= 3:
                cx, cy = params[1], params[2]
                op = (
                    cos_a, sin_a, -sin_a, cos_a,
                    cx - cos_a * cx + sin_a * cy,
                    cy - sin_a * cx - cos_a * cy,
                )
            else:
                op = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
        elif name == "skewX":
            a = math.radians(params[0])
            op = (1.0, 0.0, math.tan(a), 1.0, 0.0, 0.0)
        elif name == "skewY":
            a = math.radians(params[0])
            op = (1.0, math.tan(a), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        matrix = mat_mul(matrix, op)
    return matrix


def infer_scale(root: ET.Element) -> float:
    viewbox = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    width = root.attrib.get("width", "100")
    height = root.attrib.get("height", "100")

    if not viewbox:
        return 1.0
    vb = VIEWBOX_RE.match(viewbox.strip())
    if not vb:
        return 1.0
    vb_w = float(vb.group(3))
    vb_h = float(vb.group(4))

    w_info = parse_length(width)
    h_info = parse_length(height)
    if w_info and h_info and vb_w and vb_h:
        w_mm = unit_to_mm(w_info[0], w_info[1])
        h_mm = unit_to_mm(h_info[0], h_info[1])
        sx = w_mm / vb_w
        sy = h_mm / vb_h
        return (sx + sy) * 0.5
    return 1.0


def parse_path_tokens(path_d: str) -> Iterable[Tuple[str, List[float]]]:
    tokens = [t for t in re.split(r"([MmLlHhVvCcSsQqTtAaZz])", path_d) if t and not t.isspace()]
    if not tokens:
        return
    cmd: Optional[str] = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if CMD_END_RE.fullmatch(token):
            cmd = token
            i += 1
            if cmd in "Zz":
                yield cmd, []
            continue
        if cmd is None:
            raise ValueError("Path starts with coordinates")
        params: List[float] = []
        while i < len(tokens) and not CMD_END_RE.fullmatch(tokens[i]):
            params.extend(parse_floats(tokens[i]))
            i += 1
        yield cmd, params


def cubic_approx(p0, p1, p2, p3, step=CURVE_SEGMENT_MM) -> List[Tuple[float, float]]:
    def bezier_point(a, b, c, d, t):
        mt = 1.0 - t
        return (
            mt * mt * mt * a[0] + 3 * mt * mt * t * b[0] + 3 * mt * t * t * c[0] + t * t * t * d[0],
            mt * mt * mt * a[1] + 3 * mt * mt * t * b[1] + 3 * mt * t * t * c[1] + t * t * t * d[1],
        )

    # Do NOT use chord-length only: it severely underestimates loops where endpoints are close
    # (common in fonts), producing jagged curves. Use a quick polyline length estimate.
    samples = 10
    prev = p0
    length = 0.0
    for i in range(1, samples + 1):
        t = i / samples
        cur = bezier_point(p0, p1, p2, p3, t)
        length += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        prev = cur
    chord = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    length = max(length, chord, 0.0001)

    seg = max(2, int(math.ceil(length / max(step, 0.0001))))
    return [bezier_point(p0, p1, p2, p3, i / seg) for i in range(1, seg + 1)]


def quadratic_approx(p0, p1, p2, step=CURVE_SEGMENT_MM) -> List[Tuple[float, float]]:
    def bezier_point(a, b, c, t):
        mt = 1.0 - t
        return (
            mt * mt * a[0] + 2 * mt * t * b[0] + t * t * c[0],
            mt * mt * a[1] + 2 * mt * t * b[1] + t * t * c[1],
        )

    samples = 10
    prev = p0
    length = 0.0
    for i in range(1, samples + 1):
        t = i / samples
        cur = bezier_point(p0, p1, p2, t)
        length += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        prev = cur
    chord = math.hypot(p2[0] - p0[0], p2[1] - p0[1])
    length = max(length, chord, 0.0001)

    seg = max(2, int(math.ceil(length / max(step, 0.0001))))
    return [bezier_point(p0, p1, p2, i / seg) for i in range(1, seg + 1)]


def arc_to_polyline(p0, rx, ry, angle_deg, large_arc, sweep, p1, step=0.35) -> List[Tuple[float, float]]:
    x1, y1 = p0
    x2, y2 = p1
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(angle_deg % 360)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    rx = abs(rx)
    ry = abs(ry)
    if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
        # Per SVG behavior, identical endpoints on "A/a" represent a zero-length arc.
        # Expanding this case to a full ellipse can create random circles on imported PDFs.
        return []

    dx2 = (x1 - x2) / 2.0
    dy2 = (y1 - y2) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    sign = -1.0 if bool(large_arc) == bool(sweep) else 1.0
    den = (rx * rx * y1p * y1p + ry * ry * x1p * x1p)
    if den <= 1e-15:
        return [(x2, y2)]
    sq = max(0.0, (rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p) / den)
    if not math.isfinite(sq):
        return [(x2, y2)]
    cpx = sign * math.sqrt(sq) * (rx * y1p / ry)
    cpy = sign * math.sqrt(sq) * (-ry * x1p / rx)

    cx = cos_phi * cpx - sin_phi * cpy + (x1 + x2) / 2.0
    cy = sin_phi * cpx + cos_phi * cpy + (y1 + y2) / 2.0
    if not (math.isfinite(cx) and math.isfinite(cy)):
        return [(x2, y2)]

    v1x = (x1p - cpx) / rx
    v1y = (y1p - cpy) / ry
    v2x = (-x1p - cpx) / rx
    v2y = (-y1p - cpy) / ry
    theta1 = math.atan2(v1y, v1x)
    delta = math.atan2(v1x * v2y - v1y * v2x, v1x * v2x + v1y * v2y)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    if sweep and delta < 0:
        delta += 2 * math.pi

    arc_len = abs(delta) * max(rx, ry)
    n = max(1, int(math.ceil(arc_len / max(step, 0.1))))
    n = max(n, 1)
    pts = []
    for i in range(1, n + 1):
        t = theta1 + delta * (i / n)
        x = cx + rx * math.cos(t) * cos_phi - ry * math.sin(t) * sin_phi
        y = cy + rx * math.cos(t) * sin_phi + ry * math.sin(t) * cos_phi
        if not (math.isfinite(x) and math.isfinite(y)):
            return [(x2, y2)]
        pts.append((x, y))
    return pts


def apply_style_filter(style: Optional[dict], tag: str, element: Optional[ET.Element] = None) -> bool:
    if tag != "path":
        return True

    stroke = style_value(style, element, "stroke")
    fill = style_value(style, element, "fill")

    explicit_stroke = "stroke" in style
    explicit_fill = "fill" in style
    if element is not None:
        explicit_stroke = explicit_stroke or ("stroke" in element.attrib)
        explicit_fill = explicit_fill or ("fill" in element.attrib)

    if explicit_stroke and explicit_fill and is_none_style(stroke) and is_none_style(fill):
        return False

    # For path without explicit style, rely on SVG defaults (black fill).
    # Keep geometry to avoid dropping converted text that comes without explicit style attrs.
    return True


def read_style_dict(style: Optional[str]) -> dict:
    if not style:
        return {}
    return {k.strip().lower(): v.strip().lower() for k, _, v in (part.partition(":") for part in style.split(";")) if k.strip()}


def get_href(element: ET.Element) -> Optional[str]:
    href = element.attrib.get("href")
    if not href:
        href = element.attrib.get("xlink:href")
    if not href:
        href = element.attrib.get(f"{{{XLINK_NS}}}href")
    if not href:
        return None
    if href.startswith("#"):
        return href[1:]
    return href


def _length_to_user_units(raw: str, scale_to_mm: float) -> Optional[float]:
    info = parse_length(str(raw or "").strip())
    if info is None:
        return None
    value, unit = info
    if unit in {"", "px"}:
        return float(value)
    # Keep extraction in SVG user units; later we multiply by scale_to_mm.
    mm = unit_to_mm(float(value), unit)
    if abs(scale_to_mm) <= 1e-12:
        return float(value)
    return float(mm / scale_to_mm)


def _decode_image_from_svg_href(href: str, svg_dir: Path) -> Optional["np.ndarray"]:
    if np is None or cv2 is None:
        return None
    href_s = (href or "").strip()
    if not href_s:
        return None

    try:
        if href_s.startswith("data:"):
            m = re.match(r"^data:image/[^;]+;base64,(.+)$", href_s, flags=re.IGNORECASE | re.DOTALL)
            if not m:
                return None
            payload = m.group(1).strip()
            data = base64.b64decode(payload, validate=False)
            arr = np.frombuffer(data, dtype=np.uint8)
            if arr.size == 0:
                return None
            img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            return img

        # file:// URI
        if href_s.lower().startswith("file://"):
            parsed = urlparse(href_s)
            fs_path = unquote(parsed.path or "")
            if re.match(r"^/[a-zA-Z]:/", fs_path):
                fs_path = fs_path[1:]
            path = Path(fs_path)
            if path.exists():
                return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            return None

        # Relative file next to SVG.
        candidate = (svg_dir / unquote(href_s)).resolve()
        if candidate.exists() and candidate.is_file():
            return cv2.imread(str(candidate), cv2.IMREAD_UNCHANGED)
    except Exception:
        return None

    return None


def _extract_image_edge_contours_px(img: "np.ndarray") -> List[List[Tuple[float, float]]]:
    if cv2 is None or np is None or img is None:
        return []

    try:
        if len(img.shape) == 2:
            gray = img
            alpha = None
        else:
            if img.shape[2] == 4:
                alpha = img[:, :, 3]
                bgr = img[:, :, :3]
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                if int(np.max(alpha)) > 0:
                    gray = cv2.bitwise_and(gray, gray, mask=alpha)
            else:
                alpha = None
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    except Exception:
        return []

    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, int(IMAGE_CONTOUR_CANNY_LOW), int(IMAGE_CONTOUR_CANNY_HIGH))

    if alpha is not None and int(np.max(alpha)) > 0:
        _, alpha_mask = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)
        edges = cv2.bitwise_and(edges, alpha_mask)

    kernel = np.ones((2, 2), dtype=np.uint8)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)

    mode = cv2.RETR_EXTERNAL
    contours, _ = cv2.findContours(edges, mode, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return []

    contours = sorted(contours, key=lambda c: float(cv2.arcLength(c, True)), reverse=True)
    if len(contours) > IMAGE_CONTOUR_MAX_PATHS_PER_IMAGE:
        contours = contours[:IMAGE_CONTOUR_MAX_PATHS_PER_IMAGE]

    out: List[List[Tuple[float, float]]] = []
    for c in contours:
        if c is None or len(c) < 3:
            continue
        peri = float(cv2.arcLength(c, True))
        if peri < 18.0:
            continue
        approx = cv2.approxPolyDP(c, epsilon=max(0.6, peri * 0.003), closed=True)
        if approx is None or len(approx) < 3:
            continue
        pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
        if len(pts) < 3:
            continue
        if points_distance(pts[0], pts[-1]) > 1e-6:
            pts.append(pts[0])
        out.append(pts)
    return out


def extract_image_contour_items(svg_path: Path, logger=print) -> List[PathItem]:
    if not IMAGE_CONTOUR_ENABLED or cv2 is None or np is None:
        return []

    try:
        tree = ET.parse(svg_path)
    except Exception:
        return []
    root = tree.getroot()
    scale = infer_scale(root)
    svg_dir = svg_path.parent

    out: List[PathItem] = []
    source_id_seq = 2_000_000

    def walk(node: ET.Element, matrix: Tuple[float, float, float, float, float, float]) -> None:
        nonlocal source_id_seq
        cur_matrix = matrix
        t = node.attrib.get("transform")
        if t:
            cur_matrix = mat_mul(cur_matrix, parse_transform(t))

        if tag_name(node.tag).lower() == "image":
            href = get_href(node) or ""
            img = _decode_image_from_svg_href(href, svg_dir)
            if img is not None:
                x_u = _length_to_user_units(node.attrib.get("x", "0"), scale) or 0.0
                y_u = _length_to_user_units(node.attrib.get("y", "0"), scale) or 0.0
                w_u = _length_to_user_units(node.attrib.get("width", "0"), scale) or 0.0
                h_u = _length_to_user_units(node.attrib.get("height", "0"), scale) or 0.0
                h_px, w_px = img.shape[:2]
                if w_u > 1e-9 and h_u > 1e-9 and w_px > 2 and h_px > 2:
                    px_polys = _extract_image_edge_contours_px(img)
                    added = 0
                    for px_poly in px_polys:
                        mm_poly: List[Tuple[float, float]] = []
                        for px, py in px_poly:
                            # Map pixel contour to image placement box in SVG user units.
                            ux = x_u + (px / max(1.0, float(w_px - 1))) * w_u
                            uy = y_u + (py / max(1.0, float(h_px - 1))) * h_u
                            tx, ty = mat_apply(cur_matrix, (ux, uy))
                            mm_poly.append((tx * scale, ty * scale))
                        mm_poly = simplify_polyline(mm_poly, eps=0.02)
                        if len(mm_poly) < 3:
                            continue
                        if points_distance(mm_poly[0], mm_poly[-1]) > 1e-6:
                            mm_poly.append(mm_poly[0])
                        # Filter tiny noise loops.
                        plen = 0.0
                        for i in range(1, len(mm_poly)):
                            plen += math.hypot(mm_poly[i][0] - mm_poly[i - 1][0], mm_poly[i][1] - mm_poly[i - 1][1])
                        if plen < IMAGE_CONTOUR_MIN_PATH_MM:
                            continue
                        out.append(
                            PathItem(
                                points=mm_poly,
                                closed=True,
                                is_fill=False,
                                is_stroke=True,
                                source_id=source_id_seq,
                            )
                        )
                        added += 1
                    if added > 0 and logger:
                        logger(f"Image contour tracing: +{added} path(s) from embedded raster.")
                    source_id_seq += 1

        for child in list(node):
            walk(child, cur_matrix)

    walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    return out


def parse_color_to_rgb_like(value: str) -> Optional[Tuple[float, float, float, float]]:
    if not value:
        return None
    v = value.strip().lower()
    if v in {"none", "transparent"}:
        return None
    if v in {"white", "#fff", "#ffffff"}:
        return 1.0, 1.0, 1.0, 1.0
    if v.startswith("#") and len(v) == 7:
        try:
            r = int(v[1:3], 16) / 255.0
            g = int(v[3:5], 16) / 255.0
            b = int(v[5:7], 16) / 255.0
            return r, g, b, 1.0
        except Exception:
            return None
    if v.startswith("rgb"):
        m = re.match(r"rgba?\(([^)]+)\)", v)
        if not m:
            return None
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) < 3:
            return None
        try:
            is_pct = "%" in parts[0] or "%" in parts[1] or "%" in parts[2]
            nums = [float(p.rstrip("%")) for p in parts[:3]]
            if is_pct:
                return (nums[0] / 100.0, nums[1] / 100.0, nums[2] / 100.0, 1.0)
            return (nums[0] / 255.0, nums[1] / 255.0, nums[2] / 255.0, 1.0)
        except Exception:
            return None
    return None


def svg_has_text_nodes(svg_path: Path) -> bool:
    try:
        root = ET.parse(svg_path).getroot()
        return any(tag_name(node.tag).lower() in TEXT_NODE_TAGS for node in root.iter())
    except Exception:
        return False


def svg_text_node_count(svg_path: Path) -> int:
    try:
        root = ET.parse(svg_path).getroot()
        return sum(1 for node in root.iter() if tag_name(node.tag).lower() in TEXT_NODE_TAGS)
    except Exception:
        return 0


def convert_svg_text_to_paths(svg_path: Path, logger) -> bool:
    # Many PDFs export text as <text>, which can become unreadable glyph blocks on draw.
    # Running the conversion through Inkscape is reliable and keeps geometry in paths.
    if not svg_has_text_nodes(svg_path):
        return True

    exe = find_inkscape()
    major, _, _ = get_inkscape_version(exe)
    if major >= 1:
        candidates = [
            [
                exe,
                "--batch-process",
                "--actions=select-all;object-to-path;export-text-to-path",
                "--export-type=svg",
                "--export-overwrite",
                f"--export-filename={svg_path}",
                str(svg_path),
            ],
            [
                exe,
                "--batch-process",
                "--actions=select-all;object-to-path;export-text-to-path",
                "--export-plain-svg",
                "--export-overwrite",
                f"--export-filename={svg_path}",
                str(svg_path),
            ],
        ]
    else:
        # Fallback for older Inkscape versions.
        candidates = [
            [
                exe,
                "--batch-process",
                "--actions=select-all;object-to-path;export-text-to-path",
                "--export-overwrite",
                "--export-plain-svg",
                f"--export-filename={svg_path}",
                str(svg_path),
            ],
            [
                exe,
                "-z",
                "-l",
                f"--export-plain-svg={svg_path}",
                str(svg_path),
            ],
        ]

    last_error = ""
    for i, cmd in enumerate(candidates, start=1):
        logger(f"Text->path conversion #{i}: {' '.join([Path(str(cmd[0])).name] + [str(x) for x in cmd[1:]])}")
        rc, out, err = run_cmd(cmd)
        if rc == 0 and not svg_has_text_nodes(svg_path):
            logger("Text converted to SVG paths.")
            return True
        block = (out + "\n" + err).strip()
        logger(f"Text->path conversion #{i} failed or no effect: {block}")
        if block:
            last_error = block

    msg = f"Failed to convert text in SVG to paths. {last_error}".strip() or "Unknown error"
    logger(msg)
    return False


def style_value(style: dict, element: ET.Element, key: str) -> str:
    value = style.get(key)
    if value is not None:
        return value.strip().lower()
    return element.attrib.get(key, "").strip().lower()


def is_none_style(value: Optional[str]) -> bool:
    return value in (None, "", "none", "transparent")


def parse_style_flags(style: dict, element: ET.Element, tag: str) -> Tuple[bool, bool]:
    # Returns tuple (has_stroke, has_fill)
    if is_pure_white_shape(style, element):
        return False, False

    has_stroke = False
    has_fill = False
    if tag == "line":
        stroke = style_value(style, element, "stroke")
        has_stroke = not is_none_style(stroke)
        fill_val = style_value(style, element, "fill")
        has_fill = not is_none_style(fill_val) and fill_val not in {"", "none"}
        return has_stroke, has_fill

    stroke = style_value(style, element, "stroke")
    fill = style_value(style, element, "fill")
    explicit_stroke = "stroke" in style or "stroke" in element.attrib
    explicit_fill = "fill" in style or "fill" in element.attrib

    if tag in {"rect", "polygon", "polyline", "circle", "ellipse", "path"}:
        has_stroke = not is_none_style(stroke) if explicit_stroke else False
        # If fill is not explicitly set, keep SVG default geometry behavior:
        # shape primitives and paths are considered filled.
        if explicit_fill:
            has_fill = not is_none_style(fill)
        else:
            has_fill = True
    else:
        has_stroke = not is_none_style(stroke) if explicit_stroke else False
        if explicit_fill:
            has_fill = not is_none_style(fill)
        else:
            has_fill = not is_none_style(fill)

    # Explicit stroke/fill attributes set to none should not create geometry.
    if explicit_stroke and explicit_fill and not has_stroke and not has_fill:
        return False, False

    # For geometry primitives, if both attributes are absent (no explicit style),
    # keep default drawable behavior for paths/shapes.
    if not explicit_stroke and not explicit_fill and tag in {"line", "polyline", "polygon", "rect", "circle", "ellipse", "path"}:
        if tag == "line":
            has_stroke = True
    return has_stroke, has_fill


def is_nearly_white_fill(elem: ET.Element) -> bool:
    style = read_style_dict(elem.attrib.get("style"))
    fill = style.get("fill", elem.attrib.get("fill", "")).strip().lower()
    if not fill:
        return False
    rgb = parse_color_to_rgb_like(fill)
    if rgb is None:
        return False
    r, g, b, _ = rgb
    if min(r, g, b) < 0.99:
        return False
    opacity = style.get("fill-opacity", elem.attrib.get("fill-opacity", "1")).strip()
    try:
        if float(opacity) < 0.2:
            return False
    except Exception:
        pass
    return True


def is_pure_white_shape(style: dict, element: ET.Element) -> bool:
    fill = style.get("fill", element.attrib.get("fill", "")).strip().lower()
    stroke = style.get("stroke", element.attrib.get("stroke", "")).strip().lower()

    stroke_none = is_none_style(stroke)
    fill_none = is_none_style(fill)
    if fill_none and stroke_none:
        return False

    fill_is_white = False
    stroke_is_white = False
    if fill and not fill_none:
        fill_rgb = parse_color_to_rgb_like(fill)
        fill_is_white = fill_rgb is not None and min(fill_rgb[:3]) >= 0.99
    if stroke and not stroke_none:
        stroke_rgb = parse_color_to_rgb_like(stroke)
        stroke_is_white = stroke_rgb is not None and min(stroke_rgb[:3]) >= 0.99

    if fill_is_white and (stroke_none or stroke_is_white):
        return True
    if stroke_is_white and fill_none:
        return True
    if stroke_is_white and fill_is_white:
        return True

    return False


def is_axis_aligned_rectangle(poly: List[Tuple[float, float]]) -> bool:
    if len(poly) != 5 or poly[0] != poly[-1]:
        return False
    pts = poly[:-1]
    if len({pt for pt in pts}) != 4:
        return False
    xs = {round(p[0], 5) for p in pts}
    ys = {round(p[1], 5) for p in pts}
    if len(xs) != 2 or len(ys) != 2:
        return False
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        if abs(x1 - x2) > 1e-6 and abs(y1 - y2) > 1e-6:
            return False
    return True


def root_page_size_mm(root: ET.Element) -> Tuple[float, float]:
    width = parse_length(root.attrib.get("width", "0"))
    height = parse_length(root.attrib.get("height", "0"))
    if width and height:
        return unit_to_mm(width[0], width[1]), unit_to_mm(height[0], height[1])

    vb = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if vb:
        m = VIEWBOX_RE.match(vb.strip())
        if m:
            return float(m.group(3)), float(m.group(4))
    return 0.0, 0.0


def is_full_page_white_fill_rect(poly: List[Tuple[float, float]], elem: ET.Element, page_w: float, page_h: float) -> bool:
    if not is_axis_aligned_rectangle(poly):
        return False
    if tag_name(elem.tag) != "path":
        return False
    if not is_nearly_white_fill(elem):
        return False
    style = read_style_dict(elem.attrib.get("style"))
    stroke = (style.get("stroke") or elem.attrib.get("stroke") or "").strip().lower()
    if stroke not in {"", "none"}:
        return False
    if abs(page_w) < 1e-6 or abs(page_h) < 1e-6:
        return False
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    area_ratio = ((max(xs) - min(xs)) * (max(ys) - min(ys))) / (page_w * page_h)
    return 0.95 <= area_ratio <= 1.05


def point_line_distance(point: Tuple[float, float], line_a: Tuple[float, float], line_b: Tuple[float, float]) -> float:
    x, y = point
    x1, y1 = line_a
    x2, y2 = line_b
    vx = x2 - x1
    vy = y2 - y1
    wx = x - x1
    wy = y - y1
    vv = vx * vx + vy * vy
    if vv < 1e-12:
        return points_distance(point, line_a)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    px = x1 + t * vx
    py = y1 + t * vy
    return points_distance(point, (px, py))


def solve_3x3(mat: List[List[float]], vec: List[float]) -> Optional[Tuple[float, float, float]]:
    # Gaussian elimination with partial pivoting for a 3x3 system.
    a = [row[:] for row in mat]
    b = vec[:]

    n = 3
    for col in range(n):
        # pivot
        pivot = col
        pivot_val = abs(a[col][col])
        for r in range(col + 1, n):
            v = abs(a[r][col])
            if v > pivot_val:
                pivot = r
                pivot_val = v
        if pivot_val < 1e-12:
            return None
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            b[col], b[pivot] = b[pivot], b[col]

        # eliminate
        div = a[col][col]
        for r in range(col + 1, n):
            factor = a[r][col] / div
            if abs(factor) < 1e-18:
                continue
            for c in range(col, n):
                a[r][c] -= factor * a[col][c]
            b[r] -= factor * b[col]

    # back-substitution
    x = [0.0, 0.0, 0.0]
    for r in range(n - 1, -1, -1):
        s = b[r]
        for c in range(r + 1, n):
            s -= a[r][c] * x[c]
        if abs(a[r][r]) < 1e-12:
            return None
        x[r] = s / a[r][r]
    return float(x[0]), float(x[1]), float(x[2])


def fit_circle_kasa(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float, float]]:
    # Algebraic least-squares circle fit (Kasa). Returns (cx, cy, r, max_radial_err).
    if len(points) < 3:
        return None

    s_xx = s_xy = s_x = 0.0
    s_yy = s_y = 0.0
    s_b = s_xb = s_yb = 0.0
    n = 0
    for x, y in points:
        b = -(x * x + y * y)
        s_xx += x * x
        s_xy += x * y
        s_x += x
        s_yy += y * y
        s_y += y
        s_b += b
        s_xb += x * b
        s_yb += y * b
        n += 1

    mat = [
        [s_xx, s_xy, s_x],
        [s_xy, s_yy, s_y],
        [s_x, s_y, float(n)],
    ]
    vec = [s_xb, s_yb, s_b]
    sol = solve_3x3(mat, vec)
    if sol is None:
        return None

    d, e, f = sol
    cx = -d * 0.5
    cy = -e * 0.5
    rr = cx * cx + cy * cy - f
    if rr <= 1e-12 or not math.isfinite(rr):
        return None
    r = math.sqrt(rr)

    max_err = 0.0
    for x, y in points:
        err = abs(math.hypot(x - cx, y - cy) - r)
        if err > max_err:
            max_err = err
    return float(cx), float(cy), float(r), float(max_err)


def unwrap_angles(angles: List[float]) -> List[float]:
    if not angles:
        return []
    out = [angles[0]]
    two_pi = 2.0 * math.pi
    for a in angles[1:]:
        v = a
        prev = out[-1]
        while v - prev > math.pi:
            v -= two_pi
        while v - prev < -math.pi:
            v += two_pi
        out.append(v)
    return out


def arc_extents_xy(
    start: Tuple[float, float],
    end: Tuple[float, float],
    center: Tuple[float, float],
    cw: bool,
) -> Tuple[float, float, float, float]:
    # Conservative bounding box of a circular arc (includes quadrant extrema if swept).
    cx, cy = center
    x0, y0 = start
    x1, y1 = end
    r = math.hypot(x0 - cx, y0 - cy)
    if r <= 1e-12:
        return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)

    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)

    # Unwrap end relative to start according to direction.
    if cw:
        while a1 > a0:
            a1 -= 2.0 * math.pi
    else:
        while a1 < a0:
            a1 += 2.0 * math.pi

    def in_sweep(a: float) -> bool:
        # Unwrap a near a0.
        v = a
        while v - a0 > math.pi:
            v -= 2.0 * math.pi
        while v - a0 < -math.pi:
            v += 2.0 * math.pi
        if cw:
            while v < a1:
                v += 2.0 * math.pi
            return a1 <= v <= a0
        while v > a1:
            v -= 2.0 * math.pi
        return a0 <= v <= a1

    xs = [x0, x1]
    ys = [y0, y1]
    # Cardinal angles: 0, 90, 180, 270 degrees.
    for ang in (0.0, 0.5 * math.pi, math.pi, 1.5 * math.pi):
        if in_sweep(ang):
            xs.append(cx + r * math.cos(ang))
            ys.append(cy + r * math.sin(ang))

    return min(xs), max(xs), min(ys), max(ys)


def polyline_is_near_line(poly: List[Tuple[float, float]], tol_mm: float) -> bool:
    if len(poly) < 3:
        return False
    a = poly[0]
    b = poly[-1]
    if points_distance(a, b) < 1e-9:
        return False
    max_d = 0.0
    for p in poly[1:-1]:
        d = point_line_distance(p, a, b)
        if d > max_d:
            max_d = d
            if max_d > tol_mm:
                return False
    return True


def polyline_fit_arc(poly: List[Tuple[float, float]], tol_mm: float) -> Optional[Tuple[bool, Tuple[float, float], float, float]]:
    # Try to fit the whole polyline to a circular arc. Returns (cw, center, r, sweep_rad).
    if len(poly) < 3:
        return None

    pts = poly[:]
    # Drop duplicated closure point for fitting.
    if points_distance(pts[0], pts[-1]) <= 1e-6:
        pts = pts[:-1]
    if len(pts) < 3:
        return None

    fit = fit_circle_kasa(pts)
    if fit is None:
        return None
    cx, cy, r, max_err = fit
    if r < ARC_MIN_RADIUS_MM:
        return None
    if max_err > tol_mm:
        return None

    angles = [math.atan2(y - cy, x - cx) for x, y in pts]
    unwrapped = unwrap_angles(angles)
    # Total sweep following the point order.
    sweep = unwrapped[-1] - unwrapped[0]
    if abs(sweep) < math.radians(ARC_MIN_SWEEP_DEG):
        return None

    # Direction: positive sweep => CCW (G3), negative => CW (G2).
    cw = sweep < 0.0
    return cw, (cx, cy), r, sweep


def path_is_closed(poly: List[Tuple[float, float]], eps: float = 1e-6) -> bool:
    return len(poly) >= 4 and points_distance(poly[0], poly[-1]) <= eps


def _rdp_simplify_open(poly: List[Tuple[float, float]], eps: float) -> List[Tuple[float, float]]:
    # RamerвЂ“DouglasвЂ“Peucker for an open polyline. Preserves endpoints.
    if eps <= 0.0 or len(poly) < 3:
        return poly

    keep = [False] * len(poly)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(poly) - 1)]

    while stack:
        a_i, b_i = stack.pop()
        ax, ay = poly[a_i]
        bx, by = poly[b_i]
        max_d = -1.0
        max_i = -1
        for i in range(a_i + 1, b_i):
            d = point_line_distance(poly[i], (ax, ay), (bx, by))
            if d > max_d:
                max_d = d
                max_i = i
        if max_d > eps and max_i != -1:
            keep[max_i] = True
            stack.append((a_i, max_i))
            stack.append((max_i, b_i))

    out = [p for i, p in enumerate(poly) if keep[i]]
    return out if len(out) >= 2 else poly


def rdp_simplify_polyline(poly: List[Tuple[float, float]], eps: float) -> List[Tuple[float, float]]:
    # Simplify open and closed polylines using RDP.
    if eps <= 0.0 or len(poly) < 3:
        return poly

    if not path_is_closed(poly):
        return _rdp_simplify_open(poly, eps)

    # Closed: remove duplicated end point, choose a seam at a low-curvature vertex,
    # simplify as open, then re-close.
    ring = poly[:-1]
    if len(ring) < 4:
        return poly

    # Pick seam at the straightest vertex to reduce visible artifacts at the closure.
    best_i = 0
    best_score = -1.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[(i - 1) % n]
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        ux, uy = (x0 - x1), (y0 - y1)
        vx, vy = (x2 - x1), (y2 - y1)
        un = math.hypot(ux, uy)
        vn = math.hypot(vx, vy)
        if un <= 1e-9 or vn <= 1e-9:
            continue
        dot = max(-1.0, min(1.0, (ux * vx + uy * vy) / (un * vn)))
        # Higher is straighter (dot ~ -1 is 180deg in opposite vectors due to direction).
        # We want angle close to 180deg => dot close to -1.
        score = -dot
        if score > best_score:
            best_score = score
            best_i = i

    rotated = ring[best_i:] + ring[:best_i]
    simplified = _rdp_simplify_open(rotated, eps)
    if len(simplified) < 3:
        return poly

    # Re-close.
    if points_distance(simplified[0], simplified[-1]) <= 1e-6:
        out = simplified
    else:
        out = simplified + [simplified[0]]
    return out


def polygon_area(poly: List[Tuple[float, float]]) -> float:
    if len(poly) < 3:
        return 0.0
    area = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def polygon_bbox(poly: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), max(xs), min(ys), max(ys)


def rotate_point(point: Tuple[float, float], angle_rad: float) -> Tuple[float, float]:
    x, y = point
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (
        x * cos_a + y * sin_a,
        -x * sin_a + y * cos_a,
    )


def rotate_polyline(poly: List[Tuple[float, float]], angle_rad: float) -> List[Tuple[float, float]]:
    if angle_rad == 0.0:
        return list(poly)
    return [rotate_point(p, angle_rad) for p in poly]


def intersects_for_scanline(edges: List[Tuple[Tuple[float, float], Tuple[float, float]]], y: float) -> List[float]:
    xs: List[float] = []
    for p1, p2 in edges:
        x1, y1 = p1
        x2, y2 = p2
        if y1 == y2:
            continue
        if y1 <= y < y2 or y2 <= y < y1:
            t = (y - y1) / (y2 - y1)
            xs.append(x1 + t * (x2 - x1))
    return sorted(xs)


def should_hatch_polygon(poly: List[Tuple[float, float]], closed: bool) -> bool:
    if not closed or len(poly) < 4:
        return False
    if not FILL_HATCH_ENABLED:
        return False

    # Work with unique endpoints.
    ring = poly[:-1] if path_is_closed(poly) else list(poly)
    if len(ring) < 4:
        return False

    area = abs(polygon_area(ring))
    if area < FILL_HATCH_MIN_AREA_MM2:
        return False
    min_x, max_x, min_y, max_y = polygon_bbox(ring)
    if (max_x - min_x) < FILL_HATCH_MIN_SIDE_MM or (max_y - min_y) < FILL_HATCH_MIN_SIDE_MM:
        return False
    return True


def hatch_polygon(
    contours: List[List[Tuple[float, float]]],
    spacing: float = FILL_HATCH_SPACING_MM,
    angle_deg: float = FILL_HATCH_ANGLE_DEG,
    min_segment: float = FILL_HATCH_MIN_SEGMENT_MM,
) -> List[List[Tuple[float, float]]]:
    if spacing <= 0:
        return []
    angle_rad = math.radians(angle_deg)

    valid_contours = [c[:-1] if path_is_closed(c) else c for c in contours if len(c) >= 3]
    if not valid_contours:
        return []

    rotated = [rotate_polyline(c, angle_rad) for c in valid_contours]
    edges: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for poly in rotated:
        if len(poly) < 2:
            continue
        for i in range(len(poly)):
            p1 = poly[i]
            p2 = poly[(i + 1) % len(poly)]
            if p1 == p2:
                continue
            edges.append((p1, p2))

    if not edges:
        return []

    min_x = min(p[0] for e in edges for p in e)
    max_x = max(p[0] for e in edges for p in e)
    min_y = min(p[1] for e in edges for p in e)
    max_y = max(p[1] for e in edges for p in e)
    if not math.isfinite(min_x + max_x + min_y + max_y):
        return []

    out: List[List[Tuple[float, float]]] = []
    # Keep a tiny margin to reduce duplicates from boundary coincidences.
    scan_y = min_y + 1e-6
    while scan_y <= max_y - 1e-6:
        xs = intersects_for_scanline(edges, scan_y)
        if len(xs) % 2 == 1:
            xs = xs[:-1]
        for i in range(0, len(xs), 2):
            if i + 1 >= len(xs):
                break
            x1, x2 = xs[i], xs[i + 1]
            if (x2 - x1) < min_segment:
                continue
            p1 = rotate_point((x1, scan_y), -angle_rad)
            p2 = rotate_point((x2, scan_y), -angle_rad)
            if points_distance(p1, p2) >= min_segment:
                out.append([p1, p2])
        scan_y += spacing
    return out


def polyline_length(poly: List[Tuple[float, float]]) -> float:
    if len(poly) < 2:
        return 0.0
    return sum(points_distance(poly[i], poly[i + 1]) for i in range(len(poly) - 1))


def total_draw_length_mm(polylines: List[List[Tuple[float, float]]]) -> float:
    return sum(polyline_length(poly) for poly in polylines if len(poly) >= 2)


def _skeletonize_binary(mask: "np.ndarray") -> "np.ndarray":
    # Morphological skeletonization: robust and dependency-light (OpenCV only).
    if cv2 is None or np is None:
        return mask
    img = (mask > 0).astype(np.uint8) * 255
    skel = np.zeros_like(img)
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    max_iter = max(256, int(img.shape[0] + img.shape[1]) * 2)
    for _ in range(max_iter):
        eroded = cv2.erode(img, kernel)
        opened = cv2.dilate(eroded, kernel)
        temp = cv2.subtract(img, opened)
        skel = cv2.bitwise_or(skel, temp)
        img = eroded
        if cv2.countNonZero(img) == 0:
            break
    return skel


def _skeleton_to_pixel_paths(skel: "np.ndarray") -> List[List[Tuple[int, int]]]:
    if np is None:
        return []
    ys, xs = np.where(skel > 0)
    if len(xs) == 0:
        return []
    pixels = {(int(x), int(y)) for x, y in zip(xs.tolist(), ys.tolist())}

    def neigh8(p: Tuple[int, int]) -> List[Tuple[int, int]]:
        x, y = p
        out = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                q = (x + dx, y + dy)
                if q in pixels:
                    out.append(q)
        return out

    nbr = {p: neigh8(p) for p in pixels}
    degree = {p: len(nbr[p]) for p in pixels}
    nodes = {p for p, d in degree.items() if d != 2}
    visited_edges = set()
    out_paths: List[List[Tuple[int, int]]] = []

    def edge_key(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    def walk_from(a: Tuple[int, int], b: Tuple[int, int]) -> List[Tuple[int, int]]:
        path = [a, b]
        e = edge_key(a, b)
        visited_edges.add(e)
        prev, cur = a, b
        guard = 0
        while guard < 100000:
            guard += 1
            # For node->node edges stop once we hit the next node.
            if cur in nodes and cur != path[0]:
                break
            cand = [q for q in nbr[cur] if q != prev]
            if not cand:
                break
            nxt = None
            for q in cand:
                ek = edge_key(cur, q)
                if ek not in visited_edges:
                    nxt = q
                    break
            if nxt is None:
                nxt = cand[0]
            ek = edge_key(cur, nxt)
            if ek in visited_edges:
                if nxt == path[0]:
                    path.append(nxt)
                break
            visited_edges.add(ek)
            path.append(nxt)
            prev, cur = cur, nxt
        return path

    # First trace from endpoints/junctions.
    for p in sorted(nodes):
        for q in nbr[p]:
            if edge_key(p, q) in visited_edges:
                continue
            path = walk_from(p, q)
            if len(path) >= 2:
                out_paths.append(path)

    # Then trace remaining pure loops (all degree == 2).
    for p in sorted(pixels):
        for q in nbr[p]:
            if edge_key(p, q) in visited_edges:
                continue
            path = walk_from(p, q)
            if len(path) >= 3:
                out_paths.append(path)

    return out_paths


def centerline_fill_group(group: List["PathItem"]) -> List[List[Tuple[float, float]]]:
    # Convert tiny fill-only glyph contours to single-stroke centerlines.
    if cv2 is None or np is None or not FILL_CENTERLINE_ENABLED:
        return []

    contours: List[List[Tuple[float, float]]] = []
    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")
    for item in group:
        pts = item.points
        if len(pts) < 3:
            continue
        ring = pts[:-1] if path_is_closed(pts) else list(pts)
        if len(ring) < 3:
            continue
        contours.append(ring)
        bx0, bx1, by0, by1 = polygon_bbox(ring)
        min_x = min(min_x, bx0)
        max_x = max(max_x, bx1)
        min_y = min(min_y, by0)
        max_y = max(max_y, by1)

    if not contours:
        return []

    w = max_x - min_x
    h = max_y - min_y
    if w <= 0.0 or h <= 0.0:
        return []
    if w > FILL_CENTERLINE_MAX_BBOX_MM or h > FILL_CENTERLINE_MAX_BBOX_MM:
        return []
    if (w * h) > FILL_CENTERLINE_MAX_BBOX_AREA_MM2:
        return []

    scale = max(4.0, float(FILL_CENTERLINE_PX_PER_MM))
    margin = 4
    img_w = int(math.ceil(w * scale)) + 1 + (2 * margin)
    img_h = int(math.ceil(h * scale)) + 1 + (2 * margin)
    if img_w < 8 or img_h < 8 or img_w > 4096 or img_h > 4096:
        return []

    # Build fill mask using even-odd parity (xor) so holes are preserved.
    mask = np.zeros((img_h, img_w), dtype=np.uint8)
    for ring in contours:
        arr = []
        for x, y in ring:
            px = int(round((x - min_x) * scale)) + margin
            py = int(round((y - min_y) * scale)) + margin
            arr.append((px, py))
        if len(arr) < 3:
            continue
        poly = np.array(arr, dtype=np.int32).reshape((-1, 1, 2))
        tmp = np.zeros_like(mask)
        cv2.fillPoly(tmp, [poly], 255)
        mask = cv2.bitwise_xor(mask, tmp)

    if int(cv2.countNonZero(mask)) < FILL_CENTERLINE_MIN_COMPONENT_PX:
        return []

    skel = _skeletonize_binary(mask)
    if int(cv2.countNonZero(skel)) < FILL_CENTERLINE_MIN_COMPONENT_PX:
        return []

    # Remove tiny skeleton specks.
    labels_n, labels, stats, _ = cv2.connectedComponentsWithStats((skel > 0).astype(np.uint8), connectivity=8)
    for i in range(1, labels_n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < FILL_CENTERLINE_MIN_COMPONENT_PX:
            skel[labels == i] = 0

    pix_paths = _skeleton_to_pixel_paths(skel)
    out: List[List[Tuple[float, float]]] = []
    for path in pix_paths:
        if len(path) < 2:
            continue
        mm = [((x - margin) / scale + min_x, (y - margin) / scale + min_y) for x, y in path]
        mm = simplify_polyline(mm, eps=0.02)
        if polyline_length(mm) < FILL_CENTERLINE_MIN_PATH_MM:
            continue
        out.append(mm)
    return out


def centerline_is_usable(
    group: List["PathItem"],
    centerlines: List[List[Tuple[float, float]]],
) -> bool:
    # Reject noisy centerline outputs that fragment a glyph into many tiny strokes.
    # In those cases, fallback to original contours is visually cleaner.
    if not centerlines:
        return False
    if len(centerlines) > FILL_CENTERLINE_MAX_PATHS_PER_GLYPH:
        return False

    source_len = 0.0
    for item in group:
        if len(item.points) >= 2:
            source_len += polyline_length(item.points)
    if source_len <= 1e-9:
        return False

    center_len = sum(polyline_length(poly) for poly in centerlines if len(poly) >= 2)
    if center_len <= 1e-9:
        return False

    ratio = center_len / source_len
    return FILL_CENTERLINE_LEN_RATIO_MIN <= ratio <= FILL_CENTERLINE_LEN_RATIO_MAX


def _vertex_angle_deg(prev_pt: Tuple[float, float], pt: Tuple[float, float], next_pt: Tuple[float, float]) -> float:
    ux = prev_pt[0] - pt[0]
    uy = prev_pt[1] - pt[1]
    vx = next_pt[0] - pt[0]
    vy = next_pt[1] - pt[1]
    nu = math.hypot(ux, uy)
    nv = math.hypot(vx, vy)
    if nu <= 1e-12 or nv <= 1e-12:
        return 180.0
    dot = (ux * vx + uy * vy) / (nu * nv)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def _is_convex_ring(ring: List[Tuple[float, float]]) -> bool:
    n = len(ring)
    if n < 3:
        return False
    sign = 0
    for i in range(n):
        p0 = ring[i - 1]
        p1 = ring[i]
        p2 = ring[(i + 1) % n]
        z = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if abs(z) <= 1e-9:
            continue
        cur = 1 if z > 0 else -1
        if sign == 0:
            sign = cur
        elif sign != cur:
            return False
    return True


def _simplify_ring_for_arrow(poly: List[Tuple[float, float]], eps: float) -> List[Tuple[float, float]]:
    if len(poly) < 3:
        return []
    ring = poly[:-1] if path_is_closed(poly) else list(poly)
    if len(ring) < 3:
        return []
    closed = ring + [ring[0]]
    simp = rdp_simplify_polyline(closed, max(1e-6, eps))
    if path_is_closed(simp):
        simp = simp[:-1]
    cleaned = simplify_polyline(simp, eps=0.01)
    return cleaned if len(cleaned) >= 3 else []


def arrowhead_v_polyline(poly: List[Tuple[float, float]]) -> Optional[List[Tuple[float, float]]]:
    if not ARROWHEAD_OPT_ENABLED:
        return None
    ring = _simplify_ring_for_arrow(poly, ARROWHEAD_SIMPLIFY_EPS_MM)
    n = len(ring)
    if n < 3 or n > ARROWHEAD_MAX_VERTICES:
        return None
    if not _is_convex_ring(ring):
        return None

    min_x, max_x, min_y, max_y = polygon_bbox(ring)
    w = max_x - min_x
    h = max_y - min_y
    if w <= 1e-9 or h <= 1e-9:
        return None
    if w > ARROWHEAD_MAX_BBOX_MM or h > ARROWHEAD_MAX_BBOX_MM:
        return None
    area = abs(polygon_area(ring))
    if area < ARROWHEAD_MIN_AREA_MM2 or area > ARROWHEAD_MAX_AREA_MM2:
        return None
    fill_ratio = area / max(1e-9, w * h)
    if fill_ratio > ARROWHEAD_MAX_FILL_RATIO:
        return None
    aspect = max(w, h) / max(1e-9, min(w, h))
    if aspect < ARROWHEAD_MIN_ASPECT:
        return None

    tip_idx = -1
    tip_angle = 180.0
    for i in range(n):
        a = _vertex_angle_deg(ring[i - 1], ring[i], ring[(i + 1) % n])
        if a < tip_angle:
            tip_angle = a
            tip_idx = i
    if tip_idx < 0 or tip_angle > ARROWHEAD_MAX_TIP_ANGLE_DEG:
        return None

    left_ids: List[int] = []
    i = (tip_idx - 1) % n
    while i != (tip_idx + 1) % n:
        left_ids.append(i)
        i = (i - 1) % n
    right_ids: List[int] = []
    i = (tip_idx + 1) % n
    while i != (tip_idx - 1) % n:
        right_ids.append(i)
        i = (i + 1) % n
    if not left_ids or not right_ids:
        return None

    tip = ring[tip_idx]
    base_l = max(left_ids, key=lambda k: points_distance(tip, ring[k]))
    base_r = max(right_ids, key=lambda k: points_distance(tip, ring[k]))
    p_l = ring[base_l]
    p_r = ring[base_r]
    if points_distance(p_l, tip) < 0.2 or points_distance(p_r, tip) < 0.2:
        return None
    if points_distance(p_l, p_r) < 0.1:
        return None
    return [p_l, tip, p_r]


def split_arrowhead_fill_group(
    group: List["PathItem"],
) -> Tuple[List[List[Tuple[float, float]]], List["PathItem"]]:
    if not ARROWHEAD_OPT_ENABLED:
        return [], group
    arrow_lines: List[List[Tuple[float, float]]] = []
    rest: List[PathItem] = []
    for item in group:
        if not item.closed or len(item.points) < 3:
            rest.append(item)
            continue
        vpoly = arrowhead_v_polyline(item.points)
        if vpoly is None:
            rest.append(item)
            continue
        arrow_lines.append(vpoly)
    return arrow_lines, rest


def simplify_polyline(poly: List[Tuple[float, float]], eps: float = 1e-6) -> List[Tuple[float, float]]:
    if not poly:
        return []
    if not SIMPLIFY_ENABLED:
        return poly
    out: List[Tuple[float, float]] = [poly[0]]
    for p in poly[1:]:
        if points_distance(out[-1], p) > eps:
            out.append(p)

    # Drop only tiny immediate A->B->A spikes (artifact), keep long A->B->A strokes intact.
    if len(out) >= 3 and BACKTRACK_SPIKE_MAX_MM > 0:
        collapsed: List[Tuple[float, float]] = []
        for p in out:
            if (
                len(collapsed) >= 2
                and points_distance(collapsed[-2], p) <= eps
                and points_distance(collapsed[-2], collapsed[-1]) <= BACKTRACK_SPIKE_MAX_MM
            ):
                collapsed.pop()
                continue
            collapsed.append(p)
        out = collapsed

    # Reduce collinear noise from text/vector import and tiny font artifacts.
    if len(out) < 3:
        return out
    col = [out[0]]
    for p in out[1:]:
        if len(col) >= 2:
            last = col[-1]
            prev = col[-2]
            if point_line_distance(last, prev, p) <= POLYLINE_COLLINEAR_EPS:
                col[-1] = p
                continue
        col.append(p)

    # Ensure path tail still ends in same direction; cleanup duplicate points after collinear pass.
    if len(col) < 2:
        return col
    cleaned = [col[0]]
    for p in col[1:]:
        if points_distance(cleaned[-1], p) > eps:
            cleaned.append(p)
    return cleaned


def parse_points(points_text: str) -> List[Tuple[float, float]]:
    nums = parse_floats(points_text)
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def transform_points(points: List[Tuple[float, float]], matrix: Tuple[float, float, float, float, float, float], scale: float) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for x, y in points:
        tx, ty = mat_apply(matrix, (x, y))
        out.append((tx * scale, ty * scale))
    return out


def bounds_polylines(polylines: List[List[Tuple[float, float]]]) -> Tuple[float, float, float, float]:
    min_x = min((p[0] for poly in polylines for p in poly), default=0.0)
    max_x = max((p[0] for poly in polylines for p in poly), default=0.0)
    min_y = min((p[1] for poly in polylines for p in poly), default=0.0)
    max_y = max((p[1] for poly in polylines for p in poly), default=0.0)
    return min_x, max_x, min_y, max_y


def bounds_path_items(path_items: List[PathItem]) -> Optional[Tuple[float, float, float, float]]:
    points = [p for item in path_items for p in item.points]
    if not points:
        return None
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    return min_x, max_x, min_y, max_y


def normalize_path_units_to_page(
    items: List[PathItem],
    page_w_mm: float,
    page_h_mm: float,
    logger=print,
) -> Tuple[List[PathItem], float]:
    # Some PDF->SVG converters output path coordinates in px while the page size is in mm.
    # Detect near-uniform scale mismatch and normalize to page units before cropping/fitting.
    if not items or page_w_mm <= 0.0 or page_h_mm <= 0.0:
        return items, 1.0
    b = bounds_path_items(items)
    if b is None:
        return items, 1.0
    x0, x1, y0, y1 = b
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    if w <= 0.0 or h <= 0.0:
        return items, 1.0

    rx = w / page_w_mm
    ry = h / page_h_mm
    if rx < 1.5 or ry < 1.5:
        return items, 1.0
    if rx > 20.0 or ry > 20.0:
        return items, 1.0
    if abs(rx - ry) / max(rx, ry) > 0.20:
        return items, 1.0

    ratio = 0.5 * (rx + ry)
    if ratio <= 0.0:
        return items, 1.0
    scale = 1.0 / ratio

    for it in items:
        if not it.points:
            continue
        it.points = [(x * scale, y * scale) for x, y in it.points]

    if logger:
        logger(
            "Normalized SVG units to page mm: "
            f"ratioв‰€{ratio:.3f} (rx={rx:.3f}, ry={ry:.3f}), scale={scale:.6f}"
        )
    return items, scale


def poly_inside_bbox(
    poly: List[Tuple[float, float]],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    eps: float,
) -> bool:
    return all((x_min - eps) <= x <= (x_max + eps) and (y_min - eps) <= y <= (y_max + eps) for x, y in poly)


def filter_outer_frame_path_items(
    items: List[PathItem],
    logger,
) -> Tuple[List[PathItem], List[PathItem]]:
    if not AUTO_TRIM_OUTER_FRAME or len(items) < 2:
        return items, []

    all_bounds = bounds_path_items(items)
    if all_bounds is None:
        return items, []
    all_x0, all_x1, all_y0, all_y1 = all_bounds
    all_w = all_x1 - all_x0
    all_h = all_y1 - all_y0
    all_area = abs(all_w * all_h)
    if all_w <= 0.0 or all_h <= 0.0:
        return items, []

    bbox_tol = max(OUTER_FRAME_EDGE_EPS_MM, min(all_w, all_h) * 0.002)

    def candidate_score(it: PathItem) -> Optional[Tuple[float, Tuple[float, float, float, float]]]:
        if not it.points or not it.closed:
            return None
        if not is_axis_aligned_rectangle(it.points):
            return None
        if not it.is_stroke:
            return None

        x0, x1, y0, y1 = bounds_polylines([it.points])
        w = x1 - x0
        h = y1 - y0
        if w <= 0.0 or h <= 0.0:
            return None

        width_ratio = w / all_w
        height_ratio = h / all_h
        area_ratio = (w * h) / all_area if all_area > 0 else 0.0
        if width_ratio < OUTER_FRAME_SIDE_RATIO or height_ratio < OUTER_FRAME_SIDE_RATIO:
            return None
        if area_ratio < OUTER_FRAME_MIN_FILL_RATIO:
            return None

        touches_left = abs(x0 - all_x0) <= bbox_tol
        touches_right = abs(x1 - all_x1) <= bbox_tol
        touches_bottom = abs(y0 - all_y0) <= bbox_tol
        touches_top = abs(y1 - all_y1) <= bbox_tol
        if not (touches_left and touches_right and touches_bottom and touches_top):
            return None

        inner: List[PathItem] = [other for other in items if other is not it]
        if not inner:
            return None

        all_inner = 0
        inside = 0
        for other in inner:
            all_inner += len(other.points)
            for pt in other.points:
                x, y = pt
                if poly_inside_bbox([pt], x0, x1, y0, y1, bbox_tol):
                    inside += 1

        if all_inner == 0:
            return None
        cover_ratio = inside / float(all_inner)
        if cover_ratio < OUTER_FRAME_COVER_RATIO:
            return None

        score = area_ratio + 0.5 * cover_ratio + 0.05 * max(width_ratio, height_ratio)
        return score, (x0, x1, y0, y1)

    scored = []
    for item in items:
        if not item.points:
            continue
        score = candidate_score(item)
        if score is not None:
            scored.append((score[0], score[1], item))

    if not scored:
        # Fallback: some PDFs export borders as separate axis-aligned lines instead of one closed path.
        edge_candidates = {"left": [], "right": [], "bottom": [], "top": []}
        for item in items:
            if not item.is_stroke or not item.points:
                continue
            x0, x1, y0, y1 = bounds_polylines([item.points])
            w = x1 - x0
            h = y1 - y0
            if w <= 0.0 and h <= 0.0:
                continue

            center_x = (x0 + x1) * 0.5
            center_y = (y0 + y1) * 0.5
            # Vertical candidates.
            if abs(w) <= bbox_tol and (h / all_h) >= OUTER_FRAME_SIDE_RATIO:
                if abs(x0 - all_x0) <= bbox_tol or abs(x1 - all_x0) <= bbox_tol or abs(center_x - all_x0) <= bbox_tol:
                    edge_candidates["left"].append((h, item))
                if abs(x0 - all_x1) <= bbox_tol or abs(x1 - all_x1) <= bbox_tol or abs(center_x - all_x1) <= bbox_tol:
                    edge_candidates["right"].append((h, item))
            # Horizontal candidates.
            if abs(h) <= bbox_tol and (w / all_w) >= OUTER_FRAME_SIDE_RATIO:
                if abs(y0 - all_y0) <= bbox_tol or abs(y1 - all_y0) <= bbox_tol or abs(center_y - all_y0) <= bbox_tol:
                    edge_candidates["bottom"].append((w, item))
                if abs(y0 - all_y1) <= bbox_tol or abs(y1 - all_y1) <= bbox_tol or abs(center_y - all_y1) <= bbox_tol:
                    edge_candidates["top"].append((w, item))

        if all(edge_candidates.values()):
            left = sorted(edge_candidates["left"], key=lambda e: e[0], reverse=True)[0][1]
            right = sorted(edge_candidates["right"], key=lambda e: e[0], reverse=True)[0][1]
            bottom = sorted(edge_candidates["bottom"], key=lambda e: e[0], reverse=True)[0][1]
            top = sorted(edge_candidates["top"], key=lambda e: e[0], reverse=True)[0][1]
            chosen_ids = {id(left), id(right), id(bottom), id(top)}
            if len(chosen_ids) >= 4:
                logger(
                    "Detected outer border from separate axis-aligned lines: "
                    f"left/right/bottom/top candidates={len(edge_candidates['left'])}/{len(edge_candidates['right'])}/"
                    f"{len(edge_candidates['bottom'])}/{len(edge_candidates['top'])}"
                )
                return [it for it in items if id(it) not in chosen_ids], [it for it in items if id(it) in chosen_ids]

        return items, []

    scored.sort(key=lambda x: x[0], reverse=True)
    _, chosen_bounds, chosen_item = scored[0]
    logger(
        "Detected outer border candidate: "
        f"bbox=({chosen_bounds[0]:.2f},{chosen_bounds[1]:.2f},{chosen_bounds[2]:.2f},{chosen_bounds[3]:.2f}) "
        f"points={len(chosen_item.points)}"
    )
    return [it for it in items if it is not chosen_item], [chosen_item]


def clip_path_items_to_rect(
    items: List[PathItem],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    logger=print,
) -> Tuple[List[PathItem], int, int]:
    if not items:
        return [], 0, 0

    clipped_all: List[PathItem] = []
    dropped_segments = 0
    written_segments = 0
    for item in items:
        if len(item.points) < 2:
            continue
        out_poly: List[Tuple[float, float]] = []
        for i in range(1, len(item.points)):
            x1, y1 = item.points[i - 1]
            x2, y2 = item.points[i]
            clipped = clip_segment_to_rect(x1, y1, x2, y2, min_x, max_x, min_y, max_y)
            if clipped is None:
                dropped_segments += 1
                if out_poly and len(out_poly) >= 2:
                    p = PathItem(
                        points=out_poly,
                        closed=False,
                        is_fill=item.is_fill,
                        is_stroke=item.is_stroke,
                        source_id=item.source_id,
                    )
                    p.closed = path_is_closed(p.points)
                    clipped_all.append(p)
                out_poly = []
                continue

            (cx1, cy1), (cx2, cy2) = clipped
            cx1, cy1 = clamp_to_work_area(cx1, cy1, min_x, max_x, min_y, max_y)
            cx2, cy2 = clamp_to_work_area(cx2, cy2, min_x, max_x, min_y, max_y)

            if not point_in_work_area(cx1, cy1, min_x, max_x, min_y, max_y):
                dropped_segments += 1
                if out_poly and len(out_poly) >= 2:
                    p = PathItem(
                        points=out_poly,
                        closed=False,
                        is_fill=item.is_fill,
                        is_stroke=item.is_stroke,
                        source_id=item.source_id,
                    )
                    p.closed = path_is_closed(p.points)
                    clipped_all.append(p)
                out_poly = []
                continue

            if not out_poly:
                out_poly = [(cx1, cy1)]

            if points_distance((cx1, cy1), out_poly[-1]) > CLIP_CONTINUITY_EPS_MM:
                p = PathItem(
                    points=out_poly,
                    closed=False,
                    is_fill=item.is_fill,
                    is_stroke=item.is_stroke,
                    source_id=item.source_id,
                )
                p.closed = path_is_closed(p.points)
                clipped_all.append(p)
                out_poly = [(cx1, cy1)]
            else:
                # Snap to maintain continuity after numeric clipping.
                cx1, cy1 = out_poly[-1]

            if points_distance((cx2, cy2), out_poly[-1]) > 1e-6:
                out_poly.append((cx2, cy2))
                written_segments += 1

        if len(out_poly) >= 2:
            p = PathItem(
                points=out_poly,
                closed=False,
                is_fill=item.is_fill,
                is_stroke=item.is_stroke,
                source_id=item.source_id,
            )
            p.closed = path_is_closed(p.points)
            clipped_all.append(p)

    if logger:
        if dropped_segments:
            logger(
                f"Page/content clip: kept {written_segments} visible segments, dropped {dropped_segments} out-of-area segments."
            )
    return clipped_all, written_segments, dropped_segments


def svg_page_size_mm(svg_path: Path) -> Tuple[float, float]:
    try:
        return root_page_size_mm(ET.parse(svg_path).getroot())
    except Exception:
        return 0.0, 0.0


def clip_to_content_area(
    items: List[PathItem],
    page_w: float,
    page_h: float,
    logger=print,
) -> Tuple[List[PathItem], bool]:
    if (
        not PAGE_MARGIN_ENABLED
        or page_w <= 1.0
        or page_h <= 1.0
        or (PAGE_MARGIN_LEFT_MM <= 0 and PAGE_MARGIN_RIGHT_MM <= 0 and PAGE_MARGIN_TOP_MM <= 0 and PAGE_MARGIN_BOTTOM_MM <= 0)
    ):
        return items, False

    left = PAGE_MARGIN_LEFT_MM
    right = PAGE_MARGIN_RIGHT_MM
    top = PAGE_MARGIN_TOP_MM
    bottom = PAGE_MARGIN_BOTTOM_MM
    if left < 0 or right < 0 or top < 0 or bottom < 0:
        logger("Warning: page margin is negative, skipping content area crop.")
        return items, False

    if PAGE_MARGIN_A4_ONLY:
        # Р“РћРЎРў-РїРѕР»СЏ (20/5/10/5) РєРѕСЂСЂРµРєС‚РЅС‹ С‚РѕР»СЊРєРѕ РґР»СЏ A4. РќР° "РјР°Р»РµРЅСЊРєРёС…" PDF (С„СЂР°РіРјРµРЅС‚С‹)
        # С‚Р°РєР°СЏ РѕР±СЂРµР·РєР° РІС‹СЂРµР¶РµС‚ СЂРµР°Р»СЊРЅСѓСЋ РіРµРѕРјРµС‚СЂРёСЋ.
        is_a4 = (abs(page_w - 210.0) <= PAGE_A4_TOL_MM and abs(page_h - 297.0) <= PAGE_A4_TOL_MM) or (
            abs(page_w - 297.0) <= PAGE_A4_TOL_MM and abs(page_h - 210.0) <= PAGE_A4_TOL_MM
        )
        if not is_a4:
            logger(f"Page {page_w:.1f}x{page_h:.1f} mm not A4; skipping content area crop.")
            return items, False

    content_min_x = left
    content_max_x = page_w - right
    content_min_y = top
    content_max_y = page_h - bottom

    if not (content_min_x < content_max_x and content_min_y < content_max_y):
        logger("Warning: invalid page content area, skipping content area crop.")
        return items, False

    clipped_items, _, dropped = clip_path_items_to_rect(items, content_min_x, content_max_x, content_min_y, content_max_y, logger=logger)
    if not clipped_items:
        logger("Content area crop removed all paths; keeping original geometry.")
        return items, False

    logger(
        f"Applied content area crop: x({content_min_x:.1f},{content_max_x:.1f}) y({content_min_y:.1f},{content_max_y:.1f}) "
        f"dropped segments={dropped}"
    )
    return clipped_items, True


def base_work_area_bounds() -> Tuple[float, float, float, float]:
    min_x = min(WORK_AREA_MIN_X + WORK_OFFSET_X_MM, WORK_AREA_MAX_X + WORK_OFFSET_X_MM)
    max_x = max(WORK_AREA_MIN_X + WORK_OFFSET_X_MM, WORK_AREA_MAX_X + WORK_OFFSET_X_MM)
    min_y = min(WORK_AREA_MIN_Y + WORK_OFFSET_Y_MM, WORK_AREA_MAX_Y + WORK_OFFSET_Y_MM)
    max_y = max(WORK_AREA_MIN_Y + WORK_OFFSET_Y_MM, WORK_AREA_MAX_Y + WORK_OFFSET_Y_MM)
    return min_x, max_x, min_y, max_y


def work_area_bounds() -> Tuple[float, float, float, float]:
    if ACTIVE_WORK_AREA_BOUNDS is not None:
        x0, x1, y0, y1 = ACTIVE_WORK_AREA_BOUNDS
        return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    return base_work_area_bounds()


def configure_active_work_area(
    *,
    sheet_format: str = "work",
    sheet_width_mm: Optional[float] = None,
    sheet_height_mm: Optional[float] = None,
    anchor: str = "center",
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
    logger=print,
) -> None:
    global ACTIVE_WORK_AREA_BOUNDS

    base_min_x, base_max_x, base_min_y, base_max_y = base_work_area_bounds()
    base_w = max(1e-9, base_max_x - base_min_x)
    base_h = max(1e-9, base_max_y - base_min_y)

    fmt = (sheet_format or "work").strip().lower()
    if fmt == "custom":
        if sheet_width_mm is None or sheet_height_mm is None:
            raise ValueError("--sheet-format custom requires --sheet-width-mm and --sheet-height-mm")
        target_w = float(sheet_width_mm)
        target_h = float(sheet_height_mm)
    elif fmt in SHEET_PRESETS_MM:
        preset = SHEET_PRESETS_MM[fmt]
        if preset is None:
            target_w = base_w
            target_h = base_h
        else:
            target_w, target_h = preset
            if sheet_width_mm is not None:
                target_w = float(sheet_width_mm)
            if sheet_height_mm is not None:
                target_h = float(sheet_height_mm)
    else:
        raise ValueError(f"Unknown --sheet-format '{sheet_format}'.")

    if target_w <= 0.0 or target_h <= 0.0:
        raise ValueError("Sheet width/height must be > 0.")

    # Drawing cannot exceed actual machine workspace.
    active_w = min(target_w, base_w)
    active_h = min(target_h, base_h)
    if target_w > base_w or target_h > base_h:
        logger(
            f"Sheet {target_w:.1f}x{target_h:.1f} mm is larger than workspace {base_w:.1f}x{base_h:.1f} mm. "
            "Using workspace-sized active area (overflow must be tiled or clipped)."
        )

    anc = (anchor or "center").strip().lower()
    if anc not in SHEET_ANCHOR_CHOICES:
        raise ValueError(f"Unknown --sheet-anchor '{anchor}'.")

    if anc == "center":
        x0 = base_min_x + (base_w - active_w) * 0.5
        y0 = base_min_y + (base_h - active_h) * 0.5
    elif anc == "lower_left":
        x0 = base_min_x
        y0 = base_min_y
    elif anc == "upper_left":
        x0 = base_min_x
        y0 = base_max_y - active_h
    elif anc == "lower_right":
        x0 = base_max_x - active_w
        y0 = base_min_y
    else:  # upper_right
        x0 = base_max_x - active_w
        y0 = base_max_y - active_h

    x0 += float(offset_x_mm)
    y0 += float(offset_y_mm)

    # Keep active window inside machine base area.
    x0 = min(max(x0, base_min_x), base_max_x - active_w)
    y0 = min(max(y0, base_min_y), base_max_y - active_h)
    x1 = x0 + active_w
    y1 = y0 + active_h

    ACTIVE_WORK_AREA_BOUNDS = (x0, x1, y0, y1)
    logger(
        f"Active area: {active_w:.1f}x{active_h:.1f} mm, "
        f"bounds x({x0:.3f},{x1:.3f}) y({y0:.3f},{y1:.3f}), "
        f"sheet={fmt}, anchor={anc}, offset=({offset_x_mm:.2f},{offset_y_mm:.2f})"
    )


def plan_tiled_passes_for_sheet(sheet_w_mm: float, sheet_h_mm: float) -> dict:
    min_x, max_x, min_y, max_y = work_area_bounds()
    area_w = max(1e-9, max_x - min_x)
    area_h = max(1e-9, max_y - min_y)

    def _passes(w: float, h: float) -> Tuple[int, int, int]:
        nx = int(math.ceil(w / area_w))
        ny = int(math.ceil(h / area_h))
        return nx, ny, nx * ny

    nx1, ny1, n1 = _passes(sheet_w_mm, sheet_h_mm)
    nx2, ny2, n2 = _passes(sheet_h_mm, sheet_w_mm)
    if n2 < n1:
        best = {
            "rotated": True,
            "sheet_w_mm": sheet_h_mm,
            "sheet_h_mm": sheet_w_mm,
            "nx": nx2,
            "ny": ny2,
            "passes": n2,
        }
    else:
        best = {
            "rotated": False,
            "sheet_w_mm": sheet_w_mm,
            "sheet_h_mm": sheet_h_mm,
            "nx": nx1,
            "ny": ny1,
            "passes": n1,
        }

    # Best possible scale if user insists on exactly 2 passes.
    two_pass_scales = []
    for w, h in ((sheet_w_mm, sheet_h_mm), (sheet_h_mm, sheet_w_mm)):
        s_side = min((2.0 * area_w) / w, area_h / h)
        s_stack = min(area_w / w, (2.0 * area_h) / h)
        two_pass_scales.append(max(s_side, s_stack))
    best["max_two_pass_scale"] = max(two_pass_scales)
    best["area_w_mm"] = area_w
    best["area_h_mm"] = area_h
    return best


def resolve_sheet_size_mm(
    *,
    sheet_format: str,
    sheet_width_mm: Optional[float],
    sheet_height_mm: Optional[float],
) -> Tuple[float, float]:
    fmt = (sheet_format or "work").strip().lower()
    if fmt == "custom":
        if sheet_width_mm is None or sheet_height_mm is None:
            raise ValueError("--sheet-format custom requires --sheet-width-mm and --sheet-height-mm")
        return float(sheet_width_mm), float(sheet_height_mm)
    if fmt in SHEET_PRESETS_MM:
        preset = SHEET_PRESETS_MM[fmt]
        if preset is None:
            min_x, max_x, min_y, max_y = work_area_bounds()
            return max_x - min_x, max_y - min_y
        w, h = preset
        if sheet_width_mm is not None:
            w = float(sheet_width_mm)
        if sheet_height_mm is not None:
            h = float(sheet_height_mm)
        return float(w), float(h)
    raise ValueError(f"Unknown --sheet-format '{sheet_format}'.")


def _tile_window_start(total_mm: float, window_mm: float, idx0: int, count: int) -> float:
    if count <= 1 or total_mm <= window_mm + 1e-9:
        return 0.0
    span = max(0.0, total_mm - window_mm)
    step = span / float(count - 1)
    s = float(idx0) * step
    if s < 0.0:
        return 0.0
    if s > span:
        return span
    return s


def compute_pass_shift(
    source_w_mm: float,
    source_h_mm: float,
    window_w_mm: float,
    window_h_mm: float,
) -> Tuple[float, float, dict]:
    cols = max(1, int(PASS_COLS))
    rows = max(1, int(PASS_ROWS))
    col = min(max(1, int(PASS_COL)), cols)
    row = min(max(1, int(PASS_ROW)), rows)

    w = max(1e-9, float(source_w_mm))
    h = max(1e-9, float(source_h_mm))
    win_w = min(max(1e-9, float(window_w_mm)), w)
    win_h = min(max(1e-9, float(window_h_mm)), h)

    # Columns progress left -> right.
    sx = _tile_window_start(w, win_w, col - 1, cols)
    # Rows progress top -> bottom for human-readable pass order.
    sy = _tile_window_start(h, win_h, row - 1, rows)

    # Base fit centers full source; to select a tile window, shift by center delta.
    shift_x = (w * 0.5) - (sx + win_w * 0.5)
    shift_y = (h * 0.5) - (sy + win_h * 0.5)
    info = {
        "cols": cols,
        "rows": rows,
        "col": col,
        "row": row,
        "sx": sx,
        "sy": sy,
        "win_w": win_w,
        "win_h": win_h,
        "src_w": w,
        "src_h": h,
    }
    return shift_x, shift_y, info


def clamp_to_work_area(
    x: float,
    y: float,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> Tuple[float, float]:
    return (
        min(max(x, min_x), max_x),
        min(max(y, min_y), max_y),
    )


def point_in_work_area(x: float, y: float, min_x: float, max_x: float, min_y: float, max_y: float, eps: float = WORK_AREA_EPS) -> bool:
    return (min_x - eps) <= x <= (max_x + eps) and (min_y - eps) <= y <= (max_y + eps)


def clip_segment_to_rect(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    dx = x2 - x1
    dy = y2 - y1
    t0 = 0.0
    t1 = 1.0

    def upd(p: float, q: float, current_t0: float, current_t1: float) -> Optional[Tuple[float, float]]:
        if abs(p) < 1e-15:
            if q < 0.0:
                return None
            return current_t0, current_t1
        t = q / p
        if p < 0.0:
            if t > current_t1:
                return None
            return max(current_t0, t), current_t1
        if p > 0.0:
            if t < current_t0:
                return None
            return current_t0, min(current_t1, t)
        return current_t0, current_t1

    # Left
    r = upd(-(dx), x1 - min_x, t0, t1)
    if r is None:
        return None
    t0, t1 = r

    # Right
    r = upd(dx, max_x - x1, t0, t1)
    if r is None:
        return None
    t0, t1 = r

    # Bottom
    r = upd(-(dy), y1 - min_y, t0, t1)
    if r is None:
        return None
    t0, t1 = r

    # Top
    r = upd(dy, max_y - y1, t0, t1)
    if r is None:
        return None
    t0, t1 = r

    if t0 > t1:
        return None

    x_start = x1 + dx * t0
    y_start = y1 + dy * t0
    x_end = x1 + dx * t1
    y_end = y1 + dy * t1
    return (x_start, y_start), (x_end, y_end)


def clip_polylines_to_work_area(
    polylines: List[List[Tuple[float, float]]],
    logger=print,
) -> List[List[Tuple[float, float]]]:
    min_x, max_x, min_y, max_y = work_area_bounds()
    clipped_all: List[List[Tuple[float, float]]] = []
    dropped_segments = 0
    written_segments = 0

    for poly in polylines:
        if len(poly) < 2:
            continue
        out_poly: List[Tuple[float, float]] = []
        for i in range(1, len(poly)):
            x1, y1 = poly[i - 1]
            x2, y2 = poly[i]
            clipped = clip_segment_to_rect(x1, y1, x2, y2, min_x, max_x, min_y, max_y)
            if clipped is None:
                dropped_segments += 1
                if out_poly:
                    if len(out_poly) >= 2:
                        clipped_all.append(out_poly)
                    out_poly = []
                continue

            (cx1, cy1), (cx2, cy2) = clipped
            cx1, cy1 = clamp_to_work_area(cx1, cy1, min_x, max_x, min_y, max_y)
            cx2, cy2 = clamp_to_work_area(cx2, cy2, min_x, max_x, min_y, max_y)
            # Close and restart if next visible piece doesn't touch current one.
            if not point_in_work_area(cx1, cy1, min_x, max_x, min_y, max_y):
                dropped_segments += 1
                if out_poly and len(out_poly) >= 2:
                    clipped_all.append(out_poly)
                out_poly = []
                continue

            if not out_poly:
                out_poly = [(cx1, cy1)]

            if points_distance((cx1, cy1), out_poly[-1]) > CLIP_CONTINUITY_EPS_MM:
                clipped_all.append(out_poly)
                out_poly = [(cx1, cy1)]
            else:
                cx1, cy1 = out_poly[-1]

            if points_distance((cx2, cy2), out_poly[-1]) > 1e-6:
                out_poly.append((cx2, cy2))
                written_segments += 1

        if len(out_poly) >= 2:
            clipped_all.append(out_poly)

    if logger:
        if dropped_segments:
            logger(f"Work area clipping: kept {written_segments} visible segments, dropped {dropped_segments} out-of-area segments.")
    return clipped_all


def fit_polylines_to_area(
    polylines: List[List[Tuple[float, float]]],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    logger=print,
) -> List[List[Tuple[float, float]]]:
    if not polylines or not FIT_TO_WORK_AREA:
        return polylines

    w = max_x - min_x
    h = max_y - min_y
    if w <= 0.0 or h <= 0.0:
        return polylines

    area_min_x, area_max_x, area_min_y, area_max_y = work_area_bounds()
    area_w = max(1.0, area_max_x - area_min_x)
    area_h = max(1.0, area_max_y - area_min_y)
    usable_w = max(1.0, area_w - 2 * WORK_AREA_MARGIN)
    usable_h = max(1.0, area_h - 2 * WORK_AREA_MARGIN)

    raw_scale = min(usable_w / w, usable_h / h)
    fit_scale = raw_scale if ALLOW_UPSCALE_TO_WORK_AREA else min(1.0, raw_scale)
    use_dimensional_guard = (
        EXACT_GEOMETRY_MODE
        and fit_scale < float(MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW)
    )

    if use_dimensional_guard:
        # Preserve real mm dimensions for technical drawings.
        # Keep source centered in work area; excess is clipped symmetrically.
        scale = 1.0
        tx = area_min_x + WORK_AREA_MARGIN + (usable_w - w) / 2.0 - min_x
        ty = area_min_y + WORK_AREA_MARGIN + (usable_h - h) / 2.0 - min_y
        if logger:
            logger(
                "Fit guard (1:1 mm): required fit scale "
                f"{fit_scale:.4f} is below threshold {MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW:.3f}; "
                "keeping scale=1.0 and clipping overflow to work area."
            )
    else:
        scale = fit_scale
        scaled_w = w * scale
        scaled_h = h * scale
        tx = area_min_x + WORK_AREA_MARGIN + (usable_w - scaled_w) / 2.0 - min_x * scale
        ty = area_min_y + WORK_AREA_MARGIN + (usable_h - scaled_h) / 2.0 - min_y * scale

        if scale < 0.999999 or abs(tx) > 1e-9 or abs(ty) > 1e-9:
            if logger:
                logger(
                    f"Fit to work area: scale={scale:.4f}, translate=({tx:.3f},{ty:.3f}), "
                    f"from ({min_x:.3f}, {min_y:.3f})-({max_x:.3f}, {max_y:.3f})"
                )

    # Optional multi-pass window shift (keeps scale behavior, changes visible tile).
    # This is intended for large sheets (e.g., A3) split into several physical passes.
    if int(PASS_COLS) > 1 or int(PASS_ROWS) > 1:
        src_w_eff = w * scale
        src_h_eff = h * scale
        shift_x, shift_y, info = compute_pass_shift(src_w_eff, src_h_eff, usable_w, usable_h)
        tx += shift_x
        ty += shift_y
        if logger:
            logger(
                "Pass window: "
                f"col {info['col']}/{info['cols']}, row {info['row']}/{info['rows']}, "
                f"source={info['src_w']:.3f}x{info['src_h']:.3f} mm, "
                f"window={info['win_w']:.3f}x{info['win_h']:.3f} mm, "
                f"offset=({info['sx']:.3f},{info['sy']:.3f}), "
                f"shift=({shift_x:.3f},{shift_y:.3f})"
            )

    out: List[List[Tuple[float, float]]] = []
    for poly in polylines:
        out.append([((x * scale) + tx, (y * scale) + ty) for x, y in poly])
    return out


def get_path_polylines(
    element: ET.Element,
    matrix: Tuple[float, float, float, float, float, float],
    scale: float,
    source_id: int = -1,
    style_override: Optional[dict] = None,
) -> List[PathItem]:
    tag = tag_name(element.tag)
    result: List[PathItem] = []
    # style_override is treated as inherited/computed style from ancestors/<use>.
    # Element's own style/presentation attrs override inherited values.
    style = {}
    if style_override:
        style.update(style_override)
    style.update(read_style_dict(element.attrib.get("style")))
    for k in (
        "fill",
        "stroke",
        "fill-opacity",
        "stroke-opacity",
        "opacity",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
    ):
        if k in element.attrib:
            style[k] = str(element.attrib.get(k, "")).strip().lower()
    has_stroke, has_fill = parse_style_flags(style, element, tag)
    if not has_stroke and not has_fill:
        return result
    if not apply_style_filter(style, tag, element):
        return result

    cur_matrix = matrix

    def add_item(points: List[Tuple[float, float]]):
        if len(points) < 2:
            return
        result.append(
            PathItem(
                points=transform_points(points, cur_matrix, scale),
                closed=path_is_closed(points),
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        )

    if tag == "path":
        d = element.attrib.get("d", "")
        if not d:
            return result
        x = y = 0.0
        sx = sy = 0.0
        polyline: List[Tuple[float, float]] = []
        last_cubic = None
        last_quadratic = None
        last_cmd = ""

        for cmd, params in parse_path_tokens(d):
            prev_cmd = last_cmd

            if cmd in "zZ":
                if polyline:
                    polyline.append((sx, sy))
                    add_item(polyline)
                    polyline = []
                last_cubic = None
                last_quadratic = None
                x, y = sx, sy
                last_cmd = cmd
                continue

            if cmd in "mM":
                if len(params) < 2:
                    continue

                xi = 0
                first_pair = True
                while xi + 1 < len(params):
                    nx = params[xi]
                    ny = params[xi + 1]
                    if first_pair:
                        if polyline:
                            add_item(polyline)
                        if cmd == "m":
                            x += nx
                            y += ny
                        else:
                            x = nx
                            y = ny
                        polyline = [(x, y)]
                        sx, sy = x, y
                        first_pair = False
                    else:
                        # According to SVG spec, subsequent coordinate pairs after initial M/m are implicit L/l.
                        if cmd == "m":
                            x += nx
                            y += ny
                        else:
                            x = nx
                            y = ny
                        polyline.append((x, y))
                    xi += 2

                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "lL":
                for i in range(0, len(params), 2):
                    nx, ny = params[i], params[i + 1]
                    if cmd == "l":
                        x += nx
                        y += ny
                    else:
                        x = nx
                        y = ny
                    polyline.append((x, y))
                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "hH":
                for nx in params:
                    if cmd == "h":
                        x += nx
                    else:
                        x = nx
                    polyline.append((x, y))
                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "vV":
                for ny in params:
                    if cmd == "v":
                        y += ny
                    else:
                        y = ny
                    polyline.append((x, y))
                last_cubic = None
                last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "cC":
                for i in range(0, len(params), 6):
                    p1 = (params[i], params[i + 1])
                    p2 = (params[i + 2], params[i + 3])
                    p3 = (params[i + 4], params[i + 5])
                    if cmd == "c":
                        p1 = (x + p1[0], y + p1[1])
                        p2 = (x + p2[0], y + p2[1])
                        p3 = (x + p3[0], y + p3[1])
                    pts = cubic_approx((x, y), p1, p2, p3, CURVE_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = p3
                    last_cubic = p2
                    last_quadratic = None
                    last_cmd = cmd
                continue

            if cmd in "sS":
                for i in range(0, len(params), 4):
                    p1 = (params[i], params[i + 1])
                    p2 = (params[i + 2], params[i + 3])
                    if prev_cmd.lower() in "cs":
                        x1, y1 = x, y
                        x2, y2 = last_cubic if last_cubic is not None else (x, y)
                        p0 = (2 * x1 - x2, 2 * y1 - y2)
                    else:
                        p0 = (x, y)
                    if cmd == "s":
                        p1 = (x + p1[0], y + p1[1])
                        p2 = (x + p2[0], y + p2[1])
                    else:
                        p2 = (p2[0], p2[1])
                    pts = cubic_approx((x, y), p0, p1, p2, CURVE_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = p2
                    last_cubic = p1
                    last_quadratic = None
                last_cmd = cmd
                continue

            if cmd in "qQ":
                for i in range(0, len(params), 4):
                    p1 = (params[i], params[i + 1])
                    p2 = (params[i + 2], params[i + 3])
                    if cmd == "q":
                        p1 = (x + p1[0], y + p1[1])
                        p2 = (x + p2[0], y + p2[1])
                    pts = quadratic_approx((x, y), p1, p2, CURVE_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = p2
                    last_quadratic = p1
                    last_cubic = None
                last_cmd = cmd
                continue

            if cmd in "tT":
                for i in range(0, len(params), 2):
                    p2 = (params[i], params[i + 1])
                    if prev_cmd.lower() in "qt":
                        q1 = last_quadratic if last_quadratic is not None else (x, y)
                        p1 = (2 * x - q1[0], 2 * y - q1[1])
                    else:
                        p1 = (x, y)
                    if cmd == "t":
                        p2 = (x + p2[0], y + p2[1])
                    pts = quadratic_approx((x, y), p1, p2, CURVE_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = p2
                    last_quadratic = p1
                    last_cubic = None
                last_cmd = cmd
                continue

            if cmd in "aA":
                for i in range(0, len(params), 7):
                    rx, ry, rot, laf, sf, nx, ny = params[i : i + 7]
                    ex, ey = nx, ny
                    if cmd == "a":
                        ex += x
                        ey += y
                    pts = arc_to_polyline((x, y), rx, ry, rot, int(laf), int(sf), (ex, ey), MAX_ARC_SEGMENT_MM)
                    polyline.extend(pts)
                    x, y = ex, ey
                    last_cubic = None
                    last_quadratic = None
                last_cmd = cmd
                continue

            last_cmd = cmd
        if polyline:
            add_item(polyline)
        return result

    if tag == "line":
        x1 = float(element.attrib.get("x1", "0"))
        y1 = float(element.attrib.get("y1", "0"))
        x2 = float(element.attrib.get("x2", "0"))
        y2 = float(element.attrib.get("y2", "0"))
        return [
            PathItem(
                points=transform_points([(x1, y1), (x2, y2)], cur_matrix, scale),
                closed=False,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    if tag == "polyline":
        pts = parse_points(element.attrib.get("points", ""))
        if not pts:
            return []
        return [
            PathItem(
                points=transform_points(pts, cur_matrix, scale),
                closed=False,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    if tag == "polygon":
        pts = parse_points(element.attrib.get("points", ""))
        if pts:
            pts = pts + [pts[0]]
            return [
                PathItem(
                    points=transform_points(pts, cur_matrix, scale),
                    closed=True,
                    is_fill=has_fill,
                    is_stroke=has_stroke,
                    source_id=source_id,
                )
            ]
        return []

    if tag == "rect":
        x = float(element.attrib.get("x", "0"))
        y = float(element.attrib.get("y", "0"))
        w = float(element.attrib.get("width", "0"))
        h = float(element.attrib.get("height", "0"))
        if w == 0 or h == 0:
            return []
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
        return [
            PathItem(
                points=transform_points(pts, cur_matrix, scale),
                closed=True,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    if tag == "circle":
        cx = float(element.attrib.get("cx", "0"))
        cy = float(element.attrib.get("cy", "0"))
        r = float(element.attrib.get("r", "0"))
        if r <= 0:
            return []
        steps = max(12, int((2 * math.pi * r) / max(MAX_ARC_SEGMENT_MM, 0.1)))
        pts = []
        for i in range(steps + 1):
            a = 2 * math.pi * i / steps
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return [
            PathItem(
                points=transform_points(pts, cur_matrix, scale),
                closed=True,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    if tag == "ellipse":
        cx = float(element.attrib.get("cx", "0"))
        cy = float(element.attrib.get("cy", "0"))
        rx = float(element.attrib.get("rx", "0"))
        ry = float(element.attrib.get("ry", "0"))
        if rx <= 0 or ry <= 0:
            return []
        r = max(rx, ry)
        steps = max(12, int((2 * math.pi * r) / max(MAX_ARC_SEGMENT_MM, 0.1)))
        pts = []
        for i in range(steps + 1):
            a = 2 * math.pi * i / steps
            pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        return [
            PathItem(
                points=transform_points(pts, cur_matrix, scale),
                closed=True,
                is_fill=has_fill,
                is_stroke=has_stroke,
                source_id=source_id,
            )
        ]

    return result


def _canonical_closed_key(points_key: Tuple[Tuple[float, float], ...]) -> Tuple[Tuple[float, float], ...]:
    ring = list(points_key)
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if not ring:
        return tuple()
    if len(ring) == 1:
        return (ring[0],)

    def min_rotation(seq: List[Tuple[float, float]]) -> Tuple[Tuple[float, float], ...]:
        best: Optional[Tuple[Tuple[float, float], ...]] = None
        n = len(seq)
        for i in range(n):
            rot = tuple(seq[i:] + seq[:i])
            if best is None or rot < best:
                best = rot
        return best or tuple(seq)

    fwd = min_rotation(ring)
    rev = min_rotation(list(reversed(ring)))
    base = fwd if fwd <= rev else rev
    return base + (base[0],)


def extract_polylines(svg_path: Path) -> List[PathItem]:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    scale = infer_scale(root)
    page_w_mm, page_h_mm = root_page_size_mm(root)
    out: List[PathItem] = []
    source_seq = 0

    id_index = {}
    for element in root.iter():
        element_id = element.attrib.get("id")
        if element_id:
            id_index[element_id] = element

    SKIP_CONTAINER_TAGS = {
        "defs",
        "clipPath",
        "mask",
        "pattern",
        "symbol",
        "marker",
    }

    INHERIT_STYLE_ATTRS = (
        # Common SVG presentation attributes that inherit and affect drawable geometry.
        "fill",
        "stroke",
        "fill-opacity",
        "stroke-opacity",
        "opacity",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
    )

    def compute_style(parent: Optional[dict], node: ET.Element) -> dict:
        style = {}
        if parent:
            style.update(parent)
        style.update(read_style_dict(node.attrib.get("style")))
        for k in INHERIT_STYLE_ATTRS:
            if k in node.attrib:
                style[k] = str(node.attrib.get(k, "")).strip().lower()
        return style

    def walk(
        node: ET.Element,
        matrix=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        style_override: Optional[dict] = None,
        resolving_refs: Optional[set] = None,
    ):
        tag = tag_name(node.tag)
        if tag in SKIP_CONTAINER_TAGS:
            return

        local_transform = parse_transform(node.attrib.get("transform", ""))
        cur_matrix = mat_mul(matrix, local_transform)
        cur_style = compute_style(style_override, node)

        if tag == "use":
            href = get_href(node)
            if href:
                target = id_index.get(href)
                if target is not None:
                    if resolving_refs is None:
                        resolving_refs = set()
                    if href in resolving_refs:
                        return
                    resolving_refs.add(href)

                    use_x = float(node.attrib.get("x", "0") or 0)
                    use_y = float(node.attrib.get("y", "0") or 0)
                    use_matrix = mat_mul(cur_matrix, (1.0, 0.0, 0.0, 1.0, use_x, use_y))

                    walk(
                        target,
                        use_matrix,
                        style_override=cur_style,
                        resolving_refs=resolving_refs,
                    )
                    resolving_refs.discard(href)
            return

        if node.attrib.get("display", "").strip().lower() == "none":
            return
        if node.attrib.get("visibility", "").strip().lower() in {"hidden", "collapse"}:
            return

        nonlocal source_seq
        source_id = source_seq
        source_seq += 1
        new_polys = get_path_polylines(node, cur_matrix, scale, source_id=source_id, style_override=cur_style)
        if node.tag and tag_name(node.tag) == "path":
            for poly in new_polys:
                if is_full_page_white_fill_rect(poly.points, node, page_w_mm * scale, page_h_mm * scale):
                    continue
                out.append(poly)
        else:
            out.extend(new_polys)
        for child in list(node):
            walk(child, cur_matrix, style_override=cur_style)

    walk(root)

    normalized: List[PathItem] = []
    for item in out:
        poly = item.points
        if len(poly) < 2:
            continue
        cleaned: List[Tuple[float, float]] = []
        for p in poly:
            x, y = p
            if AXIS_INVERT_X:
                x = -x
            if AXIS_INVERT_Y:
                y = -y
            cleaned.append((x, y))
        cleaned = simplify_polyline(cleaned)
        if len(cleaned) < 2:
            continue
        item.points = cleaned
        item.closed = path_is_closed(cleaned)
        normalized.append(item)

    deduped: List[PathItem] = []
    seen = set()
    for item in normalized:
        poly = item.points
        if not poly:
            continue
        key = tuple((round(x, 4), round(y, 4)) for x, y in poly)
        is_closed = item.closed or path_is_closed(poly)
        if is_closed:
            norm_key = _canonical_closed_key(key)
        else:
            rev = tuple(reversed(key))
            norm_key = key if key < rev else rev
        if norm_key in seen:
            continue
        seen.add(norm_key)
        deduped.append(item)
    return deduped


def to_drawing_polylines(items: List[PathItem]) -> List[List[Tuple[float, float]]]:
    grouped = {}
    for item in items:
        group_key = (item.source_id, bool(item.is_fill), item.is_stroke)
        grouped.setdefault(group_key, []).append(item)

    out: List[List[Tuple[float, float]]] = []
    for (source_id, is_fill, is_stroke), group in grouped.items():
        _ = source_id

        if not is_stroke and not is_fill:
            continue

        # Some PDF text glyphs come as fill+stroke simultaneously.
        # Prefer a single centerline stroke when stable, otherwise keep original geometry.
        if is_fill:
            centerlines = centerline_fill_group(group)
            if centerline_is_usable(group, centerlines):
                out.extend(centerlines)
                continue

        # Fill-only regions are converted to hatch fill when possible.
        if is_fill and not is_stroke:
            arrow_lines, fill_rest = split_arrowhead_fill_group(group)
            if arrow_lines:
                out.extend(arrow_lines)
                if not fill_rest:
                    continue
            else:
                fill_rest = group

            closed_contours = [it.points for it in fill_rest if it.closed]
            if closed_contours and all(should_hatch_polygon(it.points, it.closed) for it in fill_rest):
                hatch_lines = hatch_polygon(
                    [it.points for it in fill_rest if it.closed],
                    spacing=FILL_HATCH_SPACING_MM,
                    angle_deg=FILL_HATCH_ANGLE_DEG,
                    min_segment=FILL_HATCH_MIN_SEGMENT_MM,
                )
                if hatch_lines:
                    out.extend(hatch_lines)
                    continue

            # Most PDF text glyphs are exported as tiny fill-only outlines.
            # Convert them to centerlines to avoid "double contour" letters.
            centerlines = centerline_fill_group(fill_rest)
            if centerline_is_usable(fill_rest, centerlines):
                out.extend(centerlines)
                continue

        for item in (fill_rest if (is_fill and not is_stroke) else group):
            if len(item.points) >= 2:
                out.append(item.points)

    return out


def translate_polylines(polylines: List[List[Tuple[float, float]]], dx: float, dy: float) -> List[List[Tuple[float, float]]]:
    if dx == 0.0 and dy == 0.0:
        return polylines
    return [[(x + dx, y + dy) for x, y in poly] for poly in polylines]

def points_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _q(v: float, nd: int = GCODE_COORD_DECIMALS) -> float:
    # Quantize to the same precision we emit into G-code (helps detect GRBL arc radius errors early).
    return round(float(v), int(nd))


def _arc_is_grbl_safe(from_pt: Tuple[float, float], to_pt: Tuple[float, float], center: Tuple[float, float]) -> bool:
    # GRBL checks that radius(from->center) ~= radius(to->center). With limited decimal output, even a good
    # circle fit can fail for small-radius arcs (fonts, tiny fillets). Reject arcs that would likely trip error:33.
    fx, fy = _q(from_pt[0]), _q(from_pt[1])
    tx, ty = _q(to_pt[0]), _q(to_pt[1])
    i = _q(center[0] - fx)
    j = _q(center[1] - fy)
    cx, cy = fx + i, fy + j
    r0 = math.hypot(i, j)
    r1 = math.hypot(tx - cx, ty - cy)
    return abs(r0 - r1) <= GRBL_ARC_RADIUS_MATCH_TOL_MM


def write_xy_gcode(output: Path, polylines: List[List[Tuple[float, float]]], feed_travel: float, feed_draw: float) -> None:
    lines = [
        "G21",
        "G90",
        "G17",
        "G91.1",
        f"G0 Z{Z_UP:.4f}",
    ]
    pos = None
    for poly in polylines:
        if len(poly) < 2:
            continue
        poly = simplify_polyline(poly)
        if len(poly) < 2:
            continue
        # If the next polyline starts exactly where we ended (within tolerance),
        # do not force a pen-up travel move. This avoids unnecessary pen lifts.
        if pos is None:
            lines.append(f"G0 X{poly[0][0]:.4f} Y{poly[0][1]:.4f} F{feed_travel:.1f}")
            pos = poly[0]
        else:
            d0 = points_distance(poly[0], pos)
            if d0 > CONTINUOUS_JOIN_EPS:
                lines.append(f"G0 X{poly[0][0]:.4f} Y{poly[0][1]:.4f} F{feed_travel:.1f}")
                pos = poly[0]
            elif d0 > 1e-9:
                # Snap the start point to the current position so G2/G3 I/J offsets are valid.
                # Without this, tiny numeric gaps can produce invalid arcs or huge "circle" bulges.
                poly = [pos] + list(poly[1:])

        # Common PDF/SVG artifact: a single line is represented as A->B->A in one path.
        # Drawing the return stroke makes lines look doubled and wastes time. Convert it to:
        # draw A->B, then rapid back to A (pen up is inserted by penlift postprocess).
        if len(poly) == 3 and points_distance(poly[0], poly[-1]) <= 1e-6 and points_distance(poly[0], poly[1]) > 1e-6:
            mid = poly[1]
            start = poly[0]
            if pos is None or points_distance(mid, pos) > 1e-9:
                lines.append(f"G1 X{mid[0]:.4f} Y{mid[1]:.4f} F{feed_draw:.1f}")
            # Rapid back to start without drawing (penlift postprocess will raise pen before this G0).
            lines.append(f"G0 X{start[0]:.4f} Y{start[1]:.4f} F{feed_travel:.1f}")
            pos = start
            continue

        # Replace noisy polylines by a single line when they are essentially straight.
        if polyline_is_near_line(poly, LINE_FIT_TOL_MM):
            end = poly[-1]
            if pos is None or points_distance(end, pos) > 1e-9:
                lines.append(f"G1 X{end[0]:.4f} Y{end[1]:.4f} F{feed_draw:.1f}")
                pos = end
            continue

        # Replace circular polylines by true arcs (G2/G3) when safe.
        is_full_circle = False
        if EMIT_ARCS:
            arc = polyline_fit_arc(poly, ARC_FIT_TOL_MM)
        else:
            arc = None
        if arc is not None:
            cw, center, r, sweep = arc
            min_x, max_x, min_y, max_y = work_area_bounds()

            start = poly[0]
            end = poly[-1]

            is_closed = points_distance(start, end) <= 0.10
            if is_closed and abs(abs(sweep) - 2.0 * math.pi) <= math.radians(25.0):
                is_full_circle = True

            # If the geometry is a closed loop but the fitted sweep is not close to a full turn,
            # do not emit a "full circle" arc. GRBL is sensitive to end==start arcs and we split
            # full circles into two arcs (via diametric midpoint). Doing that for non-circles can
            # generate huge bulges and even leave the work area.
            if is_closed and not is_full_circle:
                arc = None

            # Validate extents are still inside the work area (avoid arc "bulge" outside bounds).
            if arc is not None and is_full_circle:
                # Use actual radius implied by the start point. The fitted radius can differ by up to tol_mm
                # which may push the generated arc slightly outside the clipped work area.
                r_actual = math.hypot(start[0] - center[0], start[1] - center[1])
                ax0, ax1, ay0, ay1 = (center[0] - r_actual, center[0] + r_actual, center[1] - r_actual, center[1] + r_actual)
            else:
                if arc is not None:
                    ax0, ax1, ay0, ay1 = arc_extents_xy(start, end, center, cw=cw)

            if arc is not None:
                if not (
                    point_in_work_area(ax0, ay0, min_x, max_x, min_y, max_y)
                    and point_in_work_area(ax1, ay1, min_x, max_x, min_y, max_y)
                ):
                    arc = None

        if arc is not None:
            cw, center, _r, _sweep = arc
            code = "G2" if cw else "G3"
            start = poly[0]
            end = poly[-1]

            def emit_arc(to_pt: Tuple[float, float], from_pt: Tuple[float, float], with_f: bool):
                i = center[0] - from_pt[0]
                j = center[1] - from_pt[1]
                if with_f:
                    lines.append(f"{code} X{to_pt[0]:.4f} Y{to_pt[1]:.4f} I{i:.4f} J{j:.4f} F{feed_draw:.1f}")
                else:
                    lines.append(f"{code} X{to_pt[0]:.4f} Y{to_pt[1]:.4f} I{i:.4f} J{j:.4f}")

            # Full circle: GRBL can be picky with end==start, so split into two arcs.
            # IMPORTANT: do not use a polyline midpoint as the half-way endpoint, it may be off-radius
            # and GRBL will reject the arc (radius mismatch). Use the diametric opposite point on the
            # fitted circle so both arcs are valid.
            if is_full_circle:
                mid = (2.0 * center[0] - start[0], 2.0 * center[1] - start[1])
                # Safety: if the midpoint itself is outside the work area, reject arc emission and
                # fall back to the polyline (which was already clipped to the work area).
                min_x, max_x, min_y, max_y = work_area_bounds()
                if not point_in_work_area(mid[0], mid[1], min_x, max_x, min_y, max_y):
                    arc = None
                else:
                    # GRBL radius-mismatch safety check (avoid error:33).
                    if not (_arc_is_grbl_safe(start, mid, center) and _arc_is_grbl_safe(mid, start, center)):
                        arc = None
                    else:
                        emit_arc(mid, start, with_f=True)
                        emit_arc(start, mid, with_f=False)
                        pos = start
                        continue
            if arc is not None:
                # GRBL radius-mismatch safety check (avoid error:33).
                if not _arc_is_grbl_safe(start, end, center):
                    arc = None
                else:
                    emit_arc(end, start, with_f=True)
                    pos = end
                    continue

        # Fallback: raw polyline as G1 segments.
        if RDP_SIMPLIFY_EPS_MM > 0.0 and len(poly) >= 3:
            poly = rdp_simplify_polyline(poly, RDP_SIMPLIFY_EPS_MM)
        drew = False
        for pt in poly[1:]:
            if pos is not None and points_distance(pt, pos) <= 1e-9:
                continue
            if not drew:
                lines.append(f"G1 X{pt[0]:.4f} Y{pt[1]:.4f} F{feed_draw:.1f}")
                drew = True
            else:
                lines.append(f"G1 X{pt[0]:.4f} Y{pt[1]:.4f}")
            pos = pt
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _grid_key(pt: Tuple[float, float], cell: float) -> Tuple[int, int]:
    if cell <= 0:
        return (0, 0)
    return (int(math.floor(pt[0] / cell)), int(math.floor(pt[1] / cell)))


def _neighbor_keys(key: Tuple[int, int]) -> List[Tuple[int, int]]:
    x, y = key
    return [
        (x - 1, y - 1),
        (x, y - 1),
        (x + 1, y - 1),
        (x - 1, y),
        (x, y),
        (x + 1, y),
        (x - 1, y + 1),
        (x, y + 1),
        (x + 1, y + 1),
    ]


def stitch_polylines(polylines: List[List[Tuple[float, float]]], eps: float, logger=print) -> List[List[Tuple[float, float]]]:
    # Join polyline fragments that share endpoints to reduce pen up/down churn.
    if not polylines or eps <= 0 or not STITCH_ENABLED:
        return polylines

    if EXACT_GEOMETRY_MODE:
        # In exact-copy mode, do not "bridge" near endpoints.
        # Gap stitching can connect unrelated technical geometry and create artifacts.
        gap_eps = float(eps)
        angle_tol = 0.0
    else:
        gap_eps = max(float(eps), float(STITCH_GAP_EPS_MM))
        angle_tol = float(STITCH_GAP_MAX_ANGLE_DEG)
    cell = gap_eps

    starts = {}
    ends = {}
    for idx, poly in enumerate(polylines):
        if len(poly) < 2:
            continue
        ks = _grid_key(poly[0], cell)
        ke = _grid_key(poly[-1], cell)
        starts.setdefault(ks, []).append(idx)
        ends.setdefault(ke, []).append(idx)

    used = set()
    out: List[List[Tuple[float, float]]] = []

    def _dir(a: Tuple[float, float], b: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        n = math.hypot(dx, dy)
        if n <= 1e-12:
            return None
        return (dx / n, dy / n)

    def _angle_deg(u: Tuple[float, float], v: Tuple[float, float]) -> float:
        dot = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
        return math.degrees(math.acos(dot))

    def _find_forward(tail: Tuple[float, float], tail_dir: Optional[Tuple[float, float]], want_start: bool) -> Optional[int]:
        base = _grid_key(tail, cell)
        maps = starts if want_start else ends
        for k in _neighbor_keys(base):
            for j in maps.get(k, []):
                if j in used:
                    continue
                cand = polylines[j]
                if len(cand) < 2:
                    continue
                pt = cand[0] if want_start else cand[-1]
                d = points_distance(pt, tail)
                if d <= eps:
                    return j
                if d <= gap_eps and tail_dir is not None and angle_tol > 0:
                    cand_dir = _dir(cand[0], cand[1]) if want_start else _dir(cand[-1], cand[-2])
                    if cand_dir is not None and _angle_deg(tail_dir, cand_dir) <= angle_tol:
                        return j
        return None

    def _find_backward(head: Tuple[float, float], head_dir: Optional[Tuple[float, float]], use_end: bool) -> Optional[int]:
        # use_end=True: candidate end matches head; use_end=False: candidate start matches head (will be reversed).
        base = _grid_key(head, cell)
        maps = ends if use_end else starts
        for k in _neighbor_keys(base):
            for j in maps.get(k, []):
                if j in used:
                    continue
                cand = polylines[j]
                if len(cand) < 2:
                    continue
                pt = cand[-1] if use_end else cand[0]
                d = points_distance(pt, head)
                if d <= eps:
                    return j
                if d <= gap_eps and head_dir is not None and angle_tol > 0:
                    cand_dir = _dir(cand[-1], cand[-2]) if use_end else _dir(cand[0], cand[1])
                    if cand_dir is not None and _angle_deg(head_dir, cand_dir) <= angle_tol:
                        return j
        return None

    for i in range(len(polylines)):
        if i in used:
            continue
        poly = polylines[i]
        if len(poly) < 2:
            continue
        used.add(i)
        cur = list(poly)

        # Extend forward.
        while True:
            tail = cur[-1]
            tail_dir = _dir(cur[-2], cur[-1]) if len(cur) >= 2 else None
            j = _find_forward(tail, tail_dir, want_start=True)
            if j is not None:
                used.add(j)
                cur.extend(polylines[j][1:])
                continue
            j = _find_forward(tail, tail_dir, want_start=False)
            if j is not None:
                used.add(j)
                rev = list(reversed(polylines[j]))
                cur.extend(rev[1:])
                continue
            break

        # Extend backward.
        while True:
            head = cur[0]
            head_dir = _dir(cur[1], cur[0]) if len(cur) >= 2 else None
            j = _find_backward(head, head_dir, use_end=True)
            if j is not None:
                used.add(j)
                cur = polylines[j][:-1] + cur
                continue
            j = _find_backward(head, head_dir, use_end=False)
            if j is not None:
                used.add(j)
                rev = list(reversed(polylines[j]))
                cur = rev[:-1] + cur
                continue
            break

        cur = simplify_polyline(cur)
        if len(cur) >= 2:
            out.append(cur)

    if logger and len(out) != len(polylines):
        logger(
            f"Stitch: polylines {len(polylines)} -> {len(out)} "
            f"(eps={eps:.3f} mm, gap_eps={gap_eps:.3f} mm, angle<={angle_tol:.1f} deg)"
        )
    return out


def _segment_dedup_key(a: Tuple[float, float], b: Tuple[float, float], eps: float) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    if eps <= 0.0:
        qa = (int(round(a[0] * 1000.0)), int(round(a[1] * 1000.0)))
        qb = (int(round(b[0] * 1000.0)), int(round(b[1] * 1000.0)))
    else:
        qa = (int(round(a[0] / eps)), int(round(a[1] / eps)))
        qb = (int(round(b[0] / eps)), int(round(b[1] / eps)))
    return (qa, qb) if qa <= qb else (qb, qa)


def deduplicate_segments(
    polylines: List[List[Tuple[float, float]]],
    eps: float = SEGMENT_DEDUP_EPS_MM,
    logger=print,
) -> List[List[Tuple[float, float]]]:
    # Remove exact (or near-exact) retraced segments globally to reduce overdraw/letter boldness.
    if not polylines or not SEGMENT_DEDUP_ENABLED:
        return polylines
    seen = set()
    out: List[List[Tuple[float, float]]] = []
    dropped = 0
    src_segments = 0

    for poly in polylines:
        if len(poly) < 2:
            continue
        current: List[Tuple[float, float]] = []
        prev = poly[0]
        for pt in poly[1:]:
            if points_distance(prev, pt) <= 1e-9:
                prev = pt
                continue
            src_segments += 1
            key = _segment_dedup_key(prev, pt, eps)
            if key in seen:
                dropped += 1
                prev = pt
                continue
            seen.add(key)
            if not current:
                current = [prev, pt]
            else:
                if points_distance(current[-1], prev) <= 1e-9:
                    current.append(pt)
                else:
                    s = simplify_polyline(current)
                    if len(s) >= 2:
                        out.append(s)
                    current = [prev, pt]
            prev = pt
        if current:
            s = simplify_polyline(current)
            if len(s) >= 2:
                out.append(s)

    if logger and dropped > 0:
        kept = max(0, src_segments - dropped)
        logger(
            f"Segment dedup: dropped {dropped}/{src_segments} retraced segments "
            f"({(dropped / max(1, src_segments)) * 100.0:.1f}%), kept={kept}, eps={eps:.3f} mm"
        )
    return out if out else polylines


def reorder_polylines(polylines: List[List[Tuple[float, float]]], logger=print) -> List[List[Tuple[float, float]]]:
    if not polylines or not REORDER_ENABLED:
        return polylines

    remaining = [p for p in polylines if len(p) >= 2]
    if not remaining:
        return []

    ordered: List[List[Tuple[float, float]]] = []
    # Start from the first polyline start; we do not know the machine's true XY origin.
    cur_x, cur_y = remaining[0][0]

    while remaining:
        best_i = 0
        best_rev = False
        best_d = float("inf")
        for i, p in enumerate(remaining):
            d0 = points_distance((cur_x, cur_y), p[0])
            d1 = points_distance((cur_x, cur_y), p[-1])
            if d0 < best_d:
                best_d = d0
                best_i = i
                best_rev = False
            if d1 < best_d:
                best_d = d1
                best_i = i
                best_rev = True

        chosen = remaining.pop(best_i)
        if best_rev:
            chosen = list(reversed(chosen))
        ordered.append(chosen)
        cur_x, cur_y = chosen[-1]

    if logger and len(ordered) >= 2:
        logger(f"Reorder: {len(polylines)} polylines ordered (nearest-end).")
    return ordered


def write_outer_trim_preview_svg(
    source_items: List[PathItem],
    removed_items: List[PathItem],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    if not source_items:
        output.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10" />\n',
            encoding="utf-8",
        )
        return

    points = [p for item in source_items for p in item.points]
    if not points:
        output.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10" />\n',
            encoding="utf-8",
        )
        return

    min_x = min(x for x, _ in points)
    max_x = max(x for x, _ in points)
    min_y = min(y for _, y in points)
    max_y = max(y for _, y in points)
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0.0 or height <= 0.0:
        return

    pad = max(1.0, max(width, height) * 0.02)
    vb_x = min_x - pad
    vb_y = min_y - pad
    vb_w = width + 2 * pad
    vb_h = height + 2 * pad

    removed_ids = {id(item) for item in removed_items}
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm"',
        f'viewBox="{vb_x:.4f} {vb_y:.4f} {vb_w:.4f} {vb_h:.4f}">',
        "<g fill=\"none\" stroke-linecap=\"round\" stroke-linejoin=\"round\">",
    ]

    def svg_path(poly: List[Tuple[float, float]], closed: bool) -> str:
        if len(poly) < 2:
            return ""
        d = f"M {poly[0][0]:.4f} {poly[0][1]:.4f} "
        d += " ".join(f"L {x:.4f} {y:.4f}" for x, y in poly[1:])
        if closed:
            d += " Z"
        return d

    for item in source_items:
        if not item.points:
            continue
        color = "#555555"
        width_stroke = "0.12"
        if id(item) in removed_ids:
            color = "#cc0000"
            width_stroke = "0.2"
        elif item.is_stroke and not item.is_fill:
            color = "#0d47a1"
            width_stroke = "0.15"
        elif item.is_fill and not item.is_stroke:
            color = "#388e3c"
            width_stroke = "0.1"

        d = svg_path(item.points, item.closed)
        if d:
            lines.append(f'<path d="{d}" stroke="{color}" stroke-width="{width_stroke}" />')

    lines.append("</g>")
    lines.append("</svg>\n")
    output.write_text("\n".join(lines), encoding="utf-8")


def build_area_frame_polylines() -> List[List[Tuple[float, float]]]:
    min_x, max_x, min_y, max_y = work_area_bounds()
    x0 = min_x + WORK_AREA_FRAME_MARGIN
    x1 = max_x - WORK_AREA_FRAME_MARGIN
    y0 = min_y + WORK_AREA_FRAME_MARGIN
    y1 = max_y - WORK_AREA_FRAME_MARGIN
    if x1 <= x0 or y1 <= y0:
        return []
    tick = min(8.0, (x1 - x0) * 0.06, (y1 - y0) * 0.06)
    return [
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
        [(x0, y0), (x0 + tick, y0)],
        [(x0, y0), (x0, y0 + tick)],
        [(x1, y0), (x1 - tick, y0)],
        [(x1, y0), (x1, y0 + tick)],
        [(x0, y1), (x0 + tick, y1)],
        [(x0, y1), (x0, y1 - tick)],
        [(x1, y1), (x1 - tick, y1)],
        [(x1, y1), (x1, y1 - tick)],
    ]


def build_area_corner_mark_polylines(mark_size: float = 2.0) -> List[List[Tuple[float, float]]]:
    min_x, max_x, min_y, max_y = work_area_bounds()
    x_left = min_x
    x_right = max_x
    y_top = min_y
    y_bottom = max_y

    if mark_size <= 0 or x_right <= x_left or y_bottom <= y_top:
        return []

    dx = min(mark_size, abs(x_right - x_left) / 8.0, abs(y_bottom - y_top) / 8.0)
    if dx <= 0.0:
        return []

    corners = [
        (x_left, y_top),
        (x_right, y_top),
        (x_right, y_bottom),
        (x_left, y_bottom),
    ]

    marks: List[List[Tuple[float, float]]] = []
    for cx, cy in corners:
        dir_x = 1.0 if abs(cx - x_left) < 1e-9 else -1.0
        dir_y = 1.0 if abs(cy - y_top) < 1e-9 else -1.0
        marks.append([(cx, cy), (cx + dir_x * dx, cy)])
        marks.append([(cx, cy), (cx, cy + dir_y * dx)])
    return marks


def build_snake_hatch_polyline(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    step: float,
    *,
    horizontal: bool = True,
) -> List[Tuple[float, float]]:
    if step <= 1e-6:
        return []
    if x1 - x0 <= 1e-6 or y1 - y0 <= 1e-6:
        return []

    pts: List[Tuple[float, float]] = []
    if horizontal:
        y = y0
        at_right = True
        pts.append((x0, y))
        pts.append((x1, y))
        while y < y1 - 1e-9:
            y_next = min(y + step, y1)
            if at_right:
                pts.append((x1, y_next))
                pts.append((x0, y_next))
            else:
                pts.append((x0, y_next))
                pts.append((x1, y_next))
            at_right = not at_right
            y = y_next
    else:
        x = x0
        at_bottom = True
        pts.append((x, y0))
        pts.append((x, y1))
        while x < x1 - 1e-9:
            x_next = min(x + step, x1)
            if at_bottom:
                pts.append((x_next, y1))
                pts.append((x_next, y0))
            else:
                pts.append((x_next, y0))
                pts.append((x_next, y1))
            at_bottom = not at_bottom
            x = x_next

    out: List[Tuple[float, float]] = []
    for p in pts:
        if not out or points_distance(out[-1], p) > 1e-9:
            out.append(p)
    return out


def build_pencil_wear_test_polylines(
    *,
    levels: int = 8,
    cols: int = 2,
    margin_mm: float = 8.0,
    gap_mm: float = 6.0,
    hatch_step_mm: float = 1.0,
    hatch_loops: int = 1,
) -> Tuple[List[List[Tuple[float, float]]], List[dict]]:
    levels = max(1, int(levels))
    cols = max(1, int(cols))
    rows = int(math.ceil(levels / float(cols)))

    min_x, max_x, min_y, max_y = work_area_bounds()
    area_w = max_x - min_x
    area_h = max_y - min_y

    margin = max(2.0, float(margin_mm))
    gap = max(1.0, float(gap_mm))
    step = max(0.2, float(hatch_step_mm))
    loops = max(1, int(hatch_loops))

    usable_w = area_w - 2.0 * margin - (cols - 1) * gap
    usable_h = area_h - 2.0 * margin - (rows - 1) * gap
    if usable_w <= 6.0 or usable_h <= 6.0:
        return [], []

    block_w = usable_w / cols
    block_h = usable_h / rows
    if block_w < 8.0 or block_h < 8.0:
        return [], []

    start_x = min_x + margin
    start_y = min_y + margin
    all_paths: List[List[Tuple[float, float]]] = []
    stats: List[dict] = []
    cumulative_mm = 0.0

    for idx in range(levels):
        col = idx % cols
        row = idx // cols
        x0 = start_x + col * (block_w + gap)
        y0 = start_y + row * (block_h + gap)
        x1 = x0 + block_w
        y1 = y0 + block_h

        block_paths: List[List[Tuple[float, float]]] = []

        border = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        block_paths.append(border)

        for lp in range(loops):
            inset = min(0.7 + lp * 0.7, block_w * 0.22, block_h * 0.22)
            xi0 = x0 + inset
            yi0 = y0 + inset
            xi1 = x1 - inset
            yi1 = y1 - inset
            if xi1 - xi0 <= 2.5 or yi1 - yi0 <= 2.5:
                continue
            hatch = build_snake_hatch_polyline(
                xi0,
                xi1,
                yi0,
                yi1,
                step,
                horizontal=(lp % 2 == 0),
            )
            if len(hatch) >= 2:
                block_paths.append(hatch)

        # Stage marker: small "comb" in the block corner.
        marker_pitch = min(2.2, block_w * 0.08)
        marker_len = min(3.0, block_h * 0.18)
        marker_x0 = x0 + 1.0
        marker_y0 = y0 + 1.0
        marker_max = int(max(1.0, (block_w - 2.0) / max(0.5, marker_pitch)))
        marker_count = min(idx + 1, marker_max)
        for m in range(marker_count):
            mx = marker_x0 + m * marker_pitch
            block_paths.append([(mx, marker_y0), (mx, marker_y0 + marker_len)])

        block_len = total_draw_length_mm(block_paths)
        cumulative_mm += block_len
        stats.append(
            {
                "stage": idx + 1,
                "row": row + 1,
                "col": col + 1,
                "draw_mm": block_len,
                "cum_mm": cumulative_mm,
                "bbox": (x0, x1, y0, y1),
            }
        )
        all_paths.extend(block_paths)

    return all_paths, stats


def apply_penlift(
    xy_gcode: Path,
    pen_gcode: Path,
    *,
    z_down: float = Z_DOWN,
    dynamic_z_enable: bool = False,
    dynamic_base_z_down: Optional[float] = None,
    dynamic_initial_wear_mm: float = 0.0,
) -> None:
    script = ROOT_DIR / "src" / "penlift_postprocess.py"
    travel_lift_mm = float(Z_TRAVEL_LIFT_MM)
    if SAFE_PEN_TRAVEL_UP:
        # Force full lift for every G0 travel to avoid accidental drag lines.
        # A tiny extra margin prevents edge cases with float rounding.
        travel_lift_mm = max(travel_lift_mm, abs(float(z_down) - float(Z_UP)) + 0.1)

    cmd = [
        sys.executable,
        str(script),
        str(xy_gcode),
        "--output",
        str(pen_gcode),
        "--z-down",
        f"{float(z_down):.3f}",
        "--z-up",
        f"{Z_UP:.4f}",
        "--mode",
        PEN_LIFT_MODE,
        "--spindle-speed",
        str(PEN_SPINDLE_SPEED),
        "--delay",
        f"{Z_DELAY_DOWN:.2f}",
        "--delay-up",
        f"{Z_DELAY_UP:.2f}",
        "--z-feed-down-approach",
        f"{Z_FEED_DOWN_APPROACH:.1f}",
        "--z-feed-down-touch",
        f"{Z_FEED_DOWN_TOUCH:.1f}",
        "--z-feed-up",
        f"{Z_FEED_UP:.1f}",
        "--z-feed-up-final",
        f"{Z_FEED_UP_FINAL:.1f}",
        "--z-soft-down-mm",
        f"{Z_SOFT_DOWN_MM:.3f}",
        "--z-soft-up-mm",
        f"{Z_SOFT_UP_MM:.3f}",
        "--z-travel-lift-mm",
        f"{travel_lift_mm:.3f}",
    ]
    if dynamic_z_enable:
        base_z = float(z_down) if dynamic_base_z_down is None else float(dynamic_base_z_down)
        cmd.extend(
            [
                "--dynamic-z-enable",
                "--dynamic-base-z-down",
                f"{base_z:.4f}",
                "--dynamic-initial-wear-mm",
                f"{max(0.0, float(dynamic_initial_wear_mm)):.6f}",
                "--dynamic-wear-mm-per-m",
                f"{max(0.0, float(PENCIL_WEAR_MM_PER_M)):.6f}",
                "--dynamic-z-comp-per-wear",
                f"{max(0.0, float(PENCIL_Z_COMP_MM_PER_WEAR_MM)):.6f}",
                "--dynamic-z-max-comp-mm",
                f"{max(0.0, float(PENCIL_MAX_COMP_MM)):.6f}",
            ]
        )
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"PenLift postprocess error: {err.strip() or out.strip()}")


def apply_quality_profile(
    quality: str,
    curve_segment_mm: Optional[float] = None,
    arc_segment_mm: Optional[float] = None,
    collinear_eps: Optional[float] = None,
    rdp_simplify_eps_mm: Optional[float] = None,
    arc_fit_tol_mm: Optional[float] = None,
    line_fit_tol_mm: Optional[float] = None,
    disable_simplify: bool = False,
    disable_arcs: bool = False,
    force_text_to_path: Optional[bool] = None,
) -> None:
    global MAX_ARC_SEGMENT_MM
    global CURVE_SEGMENT_MM
    global POLYLINE_COLLINEAR_EPS
    global SIMPLIFY_ENABLED
    global EMIT_ARCS
    global ARC_FIT_TOL_MM
    global LINE_FIT_TOL_MM
    global FORCE_TEXT_TO_PATH
    global RDP_SIMPLIFY_EPS_MM
    global QUALITY_PROFILE

    profile = (quality or "normal").lower().strip()
    if profile not in {"fast", "normal", "high"}:
        raise ValueError(f"Unknown quality profile '{quality}'. Use fast|normal|high.")

    if profile == "high":
        profile_curve = 1.0
        profile_arc = 4.0
        profile_eps = 0.05
        profile_rdp = 0.05
        profile_arc_fit = 0.10
        profile_line_fit = 0.03
        profile_simplify = True
        profile_text = True
    elif profile == "normal":
        profile_curve = 2.0
        profile_arc = 8.0
        profile_eps = 0.15
        profile_rdp = 0.12
        profile_arc_fit = 0.15
        profile_line_fit = 0.05
        profile_simplify = True
        profile_text = False
    else:
        profile_curve = 4.0
        profile_arc = 14.0
        profile_eps = 0.40
        profile_rdp = 0.25
        # Speed-focused: prefer smooth controller arcs over many tiny G1 segments.
        # This tolerance is intentionally loose; use "normal"/"high" for accuracy.
        profile_arc_fit = 1.00
        profile_line_fit = 0.08
        profile_simplify = True
        profile_text = False

    if disable_simplify:
        profile_simplify = False
        profile_rdp = 0.0

    if curve_segment_mm is not None:
        profile_curve = float(curve_segment_mm)
    if arc_segment_mm is not None:
        profile_arc = float(arc_segment_mm)
    if collinear_eps is not None:
        profile_eps = float(collinear_eps)
    if rdp_simplify_eps_mm is not None:
        profile_rdp = float(rdp_simplify_eps_mm)
    if arc_fit_tol_mm is not None:
        profile_arc_fit = float(arc_fit_tol_mm)
    if line_fit_tol_mm is not None:
        profile_line_fit = float(line_fit_tol_mm)

    if profile_curve <= 0.0:
        raise ValueError("curve_segment_mm must be > 0")
    if profile_arc <= 0.0:
        raise ValueError("arc_segment_mm must be > 0")
    if profile_eps < 0.0:
        raise ValueError("collinear_eps must be >= 0")
    if profile_rdp < 0.0:
        raise ValueError("rdp_simplify_eps_mm must be >= 0")
    if profile_arc_fit < 0.0:
        raise ValueError("arc_fit_tol_mm must be >= 0")
    if profile_line_fit < 0.0:
        raise ValueError("line_fit_tol_mm must be >= 0")

    if force_text_to_path is None:
        force_text_to_path = profile_text

    if EXACT_GEOMETRY_MODE:
        # In exact-copy mode, reduce geometry simplification side effects.
        # This keeps technical drawing corners / arrowheads closer to source.
        profile_eps = min(profile_eps, 0.06)
        profile_rdp = min(profile_rdp, 0.02)
        profile_line_fit = min(profile_line_fit, 0.02)

    QUALITY_PROFILE = profile
    CURVE_SEGMENT_MM = profile_curve
    MAX_ARC_SEGMENT_MM = profile_arc
    POLYLINE_COLLINEAR_EPS = profile_eps
    SIMPLIFY_ENABLED = bool(profile_simplify)
    if EXACT_GEOMETRY_MODE:
        # In exact-copy mode, avoid synthetic arc fitting. This removes accidental
        # large-circle artifacts that can appear on some technical drawings.
        EMIT_ARCS = False
    else:
        EMIT_ARCS = not bool(disable_arcs)
    RDP_SIMPLIFY_EPS_MM = profile_rdp
    ARC_FIT_TOL_MM = profile_arc_fit
    LINE_FIT_TOL_MM = profile_line_fit
    FORCE_TEXT_TO_PATH = bool(force_text_to_path)


def quality_state() -> str:
    return (
        f"Quality profile: {QUALITY_PROFILE}; "
        f"CURVE_SEGMENT_MM={CURVE_SEGMENT_MM:.3f}; "
        f"MAX_ARC_SEGMENT_MM={MAX_ARC_SEGMENT_MM:.3f}; "
        f"POLYLINE_COLLINEAR_EPS={POLYLINE_COLLINEAR_EPS:.3f}; "
        f"RDP_EPS={RDP_SIMPLIFY_EPS_MM:.3f}; "
        f"ArcFitTol={ARC_FIT_TOL_MM:.3f}; "
        f"LineFitTol={LINE_FIT_TOL_MM:.3f}; "
        f"EmitArcs={'on' if EMIT_ARCS else 'off'}; "
        f"ExactGeometry={'on' if EXACT_GEOMETRY_MODE else 'off'}; "
        f"SafeTravelLift={'full' if SAFE_PEN_TRAVEL_UP else f'{Z_TRAVEL_LIFT_MM:.2f}mm'}; "
        f"Strict1to1Guard={'off' if MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW <= 0.0 else f'on<{MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW:.3f}'}; "
        f"Simplify={'on' if SIMPLIFY_ENABLED else 'off'}; "
        f"ForceTextToPath={'on' if FORCE_TEXT_TO_PATH else 'off'}"
    )




def pdf_to_svg(pdf_path: Path, svg_path: Path, logger) -> None:
    logger("Converting PDF -> SVG ...")

    svg_path.parent.mkdir(parents=True, exist_ok=True)

    def postprocess_text(svg_target: Path) -> None:
        if FORCE_TEXT_TO_PATH or svg_has_text_nodes(svg_target):
            if not convert_svg_text_to_paths(svg_target, logger) or svg_has_text_nodes(svg_target):
                raise RuntimeError("Text->path conversion required and failed.")
            logger(f"Text nodes after conversion: {svg_text_node_count(svg_target)}")

    def ensure_svg_exists(prefix: Path, target_svg: Path) -> bool:
        candidates = []
        for cand in [
            prefix.with_suffix(".svg"),
            prefix,
            Path(f"{prefix}-1"),
            Path(f"{prefix}-1.svg"),
        ]:
            candidates.append(cand)

        try:
            candidates.extend(sorted(prefix.parent.glob(f"{prefix.name}*")))
        except Exception:
            pass

        seen = set()
        ordered: List[Path] = []
        for cand in candidates:
            rp = Path(cand)
            if rp in seen:
                continue
            seen.add(rp)
            ordered.append(rp)

        for candidate in ordered:
            if not candidate.exists() or not candidate.is_file():
                continue
            if candidate.stat().st_size <= 0:
                continue
            if candidate == target_svg:
                return True
            if candidate.suffix.lower() == "" and candidate.with_suffix(".svg").exists():
                # prefer explicit .svg file over raw file names
                continue
            if target_svg.exists():
                target_svg.unlink()
            candidate.replace(target_svg)
            logger(f"Using generated SVG: {candidate}")
            return True

        if target_svg.exists() and target_svg.stat().st_size > 0:
            return True
        return False

    def score_svg_quality(svg_target: Path) -> Tuple[float, str]:
        # Lower score is better. Use scale-independent metrics so px/mm export differences
        # do not bias converter selection.
        try:
            items = extract_polylines(svg_target)
            if not items:
                return float("inf"), "no paths"
            polylines = to_drawing_polylines(items)
            if not polylines:
                return float("inf"), "no drawable geometry"

            seg_lengths: List[float] = []
            for poly in polylines:
                for i in range(len(poly) - 1):
                    d = points_distance(poly[i], poly[i + 1])
                    if d > 0.0:
                        seg_lengths.append(d)
            if not seg_lengths:
                return float("inf"), "empty segment set"

            seg_count = len(seg_lengths)
            lengths_sorted = sorted(seg_lengths)
            med = lengths_sorted[len(lengths_sorted) // 2]
            tiny_th = max(1e-9, med * 0.20)
            short_th = max(1e-9, med * 0.40)
            tiny_rel = sum(1 for d in seg_lengths if d <= tiny_th)
            short_rel = sum(1 for d in seg_lengths if d <= short_th)
            score = float(seg_count) + (2.5 * float(tiny_rel)) + (1.0 * float(short_rel)) + (0.2 * float(len(polylines)))

            overflow_penalty = 0.0
            page_w_mm, page_h_mm = svg_page_size_mm(svg_target)
            b = bounds_path_items(items)
            if b is not None and page_w_mm > 0.0 and page_h_mm > 0.0:
                x0, x1, y0, y1 = b
                bw = max(0.0, x1 - x0)
                bh = max(0.0, y1 - y0)
                ox = max(0.0, (bw / page_w_mm) - 1.15)
                oy = max(0.0, (bh / page_h_mm) - 1.15)
                overflow_penalty = 4000.0 * (ox + oy)
                score += overflow_penalty

            details = (
                f"score={score:.1f}, paths={len(polylines)}, seg={seg_count}, "
                f"med={med:.4f}, tiny<=0.2*med={tiny_rel}, short<=0.4*med={short_rel}, "
                f"overflow_penalty={overflow_penalty:.1f}"
            )
            return score, details
        except Exception as exc:
            return float("inf"), f"metric-error: {exc}"

    def inkscape_candidates(exe: str, target_svg: Path) -> List[List[str]]:
        major, _, _ = get_inkscape_version(exe)
        if major >= 1:
            return [
                [
                    exe,
                    "--batch-process",
                    "--export-type=svg",
                    "--export-area-page",
                    "--export-overwrite",
                    f"--export-filename={target_svg}",
                    "--pdf-page=1",
                    "--pdf-poppler",
                    str(pdf_path),
                ],
                [
                    exe,
                    "--batch-process",
                    "--export-type=svg",
                    "--export-area-page",
                    "--export-overwrite",
                    f"--export-filename={target_svg}",
                    "--pdf-page=1",
                    str(pdf_path),
                ],
                [
                    exe,
                    "--batch-process",
                    "--actions=select-all;object-to-path;export-text-to-path",
                    "--export-overwrite",
                    "--export-area-page",
                    f"--export-filename={target_svg}",
                    "--pdf-page=1",
                    str(pdf_path),
                ],
                [
                    exe,
                    "--batch-process",
                    "--actions=select-all;object-to-path;export-text-to-path",
                    "--export-overwrite",
                    "--export-area-page",
                    "--export-plain-svg",
                    f"--export-filename={target_svg}",
                    "--pdf-page=1",
                    str(pdf_path),
                ],
            ]
        return [
            [
                exe,
                "--export-area-page",
                f"--export-plain-svg={target_svg}",
                str(pdf_path),
            ],
            [
                exe,
                "-D",
                "--export-plain-svg",
                str(target_svg),
                str(pdf_path),
            ],
            [
                exe,
                "-z",
                "-l",
                str(target_svg),
                str(pdf_path),
            ],
        ]

    def try_inkscape_export(target_svg: Path) -> Tuple[bool, str]:
        try:
            exe = find_inkscape()
        except Exception as exc:
            return False, f"Inkscape unavailable: {exc}"

        logger(f"Using Inkscape: {exe}")
        last_error = ""
        for i, cmd in enumerate(inkscape_candidates(exe, target_svg), start=1):
            logger(f"Inkscape command #{i}: {' '.join([Path(str(cmd[0])).name] + [str(x) for x in cmd[1:]])}")
            rc, out, err = run_cmd(cmd)
            if rc == 0 and target_svg.exists() and target_svg.stat().st_size > 0:
                return True, "ok"
            block = (out + "\n" + err).strip()
            if block and len(block) > 500:
                block = block[:500] + " ..."
            logger(f"Inkscape command #{i} failed or produced empty SVG: {block}")
            if block:
                last_error = block
        return False, last_error or "unknown Inkscape export failure"

    def try_pdftocairo_export(target_svg: Path) -> Tuple[bool, str]:
        try:
            cairo = find_pdftocairo()
        except Exception as exc:
            return False, f"pdftocairo unavailable: {exc}"
        cairo_prefix = target_svg.with_suffix("")
        cmd = [cairo, "-svg", "-f", "1", "-l", "1", str(pdf_path), str(cairo_prefix)]
        logger(f"Trying pdftocairo: {' '.join(cmd)}")
        rc, out, err = run_cmd(cmd)
        if rc != 0:
            block = (out + "\n" + err).strip()
            if block and len(block) > 500:
                block = block[:500] + " ..."
            return False, block or f"rc={rc}"
        if ensure_svg_exists(cairo_prefix, target_svg):
            return True, "ok"
        return False, "svg not produced"

    exports: List[Tuple[str, Path]] = []

    # 1) Inkscape PDF import is optional and disabled by default to avoid interactive
    # "PDF import options" dialog windows.
    if USE_INKSCAPE_PDF_IMPORT:
        ink_svg = svg_path.with_name(f"{svg_path.stem}_inkscape.svg")
        ok_ink, msg_ink = try_inkscape_export(ink_svg)
        if ok_ink:
            try:
                postprocess_text(ink_svg)
                exports.append(("inkscape", ink_svg))
            except Exception as exc:
                logger(f"Inkscape output rejected in postprocess: {exc}")
        else:
            logger(f"Inkscape export failed: {msg_ink}")
    else:
        logger("Inkscape PDF import disabled (USE_INKSCAPE_PDF_IMPORT=False).")

    # 2) pdftocairo fallback/candidate for auto-choice.
    cairo_svg = svg_path.with_name(f"{svg_path.stem}_pdftocairo.svg")
    ok_cairo, msg_cairo = try_pdftocairo_export(cairo_svg)
    if ok_cairo:
        try:
            postprocess_text(cairo_svg)
            exports.append(("pdftocairo", cairo_svg))
        except Exception as exc:
            logger(f"pdftocairo output rejected in postprocess: {exc}")
    else:
        logger(f"pdftocairo export failed: {msg_cairo}")

    if not exports:
        if not USE_INKSCAPE_PDF_IMPORT:
            raise RuntimeError(
                "Failed to convert PDF to SVG with pdftocairo. "
                "Install/configure Poppler pdftocairo or enable Inkscape PDF import in code."
            )
        raise RuntimeError("Failed to convert PDF to SVG with both Inkscape and pdftocairo.")

    best_name = exports[0][0]
    best_svg = exports[0][1]
    best_score, best_details = score_svg_quality(best_svg)
    logger(f"Converter metrics [{best_name}]: {best_details}")

    for name, candidate in exports[1:]:
        score, details = score_svg_quality(candidate)
        logger(f"Converter metrics [{name}]: {details}")
        if score < best_score:
            best_score = score
            best_details = details
            best_name = name
            best_svg = candidate

    if svg_path.exists():
        svg_path.unlink()
    shutil.copyfile(str(best_svg), str(svg_path))
    logger(f"Selected PDF converter: {best_name} ({best_details})")


def word_to_pdf(word_path: Path, pdf_path: Path, logger) -> None:
    logger("Converting Word file to PDF ...")

    if word_path.suffix.lower() not in {".doc", ".docx"}:
        raise ValueError(f"Expected Word file (.doc/.docx), got: {word_path}")

    word_abs = word_path.resolve()
    pdf_abs = pdf_path.resolve()
    pdf_abs.parent.mkdir(parents=True, exist_ok=True)

    try:
        import win32com.client
    except Exception as exc:
        raise RuntimeError("pywin32 is required to convert Word files. Install with: pip install pywin32") from exc

    pythoncom = None
    try:
        import pythoncom as _pythoncom  # type: ignore
        _pythoncom.CoInitialize()
        pythoncom = _pythoncom
    except Exception:
        pythoncom = None

    app = None
    doc = None
    try:
        app = win32com.client.gencache.EnsureDispatch("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        doc = app.Documents.Open(
            str(word_abs),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
        )
        # Word Export format constants:
        # 17 = wdExportFormatPDF
        # Keep call minimal/positional for compatibility across Office versions.
        doc.ExportAsFixedFormat(str(pdf_abs), 17)

        if not pdf_abs.exists() or pdf_abs.stat().st_size == 0:
            raise RuntimeError(f"Word->PDF produced no output: {pdf_abs}")
    except Exception as exc:
        raise RuntimeError(f"Word conversion failed: {exc}") from exc
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def frw_to_pdf(frw_path: Path, pdf_path: Path, logger) -> None:
    logger("Converting CAD file to PDF ...")

    if frw_path.suffix.lower() not in {".frw", ".cdw"}:
        raise ValueError(f"Expected CAD file (.frw/.cdw), got: {frw_path}")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import win32com.client
    except Exception as exc:
        raise RuntimeError("pywin32 is required to convert CAD formats. Install with: pip install pywin32") from exc

    app = None
    try:
        try:
            app = win32com.client.gencache.EnsureDispatch("KOMPAS.Application.7")
        except Exception:
            app = win32com.client.gencache.EnsureDispatch("KOMPAS.Application")

        try:
            app.Visible = False
        except Exception:
            pass

        try:
            app.SuppressAlerts = True
        except Exception:
            pass

        try:
            print_job = app.PrintJob
        except Exception as exc:
            raise RuntimeError("KOMPAS PrintJob is unavailable.") from exc

        try:
            print_job.Clear()
            logger(f"PrintJob.AddSheets: {frw_path}")
            print_job.AddSheets(str(frw_path), 0, 0)
            logger(f"PrintJob.Execute: {pdf_path}")
            result = print_job.Execute(str(pdf_path))
            logger(f"PrintJob.Execute result: {result!r}")
        except Exception as exc:
            raise RuntimeError(f"PrintJob conversion failed: {exc}") from exc

        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            raise RuntimeError(f"CAD->PDF produced no output: {pdf_path}")

    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass

def make_final_with_preamble(prepared_gcode: Path, final_gcode: Path) -> None:
    lines = [
        "$X",
        # Hold steppers while a job is running (prevents Z from back-driving / pen from springing).
        # We explicitly restore to $1=0 in the trailer and also in the sender teardown.
        "$1=255",
        "G21",
        "G90",
        # Always raise pen before any XY move (e.g. before going home).
        f"G0 Z{Z_UP:.4f} F{SAFE_LIFT_FEED:.1f}",
        f"G4 P{Z_DELAY_UP:.2f}",
        f"G92 Z{Z_UP:.4f}",
        f"G0 Z{Z_UP:.4f} F{SAFE_LIFT_FEED:.1f}",
        f"G0 X{HOME_X:.4f} Y{HOME_Y:.4f} F{FEED_TRAVEL:.1f}" if GO_HOME_BEFORE_DRAW else "",
        "",
    ]
    g = prepared_gcode.read_text(encoding="utf-8", errors="ignore")
    trailer = [
        "",
        # End-of-job safety: pen up, optional park to origin.
        f"G0 Z{Z_UP:.4f} F{SAFE_LIFT_FEED:.1f}",
        f"G4 P{Z_DELAY_UP:.2f}",
        f"G0 X{HOME_X:.4f} Y{HOME_Y:.4f} F{FEED_TRAVEL:.1f}" if GO_HOME_AFTER_DRAW else "",
        "M5",
        "G4 P0.10",
        "$1=0",
    ]
    final_gcode.write_text("\n".join(lines) + g + "\n".join(trailer) + "\n", encoding="utf-8")


def _open_serial_no_reset(port: str, baud: int, *, timeout_s: float = 1.0):
    # IMPORTANT: Many GRBL boards reset on DTR when opening the port.
    # Open serial the same way as src/send_grbl_file.py to avoid losing coordinates mid-job.
    import serial  # pyserial

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = int(baud)
    ser.timeout = float(timeout_s)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    ser.open()
    time.sleep(0.2)
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
    except Exception:
        pass
    return ser


def _grbl_readline_ascii(ser) -> str:
    try:
        raw = ser.readline()
    except Exception:
        return ""
    if not raw:
        return ""
    return raw.decode("ascii", errors="replace").strip()


def _grbl_status_line(ser, *, timeout_s: float = 0.8) -> str:
    try:
        ser.write(b"?")
        ser.flush()
    except Exception:
        return ""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        s = _grbl_readline_ascii(ser)
        if s.startswith("<") and s.endswith(">"):
            return s
    return ""


def _parse_grbl_triplet(tag: str, text: str) -> Optional[Tuple[float, float, float]]:
    m = re.search(rf"{re.escape(tag)}:([^|>]+)", text)
    if not m:
        return None
    parts = m.group(1).split(",")
    if len(parts) < 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except Exception:
        return None


def _grbl_query_offsets(ser) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    # Returns (G54, G92)
    try:
        ser.write(b"$#\n")
        ser.flush()
    except Exception:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    t0 = time.time()
    buf: List[str] = []
    while time.time() - t0 < 1.5:
        s = _grbl_readline_ascii(ser)
        if not s:
            continue
        buf.append(s)
        if s == "ok" or s.startswith("error:") or s.startswith("ALARM:"):
            break
    joined = "\n".join(buf)

    def _parse_bracket(tag: str) -> Tuple[float, float, float]:
        m = re.search(rf"\\[{re.escape(tag)}:([^\\]]+)\\]", joined)
        if not m:
            return (0.0, 0.0, 0.0)
        parts = m.group(1).split(",")
        try:
            vals = [float(p) for p in parts[:3]]
        except Exception:
            return (0.0, 0.0, 0.0)
        while len(vals) < 3:
            vals.append(0.0)
        return (vals[0], vals[1], vals[2])

    return _parse_bracket("G54"), _parse_bracket("G92")


def grbl_wait_for_idle(port: str, baud: str, logger, *, timeout_s: float = 600.0) -> None:
    ser = _open_serial_no_reset(port, int(baud), timeout_s=0.5)
    try:
        t0 = time.time()
        last_log = 0.0
        while True:
            if time.time() - t0 > timeout_s:
                raise RuntimeError("Timeout waiting for GRBL to become Idle.")
            st = _grbl_status_line(ser, timeout_s=0.8)
            if st.startswith("<Idle|"):
                return
            if time.time() - last_log > 2.0 and st:
                logger(st)
                last_log = time.time()
            time.sleep(0.25)
    finally:
        try:
            ser.close()
        except Exception:
            pass


def grbl_get_wpos_xyz(port: str, baud: str) -> Tuple[float, float, float]:
    # Prefer WPos if present; else compute from MPos and WCO/($#).
    ser = _open_serial_no_reset(port, int(baud), timeout_s=0.8)
    try:
        st = _grbl_status_line(ser, timeout_s=0.8)
        wpos = _parse_grbl_triplet("WPos", st) if st else None
        if wpos is not None:
            return wpos
        mpos = _parse_grbl_triplet("MPos", st) if st else None
        if mpos is None:
            raise RuntimeError(f"Cannot read GRBL position (status='{st}').")
        wco = _parse_grbl_triplet("WCO", st) if st else None
        if wco is None:
            g54, g92 = _grbl_query_offsets(ser)
            wco = (g54[0] + g92[0], g54[1] + g92[1], g54[2] + g92[2])
        return (mpos[0] - wco[0], mpos[1] - wco[1], mpos[2] - wco[2])
    finally:
        try:
            ser.close()
        except Exception:
            pass


def _gcode_find_nearest_g0_xy_line(gcode_file: Path, *, x: float, y: float) -> int:
    # Find nearest G0 XY endpoint to current position. We resume at a travel move to avoid dragging the pen.
    x_re = re.compile(r"\bX(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    y_re = re.compile(r"\bY(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")

    cur_x: Optional[float] = None
    cur_y: Optional[float] = None
    best_d = float("inf")
    best_line = 1

    with gcode_file.open("r", encoding="utf-8", errors="ignore") as fh:
        for ln, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith(";") or line.startswith("("):
                continue
            sx = x_re.search(line)
            sy = y_re.search(line)
            if sx:
                cur_x = float(sx.group(1))
            if sy:
                cur_y = float(sy.group(1))

            if not line.startswith("G0"):
                continue
            # Only consider G0 lines that actually move in XY.
            if ("X" not in line) and ("Y" not in line):
                continue
            if cur_x is None or cur_y is None:
                continue
            d = (cur_x - x) ** 2 + (cur_y - y) ** 2
            if d < best_d:
                best_d = d
                best_line = ln

    return best_line


def _write_resume_file(src_gcode: Path, dst_gcode: Path, *, start_line: int) -> None:
    # Resume file must NOT include G92 (it would shift coordinates). We only restore modal state + pen up.
    src_lines = src_gcode.read_text(encoding="utf-8", errors="ignore").splitlines()
    payload = src_lines[max(0, int(start_line) - 1) :]
    pre = [
        "$X",
        "$1=255",
        "G21",
        "G90",
        "G17",
        "G91.1",
        f"G0 Z{Z_UP:.4f} F{SAFE_LIFT_FEED:.1f}",
        f"G4 P{Z_DELAY_UP:.2f}",
        f"; AUTO-RESUME from line {start_line} of {src_gcode.name}",
        "",
    ]
    dst_gcode.parent.mkdir(parents=True, exist_ok=True)
    dst_gcode.write_text("\n".join(pre + payload) + "\n", encoding="utf-8")


def send_to_grbl(
    gcode_file: Path,
    com: str,
    baud: str,
    logger,
    *,
    sleep_after: bool = False,
    auto_resume: bool = False,
    max_resume_attempts: int = 1,
) -> float:
    sender = ROOT_DIR / "src" / "send_grbl_file.py"
    if not sender.exists():
        raise RuntimeError("send_grbl_file.py not found")
    cmd = [sys.executable, str(sender), com, baud, str(gcode_file)]
    if sleep_after:
        cmd.append("--sleep")
    logger("Sending to Grbl ...")
    started = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout is None:
        raise RuntimeError("Failed to read sender output")
    out_lines: List[str] = []
    sender_plot_time_s: Optional[float] = None
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        s = line.strip()
        out_lines.append(s)
        logger(s)
        if s.startswith("PLOT_TIME_SECONDS="):
            try:
                sender_plot_time_s = float(s.split("=", 1)[1].strip())
            except Exception:
                pass
    rc = proc.wait()
    elapsed = time.perf_counter() - started
    if rc == 0:
        return sender_plot_time_s if sender_plot_time_s is not None else max(0.0, elapsed)

    # Sender failed.
    if not auto_resume or max_resume_attempts <= 0:
        # Surface the most relevant lines to the caller.
        tail = "\n".join(out_lines[-8:]) if out_lines else ""
        raise RuntimeError(f"Sender error code: {rc}\n{tail}".strip())

    logger("Sender failed. Waiting for machine to become Idle, then auto-resuming from current position...")
    grbl_wait_for_idle(com, baud, logger)
    wx, wy, _wz = grbl_get_wpos_xyz(com, baud)
    start_line = _gcode_find_nearest_g0_xy_line(gcode_file, x=wx, y=wy)
    resume_path = ensure_local_tmp_root() / f"resume_{gcode_file.stem}_from_{start_line}.nc"
    _write_resume_file(gcode_file, resume_path, start_line=start_line)
    logger(f"Auto-resume: WPos=({wx:.3f},{wy:.3f}), start_line={start_line}, file={resume_path}")
    # Second attempt: do not recurse forever.
    resumed = send_to_grbl(
        resume_path,
        com,
        baud,
        logger,
        sleep_after=sleep_after,
        auto_resume=False,
        max_resume_attempts=0,
    )
    return max(0.0, elapsed) + max(0.0, resumed)

def run_pipeline(
    input_path: Path,
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
    feed_travel: float = FEED_TRAVEL,
    feed_draw: float = FEED_DRAW,
    auto_resume: bool = True,
) -> Tuple[bool, str]:
    try:
        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root())) as td:
            work = Path(td)
            svg_path = work / "source.svg"
            xy_path = work / "path_xy.gcode"
            pen_path = work / "path_pen.gcode"
            final_path = work / "path_final.gcode"

            ext = input_path.suffix.lower()
            input_is_word = ext in {".doc", ".docx"}
            if ext == ".svg":
                svg_path = work / "source.svg"
                shutil.copyfile(str(input_path), str(svg_path))
                if svg_path is None or not svg_path.exists():
                    return False, "Input SVG file not found."
            elif input_is_word:
                pdf_tmp = work / "source.pdf"
                word_to_pdf(input_path, pdf_tmp, log)
                pdf_to_svg(pdf_tmp, svg_path, log)
            elif ext in {".frw", ".cdw"}:
                pdf_tmp = work / "source.pdf"
                frw_to_pdf(input_path, pdf_tmp, log)
                pdf_to_svg(pdf_tmp, svg_path, log)
            else:
                pdf_to_svg(input_path, svg_path, log)

            try:
                if svg_has_text_nodes(svg_path):
                    if not convert_svg_text_to_paths(svg_path, log):
                        return False, "Text conversion did not produce valid paths."
                    if svg_has_text_nodes(svg_path):
                        return False, "Text conversion left unresolved text nodes."
                    log(f"Text nodes after conversion: {svg_text_node_count(svg_path)}")
            except Exception as exc:
                return False, f"Text->path conversion failed: {exc}"

            log("Extracting paths from SVG ...")
            path_items = extract_polylines(svg_path)
            add_image_contours = IMAGE_CONTOUR_ENABLED and (not IMAGE_CONTOUR_WORD_ONLY or input_is_word)
            if add_image_contours:
                image_items = extract_image_contour_items(svg_path, logger=log)
                if image_items:
                    path_items.extend(image_items)
                    log(f"Image contour tracing: total +{len(image_items)} path(s).")
            if not path_items:
                return False, "No drawable paths found in file."

            raw_bounds = bounds_path_items(path_items)
            if raw_bounds:
                raw_min_x, raw_max_x, raw_min_y, raw_max_y = raw_bounds
                log(f"Raw geometry bounds: x({raw_min_x:.3f}, {raw_max_x:.3f}) y({raw_min_y:.3f}, {raw_max_y:.3f})")

            page_w, page_h = svg_page_size_mm(svg_path)
            if page_w > 0.0 and page_h > 0.0:
                log(f"SVG page: {page_w:.3f} x {page_h:.3f} mm")
            else:
                log("SVG page: unknown, content area crop skipped.")

            if page_w > 0.0 and page_h > 0.0:
                path_items, unit_scale = normalize_path_units_to_page(path_items, page_w, page_h, logger=log)
                if unit_scale != 1.0:
                    scaled_bounds = bounds_path_items(path_items)
                    if scaled_bounds:
                        s_min_x, s_max_x, s_min_y, s_max_y = scaled_bounds
                        log(
                            f"Bounds after unit normalization: x({s_min_x:.3f}, {s_max_x:.3f}) "
                            f"y({s_min_y:.3f}, {s_max_y:.3f})"
                        )

            trim_debug_target: Optional[Path] = None
            if not send_to_plotter:
                preview_name = input_path.stem + "_trimmed.svg"
                if output_path is not None:
                    trim_debug_target = output_path.with_suffix(".svg")
                else:
                    trim_debug_target = input_path.with_name(preview_name)

            if EXACT_GEOMETRY_MODE:
                trimmed_items = path_items
                trimmed_candidates: List[PathItem] = []
                log("Exact geometry mode: keeping full source geometry (no outer-frame trim, no page-margin crop).")
            else:
                trimmed_items, trimmed_candidates = filter_outer_frame_path_items(path_items, log)
                if trimmed_candidates:
                    log(f"Auto trim: removed {len(trimmed_candidates)} outer border element(s).")
                    for idx, c in enumerate(trimmed_candidates, start=1):
                        c_bounds = bounds_polylines([c.points]) if c.points else None
                        if c_bounds:
                            x0, x1, y0, y1 = c_bounds
                            log(
                                f"  - removed {idx}: points={len(c.points)} bbox={x0:.3f}..{x1:.3f}x{y0:.3f}..{y1:.3f} "
                                f"closed={c.closed} stroke={c.is_stroke} fill={c.is_fill}"
                            )
                    if raw_bounds:
                        trimmed_bounds = bounds_path_items(trimmed_items)
                        if trimmed_bounds:
                            min_x_t, max_x_t, min_y_t, max_y_t = trimmed_bounds
                            log(
                                f"Bounds after border removal: x({min_x_t:.3f}, {max_x_t:.3f}) "
                                f"y({min_y_t:.3f}, {max_y_t:.3f})"
                            )
                    if trim_debug_target is not None:
                        try:
                            write_outer_trim_preview_svg(path_items, trimmed_candidates, trim_debug_target)
                            log(f"Trim preview: {trim_debug_target}")
                        except Exception as exc:
                            log(f"Warning: failed to write trim preview: {exc}")
                elif AUTO_TRIM_OUTER_FRAME:
                    log("Auto trim: no outer border detected.")

                if page_w > 0.0 and page_h > 0.0:
                    trimmed_items, clipped_by_margins = clip_to_content_area(trimmed_items, page_w, page_h, logger=log)
                    if clipped_by_margins:
                        cropped_bounds = bounds_path_items(trimmed_items)
                        if cropped_bounds:
                            min_x_c, max_x_c, min_y_c, max_y_c = cropped_bounds
                            log(
                                f"Bounds after content margin crop: x({min_x_c:.3f}, {max_x_c:.3f}) "
                                f"y({min_y_c:.3f}, {max_y_c:.3f})"
                            )

            path_items = trimmed_items
            polylines = to_drawing_polylines(path_items)
            if not polylines:
                return False, "No drawable geometry found after fill/stroke analysis."
            src_segments = sum(max(0, len(p) - 1) for p in polylines)
            log(f"SVG geometry: paths={len(polylines)}, segments={src_segments}.")
            min_x, max_x, min_y, max_y = bounds_polylines(polylines)
            log(f"Source bounds: x({min_x:.3f}, {max_x:.3f}) y({min_y:.3f}, {max_y:.3f})")
            polylines = fit_polylines_to_area(polylines, min_x, max_x, min_y, max_y, logger=log)
            fit_segments = sum(max(0, len(p) - 1) for p in polylines)
            polylines = clip_polylines_to_work_area(polylines, logger=log)
            if not polylines:
                return False, "No drawable geometry remains after clipping to work area."
            clipped_segments = sum(max(0, len(p) - 1) for p in polylines)
            polylines = deduplicate_segments(polylines, eps=SEGMENT_DEDUP_EPS_MM, logger=log)
            before_poly_count = len(polylines)
            polylines = stitch_polylines(polylines, STITCH_EPS_MM, logger=log)
            polylines = reorder_polylines(polylines, logger=log)
            after_poly_count = len(polylines)
            if after_poly_count != before_poly_count:
                log(f"Polyline optimization: {before_poly_count} -> {after_poly_count}")
            log(f"Segment counts: source={src_segments}, fitted={fit_segments}, clipped={clipped_segments}")
            if src_segments > 0:
                keep_ratio = (clipped_segments / float(src_segments)) * 100.0
                log(f"Drawable segments after clip: {clipped_segments} ({keep_ratio:.1f}% of source)")
                if keep_ratio < 98.0:
                    log("Warning: significant clipping/transforming occurred. Check that page is inside target work area.")
            min_x, max_x, min_y, max_y = bounds_polylines(polylines)
            log(f"Prepared bounds: x({min_x:.3f}, {max_x:.3f}) y({min_y:.3f}, {max_y:.3f})")
            draw_length_mm = total_draw_length_mm(polylines)
            log(f"Estimated draw length: {draw_length_mm / 1000.0:.2f} m")

            effective_z_down = Z_DOWN
            pencil_state = None
            dynamic_wear_start = 0.0
            if TOOL_MODE == "pencil":
                pencil_state = load_pencil_state()
                effective_z_down, pencil_comp = pencil_effective_z_down(PENCIL_BASE_Z_DOWN, pencil_state)
                dynamic_wear_start = max(0.0, float(pencil_state.get("estimated_wear_mm", 0.0) or 0.0))
                dyn_slope = max(0.0, float(PENCIL_WEAR_MM_PER_M)) * max(0.0, float(PENCIL_Z_COMP_MM_PER_WEAR_MM))
                rem_best, rem_wear, rem_interval = pencil_remaining_to_sharpen_m(pencil_state)
                rem_m_txt = "inf" if not math.isfinite(rem_best) else f"{rem_best:.1f}"
                rem_wear_txt = "inf" if not math.isfinite(rem_wear) else f"{rem_wear:.1f}"
                rem_interval_txt = "inf" if not math.isfinite(rem_interval) else f"{rem_interval:.1f}"
                log(
                    "Pencil mode: "
                    f"base_z={PENCIL_BASE_Z_DOWN:.3f}, wear={dynamic_wear_start:.3f} mm, "
                    f"z_comp_start={pencil_comp:.3f}, z_down_start={effective_z_down:.3f}, "
                    f"dyn(rate={PENCIL_WEAR_MM_PER_M:.4f} mm/m, comp={PENCIL_Z_COMP_MM_PER_WEAR_MM:.3f}, "
                    f"slope={dyn_slope:.4f} Zmm/m, max={PENCIL_MAX_COMP_MM:.3f}), "
                    f"est_remaining_to_sharpen={rem_m_txt} m (wear={rem_wear_txt}, interval={rem_interval_txt})"
                )
                wear_now = float(pencil_state.get("estimated_wear_mm", 0.0) or 0.0)
                if wear_now >= PENCIL_REMIND_WEAR_MM:
                    log(
                        f"Reminder: estimated pencil wear is {wear_now:.2f} mm "
                        f"(threshold {PENCIL_REMIND_WEAR_MM:.2f} mm). Sharpen is recommended."
                    )
                if math.isfinite(rem_interval) and rem_interval <= 0.0:
                    log(
                        f"Reminder: draw length since last sharpen reached {float(PENCIL_SHARPEN_INTERVAL_M):.2f} m. "
                        "Sharpen is recommended."
                    )
            write_xy_gcode(xy_path, polylines, feed_travel, feed_draw)
            log("Applying pen-up / pen-down ...")
            apply_penlift(
                xy_path,
                pen_path,
                z_down=effective_z_down,
                dynamic_z_enable=(TOOL_MODE == "pencil"),
                dynamic_base_z_down=PENCIL_BASE_Z_DOWN if TOOL_MODE == "pencil" else None,
                dynamic_initial_wear_mm=dynamic_wear_start,
            )
            make_final_with_preamble(pen_path, final_path)
            gcode_lines, gcode_draw, gcode_travel, gcode_bounds = summarize_gcode_file(final_path)
            log(
                f"G-code stats: lines={gcode_lines}, draw={gcode_draw}, travel={gcode_travel}, "
                f"bounds={gcode_bounds[0]:.3f}..{gcode_bounds[1]:.3f} x, "
                f"{gcode_bounds[2]:.3f}..{gcode_bounds[3]:.3f} y"
            )
            if send_to_plotter:
                plot_time_s = send_to_grbl(
                    final_path,
                    com,
                    baud,
                    log,
                    sleep_after=True,
                    auto_resume=bool(auto_resume),
                    max_resume_attempts=1,
                )
                if TOOL_MODE == "pencil" and pencil_state is not None:
                    pencil_state = apply_pencil_wear_update(pencil_state, draw_length_mm)
                    save_pencil_state(pencil_state)
                    wear_now = float(pencil_state.get("estimated_wear_mm", 0.0))
                    rem_best, rem_wear, rem_interval = pencil_remaining_to_sharpen_m(pencil_state)
                    rem_m_txt = "inf" if not math.isfinite(rem_best) else f"{rem_best:.1f}"
                    rem_wear_txt = "inf" if not math.isfinite(rem_wear) else f"{rem_wear:.1f}"
                    rem_interval_txt = "inf" if not math.isfinite(rem_interval) else f"{rem_interval:.1f}"
                    log(
                        f"Pencil state updated: wear={wear_now:.2f} mm, "
                        f"estimated remaining before sharpen: {rem_m_txt} m "
                        f"(wear={rem_wear_txt}, interval={rem_interval_txt})"
                    )
                    if wear_now >= PENCIL_REMIND_WEAR_MM:
                        log(
                            f"Pencil reminder: accumulated wear {wear_now:.2f} mm. "
                            "Sharpen pencil and run with --pencil-sharpened."
                        )
                    if math.isfinite(rem_interval) and rem_interval <= 0.0:
                        log(
                            "Pencil reminder: draw-length interval reached. "
                            "Sharpen pencil and run with --pencil-sharpened."
                        )
                return_msg = (
                    f"Done: {input_path.name} sent. "
                    f"Plot time: {format_duration_hms(plot_time_s)} ({plot_time_s:.1f}s)"
                )
                if TOOL_MODE == "pencil" and pencil_state is not None:
                    return_msg += (
                        f"; pencil wear={float(pencil_state.get('estimated_wear_mm', 0.0)):.2f} mm "
                        f"(draw={draw_length_mm / 1000.0:.2f} m)"
                    )
            else:
                target = output_path or input_path.with_name(f"{input_path.stem}_prepared.nc")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(final_path.read_text(encoding="utf-8"), encoding="utf-8")
                target_lines, target_draw, target_travel, target_bounds = summarize_gcode_file(target)
                log(
                    f"Saved file stats: lines={target_lines}, draw={target_draw}, travel={target_travel}, "
                    f"bounds={target_bounds[0]:.3f}..{target_bounds[1]:.3f} x, "
                    f"{target_bounds[2]:.3f}..{target_bounds[3]:.3f} y"
                )
                log(f"Saved: {target}")
                return_msg = f"Done: prepared file saved to {target}"
                if TOOL_MODE == "pencil":
                    return_msg += f" (estimated pencil draw length {draw_length_mm / 1000.0:.2f} m)"
            return True, return_msg
    except Exception as exc:
        return False, f"Error: {exc}"


def _ask_confirmation_in_console(prompt: str = "Continue drawing?") -> bool:
    try:
        reply = input(f"{prompt} [y/n]: ").strip().lower()
    except EOFError:
        return False
    return reply in {"y", "yes", "\u0434\u0430", "\u0434"}


def run_pipeline_with_corner_calibration(
    input_path: Path,
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
    skip_calibration: bool = False,
    skip_confirmation: bool = False,
    corner_mark_size: float = 2.0,
    feed_travel: float = FEED_TRAVEL,
    feed_draw: float = FEED_DRAW,
    auto_resume: bool = True,
) -> Tuple[bool, str]:
    if send_to_plotter and not skip_calibration:
        ok, msg = run_corner_calibration_pipeline(
            log,
            com=com,
            baud=baud,
            send_to_plotter=send_to_plotter,
            mark_size=corner_mark_size,
        )
        if not ok:
            return False, msg

        if not skip_confirmation:
            if not _ask_confirmation_in_console("РљР°Р»РёР±СЂРѕРІРєР° 4-С… СѓРіР»РѕРІ РІС‹РїРѕР»РЅРµРЅР°. Р’СЃС‘ Р»Рё РїСЂР°РІРёР»СЊРЅРѕ? РџСЂРѕРґРѕР»Р¶Р°С‚СЊ СЂРёСЃРѕРІР°РЅРёРµ?"):
                return False, "Canceled by user before drawing."

    return run_pipeline(
        input_path,
        log,
        com=com,
        baud=baud,
        send_to_plotter=send_to_plotter,
        output_path=output_path,
        feed_travel=feed_travel,
        feed_draw=feed_draw,
        auto_resume=auto_resume,
    )


def run_frame_pipeline(
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    try:
        frame = build_area_frame_polylines()
        if not frame:
            return False, "Invalid work area limits."
        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root())) as td:
            work = Path(td)
            xy_path = work / "work_area_xy.gcode"
            pen_path = work / "work_area_pen.gcode"
            final_path = work / "work_area_final.gcode"

            frame = clip_polylines_to_work_area(frame, logger=log)
            write_xy_gcode(xy_path, frame, FEED_TRAVEL, FEED_DRAW)
            log("Applying pen-up / pen-down ...")
            apply_penlift(xy_path, pen_path)
            make_final_with_preamble(pen_path, final_path)
            if send_to_plotter:
                send_to_grbl(final_path, com, baud, log, sleep_after=True)
                return_msg = "Done: work area frame sent."
            else:
                target = output_path or Path("work_area_frame_prepared.nc")
                target.write_text(final_path.read_text(encoding="utf-8"), encoding="utf-8")
                log(f"Saved: {target}")
                return_msg = f"Done: work area frame saved to {target}"
        return True, return_msg
    except Exception as exc:
        return False, f"Error: {exc}"


def run_corner_calibration_pipeline(
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
    mark_size: float = 2.0,
) -> Tuple[bool, str]:
    try:
        marks = build_area_corner_mark_polylines(mark_size=mark_size)
        if not marks:
            return False, "Invalid work area limits."

        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root())) as td:
            work = Path(td)
            xy_path = work / "corner_xy.gcode"
            pen_path = work / "corner_pen.gcode"
            final_path = work / "corner_final.gcode"

            all_paths: List[List[Tuple[float, float]]] = []
            all_paths.extend(marks)

            all_paths = clip_polylines_to_work_area(all_paths, logger=log)
            if not all_paths:
                return False, "No geometry after clipping work area."

            write_xy_gcode(xy_path, all_paths, FEED_TRAVEL, FEED_DRAW)
            log("Applying pen-up / pen-down ...")
            apply_penlift(xy_path, pen_path)
            make_final_with_preamble(pen_path, final_path)

            if send_to_plotter:
                send_to_grbl(final_path, com, baud, log, sleep_after=True)
                return_msg = "Done: 4-corner calibration sent."
            else:
                target = output_path or Path("corner_calibration_prepared.nc")
                target.write_text(final_path.read_text(encoding="utf-8"), encoding="utf-8")
                log(f"Saved: {target}")
                return_msg = f"Done: calibration file saved to {target}"
        return True, return_msg
    except Exception as exc:
        return False, f"Error: {exc}"


def run_pencil_wear_test_pipeline(
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
    feed_travel: float = FEED_TRAVEL,
    feed_draw: float = FEED_DRAW,
    auto_resume: bool = True,
    levels: int = 8,
    cols: int = 2,
    hatch_step_mm: float = 1.0,
    hatch_loops: int = 1,
    margin_mm: float = 8.0,
    gap_mm: float = 6.0,
) -> Tuple[bool, str]:
    try:
        polylines, stage_stats = build_pencil_wear_test_polylines(
            levels=levels,
            cols=cols,
            margin_mm=margin_mm,
            gap_mm=gap_mm,
            hatch_step_mm=hatch_step_mm,
            hatch_loops=hatch_loops,
        )
        if not polylines:
            return False, "Failed to build pencil wear-test geometry for current active area."

        polylines = clip_polylines_to_work_area(polylines, logger=log)
        if not polylines:
            return False, "No wear-test geometry remains after clipping."

        draw_length_mm = total_draw_length_mm(polylines)
        log(
            f"Pencil wear-test geometry: stages={len(stage_stats)}, "
            f"paths={len(polylines)}, draw={draw_length_mm / 1000.0:.2f} m."
        )
        for st in stage_stats:
            x0, x1, y0, y1 = st["bbox"]
            log(
                f"  stage {int(st['stage']):02d} (r{int(st['row'])}/c{int(st['col'])}) "
                f"draw={float(st['draw_mm']) / 1000.0:.2f} m, cum={float(st['cum_mm']) / 1000.0:.2f} m, "
                f"bbox=({x0:.1f},{y0:.1f})..({x1:.1f},{y1:.1f})"
            )
        log(
            "After checking printed blocks, run: "
            "python src\\plotter_pdf_drawer.py --tool pencil "
            "--pencil-calibrate-from-last-test-stage N "
            "[--pencil-calibrate-first-bad-stage M]"
        )
        report = {
            "created_at_utc": _now_iso_utc(),
            "levels": int(levels),
            "cols": int(cols),
            "hatch_step_mm": float(hatch_step_mm),
            "hatch_loops": int(hatch_loops),
            "margin_mm": float(margin_mm),
            "gap_mm": float(gap_mm),
            "draw_total_mm": float(draw_length_mm),
            "profile_snapshot": build_pencil_profile_snapshot(),
            "stage_stats": [
                {
                    "stage": int(st["stage"]),
                    "row": int(st["row"]),
                    "col": int(st["col"]),
                    "draw_mm": float(st["draw_mm"]),
                    "cum_mm": float(st["cum_mm"]),
                    "bbox": [float(st["bbox"][0]), float(st["bbox"][1]), float(st["bbox"][2]), float(st["bbox"][3])],
                }
                for st in stage_stats
            ],
        }
        save_last_wear_test_report(report)
        log(f"Saved wear-test report: {PENCIL_WEAR_TEST_LAST_PATH}")

        effective_z_down = Z_DOWN
        pencil_state = None
        dynamic_wear_start = 0.0
        if TOOL_MODE == "pencil":
            pencil_state = load_pencil_state()
            dynamic_wear_start = max(0.0, float(pencil_state.get("estimated_wear_mm", 0.0) or 0.0))
            effective_z_down, _pencil_comp = pencil_effective_z_down(PENCIL_BASE_Z_DOWN, pencil_state)
            dyn_slope = max(0.0, float(PENCIL_WEAR_MM_PER_M)) * max(0.0, float(PENCIL_Z_COMP_MM_PER_WEAR_MM))
            rem_best, rem_wear, rem_interval = pencil_remaining_to_sharpen_m(pencil_state)
            rem_best_txt = "inf" if not math.isfinite(rem_best) else f"{rem_best:.1f}"
            rem_wear_txt = "inf" if not math.isfinite(rem_wear) else f"{rem_wear:.1f}"
            rem_interval_txt = "inf" if not math.isfinite(rem_interval) else f"{rem_interval:.1f}"
            log(
                "Pencil wear-test mode: "
                f"base_z={PENCIL_BASE_Z_DOWN:.3f}, wear_start={dynamic_wear_start:.3f} mm, "
                f"z_down_start={effective_z_down:.3f}, "
                f"dyn(rate={PENCIL_WEAR_MM_PER_M:.4f} mm/m, comp={PENCIL_Z_COMP_MM_PER_WEAR_MM:.3f}, "
                f"slope={dyn_slope:.4f} Zmm/m, max={PENCIL_MAX_COMP_MM:.3f}), "
                f"remaining={rem_best_txt} m (wear={rem_wear_txt}, interval={rem_interval_txt})"
            )
        else:
            log("Wear-test requested in pen mode. Use --tool pencil for adaptive pressure calibration.")

        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root())) as td:
            work = Path(td)
            xy_path = work / "wear_test_xy.gcode"
            pen_path = work / "wear_test_pen.gcode"
            final_path = work / "wear_test_final.gcode"

            write_xy_gcode(xy_path, polylines, feed_travel, feed_draw)
            log("Applying pen-up / pen-down ...")
            apply_penlift(
                xy_path,
                pen_path,
                z_down=effective_z_down,
                dynamic_z_enable=(TOOL_MODE == "pencil"),
                dynamic_base_z_down=PENCIL_BASE_Z_DOWN if TOOL_MODE == "pencil" else None,
                dynamic_initial_wear_mm=dynamic_wear_start,
            )
            make_final_with_preamble(pen_path, final_path)

            gcode_lines, gcode_draw, gcode_travel, gcode_bounds = summarize_gcode_file(final_path)
            log(
                f"G-code stats: lines={gcode_lines}, draw={gcode_draw}, travel={gcode_travel}, "
                f"bounds={gcode_bounds[0]:.3f}..{gcode_bounds[1]:.3f} x, "
                f"{gcode_bounds[2]:.3f}..{gcode_bounds[3]:.3f} y"
            )

            if send_to_plotter:
                plot_time_s = send_to_grbl(
                    final_path,
                    com,
                    baud,
                    log,
                    sleep_after=True,
                    auto_resume=bool(auto_resume),
                    max_resume_attempts=1,
                )
                if TOOL_MODE == "pencil" and pencil_state is not None:
                    pencil_state = apply_pencil_wear_update(pencil_state, draw_length_mm)
                    save_pencil_state(pencil_state)
                    wear_now = float(pencil_state.get("estimated_wear_mm", 0.0))
                    rem_best, rem_wear, rem_interval = pencil_remaining_to_sharpen_m(pencil_state)
                    rem_m_txt = "inf" if not math.isfinite(rem_best) else f"{rem_best:.1f}"
                    rem_wear_txt = "inf" if not math.isfinite(rem_wear) else f"{rem_wear:.1f}"
                    rem_interval_txt = "inf" if not math.isfinite(rem_interval) else f"{rem_interval:.1f}"
                    log(
                        f"Pencil state updated: wear={wear_now:.2f} mm, "
                        f"estimated remaining before sharpen: {rem_m_txt} m "
                        f"(wear={rem_wear_txt}, interval={rem_interval_txt})"
                    )
                    if wear_now >= PENCIL_REMIND_WEAR_MM:
                        log(
                            f"Pencil reminder: accumulated wear {wear_now:.2f} mm. "
                            "Sharpen pencil and run with --pencil-sharpened."
                        )
                    if math.isfinite(rem_interval) and rem_interval <= 0.0:
                        log(
                            "Pencil reminder: draw-length interval reached. "
                            "Sharpen pencil and run with --pencil-sharpened."
                        )
                return True, (
                    "Done: pencil wear-test sent. "
                    f"Plot time: {format_duration_hms(plot_time_s)} ({plot_time_s:.1f}s), "
                    f"draw={draw_length_mm / 1000.0:.2f} m."
                )

            target = output_path or Path("pencil_wear_test_prepared.nc")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(final_path.read_text(encoding="utf-8"), encoding="utf-8")
            log(f"Saved: {target}")
            return True, f"Done: pencil wear-test saved to {target} (draw={draw_length_mm / 1000.0:.2f} m)."
    except Exception as exc:
        return False, f"Error: {exc}"


def summarize_gcode_file(gcode_path: Path) -> Tuple[int, int, int, Tuple[float, float, float, float]]:
    total_lines = 0
    draw_moves = 0
    travel_moves = 0
    min_x = math.inf
    max_x = -math.inf
    min_y = math.inf
    max_y = -math.inf

    x_re = re.compile(r"\bX(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    y_re = re.compile(r"\bY(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    i_re = re.compile(r"\bI(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    j_re = re.compile(r"\bJ(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    g_re = re.compile(r"\bG(\d+)")

    cur_x = None
    cur_y = None

    with gcode_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith(";") or line.startswith("("):
                continue
            total_lines += 1

            g_match = g_re.search(line)
            if g_match:
                code = int(g_match.group(1))
            else:
                code = None

            sx = x_re.search(line)
            sy = y_re.search(line)
            x = float(sx.group(1)) if sx else None
            y = float(sy.group(1)) if sy else None
            si = i_re.search(line)
            sj = j_re.search(line)

            # Update bounds. For G2/G3, include arc "bulge" (not just endpoints).
            if code in {2, 3} and cur_x is not None and cur_y is not None and x is not None and y is not None and si and sj:
                i = float(si.group(1))
                j = float(sj.group(1))
                start = (cur_x, cur_y)
                end = (x, y)
                center = (cur_x + i, cur_y + j)
                if points_distance(start, end) <= 1e-6:
                    r = math.hypot(start[0] - center[0], start[1] - center[1])
                    ax0, ax1, ay0, ay1 = (center[0] - r, center[0] + r, center[1] - r, center[1] + r)
                else:
                    ax0, ax1, ay0, ay1 = arc_extents_xy(start, end, center, cw=(code == 2))
                min_x = min(min_x, ax0)
                max_x = max(max_x, ax1)
                min_y = min(min_y, ay0)
                max_y = max(max_y, ay1)
                cur_x, cur_y = end
            elif x is not None and y is not None:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                cur_x, cur_y = x, y

            if code in {1, 2, 3}:
                draw_moves += 1
            elif code == 0:
                travel_moves += 1

    if min_x == math.inf:
        return total_lines, draw_moves, travel_moves, (0.0, 0.0, 0.0, 0.0)
    return total_lines, draw_moves, travel_moves, (min_x, max_x, min_y, max_y)


def warn_if_text_nodes_left(svg_path: Path, logger) -> None:
    if svg_has_text_nodes(svg_path):
        logger("Warning: SVG still contains <text> nodes after conversion. "
               "Install/use Inkscape with text->path support if text is missing.")


def open_with_default_viewer(path: Path, logger=print) -> None:
    try:
        os.startfile(str(path))
        logger(f"Opened preview: {path}")
    except Exception as exc:
        logger(f"Cannot open preview automatically: {exc}")


def ensure_local_tmp_root() -> Path:
    # Sandbox-friendly temp location (system temp can be non-writable in restricted environments).
    LOCAL_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    return LOCAL_TMP_ROOT


def grbl_send_manual_commands(
    com: str,
    baud: str,
    commands: List[str],
    *,
    soft_reset_first: bool = False,
    read_tail: bool = True,
) -> Tuple[bool, str]:
    try:
        import serial  # type: ignore
    except Exception as exc:
        return False, f"pyserial not available: {exc}"

    port = (com or "").strip()
    if not port:
        return False, "COM port is empty."
    try:
        baud_i = int(str(baud).strip() or DEFAULT_BAUD)
    except Exception:
        baud_i = int(DEFAULT_BAUD)

    ser = None
    try:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud_i
        ser.timeout = 1.0
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        ser.open()

        # Wake channel.
        ser.write(b"\r\n")
        ser.flush()
        time.sleep(0.20)
        ser.read(4096)

        if soft_reset_first:
            ser.write(b"\x18")
            ser.flush()
            time.sleep(1.0)
            ser.read(4096)

        for cmd in commands:
            line = (cmd or "").strip()
            if not line:
                continue
            ser.write((line + "\n").encode("ascii", errors="replace"))
            ser.flush()
            time.sleep(0.16)

        if not read_tail:
            return True, "ok"

        time.sleep(0.35)
        tail = ser.read(8192).decode("ascii", errors="replace").strip()
        return True, tail or "ok"
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            if ser is not None:
                ser.close()
        except Exception:
            pass


class PlotterApp:
    def __init__(self):
        apply_quality_profile(DEFAULT_QUALITY_PROFILE)
        try:
            apply_pencil_profile(load_pencil_profile())
        except Exception:
            pass

        self.root = tk.Tk()
        self.root.title("Plotter Studio")
        self.root.geometry("1200x760")
        self.root.minsize(1040, 640)
        self.root.option_add("*Font", "{Segoe UI} 10")

        self.theme = {
            "bg": "#181a1f",
            "panel": "#23262f",
            "panel_alt": "#1f222a",
            "text": "#e5e7eb",
            "muted_text": "#9ca3af",
            "disabled_text": "#6b7280",
            "input_bg": "#111827",
            "button_bg": "#2a2f3a",
            "button_active": "#343a46",
            "border": "#353b48",
            "accent": "#3b82f6",
            "accent_hover": "#2563eb",
            "danger": "#ef4444",
            "danger_hover": "#dc2626",
            "success": "#059669",
            "success_hover": "#047857",
            "log_bg": "#0f1117",
            "banner_ok_bg": "#0f3d33",
            "banner_ok_fg": "#d1fae5",
            "banner_alert_bg": "#612020",
            "banner_alert_fg": "#ffffff",
            "chip_bg": "#111827",
            "chip_fg": "#cbd5e1",
        }
        self.root.configure(bg=self.theme["bg"])

        self.queue: Queue[str] = Queue()
        self.busy = False
        self.selected_input: Optional[Path] = None
        self._unread_logs = 0
        self.console_visible = False

        self.com_var = tk.StringVar(value=detect_com_port())
        self.file_var = tk.StringVar(value="")
        self.sheet_var = tk.StringVar(value="a4")
        self.tool_var = tk.StringVar(value="pencil")
        self.calibrate_before_draw_var = tk.BooleanVar(value=True)
        self.notebook_w_var = tk.StringVar(value=f"{DEFAULT_NOTEBOOK_WIDTH_MM:.1f}")
        self.notebook_h_var = tk.StringVar(value=f"{DEFAULT_NOTEBOOK_HEIGHT_MM:.1f}")
        self.z_step_var = tk.StringVar(value="5.0")
        self.z_feed_var = tk.StringVar(value="140")

        self._build_ui()

        self._controls = [
            self.refresh_com_btn,
            self.sharpen_btn,
            self.calibrate_btn,
            self.frame_btn,
            self.pick_btn,
            self.draw_btn,
            self.wear_test_btn,
            self.pen_down_btn,
            self.pen_up_btn,
            self.release_btn,
            self.com_entry,
            self.file_entry,
            self.notebook_w_entry,
            self.notebook_h_entry,
            self.z_step_entry,
            self.z_feed_entry,
            self.calibrate_check,
            self.tool_menu,
            self.sheet_menu,
            self.console_toggle_btn,
        ]

        self._add_log("Готово. Выберите файл и нажмите 'Нарисовать'.")
        self._add_log(f"Drawing profile: {quality_state()}")
        self._refresh_pencil_banner()
        self._set_console_visible(False)
        self.root.after(100, self._flush_log)

    def _style_label(self, label: tk.Label, *, muted: bool = False, panel: Optional[str] = None):
        label.config(
            bg=panel or self.theme["panel"],
            fg=self.theme["muted_text"] if muted else self.theme["text"],
        )

    def _style_entry(self, entry: tk.Entry):
        entry.config(
            bg=self.theme["input_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["accent"],
            disabledbackground=self.theme["input_bg"],
            disabledforeground=self.theme["disabled_text"],
        )

    def _style_button(self, button: tk.Button, *, accent: bool = False, danger: bool = False, success: bool = False):
        bg = self.theme["button_bg"]
        active = self.theme["button_active"]
        fg = self.theme["text"]
        if accent:
            bg = self.theme["accent"]
            active = self.theme["accent_hover"]
            fg = "#ffffff"
        elif danger:
            bg = self.theme["danger"]
            active = self.theme["danger_hover"]
            fg = "#ffffff"
        elif success:
            bg = self.theme["success"]
            active = self.theme["success_hover"]
            fg = "#ffffff"
        button.config(
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["accent"],
            disabledforeground=self.theme["disabled_text"],
            cursor="hand2",
        )

    def _style_option_menu(self, option_menu: tk.OptionMenu):
        option_menu.config(
            bg=self.theme["button_bg"],
            fg=self.theme["text"],
            activebackground=self.theme["button_active"],
            activeforeground=self.theme["text"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["accent"],
            disabledforeground=self.theme["disabled_text"],
            cursor="hand2",
        )
        try:
            menu = option_menu.nametowidget(option_menu.menuname)
            menu.config(
                bg=self.theme["panel"],
                fg=self.theme["text"],
                activebackground=self.theme["accent"],
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
            )
        except Exception:
            pass

    def _card(self, parent: tk.Widget, title: str, subtitle: Optional[str] = None) -> tk.Frame:
        card = tk.Frame(
            parent,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["border"],
            padx=12,
            pady=10,
        )
        card.pack(fill="x", pady=(0, 10))
        title_lbl = tk.Label(
            card,
            text=title,
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=("Segoe UI Semibold", 11),
            anchor="w",
        )
        title_lbl.pack(fill="x")
        if subtitle:
            subtitle_lbl = tk.Label(
                card,
                text=subtitle,
                bg=self.theme["panel"],
                fg=self.theme["muted_text"],
                font=("Segoe UI", 9),
                anchor="w",
            )
            subtitle_lbl.pack(fill="x", pady=(2, 8))
        body = tk.Frame(card, bg=self.theme["panel"])
        body.pack(fill="x")
        return body

    def _build_ui(self):
        shell = tk.Frame(self.root, bg=self.theme["bg"], padx=12, pady=12)
        shell.pack(fill="both", expand=True)

        header = tk.Frame(
            shell,
            bg=self.theme["panel_alt"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["border"],
            padx=14,
            pady=10,
        )
        header.pack(fill="x", pady=(0, 12))
        left_head = tk.Frame(header, bg=self.theme["panel_alt"])
        left_head.pack(side="left", fill="x", expand=True)
        tk.Label(
            left_head,
            text="Plotter Studio",
            bg=self.theme["panel_alt"],
            fg=self.theme["text"],
            font=("Segoe UI Semibold", 16),
        ).pack(anchor="w")
        tk.Label(
            left_head,
            text="Минималистичный контроль плоттера: калибровка, подготовка файла и рисование в один поток.",
            bg=self.theme["panel_alt"],
            fg=self.theme["muted_text"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        self.status_chip = tk.Label(
            header,
            text="Готово",
            bg=self.theme["chip_bg"],
            fg=self.theme["chip_fg"],
            font=("Segoe UI Semibold", 10),
            padx=12,
            pady=6,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["border"],
        )
        self.status_chip.pack(side="right")
        self.status = self.status_chip

        content = tk.Frame(shell, bg=self.theme["bg"])
        content.pack(fill="both", expand=True)

        left_col = tk.Frame(content, bg=self.theme["bg"], width=470)
        left_col.pack(side="left", fill="y")
        left_col.pack_propagate(False)

        right_col = tk.Frame(content, bg=self.theme["bg"])
        right_col.pack(side="left", fill="both", expand=True, padx=(12, 0))

        conn_body = self._card(left_col, "Подключение", "Порт, инструмент и текущее состояние.")
        conn_row = tk.Frame(conn_body, bg=self.theme["panel"])
        conn_row.pack(fill="x")
        tk.Label(conn_row, text="COM", bg=self.theme["panel"], fg=self.theme["muted_text"]).pack(side="left")
        self.com_entry = tk.Entry(conn_row, textvariable=self.com_var, width=10)
        self.com_entry.pack(side="left", padx=(6, 6))
        self.refresh_com_btn = tk.Button(conn_row, text="Обновить", command=self._refresh_com)
        self.refresh_com_btn.pack(side="left", padx=(0, 8))
        tk.Label(conn_row, text="Инструмент", bg=self.theme["panel"], fg=self.theme["muted_text"]).pack(side="left", padx=(4, 6))
        self.tool_menu = tk.OptionMenu(conn_row, self.tool_var, "pen", "pencil")
        self.tool_menu.pack(side="left")

        work_body = self._card(left_col, "Рабочая область", "Формат листа и калибровка.")
        work_row0 = tk.Frame(work_body, bg=self.theme["panel"])
        work_row0.pack(fill="x")
        tk.Label(work_row0, text="Формат", bg=self.theme["panel"], fg=self.theme["muted_text"]).pack(side="left")
        self.sheet_menu = tk.OptionMenu(work_row0, self.sheet_var, "work", "a4", "a3", "notebook")
        self.sheet_menu.pack(side="left", padx=(6, 12))
        tk.Label(work_row0, text="W", bg=self.theme["panel"], fg=self.theme["muted_text"]).pack(side="left")
        self.notebook_w_entry = tk.Entry(work_row0, textvariable=self.notebook_w_var, width=7)
        self.notebook_w_entry.pack(side="left", padx=(4, 8))
        tk.Label(work_row0, text="H", bg=self.theme["panel"], fg=self.theme["muted_text"]).pack(side="left")
        self.notebook_h_entry = tk.Entry(work_row0, textvariable=self.notebook_h_var, width=7)
        self.notebook_h_entry.pack(side="left", padx=(4, 0))

        self.calibrate_check = tk.Checkbutton(
            work_body,
            text="Выполнить калибровку перед рисованием",
            variable=self.calibrate_before_draw_var,
            onvalue=True,
            offvalue=False,
            bg=self.theme["panel"],
            fg=self.theme["text"],
            activebackground=self.theme["panel"],
            activeforeground=self.theme["text"],
            selectcolor=self.theme["input_bg"],
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.calibrate_check.pack(fill="x", pady=(10, 8))
        work_row1 = tk.Frame(work_body, bg=self.theme["panel"])
        work_row1.pack(fill="x")
        self.calibrate_btn = tk.Button(work_row1, text="Калибровка 4 угла", command=self._run_corner_calibration)
        self.calibrate_btn.pack(side="left")
        self.frame_btn = tk.Button(work_row1, text="Рамка активной зоны", command=self._draw_area_frame)
        self.frame_btn.pack(side="left", padx=(8, 0))

        file_body = self._card(left_col, "Файл", "Выбери файл, подготовь траекторию и отправь на плоттер.")
        self.file_entry = tk.Entry(file_body, textvariable=self.file_var)
        self.file_entry.pack(fill="x")
        file_row = tk.Frame(file_body, bg=self.theme["panel"])
        file_row.pack(fill="x", pady=(10, 0))
        self.pick_btn = tk.Button(file_row, text="Выбрать файл", command=self._pick_file)
        self.pick_btn.pack(side="left")
        self.draw_btn = tk.Button(file_row, text="Нарисовать", command=self._draw_selected)
        self.draw_btn.pack(side="left", padx=(8, 0))
        self.wear_test_btn = tk.Button(file_row, text="Тест износа", command=self._run_wear_test)
        self.wear_test_btn.pack(side="left", padx=(8, 0))

        pen_body = self._card(left_col, "Перо и моторы", "Ручное управление осью Z и отпуск удержания.")
        pen_row0 = tk.Frame(pen_body, bg=self.theme["panel"])
        pen_row0.pack(fill="x")
        tk.Label(pen_row0, text="Шаг Z (мм)", bg=self.theme["panel"], fg=self.theme["muted_text"]).pack(side="left")
        self.z_step_entry = tk.Entry(pen_row0, textvariable=self.z_step_var, width=7)
        self.z_step_entry.pack(side="left", padx=(6, 10))
        tk.Label(pen_row0, text="Feed Z", bg=self.theme["panel"], fg=self.theme["muted_text"]).pack(side="left")
        self.z_feed_entry = tk.Entry(pen_row0, textvariable=self.z_feed_var, width=7)
        self.z_feed_entry.pack(side="left", padx=(6, 0))
        pen_row1 = tk.Frame(pen_body, bg=self.theme["panel"])
        pen_row1.pack(fill="x", pady=(10, 0))
        self.pen_down_btn = tk.Button(pen_row1, text="Опустить перо", command=lambda: self._manual_pen_step(True))
        self.pen_down_btn.pack(side="left")
        self.pen_up_btn = tk.Button(pen_row1, text="Поднять перо", command=lambda: self._manual_pen_step(False))
        self.pen_up_btn.pack(side="left", padx=(8, 0))
        self.release_btn = tk.Button(pen_row1, text="Отпустить моторы", command=self._release_motors)
        self.release_btn.pack(side="left", padx=(8, 0))

        pencil_body = self._card(left_col, "Карандаш", "Контроль износа и напоминание о заточке.")
        self.sharpen_btn = tk.Button(pencil_body, text="Заточил карандаш", command=self._mark_sharpened)
        self.sharpen_btn.pack(side="left")
        self.sharpen_banner = tk.Label(
            pencil_body,
            text="ЗАТОЧИ КАРАНДАШ",
            font=("Segoe UI Semibold", 11),
            anchor="center",
            pady=6,
            padx=12,
        )
        self.sharpen_banner.pack(side="left", fill="x", expand=True, padx=(10, 0))

        workflow = self._card(
            right_col,
            "Поток работы",
            "1) Выбери формат и COM -> 2) Калибровка (опционально) -> 3) Файл -> 4) Нарисовать",
        )
        self.workflow_hint = tk.Label(
            workflow,
            text=(
                "Совет: держи консоль свернутой для компактного интерфейса.\n"
                "При ошибке подключения открой консоль и проверь последние сообщения."
            ),
            bg=self.theme["panel"],
            fg=self.theme["muted_text"],
            justify="left",
            anchor="w",
        )
        self.workflow_hint.pack(fill="x")

        console_outer = tk.Frame(
            right_col,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["border"],
            padx=12,
            pady=10,
        )
        console_outer.pack(fill="both", expand=True)
        top_console = tk.Frame(console_outer, bg=self.theme["panel"])
        top_console.pack(fill="x")
        tk.Label(
            top_console,
            text="Console",
            bg=self.theme["panel"],
            fg=self.theme["text"],
            font=("Segoe UI Semibold", 11),
        ).pack(side="left")
        self.console_toggle_btn = tk.Button(top_console, text="▶ Показать лог", command=self._toggle_console)
        self.console_toggle_btn.pack(side="right")

        self.console_body = tk.Frame(console_outer, bg=self.theme["panel"])
        self.log = scrolledtext.ScrolledText(
            self.console_body,
            height=22,
            font=("Consolas", 10),
            wrap="none",
            padx=8,
            pady=8,
        )
        self.log.pack(fill="both", expand=True, pady=(10, 0))

        self._style_entry(self.com_entry)
        self._style_entry(self.notebook_w_entry)
        self._style_entry(self.notebook_h_entry)
        self._style_entry(self.file_entry)
        self._style_entry(self.z_step_entry)
        self._style_entry(self.z_feed_entry)
        self._style_option_menu(self.tool_menu)
        self._style_option_menu(self.sheet_menu)
        self._style_button(self.refresh_com_btn)
        self._style_button(self.calibrate_btn, success=True)
        self._style_button(self.frame_btn)
        self._style_button(self.pick_btn)
        self._style_button(self.draw_btn, accent=True)
        self._style_button(self.wear_test_btn)
        self._style_button(self.pen_down_btn)
        self._style_button(self.pen_up_btn)
        self._style_button(self.release_btn, danger=True)
        self._style_button(self.sharpen_btn, success=True)
        self._style_button(self.console_toggle_btn)
        self.log.config(
            bg=self.theme["log_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["accent"],
        )
        self.sharpen_banner.config(
            bg=self.theme["banner_alert_bg"],
            fg=self.theme["banner_alert_fg"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["border"],
        )

    def _add_log(self, msg: str):
        self.queue.put(msg)

    def _set_console_visible(self, visible: bool):
        self.console_visible = bool(visible)
        if self.console_visible:
            self.console_body.pack(fill="both", expand=True)
            self._unread_logs = 0
        else:
            self.console_body.pack_forget()
        self._update_console_toggle()

    def _update_console_toggle(self):
        arrow = "▼" if self.console_visible else "▶"
        unread = f" ({self._unread_logs})" if (not self.console_visible and self._unread_logs > 0) else ""
        self.console_toggle_btn.config(text=f"{arrow} {'Скрыть лог' if self.console_visible else 'Показать лог'}{unread}")

    def _toggle_console(self):
        self._set_console_visible(not self.console_visible)

    def _flush_log(self):
        has_new = False
        try:
            while True:
                msg = self.queue.get_nowait()
                has_new = True
                if not self.console_visible:
                    self._unread_logs += 1
                self.log.insert("end", f"{msg}\n")
                self.log.see("end")
        except Empty:
            pass
        if has_new and not self.console_visible:
            self._update_console_toggle()
        self.root.after(100, self._flush_log)

    def _set_status(self, msg: str):
        msg_l = (msg or "").lower()
        bg = self.theme["chip_bg"]
        fg = self.theme["chip_fg"]
        if "error" in msg_l or "failed" in msg_l:
            bg = self.theme["danger"]
            fg = "#ffffff"
        elif "готово" in msg_l or "done" in msg_l:
            bg = self.theme["success"]
            fg = "#ffffff"
        elif "..." in msg or "рисование" in msg_l or "калибров" in msg_l:
            bg = self.theme["accent"]
            fg = "#ffffff"
        self.status.config(text=msg, bg=bg, fg=fg)

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for w in self._controls:
            try:
                w.config(state=state)
            except Exception:
                pass

    def _start_background(self, status: str, worker, *args):
        if self.busy:
            return
        self.busy = True
        self._set_controls_enabled(False)
        self._set_status(status)
        threading.Thread(target=worker, args=args, daemon=True).start()

    def _finish(self, ok: bool, msg: Optional[str] = None, *, popup: bool = False):
        self.busy = False
        self._set_controls_enabled(True)
        self._refresh_pencil_banner()
        if msg:
            self._add_log(msg)
            self._set_status(msg)
        else:
            self._set_status("Готово")

        if popup and msg:
            if ok:
                messagebox.showinfo("Done", msg)
            else:
                messagebox.showerror("Error", msg)

    def _current_com(self) -> str:
        val = (self.com_var.get() or "").strip()
        if val:
            return val
        detected = detect_com_port()
        self.com_var.set(detected)
        return detected

    def _refresh_com(self):
        detected = detect_com_port(self._current_com())
        self.com_var.set(detected)
        self._add_log(f"COM detected: {detected}")
        self._set_status(f"COM: {detected}")

    def _pick_file(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            filetypes=[
                ("Supported", "*.pdf *.svg *.frw *.cdw *.doc *.docx"),
                ("PDF", "*.pdf"),
                ("SVG", "*.svg"),
                ("COMPAS FRW", "*.frw"),
                ("COMPAS CDW", "*.cdw"),
                ("Word DOC", "*.doc"),
                ("Word DOCX", "*.docx"),
            ],
            title="Выберите файл для рисования",
        )
        if not path:
            return
        self.selected_input = Path(path)
        self.file_var.set(str(self.selected_input))
        self._add_log(f"Selected file: {self.selected_input}")
        self._set_status("Файл выбран")

    def _parse_float_var(self, var: tk.StringVar, default_value: float) -> float:
        try:
            return float((var.get() or "").replace(",", "."))
        except Exception:
            return float(default_value)

    def _sheet_config_from_ui(self) -> dict:
        fmt = (self.sheet_var.get() or "work").strip().lower()
        if fmt not in {"work", "a4", "a3", "notebook"}:
            fmt = "work"

        width = None
        height = None
        if fmt == "notebook":
            width = max(10.0, self._parse_float_var(self.notebook_w_var, DEFAULT_NOTEBOOK_WIDTH_MM))
            height = max(10.0, self._parse_float_var(self.notebook_h_var, DEFAULT_NOTEBOOK_HEIGHT_MM))

        return {
            "sheet_format": fmt,
            "sheet_width_mm": width,
            "sheet_height_mm": height,
            "anchor": "lower_left",
            "offset_x_mm": 0.0,
            "offset_y_mm": 0.0,
        }

    def _apply_sheet_from_ui(self, logger):
        cfg = self._sheet_config_from_ui()
        configure_active_work_area(
            sheet_format=cfg["sheet_format"],
            sheet_width_mm=cfg["sheet_width_mm"],
            sheet_height_mm=cfg["sheet_height_mm"],
            anchor=cfg["anchor"],
            offset_x_mm=cfg["offset_x_mm"],
            offset_y_mm=cfg["offset_y_mm"],
            logger=logger,
        )

    def _apply_tool_from_ui(self):
        global TOOL_MODE
        tool = (self.tool_var.get() or "pen").strip().lower()
        if tool not in {"pen", "pencil"}:
            tool = "pen"
        TOOL_MODE = tool

    def _refresh_pencil_banner(self):
        try:
            apply_pencil_profile(load_pencil_profile())
            state = load_pencil_state()
            rem_best, rem_wear, rem_interval = pencil_remaining_to_sharpen_m(state)
            wear_now = float(state.get("estimated_wear_mm", 0.0) or 0.0)
            alert = wear_now >= PENCIL_REMIND_WEAR_MM or (math.isfinite(rem_best) and rem_best <= 0.0)
            if alert:
                txt = "ЗАТОЧИ КАРАНДАШ"
                self.sharpen_banner.config(
                    text=txt,
                    fg=self.theme["banner_alert_fg"],
                    bg=self.theme["banner_alert_bg"],
                )
            else:
                rem_txt = "inf" if not math.isfinite(rem_best) else f"{rem_best:.1f} м"
                txt = f"Карандаш OK. До заточки: {rem_txt}"
                self.sharpen_banner.config(
                    text=txt,
                    fg=self.theme["banner_ok_fg"],
                    bg=self.theme["banner_ok_bg"],
                )
            self._add_log(
                "Pencil status: "
                f"wear={wear_now:.3f} mm, remaining={('inf' if not math.isfinite(rem_best) else f'{rem_best:.2f}')}, "
                f"wear_rule={('inf' if not math.isfinite(rem_wear) else f'{rem_wear:.2f}')}, "
                f"interval_rule={('inf' if not math.isfinite(rem_interval) else f'{rem_interval:.2f}')}"
            )
        except Exception as exc:
            self.sharpen_banner.config(
                text="Проверка карандаша недоступна",
                fg="#ffffff",
                bg="#374151",
            )
            self._add_log(f"Pencil banner update failed: {exc}")

    def _mark_sharpened(self):
        if self.busy:
            return
        reset_pencil_state_after_sharpen(self._add_log, reason="gui")
        self._refresh_pencil_banner()
        self._set_status("Карандаш отмечен как заточенный.")

    def _run_corner_calibration(self):
        self._start_background("Калибровка 4 углов...", self._corner_calibration_worker)

    def _corner_calibration_worker(self):
        try:
            self._apply_sheet_from_ui(self._add_log)
            ok, msg = run_corner_calibration_pipeline(
                self._add_log,
                com=self._current_com(),
                baud=DEFAULT_BAUD,
                send_to_plotter=True,
                mark_size=2.0,
            )
        except Exception as exc:
            ok, msg = False, f"Error: {exc}"
        self.root.after(0, lambda: self._finish(ok, msg, popup=False))

    def _draw_area_frame(self):
        self._start_background("Рисование рамки зоны...", self._frame_worker)

    def _frame_worker(self):
        try:
            self._apply_sheet_from_ui(self._add_log)
            ok, msg = run_frame_pipeline(
                self._add_log,
                com=self._current_com(),
                baud=DEFAULT_BAUD,
                send_to_plotter=True,
            )
        except Exception as exc:
            ok, msg = False, f"Error: {exc}"
        self.root.after(0, lambda: self._finish(ok, msg, popup=False))

    def _draw_selected(self):
        if self.busy:
            return
        if self.selected_input is None:
            self._pick_file()
            if self.selected_input is None:
                return
        self._start_background("Подготовка и рисование...", self._draw_worker, self.selected_input)

    def _draw_worker(self, input_path: Path):
        try:
            self._apply_tool_from_ui()
            self._apply_sheet_from_ui(self._add_log)
            ok, msg = run_pipeline_with_corner_calibration(
                input_path,
                self._add_log,
                com=self._current_com(),
                baud=DEFAULT_BAUD,
                send_to_plotter=True,
                output_path=None,
                skip_calibration=not bool(self.calibrate_before_draw_var.get()),
                skip_confirmation=True,
                corner_mark_size=2.0,
                feed_travel=FEED_TRAVEL,
                feed_draw=FEED_DRAW,
                auto_resume=True,
            )
        except Exception as exc:
            ok, msg = False, f"Error: {exc}"
        self.root.after(0, lambda: self._finish(ok, msg, popup=True))

    def _run_wear_test(self):
        self._start_background("Тест износа (квадраты)...", self._wear_test_worker)

    def _wear_test_worker(self):
        try:
            self.tool_var.set("pencil")
            self._apply_tool_from_ui()
            self._apply_sheet_from_ui(self._add_log)
            ok, msg = run_pencil_wear_test_pipeline(
                self._add_log,
                com=self._current_com(),
                baud=DEFAULT_BAUD,
                send_to_plotter=True,
                output_path=None,
                feed_travel=FEED_TRAVEL,
                feed_draw=FEED_DRAW,
                auto_resume=True,
                levels=8,
                cols=2,
                hatch_step_mm=1.0,
                hatch_loops=1,
                margin_mm=8.0,
                gap_mm=6.0,
            )
        except Exception as exc:
            ok, msg = False, f"Error: {exc}"
        self.root.after(0, lambda: self._finish(ok, msg, popup=True))

    def _manual_pen_step(self, down: bool):
        if self.busy:
            return
        step = max(0.1, self._parse_float_var(self.z_step_var, 5.0))
        feed = max(20.0, self._parse_float_var(self.z_feed_var, 140.0))
        down_sign = 1.0 if (float(PENCIL_BASE_Z_DOWN) - float(Z_UP)) >= 0.0 else -1.0
        delta = down_sign * step if down else -down_sign * step
        action = "Опускание пера..." if down else "Подъем пера..."
        done = f"Done: {'перо опущено' if down else 'перо поднято'} на {step:.2f} мм."
        cmds = [
            "$X",
            "$1=255",
            "G21",
            "G91",
            f"G1 Z{delta:.3f} F{feed:.1f}",
            "G90",
            "?",
        ]
        self._start_background(action, self._manual_worker, cmds, done)

    def _release_motors(self):
        if self.busy:
            return
        cmds = ["$X", "M5", "$1=0", "M18", "M84", "?"]
        self._start_background("Отпуск моторов...", self._manual_worker, cmds, "Done: моторы отпущены.")

    def _manual_worker(self, commands: List[str], done_message: str):
        ok, out = grbl_send_manual_commands(
            self._current_com(),
            DEFAULT_BAUD,
            commands,
            soft_reset_first=True,
            read_tail=True,
        )
        if out:
            for line in out.splitlines():
                self._add_log(line)
        msg = done_message if ok else f"Manual command failed: {out}"
        self.root.after(0, lambda: self._finish(ok, msg, popup=not ok))

    def run(self):
        self.root.mainloop()

def main():
    _force_utf8_stdio()
    global MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW
    global TOOL_MODE
    global PENCIL_BASE_Z_DOWN
    global PENCIL_WEAR_MM_PER_M
    global PENCIL_Z_COMP_MM_PER_WEAR_MM
    global PENCIL_MAX_COMP_MM
    global PENCIL_REMIND_WEAR_MM
    global Z_DELAY_DOWN
    global Z_DELAY_UP
    global Z_FEED_DOWN_APPROACH
    global Z_FEED_DOWN_TOUCH
    global Z_FEED_UP
    global Z_FEED_UP_FINAL
    global Z_SOFT_DOWN_MM
    global Z_SOFT_UP_MM
    global Z_TRAVEL_LIFT_MM
    global SAFE_PEN_TRAVEL_UP
    global PASS_COLS
    global PASS_ROWS
    global PASS_COL
    global PASS_ROW

    parser = argparse.ArgumentParser(description="PDF/SVG/FRW/CDW/DOC/DOCX -> Plotter converter")
    parser.add_argument("input", nargs="?", help="Path to PDF, SVG, FRW, CDW, DOC or DOCX file")
    parser.add_argument("--frame", action="store_true", help="Draw work area frame")
    parser.add_argument("--calibrate-corners", action="store_true", help="Draw 4 corner marks for calibration")
    parser.add_argument("--com", default=None, help="COM port (default detect)")
    parser.add_argument("--baud", default=DEFAULT_BAUD, help="Baud rate")
    parser.add_argument("--dry-run", action="store_true", help="Generate G-code and save file without sending to plotter")
    parser.add_argument("--preview", action="store_true", help="Generate G-code and do not send to plotter")
    parser.add_argument("--open-preview", action="store_true", help="Open prepared G-code in default viewer")
    parser.add_argument("--output", default=None, help="Output file when --dry-run is set")
    parser.add_argument("--feed-travel", type=float, default=FEED_TRAVEL, help=f"Feed for rapid moves (default {FEED_TRAVEL})")
    parser.add_argument("--feed-draw", type=float, default=FEED_DRAW, help=f"Feed for drawing moves (default {FEED_DRAW})")
    parser.add_argument("--z-delay-down", type=float, default=None, help=f"Pen-down settle delay seconds (default {Z_DELAY_DOWN})")
    parser.add_argument("--z-delay-up", type=float, default=None, help=f"Pen-up settle delay seconds (default {Z_DELAY_UP})")
    parser.add_argument("--z-feed-down-approach", type=float, default=None, help=f"Z feed for approach before touch (default {Z_FEED_DOWN_APPROACH})")
    parser.add_argument("--z-feed-down-touch", type=float, default=None, help=f"Z feed for final touch-down (default {Z_FEED_DOWN_TOUCH})")
    parser.add_argument("--z-feed-up", type=float, default=None, help=f"Z feed for main lift (default {Z_FEED_UP})")
    parser.add_argument("--z-feed-up-final", type=float, default=None, help=f"Z feed for final near-top lift (default {Z_FEED_UP_FINAL})")
    parser.add_argument("--z-soft-down-mm", type=float, default=None, help=f"Slow final distance before Z-down (default {Z_SOFT_DOWN_MM})")
    parser.add_argument("--z-soft-up-mm", type=float, default=None, help=f"Slow final distance before Z-up (default {Z_SOFT_UP_MM})")
    parser.add_argument(
        "--z-travel-lift-mm",
        type=float,
        default=None,
        help=f"Inter-path lift distance from Z-down towards Z-up (default {Z_TRAVEL_LIFT_MM})",
    )
    parser.add_argument(
        "--safe-travel-up",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Always lift to full Z_UP before every G0 travel move (recommended for clean technical drawings).",
    )
    parser.add_argument("--skip-calibration", action="store_true", help="Skip 4-corner calibration before drawing")
    parser.add_argument("--skip-calibration-confirmation", action="store_true", help="Do not ask confirmation after calibration")
    parser.add_argument(
        "--auto-resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-resume from current position if the sender aborts (best effort).",
    )
    parser.add_argument("--corner-mark-size", type=float, default=2.0, help="Corner mark size in mm")
    parser.add_argument(
        "--quality",
        default=DEFAULT_QUALITY_PROFILE,
        choices=["fast", "normal", "high"],
        help="Geometry quality profile: fast/normal/high",
    )
    parser.add_argument("--curve-segment-mm", type=float, default=None, help="Override curve approximation step size")
    parser.add_argument("--arc-segment-mm", type=float, default=None, help="Override arc approximation step size")
    parser.add_argument("--collinear-eps", type=float, default=None, help="Override collinear simplification epsilon")
    parser.add_argument("--rdp-eps", type=float, default=None, help="RDP simplify epsilon (mm) for G1-only polylines (0 disables)")
    parser.add_argument("--arc-fit-tol", type=float, default=None, help="Max radial error (mm) to replace polyline by G2/G3 arc")
    parser.add_argument("--line-fit-tol", type=float, default=None, help="Max deviation (mm) to replace polyline by a single line")
    parser.add_argument("--no-simplify", action="store_true", help="Disable polyline simplification")
    parser.add_argument("--no-rdp", action="store_true", help="Disable RDP polyline simplification (keep raw segments)")
    parser.add_argument("--no-arcs", action="store_true", help="Disable emitting G2/G3 arcs (use only G1)")
    parser.add_argument(
        "--strict-1to1",
        action="store_true",
        help=(
            "Preserve 1:1 mm dimensions when fit-to-area would shrink geometry too much. "
            "May clip geometry that does not fit the configured work area."
        ),
    )
    parser.add_argument(
        "--sheet-format",
        default="work",
        choices=["work", "a4", "a3", "notebook", "custom"],
        help="Active sheet profile inside workspace.",
    )
    parser.add_argument("--sheet-width-mm", type=float, default=None, help="Sheet width override (mm).")
    parser.add_argument("--sheet-height-mm", type=float, default=None, help="Sheet height override (mm).")
    parser.add_argument(
        "--sheet-anchor",
        default="center",
        choices=["center", "lower_left", "upper_left", "lower_right", "upper_right"],
        help="How to place smaller sheet area inside machine workspace.",
    )
    parser.add_argument("--sheet-offset-x-mm", type=float, default=0.0, help="Shift active sheet area in X (mm).")
    parser.add_argument("--sheet-offset-y-mm", type=float, default=0.0, help="Shift active sheet area in Y (mm).")
    parser.add_argument("--plan-sheet", action="store_true", help="Print pass plan for selected sheet and continue.")
    parser.add_argument("--pass-cols", type=int, default=1, help="How many passes along X for current sheet.")
    parser.add_argument("--pass-rows", type=int, default=1, help="How many passes along Y for current sheet.")
    parser.add_argument("--pass-col", type=int, default=1, help="Current pass column index (1-based).")
    parser.add_argument("--pass-row", type=int, default=1, help="Current pass row index (1-based).")
    parser.add_argument("--auto-pass-grid", action="store_true", help="Auto-select pass grid from sheet size and active area.")
    parser.add_argument("--tool", default="pen", choices=["pen", "pencil"], help="Drawing tool mode.")
    parser.add_argument("--pencil-base-z-down", type=float, default=None, help="Base Z_DOWN for pencil mode.")
    parser.add_argument("--pencil-wear-mm-per-m", type=float, default=None, help="Estimated HB wear (mm per 1 meter draw).")
    parser.add_argument("--pencil-z-comp-per-wear", type=float, default=None, help="Extra Z mm per 1 mm estimated wear.")
    parser.add_argument("--pencil-max-comp-mm", type=float, default=None, help="Max automatic Z compensation for pencil wear.")
    parser.add_argument("--pencil-remind-wear-mm", type=float, default=None, help="Wear threshold for sharpen reminder.")
    parser.add_argument("--pencil-sharpen-interval-m", type=float, default=None, help="Length-based sharpen interval in meters (0 disables).")
    parser.add_argument("--pencil-sharpened", action="store_true", help="Reset accumulated pencil wear state.")
    parser.add_argument("--pencil-status", action="store_true", help="Print current pencil profile/state and exit.")
    parser.add_argument(
        "--pencil-calibrate-from-last-test-stage",
        type=int,
        default=None,
        help="Use last wear-test report and stage number (last acceptable block) to auto-tune wear rate/sharpen interval.",
    )
    parser.add_argument(
        "--pencil-calibrate-first-bad-stage",
        type=int,
        default=0,
        help="Optional first unacceptable stage for auto calibration.",
    )
    parser.add_argument(
        "--pencil-calibrate-safety-factor",
        type=float,
        default=0.90,
        help="Safety factor for derived sharpen interval from calibration stage (0.5..0.99).",
    )
    parser.add_argument("--pencil-wear-test", action="store_true", help="Draw dense hatched test blocks to calibrate pencil wear.")
    parser.add_argument("--pencil-wear-test-levels", type=int, default=8, help="Number of wear-test blocks.")
    parser.add_argument("--pencil-wear-test-cols", type=int, default=2, help="How many block columns for wear-test.")
    parser.add_argument("--pencil-wear-test-hatch-step-mm", type=float, default=1.0, help="Wear-test hatch spacing (mm).")
    parser.add_argument("--pencil-wear-test-loops", type=int, default=1, help="Cross-hatch loop count per wear-test block.")
    parser.add_argument("--pencil-wear-test-margin-mm", type=float, default=8.0, help="Wear-test margin from active area borders (mm).")
    parser.add_argument("--pencil-wear-test-gap-mm", type=float, default=6.0, help="Wear-test gap between blocks (mm).")
    parser.add_argument(
        "--force-text-to-path",
        action="store_true",
        default=None,
        help="Always convert text nodes to paths (stronger glyph output)",
    )
    args = parser.parse_args()
    if args.no_rdp:
        args.rdp_eps = 0.0
    if args.feed_travel <= 0 or args.feed_draw <= 0:
        print("Invalid feed: --feed-travel and --feed-draw must be > 0")
        return 1
    # Load persistent pencil profile first, then allow CLI overrides below.
    profile_from_file = load_pencil_profile()
    apply_pencil_profile(profile_from_file)
    MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.98 if args.strict_1to1 else 0.0
    TOOL_MODE = (args.tool or "pen").strip().lower()
    PASS_COLS = max(1, int(args.pass_cols))
    PASS_ROWS = max(1, int(args.pass_rows))
    PASS_COL = min(max(1, int(args.pass_col)), PASS_COLS)
    PASS_ROW = min(max(1, int(args.pass_row)), PASS_ROWS)

    if args.pencil_base_z_down is not None:
        PENCIL_BASE_Z_DOWN = float(args.pencil_base_z_down)
    if args.pencil_wear_mm_per_m is not None:
        PENCIL_WEAR_MM_PER_M = max(0.0, float(args.pencil_wear_mm_per_m))
    if args.pencil_z_comp_per_wear is not None:
        PENCIL_Z_COMP_MM_PER_WEAR_MM = max(0.0, float(args.pencil_z_comp_per_wear))
    if args.pencil_max_comp_mm is not None:
        PENCIL_MAX_COMP_MM = max(0.0, float(args.pencil_max_comp_mm))
    if args.pencil_remind_wear_mm is not None:
        PENCIL_REMIND_WEAR_MM = max(0.0, float(args.pencil_remind_wear_mm))
    if args.pencil_sharpen_interval_m is not None:
        PENCIL_SHARPEN_INTERVAL_M = max(0.0, float(args.pencil_sharpen_interval_m))

    if args.z_delay_down is not None:
        Z_DELAY_DOWN = max(0.0, float(args.z_delay_down))
    if args.z_delay_up is not None:
        Z_DELAY_UP = max(0.0, float(args.z_delay_up))
    if args.z_feed_down_approach is not None:
        Z_FEED_DOWN_APPROACH = max(1.0, float(args.z_feed_down_approach))
    if args.z_feed_down_touch is not None:
        Z_FEED_DOWN_TOUCH = max(1.0, float(args.z_feed_down_touch))
    if args.z_feed_up is not None:
        Z_FEED_UP = max(1.0, float(args.z_feed_up))
    if args.z_feed_up_final is not None:
        Z_FEED_UP_FINAL = max(1.0, float(args.z_feed_up_final))
    if args.z_soft_down_mm is not None:
        Z_SOFT_DOWN_MM = max(0.0, float(args.z_soft_down_mm))
    if args.z_soft_up_mm is not None:
        Z_SOFT_UP_MM = max(0.0, float(args.z_soft_up_mm))
    if args.z_travel_lift_mm is not None:
        Z_TRAVEL_LIFT_MM = max(0.0, float(args.z_travel_lift_mm))
    if args.safe_travel_up is not None:
        SAFE_PEN_TRAVEL_UP = bool(args.safe_travel_up)

    pencil_profile_overrides = any(
        v is not None
        for v in (
            args.pencil_base_z_down,
            args.pencil_wear_mm_per_m,
            args.pencil_z_comp_per_wear,
            args.pencil_max_comp_mm,
            args.pencil_remind_wear_mm,
            args.pencil_sharpen_interval_m,
        )
    )
    if pencil_profile_overrides:
        profile_to_save = load_pencil_profile()
        profile_to_save.update(build_pencil_profile_snapshot())
        profile_to_save["updated_at_utc"] = _now_iso_utc()
        profile_to_save["source"] = "cli_override"
        save_pencil_profile(profile_to_save)
        print(f"Pencil profile saved: {PENCIL_PROFILE_PATH}")

    did_pencil_command = False
    if args.pencil_sharpened:
        reset_pencil_state_after_sharpen(print, reason="cli")
        did_pencil_command = True

    if args.pencil_calibrate_from_last_test_stage is not None:
        ok, msg = calibrate_pencil_wear_from_last_test(
            last_good_stage=int(args.pencil_calibrate_from_last_test_stage),
            first_bad_stage=max(0, int(args.pencil_calibrate_first_bad_stage or 0)),
            safety_factor=float(args.pencil_calibrate_safety_factor),
            logger=lambda _msg: None,
        )
        print(msg)
        if not ok:
            return 1
        did_pencil_command = True

    if args.pencil_status:
        show_pencil_status(print)
        did_pencil_command = True

    if (
        did_pencil_command
        and not args.frame
        and not args.calibrate_corners
        and not args.pencil_wear_test
        and not args.input
        and not args.plan_sheet
    ):
        return 0

    try:
        configure_active_work_area(
            sheet_format=args.sheet_format,
            sheet_width_mm=args.sheet_width_mm,
            sheet_height_mm=args.sheet_height_mm,
            anchor=args.sheet_anchor,
            offset_x_mm=args.sheet_offset_x_mm,
            offset_y_mm=args.sheet_offset_y_mm,
            logger=print,
        )
    except ValueError as exc:
        print(f"Invalid sheet configuration: {exc}")
        return 1

    try:
        sheet_w_mm, sheet_h_mm = resolve_sheet_size_mm(
            sheet_format=args.sheet_format,
            sheet_width_mm=args.sheet_width_mm,
            sheet_height_mm=args.sheet_height_mm,
        )
    except ValueError as exc:
        print(f"Invalid sheet size: {exc}")
        return 1

    if args.auto_pass_grid:
        plan_auto = plan_tiled_passes_for_sheet(sheet_w_mm, sheet_h_mm)
        PASS_COLS = max(1, int(plan_auto["nx"]))
        PASS_ROWS = max(1, int(plan_auto["ny"]))
        PASS_COL = min(max(1, int(args.pass_col)), PASS_COLS)
        PASS_ROW = min(max(1, int(args.pass_row)), PASS_ROWS)
        print(
            f"Auto pass grid: {PASS_COLS} x {PASS_ROWS} "
            f"(current pass col={PASS_COL}, row={PASS_ROW}, rotated={'yes' if plan_auto['rotated'] else 'no'})"
        )
    elif PASS_COL != int(args.pass_col) or PASS_ROW != int(args.pass_row):
        print(
            f"Pass index clamped to available grid: "
            f"col={PASS_COL}/{PASS_COLS}, row={PASS_ROW}/{PASS_ROWS}"
        )

    if args.plan_sheet:
        plan = plan_tiled_passes_for_sheet(sheet_w_mm, sheet_h_mm)
        min_x, max_x, min_y, max_y = work_area_bounds()
        print(
            f"Sheet plan ({args.sheet_format}): {sheet_w_mm:.1f} x {sheet_h_mm:.1f} mm, "
            f"active bounds x({min_x:.3f},{max_x:.3f}) y({min_y:.3f},{max_y:.3f})"
        )
        print(
            f"1:1 pass grid needed: {plan['nx']} x {plan['ny']} = {plan['passes']} "
            f"(rotated={'yes' if plan['rotated'] else 'no'})"
        )
        if int(plan["passes"]) > 2:
            print(
                "Two-pass 1:1 is impossible for this sheet on current area. "
                f"Max two-pass scale ~= {float(plan['max_two_pass_scale']):.3f}."
            )
        print(f"Current selected pass: col={PASS_COL}/{PASS_COLS}, row={PASS_ROW}/{PASS_ROWS}")

    com = detect_com_port(args.com)
    try:
        apply_quality_profile(
            quality=args.quality,
            curve_segment_mm=args.curve_segment_mm,
            arc_segment_mm=args.arc_segment_mm,
            collinear_eps=args.collinear_eps,
            rdp_simplify_eps_mm=args.rdp_eps,
            arc_fit_tol_mm=args.arc_fit_tol,
            line_fit_tol_mm=args.line_fit_tol,
            disable_simplify=args.no_simplify,
            disable_arcs=args.no_arcs,
            force_text_to_path=args.force_text_to_path,
        )
    except ValueError as exc:
        print(f"Invalid quality configuration: {exc}")
        return 1
    print(f"Drawing profile: {quality_state()}")
    if args.plan_sheet and not args.frame and not args.calibrate_corners and not args.pencil_wear_test and not args.input:
        return 0

    if args.frame:
        ok, msg = run_frame_pipeline(
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=Path(args.output) if args.output else None,
        )
        print(msg)
        return 0 if ok else 1

    if args.calibrate_corners:
        ok, msg = run_corner_calibration_pipeline(
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=Path(args.output) if args.output else None,
            mark_size=args.corner_mark_size,
        )
        print(msg)
        return 0 if ok else 1

    if args.pencil_wear_test:
        ok, msg = run_pencil_wear_test_pipeline(
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=not args.dry_run,
            output_path=Path(args.output) if args.output else None,
            feed_travel=args.feed_travel,
            feed_draw=args.feed_draw,
            auto_resume=bool(args.auto_resume),
            levels=args.pencil_wear_test_levels,
            cols=args.pencil_wear_test_cols,
            hatch_step_mm=args.pencil_wear_test_hatch_step_mm,
            hatch_loops=args.pencil_wear_test_loops,
            margin_mm=args.pencil_wear_test_margin_mm,
            gap_mm=args.pencil_wear_test_gap_mm,
        )
        print(msg)
        return 0 if ok else 1

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Input not found: {input_path}")
            return 2
        if input_path.suffix.lower() not in {".pdf", ".svg", ".frw", ".cdw", ".doc", ".docx"}:
            print(f"Unsupported file type: {input_path.suffix}. Use .pdf, .svg, .frw, .cdw, .doc or .docx.")
            return 3

        send_to_plotter = not (args.dry_run or args.preview)
        output_target = Path(args.output) if args.output else None
        ok, msg = run_pipeline_with_corner_calibration(
            input_path,
            print,
            com=com,
            baud=args.baud,
            send_to_plotter=send_to_plotter,
            output_path=output_target,
            skip_calibration=args.skip_calibration,
            skip_confirmation=args.skip_calibration_confirmation or args.dry_run or args.preview,
            corner_mark_size=args.corner_mark_size,
            feed_travel=args.feed_travel,
            feed_draw=args.feed_draw,
            auto_resume=bool(args.auto_resume),
        )
        if ok and args.preview:
            output_guess = output_target or input_path.with_name(f"{input_path.stem}_prepared.nc")
            trim_guess = output_target.with_suffix(".svg") if output_target is not None else output_guess.with_name(f"{input_path.stem}_trimmed.svg")
            if output_guess.exists():
                if args.open_preview:
                    open_with_default_viewer(output_guess)
                print(f"Preview ready: {output_guess}")
            if trim_guess.exists():
                if args.open_preview:
                    open_with_default_viewer(trim_guess)
                print(f"Trim preview ready: {trim_guess}")
        print(msg)
        return 0 if ok else 1

    app = PlotterApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


