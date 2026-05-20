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
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
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

try:
    from src.plotter_backend.converters import cad_converter as cad_converter_mod
    from src.plotter_backend import cli_entry as cli_entry_mod
    from src.plotter_backend import common_utils as common_utils_mod
    from src.plotter_backend import discovery as discovery_mod
    from src.plotter_backend import formula_image_ocr as formula_image_ocr_mod
    from src.plotter_backend import handwriting_text_utils as handwriting_text_utils_mod
    from src.plotter_backend import pencil_state as pencil_state_mod
    from src.plotter_backend import process_utils as process_utils_mod
    from src.plotter_backend import runtime_utils as runtime_utils_mod
    from src.plotter_backend import svg_filter_utils as svg_filter_utils_mod
    from src.plotter_backend import svg_text_utils as svg_text_utils_mod
    from src.plotter_backend.converters import pdf_converter as pdf_converter_mod
    from src.plotter_backend.converters import word_converter as word_converter_mod
    from src.plotter_backend.errors import BackendError, ConversionError, SerialTransportError, ToolDependencyError
    from src.plotter_backend.geometry import arc_fit as geometry_arc_fit_mod
    from src.plotter_backend.geometry import clipping as geometry_clipping_mod
    from src.plotter_backend.geometry import fitting as geometry_fitting_mod
    from src.plotter_backend.geometry import hatching as geometry_hatching_mod
    from src.plotter_backend.geometry import path_processing as geometry_path_processing_mod
    from src.plotter_backend.geometry import polyline as geometry_polyline_mod
    from src.plotter_backend.geometry import sheet_tiling as geometry_sheet_tiling_mod
    from src.plotter_backend.geometry import simplify as geometry_simplify_mod
    from src.plotter_backend.geometry import svg_path as geometry_svg_path_mod
    from src.plotter_backend.geometry import transform as geometry_transform_mod
    from src.plotter_backend.geometry import work_area as geometry_work_area_mod
    from src.plotter_backend.gcode import bounds as gcode_bounds_mod
    from src.plotter_backend.gcode import finalize as gcode_finalize_mod
    from src.plotter_backend.gcode import penlift as gcode_penlift_mod
    from src.plotter_backend.gcode import preflight as gcode_preflight_mod
    from src.plotter_backend.gcode import stats as gcode_stats_mod
    from src.plotter_backend.machine import grbl_sender as grbl_sender_mod
    from src.plotter_backend.machine import grbl_probe as grbl_probe_mod
    from src.plotter_backend.machine import manual_commands as manual_commands_mod
except Exception:
    from plotter_backend import cli_entry as cli_entry_mod
    from plotter_backend import common_utils as common_utils_mod
    from plotter_backend import discovery as discovery_mod
    from plotter_backend import formula_image_ocr as formula_image_ocr_mod
    from plotter_backend import handwriting_text_utils as handwriting_text_utils_mod
    from plotter_backend import pencil_state as pencil_state_mod
    from plotter_backend import process_utils as process_utils_mod
    from plotter_backend import runtime_utils as runtime_utils_mod
    from plotter_backend import svg_filter_utils as svg_filter_utils_mod
    from plotter_backend import svg_text_utils as svg_text_utils_mod
    from plotter_backend.converters import cad_converter as cad_converter_mod
    from plotter_backend.converters import pdf_converter as pdf_converter_mod
    from plotter_backend.converters import word_converter as word_converter_mod
    from plotter_backend.errors import BackendError, ConversionError, SerialTransportError, ToolDependencyError
    from plotter_backend.geometry import arc_fit as geometry_arc_fit_mod
    from plotter_backend.geometry import clipping as geometry_clipping_mod
    from plotter_backend.geometry import fitting as geometry_fitting_mod
    from plotter_backend.geometry import hatching as geometry_hatching_mod
    from plotter_backend.geometry import path_processing as geometry_path_processing_mod
    from plotter_backend.geometry import polyline as geometry_polyline_mod
    from plotter_backend.geometry import sheet_tiling as geometry_sheet_tiling_mod
    from plotter_backend.geometry import simplify as geometry_simplify_mod
    from plotter_backend.geometry import svg_path as geometry_svg_path_mod
    from plotter_backend.geometry import transform as geometry_transform_mod
    from plotter_backend.geometry import work_area as geometry_work_area_mod
    from plotter_backend.gcode import bounds as gcode_bounds_mod
    from plotter_backend.gcode import finalize as gcode_finalize_mod
    from plotter_backend.gcode import penlift as gcode_penlift_mod
    from plotter_backend.gcode import preflight as gcode_preflight_mod
    from plotter_backend.gcode import stats as gcode_stats_mod
    from plotter_backend.machine import grbl_sender as grbl_sender_mod
    from plotter_backend.machine import grbl_probe as grbl_probe_mod
    from plotter_backend.machine import manual_commands as manual_commands_mod

CYRILLIC_TEXT_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F]")


def _force_utf8_stdio() -> None:
    common_utils_mod.force_utf8_stdio(sys_module=sys)


def _strip_unpaired_surrogates(text: str, replacement: str = " ") -> str:
    return common_utils_mod.strip_unpaired_surrogates(text, replacement=replacement)


def _safe_log_text(value: object) -> str:
    return common_utils_mod.safe_log_text(value)


def _safe_logger(logger):
    return common_utils_mod.safe_logger(logger)


def _resolve_bundle_root() -> Path:
    return common_utils_mod.resolve_bundle_root(file_path=__file__, sys_module=sys)


def _resolve_work_root(bundle_root: Path) -> Path:
    return common_utils_mod.resolve_work_root(bundle_root, sys_module=sys)


ROOT_DIR = _resolve_bundle_root()
WORK_ROOT = _resolve_work_root(ROOT_DIR)
CONFIG_DIR = WORK_ROOT / "config"
BUNDLE_CONFIG_DIR = ROOT_DIR / "config"
AXIS_PROFILE_PATH = CONFIG_DIR / "axis_profile.json"
AXIS_PROFILE_FALLBACK_PATH = BUNDLE_CONFIG_DIR / "axis_profile.json"
LOCAL_TMP_ROOT = WORK_ROOT / "_tmp"

DEFAULT_COM_PORT = "COM6"
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
# Drawing jobs with pencil should use a short lift for speed (target ~3-4 mm).
Z_TRAVEL_LIFT_MM = 3.5
# Full Z_UP travel between contours (mainly useful for pen/marker mode on uneven media).
SAFE_PEN_TRAVEL_UP = False

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
TECH_TEXT_JOIN_ENABLE = True
TECH_TEXT_JOIN_GAP_MM = 0.55
TECH_TEXT_JOIN_MAX_DY_MM = 0.75
TECH_TEXT_JOIN_MAX_BACKTRACK_MM = 0.25
TECH_TEXT_JOIN_MAX_STROKE_LEN_MM = 10.0
TECH_TEXT_JOIN_MAX_SPAN_MM = 12.0
TECH_TEXT_JOIN_MAX_AREA_MM2 = 42.0
TECH_TEXT_JOIN_MAX_COMBINED_SPAN_X_MM = 12.0
TECH_TEXT_JOIN_MAX_COMBINED_SPAN_Y_MM = 10.0
TECH_TEXT_JOIN_MAX_COMBINED_AREA_MM2 = 80.0
TECH_TEXT_SINGLELINE_OPT_ENABLE = False
TECH_TEXT_CLUSTER_STITCH_ENABLE = False
TECH_TEXT_REORDER_OPT_ENABLE = False
TECH_TEXT_PENLIFT_OPT_ENABLE = False
TECH_TEXT_PENLIFT_SHORT_TRAVEL_MM = 0.60
TECH_TEXT_PENLIFT_SHORT_TRAVEL_FEED = 5000.0
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
# Remove retraced/overlapping vector strokes that make technical lines look bold.
# Conservative tolerances keep real parallel frame/table lines intact.
COLLINEAR_OVERLAP_DEDUP_ENABLED = True
COLLINEAR_OVERLAP_DEDUP_DIST_MM = 0.12
COLLINEAR_OVERLAP_DEDUP_ANGLE_DEG = 1.0
COLLINEAR_OVERLAP_DEDUP_MIN_LEN_MM = 0.40
COLLINEAR_OVERLAP_DEDUP_MIN_RATIO = 0.90
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
# Physical sheet alignment: shift every generated drawing 5 mm up.
# In this machine coordinate system, paper-up is negative Y.
WORK_OFFSET_Y_MM = -5.0
PAGE_MARGIN_LEFT_MM = 20.5
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
IMAGE_CONTOUR_LINEART_AUTOTRACE = True
IMAGE_CONTOUR_LINEART_DARK_RATIO_MAX = 0.34
IMAGE_CONTOUR_LINEART_INK_FILL_MAX = 0.58
IMAGE_CONTOUR_FORMULA_ASPECT_MIN = 5.0
IMAGE_CONTOUR_FORMULA_MAX_HEIGHT_PX = 180
IMAGE_CONTOUR_FORMULA_MIN_PATH_MM = 0.22
IMAGE_CONTOUR_FORMULA_SIMPLIFY_MM = 0.045
IMAGE_CONTOUR_FORMULA_TINY_BBOX_MM = 0.18
IMAGE_CONTOUR_FORMULA_MIN_COMPONENT_PX = 2
IMAGE_CONTOUR_FORMULA_RDP_PX = 0.42
IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE = "centerline"  # edge | centerline | auto
IMAGE_CONTOUR_FORMULA_OCR_ENABLED = True
IMAGE_CONTOUR_FORMULA_OCR_MIN_CONFIDENCE = 0.88
IMAGE_CONTOUR_LINEART_MIN_PATH_MM = 0.45
IMAGE_CONTOUR_LINEART_SIMPLIFY_MM = 0.080
IMAGE_CONTOUR_LINEART_TINY_BBOX_MM = 0.35
IMAGE_CONTOUR_LINEART_MIN_COMPONENT_PX = 3
IMAGE_CONTOUR_LINEART_RDP_PX = 0.60
IMAGE_CONTOUR_LINEART_THRESHOLD_MIN = 205
IMAGE_CONTOUR_LIGHT_LINEART_DARK_RATIO_MAX = 0.030
IMAGE_CONTOUR_SMALL_LINEART_MAX_WIDTH_PX = 420
IMAGE_CONTOUR_SMALL_LINEART_MAX_HEIGHT_PX = 260
IMAGE_CONTOUR_SMALL_LINEART_MIN_PATH_MM = 0.18
IMAGE_CONTOUR_SMALL_LINEART_SIMPLIFY_MM = 0.035
IMAGE_CONTOUR_SMALL_LINEART_TINY_BBOX_MM = 0.12
IMAGE_CONTOUR_SMALL_LINEART_MIN_COMPONENT_PX = 1
IMAGE_CONTOUR_SMALL_LINEART_RDP_PX = 0.25
IMAGE_CONTOUR_SMALL_LINEART_TRACE_SCALE = 2.0
IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_DP = 1.0
IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM1 = 80
IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2 = 10
IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_MIN_RADIUS_PX = 7
IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_MAX_RADIUS_PX = 18
IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_MIN_DIST_PX = 18
IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_STEPS = 20
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
TECH_TEXT_SINGLELINE_ENABLED = True
TECH_TEXT_MAX_BBOX_W_MM = 32.0
TECH_TEXT_MAX_BBOX_H_MM = 12.0
TECH_TEXT_MAX_BBOX_AREA_MM2 = 220.0
TECH_TEXT_MAX_TOTAL_SOURCE_LEN_MM = 900.0
TECH_TEXT_MAX_PATHS_PER_GROUP = 80
TECH_TEXT_MEDIAN_MIN_PATH_MM = 0.22
TECH_TEXT_SHORT_PATH_MM = 0.18
TECH_TEXT_SHORT_RATIO_MAX = 0.70
TECH_TEXT_MIN_PATH_MM = 0.05
TECH_TEXT_LOCAL_STITCH_EPS_MM = 0.12
TECH_TEXT_LOCAL_GAP_EPS_MM = 0.28
TECH_TEXT_LOCAL_ANGLE_DEG = 42.0
TECH_TEXT_TINY_SYMBOL_MAX_SPAN_MM = 5.2
TECH_TEXT_TINY_SYMBOL_MAX_AREA_MM2 = 18.0
# Some converters emit text as stroke-only closed outlines (double contour).
# Keep this disabled by default: on technical drawings it can collapse narrow
# glyph loops ("0", "8", degree mark) into single slashes.
SINGLE_STROKE_OUTLINE_TEXT_ENABLED = False
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
ACTIVE_SHEET_CONFIG: dict[str, object] = {
    "sheet_format": "work",
    "sheet_width_mm": None,
    "sheet_height_mm": None,
    "anchor": "center",
    "offset_x_mm": 0.0,
    "offset_y_mm": 0.0,
}
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
FLOAT_RE = re.compile(r"[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?")
TRANSFORM_RE = re.compile(r"(\w+)\(([^)]*)\)")
TAG_RE = re.compile(r".*}\s*(.*)")
VIEWBOX_RE = re.compile(
    r"\s*"
    r"([+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?)"
    r"[,\s]+"
    r"([+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?)"
    r"[,\s]+"
    r"([+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?)"
    r"[,\s]+"
    r"([+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?)"
)
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
    class _GlobalsProxy:
        def __getattr__(self, name: str):
            return globals()[name]

        def __setattr__(self, name: str, value) -> None:
            globals()[name] = value

    common_utils_mod.load_axis_profile(_GlobalsProxy())


load_axis_profile()


def tag_name(tag: str) -> str:
    return common_utils_mod.tag_name(tag, tag_re=TAG_RE)


def parse_floats(text: str) -> List[float]:
    return common_utils_mod.parse_floats(text, float_re=FLOAT_RE)


def parse_length(value: str) -> Optional[Tuple[float, str]]:
    return common_utils_mod.parse_length(value, length_re=LENGTH_RE)


TEXT_NODE_TAGS = {"text", "tspan", "textpath", "flowroot", "flowpara", "flowspan"}


def unit_to_mm(value: float, unit: str) -> float:
    return common_utils_mod.unit_to_mm(value, unit)


def run_cmd(cmd: List[str], cwd: Optional[Path] = None, timeout_s: Optional[float] = None) -> Tuple[int, str, str]:
    return process_utils_mod.run_cmd(
        cmd,
        cwd=cwd,
        timeout_s=timeout_s,
        platform=sys.platform,
        subprocess_module=subprocess,
        threading_module=threading,
        ctypes_module=ctypes,
        time_module=time,
        inkscape_auto_accept_pdf_import_dialog=bool(INKSCAPE_AUTO_ACCEPT_PDF_IMPORT_DIALOG),
        inkscape_pdf_dialog_watcher_enabled=bool(INKSCAPE_PDF_DIALOG_WATCHER_ENABLED),
        inkscape_pdf_import_dialog_titles=tuple(INKSCAPE_PDF_IMPORT_DIALOG_TITLES),
        inkscape_pdf_import_dialog_timeout_s=float(INKSCAPE_PDF_IMPORT_DIALOG_TIMEOUT_S),
    )


def format_duration_hms(seconds: float) -> str:
    return runtime_utils_mod.format_duration_hms(seconds)


def load_pencil_state() -> dict:
    return pencil_state_mod.load_pencil_state(_CLI_BACKEND)


def save_pencil_state(state: dict) -> None:
    pencil_state_mod.save_pencil_state(_CLI_BACKEND, state)


def load_pencil_profile() -> dict:
    return pencil_state_mod.load_pencil_profile(_CLI_BACKEND)


def save_pencil_profile(profile: dict) -> None:
    pencil_state_mod.save_pencil_profile(_CLI_BACKEND, profile)


def apply_pencil_profile(profile: dict) -> None:
    pencil_state_mod.apply_pencil_profile(_CLI_BACKEND, profile)


def build_pencil_profile_snapshot() -> dict:
    return pencil_state_mod.build_pencil_profile_snapshot(_CLI_BACKEND)


def save_last_wear_test_report(report: dict) -> None:
    pencil_state_mod.save_last_wear_test_report(_CLI_BACKEND, report)


def load_last_wear_test_report() -> Optional[dict]:
    return pencil_state_mod.load_last_wear_test_report(_CLI_BACKEND)


def _now_iso_utc() -> str:
    return pencil_state_mod._now_iso_utc()


def reset_pencil_state_after_sharpen(logger=print, *, reason: str = "manual") -> None:
    pencil_state_mod.reset_pencil_state_after_sharpen(_CLI_BACKEND, logger, reason=reason)


def pencil_remaining_to_sharpen_m(state: dict) -> Tuple[float, float, float]:
    return pencil_state_mod.pencil_remaining_to_sharpen_m(_CLI_BACKEND, state)


def calibrate_pencil_wear_from_last_test(
    *,
    last_good_stage: int,
    first_bad_stage: int = 0,
    safety_factor: float = 0.90,
    logger=print,
) -> Tuple[bool, str]:
    return pencil_state_mod.calibrate_pencil_wear_from_last_test(
        _CLI_BACKEND,
        last_good_stage=last_good_stage,
        first_bad_stage=first_bad_stage,
        safety_factor=safety_factor,
        logger=logger,
    )


def show_pencil_status(logger=print) -> None:
    pencil_state_mod.show_pencil_status(_CLI_BACKEND, logger)


def pencil_effective_z_down(base_z_down: float, state: dict) -> Tuple[float, float]:
    return pencil_state_mod.pencil_effective_z_down(_CLI_BACKEND, base_z_down, state)


def apply_pencil_wear_update(state: dict, draw_length_mm: float) -> dict:
    return pencil_state_mod.apply_pencil_wear_update(_CLI_BACKEND, state, draw_length_mm)


def pencil_remaining_draw_m(state: dict) -> float:
    return pencil_state_mod.pencil_remaining_draw_m(_CLI_BACKEND, state)


def find_inkscape() -> str:
    return discovery_mod.find_inkscape(
        INKSCAPE_CANDIDATES,
        which=shutil.which,
        dependency_error_cls=ToolDependencyError,
    )


def find_pdftocairo() -> str:
    return discovery_mod.find_pdftocairo(
        PDFTOCAIRO_CANDIDATES,
        which=shutil.which,
        dependency_error_cls=ToolDependencyError,
    )


def find_pdftotext() -> str:
    return discovery_mod.find_pdftotext(
        PDFTOTEXT_CANDIDATES,
        find_pdftocairo=find_pdftocairo,
        which=shutil.which,
        dependency_error_cls=ToolDependencyError,
    )


def pdf_text_questionmark_metrics(pdf_path: Path, logger=print) -> Optional[Tuple[float, int, int]]:
    return discovery_mod.pdf_text_questionmark_metrics(
        pdf_path,
        find_pdftotext=find_pdftotext,
        run_cmd=run_cmd,
        ensure_local_tmp_root=ensure_local_tmp_root,
        logger=logger,
    )


def detect_com_port(preferred: Optional[str] = None) -> str:
    return discovery_mod.detect_com_port(
        preferred,
        default_port=DEFAULT_COM_PORT,
    )


def get_inkscape_version(exe: str) -> Tuple[int, int, int]:
    return discovery_mod.get_inkscape_version(exe, run_cmd=run_cmd)

def mat_mul(m1: Tuple[float, float, float, float, float, float], m2: Tuple[float, float, float, float, float, float]):
    return geometry_transform_mod.mat_mul(m1, m2)


def mat_apply(m: Tuple[float, float, float, float, float, float], p: Tuple[float, float]) -> Tuple[float, float]:
    return geometry_transform_mod.mat_apply(m, p)


def parse_transform(value: str) -> Tuple[float, float, float, float, float, float]:
    return geometry_transform_mod.parse_transform(value)


def infer_scale(root: ET.Element) -> float:
    return svg_filter_utils_mod.infer_scale(
        root,
        viewbox_re=VIEWBOX_RE,
        parse_length=parse_length,
        unit_to_mm=unit_to_mm,
    )


def parse_path_tokens(path_d: str) -> Iterable[Tuple[str, List[float]]]:
    return geometry_svg_path_mod.parse_path_tokens(path_d, parse_floats_fn=parse_floats)


def cubic_approx(p0, p1, p2, p3, step=CURVE_SEGMENT_MM) -> List[Tuple[float, float]]:
    return geometry_svg_path_mod.cubic_approx(p0, p1, p2, p3, step=step)


def quadratic_approx(p0, p1, p2, step=CURVE_SEGMENT_MM) -> List[Tuple[float, float]]:
    return geometry_svg_path_mod.quadratic_approx(p0, p1, p2, step=step)


def arc_to_polyline(p0, rx, ry, angle_deg, large_arc, sweep, p1, step=0.35) -> List[Tuple[float, float]]:
    return geometry_svg_path_mod.arc_to_polyline(
        p0,
        rx,
        ry,
        angle_deg,
        large_arc,
        sweep,
        p1,
        step=step,
    )


def apply_style_filter(style: Optional[dict], tag: str, element: Optional[ET.Element] = None) -> bool:
    return svg_filter_utils_mod.apply_style_filter(
        style,
        tag,
        element,
        style_value=style_value,
        is_none_style=is_none_style,
    )


def read_style_dict(style: Optional[str]) -> dict:
    return svg_text_utils_mod.read_style_dict(style)


def get_href(element: ET.Element) -> Optional[str]:
    return svg_text_utils_mod.get_href(element)


def _length_to_user_units(raw: str, scale_to_mm: float) -> Optional[float]:
    return svg_filter_utils_mod.length_to_user_units(
        raw,
        scale_to_mm,
        parse_length=parse_length,
        unit_to_mm=unit_to_mm,
    )


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


def _embedded_image_to_gray_alpha(img: "np.ndarray") -> Tuple[Optional["np.ndarray"], Optional["np.ndarray"]]:
    if cv2 is None or np is None or img is None:
        return None, None
    try:
        if len(img.shape) == 2:
            return img, None
        if img.shape[2] == 4:
            alpha = img[:, :, 3]
            bgr = img[:, :, :3]
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            return gray, alpha
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return gray, None
    except Exception:
        return None, None


def _normalize_embedded_gray_polarity(gray: "np.ndarray", alpha: Optional["np.ndarray"]) -> "np.ndarray":
    if cv2 is None or np is None or gray is None:
        return gray
    try:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        active_area = mask.size
        if alpha is not None and int(np.max(alpha)) > 0:
            _, alpha_mask = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)
            mask = cv2.bitwise_and(mask, alpha_mask)
            active_area = max(1, int(np.count_nonzero(alpha_mask)))
        dark_ratio = float(np.count_nonzero(mask)) / float(max(1, int(active_area)))
        if dark_ratio > 0.55:
            return cv2.bitwise_not(gray)
    except Exception:
        return gray
    return gray


def _analyze_embedded_image_profile(img: "np.ndarray") -> Dict[str, object]:
    default = {
        "kind": "generic",
        "line_art": False,
        "formula_like": False,
        "small_line_art": False,
        "dark_ratio": 0.0,
        "ink_fill_ratio": 1.0,
        "aspect_ratio": 1.0,
        "width_px": 0,
        "height_px": 0,
    }
    gray, alpha = _embedded_image_to_gray_alpha(img)
    if gray is None or np is None or cv2 is None:
        return default

    try:
        gray = _normalize_embedded_gray_polarity(gray, alpha)
        h_px, w_px = gray.shape[:2]
        if h_px <= 0 or w_px <= 0:
            return default
        work = cv2.GaussianBlur(gray, (3, 3), 0)
        _, mask = cv2.threshold(work, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        if alpha is not None and int(np.max(alpha)) > 0:
            _, alpha_mask = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)
            mask = cv2.bitwise_and(mask, alpha_mask)
        dark = (mask > 0)
        total_px = max(1, int(dark.size))
        dark_px = int(np.count_nonzero(dark))
        dark_ratio = float(dark_px) / float(total_px)
        ys, xs = np.nonzero(dark)
        bbox_fill = 1.0
        if len(xs) > 0 and len(ys) > 0:
            bbox_w = int(xs.max() - xs.min() + 1)
            bbox_h = int(ys.max() - ys.min() + 1)
            bbox_area = max(1, bbox_w * bbox_h)
            bbox_fill = float(dark_px) / float(bbox_area)
        aspect = float(w_px) / float(max(1, h_px))
        line_art = (
            dark_ratio > 0.0
            and dark_ratio <= float(IMAGE_CONTOUR_LINEART_DARK_RATIO_MAX)
            and bbox_fill <= float(IMAGE_CONTOUR_LINEART_INK_FILL_MAX)
        )
        formula_like = bool(
            line_art
            and aspect >= float(IMAGE_CONTOUR_FORMULA_ASPECT_MIN)
            and h_px <= int(IMAGE_CONTOUR_FORMULA_MAX_HEIGHT_PX)
        )
        small_line_art = bool(
            line_art
            and w_px <= int(IMAGE_CONTOUR_SMALL_LINEART_MAX_WIDTH_PX)
            and h_px <= int(IMAGE_CONTOUR_SMALL_LINEART_MAX_HEIGHT_PX)
        )
        return {
            "kind": "formula" if formula_like else ("lineart" if line_art else "generic"),
            "line_art": bool(line_art),
            "formula_like": bool(formula_like),
            "small_line_art": bool(small_line_art),
            "dark_ratio": float(dark_ratio),
            "ink_fill_ratio": float(bbox_fill),
            "aspect_ratio": float(aspect),
            "width_px": int(w_px),
            "height_px": int(h_px),
        }
    except Exception:
        return default


def _extract_image_centerline_paths_px_autotrace(
    img: "np.ndarray",
    *,
    min_component_px: int,
    min_path_px: float,
    max_paths: int,
    curve_step_px: float,
    rdp_px: float,
    close_kernel: Tuple[int, int],
    threshold_floor: int = 0,
) -> List[List[Tuple[float, float]]]:
    if cv2 is None or np is None or img is None:
        return []
    autotrace_exe = _resolve_autotrace_executable()
    if autotrace_exe is None:
        return []

    gray, alpha = _embedded_image_to_gray_alpha(img)
    if gray is None:
        return []

    try:
        gray = _normalize_embedded_gray_polarity(gray, alpha)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        otsu_thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        thr = int(max(float(otsu_thr), float(threshold_floor)))
        _, mask = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY_INV)
        if alpha is not None and int(np.max(alpha)) > 0:
            _, alpha_mask = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)
            mask = cv2.bitwise_and(mask, alpha_mask)
        kx = max(1, int(close_kernel[0]))
        ky = max(1, int(close_kernel[1]))
        kernel = np.ones((ky, kx), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
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
        if int(np.count_nonzero(comp)) <= 0:
            return []
        binary = np.where(comp > 0, 0, 255).astype(np.uint8)
        raw = _run_autotrace_centerline_on_binary(
            binary,
            autotrace_exe=autotrace_exe,
            error_threshold=float(HANDWRITING_SINGLELINE_TTF_AUTOTRACE_ERROR_THRESHOLD),
            filter_iterations=int(HANDWRITING_SINGLELINE_TTF_AUTOTRACE_FILTER_ITERATIONS),
            curve_step_px=float(curve_step_px),
        )
    except Exception:
        return []

    if not raw:
        return []

    out: List[List[Tuple[float, float]]] = []
    cap = max(1, int(max_paths))
    min_len_px = max(0.0, float(min_path_px))
    simplify_eps_px = max(0.10, min(1.1, float(curve_step_px) * 0.28))
    rdp_eps_px = max(0.0, float(rdp_px))
    for poly in raw:
        if len(poly) < 2:
            continue
        clean = simplify_polyline(poly, eps=simplify_eps_px)
        if len(clean) >= 3 and rdp_eps_px > 0.0:
            clean = rdp_simplify_polyline(clean, eps=max(0.08, rdp_eps_px * 0.35))
        if len(clean) < 2:
            continue
        if polyline_length(clean) < min_len_px:
            continue
        out.append(clean)
        if len(out) >= cap:
            break
    return out


def _extract_image_centerline_paths_px(
    img: "np.ndarray",
    *,
    min_component_px: int,
    min_path_px: float,
    max_paths: int,
    rdp_px: float,
    threshold_floor: int = 0,
) -> List[List[Tuple[float, float]]]:
    if cv2 is None or np is None or img is None:
        return []
    gray, alpha = _embedded_image_to_gray_alpha(img)
    if gray is None:
        return []

    try:
        gray = _normalize_embedded_gray_polarity(gray, alpha)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        otsu_thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        thr = int(max(float(otsu_thr), float(threshold_floor)))
        _, mask = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY_INV)
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

    gray, alpha = _embedded_image_to_gray_alpha(img)
    if gray is None:
        return []

    gray = _normalize_embedded_gray_polarity(gray, alpha)
    if alpha is not None and int(np.max(alpha)) > 0:
        gray = cv2.bitwise_and(gray, gray, mask=alpha)
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


def _extract_image_hough_circles_px(img: "np.ndarray") -> List[List[Tuple[float, float]]]:
    if cv2 is None or np is None or img is None:
        return []

    gray, alpha = _embedded_image_to_gray_alpha(img)
    if gray is None:
        return []

    try:
        gray = _normalize_embedded_gray_polarity(gray, alpha)
        attempts = [
            (gray, float(IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2)),
            (cv2.GaussianBlur(gray, (3, 3), 0), max(12.0, float(IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2))),
        ]
        circles = None
        for attempt_gray, attempt_param2 in attempts:
            circles = cv2.HoughCircles(
                attempt_gray,
                cv2.HOUGH_GRADIENT,
                dp=float(IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_DP),
                minDist=float(IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_MIN_DIST_PX),
                param1=float(IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM1),
                param2=float(attempt_param2),
                minRadius=int(IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_MIN_RADIUS_PX),
                maxRadius=int(IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_MAX_RADIUS_PX),
            )
            if circles is not None and len(circles) > 0:
                break
    except Exception:
        return []

    if circles is None or len(circles) <= 0:
        return []

    out: List[List[Tuple[float, float]]] = []
    accepted: List[Tuple[float, float, float]] = []
    steps = max(10, int(IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_STEPS))
    for x, y, r in circles[0]:
        cx = float(x)
        cy = float(y)
        cr = float(r)
        if cr <= 0.0:
            continue
        duplicate = False
        for px, py, pr in accepted:
            if math.hypot(cx - px, cy - py) <= max(3.0, 0.35 * max(cr, pr)):
                duplicate = True
                break
        if duplicate:
            continue
        poly: List[Tuple[float, float]] = []
        for idx in range(steps + 1):
            ang = (2.0 * math.pi * float(idx)) / float(steps)
            poly.append((cx + (cr * math.cos(ang)), cy + (cr * math.sin(ang))))
        out.append(poly)
        accepted.append((cx, cy, cr))
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


def _resolve_formula_print_ttf_path() -> Optional[Path]:
    return (
        _resolve_handwriting_ttf_path("Times New Roman")
        or _resolve_handwriting_ttf_path("Cambria")
        or _resolve_handwriting_ttf_path("Arial")
    )


def _measure_ttf_text_bbox_units(
    text: str,
    *,
    ttf_path: Path,
    font_size: float,
) -> Optional[Tuple[float, float, float, float]]:
    if Image is None or ImageDraw is None or ImageFont is None:
        return None
    render_scale = max(2.0, float(HANDWRITING_SINGLELINE_TTF_RENDER_SCALE))
    font_px = max(24, int(round(max(1.0, float(font_size)) * render_scale)))
    font = _get_cached_handwriting_pil_font(ttf_path, font_px)
    if font is None:
        return None
    probe = Image.new("L", (10, 10), 255)
    draw_probe = ImageDraw.Draw(probe)
    try:
        left, top, right, bottom = draw_probe.textbbox((0, 0), text, font=font, anchor="ls")
    except Exception:
        return None
    inv_scale = 1.0 / max(1e-9, float(render_scale))
    return (
        float(left) * inv_scale,
        float(top) * inv_scale,
        float(right) * inv_scale,
        float(bottom) * inv_scale,
    )


def _fit_formula_ocr_font_size_units(
    text: str,
    *,
    ttf_path: Path,
    target_w_u: float,
    target_h_u: float,
) -> Optional[Tuple[float, Tuple[float, float, float, float]]]:
    target_w = max(0.4, float(target_w_u))
    target_h = max(0.4, float(target_h_u))
    font_size = max(4.0, target_h * 0.96)
    best: Optional[Tuple[float, Tuple[float, float, float, float]]] = None
    for _ in range(6):
        bbox = _measure_ttf_text_bbox_units(text, ttf_path=ttf_path, font_size=font_size)
        if bbox is None:
            return None
        left, top, right, bottom = bbox
        width = max(1e-6, float(right - left))
        height = max(1e-6, float(bottom - top))
        best = (font_size, bbox)
        scale_fit = min((target_w * 0.985) / width, (target_h * 0.92) / height)
        if 0.96 <= scale_fit <= 1.04:
            return best
        next_size = max(3.2, font_size * max(0.55, min(1.45, scale_fit)))
        if abs(next_size - font_size) < 0.08:
            return best
        font_size = next_size
    return best


def _map_formula_ocr_bbox_to_user_units(
    *,
    bbox_px: Tuple[float, float, float, float],
    image_x_u: float,
    image_y_u: float,
    image_w_u: float,
    image_h_u: float,
    image_w_px: int,
    image_h_px: int,
) -> Tuple[float, float, float, float]:
    x0_px, y0_px, x1_px, y1_px = bbox_px
    denom_x = max(1.0, float(image_w_px))
    denom_y = max(1.0, float(image_h_px))
    x0_u = image_x_u + (max(0.0, x0_px) / denom_x) * image_w_u
    x1_u = image_x_u + (max(0.0, x1_px) / denom_x) * image_w_u
    y0_u = image_y_u + (max(0.0, y0_px) / denom_y) * image_h_u
    y1_u = image_y_u + (max(0.0, y1_px) / denom_y) * image_h_u
    return (x0_u, y0_u, x1_u, y1_u)


def _extract_formula_ocr_polylines_mm(
    img: "np.ndarray",
    *,
    x_u: float,
    y_u: float,
    w_u: float,
    h_u: float,
    matrix: Tuple[float, float, float, float, float, float],
    scale: float,
    logger,
) -> List[List[Tuple[float, float]]]:
    if not IMAGE_CONTOUR_FORMULA_OCR_ENABLED:
        return []
    if formula_image_ocr_mod is None or not formula_image_ocr_mod.rapidocr_available():
        return []
    result = formula_image_ocr_mod.ocr_formula_image(img)
    if result is None or result.confidence < float(IMAGE_CONTOUR_FORMULA_OCR_MIN_CONFIDENCE):
        return []
    ttf_path = _resolve_formula_print_ttf_path()
    if ttf_path is None:
        return []

    img_h_px, img_w_px = img.shape[:2]
    out: List[List[Tuple[float, float]]] = []
    for line in result.lines:
        if float(line.confidence) < float(IMAGE_CONTOUR_FORMULA_OCR_MIN_CONFIDENCE):
            continue
        text = str(line.text or "").strip()
        if len(text) < 4:
            continue
        box_x0_u, box_y0_u, box_x1_u, box_y1_u = _map_formula_ocr_bbox_to_user_units(
            bbox_px=line.bbox_px,
            image_x_u=x_u,
            image_y_u=y_u,
            image_w_u=w_u,
            image_h_u=h_u,
            image_w_px=img_w_px,
            image_h_px=img_h_px,
        )
        target_w_u = max(0.6, box_x1_u - box_x0_u)
        target_h_u = max(0.6, box_y1_u - box_y0_u)
        fit = _fit_formula_ocr_font_size_units(
            text,
            ttf_path=ttf_path,
            target_w_u=target_w_u,
            target_h_u=target_h_u,
        )
        if fit is None:
            continue
        font_size_u, bbox_u = fit
        left_u, top_u, right_u, bottom_u = bbox_u
        text_w_u = max(1e-6, right_u - left_u)
        text_h_u = max(1e-6, bottom_u - top_u)
        pad_x_u = max(0.0, (target_w_u - text_w_u) * 0.04)
        pad_y_u = max(0.0, (target_h_u - text_h_u) * 0.08)
        baseline_x_u = box_x0_u - left_u + pad_x_u
        baseline_y_u = box_y0_u - top_u + pad_y_u
        polylines_u = _render_singleline_text_polylines_ttf(
            text,
            ttf_path=ttf_path,
            font_size=font_size_u,
            baseline_x=baseline_x_u,
            baseline_y=baseline_y_u,
            force_cyrillic_mode=False,
            logger=logger,
        )
        for poly_u in polylines_u:
            if len(poly_u) < 2:
                continue
            mm_poly: List[Tuple[float, float]] = []
            for ux, uy in poly_u:
                tx, ty = mat_apply(matrix, (ux, uy))
                mm_poly.append((tx * scale, ty * scale))
            if len(mm_poly) >= 2 and polyline_length(mm_poly) >= 0.18:
                out.append(mm_poly)

    if out and logger:
        logger(
            f"Formula OCR image route: {len(result.lines)} line(s), "
            f"conf={result.confidence:.3f}, variant={result.variant}, polylines={len(out)}"
        )
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
                    trace_img = img
                    trace_h_px, trace_w_px = h_px, w_px
                    circle_img = img
                    circle_h_px, circle_w_px = h_px, w_px
                    w_mm = max(1e-9, float(w_u) * float(scale))
                    h_mm = max(1e-9, float(h_u) * float(scale))
                    mm_per_px_x = w_mm / max(1.0, float(w_px - 1))
                    mm_per_px_y = h_mm / max(1.0, float(h_px - 1))
                    mm_per_px = max(mm_per_px_x, mm_per_px_y)
                    profile = _analyze_embedded_image_profile(img)
                    profile_kind = str(profile.get("kind", "generic"))
                    min_path_mm = max(
                        float(IMAGE_CONTOUR_MIN_PATH_MM),
                        float(IMAGE_CONTOUR_HANDWRITING_MIN_PATH_MM) if HANDWRITING_TEXT_ENABLED else 0.0,
                    )
                    simplify_eps_mm = max(float(IMAGE_CONTOUR_MM_SIMPLIFY_EPS), mm_per_px * 0.95)
                    tiny_bbox_mm = 1.10 if HANDWRITING_TEXT_ENABLED else 0.65
                    center_min_component_px = int(IMAGE_CONTOUR_CENTERLINE_MIN_COMPONENT_PX)
                    center_rdp_px = float(IMAGE_CONTOUR_CENTERLINE_RDP_PX)
                    center_curve_step_px = float(HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CURVE_STEP_PX)
                    post_rdp_eps_mm = 0.16
                    prefer_autotrace = False
                    center_threshold_floor = 0

                    if HANDWRITING_TEXT_ENABLED and bool(profile.get("line_art", False)):
                        prefer_autotrace = bool(IMAGE_CONTOUR_LINEART_AUTOTRACE)
                        dark_ratio = float(profile.get("dark_ratio", 1.0) or 1.0)
                        if dark_ratio <= float(IMAGE_CONTOUR_LIGHT_LINEART_DARK_RATIO_MAX):
                            center_threshold_floor = int(IMAGE_CONTOUR_LINEART_THRESHOLD_MIN)
                        if profile_kind == "formula":
                            min_path_mm = min(min_path_mm, float(IMAGE_CONTOUR_FORMULA_MIN_PATH_MM))
                            simplify_eps_mm = min(simplify_eps_mm, float(IMAGE_CONTOUR_FORMULA_SIMPLIFY_MM))
                            tiny_bbox_mm = min(tiny_bbox_mm, float(IMAGE_CONTOUR_FORMULA_TINY_BBOX_MM))
                            center_min_component_px = min(center_min_component_px, int(IMAGE_CONTOUR_FORMULA_MIN_COMPONENT_PX))
                            center_rdp_px = min(center_rdp_px, float(IMAGE_CONTOUR_FORMULA_RDP_PX))
                            center_curve_step_px = min(center_curve_step_px, 0.50)
                            post_rdp_eps_mm = 0.06
                        else:
                            min_path_mm = min(min_path_mm, float(IMAGE_CONTOUR_LINEART_MIN_PATH_MM))
                            simplify_eps_mm = min(simplify_eps_mm, float(IMAGE_CONTOUR_LINEART_SIMPLIFY_MM))
                            tiny_bbox_mm = min(tiny_bbox_mm, float(IMAGE_CONTOUR_LINEART_TINY_BBOX_MM))
                            center_min_component_px = min(center_min_component_px, int(IMAGE_CONTOUR_LINEART_MIN_COMPONENT_PX))
                            center_rdp_px = min(center_rdp_px, float(IMAGE_CONTOUR_LINEART_RDP_PX))
                            center_curve_step_px = min(center_curve_step_px, 0.60)
                            post_rdp_eps_mm = 0.10
                            if bool(profile.get("small_line_art", False)):
                                min_path_mm = min(min_path_mm, float(IMAGE_CONTOUR_SMALL_LINEART_MIN_PATH_MM))
                                simplify_eps_mm = min(simplify_eps_mm, float(IMAGE_CONTOUR_SMALL_LINEART_SIMPLIFY_MM))
                                tiny_bbox_mm = min(tiny_bbox_mm, float(IMAGE_CONTOUR_SMALL_LINEART_TINY_BBOX_MM))
                                center_min_component_px = min(
                                    center_min_component_px,
                                    int(IMAGE_CONTOUR_SMALL_LINEART_MIN_COMPONENT_PX),
                                )
                                center_rdp_px = min(center_rdp_px, float(IMAGE_CONTOUR_SMALL_LINEART_RDP_PX))
                                center_curve_step_px = min(center_curve_step_px, 0.40)
                                post_rdp_eps_mm = 0.04
                                trace_scale = max(1.0, float(IMAGE_CONTOUR_SMALL_LINEART_TRACE_SCALE))
                                if trace_scale > 1.01:
                                    try:
                                        trace_img = cv2.resize(
                                            img,
                                            dsize=None,
                                            fx=trace_scale,
                                            fy=trace_scale,
                                            interpolation=cv2.INTER_CUBIC,
                                        )
                                        trace_h_px, trace_w_px = trace_img.shape[:2]
                                    except Exception:
                                        trace_img = img
                                        trace_h_px, trace_w_px = h_px, w_px
                    min_path_px = max(0.25, min_path_mm / max(1e-9, mm_per_px))

                    mode = (IMAGE_CONTOUR_VECTORIZE_MODE or "centerline").strip().lower()
                    if mode not in {"edge", "centerline", "auto"}:
                        mode = "centerline"
                    if HANDWRITING_TEXT_ENABLED and profile_kind == "formula":
                        formula_mode = str(IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE or "centerline").strip().lower()
                        if formula_mode in {"edge", "centerline", "auto"}:
                            mode = formula_mode

                    ocr_formula_polys_mm: List[List[Tuple[float, float]]] = []
                    if HANDWRITING_TEXT_ENABLED and profile_kind == "formula":
                        ocr_formula_polys_mm = _extract_formula_ocr_polylines_mm(
                            img,
                            x_u=x_u,
                            y_u=y_u,
                            w_u=w_u,
                            h_u=h_u,
                            matrix=cur_matrix,
                            scale=scale,
                            logger=logger,
                        )
                    if ocr_formula_polys_mm:
                        added = 0
                        for mm_poly in ocr_formula_polys_mm:
                            out.append(
                                PathItem(
                                    points=mm_poly,
                                    closed=False,
                                    is_fill=False,
                                    is_stroke=True,
                                    source_id=source_id_seq,
                                )
                            )
                            source_id_seq += 1
                            added += 1
                        if added > 0 and logger:
                            logger(f"Image contour tracing: formula OCR +{added} path(s).")
                        for child in list(node):
                            walk(child, cur_matrix)
                        return

                    px_centerlines: List[List[Tuple[float, float]]] = []
                    if mode in {"centerline", "auto"}:
                        center_cap = int(IMAGE_CONTOUR_CENTERLINE_MAX_PATHS_PER_IMAGE)
                        if HANDWRITING_TEXT_ENABLED:
                            center_cap = min(center_cap, 1100)
                        if HANDWRITING_TEXT_ENABLED and prefer_autotrace:
                            close_kernel = (3, 1) if profile_kind == "formula" else (2, 2)
                            px_centerlines = _extract_image_centerline_paths_px_autotrace(
                                trace_img,
                                min_component_px=center_min_component_px,
                                min_path_px=min_path_px,
                                max_paths=center_cap,
                                curve_step_px=center_curve_step_px,
                                rdp_px=center_rdp_px,
                                close_kernel=close_kernel,
                                threshold_floor=center_threshold_floor,
                            )
                        if not px_centerlines:
                            px_centerlines = _extract_image_centerline_paths_px(
                                trace_img,
                                min_component_px=center_min_component_px,
                                min_path_px=min_path_px,
                                max_paths=center_cap,
                                rdp_px=center_rdp_px,
                                threshold_floor=center_threshold_floor,
                            )

                    px_edge_polys: List[List[Tuple[float, float]]] = []
                    if mode == "edge" or (mode == "auto" and not px_centerlines):
                        px_edge_polys = _extract_image_edge_contours_px(trace_img)
                    px_circle_polys: List[List[Tuple[float, float]]] = []
                    if HANDWRITING_TEXT_ENABLED and bool(profile.get("small_line_art", False)):
                        px_circle_polys = _extract_image_hough_circles_px(circle_img)

                    added = 0
                    added_centerline = 0
                    added_edge = 0
                    added_circles = 0
                    added_hatch = 0
                    for px_poly in px_centerlines:
                        mm_poly: List[Tuple[float, float]] = []
                        for px, py in px_poly:
                            # Map pixel contour to image placement box in SVG user units.
                            ux = x_u + (px / max(1.0, float(trace_w_px - 1))) * w_u
                            uy = y_u + (py / max(1.0, float(trace_h_px - 1))) * h_u
                            tx, ty = mat_apply(cur_matrix, (ux, uy))
                            mm_poly.append((tx * scale, ty * scale))
                        mm_poly = simplify_polyline(mm_poly, eps=simplify_eps_mm)
                        if len(mm_poly) >= 3:
                            mm_poly = rdp_simplify_polyline(mm_poly, eps=max(post_rdp_eps_mm, simplify_eps_mm * 1.15))
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
                            ux = x_u + (px / max(1.0, float(trace_w_px - 1))) * w_u
                            uy = y_u + (py / max(1.0, float(trace_h_px - 1))) * h_u
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

                    for px_poly in px_circle_polys:
                        mm_poly = []
                        for px, py in px_poly:
                            ux = x_u + (px / max(1.0, float(circle_w_px - 1))) * w_u
                            uy = y_u + (py / max(1.0, float(circle_h_px - 1))) * h_u
                            tx, ty = mat_apply(cur_matrix, (ux, uy))
                            mm_poly.append((tx * scale, ty * scale))
                        if len(mm_poly) < 10:
                            continue
                        if points_distance(mm_poly[0], mm_poly[-1]) > 1e-6:
                            mm_poly.append(mm_poly[0])
                        xs = [p[0] for p in mm_poly]
                        ys = [p[1] for p in mm_poly]
                        if (max(xs) - min(xs)) < max(0.45, tiny_bbox_mm * 0.35) and (max(ys) - min(ys)) < max(0.45, tiny_bbox_mm * 0.35):
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
                        added_circles += 1

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
                                ux = x_u + (px / max(1.0, float(trace_w_px - 1))) * w_u
                                uy = y_u + (py / max(1.0, float(trace_h_px - 1))) * h_u
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
                        if added_circles > 0:
                            logger(
                                "Image node circle recovery: "
                                f"+{added_circles} closed path(s)."
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
    return svg_text_utils_mod.parse_color_to_rgb_like(value)


def svg_has_text_nodes(svg_path: Path) -> bool:
    return svg_text_utils_mod.svg_has_text_nodes(svg_path, tag_name=tag_name)


def svg_text_node_count(svg_path: Path) -> int:
    return svg_text_utils_mod.svg_text_node_count(svg_path, tag_name=tag_name)


def _read_style_dict_preserve(style: Optional[str]) -> dict:
    return svg_text_utils_mod.read_style_dict_preserve(style)


def _style_dict_to_string(style: dict) -> str:
    return svg_text_utils_mod.style_dict_to_string(style)


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
        "times new roman": ["times.ttf", "timesbd.ttf", "timesi.ttf"],
        "cambria": ["cambria.ttc", "cambria.ttf"],
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
    dirs.append(LOCAL_TMP_ROOT / "inkscapestrokefont" / "strokefontdata")
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
        logger(_format_internal_exception(f"SVG stroke font load failed ({font_name})", exc))
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
    return handwriting_text_utils_mod.split_text_tokens_keep_spaces(text)


def _normalize_handwriting_text_token(text: str) -> str:
    return handwriting_text_utils_mod.normalize_handwriting_text_token(
        text,
        strip_unpaired_surrogates=_strip_unpaired_surrogates,
    )


def _normalize_handwriting_text_string(text: str) -> str:
    return handwriting_text_utils_mod.normalize_handwriting_text_string(
        text,
        strip_unpaired_surrogates=_strip_unpaired_surrogates,
        text_contains_formula_script_fn=handwriting_text_utils_mod.text_contains_formula_script,
    )


def _style_prefers_native_vector(style: Optional[dict]) -> bool:
    return handwriting_text_utils_mod.style_prefers_native_vector(style)


def _text_contains_formula_script(text: str) -> bool:
    return handwriting_text_utils_mod.text_contains_formula_script(text)


def _text_prefers_native_vector(text: str) -> bool:
    return handwriting_text_utils_mod.text_prefers_native_vector(
        text,
        strip_unpaired_surrogates=_strip_unpaired_surrogates,
    )


def _text_prefers_print_font(
    text: str,
    *,
    font_size: Optional[float] = None,
    font_names: Optional[List[str]] = None,
) -> bool:
    return handwriting_text_utils_mod.text_prefers_print_font(
        text,
        font_size=font_size,
        font_names=font_names,
        text_contains_formula_script_fn=handwriting_text_utils_mod.text_contains_formula_script,
    )


def _handwriting_min_line_step_mm(font_size: float, text: str = "") -> float:
    return handwriting_text_utils_mod.handwriting_min_line_step_mm(
        font_size,
        text,
        text_contains_cyrillic=_text_contains_cyrillic,
        line_step_factor=HANDWRITING_LINE_STEP_FACTOR,
        line_step_factor_cyr=HANDWRITING_LINE_STEP_FACTOR_CYR,
        line_step_extra_mm=HANDWRITING_LINE_STEP_EXTRA_MM,
    )


def _adjust_handwriting_tspan_dy(
    dy: float,
    *,
    font_size: float,
    text: str,
    is_first_visible_line: bool,
) -> float:
    return handwriting_text_utils_mod.adjust_handwriting_tspan_dy(
        dy,
        font_size=font_size,
        text=text,
        is_first_visible_line=is_first_visible_line,
        auto_line_spacing_enabled=HANDWRITING_AUTO_LINE_SPACING_ENABLED,
        handwriting_min_line_step_fn=_handwriting_min_line_step_mm,
    )


def _merge_svg_text_style(parent_style: dict, node: ET.Element) -> dict:
    return handwriting_text_utils_mod.merge_svg_text_style(
        parent_style,
        node,
        read_style_dict_preserve=_read_style_dict_preserve,
    )


def _sanitize_svg_text_node_for_vector(node: ET.Element) -> bool:
    return handwriting_text_utils_mod.sanitize_svg_text_node_for_vector(
        node,
        normalize_handwriting_text_token_fn=_normalize_handwriting_text_string,
    )


def _svg_text_node_is_visible(style: Optional[dict], node: Optional[ET.Element] = None) -> bool:
    return handwriting_text_utils_mod.svg_text_node_is_visible(
        style,
        node,
        parse_svg_number=_parse_svg_number,
    )


def _pick_svg_text_stroke_color(style: Optional[dict]) -> Optional[str]:
    return handwriting_text_utils_mod.pick_svg_text_stroke_color(style)


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
        txt = _normalize_handwriting_text_string(src or "")
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
            smooth_prev_cmd = prev_cmd
            for i in range(0, len(params), 4):
                if i + 3 >= len(params):
                    break
                c2 = (float(params[i]), float(params[i + 1]))
                p = (float(params[i + 2]), float(params[i + 3]))
                if smooth_prev_cmd in "CcSs" and last_cubic is not None:
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
                smooth_prev_cmd = cmd
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
            smooth_prev_cmd = prev_cmd
            for i in range(0, len(params), 2):
                if i + 1 >= len(params):
                    break
                p = (float(params[i]), float(params[i + 1]))
                if smooth_prev_cmd in "QqTt" and last_quadratic is not None:
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
                smooth_prev_cmd = cmd
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
    if np is None:
        return []
    if binary_black_on_white is None or binary_black_on_white.size <= 0:
        return []
    pbm_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(prefix="ctrace_", suffix=".pbm", delete=False) as fp:
            pbm_path = Path(fp.name)
        arr = binary_black_on_white.astype(np.uint8, copy=False)
        if Image is not None:
            img = Image.fromarray(arr, mode="L").convert("1")
            img.save(str(pbm_path))
        else:
            # Pillow is optional in this project. Write PBM directly so
            # Method3 centerline tracing keeps working in headless environments.
            h, w = int(arr.shape[0]), int(arr.shape[1])
            black_bits = (arr == 0).astype(np.uint8)
            pad = (8 - (w % 8)) % 8
            if pad:
                black_bits = np.pad(black_bits, ((0, 0), (0, pad)), mode="constant", constant_values=0)
            packed = np.packbits(black_bits, axis=1, bitorder="big")
            header = f"P4\n{w} {h}\n".encode("ascii")
            with pbm_path.open("wb") as fh:
                fh.write(header)
                fh.write(packed.tobytes())
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
            left, _, right, _ = draw.textbbox((0, 0), text, font=font, anchor="ls")
            adv_px = float(right - left)
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
    text_norm = _normalize_handwriting_text_string(text)
    line_has_cyrillic = _text_contains_cyrillic(text_norm)
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
    tokens = _split_text_tokens_keep_spaces(text_norm)
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
        logger(_format_internal_exception("TTF centerline replace failed", exc))
        return 0

    changed = 0
    total_paths = 0
    native_row_ids = _collect_native_row_text_node_ids(root)
    print_ttf_path = (
        _resolve_handwriting_ttf_path("Times New Roman")
        or _resolve_handwriting_ttf_path("Cambria")
        or _resolve_handwriting_ttf_path("Arial")
    )

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
            lead = str((node.text or "").strip())
            if lead:
                runs.append((lead, base_x, base_y, dict(style_base), node_transform))
            cursor_x = float(base_x)
            cursor_y = float(base_y)
            has_lead = bool(lead)
            for ts_idx, ts in enumerate(tspans):
                text = str(_extract_svg_text_plain(ts))
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
            text = str(_extract_svg_text_plain(node))
            if text:
                runs.append((text, base_x, base_y, dict(style_base), node_transform))

        if not runs:
            return None
        combined_text = " ".join(str(run[0]).strip() for run in runs if str(run[0]).strip())
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

        for raw_text, x0, y0, style, run_transform in runs:
            if _style_prefers_native_vector(style):
                # Preserve complex math/symbol runs in native vector form.
                continue
            if not _svg_text_node_is_visible(style):
                continue
            font_size = _parse_svg_number(style.get("font-size"), default=12.0)
            if font_size <= 0.0:
                font_size = 12.0
            use_print_font = bool(
                print_ttf_path is not None
                and _text_prefers_print_font(
                    raw_text,
                    font_size=font_size,
                    font_names=[
                        str(style.get("font-family", "")).strip(),
                        str(style.get("-inkscape-font-specification", "")).strip(),
                        str(style.get("font", "")).strip(),
                    ],
                )
            )
            render_text = str(raw_text or "")
            if not use_print_font:
                render_text = _normalize_handwriting_text_string(render_text)
            stroke_color = _pick_svg_text_stroke_color(style)
            if not stroke_color:
                continue
            stroke_width = max(
                float(HANDWRITING_SINGLELINE_TTF_PREVIEW_STROKE_MIN_MM),
                font_size * float(HANDWRITING_SINGLELINE_TTF_PREVIEW_STROKE_SCALE),
            )

            lines = [ln for ln in render_text.split("\n") if ln != ""]
            if not lines:
                continue
            line_step = max(font_size * 1.34, font_size + 1.0)
            d_parts: List[str] = []
            for li, line_text in enumerate(lines):
                baseline_y = y0 + (li * line_step)
                polylines = _render_singleline_text_line_ttf(
                    line_text,
                    ttf_path=(print_ttf_path if use_print_font and print_ttf_path is not None else ttf_path),
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
        logger(_format_internal_exception("TTF centerline save failed", exc))
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
        logger(_format_internal_exception("Handwriting font apply failed", exc))
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
                _sanitize_svg_text_node_for_vector(node)
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
        logger(_format_internal_exception("Handwriting font save failed", exc))
        return 0

    logger(f"Handwriting mode: applied font '{target_font}' to {changed} text node(s).")
    return changed


def _parse_svg_number(value: Optional[str], default: float = 0.0) -> float:
    return svg_text_utils_mod.parse_svg_number(value, default=default)


def _parse_svg_number_list(value: Optional[str]) -> List[float]:
    return svg_text_utils_mod.parse_svg_number_list(value)


def _extract_svg_text_plain(node: ET.Element) -> str:
    return svg_text_utils_mod.extract_svg_text_plain(node, strip_unpaired_surrogates=_strip_unpaired_surrogates)


def _text_contains_cyrillic(text: str) -> bool:
    return svg_text_utils_mod.text_contains_cyrillic(text)


def svg_has_cyrillic_text_nodes(svg_path: Path) -> bool:
    return svg_text_utils_mod.svg_has_cyrillic_text_nodes(svg_path, tag_name=tag_name)


def _analyze_svg_text_profile(svg_path: Path) -> Dict[str, object]:
    return handwriting_text_utils_mod.analyze_svg_text_profile(
        svg_path,
        tag_name=tag_name,
        text_node_tags=TEXT_NODE_TAGS,
        extract_svg_text_plain=_extract_svg_text_plain,
    )


def _pick_hershey_font_name(font_name: str) -> str:
    return handwriting_text_utils_mod.pick_hershey_font_name(
        font_name,
        handwriting_stroke_font_name=HANDWRITING_STROKE_FONT_NAME,
    )


def _pick_hershey_font_name_for_text(font_name: str, text: str) -> str:
    return handwriting_text_utils_mod.pick_hershey_font_name_for_text(
        font_name,
        text,
        text_contains_cyrillic=_text_contains_cyrillic,
        pick_hershey_font_name_fn=_pick_hershey_font_name,
        handwriting_stroke_cyr_font_name=HANDWRITING_STROKE_CYR_FONT_NAME,
    )


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
        logger(_format_internal_exception("SVG stroke text replace failed", exc))
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
            lead = _normalize_handwriting_text_string((node.text or "").strip())
            if lead:
                runs.append((lead, base_x, base_y, dict(style_base), node_transform))
            cursor_x = float(base_x)
            cursor_y = float(base_y)
            has_lead = bool(lead)
            for ts_idx, ts in enumerate(tspans):
                text = _normalize_handwriting_text_string(_extract_svg_text_plain(ts))
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
            text = _normalize_handwriting_text_string(_extract_svg_text_plain(node))
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
        logger(_format_internal_exception("SVG stroke text save failed", exc))
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
        logger(_format_internal_exception("Hershey text replace failed", exc))
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
            lead = _normalize_handwriting_text_string((node.text or "").strip())
            if lead:
                runs.append((lead, base_x, base_y, dict(style_base), node_transform, list(node_x_list)))
            cursor_x = float(base_x)
            cursor_y = float(base_y)
            has_lead = bool(lead)
            for ts_idx, ts in enumerate(tspans):
                text = _normalize_handwriting_text_string(_extract_svg_text_plain(ts))
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
            text = _normalize_handwriting_text_string(_extract_svg_text_plain(node))
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
        logger(_format_internal_exception("Hershey text replace save failed", exc))
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
    return svg_text_utils_mod.style_value(style, element, key)


def is_none_style(value: Optional[str]) -> bool:
    return svg_text_utils_mod.is_none_style(value)


def parse_style_flags(style: dict, element: ET.Element, tag: str) -> Tuple[bool, bool]:
    return svg_text_utils_mod.parse_style_flags(
        style,
        element,
        tag,
        is_pure_white_shape=is_pure_white_shape,
    )


def is_nearly_white_fill(elem: ET.Element) -> bool:
    return svg_filter_utils_mod.is_nearly_white_fill(
        elem,
        read_style_dict=read_style_dict,
        parse_color_to_rgb_like=parse_color_to_rgb_like,
        background_fill_min_channel=BACKGROUND_FILL_MIN_CHANNEL,
        background_fill_min_opacity=BACKGROUND_FILL_MIN_OPACITY,
    )


def is_pure_white_shape(style: dict, element: ET.Element) -> bool:
    return svg_filter_utils_mod.is_pure_white_shape(
        style,
        element,
        is_none_style=is_none_style,
        parse_color_to_rgb_like=parse_color_to_rgb_like,
    )


def is_axis_aligned_rectangle(poly: List[Tuple[float, float]]) -> bool:
    return svg_filter_utils_mod.is_axis_aligned_rectangle(poly)


def root_page_size_mm(root: ET.Element) -> Tuple[float, float]:
    return svg_filter_utils_mod.root_page_size_mm(
        root,
        parse_length=parse_length,
        unit_to_mm=unit_to_mm,
        viewbox_re=VIEWBOX_RE,
    )


def is_full_page_white_fill_rect(poly: List[Tuple[float, float]], elem: ET.Element, page_w: float, page_h: float) -> bool:
    return svg_filter_utils_mod.is_full_page_white_fill_rect(
        poly,
        elem,
        page_w,
        page_h,
        is_axis_aligned_rectangle=is_axis_aligned_rectangle,
        tag_name=tag_name,
        is_nearly_white_fill=is_nearly_white_fill,
        read_style_dict=read_style_dict,
    )


def point_line_distance(point: Tuple[float, float], line_a: Tuple[float, float], line_b: Tuple[float, float]) -> float:
    return geometry_simplify_mod.point_line_distance(point, line_a, line_b)


def solve_3x3(mat: List[List[float]], vec: List[float]) -> Optional[Tuple[float, float, float]]:
    return geometry_arc_fit_mod.solve_3x3(mat, vec)


def fit_circle_kasa(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float, float]]:
    return geometry_arc_fit_mod.fit_circle_kasa(points)


def unwrap_angles(angles: List[float]) -> List[float]:
    return geometry_arc_fit_mod.unwrap_angles(angles)


def arc_extents_xy(
    start: Tuple[float, float],
    end: Tuple[float, float],
    center: Tuple[float, float],
    cw: bool,
) -> Tuple[float, float, float, float]:
    return geometry_arc_fit_mod.arc_extents_xy(start, end, center, cw)


def polyline_is_near_line(poly: List[Tuple[float, float]], tol_mm: float) -> bool:
    return geometry_arc_fit_mod.polyline_is_near_line(poly, tol_mm)


def polyline_fit_arc(poly: List[Tuple[float, float]], tol_mm: float) -> Optional[Tuple[bool, Tuple[float, float], float, float]]:
    return geometry_arc_fit_mod.polyline_fit_arc(
        poly,
        tol_mm,
        arc_min_radius_mm=float(ARC_MIN_RADIUS_MM),
        arc_min_sweep_deg=float(ARC_MIN_SWEEP_DEG),
    )


def path_is_closed(poly: List[Tuple[float, float]], eps: float = 1e-6) -> bool:
    return geometry_simplify_mod.path_is_closed(poly, eps=eps)


def _rdp_simplify_open(poly: List[Tuple[float, float]], eps: float) -> List[Tuple[float, float]]:
    return geometry_simplify_mod.rdp_simplify_open(poly, eps)


def rdp_simplify_polyline(poly: List[Tuple[float, float]], eps: float) -> List[Tuple[float, float]]:
    return geometry_simplify_mod.rdp_simplify_polyline(poly, eps)


def polygon_area(poly: List[Tuple[float, float]]) -> float:
    return geometry_hatching_mod.polygon_area(poly)


def polygon_bbox(poly: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    return geometry_hatching_mod.polygon_bbox(poly)


def rotate_point(point: Tuple[float, float], angle_rad: float) -> Tuple[float, float]:
    return geometry_hatching_mod.rotate_point(point, angle_rad)


def rotate_polyline(poly: List[Tuple[float, float]], angle_rad: float) -> List[Tuple[float, float]]:
    return geometry_hatching_mod.rotate_polyline(poly, angle_rad)


def intersects_for_scanline(edges: List[Tuple[Tuple[float, float], Tuple[float, float]]], y: float) -> List[float]:
    return geometry_hatching_mod.intersects_for_scanline(edges, y)


def should_hatch_polygon(poly: List[Tuple[float, float]], closed: bool) -> bool:
    return geometry_hatching_mod.should_hatch_polygon(
        poly,
        closed,
        fill_hatch_enabled=bool(FILL_HATCH_ENABLED),
        fill_hatch_min_area_mm2=float(FILL_HATCH_MIN_AREA_MM2),
        fill_hatch_min_side_mm=float(FILL_HATCH_MIN_SIDE_MM),
        path_is_closed_fn=path_is_closed,
    )


def hatch_polygon(
    contours: List[List[Tuple[float, float]]],
    spacing: float = FILL_HATCH_SPACING_MM,
    angle_deg: float = FILL_HATCH_ANGLE_DEG,
    min_segment: float = FILL_HATCH_MIN_SEGMENT_MM,
) -> List[List[Tuple[float, float]]]:
    return geometry_hatching_mod.hatch_polygon(
        contours,
        spacing=spacing,
        angle_deg=angle_deg,
        min_segment=min_segment,
        path_is_closed_fn=path_is_closed,
    )


def polyline_length(poly: List[Tuple[float, float]]) -> float:
    return geometry_polyline_mod.polyline_length(poly)


def total_draw_length_mm(polylines: List[List[Tuple[float, float]]]) -> float:
    return geometry_polyline_mod.total_draw_length_mm(polylines)


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


def centerline_is_usable_relaxed_small_cluster(
    group: List["PathItem"],
    centerlines: List[List[Tuple[float, float]]],
) -> bool:
    # Tolerant centerline gate for tiny fill clusters (mostly glyph fragments).
    if not group or not centerlines:
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

    # Keep strictly scoped to small clusters to avoid affecting real geometry.
    if w > 14.0 or h > 14.0 or (w * h) > 160.0:
        return False
    if len(centerlines) > 20:
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
    return 0.10 <= ratio <= 1.35


def refine_centerline_paths(
    centerlines: List[List[Tuple[float, float]]],
    *,
    handwriting: bool = False,
    technical: bool = False,
) -> List[List[Tuple[float, float]]]:
    if not centerlines:
        return []

    if handwriting:
        eps = float(FILL_CENTERLINE_HANDWRITING_LOCAL_STITCH_EPS_MM)
        gap = float(FILL_CENTERLINE_HANDWRITING_LOCAL_GAP_EPS_MM)
        ang = float(FILL_CENTERLINE_HANDWRITING_LOCAL_ANGLE_DEG)
    elif technical:
        eps = float(TECH_TEXT_LOCAL_STITCH_EPS_MM)
        gap = float(TECH_TEXT_LOCAL_GAP_EPS_MM)
        ang = float(TECH_TEXT_LOCAL_ANGLE_DEG)
    else:
        eps = float(FILL_CENTERLINE_LOCAL_STITCH_EPS_MM)
        gap = float(FILL_CENTERLINE_LOCAL_GAP_EPS_MM)
        ang = float(FILL_CENTERLINE_LOCAL_ANGLE_DEG)
    if handwriting:
        min_path_mm = float(FILL_CENTERLINE_HANDWRITING_MIN_PATH_MM)
    elif technical:
        min_path_mm = float(TECH_TEXT_MIN_PATH_MM)
    else:
        min_path_mm = float(FILL_CENTERLINE_MIN_PATH_MM)

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


def _likely_technical_text_group(group: List["PathItem"]) -> bool:
    # Conservative drawing-mode heuristic:
    # only small fill-only groups, typical for dimensions, notes and tiny symbols.
    if not TECH_TEXT_SINGLELINE_ENABLED:
        return False
    if HANDWRITING_TEXT_ENABLED:
        return False
    if not group:
        return False
    if not all(bool(it.is_fill) for it in group):
        return False

    bbox = _handwriting_group_bbox(group)
    if bbox is None:
        return False
    _x0, _x1, _y0, _y1, w, h, area = bbox
    if w <= 0.0 or h <= 0.0:
        return False
    if w > float(TECH_TEXT_MAX_BBOX_W_MM):
        return False
    if h > float(TECH_TEXT_MAX_BBOX_H_MM):
        return False
    if area > float(TECH_TEXT_MAX_BBOX_AREA_MM2):
        return False
    # Avoid near-square filled geometry blocks.
    if w > 10.0 and h > 8.0:
        return False

    total_len = 0.0
    for item in group:
        if len(item.points) >= 2:
            total_len += polyline_length(item.points)
    if total_len > float(TECH_TEXT_MAX_TOTAL_SOURCE_LEN_MM):
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


def _clean_technical_centerlines(
    centerlines: List[List[Tuple[float, float]]],
    min_len_mm: float = 0.03,
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


def _centerline_fill_components_with_fallback(
    group: List["PathItem"],
    *,
    handwriting: bool,
) -> Tuple[List[List[Tuple[float, float]]], List["PathItem"]]:
    if not group:
        return [], []
    components = _split_handwriting_fill_group_components(group, gap_mm=0.06) if len(group) > 1 else [group]
    converted: List[List[Tuple[float, float]]] = []
    remaining: List["PathItem"] = []
    for comp in components:
        technical = bool((not handwriting) and _likely_technical_text_group(comp))
        centerlines = centerline_fill_group(comp)
        centerlines = refine_centerline_paths(centerlines, handwriting=handwriting, technical=technical)
        if centerline_is_usable(comp, centerlines) or centerline_is_usable_relaxed_small_cluster(comp, centerlines) or (
            _likely_handwriting_text_group(comp) and _centerline_quality_ok_for_handwriting(centerlines)
        ) or (
            technical and _centerline_quality_ok_for_technical(centerlines)
        ):
            converted.extend(centerlines)
            continue
        forced_single: List[List[Tuple[float, float]]] = []
        if handwriting:
            forced_single = force_single_stroke_handwriting_group(comp, centerlines)
        elif technical:
            forced_single = force_single_stroke_technical_group(comp, centerlines)
        if forced_single:
            converted.extend(forced_single)
            continue
        tiny_fallback: List[List[Tuple[float, float]]] = []
        if handwriting:
            tiny_fallback = tiny_handwriting_text_fallback(comp, centerlines)
        elif technical:
            tiny_fallback = tiny_technical_text_fallback(comp, centerlines)
        if tiny_fallback:
            converted.extend(tiny_fallback)
            continue
        remaining.extend(comp)
    return converted, remaining


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


def tiny_technical_text_fallback(
    group: List["PathItem"],
    centerlines: List[List[Tuple[float, float]]],
) -> List[List[Tuple[float, float]]]:
    if not _likely_technical_text_group(group):
        return []
    bbox = _handwriting_group_bbox(group)
    if bbox is None:
        return []
    _x0, _x1, _y0, _y1, w, h, area = bbox
    if w <= 0.0 or h <= 0.0:
        return []
    if (
        w > float(TECH_TEXT_TINY_SYMBOL_MAX_SPAN_MM)
        or h > float(TECH_TEXT_TINY_SYMBOL_MAX_SPAN_MM)
        or area > float(TECH_TEXT_TINY_SYMBOL_MAX_AREA_MM2)
    ):
        return []
    cleaned = _clean_technical_centerlines(centerlines, min_len_mm=0.03)
    if cleaned:
        return cleaned
    return _synthetic_mono_stroke_from_bbox(
        bbox,
        max_span_mm=float(TECH_TEXT_TINY_SYMBOL_MAX_SPAN_MM),
        max_area_mm2=float(TECH_TEXT_TINY_SYMBOL_MAX_AREA_MM2),
    )


def force_single_stroke_technical_group(
    group: List["PathItem"],
    centerlines: List[List[Tuple[float, float]]],
) -> List[List[Tuple[float, float]]]:
    if not _likely_technical_text_group(group):
        return []

    cleaned = _clean_technical_centerlines(centerlines, min_len_mm=0.03)
    if cleaned:
        ordered = reorder_polylines(cleaned, logger=None)
        return merge_technical_text_strokes(ordered, logger=None)

    components = _split_handwriting_fill_group_components(group, gap_mm=0.06)
    if len(components) > 1:
        merged: List[List[Tuple[float, float]]] = []
        for comp in components:
            comp_center = centerline_fill_group(comp)
            comp_center = refine_centerline_paths(comp_center, technical=True)
            comp_clean = _clean_technical_centerlines(comp_center, min_len_mm=0.03)
            if comp_clean:
                merged.extend(comp_clean)
                continue
            comp_tiny = tiny_technical_text_fallback(comp, comp_center)
            if comp_tiny:
                merged.extend(comp_tiny)
                continue
            return []
        if merged:
            merged = reorder_polylines(merged, logger=None)
            return merge_technical_text_strokes(merged, logger=None)

    tiny = tiny_technical_text_fallback(group, centerlines)
    if tiny:
        tiny = reorder_polylines(tiny, logger=None)
        return merge_technical_text_strokes(tiny, logger=None)
    return tiny


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


def _centerline_quality_ok_for_technical(centerlines: List[List[Tuple[float, float]]]) -> bool:
    if not centerlines:
        return False
    lengths = [polyline_length(poly) for poly in centerlines if len(poly) >= 2]
    if not lengths:
        return False
    n = len(lengths)
    if n > int(TECH_TEXT_MAX_PATHS_PER_GROUP):
        return False
    s = sorted(lengths)
    med = s[n // 2]
    if med < float(TECH_TEXT_MEDIAN_MIN_PATH_MM):
        return False
    short = sum(1 for L in lengths if L < float(TECH_TEXT_SHORT_PATH_MM))
    if (short / float(n)) > float(TECH_TEXT_SHORT_RATIO_MAX):
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
    if not SINGLE_STROKE_OUTLINE_TEXT_ENABLED:
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
    if not SIMPLIFY_ENABLED:
        return poly
    return geometry_simplify_mod.simplify_polyline(
        poly,
        eps=eps,
        collinear_eps=collinear_eps,
        simplify_enabled=True,
        default_collinear_eps=float(POLYLINE_COLLINEAR_EPS),
        backtrack_spike_max_mm=float(BACKTRACK_SPIKE_MAX_MM),
    )


def parse_points(points_text: str) -> List[Tuple[float, float]]:
    return geometry_transform_mod.parse_points(points_text)


def transform_points(points: List[Tuple[float, float]], matrix: Tuple[float, float, float, float, float, float], scale: float) -> List[Tuple[float, float]]:
    return geometry_transform_mod.transform_points(points, matrix, scale)


def bounds_polylines(polylines: List[List[Tuple[float, float]]]) -> Tuple[float, float, float, float]:
    return geometry_polyline_mod.bounds_polylines(polylines)


def bounds_path_items(path_items: List[PathItem]) -> Optional[Tuple[float, float, float, float]]:
    return geometry_path_processing_mod.bounds_path_items(path_items)


def normalize_path_units_to_page(
    items: List[PathItem],
    page_w_mm: float,
    page_h_mm: float,
    logger=print,
) -> Tuple[List[PathItem], float]:
    return geometry_path_processing_mod.normalize_path_units_to_page(
        items,
        page_w_mm,
        page_h_mm,
        ratio_min=1.5,
        ratio_max=20.0,
        ratio_uniform_tol=0.20,
        logger=logger,
    )


def poly_inside_bbox(
    poly: List[Tuple[float, float]],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    eps: float,
) -> bool:
    return geometry_path_processing_mod.poly_inside_bbox(poly, x_min, x_max, y_min, y_max, eps)


def filter_outer_frame_path_items(
    items: List[PathItem],
    logger,
) -> Tuple[List[PathItem], List[PathItem]]:
    return geometry_path_processing_mod.filter_outer_frame_path_items(
        items,
        auto_trim_outer_frame=bool(AUTO_TRIM_OUTER_FRAME),
        outer_frame_edge_eps_mm=float(OUTER_FRAME_EDGE_EPS_MM),
        outer_frame_side_ratio=float(OUTER_FRAME_SIDE_RATIO),
        outer_frame_min_fill_ratio=float(OUTER_FRAME_MIN_FILL_RATIO),
        outer_frame_cover_ratio=float(OUTER_FRAME_COVER_RATIO),
        bounds_polylines_fn=bounds_polylines,
        is_axis_aligned_rectangle_fn=is_axis_aligned_rectangle,
        poly_inside_bbox_fn=poly_inside_bbox,
        logger=logger,
    )


def clip_path_items_to_rect(
    items: List[PathItem],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    logger=print,
) -> Tuple[List[PathItem], int, int]:
    def _path_item_factory(points: List[Tuple[float, float]], source_item: PathItem, closed: bool) -> PathItem:
        return PathItem(
            points=points,
            closed=closed,
            is_fill=bool(source_item.is_fill),
            is_stroke=bool(source_item.is_stroke),
            source_id=source_item.source_id,
        )

    return geometry_path_processing_mod.clip_path_items_to_rect(
        items,
        min_x,
        max_x,
        min_y,
        max_y,
        clip_segment_to_rect_fn=clip_segment_to_rect,
        clamp_to_rect_fn=clamp_to_work_area,
        point_in_rect_fn=point_in_work_area,
        points_distance_fn=points_distance,
        path_is_closed_fn=path_is_closed,
        item_factory=_path_item_factory,
        clip_continuity_eps_mm=float(CLIP_CONTINUITY_EPS_MM),
        logger=logger,
    )


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
    def _clip_cb(src_items: List[PathItem], x0: float, x1: float, y0: float, y1: float) -> Tuple[List[PathItem], int, int]:
        return clip_path_items_to_rect(src_items, x0, x1, y0, y1, logger=logger)

    return geometry_path_processing_mod.clip_to_content_area(
        items,
        page_w,
        page_h,
        page_margin_enabled=bool(PAGE_MARGIN_ENABLED),
        page_margin_left_mm=float(PAGE_MARGIN_LEFT_MM),
        page_margin_right_mm=float(PAGE_MARGIN_RIGHT_MM),
        page_margin_top_mm=float(PAGE_MARGIN_TOP_MM),
        page_margin_bottom_mm=float(PAGE_MARGIN_BOTTOM_MM),
        page_margin_a4_only=bool(PAGE_MARGIN_A4_ONLY),
        page_a4_tol_mm=float(PAGE_A4_TOL_MM),
        clip_path_items_to_rect_fn=_clip_cb,
        logger=logger,
    )


def base_work_area_bounds() -> Tuple[float, float, float, float]:
    return geometry_work_area_mod.base_work_area_bounds(
        work_area_min_x=float(WORK_AREA_MIN_X),
        work_area_max_x=float(WORK_AREA_MAX_X),
        work_area_min_y=float(WORK_AREA_MIN_Y),
        work_area_max_y=float(WORK_AREA_MAX_Y),
        work_offset_x_mm=float(WORK_OFFSET_X_MM),
        work_offset_y_mm=float(WORK_OFFSET_Y_MM),
    )


def work_area_bounds() -> Tuple[float, float, float, float]:
    return geometry_work_area_mod.work_area_bounds(
        active_work_area_bounds=ACTIVE_WORK_AREA_BOUNDS,
        base_work_area_bounds_fn=base_work_area_bounds,
    )


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
    global ACTIVE_SHEET_CONFIG
    ACTIVE_WORK_AREA_BOUNDS = geometry_work_area_mod.configure_active_work_area(
        sheet_format=sheet_format,
        sheet_width_mm=sheet_width_mm,
        sheet_height_mm=sheet_height_mm,
        anchor=anchor,
        offset_x_mm=offset_x_mm,
        offset_y_mm=offset_y_mm,
        base_bounds=base_work_area_bounds(),
        sheet_presets_mm=SHEET_PRESETS_MM,
        sheet_anchor_choices=SHEET_ANCHOR_CHOICES,
        logger=logger,
    )
    ACTIVE_SHEET_CONFIG = {
        "sheet_format": str((sheet_format or "work")).strip().lower() or "work",
        "sheet_width_mm": None if sheet_width_mm is None else float(sheet_width_mm),
        "sheet_height_mm": None if sheet_height_mm is None else float(sheet_height_mm),
        "anchor": str((anchor or "center")).strip().lower() or "center",
        "offset_x_mm": float(offset_x_mm),
        "offset_y_mm": float(offset_y_mm),
    }


def plan_tiled_passes_for_sheet(sheet_w_mm: float, sheet_h_mm: float) -> dict:
    min_x, max_x, min_y, max_y = work_area_bounds()
    return geometry_sheet_tiling_mod.plan_tiled_passes_for_sheet(
        sheet_w_mm,
        sheet_h_mm,
        area_w_mm=(max_x - min_x),
        area_h_mm=(max_y - min_y),
    )


def resolve_sheet_size_mm(
    *,
    sheet_format: str,
    sheet_width_mm: Optional[float],
    sheet_height_mm: Optional[float],
) -> Tuple[float, float]:
    min_x, max_x, min_y, max_y = work_area_bounds()
    return geometry_sheet_tiling_mod.resolve_sheet_size_mm(
        sheet_format=sheet_format,
        sheet_width_mm=sheet_width_mm,
        sheet_height_mm=sheet_height_mm,
        sheet_presets_mm=SHEET_PRESETS_MM,
        work_area_size_mm=(max_x - min_x, max_y - min_y),
    )


def _tile_window_start(total_mm: float, window_mm: float, idx0: int, count: int) -> float:
    return geometry_sheet_tiling_mod.tile_window_start(total_mm, window_mm, idx0, count)


def compute_pass_shift(
    source_w_mm: float,
    source_h_mm: float,
    window_w_mm: float,
    window_h_mm: float,
) -> Tuple[float, float, dict]:
    return geometry_sheet_tiling_mod.compute_pass_shift(
        source_w_mm,
        source_h_mm,
        window_w_mm,
        window_h_mm,
        pass_cols=int(PASS_COLS),
        pass_rows=int(PASS_ROWS),
        pass_col=int(PASS_COL),
        pass_row=int(PASS_ROW),
    )


def active_sheet_pass_rotation_deg() -> int:
    return geometry_sheet_tiling_mod.sheet_pass_rotation_deg(
        sheet_format=str(ACTIVE_SHEET_CONFIG.get("sheet_format") or "work"),
        pass_cols=int(PASS_COLS),
        pass_rows=int(PASS_ROWS),
        pass_col=int(PASS_COL),
        pass_row=int(PASS_ROW),
    )


def active_sheet_pass_post_translation_mm() -> Tuple[float, float]:
    return geometry_sheet_tiling_mod.sheet_pass_post_translation_mm(
        sheet_format=str(ACTIVE_SHEET_CONFIG.get("sheet_format") or "work"),
        pass_cols=int(PASS_COLS),
        pass_rows=int(PASS_ROWS),
        pass_col=int(PASS_COL),
        pass_row=int(PASS_ROW),
    )


def transform_polylines_for_active_sheet_pass(
    polylines: List[List[Tuple[float, float]]],
    logger=print,
) -> List[List[Tuple[float, float]]]:
    rotation_deg = int(active_sheet_pass_rotation_deg()) % 360
    shift_x_mm, shift_y_mm = active_sheet_pass_post_translation_mm()
    if not polylines or (rotation_deg == 0 and abs(shift_x_mm) <= 1e-9 and abs(shift_y_mm) <= 1e-9):
        return polylines

    min_x, max_x, min_y, max_y = work_area_bounds()
    sum_x = min_x + max_x
    sum_y = min_y + max_y

    transformed = [
        [(float(x), float(y)) for x, y in poly]
        for poly in polylines
    ]

    if rotation_deg not in {0, 180}:
        if logger:
            logger(f"Warning: unsupported sheet pass rotation {rotation_deg} deg; leaving geometry unchanged.")
        return transformed

    if rotation_deg == 180:
        transformed = [
            [(sum_x - float(x), sum_y - float(y)) for x, y in poly]
            for poly in transformed
        ]
        if logger:
            logger(
                "Sheet pass transform: "
                f"rotating geometry by 180 deg for {ACTIVE_SHEET_CONFIG.get('sheet_format')} "
                f"pass {int(PASS_COL)}/{int(PASS_COLS)} x {int(PASS_ROW)}/{int(PASS_ROWS)} "
                f"around active area center ({(min_x + max_x) * 0.5:.3f},{(min_y + max_y) * 0.5:.3f})."
            )

    if abs(shift_x_mm) > 1e-9 or abs(shift_y_mm) > 1e-9:
        transformed = [
            [(float(x) + float(shift_x_mm), float(y) + float(shift_y_mm)) for x, y in poly]
            for poly in transformed
        ]
        if logger:
            logger(
                "Sheet pass transform: "
                f"translating geometry by ({float(shift_x_mm):.3f},{float(shift_y_mm):.3f}) mm "
                f"for {ACTIVE_SHEET_CONFIG.get('sheet_format')} "
                f"pass {int(PASS_COL)}/{int(PASS_COLS)} x {int(PASS_ROW)}/{int(PASS_ROWS)}."
            )
    return transformed


def clamp_to_work_area(
    x: float,
    y: float,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> Tuple[float, float]:
    return geometry_clipping_mod.clamp_to_rect(x, y, min_x, max_x, min_y, max_y)


def point_in_work_area(x: float, y: float, min_x: float, max_x: float, min_y: float, max_y: float, eps: float = WORK_AREA_EPS) -> bool:
    return geometry_clipping_mod.point_in_rect(x, y, min_x, max_x, min_y, max_y, eps=eps)


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
    return geometry_clipping_mod.clip_segment_to_rect(x1, y1, x2, y2, min_x, max_x, min_y, max_y)


def clip_polylines_to_work_area(
    polylines: List[List[Tuple[float, float]]],
    logger=print,
) -> List[List[Tuple[float, float]]]:
    min_x, max_x, min_y, max_y = work_area_bounds()
    return geometry_clipping_mod.clip_polylines_to_rect(
        polylines,
        min_x,
        max_x,
        min_y,
        max_y,
        continuity_eps_mm=float(CLIP_CONTINUITY_EPS_MM),
        logger=logger,
        clamp_fn=clamp_to_work_area,
        point_in_rect_fn=point_in_work_area,
    )


def fit_polylines_to_area(
    polylines: List[List[Tuple[float, float]]],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    logger=print,
) -> List[List[Tuple[float, float]]]:
    return geometry_fitting_mod.fit_polylines_to_area(
        polylines,
        min_x,
        max_x,
        min_y,
        max_y,
        fit_to_work_area=bool(FIT_TO_WORK_AREA),
        work_area_bounds_fn=work_area_bounds,
        work_area_margin=float(WORK_AREA_MARGIN),
        allow_upscale_to_work_area=bool(ALLOW_UPSCALE_TO_WORK_AREA),
        exact_geometry_mode=bool(EXACT_GEOMETRY_MODE),
        min_fit_scale_for_dimensional_draw=float(MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW),
        pass_cols=int(PASS_COLS),
        pass_rows=int(PASS_ROWS),
        compute_pass_shift_fn=compute_pass_shift,
        logger=logger,
    )


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
                    if i + 1 >= len(params):
                        break
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
                    if i + 5 >= len(params):
                        break
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
                smooth_prev_cmd = prev_cmd
                for i in range(0, len(params), 4):
                    if i + 3 >= len(params):
                        break
                    p1 = (params[i], params[i + 1])
                    p2 = (params[i + 2], params[i + 3])
                    if smooth_prev_cmd.lower() in "cs":
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
                    smooth_prev_cmd = cmd
                last_cmd = cmd
                continue

            if cmd in "qQ":
                for i in range(0, len(params), 4):
                    if i + 3 >= len(params):
                        break
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
                smooth_prev_cmd = prev_cmd
                for i in range(0, len(params), 2):
                    if i + 1 >= len(params):
                        break
                    p2 = (params[i], params[i + 1])
                    if smooth_prev_cmd.lower() in "qt":
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
                    smooth_prev_cmd = cmd
                last_cmd = cmd
                continue

            if cmd in "aA":
                for i in range(0, len(params), 7):
                    if i + 6 >= len(params):
                        break
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
            technical = bool((not handwriting) and _likely_technical_text_group(group))
            centerlines = centerline_fill_group(group)
            centerlines = refine_centerline_paths(centerlines, handwriting=handwriting, technical=technical)
            if centerline_is_usable(group, centerlines) or centerline_is_usable_relaxed_small_cluster(group, centerlines) or (
                _likely_handwriting_text_group(group) and _centerline_quality_ok_for_handwriting(centerlines)
            ) or (
                technical and _centerline_quality_ok_for_technical(centerlines)
            ):
                out.extend(centerlines)
                consumed_idx.update(comp)
                continue
            if technical:
                forced = force_single_stroke_technical_group(group, centerlines)
                if forced:
                    out.extend(forced)
                    consumed_idx.update(comp)

    if SINGLE_STROKE_OUTLINE_TEXT_ENABLED and not preserve_fill_outlines:
        outline_clusters = cluster_small_outline_items_for_single_stroke(items)
        for comp in outline_clusters:
            if any(i in consumed_idx for i in comp):
                continue
            group = [items[i] for i in comp]
            centerlines = centerline_fill_group(group)
            centerlines = refine_centerline_paths(centerlines, handwriting=handwriting)
            if centerline_is_usable(group, centerlines) or centerline_is_usable_relaxed_small_cluster(group, centerlines) or _centerline_quality_ok_for_handwriting(centerlines):
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
            if centerline_is_usable(group, centerlines) or centerline_is_usable_relaxed_small_cluster(group, centerlines):
                out.extend(centerlines)
                continue

        # Some PDF text glyphs come as fill+stroke simultaneously.
        # Prefer a single centerline stroke when stable, otherwise keep original geometry.
        if is_fill and (not preserve_fill_outlines):
            converted, rem = _centerline_fill_components_with_fallback(group, handwriting=handwriting)
            if converted:
                out.extend(converted)
            if not rem:
                continue
            group = rem

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
                converted, rem = _centerline_fill_components_with_fallback(fill_rest, handwriting=handwriting)
                if converted:
                    out.extend(converted)
                if not rem:
                    continue
                fill_rest = rem

        for item in (fill_rest if (is_fill and not is_stroke) else group):
            if len(item.points) >= 2:
                out.append(item.points)

    return out


def translate_polylines(polylines: List[List[Tuple[float, float]]], dx: float, dy: float) -> List[List[Tuple[float, float]]]:
    return geometry_polyline_mod.translate_polylines(polylines, dx, dy)

def points_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return geometry_polyline_mod.points_distance(a, b)


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


def _canonical_segment_axis(
    a: Tuple[float, float],
    b: Tuple[float, float],
) -> Optional[Tuple[float, float, float, float, float, float, float, float, float]]:
    dx = float(b[0]) - float(a[0])
    dy = float(b[1]) - float(a[1])
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    ux = dx / length
    uy = dy / length
    # Directionless canonical axis: A->B and B->A must land in the same bucket.
    if ux < -1e-12 or (abs(ux) <= 1e-12 and uy < 0.0):
        ux = -ux
        uy = -uy
    nx = -uy
    ny = ux
    offset = float(a[0]) * nx + float(a[1]) * ny
    t0 = float(a[0]) * ux + float(a[1]) * uy
    t1 = float(b[0]) * ux + float(b[1]) * uy
    if t1 < t0:
        t0, t1 = t1, t0
    angle = math.atan2(uy, ux)
    if angle < 0.0:
        angle += math.pi
    return ux, uy, nx, ny, offset, t0, t1, length, angle


def _collinear_overlap_ratio(a0: float, a1: float, b0: float, b1: float) -> Tuple[float, float]:
    overlap = min(float(a1), float(b1)) - max(float(a0), float(b0))
    if overlap <= 0.0:
        return 0.0, 0.0
    shorter = max(1e-9, min(abs(float(a1) - float(a0)), abs(float(b1) - float(b0))))
    return overlap / shorter, overlap


def _find_redundant_collinear_segment_keys(
    segments: List[Tuple[object, Tuple[float, float], Tuple[float, float]]],
    *,
    dist_mm: float = COLLINEAR_OVERLAP_DEDUP_DIST_MM,
    angle_deg: float = COLLINEAR_OVERLAP_DEDUP_ANGLE_DEG,
    min_len_mm: float = COLLINEAR_OVERLAP_DEDUP_MIN_LEN_MM,
    min_overlap_ratio: float = COLLINEAR_OVERLAP_DEDUP_MIN_RATIO,
) -> set[object]:
    if not segments or not COLLINEAR_OVERLAP_DEDUP_ENABLED:
        return set()

    dist_tol = max(0.0, float(dist_mm))
    angle_tol = math.radians(max(0.01, float(angle_deg)))
    min_len = max(0.0, float(min_len_mm))
    min_ratio = max(0.0, min(1.0, float(min_overlap_ratio)))
    if dist_tol <= 0.0 or min_ratio <= 0.0:
        return set()

    indexed: List[
        Tuple[
            float,
            object,
            Tuple[float, float],
            Tuple[float, float],
            Tuple[float, float, float, float, float, float, float, float, float],
        ]
    ] = []
    for key, a, b in segments:
        axis = _canonical_segment_axis(a, b)
        if axis is not None and axis[7] >= min_len:
            indexed.append((axis[7], key, a, b, axis))

    angle_cell = max(angle_tol, 1e-6)
    offset_cell = max(dist_tol, 1e-6)
    accepted: dict[Tuple[int, int], List[Tuple[float, float, float, float, float, float, float, float, float]]] = {}
    dropped: set[object] = set()
    cos_tol = math.cos(angle_tol)

    def _angle_bucket(axis: Tuple[float, float, float, float, float, float, float, float, float]) -> int:
        return int(round(axis[8] / angle_cell))

    def _offset_bucket_for_angle(angle_key: int, point: Tuple[float, float]) -> int:
        bucket_angle = float(angle_key) * angle_cell
        bucket_nx = -math.sin(bucket_angle)
        bucket_ny = math.cos(bucket_angle)
        return int(round((float(point[0]) * bucket_nx + float(point[1]) * bucket_ny) / offset_cell))

    for _length, key, a, b, axis in sorted(indexed, key=lambda row: row[0], reverse=True):
        angle_key = _angle_bucket(axis)
        duplicate = False
        for da in (-1, 0, 1):
            query_angle_key = angle_key + da
            offset_key = _offset_bucket_for_angle(query_angle_key, a)
            for doff in range(-3, 4):
                for other in accepted.get((query_angle_key, offset_key + doff), []):
                    dot = abs(axis[0] * other[0] + axis[1] * other[1])
                    if dot < cos_tol:
                        continue
                    current_t0 = float(a[0]) * other[0] + float(a[1]) * other[1]
                    current_t1 = float(b[0]) * other[0] + float(b[1]) * other[1]
                    if current_t1 < current_t0:
                        current_t0, current_t1 = current_t1, current_t0
                    ratio, overlap_len = _collinear_overlap_ratio(current_t0, current_t1, other[5], other[6])
                    if ratio < min_ratio or overlap_len < min_len:
                        continue
                    overlap_mid_t = (max(current_t0, other[5]) + min(current_t1, other[6])) * 0.5
                    other_mid = (
                        other[0] * overlap_mid_t + other[2] * other[4],
                        other[1] * overlap_mid_t + other[3] * other[4],
                    )
                    current_mid_t = (other_mid[0] - float(a[0])) * axis[0] + (other_mid[1] - float(a[1])) * axis[1]
                    current_mid = (
                        float(a[0]) + axis[0] * current_mid_t,
                        float(a[1]) + axis[1] * current_mid_t,
                    )
                    if points_distance(current_mid, other_mid) <= dist_tol:
                        duplicate = True
                        break
                if duplicate:
                    break
            if duplicate:
                break
        if duplicate:
            dropped.add(key)
            continue

        stored_keys: set[Tuple[int, int]] = set()
        for store_angle_key in (angle_key - 1, angle_key, angle_key + 1):
            store_key = (store_angle_key, _offset_bucket_for_angle(store_angle_key, a))
            if store_key in stored_keys:
                continue
            stored_keys.add(store_key)
            accepted.setdefault(store_key, []).append(axis)

    return dropped


def deduplicate_collinear_overlaps(
    polylines: List[List[Tuple[float, float]]],
    *,
    dist_mm: float = COLLINEAR_OVERLAP_DEDUP_DIST_MM,
    angle_deg: float = COLLINEAR_OVERLAP_DEDUP_ANGLE_DEG,
    min_len_mm: float = COLLINEAR_OVERLAP_DEDUP_MIN_LEN_MM,
    min_overlap_ratio: float = COLLINEAR_OVERLAP_DEDUP_MIN_RATIO,
    logger=print,
) -> List[List[Tuple[float, float]]]:
    # Remove same-line overlapping strokes even when the PDF split one line into
    # different-length fragments. Do not delete real parallel table/frame lines.
    if not polylines or not COLLINEAR_OVERLAP_DEDUP_ENABLED:
        return polylines

    dist_tol = max(0.0, float(dist_mm))
    angle_tol = math.radians(max(0.01, float(angle_deg)))
    min_len = max(0.0, float(min_len_mm))
    min_ratio = max(0.0, min(1.0, float(min_overlap_ratio)))
    segments: List[Tuple[Tuple[int, int], Tuple[float, float], Tuple[float, float]]] = []
    for poly_idx, poly in enumerate(polylines):
        if len(poly) < 2:
            continue
        prev = poly[0]
        for seg_idx, pt in enumerate(poly[1:]):
            axis = _canonical_segment_axis(prev, pt)
            if axis is not None and axis[7] >= min_len:
                segments.append(((poly_idx, seg_idx), prev, pt))
            prev = pt

    if not segments:
        return polylines

    dropped = _find_redundant_collinear_segment_keys(
        segments,
        dist_mm=dist_mm,
        angle_deg=angle_deg,
        min_len_mm=min_len_mm,
        min_overlap_ratio=min_overlap_ratio,
    )

    if not dropped:
        return polylines

    out: List[List[Tuple[float, float]]] = []
    src_segments = 0
    for poly_idx, poly in enumerate(polylines):
        if len(poly) < 2:
            continue
        current: List[Tuple[float, float]] = []
        prev = poly[0]
        for seg_idx, pt in enumerate(poly[1:]):
            src_segments += 1
            if (poly_idx, seg_idx) in dropped:
                if current:
                    simplified = simplify_polyline(current)
                    if len(simplified) >= 2:
                        out.append(simplified)
                    current = []
                prev = pt
                continue
            if not current:
                current = [prev, pt]
            elif points_distance(current[-1], prev) <= 1e-9:
                current.append(pt)
            else:
                simplified = simplify_polyline(current)
                if len(simplified) >= 2:
                    out.append(simplified)
                current = [prev, pt]
            prev = pt
        if current:
            simplified = simplify_polyline(current)
            if len(simplified) >= 2:
                out.append(simplified)

    if logger:
        logger(
            f"Collinear overlap dedup: dropped {len(dropped)}/{src_segments} overlapping segments "
            f"(dist<={dist_tol:.3f} mm, angle<={math.degrees(angle_tol):.2f} deg, overlap>={min_ratio:.2f})"
        )
    return out if out else polylines


def final_cleanup_polylines_for_gcode(
    polylines: List[List[Tuple[float, float]]],
    *,
    exact_eps: float = SEGMENT_DEDUP_EPS_MM,
    max_rounds: int = 3,
    logger=print,
) -> List[List[Tuple[float, float]]]:
    line_fit_tol = 0.0 if HANDWRITING_TEXT_ENABLED else float(LINE_FIT_TOL_MM)

    def _normalize_for_writer(src: List[List[Tuple[float, float]]]) -> List[List[Tuple[float, float]]]:
        normalized: List[List[Tuple[float, float]]] = []
        for poly in src:
            if len(poly) < 2:
                continue
            current = simplify_polyline(poly)
            if line_fit_tol > 0.0 and len(current) >= 2 and polyline_is_near_line(current, line_fit_tol):
                current = [current[0], current[-1]]
            if len(current) >= 2:
                normalized.append(current)
        return normalized

    simplified = _normalize_for_writer(polylines)
    if not simplified:
        return polylines
    cleaned = simplified
    rounds = max(1, int(max_rounds))
    for _round in range(rounds):
        # Dedup can split a noisy polyline into a shape that the writer later
        # line-fits into one long G1 move. Re-normalize every round so overlap
        # checks see the exact same line-fit form that write_xy_gcode will emit.
        cleaned = _normalize_for_writer(cleaned)
        before_segments = sum(max(0, len(poly) - 1) for poly in cleaned)
        next_cleaned = deduplicate_segments(cleaned, eps=exact_eps, logger=logger)
        next_cleaned = deduplicate_collinear_overlaps(next_cleaned, logger=logger)
        next_cleaned = _normalize_for_writer(next_cleaned)
        after_segments = sum(max(0, len(poly) - 1) for poly in next_cleaned)
        cleaned = next_cleaned
        if after_segments >= before_segments:
            break
    return cleaned


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


def _technical_stroke_bbox(poly: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float, float, float, float, float]]:
    if len(poly) < 2 or path_is_closed(poly):
        return None
    xs = [float(pt[0]) for pt in poly]
    ys = [float(pt[1]) for pt in poly]
    x0 = min(xs)
    x1 = max(xs)
    y0 = min(ys)
    y1 = max(ys)
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    area = w * h
    return (x0, x1, y0, y1, w, h, area)


def _is_technical_join_candidate(poly: List[Tuple[float, float]]) -> bool:
    if not TECH_TEXT_JOIN_ENABLE:
        return False
    bbox = _technical_stroke_bbox(poly)
    if bbox is None:
        return False
    _x0, _x1, _y0, _y1, w, h, area = bbox
    if w <= 0.0 and h <= 0.0:
        return False
    if max(w, h) > float(TECH_TEXT_JOIN_MAX_SPAN_MM):
        return False
    if area > float(TECH_TEXT_JOIN_MAX_AREA_MM2):
        return False
    if polyline_length(poly) > float(TECH_TEXT_JOIN_MAX_STROKE_LEN_MM):
        return False
    return True


def _technical_join_combined_bbox_ok(
    first: List[Tuple[float, float]],
    second: List[Tuple[float, float]],
) -> bool:
    first_box = _technical_stroke_bbox(first)
    second_box = _technical_stroke_bbox(second)
    if first_box is None or second_box is None:
        return False
    comb_x0 = min(first_box[0], second_box[0])
    comb_x1 = max(first_box[1], second_box[1])
    comb_y0 = min(first_box[2], second_box[2])
    comb_y1 = max(first_box[3], second_box[3])
    comb_w = comb_x1 - comb_x0
    comb_h = comb_y1 - comb_y0
    comb_area = comb_w * comb_h
    return not (
        comb_w > float(TECH_TEXT_JOIN_MAX_COMBINED_SPAN_X_MM)
        or comb_h > float(TECH_TEXT_JOIN_MAX_COMBINED_SPAN_Y_MM)
        or comb_area > float(TECH_TEXT_JOIN_MAX_COMBINED_AREA_MM2)
    )


def _technical_join_step_allowed(
    current: List[Tuple[float, float]],
    nxt: List[Tuple[float, float]],
    *,
    gap_max: float,
    dy_max: float,
    backtrack_max: float,
) -> tuple[bool, float]:
    if not _is_technical_join_candidate(current) or not _is_technical_join_candidate(nxt):
        return False, 0.0
    gap = points_distance(current[-1], nxt[0])
    dy = abs(float(nxt[0][1]) - float(current[-1][1]))
    dx = float(nxt[0][0]) - float(current[-1][0])
    if gap > float(gap_max) or dy > float(dy_max) or dx < (-float(backtrack_max)):
        return False, gap
    if not _technical_join_combined_bbox_ok(current, nxt):
        return False, gap
    return True, gap


def _merge_technical_text_strokes_by_nearest_endpoint(
    polylines: List[List[Tuple[float, float]]],
    *,
    gap_max: float,
    dy_max: float,
    backtrack_max: float,
    simplify_collinear_eps: Optional[float],
) -> Tuple[List[List[Tuple[float, float]]], int]:
    # MuPDF/KOMPAS can emit one glyph as many tiny paths not adjacent in source
    # order. A conservative nearest-endpoint pass reconnects only tiny technical
    # strokes whose combined bbox still looks like one glyph/symbol fragment.
    src = [p for p in polylines if len(p) >= 2]
    if len(src) < 2:
        return src, 0
    candidate = [_is_technical_join_candidate(p) for p in src]
    unused = set(range(len(src)))
    out: List[List[Tuple[float, float]]] = []
    merged_count = 0

    for idx, poly in enumerate(src):
        if idx not in unused:
            continue
        unused.remove(idx)
        if not candidate[idx]:
            out.append(poly)
            continue

        current = list(poly)
        while _is_technical_join_candidate(current):
            best_idx: Optional[int] = None
            best_poly: Optional[List[Tuple[float, float]]] = None
            best_gap = float("inf")
            for other_idx in tuple(unused):
                if not candidate[other_idx]:
                    continue
                raw_next = src[other_idx]
                for nxt in (raw_next, list(reversed(raw_next))):
                    allowed, gap = _technical_join_step_allowed(
                        current,
                        nxt,
                        gap_max=gap_max,
                        dy_max=dy_max,
                        backtrack_max=backtrack_max,
                    )
                    if allowed and gap < best_gap:
                        best_idx = other_idx
                        best_poly = nxt
                        best_gap = gap
            if best_idx is None or best_poly is None:
                break
            if best_gap > 1e-9:
                current.append(best_poly[0])
            current.extend(best_poly[1:])
            current = simplify_polyline(current, collinear_eps=simplify_collinear_eps)
            unused.remove(best_idx)
            merged_count += 1

        current = simplify_polyline(current, collinear_eps=simplify_collinear_eps)
        if len(current) >= 2:
            out.append(current)

    return out, merged_count


def merge_technical_text_strokes(
    polylines: List[List[Tuple[float, float]]],
    logger=print,
    *,
    join_gap_mm: Optional[float] = None,
    join_max_dy_mm: Optional[float] = None,
    join_max_backtrack_mm: Optional[float] = None,
    simplify_collinear_eps: Optional[float] = None,
) -> List[List[Tuple[float, float]]]:
    # Conservative continuity join for short technical glyph/symbol strokes.
    # It targets tiny fragmented text/symbol pieces and avoids large geometry.
    if not TECH_TEXT_JOIN_ENABLE:
        return polylines
    if not polylines:
        return polylines

    gap_max = max(0.0, float(TECH_TEXT_JOIN_GAP_MM if join_gap_mm is None else join_gap_mm))
    dy_max = max(0.0, float(TECH_TEXT_JOIN_MAX_DY_MM if join_max_dy_mm is None else join_max_dy_mm))
    backtrack_max = max(
        0.0,
        float(TECH_TEXT_JOIN_MAX_BACKTRACK_MM if join_max_backtrack_mm is None else join_max_backtrack_mm),
    )
    if gap_max <= 1e-9:
        return polylines

    src = [p for p in polylines if len(p) >= 2]
    if not src:
        return []

    merged_count = 0
    ordered_merged_count = 0
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

        can_merge, _step_gap = _technical_join_step_allowed(
            current,
            nxt,
            gap_max=gap_max,
            dy_max=dy_max,
            backtrack_max=backtrack_max,
        )

        if can_merge:
            if gap > 1e-9:
                current.append(nxt[0])
            current.extend(nxt[1:])
            current = simplify_polyline(current, collinear_eps=simplify_collinear_eps)
            merged_count += 1
            ordered_merged_count += 1
            continue

        current = simplify_polyline(current, collinear_eps=simplify_collinear_eps)
        if len(current) >= 2:
            out.append(current)
        current = list(nxt)

    current = simplify_polyline(current, collinear_eps=simplify_collinear_eps)
    if len(current) >= 2:
        out.append(current)

    out, nearest_merged_count = _merge_technical_text_strokes_by_nearest_endpoint(
        out,
        gap_max=gap_max,
        dy_max=dy_max,
        backtrack_max=backtrack_max,
        simplify_collinear_eps=simplify_collinear_eps,
    )
    merged_count += nearest_merged_count

    if logger and merged_count > 0:
        logger(
            f"Technical text join: merged {merged_count} short gaps "
            f"(ordered={ordered_merged_count}, nearest={nearest_merged_count}, "
            f"gap<={gap_max:.2f} mm, dy<={dy_max:.2f} mm), polylines {len(src)} -> {len(out)}"
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


def _build_corner_mark_polylines_for_bounds(
    bounds: Tuple[float, float, float, float],
    *,
    mark_size: float,
) -> List[List[Tuple[float, float]]]:
    min_x, max_x, min_y, max_y = bounds
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


def build_active_area_corner_mark_polylines(mark_size: float = 2.0) -> List[List[Tuple[float, float]]]:
    return _build_corner_mark_polylines_for_bounds(work_area_bounds(), mark_size=mark_size)


def build_a4_corner_mark_polylines(mark_size: float = 2.0) -> List[List[Tuple[float, float]]]:
    return build_active_area_corner_mark_polylines(mark_size=mark_size)


def build_a3_corner_mark_polylines(mark_size: float = 2.0) -> List[List[Tuple[float, float]]]:
    return build_active_area_corner_mark_polylines(mark_size=mark_size)


def active_calibration_profile_name() -> str:
    fmt = str(ACTIVE_SHEET_CONFIG.get("sheet_format") or "work").strip().lower()
    if fmt == "a4":
        return "a4"
    if fmt == "a3":
        if int(PASS_COLS) > 1 or int(PASS_ROWS) > 1:
            return f"a3_pass_{min(max(1, int(PASS_COL)), max(1, int(PASS_COLS)))}"
        return "a3"
    if fmt == "custom":
        return "custom"
    if fmt == "notebook":
        return "notebook"
    return "work"


def build_area_corner_mark_polylines(mark_size: float = 2.0) -> List[List[Tuple[float, float]]]:
    fmt = str(ACTIVE_SHEET_CONFIG.get("sheet_format") or "work").strip().lower()
    if fmt == "a4":
        return build_a4_corner_mark_polylines(mark_size=mark_size)
    if fmt == "a3":
        return build_a3_corner_mark_polylines(mark_size=mark_size)
    return build_active_area_corner_mark_polylines(mark_size=mark_size)


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
    force_full_lift: bool = False,
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
    if force_full_lift or SAFE_PEN_TRAVEL_UP:
        # Full-lift must win even in pencil mode; otherwise a caller asking for
        # a safe contour-to-contour lift still gets the short travel lift.
        travel_lift_mm = max(travel_lift_mm, abs(float(z_down) - float(Z_UP)) + 0.1)
    elif TOOL_MODE == "pencil":
        # Pencil plotting is much faster and still stable with a short travel lift.
        # Keep lift inside requested operational band (3..4 mm).
        travel_lift_mm = min(4.0, max(3.0, travel_lift_mm))
    gcode_penlift_mod.run_penlift_postprocess(
        xy_gcode,
        pen_gcode,
        python_executable=sys.executable,
        script_path=script,
        z_down=float(z_down),
        z_up=float(Z_UP),
        pen_lift_mode=PEN_LIFT_MODE,
        pen_spindle_speed=int(PEN_SPINDLE_SPEED),
        z_delay_down=float(z_delay_down_eff),
        z_delay_up=float(z_delay_up_eff),
        z_feed_down_approach=float(z_feed_down_approach_eff),
        z_feed_down_touch=float(z_feed_down_touch_eff),
        z_feed_up=float(z_feed_up_eff),
        z_feed_up_final=float(z_feed_up_final_eff),
        z_soft_down_mm=float(z_soft_down_eff),
        z_soft_up_mm=float(z_soft_up_eff),
        z_travel_lift_mm=float(travel_lift_mm),
        dynamic_z_enable=bool(dynamic_z_enable),
        dynamic_base_z_down=dynamic_base_z_down,
        dynamic_initial_wear_mm=float(dynamic_initial_wear_mm),
        dynamic_wear_mm_per_m=float(PENCIL_WEAR_MM_PER_M),
        dynamic_z_comp_per_wear=float(PENCIL_Z_COMP_MM_PER_WEAR_MM),
        dynamic_z_max_comp_mm=float(PENCIL_MAX_COMP_MM),
        stroke_z_jitter_enable=bool(PENCIL_STROKE_Z_JITTER_ENABLED),
        stroke_z_jitter_mm=float(PENCIL_STROKE_Z_JITTER_MM),
        stroke_z_jitter_seed=int(PENCIL_STROKE_Z_JITTER_SEED),
        # Technical merge is experimental and off by default; generic drawings
        # otherwise can get parasitic connector strokes in text/tables.
        merge_short_travel_enable=bool(
            (HANDWRITING_MERGE_SHORT_TRAVEL_ENABLE and handwriting_mode)
            or (TECH_TEXT_PENLIFT_OPT_ENABLE and not handwriting_mode)
        ),
        merge_short_travel_mm=float(
            HANDWRITING_MERGE_SHORT_TRAVEL_MM if handwriting_mode else TECH_TEXT_PENLIFT_SHORT_TRAVEL_MM
        ),
        merge_short_travel_feed=float(
            HANDWRITING_MERGE_SHORT_TRAVEL_FEED if handwriting_mode else TECH_TEXT_PENLIFT_SHORT_TRAVEL_FEED
        ),
        run_cmd=run_cmd,
    )


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
                raise ConversionError("Text->path conversion required and failed.")
            logger(f"Text nodes after conversion: {svg_text_node_count(svg_target)}")
        return had_text, handwriting_nodes

    def score_svg_quality(svg_target: Path) -> Tuple[float, str]:
        return pdf_converter_mod.score_svg_quality(
            svg_target,
            extract_polylines=extract_polylines,
            to_drawing_polylines=to_drawing_polylines,
            points_distance=points_distance,
            svg_page_size_mm=svg_page_size_mm,
            bounds_path_items=bounds_path_items,
        )

    exports: List[Tuple[str, Path, bool, int]] = []
    # Keep non-interactive behavior by default:
    # do not force Inkscape PDF import from handwriting mode, because some environments
    # may still show the "PDF import options" window.
    # In handwriting mode prefer Inkscape PDF import as well:
    # it can preserve editable text nodes before text->path conversion and
    # usually yields cleaner glyph geometry than pdftocairo-only output.
    try_inkscape = bool(USE_INKSCAPE_PDF_IMPORT or HANDWRITING_TEXT_ENABLED)
    exports = pdf_converter_mod.collect_pdf_converter_exports(
        pdf_path,
        svg_path,
        logger,
        try_inkscape=try_inkscape,
        postprocess=postprocess_text,
        svg_has_text_nodes=svg_has_text_nodes,
        find_inkscape=find_inkscape,
        run_cmd=run_cmd,
        get_inkscape_version=get_inkscape_version,
        find_pdftocairo=find_pdftocairo,
    )

    if not exports:
        if not USE_INKSCAPE_PDF_IMPORT:
            raise ToolDependencyError(
                "Failed to convert PDF to SVG with pdftocairo. "
                "Install/configure Poppler pdftocairo or enable Inkscape PDF import in code."
            )
        raise ConversionError("Failed to convert PDF to SVG with both Inkscape and pdftocairo.")

    scored = pdf_converter_mod.score_converter_exports(
        exports,
        logger,
        score_svg_quality=score_svg_quality,
    )
    best_name, best_svg, best_score, best_details, _best_had_text, _best_hw_nodes = (
        pdf_converter_mod.select_best_scored_export(
            scored,
            logger,
            handwriting_enabled=bool(HANDWRITING_TEXT_ENABLED),
        )
    )
    HANDWRITING_STROKE_ACTIVE = bool(HANDWRITING_TEXT_ENABLED and (_best_hw_nodes > 0))

    if svg_path.exists():
        svg_path.unlink()
    shutil.copyfile(str(best_svg), str(svg_path))
    logger(f"Selected PDF converter: {best_name} ({best_details})")


def _normalize_word_font_name(font_name: Optional[str], default: str = "") -> str:
    return word_converter_mod.normalize_word_font_name(font_name, default=default)


def _apply_word_formula_font(doc, formula_font: Optional[str], logger) -> int:
    return word_converter_mod.apply_word_formula_font(
        doc,
        formula_font,
        logger,
        handwriting_word_keep_math=HANDWRITING_WORD_KEEP_MATH,
    )


def apply_word_handwriting_font(
    doc,
    font_name: str,
    logger,
    math_font: Optional[str] = None,
) -> Tuple[bool, int]:
    return word_converter_mod.apply_word_handwriting_font(
        doc,
        font_name,
        logger,
        math_font=math_font,
        normalize_handwriting_font_name=normalize_handwriting_font_name,
        handwriting_word_keep_math=HANDWRITING_WORD_KEEP_MATH,
    )


def word_to_pdf(
    word_path: Path,
    pdf_path: Path,
    logger,
    override_font: Optional[str] = None,
    formula_font: Optional[str] = None,
) -> None:
    word_converter_mod.word_to_pdf(
        word_path,
        pdf_path,
        logger,
        normalize_handwriting_font_name=normalize_handwriting_font_name,
        pdf_text_questionmark_metrics=pdf_text_questionmark_metrics,
        handwriting_word_max_qmark_count=int(HANDWRITING_WORD_MAX_QMARK_COUNT),
        handwriting_word_max_qmark_ratio=float(HANDWRITING_WORD_MAX_QMARK_RATIO),
        handwriting_word_keep_math=bool(HANDWRITING_WORD_KEEP_MATH),
        wait_until_path_unlocked_fn=_wait_until_path_unlocked,
        override_font=override_font,
        formula_font=formula_font,
    )


def _wait_for_nonempty_file(path: Path, timeout_s: float = 15.0, poll_s: float = 0.25, stable_polls: int = 2) -> bool:
    return cad_converter_mod.wait_for_nonempty_file(
        path,
        timeout_s=timeout_s,
        poll_s=poll_s,
        stable_polls=stable_polls,
    )


def _wait_until_path_unlocked(path: Path, timeout_s: float = 8.0, poll_s: float = 0.20) -> bool:
    return runtime_utils_mod.wait_until_path_unlocked(path, timeout_s=timeout_s, poll_s=poll_s)


def _kompas_print_to_pdf(input_path: Path, output_pdf: Path, logger) -> None:
    cad_converter_mod.kompas_print_to_pdf(
        input_path,
        output_pdf,
        logger,
        wait_for_nonempty_file_fn=_wait_for_nonempty_file,
    )


def frw_to_pdf(frw_path: Path, pdf_path: Path, logger) -> None:
    cad_converter_mod.frw_to_pdf(
        frw_path,
        pdf_path,
        logger,
        ensure_local_tmp_root=ensure_local_tmp_root,
        find_spec=importlib.util.find_spec,
        kompas_print_to_pdf_fn=_kompas_print_to_pdf,
        wait_for_nonempty_file_fn=_wait_for_nonempty_file,
    )

def make_final_with_preamble(prepared_gcode: Path, final_gcode: Path) -> None:
    gcode_finalize_mod.make_final_with_preamble(
        prepared_gcode,
        final_gcode,
        z_up=float(Z_UP),
        safe_lift_feed=float(SAFE_LIFT_FEED),
        z_delay_up=float(Z_DELAY_UP),
        home_x=float(HOME_X),
        home_y=float(HOME_Y),
        feed_travel=float(FEED_TRAVEL),
        go_home_before_draw=bool(GO_HOME_BEFORE_DRAW),
        go_home_after_draw=bool(GO_HOME_AFTER_DRAW),
    )
    rewrite_duplicate_draw_segments_as_penup_travel(final_gcode)


_GCODE_TOKEN_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


def _gcode_line_without_comment(line: str) -> str:
    line = str(line or "").split(";", 1)[0]
    out: List[str] = []
    depth = 0
    for ch in line:
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip()


def _gcode_line_tokens(line: str) -> Dict[str, float]:
    return {axis.upper(): float(value) for axis, value in _GCODE_TOKEN_RE.findall(line)}


def _gcode_has_word(line: str, letter: str, number: int) -> bool:
    return re.search(rf"(?<![A-Z0-9.]){letter.upper()}0*{number}(?![0-9.])", str(line).upper()) is not None


def _gcode_motion_code(line: str, previous: Optional[str]) -> Optional[str]:
    for number, canonical in ((0, "G0"), (1, "G1"), (2, "G2"), (3, "G3")):
        if _gcode_has_word(line, "G", number):
            return canonical
    return previous


def cleanup_xy_gcode_overlaps(xy_gcode: Path, logger=print) -> int:
    try:
        raw_lines = xy_gcode.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0

    cur_x: Optional[float] = None
    cur_y: Optional[float] = None
    modal: Optional[str] = None
    segments: List[Tuple[int, Tuple[float, float], Tuple[float, float]]] = []

    for line_idx, raw_line in enumerate(raw_lines):
        line = _gcode_line_without_comment(raw_line)
        if not line:
            continue
        modal = _gcode_motion_code(line, modal)
        vals = _gcode_line_tokens(line)
        old_x, old_y = cur_x, cur_y
        next_x = vals.get("X", cur_x)
        next_y = vals.get("Y", cur_y)
        has_xy = "X" in vals or "Y" in vals
        if has_xy and old_x is not None and old_y is not None and next_x is not None and next_y is not None:
            if modal == "G1" and points_distance((float(old_x), float(old_y)), (float(next_x), float(next_y))) > 1e-6:
                segments.append((line_idx, (float(old_x), float(old_y)), (float(next_x), float(next_y))))
        cur_x, cur_y = next_x, next_y

    dropped = _find_redundant_collinear_segment_keys(segments)
    if not dropped:
        return 0

    for line_idx in sorted(int(idx) for idx in dropped):
        raw = raw_lines[line_idx]
        replaced = re.sub(r"(?i)(?<![A-Z0-9.])G0*1(?![0-9.])", "G0", raw, count=1)
        if replaced == raw:
            replaced = "G0 " + raw
        raw_lines[line_idx] = replaced

    xy_gcode.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    if logger:
        logger(f"Final XY G-code overlap cleanup: converted {len(dropped)} redundant draw move(s) to travel.")
    return len(dropped)


def _gcode_segment_key(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    ndigits: int = 3,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    p0 = (round(float(x0), ndigits), round(float(y0), ndigits))
    p1 = (round(float(x1), ndigits), round(float(y1), ndigits))
    return (p0, p1) if p0 <= p1 else (p1, p0)


def rewrite_duplicate_draw_segments_as_penup_travel(
    gcode_path: Path,
    *,
    z_up: float = Z_UP,
    z_down: float = Z_DOWN,
    feed_travel: float = FEED_TRAVEL,
    z_feed: float = PEN_FAST_Z_FEED_UP,
    logger=None,
) -> int:
    # Last-resort guard after line/arc fitting. If a final G-code segment would
    # draw over an already drawn segment, move over that segment with the pen up
    # and restore the previous down state before the next draw command.
    try:
        original = gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return 0

    cur_x: Optional[float] = None
    cur_y: Optional[float] = None
    cur_z: Optional[float] = None
    modal: Optional[str] = None
    spindle_down = False
    seen: set[Tuple[Tuple[float, float], Tuple[float, float]]] = set()
    rewritten: List[str] = []
    dropped = 0
    z_threshold = (float(z_up) + float(z_down)) / 2.0

    def _down(z_value: Optional[float]) -> bool:
        if spindle_down:
            return True
        if z_value is None:
            return False
        if float(z_down) >= float(z_up):
            return float(z_value) > z_threshold
        return float(z_value) < z_threshold

    for raw_line in original:
        clean = _gcode_line_without_comment(raw_line)
        if not clean:
            rewritten.append(raw_line)
            continue
        upper = clean.upper()
        vals = _gcode_line_tokens(clean)

        if "M3" in upper or "M03" in upper:
            spindle_down = True
        if "M5" in upper or "M05" in upper:
            spindle_down = False

        modal = _gcode_motion_code(clean, modal)
        if re.search(r"(^|\s)G92(\s|$)", upper):
            cur_x = vals.get("X", cur_x)
            cur_y = vals.get("Y", cur_y)
            cur_z = vals.get("Z", cur_z)
            rewritten.append(raw_line)
            continue

        next_x = vals.get("X", cur_x)
        next_y = vals.get("Y", cur_y)
        next_z = vals.get("Z", cur_z)
        has_xy = "X" in vals or "Y" in vals
        is_draw_xy = (
            has_xy
            and modal in {"G1", "G2", "G3"}
            and cur_x is not None
            and cur_y is not None
            and next_x is not None
            and next_y is not None
            and _down(next_z)
            and math.hypot(float(next_x) - float(cur_x), float(next_y) - float(cur_y)) > 0.03
        )

        if is_draw_xy:
            key = _gcode_segment_key(float(cur_x), float(cur_y), float(next_x), float(next_y))
            if key in seen:
                rewritten.extend(
                    [
                        f"G1 Z{float(z_up):.4f} F{float(z_feed):.1f}",
                        f"G0 X{float(next_x):.4f} Y{float(next_y):.4f} F{float(feed_travel):.1f}",
                        f"G1 Z{float(z_down):.4f} F{float(z_feed):.1f}",
                    ]
                )
                cur_x, cur_y, cur_z = float(next_x), float(next_y), float(z_down)
                dropped += 1
                continue
            seen.add(key)

        rewritten.append(raw_line)
        cur_x, cur_y, cur_z = next_x, next_y, next_z

    if dropped > 0:
        gcode_path.write_text("\n".join(rewritten).rstrip() + "\n", encoding="utf-8")
        if logger:
            logger(f"G-code duplicate draw scrub: converted {dropped} retraced segment(s) to pen-up travel.")
    return dropped


def _open_serial_no_reset(port: str, baud: int, *, timeout_s: float = 1.0):
    return grbl_probe_mod.open_serial_no_reset(port, baud, timeout_s=timeout_s)


def _grbl_readline_ascii(ser) -> str:
    return grbl_probe_mod.grbl_readline_ascii(ser)


def _grbl_status_line(ser, *, timeout_s: float = 0.8) -> str:
    return grbl_probe_mod.grbl_status_line(_CLI_BACKEND, ser, timeout_s=timeout_s)


def _parse_grbl_triplet(tag: str, text: str) -> Optional[Tuple[float, float, float]]:
    return grbl_probe_mod.parse_grbl_triplet(tag, text)


def _grbl_query_offsets(ser) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    return grbl_probe_mod.grbl_query_offsets(_CLI_BACKEND, ser)


def grbl_wait_for_idle(port: str, baud: str, logger, *, timeout_s: float = 600.0) -> None:
    grbl_probe_mod.grbl_wait_for_idle(_CLI_BACKEND, port, baud, logger, timeout_s=timeout_s)


def grbl_get_wpos_xyz(port: str, baud: str) -> Tuple[float, float, float]:
    return grbl_probe_mod.grbl_get_wpos_xyz(_CLI_BACKEND, port, baud)


def _gcode_find_nearest_g0_xy_line(gcode_file: Path, *, x: float, y: float) -> int:
    return grbl_sender_mod.find_nearest_g0_xy_line(gcode_file, x=x, y=y)


def _write_resume_file(src_gcode: Path, dst_gcode: Path, *, start_line: int) -> None:
    grbl_sender_mod.write_resume_file(
        src_gcode,
        dst_gcode,
        start_line=start_line,
        z_up=Z_UP,
        safe_lift_feed=SAFE_LIFT_FEED,
        z_delay_up=Z_DELAY_UP,
    )


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
    return grbl_sender_mod.send_to_grbl(
        gcode_file,
        com,
        baud,
        logger,
        sleep_after=sleep_after,
        auto_resume=auto_resume,
        max_resume_attempts=max_resume_attempts,
        root_dir=ROOT_DIR,
        ensure_local_tmp_root=ensure_local_tmp_root,
        grbl_wait_for_idle=grbl_wait_for_idle,
        grbl_get_wpos_xyz=grbl_get_wpos_xyz,
        z_up=Z_UP,
        safe_lift_feed=SAFE_LIFT_FEED,
        z_delay_up=Z_DELAY_UP,
    )

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
                return False, f"Text->path conversion failed ({type(exc).__name__}): {exc}"

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
                            log(_format_internal_exception("Warning: failed to write trim preview", exc))
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
            polylines = transform_polylines_for_active_sheet_pass(polylines, logger=log)
            fit_segments = sum(max(0, len(p) - 1) for p in polylines)
            polylines = clip_polylines_to_work_area(polylines, logger=log)
            if not polylines:
                return False, "No drawable geometry remains after clipping to work area."
            clipped_segments = sum(max(0, len(p) - 1) for p in polylines)
            polylines = deduplicate_segments(polylines, eps=SEGMENT_DEDUP_EPS_MM, logger=log)
            polylines = deduplicate_collinear_overlaps(polylines, logger=log)
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
            if not HANDWRITING_TEXT_ENABLED:
                polylines = merge_technical_text_strokes(
                    polylines,
                    logger=log,
                    simplify_collinear_eps=POLYLINE_COLLINEAR_EPS,
                )
                # Text joining can reconnect tiny glyph fragments into a path
                # that retraces a short segment.  Remove only exact/collinear
                # overlaps after the join, before pen-lift generation.
                polylines = deduplicate_segments(polylines, eps=max(float(SEGMENT_DEDUP_EPS_MM), 0.05), logger=log)
                polylines = deduplicate_collinear_overlaps(polylines, logger=log)
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
                polylines = deduplicate_segments(polylines, eps=max(float(SEGMENT_DEDUP_EPS_MM), 0.05), logger=log)
                polylines = deduplicate_collinear_overlaps(polylines, logger=log)
            polylines = final_cleanup_polylines_for_gcode(
                polylines,
                exact_eps=max(float(SEGMENT_DEDUP_EPS_MM), 0.05),
                logger=log,
            )
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
            cleanup_xy_gcode_overlaps(xy_path, logger=log)
            log("Applying pen-up / pen-down ...")
            apply_penlift(
                xy_path,
                pen_path,
                z_down=effective_z_down,
                dynamic_z_enable=(TOOL_MODE == "pencil"),
                dynamic_base_z_down=PENCIL_BASE_Z_DOWN if TOOL_MODE == "pencil" else None,
                dynamic_initial_wear_mm=dynamic_wear_start,
                handwriting_mode=HANDWRITING_TEXT_ENABLED,
                # Technical drawing jobs must fully lift between contours to
                # avoid dragging on paper and smearing geometry.
                force_full_lift=(not HANDWRITING_TEXT_ENABLED),
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
        return False, _format_backend_exception(exc)


def _format_backend_exception(exc: Exception) -> str:
    err_name = type(exc).__name__
    if isinstance(exc, BackendError):
        return f"{err_name}: {exc}"
    return f"Error[{err_name}]: {exc}"


def _format_internal_exception(prefix: str, exc: Exception) -> str:
    return runtime_utils_mod.format_internal_exception(prefix, exc)


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
    calibration_fast: bool = False,
) -> Tuple[bool, str]:
    if send_to_plotter and not skip_calibration:
        ok, msg = run_corner_calibration_pipeline(
            log,
            com=com,
            baud=baud,
            send_to_plotter=send_to_plotter,
            mark_size=corner_mark_size,
            fast=bool(calibration_fast),
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
            apply_penlift(xy_path, pen_path, force_full_lift=True)
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
        return False, _format_backend_exception(exc)


def run_corner_calibration_pipeline(
    log,
    com: str = DEFAULT_COM_PORT,
    baud: str = DEFAULT_BAUD,
    send_to_plotter: bool = True,
    output_path: Optional[Path] = None,
    mark_size: float = 2.0,
    fast: bool = False,
) -> Tuple[bool, str]:
    try:
        log(
            "Calibration profile: "
            f"{active_calibration_profile_name()}, "
            f"sheet={ACTIVE_SHEET_CONFIG.get('sheet_format')}, "
            f"anchor={ACTIVE_SHEET_CONFIG.get('anchor')}, "
            f"offset=({float(ACTIVE_SHEET_CONFIG.get('offset_x_mm') or 0.0):.2f},"
            f"{float(ACTIVE_SHEET_CONFIG.get('offset_y_mm') or 0.0):.2f}), "
            f"pass={int(PASS_COL)}/{int(PASS_COLS)} x {int(PASS_ROW)}/{int(PASS_ROWS)}, "
            f"z_travel={'short' if fast else 'full'}"
        )
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
            apply_penlift(xy_path, pen_path, force_full_lift=not bool(fast))
            make_final_with_preamble(pen_path, final_path)
            gcode_lines, gcode_draw, gcode_travel, gcode_bounds = summarize_gcode_file(final_path)
            log(
                f"Calibration G-code stats: lines={gcode_lines}, draw={gcode_draw}, travel={gcode_travel}, "
                f"bounds={gcode_bounds[0]:.3f}..{gcode_bounds[1]:.3f} x, "
                f"{gcode_bounds[2]:.3f}..{gcode_bounds[3]:.3f} y, "
                f"feed_xy=travel {FEED_TRAVEL:.1f}/draw {FEED_DRAW:.1f}, z_down={Z_DOWN:.3f}"
            )

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
        return False, _format_backend_exception(exc)


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
        return False, _format_backend_exception(exc)


def summarize_gcode_file(gcode_path: Path) -> Tuple[int, int, int, Tuple[float, float, float, float]]:
    return gcode_stats_mod.summarize_gcode_file(
        gcode_path,
        points_distance=points_distance,
        arc_extents_xy=arc_extents_xy,
    )


def _strip_gcode_comments(line: str) -> str:
    return gcode_bounds_mod.strip_gcode_comments(line)


def _pen_down_from_z_level(cur_z: float, z_up: float, z_down: float) -> bool:
    return gcode_bounds_mod.pen_down_from_z_level(cur_z, z_up, z_down)


def _gcode_draw_bounds(gcode_path: Path, *, z_up: float, z_down: float) -> Optional[Tuple[float, float, float, float]]:
    return gcode_bounds_mod.gcode_draw_bounds(
        gcode_path,
        z_up=float(z_up),
        z_down=float(z_down),
        points_distance=points_distance,
        arc_extents_xy=arc_extents_xy,
    )


def preflight_check_gcode(
    gcode_path: Path,
    logger=print,
    *,
    bounds: Optional[Tuple[float, float, float, float]] = None,
) -> Tuple[bool, str]:
    return gcode_preflight_mod.preflight_check_gcode(
        gcode_path,
        logger,
        preflight_enabled=bool(PREFLIGHT_ENABLED),
        preflight_max_gcode_lines=int(PREFLIGHT_MAX_GCODE_LINES),
        preflight_max_travel_to_draw_ratio=float(PREFLIGHT_MAX_TRAVEL_TO_DRAW_RATIO),
        preflight_bounds_margin_mm=float(PREFLIGHT_BOUNDS_MARGIN_MM),
        z_up=float(Z_UP),
        z_down=float(Z_DOWN),
        bounds=bounds,
        work_area_bounds=work_area_bounds,
        summarize_gcode_file=summarize_gcode_file,
        gcode_draw_bounds=lambda path, z_up_val, z_down_val: _gcode_draw_bounds(
            path,
            z_up=float(z_up_val),
            z_down=float(z_down_val),
        ),
    )


def warn_if_text_nodes_left(svg_path: Path, logger) -> None:
    if svg_has_text_nodes(svg_path):
        logger("Warning: SVG still contains <text> nodes after conversion. "
               "Install/use Inkscape with text->path support if text is missing.")


def open_with_default_viewer(path: Path, logger=print) -> None:
    process_utils_mod.open_with_default_viewer(
        path,
        logger=logger,
        startfile=getattr(os, "startfile", None),
        format_internal_exception=_format_internal_exception,
    )


def ensure_local_tmp_root() -> Path:
    return runtime_utils_mod.ensure_local_tmp_root(LOCAL_TMP_ROOT)


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
    return manual_commands_mod.grbl_send_manual_commands(
        com,
        baud,
        commands,
        default_baud=DEFAULT_BAUD,
        soft_reset_first=soft_reset_first,
        read_tail=read_tail,
        serial_timeout_s=serial_timeout_s,
        wake_delay_s=wake_delay_s,
        reset_delay_s=reset_delay_s,
        command_delay_s=command_delay_s,
        tail_delay_s=tail_delay_s,
        wake_read_bytes=wake_read_bytes,
        tail_read_bytes=tail_read_bytes,
    )

SUPPORTED_INPUT_EXTENSIONS = cli_entry_mod.SUPPORTED_INPUT_EXTENSIONS


class _CliBackendProxy:
    def __getattr__(self, name: str):
        return globals()[name]

    def __setattr__(self, name: str, value) -> None:
        globals()[name] = value


_CLI_BACKEND = _CliBackendProxy()


def _optional_path_arg(value: Optional[str]) -> Optional[Path]:
    return cli_entry_mod.optional_path_arg(value)


def _should_exit_after_pencil_maintenance(args, *, did_pencil_command: bool) -> bool:
    return cli_entry_mod.should_exit_after_pencil_maintenance(args, did_pencil_command=did_pencil_command)


def _has_cli_action(args) -> bool:
    return cli_entry_mod.has_cli_action(args)


def build_cli_parser() -> argparse.ArgumentParser:
    return cli_entry_mod.build_cli_parser(_CLI_BACKEND)


def _apply_cli_runtime_overrides(args) -> None:
    cli_entry_mod.apply_cli_runtime_overrides(_CLI_BACKEND, args)


def _run_cli_pencil_maintenance(args) -> Tuple[bool, Optional[int]]:
    return cli_entry_mod.run_cli_pencil_maintenance(_CLI_BACKEND, args)


def _configure_cli_sheet_state(args) -> Tuple[Optional[int], Optional[Tuple[float, float]]]:
    return cli_entry_mod.configure_cli_sheet_state(_CLI_BACKEND, args)


def _apply_cli_quality_profile(args) -> Optional[int]:
    return cli_entry_mod.apply_cli_quality_profile(_CLI_BACKEND, args)


def _run_cli_action(args, parser: argparse.ArgumentParser, *, com: str) -> int:
    return cli_entry_mod.run_cli_action(_CLI_BACKEND, args, parser, com=com)


def main(argv: Optional[List[str]] = None):
    return cli_entry_mod.run_cli_main(_CLI_BACKEND, argv)


if __name__ == "__main__":
    raise SystemExit(main())



