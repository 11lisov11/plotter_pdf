#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import importlib.util
import argparse
import tempfile
import threading
import time
import os
import base64
import ctypes
import unicodedata
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
try:
    from HersheyFonts import HersheyFonts  # type: ignore
except Exception:
    HersheyFonts = None
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps  # type: ignore
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageOps = None

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

CYRILLIC_TEXT_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F]")


def _force_utf8_stdio() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _strip_unpaired_surrogates(text: str, replacement: str = " ") -> str:
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


def _safe_log_text(value: object) -> str:
    try:
        text = _strip_unpaired_surrogates(str(value), replacement="?")
    except Exception:
        text = "<log-format-error>"
    try:
        # Keep printable UTF-8, escape any remaining problematic chars.
        return text.encode("utf-8", errors="backslashreplace").decode("utf-8", errors="replace")
    except Exception:
        try:
            return text.encode("ascii", errors="backslashreplace").decode("ascii", errors="replace")
        except Exception:
            return "<log-encode-error>"


def _safe_logger(logger):
    if not callable(logger):
        return lambda _msg: None

    def _emit(msg: object) -> None:
        text = _safe_log_text(msg)
        try:
            logger(text)
        except Exception:
            # Logging should never break conversion logic.
            pass

    return _emit


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
AXIS_PROFILE_PATH = CONFIG_DIR / "axis_profile.json"
LOCAL_TMP_ROOT = ROOT_DIR / "_tmp"

DEFAULT_COM_PORT = "COM5"
DEFAULT_BAUD = "115200"
Z_UP = 0.0
Z_DOWN = 11.9
# Legacy-safe defaults (used by pencil / technical drawing unless overridden).
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
# Fast profile for pen handwriting mode (ballpoint): minimizes idle pauses on Z.
PEN_FAST_Z_PROFILE_ENABLED = True
PEN_FAST_Z_DELAY_DOWN = 0.00
PEN_FAST_Z_DELAY_UP = 0.00
PEN_FAST_Z_FEED_DOWN_APPROACH = 8000.0
PEN_FAST_Z_FEED_DOWN_TOUCH = 8000.0
PEN_FAST_Z_FEED_UP = 8000.0
PEN_FAST_Z_FEED_UP_FINAL = 8000.0
PEN_FAST_Z_SOFT_DOWN_MM = 0.0
PEN_FAST_Z_SOFT_UP_MM = 0.0
# Be explicit: if user passes Z params via CLI, do not force pen-fast profile.
Z_PROFILE_CLI_OVERRIDE = False
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
DRAW_ORDER_MODE = "auto"  # auto | nearest | source | line_lr
DRAW_ORDER_LINE_TOL_MM = 3.0
CONTINUOUS_JOIN_EPS = 0.08
# Handwriting mode needs softer continuity constraints to avoid excessive pen lifts
# inside words built from fragmented vector contours.
HANDWRITING_STITCH_EPS_MM = 0.22
HANDWRITING_STITCH_GAP_EPS_MM = 0.38
HANDWRITING_STITCH_GAP_MAX_ANGLE_DEG = 40.0
HANDWRITING_CONTINUOUS_JOIN_EPS = 0.30
HANDWRITING_MERGE_SHORT_TRAVEL_ENABLE = True
HANDWRITING_MERGE_SHORT_TRAVEL_MM = 2.60
HANDWRITING_MERGE_SHORT_TRAVEL_FEED = 5000.0
# Keep neighboring handwriting strokes (letters inside one word) in a single pen-down path.
HANDWRITING_WORD_JOIN_ENABLE = True
HANDWRITING_WORD_JOIN_GAP_MM = 2.20
HANDWRITING_WORD_JOIN_MAX_DY_MM = 1.20
HANDWRITING_PRESERVE_FILL_OUTLINES = False
# For text readability on plotter, never fallback to contour-outline for handwriting glyph groups.
HANDWRITING_FORCE_SINGLE_STROKE_TEXT = True
# Experimental: convert stroke-only outline glyph groups to centerline.
# Disabled by default because some PDFs become fragmented/unreadable.
HANDWRITING_OUTLINE_CENTERLINE_ENABLED = False
# Extra handwriting smoothing (applied after stitch/reorder/join).
HANDWRITING_SMOOTH_ENABLED = True
HANDWRITING_SMOOTH_RESAMPLE_MM = 0.22
HANDWRITING_SMOOTH_PASSES = 2
HANDWRITING_SMOOTH_MIN_LEN_MM = 0.8
HANDWRITING_SMOOTH_MAX_LEN_MM = 180.0
HANDWRITING_SMOOTH_SKIP_NEAR_LINE_TOL_MM = 0.020
HANDWRITING_SMOOTH_RDP_EPS_MM = 0.008
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
BACKGROUND_FILL_MIN_CHANNEL = 0.92
BACKGROUND_FILL_MIN_OPACITY = 0.05
FIT_TO_WORK_AREA = True
ALLOW_UPSCALE_TO_WORK_AREA = True
WORK_AREA_EPS = 1e-6
# If fit-to-area would shrink geometry more than this threshold,
# keep 1:1 mm scale and clip to work area instead of distorting dimensions.
# 0 disables strict 1:1 guard (default behavior: always fit to work area).
MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.0
# G-code preflight (guard before send/save).
PREFLIGHT_ENABLED = True
PREFLIGHT_MAX_GCODE_LINES = 650000
PREFLIGHT_MAX_TRAVEL_TO_DRAW_RATIO = 3.5
PREFLIGHT_BOUNDS_MARGIN_MM = 0.25
FORCE_TEXT_TO_PATH = False
HANDWRITING_TEXT_ENABLED = False
HANDWRITING_FONT_FAMILY = "Marck Script"
HANDWRITING_CYRILLIC_FONT_FAMILY = "Marck Script"
# Cyrillic handwriting prefers centerline TTF backend by default.
HANDWRITING_CYRILLIC_PREFER_TTF = True
HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED = True
HANDWRITING_STROKE_FONT_ENABLED = True
HANDWRITING_STROKE_FONT_NAME = "cursive"
HANDWRITING_STROKE_CYR_FONT_NAME = "cyrilc_1"
HANDWRITING_STROKE_SCALE_Y = 0.58
# Prefer SVG stroke-fonts (single-line glyph paths) when available.
# This avoids contour-outline artifacts and keeps text as plotter-friendly vectors.
HANDWRITING_STROKE_SVG_FONT_ENABLED = True
# Default to a cleaner single-stroke font to keep small text readable on plotter.
HANDWRITING_STROKE_SVG_PRIMARY = "Hershey-Sans 1-stroke-smoothed"
HANDWRITING_STROKE_SVG_CYR = "Hershey-Cyrillic"
HANDWRITING_STROKE_SVG_FALLBACKS = (
    "Hershey-Sans 1-stroke",
    "Hershey-Script 1-stroke",
)
# Prefer native Hershey stroke generation first, use SVG stroke-fonts only as fallback.
HANDWRITING_HERSHEY_CORE_FIRST = True
# Contour averaging for Hershey output: fewer tiny segments and smoother transitions.
HANDWRITING_HERSHEY_POSTPROCESS_ENABLED = True
HANDWRITING_HERSHEY_STITCH_EPS_MM = 0.18
HANDWRITING_HERSHEY_STITCH_GAP_MM = 1.08
HANDWRITING_HERSHEY_STITCH_ANGLE_DEG = 70.0
HANDWRITING_HERSHEY_JOIN_GAP_MM = 1.12
HANDWRITING_HERSHEY_JOIN_DY_MM = 0.76
HANDWRITING_HERSHEY_SMOOTH_RESAMPLE_MM = 0.14
HANDWRITING_HERSHEY_SMOOTH_PASSES = 2
HANDWRITING_HERSHEY_SMOOTH_RDP_MM = 0.014
HANDWRITING_HERSHEY_COLLINEAR_EPS_MM = 0.020
# Collinear simplification cap for handwriting/direct-stroke mode.
# Larger values collapse bezier glyphs into almost straight "scribble" segments.
HANDWRITING_COLLINEAR_EPS_MAX = 0.0015
# Keep optional TTF centerline conversion strictly as last-resort debug fallback.
HANDWRITING_ALLOW_TTF_FALLBACK = True
HANDWRITING_STROKE_ACTIVE = False
# Runtime flag for current job: Cyrillic text detected in handwriting mode.
# For Cyrillic we prefer readability over aggressive one-stroke centerline fallback.
HANDWRITING_CYRILLIC_ACTIVE = False
HANDWRITING_SINGLELINE_TTF_ENABLED = True
# Centerline backend:
# - skeleton: in-project thinning/skeletonization
# - autotrace3: "method 3" from centerline-trace (autotrace --centerline + threshold sweep)
# - auto: autotrace3 if available, otherwise skeleton
HANDWRITING_SINGLELINE_TTF_BACKEND = "autotrace3"
HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CANDIDATES = 7
HANDWRITING_SINGLELINE_TTF_AUTOTRACE_ERROR_THRESHOLD = 2.0
HANDWRITING_SINGLELINE_TTF_AUTOTRACE_FILTER_ITERATIONS = 4
HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CURVE_STEP_PX = 0.85
HANDWRITING_SINGLELINE_TTF_RENDER_SCALE = 10.0
HANDWRITING_SINGLELINE_TTF_BIN_THRESHOLD = 210
HANDWRITING_SINGLELINE_TTF_SPUR_PRUNE_PX = 8
HANDWRITING_SINGLELINE_TTF_MIN_COMPONENT_PX = 4
HANDWRITING_SINGLELINE_TTF_USE_OTSU = True
HANDWRITING_SINGLELINE_TTF_STITCH_EPS_MM = 0.18
HANDWRITING_SINGLELINE_TTF_STITCH_GAP_MM = 0.92
HANDWRITING_SINGLELINE_TTF_STITCH_ANGLE_DEG = 62.0
HANDWRITING_SINGLELINE_TTF_WORD_JOIN_GAP_MM = 1.08
HANDWRITING_SINGLELINE_TTF_WORD_JOIN_DY_MM = 0.86
HANDWRITING_SINGLELINE_TTF_SMOOTH_RESAMPLE_MM = 0.13
HANDWRITING_SINGLELINE_TTF_SMOOTH_PASSES = 2
HANDWRITING_SINGLELINE_TTF_SMOOTH_RDP_MM = 0.03
HANDWRITING_SINGLELINE_TTF_COLLINEAR_EPS_MM = 0.028
HANDWRITING_SINGLELINE_TTF_MIXED_USE_LATIN_FALLBACK = False
HANDWRITING_SINGLELINE_TTF_PREVIEW_STROKE_SCALE = 0.020
HANDWRITING_SINGLELINE_TTF_PREVIEW_STROKE_MIN_MM = 0.11
# Auto line spacing guard for handwriting replacement:
# many script fonts have deep descenders and require larger baseline step.
HANDWRITING_AUTO_LINE_SPACING_ENABLED = True
HANDWRITING_LINE_STEP_FACTOR = 1.24
HANDWRITING_LINE_STEP_FACTOR_CYR = 1.34
HANDWRITING_LINE_STEP_EXTRA_MM = 0.70
HANDWRITING_WORD_KEEP_MATH = True
# Preserve Word layout fidelity by default: do not override document font before
# PDF export. Handwriting conversion is applied later at SVG text stage.
HANDWRITING_WORD_FORCE_FONT_EXPORT = False
# If handwriting font substitution corrupts exported text (many '?'),
# fallback to native Word fonts automatically for that job.
HANDWRITING_WORD_MAX_QMARK_RATIO = 0.015
HANDWRITING_WORD_MAX_QMARK_COUNT = 6
DEFAULT_QUALITY_PROFILE = "normal"
EXACT_GEOMETRY_MODE = True
IMAGE_CONTOUR_ENABLED = True
IMAGE_CONTOUR_WORD_ONLY = True
IMAGE_CONTOUR_MODE = "word_only"  # off | word_only | always
IMAGE_CONTOUR_CANNY_LOW = 70
IMAGE_CONTOUR_CANNY_HIGH = 170
IMAGE_CONTOUR_MIN_PATH_MM = 1.6
IMAGE_CONTOUR_MAX_PATHS_PER_IMAGE = 1200
IMAGE_CONTOUR_VECTORIZE_MODE = "centerline"  # edge | centerline | auto
IMAGE_CONTOUR_MM_SIMPLIFY_EPS = 0.12
IMAGE_CONTOUR_HANDWRITING_MIN_PATH_MM = 2.3
IMAGE_CONTOUR_CENTERLINE_MIN_COMPONENT_PX = 14
IMAGE_CONTOUR_CENTERLINE_RDP_PX = 0.90
IMAGE_CONTOUR_CENTERLINE_MAX_PATHS_PER_IMAGE = 2200
# Raster tone hatch for embedded images (notes/photos/screenshots):
# emit sparse horizontal hatch segments in dark regions.
IMAGE_TONE_HATCH_ENABLED = True
IMAGE_TONE_HATCH_WORD_ONLY = True
IMAGE_TONE_HATCH_IN_HANDWRITING = False
IMAGE_TONE_HATCH_STEP_MM = 1.1
IMAGE_TONE_HATCH_MIN_SEGMENT_MM = 0.9
IMAGE_TONE_HATCH_MAX_PATHS_PER_IMAGE = 1800
IMAGE_TONE_HATCH_USE_OTSU = True
IMAGE_TONE_HATCH_THRESHOLD = 160  # used when OTSU disabled

FILL_CENTERLINE_ENABLED = True
FILL_CENTERLINE_MAX_BBOX_MM = 12.0
FILL_CENTERLINE_MAX_BBOX_AREA_MM2 = 120.0
FILL_CENTERLINE_PX_PER_MM = 22.0
FILL_CENTERLINE_MIN_COMPONENT_PX = 4
FILL_CENTERLINE_MIN_PATH_MM = 0.12
FILL_CENTERLINE_HANDWRITING_MIN_PATH_MM = 0.24
FILL_CENTERLINE_MAX_PATHS_PER_GLYPH = 8
FILL_CENTERLINE_LEN_RATIO_MIN = 0.18
FILL_CENTERLINE_LEN_RATIO_MAX = 0.92
FILL_CENTERLINE_SPUR_PRUNE_PX = 2
FILL_CENTERLINE_HANDWRITING_SPUR_PRUNE_PX = 5
# Local centerline post-stitch joins fragmented skeleton pieces inside one glyph/cluster.
FILL_CENTERLINE_LOCAL_STITCH_EPS_MM = 0.10
FILL_CENTERLINE_LOCAL_GAP_EPS_MM = 0.16
FILL_CENTERLINE_LOCAL_ANGLE_DEG = 28.0
# Handwriting mode: allow denser centerline decomposition, then stitch locally.
FILL_CENTERLINE_HANDWRITING_MAX_PATHS_PER_GLYPH = 220
FILL_CENTERLINE_HANDWRITING_LEN_RATIO_MIN = 0.08
FILL_CENTERLINE_HANDWRITING_LEN_RATIO_MAX = 1.70
FILL_CENTERLINE_HANDWRITING_MAX_BBOX_MM = 260.0
FILL_CENTERLINE_HANDWRITING_MAX_BBOX_AREA_MM2 = 24000.0
FILL_CENTERLINE_HANDWRITING_PX_PER_MM = 26.0
FILL_CENTERLINE_HANDWRITING_LOCAL_STITCH_EPS_MM = 0.22
FILL_CENTERLINE_HANDWRITING_LOCAL_GAP_EPS_MM = 0.50
FILL_CENTERLINE_HANDWRITING_LOCAL_ANGLE_DEG = 50.0
# Stronger single-stroke text mode:
# cluster tiny fill contours across nearby source ids (common in PDF glyph export)
# and try centerline conversion on the merged glyph cluster.
SINGLE_STROKE_TEXT_ENABLED = True
SINGLE_STROKE_TEXT_CLUSTER_MAX_BBOX_MM = 13.0
SINGLE_STROKE_TEXT_CLUSTER_GAP_MM = 0.20
SINGLE_STROKE_TEXT_CLUSTER_MAX_ITEMS = 1500
# Some converters emit text as stroke-only closed outlines (double contour).
# Cluster such tiny outlines and centerline them too.
SINGLE_STROKE_OUTLINE_TEXT_ENABLED = True
SINGLE_STROKE_OUTLINE_CLUSTER_MAX_BBOX_MM = 14.0
SINGLE_STROKE_OUTLINE_COMPONENT_MAX_BBOX_MM = 22.0
SINGLE_STROKE_OUTLINE_COMPONENT_MAX_AREA_MM2 = 320.0
SINGLE_STROKE_OUTLINE_CLUSTER_GAP_MM = 0.22
SINGLE_STROKE_OUTLINE_CLUSTER_MAX_ITEMS = 2200
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
# Pencil naturalness tuning (for notes/conспекты):
# apply only in handwriting mode by default to keep technical geometry intact.
PENCIL_NATURAL_STROKES_ENABLED = True
PENCIL_NATURAL_ONLY_HANDWRITING = True
PENCIL_NATURAL_BASE_AMP_MM = 0.09
PENCIL_NATURAL_MAX_AMP_MM = 0.16
PENCIL_NATURAL_RESAMPLE_MM = 0.45
PENCIL_NATURAL_MIN_LEN_MM = 2.0
PENCIL_NATURAL_MAX_LEN_MM = 120.0
PENCIL_NATURAL_SKIP_NEAR_LINE_TOL_MM = 0.08
PENCIL_NATURAL_SMOOTH_PASSES = 1
# Tiny deterministic per-stroke pressure variation (Z) to avoid perfectly uniform tone.
PENCIL_STROKE_Z_JITTER_ENABLED = True
PENCIL_STROKE_Z_JITTER_MM = 0.06
PENCIL_STROKE_Z_JITTER_SEED = 173

INKSCAPE_CANDIDATES = [
    r"C:\Program Files\Inkscape\bin\inkscape.exe",
    r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe",
    "inkscape.exe",
    r"C:\Program Files\Inkscape\bin\inkscape.com",
    r"C:\Program Files (x86)\Inkscape\bin\inkscape.com",
    "inkscape.com",
    "inkscape",
]
PDFTOCAIRO_CANDIDATES = [
    "pdftocairo",
]
PDFTOTEXT_CANDIDATES = [
    "pdftotext",
]
USE_INKSCAPE_PDF_IMPORT = False
INKSCAPE_AUTO_ACCEPT_PDF_IMPORT_DIALOG = True
INKSCAPE_PDF_DIALOG_WATCHER_ENABLED = False
INKSCAPE_PDF_IMPORT_DIALOG_TITLES = (
    "Параметры импорта PDF",
    "PDF Import Settings",
)
INKSCAPE_PDF_IMPORT_DIALOG_TIMEOUT_S = 45.0

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

    def _is_inkscape_pdf_call(argv: List[str]) -> bool:
        if not argv:
            return False
        exe = Path(str(argv[0])).name.lower()
        if "inkscape" not in exe:
            return False
        return any(str(part).lower().endswith(".pdf") for part in argv[1:])

    def _auto_accept_inkscape_pdf_import_dialog(proc: subprocess.Popen) -> None:
        if not sys.platform.startswith("win"):
            return
        if not INKSCAPE_AUTO_ACCEPT_PDF_IMPORT_DIALOG:
            return
        if not proc or proc.poll() is not None:
            return

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        WM_COMMAND = 0x0111
        IDOK = 1
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        VK_RETURN = 0x0D
        BM_CLICK = 0x00F5

        enum_windows = user32.EnumWindows
        is_window_visible = user32.IsWindowVisible
        get_window_text_length = user32.GetWindowTextLengthW
        get_window_text = user32.GetWindowTextW
        get_window_thread_process_id = user32.GetWindowThreadProcessId
        post_message = user32.PostMessageW
        enum_child_windows = user32.EnumChildWindows
        send_message = user32.SendMessageW
        set_foreground_window = user32.SetForegroundWindow

        title_tokens = tuple(t.lower() for t in INKSCAPE_PDF_IMPORT_DIALOG_TITLES if t)
        deadline = time.time() + max(2.0, float(INKSCAPE_PDF_IMPORT_DIALOG_TIMEOUT_S))

        def _window_title(hwnd: int) -> str:
            if not is_window_visible(hwnd):
                return ""
            length = int(get_window_text_length(hwnd))
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            get_window_text(hwnd, buf, length + 1)
            return str(buf.value or "")

        while proc.poll() is None and time.time() < deadline:
            found_hwnd = 0

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def _enum_cb(hwnd, _lparam):
                nonlocal found_hwnd
                if found_hwnd:
                    return False
                title = _window_title(hwnd)
                if not title:
                    return True
                low = title.lower()
                if not any(token in low for token in title_tokens):
                    return True
                pid = ctypes.c_ulong(0)
                get_window_thread_process_id(hwnd, ctypes.byref(pid))
                if int(pid.value) != int(proc.pid):
                    return True
                found_hwnd = int(hwnd)
                return False

            try:
                enum_windows(_enum_cb, 0)
            except Exception:
                time.sleep(0.15)
                continue

            if found_hwnd:
                try:
                    set_foreground_window(found_hwnd)
                except Exception:
                    pass
                try:
                    post_message(found_hwnd, WM_COMMAND, IDOK, 0)
                except Exception:
                    pass

                clicked = {"ok": False}

                @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                def _child_cb(child, _lparam):
                    if clicked["ok"]:
                        return False
                    tlen = int(get_window_text_length(child))
                    if tlen <= 0:
                        return True
                    tbuf = ctypes.create_unicode_buffer(tlen + 1)
                    get_window_text(child, tbuf, tlen + 1)
                    txt = str(tbuf.value or "").strip().lower()
                    if txt in {"ok", "ок"}:
                        try:
                            send_message(child, BM_CLICK, 0, 0)
                            clicked["ok"] = True
                            return False
                        except Exception:
                            return True
                    return True

                try:
                    enum_child_windows(found_hwnd, _child_cb, 0)
                except Exception:
                    pass
                try:
                    post_message(found_hwnd, WM_KEYDOWN, VK_RETURN, 0)
                    post_message(found_hwnd, WM_KEYUP, VK_RETURN, 0)
                except Exception:
                    pass
            time.sleep(0.15)

    if _is_inkscape_pdf_call(cmd) and INKSCAPE_PDF_DIALOG_WATCHER_ENABLED:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **run_kwargs,
        )
        watcher = threading.Thread(
            target=_auto_accept_inkscape_pdf_import_dialog,
            args=(proc,),
            daemon=True,
        )
        watcher.start()
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            out, err = proc.communicate()
            raise
        return int(proc.returncode or 0), out, err

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


def find_pdftotext() -> str:
    for candidate in PDFTOTEXT_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return str(Path(found))
        if Path(candidate).is_file():
            return str(Path(candidate))
    # Common case: pdftocairo is discoverable and pdftotext sits in the same Poppler bin.
    try:
        cairo = Path(find_pdftocairo())
        siblings = [
            cairo.with_name("pdftotext.exe"),
            cairo.with_name("pdftotext"),
        ]
        for cand in siblings:
            if cand.is_file():
                return str(cand)
    except Exception:
        pass
    raise RuntimeError("pdftotext not found.")


def pdf_text_questionmark_metrics(pdf_path: Path, logger=print) -> Optional[Tuple[float, int, int]]:
    """Return (ratio, qmark_count, text_len) from pdftotext output, or None if unavailable."""
    try:
        exe = find_pdftotext()
    except Exception:
        return None

    with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
        txt_path = Path(td) / "text.txt"
        cmd = [exe, "-q", "-enc", "UTF-8", str(pdf_path), str(txt_path)]
        rc, out, err = run_cmd(cmd, timeout_s=25.0)
        if rc != 0 or not txt_path.exists():
            block = (out + "\n" + err).strip()
            if block:
                logger(f"pdftotext warning: {block[:300]}")
            return None
        try:
            text = txt_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    if not text:
        return None

    qmarks = text.count("?")
    qmarks += text.count("\ufffd")
    meaningful = sum(1 for ch in text if not ch.isspace())
    if meaningful <= 0:
        return None
    ratio = float(qmarks) / float(meaningful)
    return ratio, qmarks, meaningful


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


def _extract_image_centerline_paths_px(
    img: "np.ndarray",
    *,
    min_component_px: int,
    min_path_px: float,
    max_paths: int,
    rdp_px: float,
) -> List[List[Tuple[float, float]]]:
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
            else:
                alpha = None
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    except Exception:
        return []

    try:
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        if alpha is not None and int(np.max(alpha)) > 0:
            _, alpha_mask = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)
            mask = cv2.bitwise_and(mask, alpha_mask)
        # Connect anti-aliased strokes before thinning.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), dtype=np.uint8), iterations=1)
        comp = (mask > 0).astype(np.uint8)
        if int(np.count_nonzero(comp)) <= 0:
            return []
        min_comp = max(1, int(min_component_px))
        if min_comp > 1:
            num, labels, stats, _ = cv2.connectedComponentsWithStats(comp, connectivity=8)
            cleaned = np.zeros_like(comp, dtype=np.uint8)
            for i in range(1, int(num)):
                if int(stats[i, cv2.CC_STAT_AREA]) >= min_comp:
                    cleaned[labels == i] = 1
            comp = cleaned
        skel = _skeletonize_binary((comp * 255).astype(np.uint8))
        if int(np.count_nonzero(skel)) <= 0:
            return []
        skel = _prune_skeleton_spurs(skel, 2)
        pix_paths = _trace_skeleton_paths_greedy(skel)
    except Exception:
        return []

    if not pix_paths:
        return []

    out: List[List[Tuple[float, float]]] = []
    cap = max(1, int(max_paths))
    min_len_px = max(0.0, float(min_path_px))
    rdp_eps_px = max(0.0, float(rdp_px))
    simplify_eps_px = max(0.15, min(1.6, rdp_eps_px * 0.35))

    for pix_poly in pix_paths:
        if len(pix_poly) < 2:
            continue
        poly = [(float(x), float(y)) for x, y in pix_poly]
        poly = simplify_polyline(poly, eps=simplify_eps_px)
        if len(poly) >= 3 and rdp_eps_px > 0.0:
            poly = rdp_simplify_polyline(poly, eps=rdp_eps_px)
        if len(poly) < 2:
            continue
        if polyline_length(poly) < min_len_px:
            continue
        out.append(poly)
        if len(out) >= cap:
            break
    return out


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


def _extract_image_tone_hatch_segments_px(
    img: "np.ndarray",
    *,
    step_px: int,
    min_seg_px: int,
    max_paths: int,
) -> List[List[Tuple[float, float]]]:
    if cv2 is None or np is None or img is None:
        return []
    step = max(1, int(step_px))
    min_len = max(1, int(min_seg_px))
    cap = max(1, int(max_paths))

    try:
        if len(img.shape) == 2:
            gray = img
            alpha = None
        else:
            if img.shape[2] == 4:
                alpha = img[:, :, 3]
                bgr = img[:, :, :3]
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            else:
                alpha = None
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    except Exception:
        return []

    try:
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        if IMAGE_TONE_HATCH_USE_OTSU:
            _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        else:
            thr = int(max(0, min(255, IMAGE_TONE_HATCH_THRESHOLD)))
            _, dark = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY_INV)
        if alpha is not None and int(np.max(alpha)) > 0:
            _, alpha_mask = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)
            dark = cv2.bitwise_and(dark, alpha_mask)
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((2, 2), dtype=np.uint8), iterations=1)
    except Exception:
        return []

    h_px, w_px = dark.shape[:2]
    if h_px <= 1 or w_px <= 1:
        return []

    out: List[List[Tuple[float, float]]] = []
    for y in range(0, h_px, step):
        row = dark[y]
        x = 0
        while x < w_px:
            while x < w_px and row[x] == 0:
                x += 1
            if x >= w_px:
                break
            x0 = x
            while x < w_px and row[x] != 0:
                x += 1
            x1 = x - 1
            if (x1 - x0 + 1) >= min_len:
                out.append([(float(x0), float(y)), (float(x1), float(y))])
                if len(out) >= cap:
                    return out
    return out


def extract_image_contour_items(
    svg_path: Path,
    logger=print,
    *,
    enable_hatch: bool = False,
) -> List[PathItem]:
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
            # mat_mul composes in reverse order: mat_mul(a, b) == b * a.
            # For nested SVG nodes we need parent * local, so pass (local, parent).
            cur_matrix = mat_mul(parse_transform(t), cur_matrix)

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
                    w_mm = max(1e-9, float(w_u) * float(scale))
                    h_mm = max(1e-9, float(h_u) * float(scale))
                    mm_per_px_x = w_mm / max(1.0, float(w_px - 1))
                    mm_per_px_y = h_mm / max(1.0, float(h_px - 1))
                    mm_per_px = max(mm_per_px_x, mm_per_px_y)
                    min_path_mm = max(
                        float(IMAGE_CONTOUR_MIN_PATH_MM),
                        float(IMAGE_CONTOUR_HANDWRITING_MIN_PATH_MM) if HANDWRITING_TEXT_ENABLED else 0.0,
                    )
                    min_path_px = max(1.0, min_path_mm / max(1e-9, mm_per_px))
                    simplify_eps_mm = max(float(IMAGE_CONTOUR_MM_SIMPLIFY_EPS), mm_per_px * 0.95)
                    tiny_bbox_mm = 1.10 if HANDWRITING_TEXT_ENABLED else 0.65

                    mode = (IMAGE_CONTOUR_VECTORIZE_MODE or "centerline").strip().lower()
                    if mode not in {"edge", "centerline", "auto"}:
                        mode = "centerline"

                    px_centerlines: List[List[Tuple[float, float]]] = []
                    if mode in {"centerline", "auto"}:
                        center_cap = int(IMAGE_CONTOUR_CENTERLINE_MAX_PATHS_PER_IMAGE)
                        if HANDWRITING_TEXT_ENABLED:
                            center_cap = min(center_cap, 1100)
                        px_centerlines = _extract_image_centerline_paths_px(
                            img,
                            min_component_px=int(IMAGE_CONTOUR_CENTERLINE_MIN_COMPONENT_PX),
                            min_path_px=min_path_px,
                            max_paths=center_cap,
                            rdp_px=float(IMAGE_CONTOUR_CENTERLINE_RDP_PX),
                        )

                    px_edge_polys: List[List[Tuple[float, float]]] = []
                    if mode == "edge" or (mode == "auto" and not px_centerlines):
                        px_edge_polys = _extract_image_edge_contours_px(img)

                    added = 0
                    added_centerline = 0
                    added_edge = 0
                    added_hatch = 0
                    for px_poly in px_centerlines:
                        mm_poly: List[Tuple[float, float]] = []
                        for px, py in px_poly:
                            # Map pixel contour to image placement box in SVG user units.
                            ux = x_u + (px / max(1.0, float(w_px - 1))) * w_u
                            uy = y_u + (py / max(1.0, float(h_px - 1))) * h_u
                            tx, ty = mat_apply(cur_matrix, (ux, uy))
                            mm_poly.append((tx * scale, ty * scale))
                        mm_poly = simplify_polyline(mm_poly, eps=simplify_eps_mm)
                        if len(mm_poly) >= 3:
                            mm_poly = rdp_simplify_polyline(mm_poly, eps=max(0.16, simplify_eps_mm * 1.35))
                        if len(mm_poly) < 2:
                            continue
                        xs = [p[0] for p in mm_poly]
                        ys = [p[1] for p in mm_poly]
                        if (max(xs) - min(xs)) < tiny_bbox_mm and (max(ys) - min(ys)) < tiny_bbox_mm:
                            continue
                        if polyline_length(mm_poly) < min_path_mm:
                            continue
                        out.append(
                            PathItem(
                                points=mm_poly,
                                closed=False,
                                is_fill=False,
                                is_stroke=True,
                                source_id=source_id_seq,
                            )
                        )
                        added += 1
                        added_centerline += 1

                    for px_poly in px_edge_polys:
                        mm_poly = []
                        for px, py in px_poly:
                            ux = x_u + (px / max(1.0, float(w_px - 1))) * w_u
                            uy = y_u + (py / max(1.0, float(h_px - 1))) * h_u
                            tx, ty = mat_apply(cur_matrix, (ux, uy))
                            mm_poly.append((tx * scale, ty * scale))
                        mm_poly = simplify_polyline(mm_poly, eps=simplify_eps_mm)
                        if len(mm_poly) >= 3:
                            mm_poly = rdp_simplify_polyline(mm_poly, eps=max(0.18, simplify_eps_mm * 1.55))
                        if len(mm_poly) < 3:
                            continue
                        if points_distance(mm_poly[0], mm_poly[-1]) > 1e-6:
                            mm_poly.append(mm_poly[0])
                        xs = [p[0] for p in mm_poly]
                        ys = [p[1] for p in mm_poly]
                        if (max(xs) - min(xs)) < tiny_bbox_mm and (max(ys) - min(ys)) < tiny_bbox_mm:
                            continue
                        if polyline_length(mm_poly) < min_path_mm:
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
                        added_edge += 1

                    if enable_hatch:
                        step_px = max(1, int(round(float(IMAGE_TONE_HATCH_STEP_MM) * (float(h_px) / h_mm))))
                        min_seg_px = max(1, int(round(float(IMAGE_TONE_HATCH_MIN_SEGMENT_MM) * (float(w_px) / w_mm))))
                        hatch_px = _extract_image_tone_hatch_segments_px(
                            img,
                            step_px=step_px,
                            min_seg_px=min_seg_px,
                            max_paths=IMAGE_TONE_HATCH_MAX_PATHS_PER_IMAGE,
                        )
                        for px_seg in hatch_px:
                            mm_seg: List[Tuple[float, float]] = []
                            for px, py in px_seg:
                                ux = x_u + (px / max(1.0, float(w_px - 1))) * w_u
                                uy = y_u + (py / max(1.0, float(h_px - 1))) * h_u
                                tx, ty = mat_apply(cur_matrix, (ux, uy))
                                mm_seg.append((tx * scale, ty * scale))
                            mm_seg = simplify_polyline(mm_seg, eps=max(0.08, simplify_eps_mm * 0.85))
                            if len(mm_seg) < 2:
                                continue
                            if polyline_length(mm_seg) < IMAGE_TONE_HATCH_MIN_SEGMENT_MM:
                                continue
                            out.append(
                                PathItem(
                                    points=mm_seg,
                                    closed=False,
                                    is_fill=False,
                                    is_stroke=True,
                                    source_id=source_id_seq,
                                )
                            )
                            added_hatch += 1
                    if added > 0 and logger:
                        logger(f"Image contour tracing: +{added} path(s) from embedded raster.")
                        if added_centerline > 0:
                            logger(
                                "Image vectorization mode: centerline "
                                f"(added {added_centerline} path(s), simplify={simplify_eps_mm:.2f} mm)."
                            )
                        if added_edge > 0:
                            logger(
                                "Image vectorization mode: edge fallback "
                                f"(added {added_edge} path(s), simplify={simplify_eps_mm:.2f} mm)."
                            )
                    if added_hatch > 0 and logger:
                        logger(
                            f"Image tone hatch: +{added_hatch} path(s) "
                            f"(step={IMAGE_TONE_HATCH_STEP_MM:.2f} mm, min={IMAGE_TONE_HATCH_MIN_SEGMENT_MM:.2f} mm)."
                        )
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


def _read_style_dict_preserve(style: Optional[str]) -> dict:
    if not style:
        return {}
    out: dict = {}
    for part in style.split(";"):
        key, _, value = part.partition(":")
        key_s = key.strip()
        if not key_s:
            continue
        out[key_s] = value.strip()
    return out


def _style_dict_to_string(style: dict) -> str:
    parts: List[str] = []
    for key, value in style.items():
        k = str(key).strip()
        v = str(value).strip()
        if not k:
            continue
        parts.append(f"{k}:{v}")
    return ";".join(parts)


def normalize_handwriting_font_name(font_name: Optional[str]) -> str:
    name = (font_name or "").strip().strip("'").strip('"')
    if not name:
        return "Marck Script"
    return name


_HANDWRITING_TTF_PATH_CACHE: dict[str, Optional[Path]] = {}
_HANDWRITING_TTF_FONT_CACHE: dict[Tuple[str, int], object] = {}
_AUTOTRACE_EXE_CACHE: dict[str, Optional[Path]] = {}


@dataclass
class SvgStrokeGlyph:
    d: str
    adv: float


@dataclass
class SvgStrokeFontData:
    name: str
    units_per_em: float
    default_adv: float
    glyphs: dict[str, SvgStrokeGlyph]


_SVG_STROKE_FONT_PATH_CACHE: dict[str, Optional[Path]] = {}
_SVG_STROKE_FONT_DATA_CACHE: dict[str, Optional[SvgStrokeFontData]] = {}


def _resolve_handwriting_ttf_path(font_name: str) -> Optional[Path]:
    if ImageFont is None:
        return None
    requested = normalize_handwriting_font_name(font_name)
    key = requested.strip().lower()
    if key in _HANDWRITING_TTF_PATH_CACHE:
        return _HANDWRITING_TTF_PATH_CACHE[key]

    direct = Path(requested)
    if direct.exists() and direct.is_file():
        _HANDWRITING_TTF_PATH_CACHE[key] = direct
        return direct

    fonts_dir = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
    project_fonts_dir = ROOT_DIR / "data" / "fonts"
    root_fonts_dir = ROOT_DIR
    cwd_fonts_dir = Path.cwd()
    aliases: dict[str, List[str]] = {
        "segoe script": ["segoesc.ttf", "segoescb.ttf"],
        "comic sans ms": ["comic.ttf", "comicbd.ttf"],
        "caveat": ["Caveat-wght.ttf", "Caveat[wght].ttf", "Caveat-Regular.ttf", "Caveat-Bold.ttf"],
        "neucha": ["Neucha.ttf", "Neucha-Regular.ttf"],
        "marck script": ["MarckScript-Regular.ttf"],
        "bad script": ["BadScript-Regular.ttf"],
        "katherine plus": ["Katherine Plus.ttf", "Katerine Plus SL.otf"],
        "katerine plus": ["Katherine Plus.ttf", "Katerine Plus SL.otf"],
        "katerine plus sl": ["Katerine Plus SL.otf", "Katherine Plus.ttf"],
        "arial": ["arial.ttf"],
    }
    candidate_files: List[Path] = []
    for fname in aliases.get(key, []):
        candidate_files.append(project_fonts_dir / fname)
        candidate_files.append(root_fonts_dir / fname)
        candidate_files.append(cwd_fonts_dir / fname)
        candidate_files.append(fonts_dir / fname)
    if requested.lower().endswith((".ttf", ".otf", ".ttc")):
        candidate_files.append(project_fonts_dir / requested)
        candidate_files.append(root_fonts_dir / requested)
        candidate_files.append(cwd_fonts_dir / requested)
        candidate_files.append(fonts_dir / requested)
    for c in candidate_files:
        if c.exists() and c.is_file():
            _HANDWRITING_TTF_PATH_CACHE[key] = c
            return c

    tokenized = [tok for tok in re.split(r"[\s_\-]+", key) if tok]
    if tokenized:
        search_dirs = [project_fonts_dir, root_fonts_dir, cwd_fonts_dir, fonts_dir]
        seen_dirs: set[str] = set()
        for d in search_dirs:
            try:
                d_key = str(d.resolve())
            except Exception:
                d_key = str(d)
            if d_key in seen_dirs:
                continue
            seen_dirs.add(d_key)
            if not d.exists():
                continue
            try:
                for cand in d.iterdir():
                    if not cand.is_file():
                        continue
                    if cand.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                        continue
                    name = cand.name.lower()
                    if all(tok in name for tok in tokenized):
                        _HANDWRITING_TTF_PATH_CACHE[key] = cand
                        return cand
            except Exception:
                continue

    # Last resort: common script font path on Windows.
    fallback = fonts_dir / "segoesc.ttf"
    if fallback.exists() and fallback.is_file():
        _HANDWRITING_TTF_PATH_CACHE[key] = fallback
        return fallback

    _HANDWRITING_TTF_PATH_CACHE[key] = None
    return None


def _auto_local_handwriting_font_candidate() -> Optional[str]:
    # Local per-project single-line fonts placed in repository root.
    for fname in ("Katherine Plus.ttf", "Katerine Plus SL.otf"):
        p = ROOT_DIR / fname
        if p.exists() and p.is_file():
            return str(p)
    return None


def _effective_handwriting_font_for_text(has_cyrillic: bool) -> str:
    auto_local = _auto_local_handwriting_font_candidate()
    default_not_overridden = (
        normalize_handwriting_font_name(HANDWRITING_FONT_FAMILY).lower() == "marck script"
        and normalize_handwriting_font_name(HANDWRITING_CYRILLIC_FONT_FAMILY).lower() == "marck script"
    )
    # Prefer explicit Cyrillic-capable handwriting fonts for RU text.
    if has_cyrillic:
        candidates = [
            *(([auto_local] if auto_local and default_not_overridden else [])),
            HANDWRITING_CYRILLIC_FONT_FAMILY,
            HANDWRITING_FONT_FAMILY,
            "Caveat",
            "Neucha",
            "Marck Script",
            "Bad Script",
            "Comic Sans MS",
            "Arial",
        ]
    else:
        candidates = [
            *(([auto_local] if auto_local and default_not_overridden else [])),
            HANDWRITING_FONT_FAMILY,
            "Caveat",
            "Neucha",
            "Marck Script",
            "Bad Script",
            "Segoe Script",
            "Arial",
        ]
    for cand in candidates:
        name = normalize_handwriting_font_name(cand)
        if not name:
            continue
        if _resolve_handwriting_ttf_path(name) is not None:
            return name
    return normalize_handwriting_font_name(HANDWRITING_FONT_FAMILY)


def _replace_handwriting_text_nodes(svg_path: Path, has_cyrillic: bool, logger) -> int:
    preferred_font = _effective_handwriting_font_for_text(has_cyrillic)
    locale = "Cyrillic" if has_cyrillic else "Latin/EN"
    cyr_profile = _analyze_svg_text_profile(svg_path) if has_cyrillic else None
    cyr_method3_force = bool(
        has_cyrillic and _normalize_singleline_ttf_backend(HANDWRITING_SINGLELINE_TTF_BACKEND) == "autotrace3"
    )
    cyr_prefers_direct = bool(
        has_cyrillic
        and HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED
        and cyr_profile
        and cyr_profile.get("technical_like", False)
        and not cyr_method3_force
    )
    if has_cyrillic and cyr_profile:
        logger(
            "Handwriting mode: Cyrillic text profile "
            f"tokens={int(cyr_profile.get('tokens', 0))}, "
            f"short={100.0 * float(cyr_profile.get('short_ratio', 0.0)):.0f}%, "
            f"digits={100.0 * float(cyr_profile.get('digit_ratio', 0.0)):.0f}%, "
            f"long={100.0 * float(cyr_profile.get('long_ratio', 0.0)):.0f}%, "
            f"style={'technical' if cyr_prefers_direct else 'paragraph'}."
        )
    if cyr_prefers_direct:
        logger(
            f"Handwriting mode: {locale} detected, direct-vector pipeline first "
            f"('{preferred_font}')."
        )
        replaced = replace_svg_text_with_hershey_strokes(svg_path, preferred_font, logger)
        if replaced > 0:
            return replaced
        if HANDWRITING_ALLOW_TTF_FALLBACK:
            logger(
                "Handwriting mode warning: direct vector replacement unavailable; "
                f"fallback to TTF centerline ({preferred_font})."
            )
            return replace_svg_text_with_singleline_ttf(svg_path, preferred_font, logger)
        logger("Handwriting mode warning: direct vector replacement unavailable, keeping source text nodes.")
        return 0
    # Optional compatibility mode: keep TTF centerline as first attempt.
    # Disabled by default for RU because Hershey + contour averaging is more stable for plotting.
    if has_cyrillic and HANDWRITING_CYRILLIC_PREFER_TTF:
        logger(
            f"Handwriting mode: {locale} detected, trying TTF single-line pipeline first "
            f"('{preferred_font}')."
        )
        ttf_replaced = replace_svg_text_with_singleline_ttf(svg_path, preferred_font, logger)
        if ttf_replaced > 0:
            return ttf_replaced
        logger("Handwriting mode warning: TTF single-line replacement failed, fallback to Hershey stroke mode.")

    logger(f"Handwriting mode: {locale} detected, using Hershey stroke pipeline.")
    # Keep handwriting text deterministic and single-line by default:
    # prefer vector stroke-fonts over rasterized TTF centerline extraction.
    replaced = replace_svg_text_with_hershey_strokes(svg_path, preferred_font, logger)
    if replaced > 0:
        return replaced
    if HANDWRITING_ALLOW_TTF_FALLBACK:
        logger(
            "Handwriting mode warning: stroke-font replacement unavailable; "
            f"fallback to TTF centerline ({preferred_font})."
        )
        return replace_svg_text_with_singleline_ttf(svg_path, preferred_font, logger)
    logger("Handwriting mode warning: stroke-font replacement unavailable, keeping source text nodes.")
    return 0


def _svg_stroke_font_dirs() -> List[Path]:
    dirs: List[Path] = []
    # Project-local bundle (preferred for reproducibility).
    dirs.append(ROOT_DIR / "data" / "stroke_fonts")
    # Dev/test clone used during tuning.
    dirs.append(ROOT_DIR / "_tmp" / "inkscapestrokefont" / "strokefontdata")
    out: List[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _resolve_svg_stroke_font_path(font_name: str) -> Optional[Path]:
    name = (font_name or "").strip().strip("'").strip('"')
    if not name:
        return None
    key = name.lower()
    if key in _SVG_STROKE_FONT_PATH_CACHE:
        return _SVG_STROKE_FONT_PATH_CACHE[key]

    p = Path(name)
    if p.exists() and p.is_file():
        _SVG_STROKE_FONT_PATH_CACHE[key] = p
        return p

    candidates: List[Path] = []
    for d in _svg_stroke_font_dirs():
        candidates.append(d / f"{name}.svg")
        if name.lower().endswith(".svg"):
            candidates.append(d / name)

    for c in candidates:
        if c.exists() and c.is_file():
            _SVG_STROKE_FONT_PATH_CACHE[key] = c
            return c

    # Tokenized fuzzy match as final fallback.
    toks = [t for t in re.split(r"[\s_\-]+", key) if t]
    for d in _svg_stroke_font_dirs():
        if not d.exists():
            continue
        try:
            for f in d.iterdir():
                if not f.is_file() or f.suffix.lower() != ".svg":
                    continue
                lname = f.stem.lower()
                if all(t in lname for t in toks):
                    _SVG_STROKE_FONT_PATH_CACHE[key] = f
                    return f
        except Exception:
            continue

    _SVG_STROKE_FONT_PATH_CACHE[key] = None
    return None


def _load_svg_stroke_font_data(font_name: str, logger) -> Optional[SvgStrokeFontData]:
    key = (font_name or "").strip().lower()
    if key in _SVG_STROKE_FONT_DATA_CACHE:
        return _SVG_STROKE_FONT_DATA_CACHE[key]

    font_path = _resolve_svg_stroke_font_path(font_name)
    if font_path is None:
        _SVG_STROKE_FONT_DATA_CACHE[key] = None
        return None

    try:
        root = ET.parse(font_path).getroot()
    except Exception as exc:
        logger(f"SVG stroke font load failed ({font_name}): {exc}")
        _SVG_STROKE_FONT_DATA_CACHE[key] = None
        return None

    ns = ""
    if "}" in root.tag:
        ns = root.tag.split("}")[0] + "}"
    font_el = root.find(f".//{ns}font")
    face_el = root.find(f".//{ns}font-face")
    if font_el is None:
        _SVG_STROKE_FONT_DATA_CACHE[key] = None
        return None

    units = _parse_svg_number(face_el.attrib.get("units-per-em") if face_el is not None else None, default=1000.0)
    if units <= 0.0:
        units = 1000.0
    default_adv = _parse_svg_number(font_el.attrib.get("horiz-adv-x"), default=units * 0.5)
    if default_adv <= 0.0:
        default_adv = units * 0.5

    cyr_font_hint = any(
        token in f"{(font_name or '').lower()} {(font_path.stem or '').lower()}"
        for token in ("cyr", "cyril", "кирил")
    )

    def _normalize_svg_glyph_unicode(raw: str) -> Optional[str]:
        text = (raw or "").strip()
        if not text:
            return None
        if len(text) == 1:
            if cyr_font_hint:
                code = ord(text)
                # Some Cyrillic stroke-font bundles store glyph unicode as raw 8-bit
                # cp1251 bytes inside XML (e.g. 0xC0..0xFF) instead of proper Unicode.
                # ET then gives us Latin-1-like chars (À, Ý, ...). Re-map them back.
                if 0x80 <= code <= 0xFF and not CYRILLIC_TEXT_RE.search(text):
                    try:
                        repaired = bytes([code]).decode("cp1251")
                    except Exception:
                        repaired = ""
                    if repaired and len(repaired) == 1:
                        return repaired
            return text
        if not cyr_font_hint:
            return None
        # Some bundled stroke-fonts keep Cyrillic unicode values mojibaked
        # (UTF-8 bytes decoded as cp1251/latin1, e.g. "Рђ" instead of "А").
        for src_enc in ("cp1251", "latin1"):
            try:
                repaired = text.encode(src_enc, errors="strict").decode("utf-8", errors="strict")
            except Exception:
                continue
            if len(repaired) == 1:
                return repaired
        return None

    glyphs: dict[str, SvgStrokeGlyph] = {}
    for g in font_el.findall(f"{ns}glyph"):
        unicode_raw = g.attrib.get("unicode")
        if unicode_raw is None:
            continue
        # Keep deterministic one-char mapping; skip ligatures/multichar glyphs.
        unicode_val = _normalize_svg_glyph_unicode(unicode_raw)
        if unicode_val is None:
            continue
        d = (g.attrib.get("d") or "").strip()
        adv = _parse_svg_number(g.attrib.get("horiz-adv-x"), default=default_adv)
        if adv <= 0.0:
            adv = default_adv
        glyphs[unicode_val] = SvgStrokeGlyph(d=d, adv=adv)

    out = SvgStrokeFontData(
        name=(face_el.attrib.get("font-family") if face_el is not None else font_el.attrib.get("id", font_name)) or font_name,
        units_per_em=units,
        default_adv=default_adv,
        glyphs=glyphs,
    )
    _SVG_STROKE_FONT_DATA_CACHE[key] = out
    return out


def _pick_svg_stroke_font_chain(font_name: str, text: str) -> List[str]:
    requested = (font_name or "").strip().lower()
    chain: List[str] = []
    has_cyr = _text_contains_cyrillic(text)
    if requested and requested.endswith(".svg"):
        chain.append(font_name.strip())
    elif requested and "hershey-cyr" in requested:
        chain.append(HANDWRITING_STROKE_SVG_CYR)
    elif has_cyr:
        # For Cyrillic text prefer explicit Cyrillic stroke font first.
        chain.append(HANDWRITING_STROKE_SVG_CYR)
    else:
        chain.append(HANDWRITING_STROKE_SVG_PRIMARY)
    if has_cyr:
        if HANDWRITING_STROKE_SVG_CYR not in chain:
            chain.append(HANDWRITING_STROKE_SVG_CYR)
    for fb in HANDWRITING_STROKE_SVG_FALLBACKS:
        if fb not in chain:
            chain.append(fb)
    # Do not inject requested TTF handwriting family names (e.g. "Marck Script")
    # into SVG stroke-font lookup. It previously caused fuzzy matching to
    # unrelated SVG fonts and produced unreadable text outlines.
    if requested and not requested.endswith(".svg"):
        explicit = requested.replace("_", " ").strip()
        if explicit.startswith("hershey") or explicit == "custom-script":
            if all(explicit != c.lower() for c in chain):
                chain.insert(1, explicit)
    return chain


def _get_cached_handwriting_pil_font(ttf_path: Path, font_px: int):
    if ImageFont is None:
        return None
    key = (str(ttf_path).lower(), int(font_px))
    cached = _HANDWRITING_TTF_FONT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        font = ImageFont.truetype(str(ttf_path), int(font_px))
    except Exception:
        return None
    _HANDWRITING_TTF_FONT_CACHE[key] = font
    return font


def _split_text_tokens_keep_spaces(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"\S+|\s+", text, flags=re.UNICODE)


_HANDWRITING_TEXT_NORMALIZE_TRANSLATIONS = {
    # Superscripts -> explicit baseline notation to avoid disappearing tiny glyphs.
    ord("⁰"): "^0",
    ord("¹"): "^1",
    ord("²"): "^2",
    ord("³"): "^3",
    ord("⁴"): "^4",
    ord("⁵"): "^5",
    ord("⁶"): "^6",
    ord("⁷"): "^7",
    ord("⁸"): "^8",
    ord("⁹"): "^9",
    # Subscripts -> explicit notation.
    ord("₀"): "_0",
    ord("₁"): "_1",
    ord("₂"): "_2",
    ord("₃"): "_3",
    ord("₄"): "_4",
    ord("₅"): "_5",
    ord("₆"): "_6",
    ord("₇"): "_7",
    ord("₈"): "_8",
    ord("₉"): "_9",
    # Common math dashes/symbols.
    ord("−"): "-",
    ord("–"): "-",
    ord("—"): "-",
    ord("×"): "x",
    ord("⋅"): "*",
    ord("·"): ".",
    ord("ˆ"): "^",
}

_HANDWRITING_MATH_SYMBOL_RE = re.compile(r"[\u2190-\u22FF\u27C0-\u27EF\u2980-\u2AFF\uE000-\uF8FF]")
_HANDWRITING_MATH_FONT_HINTS = (
    "cambria math",
    "cambriamath",
    "stix math",
    "xits math",
    "latin modern math",
    "tex gyre",
    "asana math",
)
_HANDWRITING_GREEK_ASCII_FALLBACK = {
    "α": "a",
    "β": "b",
    "γ": "g",
    "δ": "d",
    "ε": "e",
    "ζ": "z",
    "η": "n",
    "θ": "th",
    "ι": "i",
    "κ": "k",
    "λ": "l",
    "μ": "m",
    "ν": "n",
    "ξ": "x",
    "ο": "o",
    "π": "p",
    "ρ": "p",
    "σ": "s",
    "τ": "t",
    "υ": "u",
    "φ": "f",
    "χ": "x",
    "ψ": "ps",
    "ω": "w",
    "Α": "A",
    "Β": "B",
    "Γ": "G",
    "Δ": "D",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Θ": "TH",
    "Ι": "I",
    "Κ": "K",
    "Λ": "L",
    "Μ": "M",
    "Ν": "N",
    "Ξ": "X",
    "Ο": "O",
    "Π": "P",
    "Ρ": "P",
    "Σ": "S",
    "Τ": "T",
    "Υ": "Y",
    "Φ": "F",
    "Χ": "X",
    "Ψ": "PS",
    "Ω": "W",
}


def _normalize_handwriting_text_token(text: str) -> str:
    if not text:
        return text
    normalized = _strip_unpaired_surrogates(text, replacement=" ")
    normalized = normalized.translate(_HANDWRITING_TEXT_NORMALIZE_TRANSLATIONS)
    out_chars: List[str] = []
    for ch in normalized:
        cp = ord(ch)
        # Recover mathematical alphanumeric symbols from broken U+D4xx imports
        # and normalize them to plain Latin/Greek for stable single-stroke output.
        if 0xD400 <= cp <= 0xD7FF:
            try:
                expanded = unicodedata.normalize("NFKD", chr(cp + 0x10000))
            except Exception:
                expanded = " "
        elif 0x1D400 <= cp <= 0x1D7FF:
            try:
                expanded = unicodedata.normalize("NFKD", ch)
            except Exception:
                expanded = " "
        else:
            expanded = ch

        for part in (expanded or " "):
            if part in _HANDWRITING_GREEK_ASCII_FALLBACK:
                out_chars.append(_HANDWRITING_GREEK_ASCII_FALLBACK[part])
                continue
            if part == "\u00A0":
                out_chars.append(" ")
                continue
            cat = unicodedata.category(part)
            if cat in {"Cc", "Cs", "Co", "Cn"}:
                out_chars.append(" ")
                continue
            out_chars.append(part)
    return "".join(out_chars)


def _style_prefers_native_vector(style: Optional[dict]) -> bool:
    # Keep disabled by default: math/cambria glyphs are normalized and rendered
    # through the same centerline pipeline for consistent single-stroke output.
    return False


def _text_contains_formula_script(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if 0x0370 <= cp <= 0x03FF:  # Greek
            return True
        if 0x1D400 <= cp <= 0x1D7FF:  # Math Alphanumeric Symbols
            return True
        if 0xD400 <= cp <= 0xD7FF:  # Broken imported math symbols
            return True
    return False


def _text_prefers_native_vector(text: str) -> bool:
    src = _strip_unpaired_surrogates(text or "", replacement=" ")
    if not src:
        return False
    # Keep native text only for obviously broken/private-use symbolic fragments.
    # Everything else should pass through the same handwriting centerline path.
    letters = sum(1 for ch in src if ch.isalpha())
    digits = sum(1 for ch in src if ch.isdigit())
    private_use = sum(1 for ch in src if 0xE000 <= ord(ch) <= 0xF8FF)
    broken_math = sum(1 for ch in src if 0xD400 <= ord(ch) <= 0xD7FF)
    replacement = src.count("\uFFFD")
    if (private_use + broken_math + replacement) >= 3 and letters <= 2 and digits <= 2:
        return True
    return False


def _handwriting_min_line_step_mm(font_size: float, text: str = "") -> float:
    fs = max(1.0, float(font_size))
    factor = float(HANDWRITING_LINE_STEP_FACTOR_CYR) if _text_contains_cyrillic(text or "") else float(HANDWRITING_LINE_STEP_FACTOR)
    return max(fs * factor, fs + float(HANDWRITING_LINE_STEP_EXTRA_MM))


def _adjust_handwriting_tspan_dy(
    dy: float,
    *,
    font_size: float,
    text: str,
    is_first_visible_line: bool,
) -> float:
    if not HANDWRITING_AUTO_LINE_SPACING_ENABLED:
        return float(dy)
    d = float(dy)
    if is_first_visible_line and abs(d) <= 1e-9:
        return d
    min_step = _handwriting_min_line_step_mm(font_size, text)
    if d >= 0.0:
        return max(d, min_step)
    return min(d, -min_step)


def _merge_svg_text_style(parent_style: dict, node: ET.Element) -> dict:
    merged = dict(parent_style)
    merged.update(_read_style_dict_preserve(node.attrib.get("style")))
    for key in (
        "fill",
        "stroke",
        "font-size",
        "font-family",
        "-inkscape-font-specification",
        "font",
        "display",
        "visibility",
        "opacity",
        "fill-opacity",
        "stroke-opacity",
    ):
        if key in node.attrib:
            merged[key] = str(node.attrib.get(key, "")).strip()
    return merged


def _sanitize_svg_text_node_for_vector(node: ET.Element) -> bool:
    def _sanitize_local(text: Optional[str]) -> Tuple[Optional[str], bool]:
        if text is None:
            return None, False
        normalized = _normalize_handwriting_text_token(text)
        return normalized, (normalized != text)

    changed = False

    new_text, c = _sanitize_local(node.text)
    if c:
        node.text = new_text
        changed = True

    for child in list(node):
        child_changed = _sanitize_svg_text_node_for_vector(child)
        if child_changed:
            changed = True
        new_tail, c_tail = _sanitize_local(child.tail)
        if c_tail:
            child.tail = new_tail
            changed = True

    return changed


def _svg_text_node_is_visible(style: Optional[dict], node: Optional[ET.Element] = None) -> bool:
    st = style or {}

    def _pick_style_val(key: str) -> str:
        v = st.get(key)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
        if node is not None:
            return str(node.attrib.get(key, "")).strip()
        return ""

    display = _pick_style_val("display").lower()
    if display == "none":
        return False

    visibility = _pick_style_val("visibility").lower()
    if visibility in {"hidden", "collapse"}:
        return False

    opacity = _parse_svg_number(_pick_style_val("opacity"), default=1.0)
    if opacity <= 1e-6:
        return False

    fill = _pick_style_val("fill").lower()
    stroke = _pick_style_val("stroke").lower()
    fill_none = fill in {"", "none", "transparent"}
    stroke_none = stroke in {"", "none", "transparent"}

    fill_opacity = _parse_svg_number(_pick_style_val("fill-opacity"), default=1.0)
    stroke_opacity = _parse_svg_number(_pick_style_val("stroke-opacity"), default=1.0)

    if fill_none and stroke_none:
        # If neither color is specified at all, SVG defaults to black fill.
        if "fill" not in st and "stroke" not in st and (node is None or ("fill" not in node.attrib and "stroke" not in node.attrib)):
            return True
        return False

    if (fill_none or fill_opacity <= 1e-6) and (stroke_none or stroke_opacity <= 1e-6):
        return False

    return True


def _pick_svg_text_stroke_color(style: Optional[dict]) -> Optional[str]:
    st = style or {}
    stroke_raw = str(st.get("stroke", "")).strip()
    fill_raw = str(st.get("fill", "")).strip()
    stroke = stroke_raw.lower()
    fill = fill_raw.lower()
    stroke_none = stroke in {"", "none", "transparent"}
    fill_none = fill in {"", "none", "transparent"}

    if not stroke_none:
        return stroke_raw
    if not fill_none:
        return fill_raw

    # Explicit none/transparent should stay invisible.
    if ("stroke" in st and stroke_none) or ("fill" in st and fill_none):
        return None

    # No explicit paint specified: default visible black fill in SVG.
    return "#000000"


def _collect_native_row_text_node_ids(root: ET.Element, *, row_tol: float = 1.4) -> set[int]:
    entries: List[Tuple[int, float, bool]] = []

    def walk(node: ET.Element, inherited_style: dict, matrix: Tuple[float, float, float, float, float, float]) -> None:
        cur_style = _merge_svg_text_style(inherited_style, node)
        local_transform = parse_transform(node.attrib.get("transform", ""))
        cur_matrix = mat_mul(local_transform, matrix)
        if tag_name(node.tag).lower() in TEXT_NODE_TAGS:
            x_list = _parse_svg_number_list(node.attrib.get("x"))
            y_list = _parse_svg_number_list(node.attrib.get("y"))
            x0 = x_list[0] if x_list else 0.0
            y0 = y_list[0] if y_list else 0.0
            _, gy = mat_apply(cur_matrix, (x0, y0))
            txt = _extract_svg_text_plain(node)
            force_native = _style_prefers_native_vector(cur_style) or _text_prefers_native_vector(txt)
            entries.append((id(node), float(gy), bool(force_native)))
        for child in list(node):
            walk(child, cur_style, cur_matrix)

    walk(root, {}, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    keep_ids: set[int] = set()
    for node_id, _, force_native in entries:
        if force_native:
            keep_ids.add(node_id)
    return keep_ids


def _dedupe_svg_text_nodes(root: ET.Element, *, coord_tol_mm: float = 0.20, font_tol_mm: float = 0.20) -> int:
    """Drop exact duplicate text nodes at the same position (Word/PDF import artifact)."""

    def _norm_text(src: str) -> str:
        txt = _normalize_handwriting_text_token(src or "")
        txt = re.sub(r"\s+", " ", txt, flags=re.UNICODE).strip()
        return txt

    buckets: Dict[Tuple[int, int, int, str], List[Tuple[ET.Element, ET.Element, int, float]]] = {}
    seq = 0

    def walk(
        parent: ET.Element,
        node: ET.Element,
        inherited_style: dict,
        matrix: Tuple[float, float, float, float, float, float],
    ) -> None:
        nonlocal seq
        cur_style = _merge_svg_text_style(inherited_style, node)
        local_transform = parse_transform(node.attrib.get("transform", ""))
        cur_matrix = mat_mul(local_transform, matrix)
        if tag_name(node.tag).lower() in TEXT_NODE_TAGS:
            txt_raw = _extract_svg_text_plain(node)
            txt = _norm_text(txt_raw)
            if txt and _svg_text_node_is_visible(cur_style, node):
                raw = _strip_unpaired_surrogates(txt_raw, replacement=" ")
                broken = 0
                for ch in raw:
                    cp = ord(ch)
                    if (0xD400 <= cp <= 0xD7FF) or (0xE000 <= cp <= 0xF8FF) or ch == "\uFFFD":
                        broken += 1
                alnum = sum(1 for ch in txt if ch.isalnum())
                native_penalty = 25.0 if _text_prefers_native_vector(raw) else 0.0
                # Prefer cleaner, more readable candidate in duplicate stack.
                quality = float(alnum) * 4.0 + float(len(txt)) * 0.1 - float(broken) * 12.0 - native_penalty

                x_list = _parse_svg_number_list(node.attrib.get("x"))
                y_list = _parse_svg_number_list(node.attrib.get("y"))
                x0 = x_list[0] if x_list else 0.0
                y0 = y_list[0] if y_list else 0.0
                gx, gy = mat_apply(cur_matrix, (x0, y0))
                font_size = _parse_svg_number(cur_style.get("font-size"), default=12.0)
                key = (
                    int(round(float(gx) / max(0.01, float(coord_tol_mm)))),
                    int(round(float(gy) / max(0.01, float(coord_tol_mm)))),
                    int(round(float(font_size) / max(0.01, float(font_tol_mm)))),
                    txt,
                )
                buckets.setdefault(key, []).append((parent, node, seq, quality))
                seq += 1
        for child in list(node):
            walk(node, child, cur_style, cur_matrix)

    for child in list(root):
        walk(root, child, {}, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))

    removed = 0
    for entries in buckets.values():
        if len(entries) <= 1:
            continue
        keep = max(entries, key=lambda row: (row[3], -row[2]))
        keep_node = keep[1]
        for parent, node, _seq, _quality in entries:
            if node is keep_node:
                continue
            try:
                parent.remove(node)
                removed += 1
            except Exception:
                pass

    return removed


def _normalize_singleline_ttf_backend(mode: Optional[str]) -> str:
    m = (mode or "").strip().lower()
    if m in {"autotrace", "autotrace3", "method3", "m3", "3"}:
        return "autotrace3"
    if m in {"skeleton", "thin", "thinning"}:
        return "skeleton"
    if m in {"auto", ""}:
        return "auto"
    return "skeleton"


def _resolve_autotrace_executable() -> Optional[Path]:
    key = "autotrace"
    if key in _AUTOTRACE_EXE_CACHE:
        return _AUTOTRACE_EXE_CACHE[key]

    env_cands = [
        os.environ.get("HANDWRITING_AUTOTRACE_EXE", ""),
        os.environ.get("AUTOTRACE_EXE", ""),
    ]
    candidate_paths: List[Path] = []
    for envv in env_cands:
        if envv and str(envv).strip():
            candidate_paths.append(Path(str(envv).strip()))
    candidate_paths.extend(
        [
            ROOT_DIR / "tools" / "autotrace" / "autotrace.exe",
            ROOT_DIR / "tools" / "autotrace" / "autotrace",
            ROOT_DIR / "autotrace.exe",
            Path.cwd() / "autotrace.exe",
            Path("C:/Program Files (x86)/AutoTrace/autotrace.exe"),
            Path("C:/Program Files/AutoTrace/autotrace.exe"),
        ]
    )
    which_cands = [shutil.which("autotrace"), shutil.which("autotrace.exe")]
    for wc in which_cands:
        if wc:
            candidate_paths.append(Path(wc))

    seen: set[str] = set()
    for cand in candidate_paths:
        try:
            key_path = str(cand.resolve())
        except Exception:
            key_path = str(cand)
        if key_path in seen:
            continue
        seen.add(key_path)
        if not cand.exists() or not cand.is_file():
            continue
        try:
            rc, out, err = run_cmd([str(cand), "--version"], timeout_s=12.0)
            probe = (out or "") + "\n" + (err or "")
            if rc == 0 and "AutoTrace" in probe:
                _AUTOTRACE_EXE_CACHE[key] = cand
                return cand
        except Exception:
            continue

    _AUTOTRACE_EXE_CACHE[key] = None
    return None


def _autotrace_path_d_to_polylines(path_d: str, *, curve_step_px: float) -> List[List[Tuple[float, float]]]:
    out: List[List[Tuple[float, float]]] = []
    if not path_d:
        return out

    x = y = 0.0
    sx = sy = 0.0
    polyline: List[Tuple[float, float]] = []
    last_cubic: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
    last_quadratic: Optional[Tuple[float, float]] = None
    last_cmd = ""

    for cmd, params in parse_path_tokens(path_d):
        prev_cmd = last_cmd

        if cmd in "zZ":
            if polyline:
                polyline.append((sx, sy))
                if len(polyline) >= 2:
                    out.append(polyline)
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
                nx = float(params[xi])
                ny = float(params[xi + 1])
                if first_pair:
                    if polyline and len(polyline) >= 2:
                        out.append(polyline)
                    if cmd == "m":
                        x += nx
                        y += ny
                    else:
                        x, y = nx, ny
                    polyline = [(x, y)]
                    sx, sy = x, y
                    first_pair = False
                else:
                    if cmd == "m":
                        x += nx
                        y += ny
                    else:
                        x, y = nx, ny
                    polyline.append((x, y))
                xi += 2
            last_cubic = None
            last_quadratic = None
            last_cmd = cmd
            continue

        if cmd in "lL":
            for i in range(0, len(params), 2):
                if i + 1 >= len(params):
                    break
                nx, ny = float(params[i]), float(params[i + 1])
                if cmd == "l":
                    x += nx
                    y += ny
                else:
                    x, y = nx, ny
                polyline.append((x, y))
            last_cubic = None
            last_quadratic = None
            last_cmd = cmd
            continue

        if cmd in "hH":
            for nx in params:
                v = float(nx)
                x = x + v if cmd == "h" else v
                polyline.append((x, y))
            last_cubic = None
            last_quadratic = None
            last_cmd = cmd
            continue

        if cmd in "vV":
            for ny in params:
                v = float(ny)
                y = y + v if cmd == "v" else v
                polyline.append((x, y))
            last_cubic = None
            last_quadratic = None
            last_cmd = cmd
            continue

        if cmd in "cC":
            for i in range(0, len(params), 6):
                if i + 5 >= len(params):
                    break
                c1 = (float(params[i]), float(params[i + 1]))
                c2 = (float(params[i + 2]), float(params[i + 3]))
                p = (float(params[i + 4]), float(params[i + 5]))
                if cmd == "c":
                    c1 = (x + c1[0], y + c1[1])
                    c2 = (x + c2[0], y + c2[1])
                    p = (x + p[0], y + p[1])
                seg = cubic_approx((x, y), c1, c2, p, step=max(0.25, float(curve_step_px)))
                polyline.extend(seg)
                x, y = p
                last_cubic = (c2, p)
                last_quadratic = None
            last_cmd = cmd
            continue

        if cmd in "sS":
            for i in range(0, len(params), 4):
                if i + 3 >= len(params):
                    break
                c2 = (float(params[i]), float(params[i + 1]))
                p = (float(params[i + 2]), float(params[i + 3]))
                if prev_cmd in "CcSs" and last_cubic is not None:
                    c1 = (
                        (2.0 * x) - float(last_cubic[0][0]),
                        (2.0 * y) - float(last_cubic[0][1]),
                    )
                else:
                    c1 = (x, y)
                if cmd == "s":
                    c2 = (x + c2[0], y + c2[1])
                    p = (x + p[0], y + p[1])
                seg = cubic_approx((x, y), c1, c2, p, step=max(0.25, float(curve_step_px)))
                polyline.extend(seg)
                x, y = p
                last_cubic = (c2, p)
                last_quadratic = None
            last_cmd = cmd
            continue

        if cmd in "qQ":
            for i in range(0, len(params), 4):
                if i + 3 >= len(params):
                    break
                c1 = (float(params[i]), float(params[i + 1]))
                p = (float(params[i + 2]), float(params[i + 3]))
                if cmd == "q":
                    c1 = (x + c1[0], y + c1[1])
                    p = (x + p[0], y + p[1])
                seg = quadratic_approx((x, y), c1, p, step=max(0.25, float(curve_step_px)))
                polyline.extend(seg)
                x, y = p
                last_quadratic = c1
                last_cubic = None
            last_cmd = cmd
            continue

        if cmd in "tT":
            for i in range(0, len(params), 2):
                if i + 1 >= len(params):
                    break
                p = (float(params[i]), float(params[i + 1]))
                if prev_cmd in "QqTt" and last_quadratic is not None:
                    c1 = (
                        (2.0 * x) - float(last_quadratic[0]),
                        (2.0 * y) - float(last_quadratic[1]),
                    )
                else:
                    c1 = (x, y)
                if cmd == "t":
                    p = (x + p[0], y + p[1])
                seg = quadratic_approx((x, y), c1, p, step=max(0.25, float(curve_step_px)))
                polyline.extend(seg)
                x, y = p
                last_quadratic = c1
                last_cubic = None
            last_cmd = cmd
            continue

        if cmd in "aA":
            for i in range(0, len(params), 7):
                if i + 6 >= len(params):
                    break
                rx = float(params[i])
                ry = float(params[i + 1])
                ang = float(params[i + 2])
                laf = int(float(params[i + 3]))
                sf = int(float(params[i + 4]))
                nx = float(params[i + 5])
                ny = float(params[i + 6])
                p = (x + nx, y + ny) if cmd == "a" else (nx, ny)
                seg = arc_to_polyline((x, y), rx, ry, ang, laf, sf, p, step=max(0.45, float(curve_step_px)))
                polyline.extend(seg)
                x, y = p
                last_cubic = None
                last_quadratic = None
            last_cmd = cmd
            continue

        last_cubic = None
        last_quadratic = None
        last_cmd = cmd

    if polyline and len(polyline) >= 2:
        out.append(polyline)
    return out


def _autotrace_svg_to_polylines(svg_text: str, *, curve_step_px: float) -> List[List[Tuple[float, float]]]:
    if not svg_text:
        return []
    try:
        root = ET.fromstring(svg_text)
    except Exception:
        return []
    out: List[List[Tuple[float, float]]] = []
    for node in root.iter():
        if tag_name(node.tag).lower() != "path":
            continue
        d = (node.attrib.get("d") or "").strip()
        if not d:
            continue
        raw = _autotrace_path_d_to_polylines(d, curve_step_px=curve_step_px)
        for poly in raw:
            if len(poly) >= 2:
                out.append(poly)
    return out


def _run_autotrace_centerline_on_binary(
    binary_black_on_white: "np.ndarray",
    *,
    autotrace_exe: Path,
    error_threshold: float,
    filter_iterations: int,
    curve_step_px: float,
) -> List[List[Tuple[float, float]]]:
    # Input array is uint8 with 0=black stroke, 255=white background.
    if Image is None or np is None:
        return []
    if binary_black_on_white is None or binary_black_on_white.size <= 0:
        return []
    pbm_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(prefix="ctrace_", suffix=".pbm", delete=False) as fp:
            pbm_path = Path(fp.name)
        img = Image.fromarray(binary_black_on_white.astype(np.uint8), mode="L").convert("1")
        img.save(str(pbm_path))
        cmd = [
            str(autotrace_exe),
            "--centerline",
            "--input-format=pbm",
            "--output-format=svg",
            "--error-threshold",
            f"{max(0.1, float(error_threshold)):.3f}",
            "--filter-iterations",
            str(max(0, int(filter_iterations))),
            str(pbm_path),
        ]
        rc, out, _err = run_cmd(cmd, timeout_s=25.0)
        if rc != 0 or not out.strip():
            return []
        return _autotrace_svg_to_polylines(out, curve_step_px=curve_step_px)
    except Exception:
        return []
    finally:
        if pbm_path is not None:
            try:
                if pbm_path.exists():
                    pbm_path.unlink()
            except Exception:
                pass


def _render_singleline_text_polylines_ttf_autotrace(
    text: str,
    *,
    ttf_path: Path,
    font_size: float,
    baseline_x: float,
    baseline_y: float,
    force_cyrillic_mode: Optional[bool] = None,
    logger,
) -> List[List[Tuple[float, float]]]:
    if Image is None or ImageDraw is None or ImageFont is None or cv2 is None or np is None:
        return []
    if not text:
        return []
    autotrace_exe = _resolve_autotrace_executable()
    if autotrace_exe is None:
        return []

    cyrillic_mode = _text_contains_cyrillic(text) if force_cyrillic_mode is None else bool(force_cyrillic_mode)
    render_scale = max(2.0, float(HANDWRITING_SINGLELINE_TTF_RENDER_SCALE))
    if cyrillic_mode:
        render_scale = max(render_scale, 18.0)
    font_px = max(24, int(round(max(1.0, float(font_size)) * render_scale)))
    font = _get_cached_handwriting_pil_font(ttf_path, font_px)
    if font is None:
        return []

    probe = Image.new("L", (10, 10), 255)
    draw_probe = ImageDraw.Draw(probe)
    try:
        left, top, right, bottom = draw_probe.textbbox((0, 0), text, font=font, anchor="ls")
    except Exception:
        return []
    width = max(1, int(math.ceil(right - left)))
    height = max(1, int(math.ceil(bottom - top)))
    pad = max(12, font_px // 4)
    img = Image.new("L", (width + 2 * pad, height + 2 * pad), 255)
    draw = ImageDraw.Draw(img)
    anchor_x = float(pad - left)
    anchor_y = float(pad - top)
    draw.text((anchor_x, anchor_y), text, fill=0, font=font, anchor="ls")

    if ImageOps is not None:
        try:
            img = ImageOps.autocontrast(img, cutoff=0)
        except Exception:
            pass
    arr = np.array(img, dtype=np.uint8)
    if arr.size <= 0:
        return []

    thresholds: List[int] = []
    candidates = int(max(1, min(255, HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CANDIDATES)))
    for i in range(candidates):
        thresholds.append(int(round(256.0 * (1 + i) / float(candidates + 1))))
    if HANDWRITING_SINGLELINE_TTF_USE_OTSU:
        try:
            otsu_thr, _ = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            thresholds.append(int(max(1, min(254, otsu_thr))))
        except Exception:
            pass
    if not thresholds:
        thresholds = [int(max(1, min(254, HANDWRITING_SINGLELINE_TTF_BIN_THRESHOLD)))]
    thresholds = list(dict.fromkeys(max(1, min(254, int(t))) for t in thresholds))

    best_score = -1e30
    best_thr = thresholds[0]
    best_polys_px: List[List[Tuple[float, float]]] = []

    for idx, thr in enumerate(thresholds):
        mask = ((arr < int(thr)).astype(np.uint8)) * 255
        if np.count_nonzero(mask) <= 0:
            continue
        try:
            if cyrillic_mode:
                kernel = np.ones((1, 3), dtype=np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
            else:
                kernel = np.ones((2, 2), dtype=np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        except Exception:
            pass

        binary = np.where(mask > 0, 0, 255).astype(np.uint8)
        polys_px = _run_autotrace_centerline_on_binary(
            binary,
            autotrace_exe=autotrace_exe,
            error_threshold=float(HANDWRITING_SINGLELINE_TTF_AUTOTRACE_ERROR_THRESHOLD),
            filter_iterations=int(HANDWRITING_SINGLELINE_TTF_AUTOTRACE_FILTER_ITERATIONS),
            curve_step_px=float(HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CURVE_STEP_PX),
        )
        if not polys_px:
            continue

        length = sum(polyline_length(poly) for poly in polys_px if len(poly) >= 2)
        points = sum(len(poly) for poly in polys_px if len(poly) >= 2)
        segments = sum(max(0, len(poly) - 1) for poly in polys_px if len(poly) >= 2)
        offset = ((len(thresholds) / 2.0) - float(idx)) ** 2 * float(binary.shape[0] + binary.shape[1])
        score = (length * 5.0) - (offset * 0.005) - (points * 0.20) - (segments * 20.0)
        if score > best_score:
            best_score = score
            best_thr = int(thr)
            best_polys_px = polys_px

    if not best_polys_px:
        return []

    if cyrillic_mode:
        min_path_units = max(0.08, float(font_size) * 0.008)
        rdp_eps = max(0.0010, min(0.006, float(font_size) * 0.00045))
    else:
        min_path_units = max(0.20, float(font_size) * 0.03)
        rdp_eps = max(0.004, min(0.020, float(font_size) * 0.0012))

    out: List[List[Tuple[float, float]]] = []
    for pix_poly in best_polys_px:
        if len(pix_poly) < 2:
            continue
        poly = [
            (
                baseline_x + ((float(x) - anchor_x) / render_scale),
                baseline_y + ((float(y) - anchor_y) / render_scale),
            )
            for x, y in pix_poly
        ]
        if len(poly) < 2:
            continue
        poly = simplify_polyline(poly, eps=1e-6)
        if len(poly) >= 3:
            poly = rdp_simplify_polyline(poly, eps=rdp_eps)
        if len(poly) < 2:
            continue
        if polyline_length(poly) < min_path_units:
            continue
        out.append(poly)

    out = _postprocess_singleline_text_polylines(
        out,
        font_size=font_size,
        cyrillic_mode=cyrillic_mode,
        logger=logger,
    )
    if out:
        txt_snippet = _safe_log_text(text[:28])
        logger(
            f"TTF centerline method3 text: '{txt_snippet}' -> {len(out)} stroke(s), "
            f"thr={best_thr}, cand={len(thresholds)}, font={ttf_path.name}, size={font_size:.2f}"
        )
    return out


def _measure_text_advance_mm(text: str, *, font, render_scale: float) -> float:
    if not text:
        return 0.0
    probe = Image.new("L", (8, 8), 255)
    draw = ImageDraw.Draw(probe)
    adv_px = 0.0
    try:
        adv_px = float(draw.textlength(text, font=font))
    except Exception:
        adv_px = 0.0
    if adv_px <= 0.0:
        try:
            l, _, r, _ = draw.textbbox((0, 0), text, font=font, anchor="ls")
            adv_px = float(r - l)
        except Exception:
            adv_px = 0.0
    return max(0.0, adv_px / max(1e-9, float(render_scale)))


def _trace_skeleton_paths_greedy(skel: "np.ndarray") -> List[List[Tuple[int, int]]]:
    if np is None:
        return []
    ys, xs = np.where(skel > 0)
    if len(xs) == 0:
        return []
    pixels = {(int(x), int(y)) for x, y in zip(xs.tolist(), ys.tolist())}

    def neigh8(p: Tuple[int, int]) -> List[Tuple[int, int]]:
        x, y = p
        out: List[Tuple[int, int]] = []
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

    def edge_key(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    def _pt_sort_key(p: Tuple[int, int]) -> Tuple[int, int]:
        return (p[1], p[0])

    def _turn_cost(prev_pt: Tuple[int, int], cur_pt: Tuple[int, int], nxt_pt: Tuple[int, int]) -> float:
        v1x = float(cur_pt[0] - prev_pt[0])
        v1y = float(cur_pt[1] - prev_pt[1])
        v2x = float(nxt_pt[0] - cur_pt[0])
        v2y = float(nxt_pt[1] - cur_pt[1])
        l1 = math.hypot(v1x, v1y)
        l2 = math.hypot(v2x, v2y)
        if l1 <= 1e-9 or l2 <= 1e-9:
            return 1.0
        cosang = (v1x * v2x + v1y * v2y) / (l1 * l2)
        cosang = max(-1.0, min(1.0, cosang))
        # Prefer smallest turn (straight continuation).
        return 1.0 - cosang

    def _pick_next(prev_pt: Tuple[int, int], cur_pt: Tuple[int, int], candidates: List[Tuple[int, int]]) -> Tuple[int, int]:
        if len(candidates) <= 1:
            return candidates[0]
        scored = sorted(candidates, key=lambda q: (_turn_cost(prev_pt, cur_pt, q), _pt_sort_key(q)))
        return scored[0]

    used_edges: set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
    out: List[List[Tuple[int, int]]] = []

    def walk_edge(start: Tuple[int, int], nxt: Tuple[int, int]) -> List[Tuple[int, int]]:
        path = [start, nxt]
        used_edges.add(edge_key(start, nxt))
        prev, cur = start, nxt
        guard = 0
        while guard < 300000:
            guard += 1
            # Stop chain at a graph node (endpoint/junction), but keep first segment.
            if len(path) > 2 and degree.get(cur, 0) != 2:
                break
            cand = [q for q in nbr.get(cur, []) if q != prev]
            if not cand:
                break
            unvisited = [q for q in cand if edge_key(cur, q) not in used_edges]
            if not unvisited:
                break
            qn = _pick_next(prev, cur, unvisited)
            used_edges.add(edge_key(cur, qn))
            path.append(qn)
            prev, cur = cur, qn
        return path

    # 1) Extract branches between graph nodes first (degree != 2).
    node_points = sorted((p for p, d in degree.items() if d != 2), key=_pt_sort_key)
    for s in node_points:
        for q in sorted(nbr.get(s, []), key=_pt_sort_key):
            if edge_key(s, q) in used_edges:
                continue
            path = walk_edge(s, q)
            if len(path) >= 2:
                out.append(path)

    # 2) Extract remaining closed loops (all degree=2 parts without nodes).
    for s in sorted(pixels, key=_pt_sort_key):
        for q in sorted(nbr.get(s, []), key=_pt_sort_key):
            e0 = edge_key(s, q)
            if e0 in used_edges:
                continue
            path = [s, q]
            used_edges.add(e0)
            prev, cur = s, q
            guard = 0
            while guard < 300000:
                guard += 1
                cand = [n for n in nbr.get(cur, []) if n != prev]
                if not cand:
                    break
                unvisited = [n for n in cand if edge_key(cur, n) not in used_edges]
                if not unvisited:
                    break
                nxt = _pick_next(prev, cur, unvisited)
                used_edges.add(edge_key(cur, nxt))
                path.append(nxt)
                prev, cur = cur, nxt
                if cur == s:
                    break
            if len(path) >= 3:
                out.append(path)
    return out


def _postprocess_singleline_text_polylines(
    polylines: List[List[Tuple[float, float]]],
    *,
    font_size: float,
    cyrillic_mode: bool = False,
    logger,
) -> List[List[Tuple[float, float]]]:
    if not polylines:
        return polylines

    def _force_continuous_word_strokes(
        src_polys: List[List[Tuple[float, float]]],
        *,
        max_gap_mm: float,
        max_dy_mm: float,
        collinear_eps_mm: float,
    ) -> List[List[Tuple[float, float]]]:
        src = [p for p in src_polys if len(p) >= 2]
        if len(src) <= 1:
            return src
        ordered = reorder_polylines(src, logger=None)
        out: List[List[Tuple[float, float]]] = []
        cur = list(ordered[0])
        for nxt_raw in ordered[1:]:
            nxt_fwd = list(nxt_raw)
            nxt_rev = list(reversed(nxt_raw))
            end_pt = cur[-1]
            d_fwd = points_distance(end_pt, nxt_fwd[0])
            d_rev = points_distance(end_pt, nxt_rev[0])
            nxt = nxt_rev if d_rev < d_fwd else nxt_fwd
            gap = min(d_fwd, d_rev)
            dy = abs(nxt[0][1] - end_pt[1])
            dx = nxt[0][0] - end_pt[0]
            backward_limit = -max(0.55, 0.25 * float(max_gap_mm))
            # Prefer forward pen flow inside a word. Allow tiny backward hooks only
            # for close fragments (loops/ligatures), but block long reverse bridges.
            flow_ok = (dx >= backward_limit) and (dx >= 0.0 or gap <= 1.10)
            if gap <= float(max_gap_mm) and dy <= float(max_dy_mm) and flow_ok:
                if gap > 1e-9:
                    # Add explicit pen-down connector between letter strokes.
                    cur.append(nxt[0])
                cur.extend(nxt[1:])
                cur = simplify_polyline(cur, collinear_eps=collinear_eps_mm)
                continue
            cur = simplify_polyline(cur, collinear_eps=collinear_eps_mm)
            if len(cur) >= 2:
                out.append(cur)
            cur = list(nxt)
        cur = simplify_polyline(cur, collinear_eps=collinear_eps_mm)
        if len(cur) >= 2:
            out.append(cur)
        return out

    fs = max(6.0, float(font_size))
    if cyrillic_mode:
        # For Cyrillic cursive keep joins conservative: enough to connect letters,
        # but avoid cross-strokes and triangle artifacts from over-merge.
        # Allow slightly coarser collinear cleanup so tiny raster jitter does not
        # explode into thousands of short G1 segments.
        collinear_eps = max(0.0018, min(float(HANDWRITING_SINGLELINE_TTF_COLLINEAR_EPS_MM), fs * 0.0032))
        eps = max(0.06, min(float(HANDWRITING_SINGLELINE_TTF_STITCH_EPS_MM), fs * 0.012))
        gap = max(eps, min(float(HANDWRITING_SINGLELINE_TTF_STITCH_GAP_MM), fs * 0.10))
        # After nearest-end ordering we can allow larger join window safely,
        # so cursive links survive raster skeleton breakup.
        join_gap = min(2.40, max(float(HANDWRITING_SINGLELINE_TTF_WORD_JOIN_GAP_MM), fs * 0.16))
        join_dy = min(1.70, max(float(HANDWRITING_SINGLELINE_TTF_WORD_JOIN_DY_MM), fs * 0.12))
        angle = max(35.0, min(58.0, float(HANDWRITING_SINGLELINE_TTF_STITCH_ANGLE_DEG)))
    else:
        collinear_eps = max(0.004, min(float(HANDWRITING_SINGLELINE_TTF_COLLINEAR_EPS_MM), fs * 0.0028))
        eps = max(0.10, min(float(HANDWRITING_SINGLELINE_TTF_STITCH_EPS_MM), fs * 0.022))
        gap = max(eps, min(float(HANDWRITING_SINGLELINE_TTF_STITCH_GAP_MM), fs * 0.11))
        join_gap = max(0.55, min(float(HANDWRITING_SINGLELINE_TTF_WORD_JOIN_GAP_MM), fs * 0.12))
        join_dy = max(0.35, min(float(HANDWRITING_SINGLELINE_TTF_WORD_JOIN_DY_MM), fs * 0.085))
        angle = max(20.0, float(HANDWRITING_SINGLELINE_TTF_STITCH_ANGLE_DEG))

    stitched = stitch_polylines(
        [p for p in polylines if len(p) >= 2],
        eps=eps,
        logger=None,
        gap_eps=gap,
        angle_tol_deg=angle,
        simplify_collinear_eps=collinear_eps,
    )
    if not stitched:
        return []

    # Preserve local stroke continuity: nearest-end ordering is less likely to
    # produce false cross-links than static y/x sorting for cursive glyphs.
    stitched = reorder_polylines(stitched, logger=None)

    joined = merge_handwriting_word_strokes(
        stitched,
        logger=None,
        join_gap_mm=join_gap,
        join_max_dy_mm=join_dy,
        simplify_collinear_eps=collinear_eps,
    )
    if cyrillic_mode and joined:
        # One pass is often insufficient for fragmented raster-skeleton output.
        # Run a couple of conservative reorder+merge iterations to reconnect
        # cursive pieces that become adjacent only after previous merges.
        for _ in range(2):
            before_n = len(joined)
            joined = reorder_polylines(joined, logger=None)
            joined = merge_handwriting_word_strokes(
                joined,
                logger=None,
                join_gap_mm=min(1.90, join_gap * 1.06),
                join_max_dy_mm=min(1.45, join_dy * 1.08),
                simplify_collinear_eps=collinear_eps,
            )
            if len(joined) >= before_n:
                break
        # Ensure pen-down continuity inside one word token.
        joined = _force_continuous_word_strokes(
            joined,
            max_gap_mm=min(3.60, join_gap * 1.42),
            max_dy_mm=min(2.30, join_dy * 1.36),
            collinear_eps_mm=collinear_eps,
        )

    if cyrillic_mode:
        # Previous limits were too tight for plotter motion (very small segments).
        # Keep enough detail, but prefer longer stable strokes for pen mode.
        smooth_step = max(0.10, min(float(HANDWRITING_SINGLELINE_TTF_SMOOTH_RESAMPLE_MM), fs * 0.034))
        smooth_passes = max(1, min(2, int(HANDWRITING_SINGLELINE_TTF_SMOOTH_PASSES)))
        smooth_rdp = max(0.0, min(float(HANDWRITING_SINGLELINE_TTF_SMOOTH_RDP_MM), fs * 0.0045))
    else:
        smooth_step = max(0.08, min(float(HANDWRITING_SINGLELINE_TTF_SMOOTH_RESAMPLE_MM), fs * 0.018))
        smooth_passes = max(0, int(HANDWRITING_SINGLELINE_TTF_SMOOTH_PASSES))
        smooth_rdp = max(0.0, min(float(HANDWRITING_SINGLELINE_TTF_SMOOTH_RDP_MM), fs * 0.004))
    out: List[List[Tuple[float, float]]] = []
    for poly in joined:
        if len(poly) < 2:
            continue
        cur = list(poly)
        if len(cur) >= 3 and not path_is_closed(cur):
            cur = _resample_polyline_step(cur, smooth_step)
            cur = _smooth_open_polyline(cur, smooth_passes)
            if smooth_rdp > 0.0 and len(cur) >= 3:
                cur = rdp_simplify_polyline(cur, smooth_rdp)
        cur = simplify_polyline(cur, collinear_eps=collinear_eps)
        if len(cur) >= 2:
            out.append(cur)

    if logger:
        logger(
            f"TTF centerline postprocess: {len(polylines)} -> {len(out)} stroke(s) "
            f"(eps={eps:.2f}, gap={gap:.2f}, smooth_step={smooth_step:.2f}, col={collinear_eps:.3f})"
        )
    return out


def _render_singleline_text_polylines_ttf(
    text: str,
    *,
    ttf_path: Path,
    font_size: float,
    baseline_x: float,
    baseline_y: float,
    force_cyrillic_mode: Optional[bool] = None,
    logger,
) -> List[List[Tuple[float, float]]]:
    if Image is None or ImageDraw is None or ImageFont is None or cv2 is None or np is None:
        return []
    if not text:
        return []

    backend = _normalize_singleline_ttf_backend(HANDWRITING_SINGLELINE_TTF_BACKEND)
    if backend in {"autotrace3", "auto"}:
        at_polys = _render_singleline_text_polylines_ttf_autotrace(
            text,
            ttf_path=ttf_path,
            font_size=font_size,
            baseline_x=baseline_x,
            baseline_y=baseline_y,
            force_cyrillic_mode=force_cyrillic_mode,
            logger=logger,
        )
        if at_polys:
            return at_polys
        if backend == "autotrace3":
            logger("TTF centerline method3 warning: autotrace unavailable/failed, fallback to skeleton backend.")

    cyrillic_mode = _text_contains_cyrillic(text) if force_cyrillic_mode is None else bool(force_cyrillic_mode)
    render_scale = max(2.0, float(HANDWRITING_SINGLELINE_TTF_RENDER_SCALE))
    if cyrillic_mode:
        # Higher raster resolution keeps thin handwritten connectors alive
        # before centerline extraction.
        render_scale = max(render_scale, 20.0)
    font_px = max(24, int(round(max(1.0, float(font_size)) * render_scale)))
    font = _get_cached_handwriting_pil_font(ttf_path, font_px)
    if font is None:
        return []

    probe = Image.new("L", (10, 10), 255)
    draw_probe = ImageDraw.Draw(probe)
    try:
        left, top, right, bottom = draw_probe.textbbox((0, 0), text, font=font, anchor="ls")
    except Exception:
        return []

    width = max(1, int(math.ceil(right - left)))
    height = max(1, int(math.ceil(bottom - top)))
    pad = max(12, font_px // 4)
    img = Image.new("L", (width + 2 * pad, height + 2 * pad), 255)
    draw = ImageDraw.Draw(img)
    anchor_x = float(pad - left)
    anchor_y = float(pad - top)
    draw.text((anchor_x, anchor_y), text, fill=0, font=font, anchor="ls")

    arr = np.array(img, dtype=np.uint8)
    if HANDWRITING_SINGLELINE_TTF_USE_OTSU:
        try:
            _, mask = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        except Exception:
            thr = int(max(1, min(254, HANDWRITING_SINGLELINE_TTF_BIN_THRESHOLD)))
            mask = ((arr < thr).astype(np.uint8)) * 255
    else:
        thr = int(max(1, min(254, HANDWRITING_SINGLELINE_TTF_BIN_THRESHOLD)))
        mask = ((arr < thr).astype(np.uint8)) * 255
    if np.count_nonzero(mask) <= 0:
        return []

    try:
        # Bridge tiny anti-aliased gaps before skeletonization.
        if cyrillic_mode:
            # Handwritten Cyrillic joins are mostly horizontal.
            # Horizontal close bridges pen transitions with fewer diagonal artifacts.
            kernel = np.ones((1, 3), dtype=np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        else:
            kernel = np.ones((2, 2), dtype=np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    except Exception:
        pass

    skel = _skeletonize_binary(mask)
    if np.count_nonzero(skel) <= 0:
        return []

    try:
        min_comp = int(max(1, HANDWRITING_SINGLELINE_TTF_MIN_COMPONENT_PX))
        if cyrillic_mode:
            # Drop single-pixel dust while preserving letter joints.
            min_comp = max(2, min_comp)
        if min_comp > 1:
            comp = (skel > 0).astype(np.uint8)
            num, labels, stats, _ = cv2.connectedComponentsWithStats(comp, connectivity=8)
            cleaned = np.zeros_like(skel)
            for i in range(1, int(num)):
                if int(stats[i, cv2.CC_STAT_AREA]) >= min_comp:
                    cleaned[labels == i] = 255
            skel = cleaned
    except Exception:
        pass

    spur_prune = int(max(0, HANDWRITING_SINGLELINE_TTF_SPUR_PRUNE_PX))
    if cyrillic_mode:
        # Keep joins, but remove tiny one-pixel hooks from thinning noise.
        spur_prune = max(1, min(2, spur_prune))
    skel = _prune_skeleton_spurs(skel, spur_prune)
    pix_paths = _trace_skeleton_paths_greedy(skel)
    if not pix_paths:
        return []

    if cyrillic_mode:
        # Keep very short connectors (otherwise letters look dotted).
        min_path_units = max(0.08, float(font_size) * 0.008)
        rdp_eps = max(0.0010, min(0.006, float(font_size) * 0.00045))
    else:
        min_path_units = max(0.20, float(font_size) * 0.03)
        rdp_eps = max(0.004, min(0.020, float(font_size) * 0.0012))
    out: List[List[Tuple[float, float]]] = []
    for pix in pix_paths:
        if len(pix) < 2:
            continue
        poly = [
            (
                baseline_x + ((float(x) - anchor_x) / render_scale),
                baseline_y + ((float(y) - anchor_y) / render_scale),
            )
            for x, y in pix
        ]
        if len(poly) < 2:
            continue
        poly = simplify_polyline(poly, eps=1e-6)
        poly = rdp_simplify_polyline(poly, eps=rdp_eps)
        if len(poly) < 2:
            continue
        if polyline_length(poly) < min_path_units:
            continue
        out.append(poly)

    out = _postprocess_singleline_text_polylines(
        out,
        font_size=font_size,
        cyrillic_mode=cyrillic_mode,
        logger=logger,
    )
    if out:
        txt_snippet = _safe_log_text(text[:28])
        logger(
            f"TTF centerline text: '{txt_snippet}' -> {len(out)} stroke(s), "
            f"font={ttf_path.name}, size={font_size:.2f}"
        )
    return out


def _render_singleline_text_line_ttf(
    line_text: str,
    *,
    ttf_path: Path,
    font_size: float,
    baseline_x: float,
    baseline_y: float,
    logger,
) -> List[List[Tuple[float, float]]]:
    text = line_text or ""
    if not text:
        return []
    backend = _normalize_singleline_ttf_backend(HANDWRITING_SINGLELINE_TTF_BACKEND)
    line_has_cyrillic = _text_contains_cyrillic(text)
    text_norm = _normalize_handwriting_text_token(text)
    # Method3 (autotrace centerline) works best on full line raster,
    # preserving inter-letter continuity and reducing token boundary artifacts.
    if backend == "autotrace3":
        return _render_singleline_text_polylines_ttf(
            text_norm,
            ttf_path=ttf_path,
            font_size=font_size,
            baseline_x=baseline_x,
            baseline_y=baseline_y,
            force_cyrillic_mode=line_has_cyrillic,
            logger=logger,
        )
    tokens = _split_text_tokens_keep_spaces(text)
    if len(tokens) <= 1:
        return _render_singleline_text_polylines_ttf(
            text_norm,
            ttf_path=ttf_path,
            font_size=font_size,
            baseline_x=baseline_x,
            baseline_y=baseline_y,
            force_cyrillic_mode=line_has_cyrillic,
            logger=logger,
        )

    render_scale = max(2.0, float(HANDWRITING_SINGLELINE_TTF_RENDER_SCALE))
    font_px = max(24, int(round(max(1.0, float(font_size)) * render_scale)))
    default_font = _get_cached_handwriting_pil_font(ttf_path, font_px)
    if default_font is None:
        return _render_singleline_text_polylines_ttf(
            text,
            ttf_path=ttf_path,
            font_size=font_size,
            baseline_x=baseline_x,
            baseline_y=baseline_y,
            force_cyrillic_mode=line_has_cyrillic,
            logger=logger,
        )

    latin_ttf_path: Optional[Path] = None
    if line_has_cyrillic and HANDWRITING_SINGLELINE_TTF_MIXED_USE_LATIN_FALLBACK:
        latin_name = normalize_handwriting_font_name(HANDWRITING_FONT_FAMILY)
        resolved_latin = _resolve_handwriting_ttf_path(latin_name)
        if resolved_latin is not None:
            latin_ttf_path = resolved_latin

    cursor_x = float(baseline_x)
    out: List[List[Tuple[float, float]]] = []
    for token in tokens:
        token_norm = _normalize_handwriting_text_token(token)
        token_has_cyr = _text_contains_cyrillic(token_norm)
        token_has_mathish = bool(re.search(r"[0-9=+\-*/^()]", token_norm or ""))
        token_ttf_path = ttf_path
        if (
            line_has_cyrillic
            and latin_ttf_path is not None
            and not token_has_cyr
        ):
            token_ttf_path = latin_ttf_path
        token_font = _get_cached_handwriting_pil_font(token_ttf_path, font_px) or default_font
        adv_mm = _measure_text_advance_mm(token_norm, font=token_font, render_scale=render_scale)
        if token_norm.strip():
            token_polys = _render_singleline_text_polylines_ttf(
                token_norm,
                ttf_path=token_ttf_path,
                font_size=font_size,
                baseline_x=cursor_x,
                baseline_y=baseline_y,
                # Keep math fragments out of Cyrillic-join mode to avoid
                # over-merged symbols in formulas/equations.
                force_cyrillic_mode=token_has_cyr,
                logger=logger,
            )
            out.extend(token_polys)
        cursor_x += adv_mm
    return out


def replace_svg_text_with_singleline_ttf(svg_path: Path, font_name: str, logger) -> int:
    if not HANDWRITING_SINGLELINE_TTF_ENABLED:
        return 0
    if Image is None or ImageDraw is None or ImageFont is None or cv2 is None or np is None:
        return 0
    ttf_path = _resolve_handwriting_ttf_path(font_name)
    if ttf_path is None:
        logger(f"TTF centerline text: no usable font found for '{font_name}'.")
        return 0

    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
    except Exception as exc:
        logger(f"TTF centerline replace failed: {exc}")
        return 0

    changed = 0
    total_paths = 0
    native_row_ids = _collect_native_row_text_node_ids(root)

    def _merge_inherited_text_style(parent_style: dict, node: ET.Element) -> dict:
        return _merge_svg_text_style(parent_style, node)

    def build_path_for_text_node(node: ET.Element, inherited_style: dict) -> Optional[ET.Element]:
        nonlocal total_paths
        if id(node) in native_row_ids:
            _sanitize_svg_text_node_for_vector(node)
            return None
        style_base = _merge_inherited_text_style(inherited_style, node)
        if not _svg_text_node_is_visible(style_base, node):
            return None

        node_x_list = _parse_svg_number_list(node.attrib.get("x"))
        node_y_list = _parse_svg_number_list(node.attrib.get("y"))
        base_x = node_x_list[0] if node_x_list else 0.0
        base_y = node_y_list[0] if node_y_list else 0.0
        node_transform = node.attrib.get("transform", "").strip()

        runs: List[Tuple[str, float, float, dict, str]] = []
        tspans = [c for c in list(node) if tag_name(c.tag).lower() == "tspan"]
        if tspans:
            lead = (node.text or "").strip()
            if lead:
                runs.append((lead, base_x, base_y, dict(style_base), node_transform))
            cursor_x = float(base_x)
            cursor_y = float(base_y)
            has_lead = bool(lead)
            for ts_idx, ts in enumerate(tspans):
                text = _extract_svg_text_plain(ts)
                if not text:
                    continue
                run_style = dict(style_base)
                run_style.update(_read_style_dict_preserve(ts.attrib.get("style")))
                for key in (
                    "fill",
                    "stroke",
                    "font-size",
                    "font-family",
                    "-inkscape-font-specification",
                    "display",
                    "visibility",
                    "opacity",
                    "fill-opacity",
                    "stroke-opacity",
                ):
                    if key in ts.attrib:
                        run_style[key] = str(ts.attrib.get(key, "")).strip()
                run_font_size = _parse_svg_number(
                    run_style.get("font-size"),
                    default=_parse_svg_number(style_base.get("font-size"), default=12.0),
                )
                x_list = _parse_svg_number_list(ts.attrib.get("x"))
                y_list = _parse_svg_number_list(ts.attrib.get("y"))
                dx_list = _parse_svg_number_list(ts.attrib.get("dx"))
                dy_list = _parse_svg_number_list(ts.attrib.get("dy"))
                if x_list:
                    x0 = x_list[0]
                elif dx_list:
                    x0 = cursor_x + dx_list[0]
                else:
                    x0 = cursor_x
                if y_list:
                    y0 = y_list[0]
                elif dy_list:
                    dy0 = _adjust_handwriting_tspan_dy(
                        dy_list[0],
                        font_size=run_font_size,
                        text=text,
                        is_first_visible_line=(ts_idx == 0 and not has_lead),
                    )
                    y0 = cursor_y + dy0
                else:
                    y0 = cursor_y
                cursor_x, cursor_y = float(x0), float(y0)
                ts_transform = ts.attrib.get("transform", "").strip()
                run_transform = " ".join(part for part in (node_transform, ts_transform) if part)
                runs.append((text, x0, y0, run_style, run_transform))
        else:
            text = _extract_svg_text_plain(node)
            if text:
                runs.append((text, base_x, base_y, dict(style_base), node_transform))

        if not runs:
            return None
        combined_text = " ".join(str(run[0]) for run in runs if str(run[0]).strip())
        if (
            _text_prefers_native_vector(combined_text)
            or any(_style_prefers_native_vector(run[3]) for run in runs)
        ):
            _sanitize_svg_text_node_for_vector(node)
            return None

        ns = ""
        if "}" in node.tag:
            ns = node.tag.split("}")[0] + "}"
        group_el = ET.Element(f"{ns}g")

        for text, x0, y0, style, run_transform in runs:
            if _style_prefers_native_vector(style):
                # Preserve complex math/symbol runs in native vector form.
                continue
            if not _svg_text_node_is_visible(style):
                continue
            font_size = _parse_svg_number(style.get("font-size"), default=12.0)
            if font_size <= 0.0:
                font_size = 12.0
            stroke_color = _pick_svg_text_stroke_color(style)
            if not stroke_color:
                continue
            stroke_width = max(
                float(HANDWRITING_SINGLELINE_TTF_PREVIEW_STROKE_MIN_MM),
                font_size * float(HANDWRITING_SINGLELINE_TTF_PREVIEW_STROKE_SCALE),
            )

            lines = [ln for ln in text.split("\n") if ln != ""]
            if not lines:
                continue
            line_step = max(font_size * 1.34, font_size + 1.0)
            d_parts: List[str] = []
            for li, line_text in enumerate(lines):
                baseline_y = y0 + (li * line_step)
                polylines = _render_singleline_text_line_ttf(
                    line_text,
                    ttf_path=ttf_path,
                    font_size=font_size,
                    baseline_x=x0,
                    baseline_y=baseline_y,
                    logger=logger,
                )
                for poly in polylines:
                    if len(poly) < 2:
                        continue
                    cmd = [f"M {poly[0][0]:.4f} {poly[0][1]:.4f}"]
                    for px, py in poly[1:]:
                        cmd.append(f"L {px:.4f} {py:.4f}")
                    d_parts.append(" ".join(cmd))
            if not d_parts:
                continue

            path_el = ET.Element(f"{ns}path")
            path_el.set("d", " ".join(d_parts))
            path_el.set("fill", "none")
            path_el.set("stroke", stroke_color)
            path_el.set("stroke-width", f"{stroke_width:.4f}")
            path_el.set("stroke-linecap", "round")
            path_el.set("stroke-linejoin", "round")
            if run_transform:
                path_el.set("transform", run_transform)
            group_el.append(path_el)
            total_paths += len(d_parts)

        if len(list(group_el)) <= 0:
            return None
        if len(list(group_el)) == 1:
            return list(group_el)[0]
        return group_el

    def walk(parent: ET.Element, inherited_style: dict) -> None:
        nonlocal changed
        children = list(parent)
        for idx, child in enumerate(children):
            child_style = _merge_inherited_text_style(inherited_style, child)
            if tag_name(child.tag).lower() in TEXT_NODE_TAGS:
                repl = build_path_for_text_node(child, inherited_style)
                if repl is not None:
                    parent.remove(child)
                    parent.insert(idx, repl)
                    changed += 1
                continue
            walk(child, child_style)

    walk(root, {})
    if changed <= 0:
        return 0

    try:
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        logger(f"TTF centerline save failed: {exc}")
        return 0
    logger(
        f"Handwriting TTF centerline mode: replaced {changed} text node(s), "
        f"generated {total_paths} stroke path(s) using '{ttf_path.name}'."
    )
    return changed


def apply_handwriting_font(svg_path: Path, font_name: str, logger) -> int:
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
    except Exception as exc:
        logger(f"Handwriting font apply failed: {exc}")
        return 0

    target_font = normalize_handwriting_font_name(font_name)
    changed = 0
    native_row_ids = _collect_native_row_text_node_ids(root)

    def walk(node: ET.Element, inherited_style: dict) -> None:
        nonlocal changed
        cur_style = _merge_svg_text_style(inherited_style, node)
        if tag_name(node.tag).lower() in TEXT_NODE_TAGS:
            txt = _extract_svg_text_plain(node)
            if not _svg_text_node_is_visible(cur_style, node):
                for child in list(node):
                    walk(child, cur_style)
                return
            if (id(node) not in native_row_ids) and not (_text_prefers_native_vector(txt) or _style_prefers_native_vector(cur_style)):
                node_style = _read_style_dict_preserve(node.attrib.get("style"))
                node_style["font-family"] = f"'{target_font}'"
                node_style["-inkscape-font-specification"] = target_font
                node.attrib["style"] = _style_dict_to_string(node_style)
                node.attrib["font-family"] = target_font
                changed += 1
            else:
                _sanitize_svg_text_node_for_vector(node)
        for child in list(node):
            walk(child, cur_style)

    walk(root, {})

    if changed <= 0:
        return 0

    try:
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        logger(f"Handwriting font save failed: {exc}")
        return 0

    logger(f"Handwriting mode: applied font '{target_font}' to {changed} text node(s).")
    return changed


def _parse_svg_number(value: Optional[str], default: float = 0.0) -> float:
    if value is None:
        return default
    s = str(value).strip()
    if not s:
        return default
    token = s.replace(",", " ").split()[0]
    token = re.sub(r"[^0-9eE+\-\.]", "", token)
    try:
        return float(token)
    except Exception:
        return default


def _parse_svg_number_list(value: Optional[str]) -> List[float]:
    if value is None:
        return []
    src = str(value).replace(",", " ").strip()
    if not src:
        return []
    out: List[float] = []
    for tok in src.split():
        t = re.sub(r"[^0-9eE+\-\.]", "", tok)
        if not t:
            continue
        try:
            out.append(float(t))
        except Exception:
            continue
    return out


def _extract_svg_text_plain(node: ET.Element) -> str:
    raw = _strip_unpaired_surrogates("".join(node.itertext()), replacement=" ")
    if not raw:
        return ""

    def _repair_cp1251_single_byte(text: str) -> str:
        # Some PDF/SVG exports keep Cyrillic as single-byte cp1251 chars rendered
        # as Latin-1 (e.g. Е -> Å, З -> Ç). Repair those codepoints per-char.
        out_chars: List[str] = []
        changed = False
        for ch in text:
            code = ord(ch)
            if CYRILLIC_TEXT_RE.search(ch):
                out_chars.append(ch)
                continue
            if code in {0xA8, 0xB8} or (0xC0 <= code <= 0xFF):
                repaired = ""
                try:
                    repaired = bytes([code]).decode("cp1251")
                except Exception:
                    repaired = ""
                if repaired and len(repaired) == 1 and CYRILLIC_TEXT_RE.search(repaired):
                    out_chars.append(repaired)
                    changed = True
                    continue
            out_chars.append(ch)
        if not changed:
            return text
        return "".join(out_chars)

    if not CYRILLIC_TEXT_RE.search(raw):
        raw = _repair_cp1251_single_byte(raw)
    if not CYRILLIC_TEXT_RE.search(raw):
        if any(tok in raw for tok in ("Р", "С", "Ð", "Ñ")):
            for src_enc in ("cp1251", "latin1"):
                try:
                    repaired = raw.encode(src_enc, errors="strict").decode("utf-8", errors="strict")
                except Exception:
                    continue
                if CYRILLIC_TEXT_RE.search(repaired):
                    raw = repaired
                    break
    # Preserve explicit line breaks while normalizing excessive spaces.
    lines = []
    for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        lines.append(re.sub(r"[ \t]+", " ", ln).strip())
    return "\n".join(ln for ln in lines if ln)


def _text_contains_cyrillic(text: str) -> bool:
    return bool(CYRILLIC_TEXT_RE.search(text or ""))


def svg_has_cyrillic_text_nodes(svg_path: Path) -> bool:
    try:
        root = ET.parse(svg_path).getroot()
    except Exception:
        return False
    for node in root.iter():
        if tag_name(node.tag).lower() not in TEXT_NODE_TAGS:
            continue
        if _text_contains_cyrillic("".join(node.itertext())):
            return True
    return False


def _analyze_svg_text_profile(svg_path: Path) -> Dict[str, object]:
    """Estimate text style to choose RU handwriting pipeline.

    Technical drawings usually contain many short and numeric tokens.
    Paragraph-like notes contain more medium/long words.
    """
    profile: Dict[str, object] = {
        "tokens": 0,
        "short_ratio": 0.0,
        "digit_ratio": 0.0,
        "long_ratio": 0.0,
        "technical_like": False,
    }
    try:
        root = ET.parse(svg_path).getroot()
    except Exception:
        return profile

    tokens: List[str] = []
    token_re = re.compile(r"[0-9A-Za-z\u0400-\u04FFЁё]+")
    for node in root.iter():
        if tag_name(node.tag).lower() not in TEXT_NODE_TAGS:
            continue
        text = _extract_svg_text_plain(node)
        if not text:
            continue
        for tok in token_re.findall(text):
            t = tok.strip()
            if t:
                tokens.append(t)

    total = len(tokens)
    if total <= 0:
        return profile

    short = sum(1 for t in tokens if len(t) <= 3)
    long = sum(1 for t in tokens if len(t) >= 6)
    digit = sum(1 for t in tokens if re.fullmatch(r"\d+", t))

    short_ratio = short / float(total)
    long_ratio = long / float(total)
    digit_ratio = digit / float(total)
    technical_like = (
        (total >= 18 and short_ratio >= 0.62 and (digit_ratio >= 0.18 or long_ratio <= 0.18))
        or (total >= 12 and short_ratio >= 0.72 and long_ratio <= 0.12)
    )

    profile["tokens"] = total
    profile["short_ratio"] = short_ratio
    profile["digit_ratio"] = digit_ratio
    profile["long_ratio"] = long_ratio
    profile["technical_like"] = technical_like
    return profile


def _pick_hershey_font_name(font_name: str) -> str:
    requested = (font_name or "").strip().lower()
    if not requested:
        return HANDWRITING_STROKE_FONT_NAME
    # Keep mapping simple and deterministic.
    if any(k in requested for k in ("script", "cursive", "hand")):
        return "cursive"
    if any(k in requested for k in ("mono", "console", "type")):
        return "futural"
    return HANDWRITING_STROKE_FONT_NAME


def _pick_hershey_font_name_for_text(font_name: str, text: str) -> str:
    if _text_contains_cyrillic(text):
        requested = (font_name or "").strip().lower()
        default_cyr = (HANDWRITING_STROKE_CYR_FONT_NAME or "cyrilc_1").strip().lower()
        if any(k in requested for k in ("mono", "console", "type")):
            # Technical/monospace intent -> simpler Cyrillic stroke set.
            return "cyrillic"
        if "cyr" in requested:
            if any(k in requested for k in ("1", "script", "cursive", "hand")):
                return "cyrilc_1"
            return "cyrillic"
        if any(k in requested for k in ("script", "cursive", "hand")):
            return default_cyr
        return default_cyr
    return _pick_hershey_font_name(font_name)


def _hershey_segments_to_polylines(
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    tol: float = 1e-9,
) -> List[List[Tuple[float, float]]]:
    out: List[List[Tuple[float, float]]] = []
    cur: List[Tuple[float, float]] = []

    def _same(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

    for seg in segments:
        if not seg or len(seg) < 2:
            continue
        p1 = (float(seg[0][0]), float(seg[0][1]))
        p2 = (float(seg[1][0]), float(seg[1][1]))
        if not cur:
            cur = [p1, p2]
            continue
        if _same(cur[-1], p1):
            cur.append(p2)
            continue
        if _same(cur[-1], p2):
            cur.append(p1)
            continue
        if len(cur) >= 2:
            out.append(cur)
        cur = [p1, p2]

    if len(cur) >= 2:
        out.append(cur)
    return out


def _postprocess_hershey_text_polylines(
    polylines: List[List[Tuple[float, float]]],
    *,
    font_size: float,
    has_cyrillic: bool,
    logger=None,
) -> List[List[Tuple[float, float]]]:
    # "Second method": keep Hershey centerlines, then average/smooth contour
    # to reduce tiny deterministic segments before final G-code conversion.
    if not HANDWRITING_HERSHEY_POSTPROCESS_ENABLED:
        return polylines
    if not polylines:
        return polylines

    fs = max(1.0, float(font_size))
    collinear_eps = max(
        0.003,
        min(float(HANDWRITING_HERSHEY_COLLINEAR_EPS_MM), fs * (0.0022 if has_cyrillic else 0.0019)),
    )
    stitch_eps = max(
        0.06,
        min(float(HANDWRITING_HERSHEY_STITCH_EPS_MM), fs * (0.012 if has_cyrillic else 0.010)),
    )
    stitch_gap = max(
        stitch_eps,
        min(float(HANDWRITING_HERSHEY_STITCH_GAP_MM), fs * (0.068 if has_cyrillic else 0.056)),
    )
    stitch_angle = max(20.0, min(88.0, float(HANDWRITING_HERSHEY_STITCH_ANGLE_DEG)))
    join_gap = max(
        0.32,
        min(float(HANDWRITING_HERSHEY_JOIN_GAP_MM), fs * (0.064 if has_cyrillic else 0.050)),
    )
    join_dy = max(
        0.18,
        min(float(HANDWRITING_HERSHEY_JOIN_DY_MM), fs * (0.042 if has_cyrillic else 0.035)),
    )
    smooth_step = max(
        0.06,
        min(float(HANDWRITING_HERSHEY_SMOOTH_RESAMPLE_MM), fs * (0.010 if has_cyrillic else 0.0088)),
    )
    smooth_passes = max(0, int(HANDWRITING_HERSHEY_SMOOTH_PASSES))
    smooth_rdp = max(
        0.0,
        min(float(HANDWRITING_HERSHEY_SMOOTH_RDP_MM), fs * (0.0012 if has_cyrillic else 0.0010)),
    )

    base: List[List[Tuple[float, float]]] = []
    for poly in polylines:
        if len(poly) < 2:
            continue
        cur = simplify_polyline(list(poly), collinear_eps=collinear_eps)
        if len(cur) >= 2:
            base.append(cur)
    if not base:
        return []

    stitched = stitch_polylines(
        base,
        stitch_eps,
        logger=None,
        gap_eps=stitch_gap,
        angle_tol_deg=stitch_angle,
        simplify_collinear_eps=collinear_eps,
    )
    if not stitched:
        return []

    joined = merge_handwriting_word_strokes(
        stitched,
        logger=None,
        join_gap_mm=join_gap,
        join_max_dy_mm=join_dy,
        simplify_collinear_eps=collinear_eps,
    )
    if not joined:
        return []

    out: List[List[Tuple[float, float]]] = []
    smooth_hits = 0
    for poly in joined:
        cur = list(poly)
        if len(cur) >= 3:
            cur = _resample_polyline_step(cur, smooth_step)
            cur = _smooth_open_polyline(cur, smooth_passes)
            if smooth_rdp > 0.0 and len(cur) >= 3:
                cur = rdp_simplify_polyline(cur, smooth_rdp)
        cur = simplify_polyline(cur, collinear_eps=collinear_eps)
        if len(cur) >= 2:
            out.append(cur)
            if len(cur) != len(poly):
                smooth_hits += 1

    if logger and smooth_hits > 0:
        logger(
            f"Hershey contour averaging: {smooth_hits}/{len(joined)} stroke(s) "
            f"(step={smooth_step:.2f}, stitch={stitch_eps:.2f}/{stitch_gap:.2f}, join={join_gap:.2f})."
        )
    return out if out else joined


def replace_svg_text_with_svg_stroke_fonts(svg_path: Path, font_name: str, logger) -> int:
    if not HANDWRITING_STROKE_SVG_FONT_ENABLED:
        return 0

    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
    except Exception as exc:
        logger(f"SVG stroke text replace failed: {exc}")
        return 0

    changed = 0
    total_paths = 0
    total_glyphs = 0
    fonts_used: set[str] = set()
    native_row_ids = _collect_native_row_text_node_ids(root)

    def _merge_inherited_text_style(parent_style: dict, node: ET.Element) -> dict:
        return _merge_svg_text_style(parent_style, node)

    def _glyph_lookup(ch: str, chain_data: List[SvgStrokeFontData]) -> Tuple[Optional[SvgStrokeFontData], Optional[SvgStrokeGlyph]]:
        for fd in chain_data:
            g = fd.glyphs.get(ch)
            if g is not None:
                return fd, g
        return None, None

    def build_path_for_text_node(node: ET.Element, inherited_style: dict) -> Optional[ET.Element]:
        nonlocal total_paths, total_glyphs
        if id(node) in native_row_ids:
            _sanitize_svg_text_node_for_vector(node)
            return None
        style_base = _merge_inherited_text_style(inherited_style, node)
        if not _svg_text_node_is_visible(style_base, node):
            return None

        node_x_list = _parse_svg_number_list(node.attrib.get("x"))
        node_y_list = _parse_svg_number_list(node.attrib.get("y"))
        base_x = node_x_list[0] if node_x_list else 0.0
        base_y = node_y_list[0] if node_y_list else 0.0
        node_transform = node.attrib.get("transform", "").strip()

        runs: List[Tuple[str, float, float, dict, str]] = []
        tspans = [c for c in list(node) if tag_name(c.tag).lower() == "tspan"]
        if tspans:
            lead = (node.text or "").strip()
            if lead:
                runs.append((lead, base_x, base_y, dict(style_base), node_transform))
            cursor_x = float(base_x)
            cursor_y = float(base_y)
            has_lead = bool(lead)
            for ts_idx, ts in enumerate(tspans):
                text = _extract_svg_text_plain(ts)
                if not text:
                    continue
                run_style = dict(style_base)
                run_style.update(_read_style_dict_preserve(ts.attrib.get("style")))
                for key in (
                    "fill",
                    "stroke",
                    "font-size",
                    "font-family",
                    "-inkscape-font-specification",
                    "display",
                    "visibility",
                    "opacity",
                    "fill-opacity",
                    "stroke-opacity",
                ):
                    if key in ts.attrib:
                        run_style[key] = str(ts.attrib.get(key, "")).strip()
                run_font_size = _parse_svg_number(
                    run_style.get("font-size"),
                    default=_parse_svg_number(style_base.get("font-size"), default=12.0),
                )
                x_list = _parse_svg_number_list(ts.attrib.get("x"))
                y_list = _parse_svg_number_list(ts.attrib.get("y"))
                dx_list = _parse_svg_number_list(ts.attrib.get("dx"))
                dy_list = _parse_svg_number_list(ts.attrib.get("dy"))
                if x_list:
                    x0 = x_list[0]
                elif dx_list:
                    x0 = cursor_x + dx_list[0]
                else:
                    x0 = cursor_x
                if y_list:
                    y0 = y_list[0]
                elif dy_list:
                    dy0 = _adjust_handwriting_tspan_dy(
                        dy_list[0],
                        font_size=run_font_size,
                        text=text,
                        is_first_visible_line=(ts_idx == 0 and not has_lead),
                    )
                    y0 = cursor_y + dy0
                else:
                    y0 = cursor_y
                cursor_x, cursor_y = float(x0), float(y0)
                ts_transform = ts.attrib.get("transform", "").strip()
                run_transform = " ".join(part for part in (node_transform, ts_transform) if part)
                runs.append((text, x0, y0, run_style, run_transform))
        else:
            text = _extract_svg_text_plain(node)
            if text:
                runs.append((text, base_x, base_y, dict(style_base), node_transform))

        if not runs:
            return None
        combined_text = " ".join(str(run[0]) for run in runs if str(run[0]).strip())
        if (
            _text_prefers_native_vector(combined_text)
            or any(_style_prefers_native_vector(run[3]) for run in runs)
        ):
            _sanitize_svg_text_node_for_vector(node)
            return None

        ns = ""
        if "}" in node.tag:
            ns = node.tag.split("}")[0] + "}"
        out_group = ET.Element(f"{ns}g")

        for text, x0, y0, style, run_transform in runs:
            if _style_prefers_native_vector(style):
                continue
            if not _svg_text_node_is_visible(style):
                continue
            chain_names = _pick_svg_stroke_font_chain(font_name, text)
            chain_data: List[SvgStrokeFontData] = []
            for name in chain_names:
                fd = _load_svg_stroke_font_data(name, logger)
                if fd is not None:
                    chain_data.append(fd)
            if not chain_data:
                continue

            font_size = _parse_svg_number(style.get("font-size"), default=12.0)
            if font_size <= 0.0:
                font_size = 12.0

            stroke_color = _pick_svg_text_stroke_color(style)
            if not stroke_color:
                continue

            stroke_width = max(0.10, font_size * 0.018)
            line_step = max(font_size * 1.34, font_size + 1.0)
            lines = [ln for ln in text.split("\n") if ln != ""]
            if not lines:
                continue

            run_group = ET.Element(f"{ns}g")
            if run_transform:
                run_group.set("transform", run_transform)

            used_any = False
            for li, line_text in enumerate(lines):
                cursor_x = float(x0)
                baseline_y = float(y0 + (li * line_step))
                for ch in line_text:
                    if ch == "\u00a0":
                        ch = " "
                    if ch == "\t":
                        fd0 = chain_data[0]
                        cursor_x += (fd0.default_adv * (font_size / max(1e-9, fd0.units_per_em))) * 2.40
                        continue

                    fd, glyph = _glyph_lookup(ch, chain_data)
                    if fd is None or glyph is None:
                        fd0 = chain_data[0]
                        cursor_x += (fd0.default_adv * (font_size / max(1e-9, fd0.units_per_em))) * 0.60
                        continue

                    scale = float(font_size) / max(1e-9, fd.units_per_em)
                    adv = glyph.adv if glyph.adv > 0.0 else fd.default_adv
                    if not glyph.d:
                        cursor_x += adv * scale
                        continue

                    path_el = ET.Element(f"{ns}path")
                    path_el.set("d", glyph.d)
                    path_el.set("fill", "none")
                    path_el.set("stroke", stroke_color)
                    path_el.set("stroke-width", f"{stroke_width:.4f}")
                    path_el.set("stroke-linecap", "round")
                    path_el.set("stroke-linejoin", "round")
                    path_el.set(
                        "transform",
                        f"matrix({scale:.6f} 0 0 {-scale:.6f} {cursor_x:.4f} {baseline_y:.4f})",
                    )
                    run_group.append(path_el)
                    fonts_used.add(fd.name)
                    total_paths += 1
                    total_glyphs += 1
                    used_any = True
                    cursor_x += adv * scale

            if used_any:
                out_group.append(run_group)

        children = list(out_group)
        if not children:
            return None
        if len(children) == 1:
            return children[0]
        return out_group

    def walk(parent: ET.Element, inherited_style: dict) -> None:
        nonlocal changed
        children = list(parent)
        for idx, child in enumerate(children):
            child_style = _merge_inherited_text_style(inherited_style, child)
            if tag_name(child.tag).lower() in TEXT_NODE_TAGS:
                repl = build_path_for_text_node(child, inherited_style)
                if repl is not None:
                    parent.remove(child)
                    parent.insert(idx, repl)
                    changed += 1
                continue
            walk(child, child_style)

    walk(root, {})
    if changed <= 0:
        return 0

    try:
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        logger(f"SVG stroke text save failed: {exc}")
        return 0

    used = ", ".join(sorted(fonts_used)) if fonts_used else "-"
    logger(
        f"Handwriting SVG-stroke mode: replaced {changed} text node(s), "
        f"glyphs={total_glyphs}, paths={total_paths}, fonts={used}."
    )
    return changed


def replace_svg_text_with_hershey_strokes(svg_path: Path, font_name: str, logger) -> int:
    if not HANDWRITING_STROKE_FONT_ENABLED:
        return 0
    if HANDWRITING_STROKE_SVG_FONT_ENABLED and not HANDWRITING_HERSHEY_CORE_FIRST:
        svg_stroke_changed = replace_svg_text_with_svg_stroke_fonts(svg_path, font_name, logger)
        if svg_stroke_changed > 0:
            return svg_stroke_changed
    if HersheyFonts is None:
        if HANDWRITING_STROKE_SVG_FONT_ENABLED:
            logger("Hershey module unavailable, fallback to SVG stroke-font pipeline.")
            return replace_svg_text_with_svg_stroke_fonts(svg_path, font_name, logger)
        logger("Handwriting stroke font disabled: HersheyFonts module not available.")
        return 0

    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
    except Exception as exc:
        logger(f"Hershey text replace failed: {exc}")
        return 0

    font_cache: dict[str, HersheyFonts] = {}

    def get_font(name: str) -> Optional[HersheyFonts]:
        key = (name or "").strip().lower()
        if not key:
            key = HANDWRITING_STROKE_FONT_NAME
        if key in font_cache:
            return font_cache[key]
        f = HersheyFonts()
        try:
            f.load_default_font(key)
            font_cache[key] = f
            return f
        except Exception:
            pass
        for fallback in [HANDWRITING_STROKE_CYR_FONT_NAME, HANDWRITING_STROKE_FONT_NAME, "cyrillic", "cursive", "futural"]:
            fb = (fallback or "").strip().lower()
            if not fb:
                continue
            try:
                f = HersheyFonts()
                f.load_default_font(fb)
                font_cache[key] = f
                return f
            except Exception:
                continue
        return None

    default_font_name = _pick_hershey_font_name(font_name)
    if get_font(default_font_name) is None:
        logger("Hershey font load failed: no suitable default font.")
        return 0

    fonts_used: set[str] = set()
    changed = 0
    native_row_ids = _collect_native_row_text_node_ids(root)

    def build_path_for_text_node(node: ET.Element) -> Optional[ET.Element]:
        if id(node) in native_row_ids:
            _sanitize_svg_text_node_for_vector(node)
            return None
        style_base = _read_style_dict_preserve(node.attrib.get("style"))
        for key in (
            "fill",
            "stroke",
            "font-size",
            "font-family",
            "-inkscape-font-specification",
            "display",
            "visibility",
            "opacity",
            "fill-opacity",
            "stroke-opacity",
        ):
            if key in node.attrib:
                style_base[key] = str(node.attrib.get(key, "")).strip()
        if not _svg_text_node_is_visible(style_base, node):
            return None

        node_x_list = _parse_svg_number_list(node.attrib.get("x"))
        node_y_list = _parse_svg_number_list(node.attrib.get("y"))
        base_x = node_x_list[0] if node_x_list else 0.0
        base_y = node_y_list[0] if node_y_list else 0.0
        node_transform = node.attrib.get("transform", "").strip()

        # Collect runs with per-run coordinates (tspan-aware).
        runs: List[Tuple[str, float, float, dict, str, List[float]]] = []
        tspans = [c for c in list(node) if tag_name(c.tag).lower() == "tspan"]
        if tspans:
            lead = (node.text or "").strip()
            if lead:
                runs.append((lead, base_x, base_y, dict(style_base), node_transform, list(node_x_list)))
            cursor_x = float(base_x)
            cursor_y = float(base_y)
            has_lead = bool(lead)
            for ts_idx, ts in enumerate(tspans):
                text = _extract_svg_text_plain(ts)
                if not text:
                    continue
                run_style = dict(style_base)
                run_style.update(_read_style_dict_preserve(ts.attrib.get("style")))
                for key in (
                    "fill",
                    "stroke",
                    "font-size",
                    "font-family",
                    "-inkscape-font-specification",
                    "display",
                    "visibility",
                    "opacity",
                    "fill-opacity",
                    "stroke-opacity",
                ):
                    if key in ts.attrib:
                        run_style[key] = str(ts.attrib.get(key, "")).strip()
                run_font_size = _parse_svg_number(
                    run_style.get("font-size"),
                    default=_parse_svg_number(style_base.get("font-size"), default=12.0),
                )
                x_list = _parse_svg_number_list(ts.attrib.get("x"))
                y_list = _parse_svg_number_list(ts.attrib.get("y"))
                dx_list = _parse_svg_number_list(ts.attrib.get("dx"))
                dy_list = _parse_svg_number_list(ts.attrib.get("dy"))
                if x_list:
                    x0 = x_list[0]
                elif dx_list:
                    x0 = cursor_x + dx_list[0]
                else:
                    x0 = cursor_x
                if y_list:
                    y0 = y_list[0]
                elif dy_list:
                    dy0 = _adjust_handwriting_tspan_dy(
                        dy_list[0],
                        font_size=run_font_size,
                        text=text,
                        is_first_visible_line=(ts_idx == 0 and not has_lead),
                    )
                    y0 = cursor_y + dy0
                else:
                    y0 = cursor_y
                cursor_x, cursor_y = float(x0), float(y0)
                ts_transform = ts.attrib.get("transform", "").strip()
                run_transform = " ".join(part for part in (node_transform, ts_transform) if part)
                runs.append((text, x0, y0, run_style, run_transform, x_list if x_list else [x0]))
        else:
            text = _extract_svg_text_plain(node)
            if text:
                runs.append((text, base_x, base_y, dict(style_base), node_transform, list(node_x_list)))

        if not runs:
            return None
        combined_text = " ".join(str(run[0]) for run in runs if str(run[0]).strip())
        if (
            _text_prefers_native_vector(combined_text)
            or any(_style_prefers_native_vector(run[3]) for run in runs)
        ):
            _sanitize_svg_text_node_for_vector(node)
            return None

        ns = ""
        if "}" in node.tag:
            ns = node.tag.split("}")[0] + "}"
        group_el = ET.Element(f"{ns}g")

        for text, x0, y0, style, run_transform, x_positions in runs:
            if _style_prefers_native_vector(style):
                continue
            if not _svg_text_node_is_visible(style):
                continue
            font_size = _parse_svg_number(style.get("font-size"), default=12.0)
            if font_size <= 0.0:
                font_size = 12.0

            font_name_pick = _pick_hershey_font_name_for_text(font_name, text)
            font = get_font(font_name_pick)
            if font is None:
                continue
            fonts_used.add(font_name_pick)
            base_line = float(font.render_options.get("base_line", 9.0))

            scale_base = max(0.30, float(HANDWRITING_STROKE_SCALE_Y))
            if _text_contains_cyrillic(text):
                # Cyrillic with tiny scale becomes dotted and unreadable.
                scale_base = max(scale_base, 0.70)
            scale_y = (font_size / 21.0) * scale_base
            scale_x = scale_y

            stroke_color = _pick_svg_text_stroke_color(style)
            if not stroke_color:
                continue
            stroke_width = max(0.14, font_size * 0.035)

            d_parts: List[str] = []
            try:
                rendered_lines = [ln for ln in (text.split("\n")) if ln != ""]
                if not rendered_lines:
                    continue
                line_step = max(font_size * 1.30, font_size + 1.0)
                for line_idx, line_text in enumerate(rendered_lines):
                    segments = list(font.lines_for_text(line_text))
                    if not segments:
                        continue
                    if line_idx == 0 and len(x_positions) >= 2 and segments:
                        src_xs = [float(p[0]) for seg in segments for p in seg]
                        src_span = max(src_xs) - min(src_xs) if src_xs else 0.0
                        dst_span = max(x_positions) - min(x_positions)
                        if src_span > 1e-9 and dst_span > 1e-9:
                            fit_scale_x = dst_span / src_span
                            scale_x = max(scale_y * 0.35, min(scale_y, fit_scale_x))
                    polylines = _hershey_segments_to_polylines(segments)
                    y_shift = y0 + (line_idx * line_step)
                    line_mm: List[List[Tuple[float, float]]] = []
                    for poly in polylines:
                        if len(poly) < 2:
                            continue
                        mm_poly: List[Tuple[float, float]] = []
                        for px, py in poly:
                            xx = x0 + (float(px) * scale_x)
                            yy = y_shift + ((float(py) - base_line) * scale_y)
                            mm_poly.append((xx, yy))
                        if len(mm_poly) >= 2:
                            line_mm.append(mm_poly)
                    line_mm = _postprocess_hershey_text_polylines(
                        line_mm,
                        font_size=font_size,
                        has_cyrillic=_text_contains_cyrillic(line_text),
                        logger=None,
                    )
                    for mm_poly in line_mm:
                        if len(mm_poly) < 2:
                            continue
                        first_x, first_y = mm_poly[0]
                        cmd = [f"M {first_x:.4f} {first_y:.4f}"]
                        for xx, yy in mm_poly[1:]:
                            cmd.append(f"L {xx:.4f} {yy:.4f}")
                        d_parts.append(" ".join(cmd))
            except Exception:
                continue
            if not d_parts:
                continue

            path_el = ET.Element(f"{ns}path")
            path_el.set("d", " ".join(d_parts))
            path_el.set("fill", "none")
            path_el.set("stroke", stroke_color)
            path_el.set("stroke-width", f"{stroke_width:.4f}")
            if run_transform:
                path_el.set("transform", run_transform)
            group_el.append(path_el)

        if len(list(group_el)) <= 0:
            return None
        if len(list(group_el)) == 1:
            return list(group_el)[0]
        return group_el

    def walk(parent: ET.Element) -> None:
        nonlocal changed
        children = list(parent)
        for idx, child in enumerate(children):
            if tag_name(child.tag).lower() in TEXT_NODE_TAGS:
                repl = build_path_for_text_node(child)
                if repl is not None:
                    parent.remove(child)
                    parent.insert(idx, repl)
                    changed += 1
                continue
            walk(child)

    walk(root)
    if changed <= 0:
        if HANDWRITING_STROKE_SVG_FONT_ENABLED and HANDWRITING_HERSHEY_CORE_FIRST:
            logger("Hershey produced no replacement, fallback to SVG stroke-font pipeline.")
            return replace_svg_text_with_svg_stroke_fonts(svg_path, font_name, logger)
        return 0

    try:
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        logger(f"Hershey text replace save failed: {exc}")
        return 0

    used = ",".join(sorted(fonts_used)) if fonts_used else default_font_name
    logger(f"Handwriting stroke mode: replaced {changed} text node(s) with Hershey stroke fonts: {used}.")
    return changed


def normalize_image_contour_mode(mode: Optional[str]) -> str:
    m = (mode or "").strip().lower()
    if m not in {"off", "word_only", "always"}:
        # Backward compatibility with previous boolean-only behavior.
        return "word_only" if IMAGE_CONTOUR_WORD_ONLY else "always"
    return m


def image_contours_enabled_for_input(input_is_word: bool) -> bool:
    if not IMAGE_CONTOUR_ENABLED:
        return False
    mode = normalize_image_contour_mode(IMAGE_CONTOUR_MODE)
    if mode == "off":
        return False
    if mode == "always":
        return True
    return bool(input_is_word)


def image_hatch_enabled_for_input(input_is_word: bool) -> bool:
    if not IMAGE_TONE_HATCH_ENABLED:
        return False
    if HANDWRITING_TEXT_ENABLED and not IMAGE_TONE_HATCH_IN_HANDWRITING:
        return False
    mode = normalize_image_contour_mode(IMAGE_CONTOUR_MODE)
    if mode == "off":
        return False
    if IMAGE_TONE_HATCH_WORD_ONLY and not bool(input_is_word):
        return False
    if mode == "always":
        return True
    return bool(input_is_word)


def convert_svg_text_to_paths(svg_path: Path, logger, *, text_only: bool = False) -> bool:
    # Many PDFs export text as <text>, which can become unreadable glyph blocks on draw.
    # Running the conversion through Inkscape is reliable and keeps geometry in paths.
    if not svg_has_text_nodes(svg_path):
        return True

    exe = find_inkscape()
    major, _, _ = get_inkscape_version(exe)
    action_core = "select-all;export-text-to-path" if text_only else "select-all;object-to-path;export-text-to-path"
    if major >= 1:
        candidates = [
            [
                exe,
                "--batch-process",
                f"--actions={action_core}",
                "--export-type=svg",
                "--export-overwrite",
                f"--export-filename={svg_path}",
                str(svg_path),
            ],
            [
                exe,
                "--batch-process",
                f"--actions={action_core}",
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
                f"--actions={action_core}",
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
    if min(r, g, b) < float(BACKGROUND_FILL_MIN_CHANNEL):
        return False
    opacity = style.get("fill-opacity", elem.attrib.get("fill-opacity", "1")).strip()
    try:
        if float(opacity) < float(BACKGROUND_FILL_MIN_OPACITY):
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
    if tag_name(elem.tag) not in {"path", "rect", "polygon"}:
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


def _zhang_suen_thinning(mask: "np.ndarray") -> "np.ndarray":
    # Cleaner single-pixel skeleton for handwriting than morphological skeleton.
    if np is None:
        return mask
    img = (mask > 0).astype(np.uint8)
    if img.size == 0:
        return (img * 255).astype(np.uint8)

    def _mark(img01: "np.ndarray", step: int) -> "np.ndarray":
        p2 = img01[:-2, 1:-1]
        p3 = img01[:-2, 2:]
        p4 = img01[1:-1, 2:]
        p5 = img01[2:, 2:]
        p6 = img01[2:, 1:-1]
        p7 = img01[2:, :-2]
        p8 = img01[1:-1, :-2]
        p9 = img01[:-2, :-2]
        p1 = img01[1:-1, 1:-1]

        b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
        a = (
            ((p2 == 0) & (p3 == 1)).astype(np.uint8)
            + ((p3 == 0) & (p4 == 1)).astype(np.uint8)
            + ((p4 == 0) & (p5 == 1)).astype(np.uint8)
            + ((p5 == 0) & (p6 == 1)).astype(np.uint8)
            + ((p6 == 0) & (p7 == 1)).astype(np.uint8)
            + ((p7 == 0) & (p8 == 1)).astype(np.uint8)
            + ((p8 == 0) & (p9 == 1)).astype(np.uint8)
            + ((p9 == 0) & (p2 == 1)).astype(np.uint8)
        )

        base = (p1 == 1) & (b >= 2) & (b <= 6) & (a == 1)
        if step == 1:
            keep = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
        else:
            keep = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
        m = base & keep
        out = np.zeros_like(img01, dtype=bool)
        out[1:-1, 1:-1] = m
        return out

    changed = True
    guard = 0
    max_iter = max(64, int(img.shape[0] + img.shape[1]))
    while changed and guard < max_iter:
        guard += 1
        changed = False
        m1 = _mark(img, step=1)
        if np.any(m1):
            img[m1] = 0
            changed = True
        m2 = _mark(img, step=2)
        if np.any(m2):
            img[m2] = 0
            changed = True

    return (img * 255).astype(np.uint8)


def _skeletonize_binary(mask: "np.ndarray") -> "np.ndarray":
    # Prefer Zhang-Suen thinning for cleaner handwriting centerlines.
    if cv2 is None or np is None:
        return mask
    img = (mask > 0).astype(np.uint8) * 255
    try:
        thin = _zhang_suen_thinning(img)
        if cv2.countNonZero(thin) > 0:
            return thin
    except Exception:
        pass

    # Fallback: morphological skeletonization (robust, OpenCV-only).
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


def _prune_skeleton_spurs(skel: "np.ndarray", max_len_px: int) -> "np.ndarray":
    # Remove very short dangling branches to reduce glyph "spikes"/noise.
    if np is None:
        return skel
    max_len = int(max(0, max_len_px))
    if max_len <= 0:
        return skel

    work = (skel > 0).astype(np.uint8)
    h, w = work.shape[:2]

    def _neighbors(p: Tuple[int, int], pix: set[Tuple[int, int]]) -> List[Tuple[int, int]]:
        x, y = p
        out = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                q = (x + dx, y + dy)
                if q in pix:
                    out.append(q)
        return out

    changed = True
    guard = 0
    while changed and guard < 64:
        guard += 1
        changed = False
        ys, xs = np.where(work > 0)
        pixels = {(int(x), int(y)) for x, y in zip(xs.tolist(), ys.tolist())}
        if not pixels:
            break

        nbr = {p: _neighbors(p, pixels) for p in pixels}
        endpoints = [p for p, n in nbr.items() if len(n) == 1]
        remove: set[Tuple[int, int]] = set()

        for ep in endpoints:
            if ep in remove or ep not in pixels:
                continue
            path = [ep]
            prev = None
            cur = ep
            while len(path) <= max_len + 1:
                nbs = [q for q in nbr.get(cur, []) if q != prev and q not in remove]
                if not nbs:
                    break
                nxt = nbs[0]
                path.append(nxt)
                prev, cur = cur, nxt
                deg = len([q for q in nbr.get(cur, []) if q not in remove])
                if deg != 2:
                    break

            # Remove only true short dangling branch that ends at junction.
            deg_end = len([q for q in nbr.get(cur, []) if q not in remove])
            if deg_end >= 3 and (len(path) - 1) <= max_len:
                remove.update(path[:-1])  # keep junction pixel

        if remove:
            changed = True
            for x, y in remove:
                if 0 <= x < w and 0 <= y < h:
                    work[y, x] = 0

    return (work * 255).astype(np.uint8)


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
        # Centerline rasterization must use only closed contours.
        # Treating open polylines as polygons creates bogus fills/loops.
        if not path_is_closed(pts):
            continue
        ring = pts[:-1]
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
    max_bbox_mm = float(FILL_CENTERLINE_MAX_BBOX_MM)
    max_bbox_area_mm2 = float(FILL_CENTERLINE_MAX_BBOX_AREA_MM2)
    if HANDWRITING_TEXT_ENABLED:
        max_bbox_mm = max(max_bbox_mm, float(FILL_CENTERLINE_HANDWRITING_MAX_BBOX_MM))
        max_bbox_area_mm2 = max(max_bbox_area_mm2, float(FILL_CENTERLINE_HANDWRITING_MAX_BBOX_AREA_MM2))

    if w > max_bbox_mm or h > max_bbox_mm:
        return []
    if (w * h) > max_bbox_area_mm2:
        return []

    scale = max(4.0, float(FILL_CENTERLINE_PX_PER_MM))
    if HANDWRITING_TEXT_ENABLED:
        scale = max(scale, float(FILL_CENTERLINE_HANDWRITING_PX_PER_MM))
    margin = 4
    max_side_px = 4096 - 1 - (2 * margin)
    if HANDWRITING_TEXT_ENABLED:
        # For long words/phrases exported as one outlined path, downscale rasterization
        # to keep centerline extraction available instead of falling back to double contours.
        fit_scale = min(max_side_px / max(w, 1e-9), max_side_px / max(h, 1e-9))
        scale = min(scale, fit_scale)
        if scale < 6.0:
            return []
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

    spur_prune_px = int(FILL_CENTERLINE_HANDWRITING_SPUR_PRUNE_PX if HANDWRITING_TEXT_ENABLED else FILL_CENTERLINE_SPUR_PRUNE_PX)
    if spur_prune_px > 0:
        skel = _prune_skeleton_spurs(skel, spur_prune_px)
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
    min_path_mm = float(FILL_CENTERLINE_HANDWRITING_MIN_PATH_MM if HANDWRITING_TEXT_ENABLED else FILL_CENTERLINE_MIN_PATH_MM)
    for path in pix_paths:
        if len(path) < 2:
            continue
        mm = [((x - margin) / scale + min_x, (y - margin) / scale + min_y) for x, y in path]
        mm = simplify_polyline(mm, eps=0.02)
        if polyline_length(mm) < min_path_mm:
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
    max_paths = int(FILL_CENTERLINE_MAX_PATHS_PER_GLYPH)
    min_ratio = float(FILL_CENTERLINE_LEN_RATIO_MIN)
    max_ratio = float(FILL_CENTERLINE_LEN_RATIO_MAX)
    if HANDWRITING_TEXT_ENABLED:
        max_paths = max(max_paths, int(FILL_CENTERLINE_HANDWRITING_MAX_PATHS_PER_GLYPH))
        min_ratio = min(min_ratio, float(FILL_CENTERLINE_HANDWRITING_LEN_RATIO_MIN))
        max_ratio = max(max_ratio, float(FILL_CENTERLINE_HANDWRITING_LEN_RATIO_MAX))

    if len(centerlines) > max_paths:
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
    return min_ratio <= ratio <= max_ratio


def refine_centerline_paths(
    centerlines: List[List[Tuple[float, float]]],
    *,
    handwriting: bool = False,
) -> List[List[Tuple[float, float]]]:
    if not centerlines:
        return []

    if handwriting:
        eps = float(FILL_CENTERLINE_HANDWRITING_LOCAL_STITCH_EPS_MM)
        gap = float(FILL_CENTERLINE_HANDWRITING_LOCAL_GAP_EPS_MM)
        ang = float(FILL_CENTERLINE_HANDWRITING_LOCAL_ANGLE_DEG)
    else:
        eps = float(FILL_CENTERLINE_LOCAL_STITCH_EPS_MM)
        gap = float(FILL_CENTERLINE_LOCAL_GAP_EPS_MM)
        ang = float(FILL_CENTERLINE_LOCAL_ANGLE_DEG)
    min_path_mm = float(FILL_CENTERLINE_HANDWRITING_MIN_PATH_MM if handwriting else FILL_CENTERLINE_MIN_PATH_MM)

    refined = stitch_polylines(centerlines, eps, logger=None, gap_eps=gap, angle_tol_deg=ang)
    out: List[List[Tuple[float, float]]] = []
    for poly in refined:
        if len(poly) < 2:
            continue
        simp = simplify_polyline(poly)
        if len(simp) < 2:
            continue
        if polyline_length(simp) < min_path_mm:
            continue
        out.append(simp)
    return out


def _bbox_touches_or_overlaps(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
    gap: float = 0.0,
) -> bool:
    ax0, ax1, ay0, ay1 = a
    bx0, bx1, by0, by1 = b
    g = max(0.0, float(gap))
    if (ax1 + g) < bx0:
        return False
    if (bx1 + g) < ax0:
        return False
    if (ay1 + g) < by0:
        return False
    if (by1 + g) < ay0:
        return False
    return True


def _small_fill_bbox(item: "PathItem") -> Optional[Tuple[float, float, float, float]]:
    if not item.is_fill or len(item.points) < 3:
        return None
    ring = item.points[:-1] if path_is_closed(item.points) else list(item.points)
    if len(ring) < 3:
        return None
    bx0, bx1, by0, by1 = polygon_bbox(ring)
    w = bx1 - bx0
    h = by1 - by0
    if w <= 0.0 or h <= 0.0:
        return None
    if w > SINGLE_STROKE_TEXT_CLUSTER_MAX_BBOX_MM or h > SINGLE_STROKE_TEXT_CLUSTER_MAX_BBOX_MM:
        return None
    return (bx0, bx1, by0, by1)


def _small_outline_bbox(item: "PathItem") -> Optional[Tuple[float, float, float, float]]:
    if not item.is_stroke or item.is_fill:
        return None
    if len(item.points) < 4:
        return None
    if not path_is_closed(item.points):
        return None
    ring = item.points[:-1]
    if len(ring) < 3:
        return None
    bx0, bx1, by0, by1 = polygon_bbox(ring)
    w = bx1 - bx0
    h = by1 - by0
    if w <= 0.0 or h <= 0.0:
        return None
    if w > SINGLE_STROKE_OUTLINE_CLUSTER_MAX_BBOX_MM or h > SINGLE_STROKE_OUTLINE_CLUSTER_MAX_BBOX_MM:
        return None
    return (bx0, bx1, by0, by1)


def _likely_handwriting_text_group(group: List["PathItem"]) -> bool:
    # Heuristic: tiny fill-driven clusters are usually glyph parts in handwriting mode.
    # For such groups, one-stroke centerline is preferred over contour fallback.
    if not group:
        return False
    if not HANDWRITING_TEXT_ENABLED:
        return False
    if not all(bool(it.is_fill) for it in group):
        return False

    pts = [p for it in group for p in it.points]
    if not pts:
        return False
    x0 = min(p[0] for p in pts)
    x1 = max(p[0] for p in pts)
    y0 = min(p[1] for p in pts)
    y1 = max(p[1] for p in pts)
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    if w <= 0.0 or h <= 0.0:
        return False

    # Handwriting text is usually low-height even for long words/lines.
    # Allow wider groups so single-stroke logic can cover whole words,
    # but keep a strict height cap to avoid technical geometry.
    if h > 22.0:
        return False
    if w > 180.0:
        return False
    if (w * h) > 3200.0:
        return False
    # Very large near-square areas are unlikely to be text.
    if w > 35.0 and h > 18.0:
        return False

    # Avoid using this shortcut for long structural geometry.
    total_len = 0.0
    for it in group:
        if len(it.points) >= 2:
            total_len += polyline_length(it.points)
    if total_len > 4200.0:
        return False
    return True


def _handwriting_group_bbox(group: List["PathItem"]) -> Optional[Tuple[float, float, float, float, float, float, float]]:
    pts = [p for it in group for p in it.points]
    if not pts:
        return None
    x0 = min(p[0] for p in pts)
    x1 = max(p[0] for p in pts)
    y0 = min(p[1] for p in pts)
    y1 = max(p[1] for p in pts)
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    return (x0, x1, y0, y1, w, h, w * h)


def _clean_handwriting_centerlines(
    centerlines: List[List[Tuple[float, float]]],
    min_len_mm: float = 0.04,
) -> List[List[Tuple[float, float]]]:
    cleaned: List[List[Tuple[float, float]]] = []
    min_len = max(0.0, float(min_len_mm))
    for poly in centerlines:
        if len(poly) < 2:
            continue
        simp = simplify_polyline(poly, eps=0.01)
        if len(simp) < 2:
            continue
        if polyline_length(simp) < min_len:
            continue
        cleaned.append(simp)
    return cleaned


def _synthetic_mono_stroke_from_bbox(
    bbox: Optional[Tuple[float, float, float, float, float, float, float]],
    *,
    max_span_mm: float = 8.0,
    max_area_mm2: float = 30.0,
) -> List[List[Tuple[float, float]]]:
    if bbox is None:
        return []
    x0, x1, y0, y1, w, h, area = bbox
    if w <= 0.0 or h <= 0.0:
        return []
    # Synthetic fallback is for tiny punctuation only.
    if w > float(max_span_mm) or h > float(max_span_mm) or area > float(max_area_mm2):
        return []
    cx = (x0 + x1) * 0.5
    cy = (y0 + y1) * 0.5
    if max(w, h) <= 0.9:
        d = 0.10
        return [[(cx - d, cy), (cx + d, cy)]]
    if h >= (w * 1.6):
        d = max(0.15, min(0.45, h * 0.28))
        return [[(cx, cy - d), (cx, cy + d)]]
    if w >= (h * 1.6):
        d = max(0.15, min(0.45, w * 0.28))
        return [[(cx - d, cy), (cx + d, cy)]]
    d = max(0.12, min(0.35, max(w, h) * 0.22))
    return [[(cx - d, cy - d), (cx + d, cy + d)]]


def _split_handwriting_fill_group_components(
    group: List["PathItem"],
    *,
    gap_mm: float = 0.06,
) -> List[List["PathItem"]]:
    if not group:
        return []

    indexed_bbox: List[Tuple[int, Tuple[float, float, float, float]]] = []
    for idx, item in enumerate(group):
        if len(item.points) < 3:
            continue
        if not path_is_closed(item.points):
            continue
        ring = item.points[:-1]
        if len(ring) < 3:
            continue
        indexed_bbox.append((idx, polygon_bbox(ring)))

    if len(indexed_bbox) <= 1:
        return [group]

    n = len(indexed_bbox)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def unite(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        _, bi = indexed_bbox[i]
        for j in range(i + 1, n):
            _, bj = indexed_bbox[j]
            if _bbox_touches_or_overlaps(bi, bj, gap=gap_mm):
                unite(i, j)

    components: dict[int, List[int]] = {}
    for i, (orig_idx, _bbox) in enumerate(indexed_bbox):
        root = find(i)
        components.setdefault(root, []).append(orig_idx)

    # Keep deterministic order (left-to-right).
    ordered: List[List["PathItem"]] = []
    for comp_idx in components.values():
        comp = [group[i] for i in sorted(comp_idx)]
        bbox = _handwriting_group_bbox(comp)
        left = bbox[0] if bbox else 0.0
        ordered.append((left, comp))
    ordered.sort(key=lambda t: t[0])
    out = [comp for _left, comp in ordered]

    covered = {idx for comp in components.values() for idx in comp}
    for idx, item in enumerate(group):
        if idx not in covered:
            out.append([item])
    return out


def tiny_handwriting_text_fallback(
    group: List["PathItem"],
    centerlines: List[List[Tuple[float, float]]],
) -> List[List[Tuple[float, float]]]:
    # Last-resort single-stroke fallback for tiny handwriting glyphs.
    # Prevents reverting to double contour outlines on punctuation/small letters.
    if not HANDWRITING_TEXT_ENABLED:
        return []
    if HANDWRITING_CYRILLIC_ACTIVE:
        return []
    if not _likely_handwriting_text_group(group):
        return []
    bbox = _handwriting_group_bbox(group)
    if bbox is None:
        return []
    x0, x1, y0, y1, w, h, area = bbox
    if w <= 0.0 or h <= 0.0:
        return []

    # Keep this very narrow to avoid touching technical geometry in drawings.
    if w > 6.2 or h > 6.2 or area > 20.0:
        return []

    cleaned = _clean_handwriting_centerlines(centerlines, min_len_mm=0.05)
    if cleaned:
        return cleaned

    # If skeletonization collapses to nothing, draw a tiny synthetic mono-stroke
    # in the glyph bbox instead of falling back to closed contour.
    return _synthetic_mono_stroke_from_bbox(bbox, max_span_mm=6.2, max_area_mm2=20.0)


def force_single_stroke_handwriting_group(
    group: List["PathItem"],
    centerlines: List[List[Tuple[float, float]]],
) -> List[List[Tuple[float, float]]]:
    # Hard guard for handwriting text: no contour fallback.
    # Prefer centerlines even if quality gate is strict; use synthetic mono-stroke as last resort.
    if not HANDWRITING_FORCE_SINGLE_STROKE_TEXT:
        return []
    if not HANDWRITING_TEXT_ENABLED:
        return []
    if HANDWRITING_CYRILLIC_ACTIVE:
        return []
    if not _likely_handwriting_text_group(group):
        return []

    cleaned = _clean_handwriting_centerlines(centerlines, min_len_mm=0.04)
    if cleaned:
        return cleaned

    # Large text groups often contain many glyph contours.
    # Split to small connected components and centerline each one,
    # instead of generating one synthetic dash for the whole line.
    components = _split_handwriting_fill_group_components(group, gap_mm=0.06)
    if len(components) > 1:
        merged: List[List[Tuple[float, float]]] = []
        for comp in components:
            comp_center = centerline_fill_group(comp)
            comp_center = refine_centerline_paths(comp_center, handwriting=True)
            comp_clean = _clean_handwriting_centerlines(comp_center, min_len_mm=0.04)
            if comp_clean:
                merged.extend(comp_clean)
                continue
            comp_tiny = tiny_handwriting_text_fallback(comp, comp_center)
            if comp_tiny:
                merged.extend(comp_tiny)
                continue
            comp_bbox = _handwriting_group_bbox(comp)
            comp_synth = _synthetic_mono_stroke_from_bbox(comp_bbox, max_span_mm=7.0, max_area_mm2=30.0)
            if comp_synth:
                merged.extend(comp_synth)
                continue
            return []
        if merged:
            return merged

    tiny = tiny_handwriting_text_fallback(group, centerlines)
    if tiny:
        return tiny

    # Absolute last resort: synthetic fallback only for tiny marks.
    bbox = _handwriting_group_bbox(group)
    return _synthetic_mono_stroke_from_bbox(bbox, max_span_mm=7.0, max_area_mm2=30.0)


def _centerline_quality_ok_for_handwriting(centerlines: List[List[Tuple[float, float]]]) -> bool:
    # Safety gate for handwriting-only fallback:
    # reject decompositions that are mostly tiny fragments (dot-noise output).
    if not centerlines:
        return False
    lengths = [polyline_length(poly) for poly in centerlines if len(poly) >= 2]
    if not lengths:
        return False
    n = len(lengths)
    if n > int(FILL_CENTERLINE_HANDWRITING_MAX_PATHS_PER_GLYPH):
        return False
    s = sorted(lengths)
    med = s[n // 2]
    if med < 0.40:
        return False
    short = sum(1 for L in lengths if L < 0.30)
    if (short / float(n)) > 0.38:
        return False
    return True


def _likely_handwriting_outline_group(group: List["PathItem"]) -> bool:
    # Detect tiny closed stroke-only outline glyphs and convert them to centerline.
    # This removes "double contour" text in handwriting mode.
    if not group:
        return False
    if not HANDWRITING_TEXT_ENABLED:
        return False
    if not all(bool(it.is_stroke) for it in group):
        return False
    if any(bool(it.is_fill) for it in group):
        return False

    closed = [it for it in group if path_is_closed(it.points) and len(it.points) >= 4]
    if not closed:
        return False

    pts = [p for it in closed for p in it.points]
    if not pts:
        return False
    x0 = min(p[0] for p in pts)
    x1 = max(p[0] for p in pts)
    y0 = min(p[1] for p in pts)
    y1 = max(p[1] for p in pts)
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    if w <= 0.0 or h <= 0.0:
        return False

    # Keep this narrow to avoid technical geometry (circles/details) in drawings.
    if w > 18.0 or h > 18.0:
        return False
    if (w * h) > 220.0:
        return False

    total_len = 0.0
    for it in closed:
        total_len += polyline_length(it.points)
    if total_len > 320.0:
        return False
    return True


def cluster_small_fill_items_for_single_stroke(items: List["PathItem"]) -> List[List[int]]:
    if not SINGLE_STROKE_TEXT_ENABLED:
        return []

    candidates: List[Tuple[int, Tuple[float, float, float, float]]] = []
    for idx, item in enumerate(items):
        bbox = _small_fill_bbox(item)
        if bbox is None:
            continue
        candidates.append((idx, bbox))

    n = len(candidates)
    if n < 2:
        return []
    if n > SINGLE_STROKE_TEXT_CLUSTER_MAX_ITEMS:
        return []

    parent = list(range(n))
    rank = [0] * n

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def unite(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            parent[ra] = rb
        elif rank[rb] < rank[ra]:
            parent[rb] = ra
        else:
            parent[rb] = ra
            rank[ra] += 1

    # Bounding-box touch graph (with tiny tolerance) captures split glyph contours:
    # outer ring + hole(s) often arrive as separate path items / source ids.
    for i in range(n):
        _idx_i, bi = candidates[i]
        for j in range(i + 1, n):
            _idx_j, bj = candidates[j]
            if _bbox_touches_or_overlaps(bi, bj, gap=SINGLE_STROKE_TEXT_CLUSTER_GAP_MM):
                unite(i, j)

    components: dict[int, List[int]] = {}
    comp_bbox: dict[int, Tuple[float, float, float, float]] = {}
    for i, (orig_idx, bbox) in enumerate(candidates):
        root = find(i)
        components.setdefault(root, []).append(orig_idx)
        if root not in comp_bbox:
            comp_bbox[root] = bbox
        else:
            x0, x1, y0, y1 = comp_bbox[root]
            bx0, bx1, by0, by1 = bbox
            comp_bbox[root] = (min(x0, bx0), max(x1, bx1), min(y0, by0), max(y1, by1))

    out: List[List[int]] = []
    for root, comp in components.items():
        if len(comp) < 2:
            continue
        x0, x1, y0, y1 = comp_bbox[root]
        w = x1 - x0
        h = y1 - y0
        if w <= 0.0 or h <= 0.0:
            continue
        if w > SINGLE_STROKE_TEXT_CLUSTER_MAX_BBOX_MM or h > SINGLE_STROKE_TEXT_CLUSTER_MAX_BBOX_MM:
            continue
        out.append(comp)
    return out


def cluster_small_outline_items_for_single_stroke(items: List["PathItem"]) -> List[List[int]]:
    if not SINGLE_STROKE_OUTLINE_TEXT_ENABLED or not HANDWRITING_TEXT_ENABLED:
        return []

    candidates: List[Tuple[int, Tuple[float, float, float, float]]] = []
    for idx, item in enumerate(items):
        bbox = _small_outline_bbox(item)
        if bbox is None:
            continue
        candidates.append((idx, bbox))

    n = len(candidates)
    if n < 2:
        return []
    if n > SINGLE_STROKE_OUTLINE_CLUSTER_MAX_ITEMS:
        return []

    parent = list(range(n))
    rank = [0] * n

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def unite(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            parent[ra] = rb
        elif rank[rb] < rank[ra]:
            parent[rb] = ra
        else:
            parent[rb] = ra
            rank[ra] += 1

    for i in range(n):
        _idx_i, bi = candidates[i]
        for j in range(i + 1, n):
            _idx_j, bj = candidates[j]
            if _bbox_touches_or_overlaps(bi, bj, gap=SINGLE_STROKE_OUTLINE_CLUSTER_GAP_MM):
                unite(i, j)

    components: dict[int, List[int]] = {}
    comp_bbox: dict[int, Tuple[float, float, float, float]] = {}
    for i, (orig_idx, bbox) in enumerate(candidates):
        root = find(i)
        components.setdefault(root, []).append(orig_idx)
        if root not in comp_bbox:
            comp_bbox[root] = bbox
        else:
            x0, x1, y0, y1 = comp_bbox[root]
            bx0, bx1, by0, by1 = bbox
            comp_bbox[root] = (min(x0, bx0), max(x1, bx1), min(y0, by0), max(y1, by1))

    out: List[List[int]] = []
    for root, comp in components.items():
        if len(comp) < 2:
            continue
        x0, x1, y0, y1 = comp_bbox[root]
        w = x1 - x0
        h = y1 - y0
        if w <= 0.0 or h <= 0.0:
            continue
        if w > SINGLE_STROKE_OUTLINE_COMPONENT_MAX_BBOX_MM or h > SINGLE_STROKE_OUTLINE_COMPONENT_MAX_BBOX_MM:
            continue
        if (w * h) > SINGLE_STROKE_OUTLINE_COMPONENT_MAX_AREA_MM2:
            continue
        out.append(comp)
    return out


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


def simplify_polyline(
    poly: List[Tuple[float, float]],
    eps: float = 1e-6,
    *,
    collinear_eps: Optional[float] = None,
) -> List[Tuple[float, float]]:
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
    col_eps = float(POLYLINE_COLLINEAR_EPS if collinear_eps is None else max(0.0, collinear_eps))
    for p in out[1:]:
        if len(col) >= 2:
            last = col[-1]
            prev = col[-2]
            if point_line_distance(last, prev, p) <= col_eps:
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
        # mat_mul composes in reverse order: mat_mul(a, b) == b * a.
        # For nested SVG nodes we need parent * local, so pass (local, parent).
        cur_matrix = mat_mul(local_transform, matrix)
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
                    use_matrix = mat_mul((1.0, 0.0, 0.0, 1.0, use_x, use_y), cur_matrix)

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
        for poly in new_polys:
            if is_full_page_white_fill_rect(poly.points, node, page_w_mm * scale, page_h_mm * scale):
                continue
            out.append(poly)
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
    out: List[List[Tuple[float, float]]] = []
    consumed_idx: set[int] = set()
    handwriting = bool(HANDWRITING_TEXT_ENABLED)
    preserve_fill_outlines = bool(
        HANDWRITING_TEXT_ENABLED
        and HANDWRITING_STROKE_ACTIVE
        and HANDWRITING_PRESERVE_FILL_OUTLINES
    )
    if SINGLE_STROKE_TEXT_ENABLED and not preserve_fill_outlines:
        clusters = cluster_small_fill_items_for_single_stroke(items)
        for comp in clusters:
            group = [items[i] for i in comp]
            centerlines = centerline_fill_group(group)
            centerlines = refine_centerline_paths(centerlines, handwriting=handwriting)
            if centerline_is_usable(group, centerlines) or (
                _likely_handwriting_text_group(group) and _centerline_quality_ok_for_handwriting(centerlines)
            ):
                out.extend(centerlines)
                consumed_idx.update(comp)

    if SINGLE_STROKE_OUTLINE_TEXT_ENABLED and handwriting and not preserve_fill_outlines:
        outline_clusters = cluster_small_outline_items_for_single_stroke(items)
        for comp in outline_clusters:
            if any(i in consumed_idx for i in comp):
                continue
            group = [items[i] for i in comp]
            centerlines = centerline_fill_group(group)
            centerlines = refine_centerline_paths(centerlines, handwriting=handwriting)
            if centerline_is_usable(group, centerlines) or _centerline_quality_ok_for_handwriting(centerlines):
                out.extend(centerlines)
                consumed_idx.update(comp)

    grouped = {}
    for idx, item in enumerate(items):
        if idx in consumed_idx:
            continue
        group_key = (item.source_id, bool(item.is_fill), item.is_stroke)
        grouped.setdefault(group_key, []).append(item)

    for (source_id, is_fill, is_stroke), group in grouped.items():
        _ = source_id

        if not is_stroke and not is_fill:
            continue

        if (not preserve_fill_outlines) and HANDWRITING_OUTLINE_CENTERLINE_ENABLED and _likely_handwriting_outline_group(group):
            centerlines = centerline_fill_group(group)
            centerlines = refine_centerline_paths(centerlines, handwriting=handwriting)
            if centerline_is_usable(group, centerlines):
                out.extend(centerlines)
                continue

        # Some PDF text glyphs come as fill+stroke simultaneously.
        # Prefer a single centerline stroke when stable, otherwise keep original geometry.
        if is_fill and (not preserve_fill_outlines):
            centerlines = centerline_fill_group(group)
            centerlines = refine_centerline_paths(centerlines, handwriting=handwriting)
            if centerline_is_usable(group, centerlines) or (
                _likely_handwriting_text_group(group) and _centerline_quality_ok_for_handwriting(centerlines)
            ):
                out.extend(centerlines)
                continue
            forced_single = force_single_stroke_handwriting_group(group, centerlines)
            if forced_single:
                out.extend(forced_single)
                continue
            tiny_fallback = tiny_handwriting_text_fallback(group, centerlines)
            if tiny_fallback:
                out.extend(tiny_fallback)
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
            if not preserve_fill_outlines:
                centerlines = centerline_fill_group(fill_rest)
                centerlines = refine_centerline_paths(centerlines, handwriting=handwriting)
                if centerline_is_usable(fill_rest, centerlines) or (
                    _likely_handwriting_text_group(fill_rest) and _centerline_quality_ok_for_handwriting(centerlines)
                ):
                    out.extend(centerlines)
                    continue
                forced_single = force_single_stroke_handwriting_group(fill_rest, centerlines)
                if forced_single:
                    out.extend(forced_single)
                    continue
                tiny_fallback = tiny_handwriting_text_fallback(fill_rest, centerlines)
                if tiny_fallback:
                    out.extend(tiny_fallback)
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


def write_xy_gcode(
    output: Path,
    polylines: List[List[Tuple[float, float]]],
    feed_travel: float,
    feed_draw: float,
    *,
    join_eps: Optional[float] = None,
) -> None:
    lines = [
        "G21",
        "G90",
        "G17",
        "G91.1",
        f"G0 Z{Z_UP:.4f}",
    ]
    pos = None
    join_eps_v = CONTINUOUS_JOIN_EPS if join_eps is None else max(0.0, float(join_eps))
    line_fit_tol = 0.0 if HANDWRITING_TEXT_ENABLED else float(LINE_FIT_TOL_MM)
    rdp_eps = 0.0 if HANDWRITING_TEXT_ENABLED else float(RDP_SIMPLIFY_EPS_MM)
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
            if d0 > join_eps_v:
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
        if line_fit_tol > 0.0 and polyline_is_near_line(poly, line_fit_tol):
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
        if rdp_eps > 0.0 and len(poly) >= 3:
            poly = rdp_simplify_polyline(poly, rdp_eps)
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


def stitch_polylines(
    polylines: List[List[Tuple[float, float]]],
    eps: float,
    logger=print,
    *,
    gap_eps: Optional[float] = None,
    angle_tol_deg: Optional[float] = None,
    simplify_collinear_eps: Optional[float] = None,
) -> List[List[Tuple[float, float]]]:
    # Join polyline fragments that share endpoints to reduce pen up/down churn.
    if not polylines or eps <= 0 or not STITCH_ENABLED:
        return polylines

    if EXACT_GEOMETRY_MODE and gap_eps is None and angle_tol_deg is None:
        # In exact-copy mode, do not "bridge" near endpoints.
        # Gap stitching can connect unrelated technical geometry and create artifacts.
        gap_eps_v = float(eps)
        angle_tol = 0.0
    else:
        gap_eps_v = (
            max(float(eps), float(STITCH_GAP_EPS_MM))
            if gap_eps is None
            else max(float(eps), float(gap_eps))
        )
        angle_tol = (
            float(STITCH_GAP_MAX_ANGLE_DEG)
            if angle_tol_deg is None
            else max(0.0, float(angle_tol_deg))
        )
    cell = gap_eps_v

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
                if d <= gap_eps_v and tail_dir is not None and angle_tol > 0:
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
                if d <= gap_eps_v and head_dir is not None and angle_tol > 0:
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

        cur = simplify_polyline(cur, collinear_eps=simplify_collinear_eps)
        if len(cur) >= 2:
            out.append(cur)

    if logger and len(out) != len(polylines):
        logger(
            f"Stitch: polylines {len(polylines)} -> {len(out)} "
            f"(eps={eps:.3f} mm, gap_eps={gap_eps_v:.3f} mm, angle<={angle_tol:.1f} deg)"
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


def _effective_draw_order_mode() -> str:
    mode = str(DRAW_ORDER_MODE or "nearest").strip().lower()
    if mode == "auto":
        # Preserve classic optimization for technical/pencil jobs,
        # but keep natural reading direction for handwriting with pen.
        if HANDWRITING_TEXT_ENABLED and TOOL_MODE == "pen":
            return "line_lr"
        return "nearest"
    if mode in {"nearest", "source", "line_lr", "line"}:
        return mode
    return "nearest"


def reorder_polylines(polylines: List[List[Tuple[float, float]]], logger=print) -> List[List[Tuple[float, float]]]:
    if not polylines:
        return polylines

    mode = _effective_draw_order_mode()
    if not REORDER_ENABLED or mode == "source":
        if logger and len(polylines) >= 2 and mode == "source":
            logger(f"Reorder: source order preserved ({len(polylines)} polylines).")
        return polylines

    if mode in {"line_lr", "line"}:
        remaining = [p for p in polylines if len(p) >= 2]
        if not remaining:
            return []
        tol = max(0.6, float(DRAW_ORDER_LINE_TOL_MM))
        entries: List[Tuple[int, float, float, float, float, List[Tuple[float, float]]]] = []
        for idx, poly in enumerate(remaining):
            xs = [pt[0] for pt in poly]
            ys = [pt[1] for pt in poly]
            min_x = min(xs)
            max_x = max(xs)
            min_y = min(ys)
            max_y = max(ys)
            cy = 0.5 * (min_y + max_y)
            entries.append((idx, min_x, max_x, min_y, cy, poly))

        # Top -> bottom rows (smaller Y first in our page-like coordinate space),
        # then left -> right inside each row.
        entries.sort(key=lambda row: (row[4], row[1], row[0]))
        rows: List[Tuple[float, List[Tuple[int, float, float, float, float, List[Tuple[float, float]]]]]] = []
        for ent in entries:
            if not rows:
                rows.append((ent[4], [ent]))
                continue
            last_y, last_items = rows[-1]
            if abs(ent[4] - last_y) <= tol:
                last_items.append(ent)
                # update running row center for robust clustering
                rows[-1] = ((last_y * (len(last_items) - 1) + ent[4]) / len(last_items), last_items)
            else:
                rows.append((ent[4], [ent]))

        ordered: List[List[Tuple[float, float]]] = []
        for _, row_items in rows:
            row_items.sort(key=lambda row: (row[1], row[0]))
            for _, min_x, max_x, _min_y, _cy, poly in row_items:
                out_poly = list(poly)
                # Prefer left->right local stroke direction when it is unambiguous.
                if len(out_poly) >= 2:
                    sx, ex = out_poly[0][0], out_poly[-1][0]
                    span_x = max(0.0, max_x - min_x)
                    if (sx - ex) > max(0.6, 0.15 * span_x):
                        out_poly = list(reversed(out_poly))
                ordered.append(out_poly)

        if logger and len(ordered) >= 2:
            logger(
                f"Reorder: {len(polylines)} polylines ordered (line_lr, row_tol={tol:.2f} mm)."
            )
        return ordered

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


def merge_handwriting_word_strokes(
    polylines: List[List[Tuple[float, float]]],
    logger=print,
    *,
    join_gap_mm: float = HANDWRITING_WORD_JOIN_GAP_MM,
    join_max_dy_mm: float = HANDWRITING_WORD_JOIN_MAX_DY_MM,
    simplify_collinear_eps: Optional[float] = None,
) -> List[List[Tuple[float, float]]]:
    # Keep short same-line gaps inside words as one continuous stroke.
    if not HANDWRITING_WORD_JOIN_ENABLE:
        return polylines
    if not polylines:
        return polylines

    gap_max = max(0.0, float(join_gap_mm))
    dy_max = max(0.0, float(join_max_dy_mm))
    if gap_max <= 1e-9:
        return polylines

    src = [p for p in polylines if len(p) >= 2]
    if not src:
        return []

    merged_count = 0
    out: List[List[Tuple[float, float]]] = []
    current = list(src[0])

    for raw_next in src[1:]:
        next_fwd = list(raw_next)
        next_rev = list(reversed(raw_next))
        cur_end = current[-1]

        d_fwd = points_distance(cur_end, next_fwd[0])
        d_rev = points_distance(cur_end, next_rev[0])
        nxt = next_rev if d_rev < d_fwd else next_fwd
        gap = min(d_fwd, d_rev)
        dy = abs(nxt[0][1] - cur_end[1])
        dx = nxt[0][0] - cur_end[0]

        # Prevent accidental backward/side jumps that corrupt glyph shapes.
        backward_limit = -max(0.20, 0.35 * gap_max)
        if gap <= gap_max and dy <= dy_max and dx >= backward_limit:
            if gap > 1e-9:
                current.append(nxt[0])
            current.extend(nxt[1:])
            current = simplify_polyline(current, collinear_eps=simplify_collinear_eps)
            merged_count += 1
            continue

        current = simplify_polyline(current, collinear_eps=simplify_collinear_eps)
        if len(current) >= 2:
            out.append(current)
        current = list(nxt)

    current = simplify_polyline(current, collinear_eps=simplify_collinear_eps)
    if len(current) >= 2:
        out.append(current)

    if logger and merged_count > 0:
        logger(
            f"Handwriting join: merged {merged_count} short gaps "
            f"(gap<={gap_max:.2f} mm, dy<={dy_max:.2f} mm), polylines {len(src)} -> {len(out)}"
        )
    return out


def _is_handwriting_smooth_candidate(poly: List[Tuple[float, float]]) -> bool:
    if len(poly) < 3:
        return False
    if path_is_closed(poly):
        return False
    L = polyline_length(poly)
    if L < float(HANDWRITING_SMOOTH_MIN_LEN_MM) or L > float(HANDWRITING_SMOOTH_MAX_LEN_MM):
        return False
    # Keep long technical straight segments untouched.
    if polyline_is_near_line(poly, float(HANDWRITING_SMOOTH_SKIP_NEAR_LINE_TOL_MM)) and L > 14.0:
        return False
    return True


def smooth_handwriting_polylines(
    polylines: List[List[Tuple[float, float]]],
    logger=print,
) -> List[List[Tuple[float, float]]]:
    if not HANDWRITING_SMOOTH_ENABLED:
        return polylines
    if not polylines:
        return polylines

    out: List[List[Tuple[float, float]]] = []
    changed = 0
    resample_step = max(0.08, float(HANDWRITING_SMOOTH_RESAMPLE_MM))
    smooth_passes = max(0, int(HANDWRITING_SMOOTH_PASSES))
    rdp_eps = max(0.0, float(HANDWRITING_SMOOTH_RDP_EPS_MM))

    for poly in polylines:
        if not _is_handwriting_smooth_candidate(poly):
            out.append(poly)
            continue
        base = _resample_polyline_step(poly, resample_step)
        base = _smooth_open_polyline(base, smooth_passes)
        if rdp_eps > 0.0 and len(base) >= 3:
            base = rdp_simplify_polyline(base, rdp_eps)
        base = simplify_polyline(base)
        if len(base) < 2:
            out.append(poly)
            continue
        out.append(base)
        if len(base) != len(poly) or any(points_distance(a, b) > 1e-8 for a, b in zip(base, poly[: len(base)])):
            changed += 1

    if logger and changed > 0:
        logger(f"Handwriting smooth: adjusted {changed}/{len(polylines)} stroke(s).")
    return out


def _pseudo_rand01(seed: int) -> float:
    x = math.sin(float(seed) * 12.9898 + 78.233) * 43758.5453
    return x - math.floor(x)


def _resample_polyline_step(poly: List[Tuple[float, float]], step_mm: float) -> List[Tuple[float, float]]:
    if len(poly) < 2:
        return list(poly)
    step = max(1e-4, float(step_mm))
    out: List[Tuple[float, float]] = [poly[0]]
    carry = 0.0
    prev = poly[0]
    for cur in poly[1:]:
        seg = points_distance(prev, cur)
        if seg <= 1e-12:
            prev = cur
            continue
        ux = (cur[0] - prev[0]) / seg
        uy = (cur[1] - prev[1]) / seg
        d = step - carry
        while d < seg - 1e-12:
            px = prev[0] + ux * d
            py = prev[1] + uy * d
            out.append((px, py))
            d += step
            carry = 0.0
        carry = max(0.0, seg - (d - step))
        prev = cur
    if points_distance(out[-1], poly[-1]) > 1e-9:
        out.append(poly[-1])
    return out


def _smooth_open_polyline(poly: List[Tuple[float, float]], passes: int = 1) -> List[Tuple[float, float]]:
    if len(poly) < 3 or passes <= 0:
        return list(poly)
    cur = list(poly)
    for _ in range(int(max(0, passes))):
        if len(cur) < 3:
            break
        nxt = [cur[0]]
        for i in range(1, len(cur) - 1):
            px, py = cur[i - 1]
            cx, cy = cur[i]
            nx, ny = cur[i + 1]
            nxt.append(((px * 0.20) + (cx * 0.60) + (nx * 0.20), (py * 0.20) + (cy * 0.60) + (ny * 0.20)))
        nxt.append(cur[-1])
        cur = nxt
    return cur


def _is_pencil_humanize_candidate(poly: List[Tuple[float, float]]) -> bool:
    if len(poly) < 2:
        return False
    if path_is_closed(poly):
        return False
    L = polyline_length(poly)
    if L < float(PENCIL_NATURAL_MIN_LEN_MM) or L > float(PENCIL_NATURAL_MAX_LEN_MM):
        return False
    chord = points_distance(poly[0], poly[-1])
    if L > 1e-9 and (chord / L) >= 0.985:
        if polyline_is_near_line(poly, float(PENCIL_NATURAL_SKIP_NEAR_LINE_TOL_MM)):
            # Keep long technical straight lines crisp; allow small handwriting strokes.
            if L > 18.0:
                return False
    return True


def _humanize_one_pencil_polyline(poly: List[Tuple[float, float]], idx: int) -> List[Tuple[float, float]]:
    base = _resample_polyline_step(poly, float(PENCIL_NATURAL_RESAMPLE_MM))
    if len(base) < 4:
        return list(poly)
    base = _smooth_open_polyline(base, int(PENCIL_NATURAL_SMOOTH_PASSES))
    if len(base) < 4:
        return list(poly)

    total_len = polyline_length(base)
    if total_len <= 1e-9:
        return list(poly)

    amp_scale = 0.70 + 0.60 * _pseudo_rand01(1009 + idx * 23)
    amp = min(float(PENCIL_NATURAL_MAX_AMP_MM), float(PENCIL_NATURAL_BASE_AMP_MM) * amp_scale)
    phase1 = _pseudo_rand01(2003 + idx * 17)
    phase2 = _pseudo_rand01(3001 + idx * 29)
    freq1 = 1.10 + 1.10 * _pseudo_rand01(4001 + idx * 31)
    freq2 = 2.30 + 1.60 * _pseudo_rand01(5003 + idx * 37)

    out: List[Tuple[float, float]] = [base[0]]
    acc = 0.0
    for i in range(1, len(base) - 1):
        prev = base[i - 1]
        cur = base[i]
        nxt = base[i + 1]
        acc += points_distance(prev, cur)
        t = max(0.0, min(1.0, acc / total_len))
        edge_fade = min(1.0, t / 0.12, (1.0 - t) / 0.12)

        tx = nxt[0] - prev[0]
        ty = nxt[1] - prev[1]
        tn = math.hypot(tx, ty)
        if tn <= 1e-12:
            out.append(cur)
            continue
        nx = -ty / tn
        ny = tx / tn

        s1 = math.sin(2.0 * math.pi * (freq1 * t + phase1))
        s2 = math.sin(2.0 * math.pi * (freq2 * t + phase2))
        delta = amp * edge_fade * ((0.72 * s1) + (0.28 * s2))
        out.append((cur[0] + nx * delta, cur[1] + ny * delta))
    out.append(base[-1])

    out = simplify_polyline(out)
    if len(out) >= 3:
        out = rdp_simplify_polyline(out, min(0.03, amp * 0.6))
    if len(out) < 2:
        return list(poly)
    return out


def humanize_pencil_polylines(
    polylines: List[List[Tuple[float, float]]],
    logger=print,
    *,
    handwriting_enabled: bool = False,
) -> List[List[Tuple[float, float]]]:
    if not polylines or not PENCIL_NATURAL_STROKES_ENABLED:
        return polylines
    if PENCIL_NATURAL_ONLY_HANDWRITING and not bool(handwriting_enabled):
        return polylines

    out: List[List[Tuple[float, float]]] = []
    changed = 0
    for idx, poly in enumerate(polylines):
        if not _is_pencil_humanize_candidate(poly):
            out.append(poly)
            continue
        h = _humanize_one_pencil_polyline(poly, idx)
        out.append(h)
        if len(h) != len(poly) or any(points_distance(a, b) > 1e-8 for a, b in zip(h, poly[: len(h)])):
            changed += 1
    if logger and changed > 0:
        logger(f"Pencil naturalization: adjusted {changed}/{len(polylines)} stroke(s).")
    return out


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
    handwriting_mode: bool = False,
) -> None:
    script = ROOT_DIR / "src" / "penlift_postprocess.py"
    z_delay_down_eff = float(Z_DELAY_DOWN)
    z_delay_up_eff = float(Z_DELAY_UP)
    z_feed_down_approach_eff = float(Z_FEED_DOWN_APPROACH)
    z_feed_down_touch_eff = float(Z_FEED_DOWN_TOUCH)
    z_feed_up_eff = float(Z_FEED_UP)
    z_feed_up_final_eff = float(Z_FEED_UP_FINAL)
    z_soft_down_eff = float(Z_SOFT_DOWN_MM)
    z_soft_up_eff = float(Z_SOFT_UP_MM)

    if TOOL_MODE == "pen" and PEN_FAST_Z_PROFILE_ENABLED and not Z_PROFILE_CLI_OVERRIDE:
        z_delay_down_eff = float(PEN_FAST_Z_DELAY_DOWN)
        z_delay_up_eff = float(PEN_FAST_Z_DELAY_UP)
        z_feed_down_approach_eff = float(PEN_FAST_Z_FEED_DOWN_APPROACH)
        z_feed_down_touch_eff = float(PEN_FAST_Z_FEED_DOWN_TOUCH)
        z_feed_up_eff = float(PEN_FAST_Z_FEED_UP)
        z_feed_up_final_eff = float(PEN_FAST_Z_FEED_UP_FINAL)
        z_soft_down_eff = float(PEN_FAST_Z_SOFT_DOWN_MM)
        z_soft_up_eff = float(PEN_FAST_Z_SOFT_UP_MM)

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
        f"{z_delay_down_eff:.2f}",
        "--delay-up",
        f"{z_delay_up_eff:.2f}",
        "--z-feed-down-approach",
        f"{z_feed_down_approach_eff:.1f}",
        "--z-feed-down-touch",
        f"{z_feed_down_touch_eff:.1f}",
        "--z-feed-up",
        f"{z_feed_up_eff:.1f}",
        "--z-feed-up-final",
        f"{z_feed_up_final_eff:.1f}",
        "--z-soft-down-mm",
        f"{z_soft_down_eff:.3f}",
        "--z-soft-up-mm",
        f"{z_soft_up_eff:.3f}",
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
        if PENCIL_STROKE_Z_JITTER_ENABLED:
            cmd.extend(
                [
                    "--stroke-z-jitter-enable",
                    "--stroke-z-jitter-mm",
                    f"{max(0.0, float(PENCIL_STROKE_Z_JITTER_MM)):.6f}",
                    "--stroke-z-jitter-seed",
                    str(int(PENCIL_STROKE_Z_JITTER_SEED)),
                ]
            )
    if HANDWRITING_MERGE_SHORT_TRAVEL_ENABLE and (handwriting_mode or TOOL_MODE == "pen"):
        cmd.extend(
            [
                "--merge-short-travel-enable",
                "--merge-short-travel-mm",
                f"{max(0.0, float(HANDWRITING_MERGE_SHORT_TRAVEL_MM)):.3f}",
                "--merge-short-travel-feed",
                f"{max(1.0, float(HANDWRITING_MERGE_SHORT_TRAVEL_FEED)):.1f}",
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
    collinear_overridden = collinear_eps is not None
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

    if HANDWRITING_TEXT_ENABLED:
        # Handwriting readability first: keep more curvature/details, avoid over-flattening.
        if not collinear_overridden:
            profile_eps = min(profile_eps, float(HANDWRITING_COLLINEAR_EPS_MAX))
        profile_rdp = min(profile_rdp, 0.008)
        profile_line_fit = min(profile_line_fit, 0.008)

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
    if HANDWRITING_TEXT_ENABLED:
        # For handwriting output keep literal stroke geometry.
        # Arc fitting can incorrectly "curve" table lines/formulas into large arcs.
        EMIT_ARCS = False
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
        f"DrawOrder={_effective_draw_order_mode()}(cfg={str(DRAW_ORDER_MODE or 'nearest').strip().lower()}); "
        f"ForceTextToPath={'on' if FORCE_TEXT_TO_PATH else 'off'}; "
        f"Handwriting={'on' if HANDWRITING_TEXT_ENABLED else 'off'}({normalize_handwriting_font_name(HANDWRITING_FONT_FAMILY)}); "
        f"HandwritingCenterline={_normalize_singleline_ttf_backend(HANDWRITING_SINGLELINE_TTF_BACKEND)}; "
        f"HandwritingDirectVector={'on' if HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED else 'off'}; "
        f"ImageContours={normalize_image_contour_mode(IMAGE_CONTOUR_MODE)}"
    )




def pdf_to_svg(pdf_path: Path, svg_path: Path, logger) -> None:
    global HANDWRITING_STROKE_ACTIVE
    global HANDWRITING_CYRILLIC_ACTIVE
    logger = _safe_logger(logger)
    logger("Converting PDF -> SVG ...")
    HANDWRITING_STROKE_ACTIVE = False
    HANDWRITING_CYRILLIC_ACTIVE = False

    svg_path.parent.mkdir(parents=True, exist_ok=True)

    def postprocess_text(svg_target: Path) -> Tuple[bool, int]:
        global HANDWRITING_CYRILLIC_ACTIVE
        has_text = svg_has_text_nodes(svg_target)
        had_text = has_text
        handwriting_nodes = 0
        used_stroke_text = False
        if HANDWRITING_TEXT_ENABLED and has_text:
            has_cyrillic = svg_has_cyrillic_text_nodes(svg_target)
            HANDWRITING_CYRILLIC_ACTIVE = bool(has_cyrillic)
            stroke_replaced = _replace_handwriting_text_nodes(svg_target, has_cyrillic, logger)
            handwriting_nodes = stroke_replaced
            has_text = svg_has_text_nodes(svg_target)
            used_stroke_text = stroke_replaced > 0
            if stroke_replaced > 0:
                logger(f"Text nodes after stroke-font replacement: {svg_text_node_count(svg_target)}")
            if has_text:
                # Keep remaining unresolved text nodes in handwriting style too.
                # Without this, mixed output appears when only part of text was
                # replaced by direct vector/TTF centerline.
                font_applied = apply_handwriting_font(
                    svg_target,
                    _effective_handwriting_font_for_text(has_cyrillic),
                    logger,
                )
                handwriting_nodes += max(0, int(font_applied))
                has_text = svg_has_text_nodes(svg_target)
            has_text = svg_has_text_nodes(svg_target)
        if FORCE_TEXT_TO_PATH or has_text:
            text_only = bool(used_stroke_text)
            if not convert_svg_text_to_paths(svg_target, logger, text_only=text_only) or svg_has_text_nodes(svg_target):
                raise RuntimeError("Text->path conversion required and failed.")
            logger(f"Text nodes after conversion: {svg_text_node_count(svg_target)}")
        return had_text, handwriting_nodes

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
                    str(pdf_path),
                    "--export-type=svg",
                    "--export-area-page",
                    "--export-overwrite",
                    f"--export-filename={target_svg}",
                    "--pdf-page=1",
                    "--pdf-poppler",
                ],
                [
                    exe,
                    str(pdf_path),
                    "--export-type=svg",
                    "--export-area-page",
                    "--export-overwrite",
                    f"--export-filename={target_svg}",
                    "--pdf-page=1",
                ],
                [
                    exe,
                    str(pdf_path),
                    "--actions=select-all;object-to-path;export-text-to-path",
                    "--export-overwrite",
                    "--export-area-page",
                    f"--export-filename={target_svg}",
                    "--pdf-page=1",
                ],
                [
                    exe,
                    str(pdf_path),
                    "--actions=select-all;object-to-path;export-text-to-path",
                    "--export-overwrite",
                    "--export-area-page",
                    "--export-plain-svg",
                    f"--export-filename={target_svg}",
                    "--pdf-page=1",
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

    exports: List[Tuple[str, Path, bool, int]] = []
    # Keep non-interactive behavior by default:
    # do not force Inkscape PDF import from handwriting mode, because some environments
    # may still show the "PDF import options" window.
    # In handwriting mode prefer Inkscape PDF import as well:
    # it can preserve editable text nodes before text->path conversion and
    # usually yields cleaner glyph geometry than pdftocairo-only output.
    try_inkscape = bool(USE_INKSCAPE_PDF_IMPORT or HANDWRITING_TEXT_ENABLED)

    # 1) Inkscape PDF import is optional and disabled by default to avoid interactive
    # "PDF import options" dialog windows.
    if try_inkscape:
        ink_svg = svg_path.with_name(f"{svg_path.stem}_inkscape.svg")
        ok_ink, msg_ink = try_inkscape_export(ink_svg)
        if ok_ink:
            try:
                had_text, handwriting_nodes = postprocess_text(ink_svg)
                exports.append(("inkscape", ink_svg, had_text, handwriting_nodes))
            except Exception as exc:
                logger(f"Inkscape output rejected in postprocess: {exc}")
                exports.append(("inkscape", ink_svg, svg_has_text_nodes(ink_svg), 0))
        else:
            logger(f"Inkscape export failed: {msg_ink}")
    else:
        logger("Inkscape PDF import disabled (USE_INKSCAPE_PDF_IMPORT=False and handwriting=off).")

    # 2) pdftocairo fallback/candidate for auto-choice.
    cairo_svg = svg_path.with_name(f"{svg_path.stem}_pdftocairo.svg")
    ok_cairo, msg_cairo = try_pdftocairo_export(cairo_svg)
    if ok_cairo:
        try:
            had_text, handwriting_nodes = postprocess_text(cairo_svg)
            exports.append(("pdftocairo", cairo_svg, had_text, handwriting_nodes))
        except Exception as exc:
            logger(f"pdftocairo output rejected in postprocess: {exc}")
            exports.append(("pdftocairo", cairo_svg, svg_has_text_nodes(cairo_svg), 0))
    else:
        logger(f"pdftocairo export failed: {msg_cairo}")

    if not exports:
        if not USE_INKSCAPE_PDF_IMPORT:
            raise RuntimeError(
                "Failed to convert PDF to SVG with pdftocairo. "
                "Install/configure Poppler pdftocairo or enable Inkscape PDF import in code."
            )
        raise RuntimeError("Failed to convert PDF to SVG with both Inkscape and pdftocairo.")

    scored: List[Tuple[str, Path, float, str, bool, int]] = []
    for name, candidate, had_text, handwriting_nodes in exports:
        score, details = score_svg_quality(candidate)
        logger(
            f"Converter metrics [{name}]: {details}, "
            f"had_text={'yes' if had_text else 'no'}, handwriting_nodes={handwriting_nodes}"
        )
        scored.append((name, candidate, score, details, had_text, handwriting_nodes))

    preferred = scored
    if HANDWRITING_TEXT_ENABLED:
        with_handwriting = [row for row in scored if row[5] > 0]
        with_text = [row for row in scored if row[4]]
        if with_handwriting:
            preferred = with_handwriting
            logger(
                "Handwriting mode: forcing converter with editable text "
                f"(font applied to {sum(row[5] for row in with_handwriting)} node(s) total)."
            )
        elif with_text:
            preferred = with_text
            logger(
                "Handwriting mode: forcing converter that preserved text nodes "
                "(font substitution reported 0 changed nodes)."
            )
        else:
            inkscape_only = [row for row in scored if row[0] == "inkscape"]
            if inkscape_only:
                preferred = inkscape_only
                logger(
                    "Handwriting mode warning: no converter produced editable text; "
                    "using Inkscape geometry for contour-only fallback."
                )
            else:
                logger(
                    "Handwriting mode warning: no converter produced editable text; "
                    "font substitution cannot be applied for this PDF page."
                )

    best_name, best_svg, best_score, best_details, _best_had_text, _best_hw_nodes = min(
        preferred, key=lambda row: row[2]
    )
    HANDWRITING_STROKE_ACTIVE = bool(HANDWRITING_TEXT_ENABLED and (_best_hw_nodes > 0))

    if svg_path.exists():
        svg_path.unlink()
    shutil.copyfile(str(best_svg), str(svg_path))
    logger(f"Selected PDF converter: {best_name} ({best_details})")


def _normalize_word_font_name(font_name: Optional[str], default: str = "") -> str:
    raw = str(font_name or "").strip().strip("'").strip('"')
    if not raw:
        return str(default or "").strip()
    stem = Path(raw).stem if raw.lower().endswith((".ttf", ".otf", ".ttc")) else ""
    candidates: List[str] = []
    if stem:
        candidates.append(stem)
        candidates.append(stem.replace("_", " "))
        if stem.lower().startswith("ofont.ru_"):
            short = stem.split("_", 1)[1]
            candidates.append(short)
            candidates.append(short.replace("_", " "))
    candidates.append(raw)
    for cand in candidates:
        name = str(cand or "").strip()
        if name:
            return name
    return str(default or "").strip()


def _apply_word_formula_font(doc, formula_font: Optional[str], logger) -> int:
    apply_math = bool(formula_font) or bool(HANDWRITING_WORD_KEEP_MATH)
    if not apply_math:
        return 0
    target_math = _normalize_word_font_name(formula_font, default="Cambria Math")
    restored_math = 0
    try:
        omaths = getattr(doc, "OMaths", None)
        count = int(getattr(omaths, "Count", 0) or 0) if omaths is not None else 0
        for i in range(1, count + 1):
            try:
                rng = omaths.Item(i).Range
                rng.Font.Name = target_math
                try:
                    rng.Font.NameAscii = target_math
                    rng.Font.NameFarEast = target_math
                    rng.Font.NameOther = target_math
                except Exception:
                    pass
                restored_math += 1
            except Exception:
                continue
    except Exception:
        restored_math = 0
    if restored_math > 0:
        logger(f"Word export: formula font '{target_math}', runs={restored_math}")
    return restored_math


def apply_word_handwriting_font(
    doc,
    font_name: str,
    logger,
    math_font: Optional[str] = None,
) -> Tuple[bool, int]:
    target = _normalize_word_font_name(font_name, default=normalize_handwriting_font_name(font_name))
    try:
        doc.Content.Font.Name = target
        try:
            doc.Content.Font.NameAscii = target
            doc.Content.Font.NameFarEast = target
            doc.Content.Font.NameOther = target
        except Exception:
            pass
    except Exception as exc:
        logger(f"Word handwriting mode warning: cannot force font '{target}': {exc}")
        return False, 0

    restored_math = _apply_word_formula_font(doc, math_font, logger)
    logger(
        f"Word handwriting mode: forcing font '{target}' before PDF export; "
        f"math_runs_restored={restored_math}"
    )
    return True, restored_math


def word_to_pdf(
    word_path: Path,
    pdf_path: Path,
    logger,
    override_font: Optional[str] = None,
    formula_font: Optional[str] = None,
) -> None:
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
    try:
        app = win32com.client.gencache.EnsureDispatch("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0

        def _export_once(font_override: Optional[str]) -> None:
            doc = None
            try:
                doc = app.Documents.Open(
                    str(word_abs),
                    ConfirmConversions=False,
                    ReadOnly=False,
                    AddToRecentFiles=False,
                )
                if font_override:
                    # Apply in-memory only (document is closed without save).
                    apply_word_handwriting_font(doc, font_override, logger, math_font=formula_font)
                elif formula_font:
                    _apply_word_formula_font(doc, formula_font, logger)
                # Word Export format constants:
                # 17 = wdExportFormatPDF
                # Keep call minimal/positional for compatibility across Office versions.
                doc.ExportAsFixedFormat(str(pdf_abs), 17)
                if not pdf_abs.exists() or pdf_abs.stat().st_size == 0:
                    raise RuntimeError(f"Word->PDF produced no output: {pdf_abs}")
            finally:
                if doc is not None:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass

        # First pass: requested mode (with optional handwriting font).
        _export_once(override_font if override_font else None)

        # Safety fallback: if forced handwriting font produced many "?" symbols,
        # re-export with native fonts to preserve readable content.
        if override_font:
            qm = pdf_text_questionmark_metrics(pdf_abs, logger=logger)
            if qm is not None:
                ratio, qmarks, meaningful = qm
                if qmarks >= int(HANDWRITING_WORD_MAX_QMARK_COUNT) and ratio >= float(HANDWRITING_WORD_MAX_QMARK_RATIO):
                    logger(
                        "Word handwriting mode warning: exported PDF looks garbled "
                        f"(qmarks={qmarks}/{meaningful}, ratio={ratio:.3f}). "
                        "Retrying export with native fonts to preserve text."
                    )
                    try:
                        if pdf_abs.exists():
                            pdf_abs.unlink()
                    except Exception:
                        pass
                    _export_once(None)
    except Exception as exc:
        raise RuntimeError(f"Word conversion failed: {exc}") from exc
    finally:
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
        if not _wait_until_path_unlocked(pdf_abs, timeout_s=8.0, poll_s=0.25):
            logger(
                "Warning: Word->PDF output file is still locked after export. "
                "Continuing with best effort."
            )


def _wait_for_nonempty_file(path: Path, timeout_s: float = 15.0, poll_s: float = 0.25, stable_polls: int = 2) -> bool:
    deadline = time.time() + max(0.1, float(timeout_s))
    poll = max(0.05, float(poll_s))
    stable_need = max(1, int(stable_polls))
    last_size = -1
    stable = 0

    while time.time() < deadline:
        try:
            if path.exists():
                sz = int(path.stat().st_size)
                if sz > 0:
                    if sz == last_size:
                        stable += 1
                    else:
                        stable = 1
                    last_size = sz
                    if stable >= stable_need:
                        return True
        except Exception:
            pass
        time.sleep(poll)
    return False


def _wait_until_path_unlocked(path: Path, timeout_s: float = 8.0, poll_s: float = 0.20) -> bool:
    deadline = time.time() + max(0.2, float(timeout_s))
    poll = max(0.05, float(poll_s))
    while time.time() < deadline:
        try:
            if not path.exists():
                return True
            with path.open("rb"):
                pass
            return True
        except Exception:
            time.sleep(poll)
    return False


def _kompas_print_to_pdf(input_path: Path, output_pdf: Path, logger) -> None:
    import win32com.client

    pythoncom = None
    try:
        import pythoncom as _pythoncom  # type: ignore

        _pythoncom.CoInitialize()
        pythoncom = _pythoncom
    except Exception:
        pythoncom = None

    app = None
    try:
        app = None
        last_exc: Optional[Exception] = None
        for progid in ("KOMPAS.Application.7", "KOMPAS.Application"):
            try:
                logger(f"KOMPAS dispatch: {progid}")
                app = win32com.client.gencache.EnsureDispatch(progid)
                break
            except Exception as exc:
                last_exc = exc
                app = None
        if app is None:
            raise RuntimeError(f"KOMPAS COM application is unavailable: {last_exc}")

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

        for attempt in range(1, 4):
            try:
                if output_pdf.exists():
                    output_pdf.unlink()
            except Exception:
                pass
            try:
                print_job.Clear()
            except Exception:
                pass

            logger(f"PrintJob.AddSheets (attempt {attempt}): {input_path}")
            print_job.AddSheets(str(input_path), 0, 0)
            logger(f"PrintJob.Execute (attempt {attempt}): {output_pdf}")
            result = print_job.Execute(str(output_pdf))
            logger(f"PrintJob.Execute result (attempt {attempt}): {result!r}")

            if _wait_for_nonempty_file(output_pdf, timeout_s=18.0):
                return
            time.sleep(0.6)

        raise RuntimeError(f"KOMPAS PrintJob completed without PDF output: {output_pdf}")
    finally:
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

    frw_abs = frw_path.resolve()
    pdf_abs = pdf_path.resolve()
    pdf_abs.parent.mkdir(parents=True, exist_ok=True)
    if not frw_abs.exists():
        raise RuntimeError(f"CAD file not found: {frw_abs}")

    try:
        import win32com.client
    except Exception as exc:
        raise RuntimeError("pywin32 is required to convert CAD formats. Install with: pip install pywin32") from exc

    primary_error: Optional[Exception] = None
    try:
        # KOMPAS can fail on non-ASCII source paths depending on locale/settings.
        # Copy to a short ASCII temp name first.
        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
            work = Path(td)
            src_local = work / f"source{frw_abs.suffix.lower()}"
            out_local = work / "export.pdf"
            shutil.copyfile(str(frw_abs), str(src_local))

            _kompas_print_to_pdf(src_local, out_local, logger)
            if not _wait_for_nonempty_file(out_local, timeout_s=6.0):
                raise RuntimeError(f"CAD->PDF produced no output: {out_local}")

            shutil.copyfile(str(out_local), str(pdf_abs))
            if not _wait_for_nonempty_file(pdf_abs, timeout_s=2.0):
                raise RuntimeError(f"Failed to finalize CAD PDF output: {pdf_abs}")
            return
    except Exception as exc:
        primary_error = exc
        logger(f"Warning: primary CAD conversion failed: {exc}")

    # Fallback: if source folder already has an exported PDF with same stem, reuse it.
    fallback_pdf = frw_abs.with_suffix(".pdf")
    if fallback_pdf.exists() and _wait_for_nonempty_file(fallback_pdf, timeout_s=0.5):
        logger(f"Using fallback PDF next to source: {fallback_pdf}")
        shutil.copyfile(str(fallback_pdf), str(pdf_abs))
        if _wait_for_nonempty_file(pdf_abs, timeout_s=2.0):
            return

    raise RuntimeError(f"CAD conversion failed: {primary_error}")

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

    def _load_sender_module():
        # In frozen builds, launching sys.executable opens PlotterStudio.exe again.
        # Import sender module and run it in-process to avoid recursive GUI spawn.
        module_name = "_plotter_sender_inline"
        existing = sys.modules.get(module_name)
        if existing is not None:
            return existing
        spec = importlib.util.spec_from_file_location(module_name, str(sender))
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load send_grbl_file.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _run_sender_inline() -> Tuple[int, List[str], Optional[float], float]:
        sender_mod = _load_sender_module()
        out_lines: List[str] = []
        sender_plot_time_s: Optional[float] = None
        started_local = time.perf_counter()

        original_print = getattr(sender_mod, "_safe_print", None)
        original_enabled = getattr(sender_mod, "_PRINT_ENABLED", True)

        def _forward_print(*args, **kwargs):
            nonlocal sender_plot_time_s
            line = " ".join(str(a) for a in args).strip()
            if not line:
                return
            out_lines.append(line)
            logger(line)
            if line.startswith("PLOT_TIME_SECONDS="):
                try:
                    sender_plot_time_s = float(line.split("=", 1)[1].strip())
                except Exception:
                    pass

        try:
            sender_mod._PRINT_ENABLED = True
            sender_mod._safe_print = _forward_print
            argv = ["send_grbl_file.py", com, baud, str(gcode_file)]
            if sleep_after:
                argv.append("--sleep")
            rc = int(sender_mod.main(argv))
        finally:
            if original_print is not None:
                sender_mod._safe_print = original_print
            sender_mod._PRINT_ENABLED = original_enabled

        elapsed_local = time.perf_counter() - started_local
        return rc, out_lines, sender_plot_time_s, elapsed_local

    logger("Sending to Grbl ...")
    use_inline = bool(getattr(sys, "frozen", False)) or os.environ.get("PLOTTER_INLINE_SENDER") == "1"

    if use_inline:
        rc, out_lines, sender_plot_time_s, elapsed = _run_sender_inline()
    else:
        cmd = [sys.executable, str(sender), com, baud, str(gcode_file)]
        if sleep_after:
            cmd.append("--sleep")
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
        out_lines = []
        sender_plot_time_s = None
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
    global HANDWRITING_STROKE_ACTIVE
    global HANDWRITING_CYRILLIC_ACTIVE
    try:
        HANDWRITING_STROKE_ACTIVE = False
        HANDWRITING_CYRILLIC_ACTIVE = False
        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
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
                word_font_override: Optional[str] = None
                if HANDWRITING_TEXT_ENABLED and HANDWRITING_WORD_FORCE_FONT_EXPORT:
                    word_font_override = normalize_handwriting_font_name(HANDWRITING_FONT_FAMILY)
                word_to_pdf(
                    input_path,
                    pdf_tmp,
                    log,
                    override_font=word_font_override,
                )
                pdf_to_svg(pdf_tmp, svg_path, log)
                if HANDWRITING_TEXT_ENABLED and not HANDWRITING_WORD_FORCE_FONT_EXPORT:
                    try:
                        has_text_after_first_pass = svg_has_text_nodes(svg_path)
                    except Exception:
                        has_text_after_first_pass = False
                    if not has_text_after_first_pass:
                        forced_font = normalize_handwriting_font_name(HANDWRITING_FONT_FAMILY)
                        log(
                            "Handwriting fallback: SVG has no editable text after initial conversion; "
                            f"retrying Word->PDF with forced font '{forced_font}'."
                        )
                        pdf_tmp_hw = work / "source_hwfont.pdf"
                        word_to_pdf(
                            input_path,
                            pdf_tmp_hw,
                            log,
                            override_font=forced_font,
                        )
                        pdf_to_svg(pdf_tmp_hw, svg_path, log)
            elif ext in {".frw", ".cdw"}:
                pdf_tmp = work / "source.pdf"
                frw_to_pdf(input_path, pdf_tmp, log)
                pdf_to_svg(pdf_tmp, svg_path, log)
            else:
                pdf_to_svg(input_path, svg_path, log)

            log(
                f"Text render mode: handwriting={'on' if HANDWRITING_TEXT_ENABLED else 'off'} "
                f"font='{normalize_handwriting_font_name(HANDWRITING_FONT_FAMILY)}'; "
                f"image_contours={normalize_image_contour_mode(IMAGE_CONTOUR_MODE)}"
            )

            try:
                has_text_nodes = svg_has_text_nodes(svg_path)
                used_stroke_text = False
                if has_text_nodes and HANDWRITING_TEXT_ENABLED:
                    HANDWRITING_CYRILLIC_ACTIVE = svg_has_cyrillic_text_nodes(svg_path)
                if has_text_nodes:
                    if HANDWRITING_TEXT_ENABLED:
                        replaced = _replace_handwriting_text_nodes(svg_path, HANDWRITING_CYRILLIC_ACTIVE, log)
                        if replaced > 0:
                            HANDWRITING_STROKE_ACTIVE = True
                            used_stroke_text = True
                            log(f"Text nodes after stroke-font replacement: {svg_text_node_count(svg_path)}")
                        if svg_has_text_nodes(svg_path):
                            # Convert remaining unresolved text nodes to the selected
                            # handwriting family to avoid mixed non-handwritten output.
                            apply_handwriting_font(
                                svg_path,
                                _effective_handwriting_font_for_text(HANDWRITING_CYRILLIC_ACTIVE),
                                log,
                            )
                    if not convert_svg_text_to_paths(svg_path, log, text_only=used_stroke_text):
                        return False, "Text conversion did not produce valid paths."
                    if svg_has_text_nodes(svg_path):
                        return False, "Text conversion left unresolved text nodes."
                    log(f"Text nodes after conversion: {svg_text_node_count(svg_path)}")
            except Exception as exc:
                return False, f"Text->path conversion failed: {exc}"

            log("Extracting paths from SVG ...")
            path_items = extract_polylines(svg_path)
            add_image_contours = image_contours_enabled_for_input(input_is_word)
            if add_image_contours:
                image_items = extract_image_contour_items(
                    svg_path,
                    logger=log,
                    enable_hatch=image_hatch_enabled_for_input(input_is_word),
                )
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
            if HANDWRITING_TEXT_ENABLED and not HANDWRITING_STROKE_ACTIVE:
                stitch_eps = HANDWRITING_STITCH_EPS_MM
                stitch_gap_eps = HANDWRITING_STITCH_GAP_EPS_MM
                stitch_angle = HANDWRITING_STITCH_GAP_MAX_ANGLE_DEG
            else:
                stitch_eps = STITCH_EPS_MM
                stitch_gap_eps = STITCH_GAP_EPS_MM
                stitch_angle = STITCH_GAP_MAX_ANGLE_DEG
            polylines = stitch_polylines(
                polylines,
                stitch_eps,
                logger=log,
                gap_eps=stitch_gap_eps,
                angle_tol_deg=stitch_angle,
            )
            polylines = reorder_polylines(polylines, logger=log)
            if HANDWRITING_TEXT_ENABLED and not HANDWRITING_STROKE_ACTIVE:
                # Fallback path-only handwriting (no editable text nodes): avoid aggressive
                # word merge/smoothing that can cross-connect contour fragments.
                log("Handwriting fallback: skipping word-merge/smoothing for contour-only text source.")
            if TOOL_MODE == "pencil":
                before_natural_segments = sum(max(0, len(p) - 1) for p in polylines)
                polylines = humanize_pencil_polylines(
                    polylines,
                    logger=log,
                    handwriting_enabled=HANDWRITING_TEXT_ENABLED,
                )
                polylines = clip_polylines_to_work_area(polylines, logger=log)
                after_natural_segments = sum(max(0, len(p) - 1) for p in polylines)
                if after_natural_segments != before_natural_segments:
                    log(f"Pencil naturalization segments: {before_natural_segments} -> {after_natural_segments}")
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
            write_xy_gcode(
                xy_path,
                polylines,
                feed_travel,
                feed_draw,
                join_eps=(HANDWRITING_CONTINUOUS_JOIN_EPS if HANDWRITING_TEXT_ENABLED else CONTINUOUS_JOIN_EPS),
            )
            log("Applying pen-up / pen-down ...")
            apply_penlift(
                xy_path,
                pen_path,
                z_down=effective_z_down,
                dynamic_z_enable=(TOOL_MODE == "pencil"),
                dynamic_base_z_down=PENCIL_BASE_Z_DOWN if TOOL_MODE == "pencil" else None,
                dynamic_initial_wear_mm=dynamic_wear_start,
                handwriting_mode=HANDWRITING_TEXT_ENABLED,
            )
            make_final_with_preamble(pen_path, final_path)
            gcode_lines, gcode_draw, gcode_travel, gcode_bounds = summarize_gcode_file(final_path)
            log(
                f"G-code stats: lines={gcode_lines}, draw={gcode_draw}, travel={gcode_travel}, "
                f"bounds={gcode_bounds[0]:.3f}..{gcode_bounds[1]:.3f} x, "
                f"{gcode_bounds[2]:.3f}..{gcode_bounds[3]:.3f} y"
            )
            pf_ok, pf_msg = preflight_check_gcode(final_path, logger=log)
            if not pf_ok:
                return False, f"Preflight failed: {pf_msg}"
            log(f"Preflight: {pf_msg}")

            saved_target: Optional[Path] = None
            if output_path is not None:
                saved_target = output_path
                saved_target.parent.mkdir(parents=True, exist_ok=True)
                saved_target.write_text(final_path.read_text(encoding="utf-8"), encoding="utf-8")
                target_lines, target_draw, target_travel, target_bounds = summarize_gcode_file(saved_target)
                log(
                    f"Saved file stats: lines={target_lines}, draw={target_draw}, travel={target_travel}, "
                    f"bounds={target_bounds[0]:.3f}..{target_bounds[1]:.3f} x, "
                    f"{target_bounds[2]:.3f}..{target_bounds[3]:.3f} y"
                )
                log(f"Saved: {saved_target}")

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
                if saved_target is not None:
                    return_msg += f"; gcode_copy={saved_target}"
            else:
                target = saved_target
                if target is None:
                    target = input_path.with_name(f"{input_path.stem}_prepared.nc")
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
        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
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

        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
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

        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
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


def _strip_gcode_comments(line: str) -> str:
    s = (line or "").strip()
    if not s:
        return ""
    if ";" in s:
        s = s.split(";", 1)[0].strip()
    # Remove parenthesized comments conservatively.
    while "(" in s and ")" in s:
        a = s.find("(")
        b = s.find(")", a + 1)
        if b < 0:
            break
        s = (s[:a] + " " + s[b + 1 :]).strip()
    return s


def _pen_down_from_z_level(cur_z: float, z_up: float, z_down: float) -> bool:
    rng = abs(float(z_down) - float(z_up))
    if rng <= 1e-9:
        return True
    tol = max(0.05, rng * 0.18)
    if z_down >= z_up:
        return cur_z >= (z_down - tol)
    return cur_z <= (z_down + tol)


def _gcode_draw_bounds(gcode_path: Path, *, z_up: float, z_down: float) -> Optional[Tuple[float, float, float, float]]:
    x_re = re.compile(r"\bX(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    y_re = re.compile(r"\bY(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    z_re = re.compile(r"\bZ(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    i_re = re.compile(r"\bI(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    j_re = re.compile(r"\bJ(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    g_re = re.compile(r"\bG(\d+(?:\.\d+)?)")
    m_re = re.compile(r"\bM(\d+(?:\.\d+)?)")

    cur_x = 0.0
    cur_y = 0.0
    cur_z = float(z_up)
    abs_mode = True
    ijk_abs = False
    pen_down = _pen_down_from_z_level(cur_z, z_up, z_down)
    last_motion: Optional[int] = None

    min_x = math.inf
    max_x = -math.inf
    min_y = math.inf
    max_y = -math.inf

    def _expand(x0: float, x1: float, y0: float, y1: float) -> None:
        nonlocal min_x, max_x, min_y, max_y
        min_x = min(min_x, x0)
        max_x = max(max_x, x1)
        min_y = min(min_y, y0)
        max_y = max(max_y, y1)

    with gcode_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            body = _strip_gcode_comments(raw)
            if not body:
                continue

            motion: Optional[int] = None
            for gm in g_re.findall(body):
                try:
                    gval = float(gm)
                except Exception:
                    continue
                if abs(gval - 90.0) <= 1e-9:
                    abs_mode = True
                elif abs(gval - 91.0) <= 1e-9:
                    abs_mode = False
                elif abs(gval - 90.1) <= 1e-9:
                    ijk_abs = True
                elif abs(gval - 91.1) <= 1e-9:
                    ijk_abs = False
                elif abs(gval - 0.0) <= 1e-9:
                    motion = 0
                elif abs(gval - 1.0) <= 1e-9:
                    motion = 1
                elif abs(gval - 2.0) <= 1e-9:
                    motion = 2
                elif abs(gval - 3.0) <= 1e-9:
                    motion = 3
            if motion is None:
                motion = last_motion
            else:
                last_motion = motion

            for mm in m_re.findall(body):
                try:
                    mval = int(float(mm))
                except Exception:
                    continue
                if mval == 3:
                    pen_down = True
                elif mval == 5:
                    pen_down = False

            mz = z_re.search(body)
            if mz:
                try:
                    z_val = float(mz.group(1))
                    cur_z = z_val if abs_mode else (cur_z + z_val)
                    pen_down = _pen_down_from_z_level(cur_z, z_up, z_down)
                except Exception:
                    pass

            sx = x_re.search(body)
            sy = y_re.search(body)
            has_xy = sx is not None or sy is not None
            tx = cur_x
            ty = cur_y
            if sx:
                try:
                    xv = float(sx.group(1))
                    tx = xv if abs_mode else (cur_x + xv)
                except Exception:
                    tx = cur_x
            if sy:
                try:
                    yv = float(sy.group(1))
                    ty = yv if abs_mode else (cur_y + yv)
                except Exception:
                    ty = cur_y

            if pen_down and has_xy and motion in {1, 2, 3}:
                if motion in {2, 3}:
                    si = i_re.search(body)
                    sj = j_re.search(body)
                    if si and sj:
                        try:
                            i_val = float(si.group(1))
                            j_val = float(sj.group(1))
                            center = (i_val, j_val) if ijk_abs else (cur_x + i_val, cur_y + j_val)
                            if points_distance((cur_x, cur_y), (tx, ty)) <= 1e-6:
                                r = math.hypot(cur_x - center[0], cur_y - center[1])
                                _expand(center[0] - r, center[0] + r, center[1] - r, center[1] + r)
                            else:
                                ax0, ax1, ay0, ay1 = arc_extents_xy((cur_x, cur_y), (tx, ty), center, cw=(motion == 2))
                                _expand(ax0, ax1, ay0, ay1)
                        except Exception:
                            _expand(min(cur_x, tx), max(cur_x, tx), min(cur_y, ty), max(cur_y, ty))
                    else:
                        _expand(min(cur_x, tx), max(cur_x, tx), min(cur_y, ty), max(cur_y, ty))
                else:
                    _expand(min(cur_x, tx), max(cur_x, tx), min(cur_y, ty), max(cur_y, ty))

            if has_xy:
                cur_x, cur_y = tx, ty

    if min_x == math.inf:
        return None
    return min_x, max_x, min_y, max_y


def preflight_check_gcode(
    gcode_path: Path,
    logger=print,
    *,
    bounds: Optional[Tuple[float, float, float, float]] = None,
) -> Tuple[bool, str]:
    if not PREFLIGHT_ENABLED:
        return True, "disabled"

    lines, draw_moves, travel_moves, g_bounds = summarize_gcode_file(gcode_path)
    if lines <= 0:
        return False, "empty or invalid G-code."
    if draw_moves <= 0:
        return False, "no drawing moves (G1/G2/G3)."
    if lines > int(PREFLIGHT_MAX_GCODE_LINES):
        return False, f"too many G-code lines: {lines} > {int(PREFLIGHT_MAX_GCODE_LINES)}."

    ratio = float(travel_moves) / max(1.0, float(draw_moves))
    if ratio > float(PREFLIGHT_MAX_TRAVEL_TO_DRAW_RATIO):
        logger(
            "Preflight warning: high travel ratio "
            f"{ratio:.2f} (travel={travel_moves}, draw={draw_moves}). "
            "Trajectory may be inefficient."
        )

    min_x, max_x, min_y, max_y = bounds if bounds is not None else work_area_bounds()
    margin = max(0.0, float(PREFLIGHT_BOUNDS_MARGIN_MM))
    gx0, gx1, gy0, gy1 = g_bounds

    # Bounds safety should validate drawing geometry (pen-down), not all travel/home moves.
    # This avoids false-positive area errors when trailer parks at Y=0 outside active draw Y range.
    draw_bounds = None
    try:
        draw_bounds = _gcode_draw_bounds(gcode_path, z_up=float(Z_UP), z_down=float(Z_DOWN))
    except Exception:
        draw_bounds = None
    if draw_bounds is not None:
        gx0, gx1, gy0, gy1 = draw_bounds

    if (
        gx0 < (min_x - margin)
        or gx1 > (max_x + margin)
        or gy0 < (min_y - margin)
        or gy1 > (max_y + margin)
    ):
        return (
            False,
            "geometry exceeds active area: "
            f"gcode x({gx0:.3f},{gx1:.3f}) y({gy0:.3f},{gy1:.3f}) vs "
            f"area x({min_x:.3f},{max_x:.3f}) y({min_y:.3f},{max_y:.3f}) (margin {margin:.3f}).",
        )

    return (
        True,
        f"ok: lines={lines}, draw={draw_moves}, travel={travel_moves}, ratio={ratio:.2f}",
    )


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
    serial_timeout_s: float = 1.0,
    wake_delay_s: float = 0.20,
    reset_delay_s: float = 1.0,
    command_delay_s: float = 0.16,
    tail_delay_s: float = 0.35,
    wake_read_bytes: int = 4096,
    tail_read_bytes: int = 8192,
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
    timeout_s = max(0.05, float(serial_timeout_s))
    wake_delay = max(0.0, float(wake_delay_s))
    reset_delay = max(0.0, float(reset_delay_s))
    command_delay = max(0.0, float(command_delay_s))
    tail_delay = max(0.0, float(tail_delay_s))
    wake_read = max(0, int(wake_read_bytes))
    tail_read = max(0, int(tail_read_bytes))
    try:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud_i
        ser.timeout = timeout_s
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        ser.open()

        # Wake channel.
        ser.write(b"\r\n")
        ser.flush()
        time.sleep(wake_delay)
        if wake_read > 0:
            ser.read(wake_read)

        if soft_reset_first:
            ser.write(b"\x18")
            ser.flush()
            time.sleep(reset_delay)
            if wake_read > 0:
                ser.read(wake_read)

        for cmd in commands:
            line = (cmd or "").strip()
            if not line:
                continue
            ser.write((line + "\n").encode("ascii", errors="replace"))
            ser.flush()
            time.sleep(command_delay)

        if not read_tail:
            return True, "ok"

        time.sleep(tail_delay)
        tail = ser.read(tail_read).decode("ascii", errors="replace").strip() if tail_read > 0 else ""
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
        cmds = ["$X", "M5", "$1=0", "?"]
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
    global Z_PROFILE_CLI_OVERRIDE
    global DRAW_ORDER_MODE
    global DRAW_ORDER_LINE_TOL_MM
    global HANDWRITING_TEXT_ENABLED
    global HANDWRITING_FONT_FAMILY
    global HANDWRITING_CYRILLIC_FONT_FAMILY
    global HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED
    global HANDWRITING_SINGLELINE_TTF_BACKEND
    global IMAGE_CONTOUR_MODE
    global IMAGE_CONTOUR_ENABLED
    global IMAGE_CONTOUR_WORD_ONLY
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
    parser.add_argument(
        "--draw-order",
        default=DRAW_ORDER_MODE,
        choices=["auto", "nearest", "source", "line_lr"],
        help="Polyline order mode: auto, nearest (fastest), source (as in file), line_lr (top->bottom, left->right).",
    )
    parser.add_argument(
        "--draw-order-line-tol-mm",
        type=float,
        default=DRAW_ORDER_LINE_TOL_MM,
        help="Row clustering tolerance for --draw-order line_lr (mm).",
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
    parser.add_argument(
        "--handwriting",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable handwriting font replacement for text before vectorization.",
    )
    parser.add_argument(
        "--handwriting-font",
        default=None,
        help="Font family for handwriting mode (example: Marck Script).",
    )
    parser.add_argument(
        "--handwriting-direct-vector",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Prefer direct vector stroke-font conversion for text (no raster/skeleton stage).",
    )
    parser.add_argument(
        "--handwriting-centerline-backend",
        choices=["auto", "skeleton", "autotrace3"],
        default=None,
        help="Centerline backend for TTF handwriting mode: auto | skeleton | autotrace3.",
    )
    parser.add_argument(
        "--image-contours-mode",
        choices=["off", "word_only", "always"],
        default=None,
        help="Raster contour extraction mode: off | word_only | always.",
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
    DRAW_ORDER_MODE = (args.draw_order or DRAW_ORDER_MODE).strip().lower()
    DRAW_ORDER_LINE_TOL_MM = max(0.2, float(args.draw_order_line_tol_mm))
    Z_PROFILE_CLI_OVERRIDE = any(
        v is not None
        for v in (
            args.z_delay_down,
            args.z_delay_up,
            args.z_feed_down_approach,
            args.z_feed_down_touch,
            args.z_feed_up,
            args.z_feed_up_final,
            args.z_soft_down_mm,
            args.z_soft_up_mm,
            args.z_travel_lift_mm,
        )
    )
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
    if args.handwriting is not None:
        HANDWRITING_TEXT_ENABLED = bool(args.handwriting)
    if args.handwriting_font is not None and str(args.handwriting_font).strip():
        normalized_hw = normalize_handwriting_font_name(args.handwriting_font)
        HANDWRITING_FONT_FAMILY = normalized_hw
        # Keep one explicit CLI font for both Latin and Cyrillic selection paths.
        HANDWRITING_CYRILLIC_FONT_FAMILY = normalized_hw
    if args.handwriting_direct_vector is not None:
        HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED = bool(args.handwriting_direct_vector)
    if args.handwriting_centerline_backend is not None:
        HANDWRITING_SINGLELINE_TTF_BACKEND = _normalize_singleline_ttf_backend(args.handwriting_centerline_backend)
    if args.image_contours_mode is not None:
        IMAGE_CONTOUR_MODE = normalize_image_contour_mode(args.image_contours_mode)
        IMAGE_CONTOUR_ENABLED = IMAGE_CONTOUR_MODE != "off"
        IMAGE_CONTOUR_WORD_ONLY = IMAGE_CONTOUR_MODE == "word_only"

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


