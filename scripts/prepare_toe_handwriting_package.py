from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import cv2  # type: ignore
import fitz  # type: ignore
import numpy as np  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import prepare_folder1_packages as prep
import run_pdf_handwriting_acceptance as acceptance
from plotter_studio.core.protocol import _gcode_to_polylines, _write_svg_preview
from src.plotter_backend.geometry.clipping import clip_polylines_to_rect
from src.plotter_backend import toe_font_policy

TOE_RENDER_VARIANTS = [
    ("always", "always"),
    ("contours_off", "off"),
]
SOFT_OVERRIDE_MAX_DUPLICATE_RATIO = 0.005
SOFT_OVERRIDE_MAX_TINY_RATIO = 0.040
SOFT_OVERRIDE_MAX_SHORT_RATIO = 0.180
SOFT_OVERRIDE_MIN_SCORE_GAIN = 0.001
IMAGE_HEAVY_COUNT_THRESHOLD = 4
IMAGE_HEAVY_MASK_IOU_MIN = 0.18
IMAGE_HEAVY_MASK_IOU_GATE = 0.10
BLANK_PAGE_INK_RATIO_MAX = 0.0005
GRAPH_LIKE_IMAGE_COUNT_MIN = 4
GRAPH_LIKE_IMAGE_COUNT_MAX = 18
GRAPH_LIKE_PATH_COUNT_MIN = 40
FORMULA_HEAVY_IMAGE_COUNT_THRESHOLD = 30
FORMULA_HEAVY_SELECTED_IOU_MAX = 0.20
FORMULA_HEAVY_MAX_SIMILARITY_LOSS = 0.002
FORMULA_HEAVY_SEGMENTS_RATIO_MIN = 2.0
FORMULA_HEAVY_DRAW_LENGTH_RATIO_MIN = 2.0
LOW_SIMILARITY_FALLBACK_THRESHOLD = 0.946
LOW_SIMILARITY_FALLBACK_SIM_GAIN_MIN = 0.004
LOW_SIMILARITY_FALLBACK_IOU_DROP_MAX = 0.03
TEXT_RICH_FONT_FIRST_TEXT_COUNT_MIN = 48
TEXT_RICH_FONT_FIRST_IMAGE_COUNT_MAX = 1
TEXT_RICH_FONT_FIRST_FALLBACK_THRESHOLD = 0.920
LINEART_RESCUE_SIMILARITY_THRESHOLD = 0.948
LINEART_RESCUE_SIM_GAIN_MIN = 0.0001
LINEART_RESCUE_IOU_DROP_MAX = 0.01
LINEART_RESCUE_BACKEND_OVERRIDES = {
    "IMAGE_CONTOUR_LINEART_MIN_PATH_MM": 0.28,
    "IMAGE_CONTOUR_LINEART_SIMPLIFY_MM": 0.050,
    "IMAGE_CONTOUR_LINEART_MIN_COMPONENT_PX": 2,
    "IMAGE_CONTOUR_LINEART_RDP_PX": 0.35,
    "HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CURVE_STEP_PX": 0.60,
}
GRAPH_RESCUE_SIMILARITY_THRESHOLD = 0.972
GRAPH_RESCUE_SIM_GAIN_MIN = 0.0002
GRAPH_RESCUE_IOU_DROP_MAX = 0.015
GRAPH_RESCUE_BACKEND_OVERRIDES = {
    "IMAGE_CONTOUR_LINEART_MIN_PATH_MM": 0.20,
    "IMAGE_CONTOUR_LINEART_SIMPLIFY_MM": 0.040,
    "IMAGE_CONTOUR_LINEART_MIN_COMPONENT_PX": 1,
    "IMAGE_CONTOUR_LINEART_RDP_PX": 0.25,
    "HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CURVE_STEP_PX": 0.50,
}
REGION_RESCUE_SIMILARITY_THRESHOLD = 0.968
REGION_RESCUE_SIM_GAIN_MIN = 0.0001
REGION_RESCUE_IOU_DROP_MAX = 0.012
REGION_RESCUE_GRID_COLS = 3
REGION_RESCUE_GRID_ROWS = 4
REGION_RESCUE_TILE_ERROR_MIN = 0.010
REGION_RESCUE_TILE_GAIN_MIN = 0.012
REGION_RESCUE_MAX_REGIONS = 3
REGION_RESCUE_MARGIN_MM = 1.6
REGION_RESCUE_MAX_ALTERNATIVES = 2


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip().lower())
    return text.strip("_") or "font"


def _candidate_fonts() -> list[tuple[str, Path]]:
    return toe_font_policy.resolve_toe_handwriting_profiles(PROJECT_ROOT)


def _filter_candidate_fonts(
    fonts: list[tuple[str, Path]],
    selected_labels: list[str],
) -> list[tuple[str, Path]]:
    return toe_font_policy.filter_toe_handwriting_profiles(
        fonts,
        selected_labels,
        default_labels=toe_font_policy.DEFAULT_TOE_FONT_LABELS,
    )


def _source_page_visual_profile(page_svg: Path) -> dict[str, Any]:
    profile = {
        "image_count": 0,
        "text_count": 0,
        "path_count": 0,
        "image_heavy": False,
    }
    try:
        root = ET.parse(page_svg).getroot()
    except Exception:
        return profile
    counts: dict[str, int] = {}
    for el in root.iter():
        tag = str(el.tag).split("}")[-1]
        counts[tag] = counts.get(tag, 0) + 1
    image_count = int(counts.get("image", 0))
    text_count = int(counts.get("text", 0))
    path_count = int(counts.get("path", 0))
    profile.update(
        {
            "image_count": image_count,
            "text_count": text_count,
            "path_count": path_count,
            "image_heavy": image_count >= int(IMAGE_HEAVY_COUNT_THRESHOLD),
        }
    )
    return profile


def _source_profile_prefers_font_first(source_profile: dict[str, Any]) -> bool:
    return (
        int(source_profile.get("text_count", 0) or 0) >= int(TEXT_RICH_FONT_FIRST_TEXT_COUNT_MIN)
        and int(source_profile.get("image_count", 0) or 0) <= int(TEXT_RICH_FONT_FIRST_IMAGE_COUNT_MAX)
    )


def _source_profile_graph_like(source_profile: dict[str, Any]) -> bool:
    image_count = int(source_profile.get("image_count", 0) or 0)
    path_count = int(source_profile.get("path_count", 0) or 0)
    return (
        int(GRAPH_LIKE_IMAGE_COUNT_MIN) <= image_count <= int(GRAPH_LIKE_IMAGE_COUNT_MAX)
        and path_count >= int(GRAPH_LIKE_PATH_COUNT_MIN)
        and image_count < int(FORMULA_HEAVY_IMAGE_COUNT_THRESHOLD)
    )


def _source_profile_strategy(source_profile: dict[str, Any]) -> str:
    if bool(source_profile.get("blank_like")):
        return "blank_safe"
    image_count = int(source_profile.get("image_count", 0) or 0)
    if image_count >= int(FORMULA_HEAVY_IMAGE_COUNT_THRESHOLD):
        return "formula_heavy"
    if _source_profile_graph_like(source_profile):
        return "graph_lineart"
    if bool(source_profile.get("image_heavy")):
        return "image_heavy"
    if _source_profile_prefers_font_first(source_profile):
        return "font_first_text_rich"
    if image_count > 0:
        return "mixed_vector_image"
    return "font_first_default"


def _fallback_threshold_for_source_profile(source_profile: dict[str, Any]) -> float:
    if _source_profile_prefers_font_first(source_profile):
        return float(TEXT_RICH_FONT_FIRST_FALLBACK_THRESHOLD)
    return float(LOW_SIMILARITY_FALLBACK_THRESHOLD)


def _selection_reason_parts(
    *,
    source_profile: dict[str, Any],
    selected: dict[str, Any],
    primary_font: str,
    changed_from_base: bool,
    blank_selected: bool = False,
    image_fallback_selected: bool = False,
    low_similarity_fallback_selected: bool = False,
    lineart_rescue_selected: bool = False,
    graph_rescue_selected: bool = False,
    region_rescue_selected: bool = False,
    dominating_promoted: bool = False,
) -> list[str]:
    parts = [f"source_strategy={_source_profile_strategy(source_profile)}"]
    parts.append(f"primary_font={primary_font}")
    parts.append(f"selected_font={selected.get('font_label')}")
    parts.append(f"selected_variant={selected.get('variant_label')}")
    parts.append(f"selected_contours={selected.get('image_contours_mode')}")
    parts.append(f"font_first_preferred={str(_source_profile_prefers_font_first(source_profile)).lower()}")
    parts.append(f"fallback_threshold={_fallback_threshold_for_source_profile(source_profile):.3f}")
    if changed_from_base:
        parts.append("selection=override")
    else:
        parts.append("selection=base")
    if blank_selected:
        parts.append("reason=blank_safe")
    if image_fallback_selected:
        parts.append("reason=image_heavy_fallback")
    if low_similarity_fallback_selected:
        parts.append("reason=low_similarity_fallback")
    if lineart_rescue_selected:
        parts.append("reason=lineart_rescue")
    if graph_rescue_selected:
        parts.append("reason=graph_rescue")
    if region_rescue_selected:
        parts.append("reason=region_rescue")
    if dominating_promoted:
        parts.append("reason=dominating_candidate")
    return parts


def _pdf_page_ink_ratio(source_pdf: Path, page_index: int) -> float:
    try:
        gray = prep._render_pdf_page_gray(source_pdf, page_index=page_index - 1, dpi=140)
    except Exception:
        return 0.0
    if gray is None or getattr(gray, "size", 0) <= 0:
        return 0.0
    mask = gray < 245
    return float(np.count_nonzero(mask)) / float(mask.size)


def _compute_quality_metrics(nc_path: Path) -> dict[str, Any]:
    return acceptance._analyze_gcode(
        nc_path,
        z_up=float(prep.backend.Z_UP),
        z_down=float(prep.backend.Z_DOWN),
    )


def _load_existing_candidate(
    *,
    source_pdf: Path,
    page_index: int,
    font_label: str,
    font_path: Path,
    prefix: Path,
) -> dict[str, Any] | None:
    svg_path, pdf_path, nc_path, gcode_path = prep._bridge_preview_copy_targets(prefix)
    if not all(path.exists() and path.is_file() for path in (svg_path, pdf_path, nc_path, gcode_path)):
        return None
    similarity = prep._layout_similarity_pdf(source_pdf, pdf_path, source_page_index=page_index - 1)
    return {
        "item": f"page_{page_index:02d}",
        "ok": True,
        "message": "reused existing candidate",
        "logs": ["reused existing candidate artifacts"],
        "font_label": font_label,
        "font_path": str(font_path),
        "layout_similarity": similarity,
        "metrics": prep._analyze_gcode(nc_path),
        "svg": str(svg_path),
        "pdf": str(pdf_path),
        "nc": str(nc_path),
        "gcode": str(gcode_path),
        "notes": "reused_existing",
    }


def _build_overlay_metrics(
    *,
    source_pdf: Path,
    source_page_index: int,
    preview_pdf: Path,
    out_png: Path,
) -> dict[str, float]:
    src = prep._crop_content(prep._render_pdf_page_gray(source_pdf, page_index=source_page_index))
    cur = prep._crop_content(prep._render_pdf_page_gray(preview_pdf, page_index=0))
    size = (900, 900)
    src = cv2.resize(src, size, interpolation=cv2.INTER_AREA)
    cur = cv2.resize(cur, size, interpolation=cv2.INTER_AREA)
    src = cv2.GaussianBlur(src, (0, 0), 1.0)
    cur = cv2.GaussianBlur(cur, (0, 0), 1.0)

    src_mask = src < 228
    cur_mask = cur < 228
    inter = int(np.count_nonzero(src_mask & cur_mask))
    union = int(np.count_nonzero(src_mask | cur_mask))
    src_count = int(np.count_nonzero(src_mask))
    cur_count = int(np.count_nonzero(cur_mask))
    iou = float(inter / union) if union > 0 else 1.0
    recall = float(inter / src_count) if src_count > 0 else 1.0
    precision = float(inter / cur_count) if cur_count > 0 else 1.0

    overlay = np.full((size[1], size[0], 3), 255, dtype=np.uint8)
    overlay[src_mask & cur_mask] = (35, 35, 35)
    overlay[src_mask & ~cur_mask] = (40, 40, 220)
    overlay[cur_mask & ~src_mask] = (220, 40, 40)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_png), overlay)
    return {
        "mask_iou": round(iou, 6),
        "mask_recall": round(recall, 6),
        "mask_precision": round(precision, 6),
    }


def _layout_similarity_full_page_pdf(source_pdf: Path, preview_pdf: Path, source_page_index: int = 0) -> float:
    src = prep._render_pdf_page_gray(source_pdf, page_index=source_page_index)
    cur = prep._render_pdf_page_gray(preview_pdf, page_index=0)
    size = (512, 512)
    src = cv2.resize(src, size, interpolation=cv2.INTER_AREA)
    cur = cv2.resize(cur, size, interpolation=cv2.INTER_AREA)
    src = cv2.GaussianBlur(src, (0, 0), 1.2)
    cur = cv2.GaussianBlur(cur, (0, 0), 1.2)
    score = 1.0 - float(np.mean(np.abs(src.astype(np.float32) - cur.astype(np.float32))) / 255.0)
    return round(score, 6)


def _blank_preview_canvas_mm() -> tuple[float, float]:
    try:
        area_min_x, area_max_x, area_min_y, area_max_y = prep.backend.work_area_bounds()
        width_mm = max(1.0, float(area_max_x) - float(area_min_x)) + 4.0
        height_mm = max(1.0, float(area_max_y) - float(area_min_y)) + 4.0
        return width_mm, height_mm
    except Exception:
        return 184.0, 284.0


def _write_blank_preview_artifacts(prefix: Path) -> tuple[Path, Path, Path, Path]:
    svg_path, pdf_path, nc_path, gcode_path = prep._bridge_preview_copy_targets(prefix)
    width_mm, height_mm = _blank_preview_canvas_mm()
    svg_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{width_mm:.3f}mm" height="{height_mm:.3f}mm" '
        f'viewBox="0 0 {width_mm:.3f} {height_mm:.3f}">\n'
        '</svg>\n'
    )
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg_text, encoding="utf-8")
    mm_to_pt = 72.0 / 25.4
    doc = fitz.open()
    try:
        doc.new_page(width=width_mm * mm_to_pt, height=height_mm * mm_to_pt)
        doc.save(pdf_path)
    finally:
        doc.close()
    blank_gcode = "G21\nG90\nG0 Z0.0000\nM2\n"
    nc_path.write_text(blank_gcode, encoding="utf-8")
    gcode_path.write_text(blank_gcode, encoding="utf-8")
    return svg_path, pdf_path, nc_path, gcode_path


def _build_blank_like_candidate(
    *,
    source_pdf: Path,
    page_index: int,
    package_dir: Path,
    font_label: str,
    source_profile: dict[str, Any],
) -> dict[str, Any]:
    prefix = package_dir / "_candidates" / f"page_{page_index:02d}" / "blank_safe" / f"page_{page_index:02d}"
    prefix.parent.mkdir(parents=True, exist_ok=True)
    svg_path, pdf_path, nc_path, gcode_path = _write_blank_preview_artifacts(prefix)
    overlay_png = prefix.parent / f"{prefix.name}_overlay.png"
    row = {
        "item": f"page_{page_index:02d}",
        "ok": True,
        "message": "blank-like source page exported as blank preview",
        "logs": [
            "blank_like_source=True",
            f"ink_ratio={float(source_profile.get('ink_ratio', 0.0) or 0.0):.8f}",
            "selected_variant=blank_safe",
        ],
        "font_label": font_label,
        "font_path": "",
        "layout_similarity": _layout_similarity_full_page_pdf(source_pdf, pdf_path, source_page_index=page_index - 1),
        "metrics": {
            "draw_length_mm": 0.0,
            "segments_total": 0,
            "segments_duplicate": 0,
            "bounds": {"x_min": 0.0, "x_max": 0.0, "y_min": 0.0, "y_max": 0.0},
        },
        "svg": str(svg_path),
        "pdf": str(pdf_path),
        "nc": str(nc_path),
        "gcode": str(gcode_path),
        "notes": "variant=blank_safe; blank_page_output",
        "quality_metrics": {
            "polylines": 0,
            "segments_total": 0,
            "segments_duplicate": 0,
            "segments_duplicate_ratio": 0.0,
            "segments_tiny_lt_0_12mm": 0,
            "segments_tiny_ratio": 0.0,
            "segments_short_lt_0_25mm": 0,
            "segments_short_ratio": 0.0,
            "draw_length_mm": 0.0,
            "bounds": {"x_min": 0.0, "x_max": 0.0, "y_min": 0.0, "y_max": 0.0},
        },
        "overlay_metrics": _build_overlay_metrics(
            source_pdf=source_pdf,
            source_page_index=page_index - 1,
            preview_pdf=pdf_path,
            out_png=overlay_png,
        ),
        "overlay_png": str(overlay_png),
        "quality_gate": {
            "max_duplicate_ratio": 0.0,
            "max_tiny_ratio": 0.0,
            "mask_iou_min": 0.0,
            "duplicate_ratio_ok": True,
            "tiny_ratio_ok": True,
            "mask_iou_ok": True,
            "accepted": True,
        },
        "score": 10.0,
        "variant_label": "blank_safe",
        "image_contours_mode": "off",
        "page_index": int(page_index),
        "source_image_count": int(source_profile.get("image_count", 0) or 0),
        "source_text_count": int(source_profile.get("text_count", 0) or 0),
        "source_path_count": int(source_profile.get("path_count", 0) or 0),
    }
    return row


def _candidate_score(row: dict[str, Any]) -> float:
    sim = float(row.get("layout_similarity", 0.0) or 0.0)
    g = dict(row.get("quality_metrics", {}))
    overlay = dict(row.get("overlay_metrics", {}))
    dup = float(g.get("segments_duplicate_ratio", 0.0) or 0.0)
    tiny = float(g.get("segments_tiny_ratio", 0.0) or 0.0)
    short = float(g.get("segments_short_ratio", 0.0) or 0.0)
    iou = float(overlay.get("mask_iou", 0.0) or 0.0)
    recall = float(overlay.get("mask_recall", 0.0) or 0.0)
    precision = float(overlay.get("mask_precision", 0.0) or 0.0)
    image_count = int(row.get("source_image_count", 0) or 0)
    image_heavy = image_count >= int(IMAGE_HEAVY_COUNT_THRESHOLD)
    iou_weight = 0.18 if image_heavy else 0.08
    recall_weight = 0.55 if image_heavy else 0.0
    precision_weight = 0.04 if image_heavy else 0.0
    low_iou_floor = float(IMAGE_HEAVY_MASK_IOU_MIN) if image_heavy else 0.0
    low_iou_penalty = max(0.0, low_iou_floor - iou) * (0.55 if image_heavy else 0.0)
    return round(
        sim
        + (iou * iou_weight)
        + (recall * recall_weight)
        + (precision * precision_weight)
        - (dup * 0.30)
        - (tiny * 0.12)
        - (short * 0.03)
        - low_iou_penalty,
        6,
    )


def _font_doc_score(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return -1e9
    scores = [_candidate_score(row) for row in rows if bool(row.get("ok"))]
    if not scores:
        return -1e9
    min_similarity = min(float(row.get("layout_similarity", 0.0) or 0.0) for row in rows if bool(row.get("ok")))
    return float(statistics.fmean(scores)) + (min_similarity * 0.02)


def _quality_gate(row: dict[str, Any], *, max_duplicate_ratio: float, max_tiny_ratio: float) -> dict[str, Any]:
    g = dict(row.get("quality_metrics", {}))
    overlay = dict(row.get("overlay_metrics", {}))
    dup = float(g.get("segments_duplicate_ratio", 0.0) or 0.0)
    tiny = float(g.get("segments_tiny_ratio", 0.0) or 0.0)
    image_count = int(row.get("source_image_count", 0) or 0)
    image_heavy = image_count >= int(IMAGE_HEAVY_COUNT_THRESHOLD)
    iou = float(overlay.get("mask_iou", 0.0) or 0.0)
    mask_iou_min = float(IMAGE_HEAVY_MASK_IOU_GATE) if image_heavy else 0.0
    mask_iou_ok = True if not image_heavy else iou >= mask_iou_min
    return {
        "max_duplicate_ratio": float(max_duplicate_ratio),
        "max_tiny_ratio": float(max_tiny_ratio),
        "mask_iou_min": float(mask_iou_min),
        "duplicate_ratio_ok": dup <= float(max_duplicate_ratio),
        "tiny_ratio_ok": tiny <= float(max_tiny_ratio),
        "mask_iou_ok": bool(mask_iou_ok),
        "accepted": dup <= float(max_duplicate_ratio) and tiny <= float(max_tiny_ratio) and bool(mask_iou_ok),
    }


def _candidate_soft_ok(row: dict[str, Any]) -> bool:
    q = dict(row.get("quality_metrics", {}))
    dup = float(q.get("segments_duplicate_ratio", 0.0) or 0.0)
    tiny = float(q.get("segments_tiny_ratio", 0.0) or 0.0)
    short = float(q.get("segments_short_ratio", 0.0) or 0.0)
    return (
        dup <= float(SOFT_OVERRIDE_MAX_DUPLICATE_RATIO)
        and tiny <= float(SOFT_OVERRIDE_MAX_TINY_RATIO)
        and short <= float(SOFT_OVERRIDE_MAX_SHORT_RATIO)
    )


def _select_page_result(
    *,
    primary_label: str,
    page_results: list[dict[str, Any]],
    override_similarity_gain: float,
) -> dict[str, Any]:
    successful = [row for row in page_results if bool(row.get("ok"))]
    if not successful:
        return max(page_results, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))

    primary_candidates = [row for row in successful if str(row.get("font_label", "")) == str(primary_label)]
    base = next(
        (
            row for row in primary_candidates
            if str(row.get("variant_label", "always")) == "always"
        ),
        None,
    )
    if base is None and primary_candidates:
        base = max(
            primary_candidates,
            key=lambda row: (_candidate_score(row), float(row.get("layout_similarity", 0.0) or 0.0)),
        )
    if base is None:
        return max(successful, key=lambda row: (_candidate_score(row), float(row.get("layout_similarity", 0.0) or 0.0)))

    accepted = [row for row in successful if bool(dict(row.get("quality_gate", {})).get("accepted", False))]
    if accepted:
        best_accepted = max(accepted, key=lambda row: (_candidate_score(row), float(row.get("layout_similarity", 0.0) or 0.0)))
        base_accepted = bool(dict(base.get("quality_gate", {})).get("accepted", False))
        if not base_accepted:
            base_sim = float(base.get("layout_similarity", 0.0) or 0.0)
            cand_sim = float(best_accepted.get("layout_similarity", 0.0) or 0.0)
            base_iou = float(dict(base.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
            cand_iou = float(dict(best_accepted.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
            if base_sim < 0.93 or (cand_sim >= (base_sim - 0.002) and cand_iou >= (base_iou - 0.01)):
                base = best_accepted

    soft_candidates = [row for row in successful if _candidate_soft_ok(row)]
    if not soft_candidates:
        return base

    best_soft = max(soft_candidates, key=lambda row: (_candidate_score(row), float(row.get("layout_similarity", 0.0) or 0.0)))
    best_score = float(best_soft.get("score", -1e9) or -1e9)
    base_score = float(base.get("score", -1e9) or -1e9)
    sim_gain = float(best_soft.get("layout_similarity", 0.0) or 0.0) - float(base.get("layout_similarity", 0.0) or 0.0)
    best_iou = float(dict(best_soft.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    base_iou = float(dict(base.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    iou_gain = best_iou - base_iou
    base_image_count = int(base.get("source_image_count", 0) or 0)
    image_heavy = base_image_count >= int(IMAGE_HEAVY_COUNT_THRESHOLD)
    if image_heavy and str(best_soft.get("variant_label", "")) == "raster_safe":
        if sim_gain >= 0.001 and iou_gain >= -0.002:
            return best_soft
        if iou_gain >= 0.02 and sim_gain >= -0.002:
            return best_soft
    if best_score >= (base_score + float(SOFT_OVERRIDE_MIN_SCORE_GAIN)):
        if str(best_soft.get("font_label", "")) != str(base.get("font_label", "")):
            if sim_gain >= float(override_similarity_gain) and iou_gain >= -0.005:
                return best_soft
            if iou_gain >= 0.03 and sim_gain >= -0.001:
                return best_soft
        else:
            if sim_gain >= -0.002 and iou_gain >= 0.01:
                return best_soft
    return base


def _should_prefer_image_heavy_fallback(
    *,
    selected: dict[str, Any],
    fallback: dict[str, Any],
    source_profile: dict[str, Any],
) -> bool:
    if not bool(fallback.get("ok")):
        return False
    selected_iou = float(dict(selected.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    fallback_iou = float(dict(fallback.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    selected_recall = float(dict(selected.get("overlay_metrics", {})).get("mask_recall", 0.0) or 0.0)
    fallback_recall = float(dict(fallback.get("overlay_metrics", {})).get("mask_recall", 0.0) or 0.0)
    selected_score = float(selected.get("score", -1e9) or -1e9)
    fallback_score = float(fallback.get("score", -1e9) or -1e9)
    selected_sim = float(selected.get("layout_similarity", 0.0) or 0.0)
    fallback_sim = float(fallback.get("layout_similarity", 0.0) or 0.0)
    if (
        fallback_score >= (selected_score + 0.003)
        or fallback_iou >= (selected_iou + 0.05)
        or (fallback_recall >= (selected_recall + 0.02) and fallback_iou >= (selected_iou - 0.01))
    ):
        return True
    if fallback_sim >= (selected_sim + 0.003) and fallback_iou >= (selected_iou + 0.02):
        return True
    if fallback_sim >= (selected_sim + 0.002) and fallback_recall >= (selected_recall + 0.015) and fallback_iou >= (selected_iou - 0.005):
        return True

    image_count = int(source_profile.get("image_count", 0) or 0)
    graph_like_page = int(IMAGE_HEAVY_COUNT_THRESHOLD) <= image_count < int(FORMULA_HEAVY_IMAGE_COUNT_THRESHOLD)
    if graph_like_page:
        if fallback_sim >= (selected_sim + 0.004) and fallback_iou >= (selected_iou - 0.02):
            return True
        if fallback_sim >= (selected_sim + 0.010) and fallback_iou >= (selected_iou - 0.055):
            return True
    selected_variant = str(selected.get("variant_label", "always") or "always")
    selected_segments = int(dict(selected.get("quality_metrics", {})).get("segments_total", 0) or 0)
    fallback_segments = int(dict(fallback.get("quality_metrics", {})).get("segments_total", 0) or 0)
    selected_draw = float(dict(selected.get("quality_metrics", {})).get("draw_length_mm", 0.0) or 0.0)
    fallback_draw = float(dict(fallback.get("quality_metrics", {})).get("draw_length_mm", 0.0) or 0.0)
    formula_like_overtrace = (
        image_count >= int(FORMULA_HEAVY_IMAGE_COUNT_THRESHOLD)
        and selected_variant == "always"
        and selected_iou <= float(FORMULA_HEAVY_SELECTED_IOU_MAX)
        and fallback_sim >= (selected_sim - float(FORMULA_HEAVY_MAX_SIMILARITY_LOSS))
        and (
            (fallback_segments > 0 and selected_segments >= math.ceil(fallback_segments * float(FORMULA_HEAVY_SEGMENTS_RATIO_MIN)))
            or (fallback_draw > 0.0 and selected_draw >= (fallback_draw * float(FORMULA_HEAVY_DRAW_LENGTH_RATIO_MIN)))
        )
    )
    if formula_like_overtrace:
        return True
    return False


def _should_prefer_low_similarity_fallback(
    *,
    selected: dict[str, Any],
    fallback: dict[str, Any],
) -> bool:
    if not bool(fallback.get("ok")):
        return False
    selected_sim = float(selected.get("layout_similarity", 0.0) or 0.0)
    fallback_sim = float(fallback.get("layout_similarity", 0.0) or 0.0)
    if fallback_sim < (selected_sim + float(LOW_SIMILARITY_FALLBACK_SIM_GAIN_MIN)):
        return False
    selected_iou = float(dict(selected.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    fallback_iou = float(dict(fallback.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    return fallback_iou >= (selected_iou - float(LOW_SIMILARITY_FALLBACK_IOU_DROP_MAX))


def _should_prefer_lineart_rescue(
    *,
    selected: dict[str, Any],
    rescue: dict[str, Any],
) -> bool:
    if not bool(rescue.get("ok")):
        return False
    selected_sim = float(selected.get("layout_similarity", 0.0) or 0.0)
    rescue_sim = float(rescue.get("layout_similarity", 0.0) or 0.0)
    if rescue_sim < (selected_sim + float(LINEART_RESCUE_SIM_GAIN_MIN)):
        return False
    selected_iou = float(dict(selected.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    rescue_iou = float(dict(rescue.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    return rescue_iou >= (selected_iou - float(LINEART_RESCUE_IOU_DROP_MAX))


def _should_prefer_graph_rescue(
    *,
    selected: dict[str, Any],
    rescue: dict[str, Any],
) -> bool:
    if not bool(rescue.get("ok")):
        return False
    selected_sim = float(selected.get("layout_similarity", 0.0) or 0.0)
    rescue_sim = float(rescue.get("layout_similarity", 0.0) or 0.0)
    if rescue_sim < (selected_sim + float(GRAPH_RESCUE_SIM_GAIN_MIN)):
        return False
    selected_iou = float(dict(selected.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    rescue_iou = float(dict(rescue.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    return rescue_iou >= (selected_iou - float(GRAPH_RESCUE_IOU_DROP_MAX))


def _preview_svg_canvas_bounds(svg_path: Path) -> tuple[float, float, float, float]:
    root = ET.parse(svg_path).getroot()
    view_box = str(root.get("viewBox", "") or "").strip()
    parts = [part for part in re.split(r"[\s,]+", view_box) if part]
    if len(parts) != 4:
        raise ValueError(f"SVG viewBox missing or invalid: {svg_path}")
    x0, y0, width, height = [float(part) for part in parts]
    if width <= 0.0 or height <= 0.0:
        raise ValueError(f"SVG viewBox has non-positive size: {svg_path}")
    return x0, x0 + width, y0, y0 + height


def _candidate_polylines_from_nc(nc_path: Path) -> list[list[tuple[float, float]]]:
    lines = nc_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return _gcode_to_polylines(
        lines,
        z_up=float(prep.backend.Z_UP),
        z_down=float(prep.backend.Z_DOWN),
    )


def _polylines_bounds(polylines: list[list[tuple[float, float]]]) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for poly in polylines:
        if len(poly) < 2:
            continue
        xs.extend(float(pt[0]) for pt in poly)
        ys.extend(float(pt[1]) for pt in poly)
    if not xs or not ys:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def _overlay_error_mask(overlay_png: Path) -> np.ndarray | None:
    image = cv2.imread(str(overlay_png), cv2.IMREAD_COLOR)
    if image is None or image.size <= 0:
        return None
    spread = image.max(axis=2).astype(np.int16) - image.min(axis=2).astype(np.int16)
    return spread >= 60


def _merge_adjacent_tile_boxes(
    marked_tiles: list[tuple[int, int]],
    *,
    rows: int,
    cols: int,
) -> list[tuple[int, int, int, int]]:
    pending = set(marked_tiles)
    boxes: list[tuple[int, int, int, int]] = []
    while pending:
        start = pending.pop()
        stack = [start]
        comp_rows = [start[0]]
        comp_cols = [start[1]]
        while stack:
            r, c = stack.pop()
            for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                    continue
                key = (nr, nc)
                if key not in pending:
                    continue
                pending.remove(key)
                stack.append(key)
                comp_rows.append(nr)
                comp_cols.append(nc)
        boxes.append((min(comp_rows), max(comp_rows) + 1, min(comp_cols), max(comp_cols) + 1))
    return boxes


def _region_boxes_from_candidate_overlays(
    *,
    selected_overlay_png: Path,
    rescue_overlay_png: Path,
) -> list[tuple[float, float, float, float]]:
    selected_mask = _overlay_error_mask(selected_overlay_png)
    rescue_mask = _overlay_error_mask(rescue_overlay_png)
    if selected_mask is None or rescue_mask is None:
        return []
    if selected_mask.shape != rescue_mask.shape:
        rescue_mask = cv2.resize(
            rescue_mask.astype(np.uint8),
            (selected_mask.shape[1], selected_mask.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        ).astype(bool)
    height, width = selected_mask.shape[:2]
    marked_tiles: list[tuple[int, int]] = []
    rows = max(1, int(REGION_RESCUE_GRID_ROWS))
    cols = max(1, int(REGION_RESCUE_GRID_COLS))
    for row_idx in range(rows):
        y0 = int(round((row_idx * height) / float(rows)))
        y1 = int(round(((row_idx + 1) * height) / float(rows)))
        for col_idx in range(cols):
            x0 = int(round((col_idx * width) / float(cols)))
            x1 = int(round(((col_idx + 1) * width) / float(cols)))
            if y1 <= y0 or x1 <= x0:
                continue
            selected_err = float(np.mean(selected_mask[y0:y1, x0:x1]))
            rescue_err = float(np.mean(rescue_mask[y0:y1, x0:x1]))
            if selected_err < float(REGION_RESCUE_TILE_ERROR_MIN):
                continue
            if rescue_err <= (selected_err - float(REGION_RESCUE_TILE_GAIN_MIN)):
                marked_tiles.append((row_idx, col_idx))
    if not marked_tiles:
        return []
    boxes: list[tuple[float, float, float, float]] = []
    for row0, row1, col0, col1 in _merge_adjacent_tile_boxes(marked_tiles, rows=rows, cols=cols):
        boxes.append(
            (
                col0 / float(cols),
                col1 / float(cols),
                row0 / float(rows),
                row1 / float(rows),
            )
        )
    boxes.sort(key=lambda box: (box[1] - box[0]) * (box[3] - box[2]), reverse=True)
    return boxes[: int(REGION_RESCUE_MAX_REGIONS)]


def _normalized_boxes_to_poly_regions(
    boxes: list[tuple[float, float, float, float]],
    *,
    content_bounds: tuple[float, float, float, float],
) -> list[tuple[float, float, float, float]]:
    min_x, max_x, min_y, max_y = content_bounds
    width = max(1e-6, max_x - min_x)
    height = max(1e-6, max_y - min_y)
    margin = float(REGION_RESCUE_MARGIN_MM)
    regions: list[tuple[float, float, float, float]] = []
    for fx0, fx1, fy0, fy1 in boxes:
        x0 = min_x + (float(fx0) * width) - margin
        x1 = min_x + (float(fx1) * width) + margin
        y_top = max_y - (float(fy0) * height)
        y_bottom = max_y - (float(fy1) * height)
        y0 = y_bottom - margin
        y1 = y_top + margin
        regions.append(
            (
                max(min_x, x0),
                min(max_x, x1),
                max(min_y, y0),
                min(max_y, y1),
            )
        )
    return [region for region in regions if region[1] > region[0] and region[3] > region[2]]


def _subtract_polylines_in_regions(
    polylines: list[list[tuple[float, float]]],
    *,
    regions: list[tuple[float, float, float, float]],
    content_bounds: tuple[float, float, float, float],
) -> list[list[tuple[float, float]]]:
    current = [list(poly) for poly in polylines if len(poly) >= 2]
    full_min_x, full_max_x, full_min_y, full_max_y = content_bounds
    for region_min_x, region_max_x, region_min_y, region_max_y in regions:
        next_polys: list[list[tuple[float, float]]] = []
        outside_rects = [
            (full_min_x, region_min_x, full_min_y, full_max_y),
            (region_max_x, full_max_x, full_min_y, full_max_y),
            (region_min_x, region_max_x, full_min_y, region_min_y),
            (region_min_x, region_max_x, region_max_y, full_max_y),
        ]
        for poly in current:
            bounds = _polylines_bounds([poly])
            if bounds is None:
                continue
            bx0, bx1, by0, by1 = bounds
            intersects = not (
                bx1 <= region_min_x
                or bx0 >= region_max_x
                or by1 <= region_min_y
                or by0 >= region_max_y
            )
            if not intersects:
                next_polys.append(poly)
                continue
            for clip_min_x, clip_max_x, clip_min_y, clip_max_y in outside_rects:
                if clip_max_x <= clip_min_x or clip_max_y <= clip_min_y:
                    continue
                next_polys.extend(
                    clip_polylines_to_rect(
                        [poly],
                        clip_min_x,
                        clip_max_x,
                        clip_min_y,
                        clip_max_y,
                        continuity_eps_mm=0.02,
                    )
                )
        current = [poly for poly in next_polys if len(poly) >= 2]
    return current


def _clip_polylines_to_regions(
    polylines: list[list[tuple[float, float]]],
    *,
    regions: list[tuple[float, float, float, float]],
) -> list[list[tuple[float, float]]]:
    clipped: list[list[tuple[float, float]]] = []
    for region_min_x, region_max_x, region_min_y, region_max_y in regions:
        clipped.extend(
            clip_polylines_to_rect(
                polylines,
                region_min_x,
                region_max_x,
                region_min_y,
                region_max_y,
                continuity_eps_mm=0.02,
            )
        )
    return [poly for poly in clipped if len(poly) >= 2]


def _build_region_rescue_candidate(
    *,
    source_pdf: Path,
    page_index: int,
    package_dir: Path,
    source_profile: dict[str, Any],
    base_selected: dict[str, Any],
    rescue_source: dict[str, Any],
    font_label: str,
    font_path: Path,
    max_duplicate_ratio: float,
    max_tiny_ratio: float,
    resume: bool,
) -> dict[str, Any]:
    rescue_slug = _slugify(str(rescue_source.get("variant_label", "alt") or "alt"))
    font_slug = _slugify(font_label)
    prefix = (
        package_dir
        / "_candidates"
        / f"page_{page_index:02d}"
        / f"{font_slug}__region_safe_from_{rescue_slug}"
        / f"page_{page_index:02d}"
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)
    row = None
    if resume:
        row = _load_existing_candidate(
            source_pdf=source_pdf,
            page_index=page_index,
            font_label=font_label,
            font_path=font_path,
            prefix=prefix,
        )
    boxes = _region_boxes_from_candidate_overlays(
        selected_overlay_png=Path(str(base_selected.get("overlay_png", ""))),
        rescue_overlay_png=Path(str(rescue_source.get("overlay_png", ""))),
    )
    if not boxes:
        return {
            "item": f"page_{page_index:02d}",
            "ok": False,
            "message": "No weak local regions detected for region rescue.",
            "logs": ["region_rescue=no_boxes"],
            "font_label": font_label,
            "font_path": str(font_path),
            "variant_label": "region_safe",
        }
    if row is None:
        base_polylines = _candidate_polylines_from_nc(Path(str(base_selected["nc"])))
        rescue_polylines = _candidate_polylines_from_nc(Path(str(rescue_source["nc"])))
        content_bounds = _polylines_bounds([*base_polylines, *rescue_polylines])
        if content_bounds is None:
            return {
                "item": f"page_{page_index:02d}",
                "ok": False,
                "message": "Region rescue has no drawable geometry.",
                "logs": ["region_rescue=no_geometry"],
                "font_label": font_label,
                "font_path": str(font_path),
                "variant_label": "region_safe",
            }
        regions = _normalized_boxes_to_poly_regions(boxes, content_bounds=content_bounds)
        if not regions:
            return {
                "item": f"page_{page_index:02d}",
                "ok": False,
                "message": "Region rescue could not map weak areas into page geometry.",
                "logs": ["region_rescue=no_mapped_regions"],
                "font_label": font_label,
                "font_path": str(font_path),
                "variant_label": "region_safe",
            }
        kept_base = _subtract_polylines_in_regions(
            base_polylines,
            regions=regions,
            content_bounds=content_bounds,
        )
        rescue_local = _clip_polylines_to_regions(
            rescue_polylines,
            regions=regions,
        )
        merged_polylines = [*kept_base, *rescue_local]
        if not merged_polylines:
            return {
                "item": f"page_{page_index:02d}",
                "ok": False,
                "message": "Region rescue produced no merged geometry.",
                "logs": ["region_rescue=empty_merge"],
                "font_label": font_label,
                "font_path": str(font_path),
                "variant_label": "region_safe",
            }
        input_svg = prefix.parent / f"{prefix.name}_region_input.svg"
        canvas_bounds = _preview_svg_canvas_bounds(Path(str(base_selected["svg"])))
        _write_svg_preview(merged_polylines, input_svg, canvas_bounds_mm=canvas_bounds)
        prep._configure_toe_backend(font_path)
        logs: list[str] = [
            f"region_rescue_from={rescue_source.get('variant_label')}",
            f"region_boxes_norm={json.dumps([[round(v, 4) for v in box] for box in boxes], ensure_ascii=True)}",
        ]
        nc_path = prefix.with_suffix(".nc")
        ok, msg = prep.backend.run_pipeline(input_svg, logs.append, send_to_plotter=False, output_path=nc_path)
        if not ok:
            return {
                "item": f"page_{page_index:02d}",
                "ok": False,
                "message": msg,
                "logs": logs,
                "font_label": font_label,
                "font_path": str(font_path),
                "variant_label": "region_safe",
            }
        bridge = prep.BackendBridge(PROJECT_ROOT)
        svg_path = prefix.with_suffix(".svg")
        pdf_path = prefix.with_suffix(".pdf")
        preview_ok, preview_err = bridge._build_vector_preview_from_gcode(
            nc_path,
            svg_path,
            pdf_path,
            backend=prep.backend,
            log=logs.append,
        )
        if not preview_ok:
            return {
                "item": f"page_{page_index:02d}",
                "ok": False,
                "message": preview_err,
                "logs": logs,
                "font_label": font_label,
                "font_path": str(font_path),
                "variant_label": "region_safe",
            }
        gcode_path = prefix.with_suffix(".gcode")
        prep._copy_file(nc_path, gcode_path)
        row = {
            "item": f"page_{page_index:02d}",
            "ok": True,
            "message": msg,
            "logs": logs,
            "font_label": font_label,
            "font_path": str(font_path),
            "layout_similarity": prep._layout_similarity_pdf(source_pdf, pdf_path, source_page_index=page_index - 1),
            "metrics": prep._analyze_gcode(nc_path),
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
            "notes": (
                f"variant=region_safe; region_rescue_from={rescue_source.get('variant_label')}; "
                f"region_count={len(regions)}"
            ),
        }
    row["font_slug"] = font_slug
    row["variant_label"] = "region_safe"
    row["image_contours_mode"] = str(base_selected.get("image_contours_mode", "always") or "always")
    row["page_index"] = int(page_index)
    row["source_image_count"] = int(source_profile.get("image_count", 0) or 0)
    row["source_text_count"] = int(source_profile.get("text_count", 0) or 0)
    row["source_path_count"] = int(source_profile.get("path_count", 0) or 0)
    if bool(row.get("ok")):
        quality_metrics = _compute_quality_metrics(Path(str(row["nc"])))
        row["quality_metrics"] = quality_metrics
        overlay_png = prefix.parent / f"{prefix.name}_overlay.png"
        row["overlay_metrics"] = _build_overlay_metrics(
            source_pdf=source_pdf,
            source_page_index=page_index - 1,
            preview_pdf=Path(str(row["pdf"])),
            out_png=overlay_png,
        )
        row["overlay_png"] = str(overlay_png)
        row["quality_gate"] = _quality_gate(
            row,
            max_duplicate_ratio=float(max_duplicate_ratio),
            max_tiny_ratio=float(max_tiny_ratio),
        )
        row["score"] = _candidate_score(row)
    else:
        row["quality_metrics"] = {}
        row["quality_gate"] = {"accepted": False}
        row["overlay_metrics"] = {}
        row["overlay_png"] = ""
        row["score"] = -1e9
    return row


def _should_prefer_region_rescue(
    *,
    selected: dict[str, Any],
    rescue: dict[str, Any],
) -> bool:
    if not bool(rescue.get("ok")):
        return False
    selected_sim = float(selected.get("layout_similarity", 0.0) or 0.0)
    rescue_sim = float(rescue.get("layout_similarity", 0.0) or 0.0)
    if rescue_sim < (selected_sim + float(REGION_RESCUE_SIM_GAIN_MIN)):
        return False
    selected_iou = float(dict(selected.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    rescue_iou = float(dict(rescue.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    return rescue_iou >= (selected_iou - float(REGION_RESCUE_IOU_DROP_MAX))


def _prefer_dominating_candidate(
    *,
    selected: dict[str, Any],
    page_results: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_sim = float(selected.get("layout_similarity", 0.0) or 0.0)
    selected_iou = float(dict(selected.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    best = selected
    best_tuple = (selected_sim, selected_iou)
    for candidate in page_results:
        if candidate is selected or not bool(candidate.get("ok")):
            continue
        cand_sim = float(candidate.get("layout_similarity", 0.0) or 0.0)
        cand_iou = float(dict(candidate.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
        sim_gain = cand_sim - selected_sim
        iou_gain = cand_iou - selected_iou
        dominates = (sim_gain > 1e-6 and iou_gain >= -1e-6) or (abs(sim_gain) <= 1e-6 and iou_gain > 1e-6)
        if not dominates:
            continue
        cand_tuple = (cand_sim, cand_iou)
        if cand_tuple > best_tuple:
            best = candidate
            best_tuple = cand_tuple
    return best


def _copy_selected_artifacts(selected: dict[str, Any], prefix: Path) -> None:
    for src_key, dst_path in zip(["svg", "pdf", "nc", "gcode"], prep._bridge_preview_copy_targets(prefix)):
        prep._copy_file(Path(str(selected[src_key])), dst_path)
    overlay_src = Path(str(selected.get("overlay_png", "")))
    if overlay_src.exists():
        prep._copy_file(overlay_src, prefix.parent / f"{prefix.name}_overlay.png")


def _build_image_heavy_fallback_candidate(
    *,
    source_pdf: Path,
    page_index: int,
    page_svg: Path,
    package_dir: Path,
    font_label: str,
    font_path: Path,
    source_profile: dict[str, Any],
    max_duplicate_ratio: float,
    max_tiny_ratio: float,
    resume: bool,
) -> dict[str, Any]:
    font_slug = _slugify(font_label)
    prefix = package_dir / "_candidates" / f"page_{page_index:02d}" / f"{font_slug}__raster_safe" / f"page_{page_index:02d}"
    prefix.parent.mkdir(parents=True, exist_ok=True)
    row = None
    if resume:
        row = _load_existing_candidate(
            source_pdf=source_pdf,
            page_index=page_index,
            font_label=font_label,
            font_path=font_path,
            prefix=prefix,
        )
    if row is None:
        row = prep._prepare_toe_raster_fallback(
            source_pdf=source_pdf,
            page_index=page_index,
            page_svg=page_svg,
            prefix=prefix,
            font_label=font_label,
            font_path=font_path,
        )
    row["font_slug"] = font_slug
    row["variant_label"] = "raster_safe"
    row["image_contours_mode"] = "always"
    row["page_index"] = int(page_index)
    row["source_image_count"] = int(source_profile.get("image_count", 0) or 0)
    row["source_text_count"] = int(source_profile.get("text_count", 0) or 0)
    row["source_path_count"] = int(source_profile.get("path_count", 0) or 0)
    if bool(row.get("ok")):
        quality_metrics = _compute_quality_metrics(Path(str(row["nc"])))
        row["quality_metrics"] = quality_metrics
        overlay_png = prefix.parent / f"{prefix.name}_overlay.png"
        row["overlay_metrics"] = _build_overlay_metrics(
            source_pdf=source_pdf,
            source_page_index=page_index - 1,
            preview_pdf=Path(str(row["pdf"])),
            out_png=overlay_png,
        )
        row["overlay_png"] = str(overlay_png)
        row["quality_gate"] = _quality_gate(
            row,
            max_duplicate_ratio=float(max_duplicate_ratio),
            max_tiny_ratio=float(max_tiny_ratio),
        )
        row["score"] = _candidate_score(row)
        row["notes"] = "; ".join(
            part for part in [str(row.get("notes", "")), "variant=raster_safe"] if part
        )
    else:
        row["quality_metrics"] = {}
        row["quality_gate"] = {"accepted": False}
        row["overlay_metrics"] = {}
        row["overlay_png"] = ""
        row["score"] = -1e9
    return row


def _build_lineart_rescue_candidate(
    *,
    source_pdf: Path,
    page_index: int,
    page_svg: Path,
    package_dir: Path,
    font_label: str,
    font_path: Path,
    source_profile: dict[str, Any],
    max_duplicate_ratio: float,
    max_tiny_ratio: float,
    resume: bool,
) -> dict[str, Any]:
    font_slug = _slugify(font_label)
    prefix = package_dir / "_candidates" / f"page_{page_index:02d}" / f"{font_slug}__lineart_safe" / f"page_{page_index:02d}"
    prefix.parent.mkdir(parents=True, exist_ok=True)
    row = None
    if resume:
        row = _load_existing_candidate(
            source_pdf=source_pdf,
            page_index=page_index,
            font_label=font_label,
            font_path=font_path,
            prefix=prefix,
        )
    if row is None:
        row = prep._prepare_toe_page(
            source_pdf=source_pdf,
            page_index=page_index,
            page_svg=page_svg,
            font_label=font_label,
            font_path=font_path,
            prefix=prefix,
            backend_overrides=dict(LINEART_RESCUE_BACKEND_OVERRIDES),
        )
    row["font_slug"] = font_slug
    row["variant_label"] = "lineart_safe"
    row["image_contours_mode"] = "always"
    row["page_index"] = int(page_index)
    row["source_image_count"] = int(source_profile.get("image_count", 0) or 0)
    row["source_text_count"] = int(source_profile.get("text_count", 0) or 0)
    row["source_path_count"] = int(source_profile.get("path_count", 0) or 0)
    if bool(row.get("ok")):
        quality_metrics = _compute_quality_metrics(Path(str(row["nc"])))
        row["quality_metrics"] = quality_metrics
        overlay_png = prefix.parent / f"{prefix.name}_overlay.png"
        row["overlay_metrics"] = _build_overlay_metrics(
            source_pdf=source_pdf,
            source_page_index=page_index - 1,
            preview_pdf=Path(str(row["pdf"])),
            out_png=overlay_png,
        )
        row["overlay_png"] = str(overlay_png)
        row["quality_gate"] = _quality_gate(
            row,
            max_duplicate_ratio=float(max_duplicate_ratio),
            max_tiny_ratio=float(max_tiny_ratio),
        )
        row["score"] = _candidate_score(row)
        row["notes"] = "; ".join(
            part for part in [str(row.get("notes", "")), "variant=lineart_safe", "lineart_rescue=tuned"] if part
        )
    else:
        row["quality_metrics"] = {}
        row["quality_gate"] = {"accepted": False}
        row["overlay_metrics"] = {}
        row["overlay_png"] = ""
        row["score"] = -1e9
    return row


def _build_graph_rescue_candidate(
    *,
    source_pdf: Path,
    page_index: int,
    page_svg: Path,
    package_dir: Path,
    font_label: str,
    font_path: Path,
    source_profile: dict[str, Any],
    max_duplicate_ratio: float,
    max_tiny_ratio: float,
    resume: bool,
) -> dict[str, Any]:
    font_slug = _slugify(font_label)
    prefix = package_dir / "_candidates" / f"page_{page_index:02d}" / f"{font_slug}__graph_safe" / f"page_{page_index:02d}"
    prefix.parent.mkdir(parents=True, exist_ok=True)
    row = None
    if resume:
        row = _load_existing_candidate(
            source_pdf=source_pdf,
            page_index=page_index,
            font_label=font_label,
            font_path=font_path,
            prefix=prefix,
        )
    if row is None:
        row = prep._prepare_toe_page(
            source_pdf=source_pdf,
            page_index=page_index,
            page_svg=page_svg,
            font_label=font_label,
            font_path=font_path,
            prefix=prefix,
            backend_overrides=dict(GRAPH_RESCUE_BACKEND_OVERRIDES),
        )
    row["font_slug"] = font_slug
    row["variant_label"] = "graph_safe"
    row["image_contours_mode"] = "always"
    row["page_index"] = int(page_index)
    row["source_image_count"] = int(source_profile.get("image_count", 0) or 0)
    row["source_text_count"] = int(source_profile.get("text_count", 0) or 0)
    row["source_path_count"] = int(source_profile.get("path_count", 0) or 0)
    if bool(row.get("ok")):
        quality_metrics = _compute_quality_metrics(Path(str(row["nc"])))
        row["quality_metrics"] = quality_metrics
        overlay_png = prefix.parent / f"{prefix.name}_overlay.png"
        row["overlay_metrics"] = _build_overlay_metrics(
            source_pdf=source_pdf,
            source_page_index=page_index - 1,
            preview_pdf=Path(str(row["pdf"])),
            out_png=overlay_png,
        )
        row["overlay_png"] = str(overlay_png)
        row["quality_gate"] = _quality_gate(
            row,
            max_duplicate_ratio=float(max_duplicate_ratio),
            max_tiny_ratio=float(max_tiny_ratio),
        )
        row["score"] = _candidate_score(row)
        row["notes"] = "; ".join(
            part for part in [str(row.get("notes", "")), "variant=graph_safe", "graph_rescue=tuned"] if part
        )
    else:
        row["quality_metrics"] = {}
        row["quality_gate"] = {"accepted": False}
        row["overlay_metrics"] = {}
        row["overlay_png"] = ""
        row["score"] = -1e9
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a root TOE PDF handwriting package with self-check and font search.")
    parser.add_argument("--pdf", default="TOE_Zadachi_1_2_Variant_4.pdf", help="Source TOE PDF in project root.")
    parser.add_argument("--out-dir", default="", help="Optional output package directory. Defaults to <pdf>_pack.")
    parser.add_argument("--max-duplicate-ratio", type=float, default=0.002)
    parser.add_argument("--max-tiny-ratio", type=float, default=0.015)
    parser.add_argument("--override-similarity-gain", type=float, default=0.012)
    parser.add_argument(
        "--font-label",
        action="append",
        default=[],
        help="Restrict candidate fonts to specific labels. Can be passed multiple times.",
    )
    parser.add_argument("--resume", action="store_true", help="Reuse existing package/candidate artifacts and continue from them.")
    args = parser.parse_args()

    source_pdf = (PROJECT_ROOT / str(args.pdf)).resolve()
    if not source_pdf.exists():
        raise FileNotFoundError(f"PDF not found: {source_pdf}")
    package_dir = (PROJECT_ROOT / str(args.out_dir)).resolve() if str(args.out_dir).strip() else source_pdf.with_name(f"{source_pdf.stem}_pack")

    if args.resume:
        package_dir.mkdir(parents=True, exist_ok=True)
    else:
        prep._ensure_clean_dir(package_dir)
    pages_dir = package_dir / "pages"
    logs_dir = package_dir / "logs"
    candidates_dir = package_dir / "_candidates"
    page_svg_dir = package_dir / "_page_svg"
    pages_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    page_svg_dir.mkdir(parents=True, exist_ok=True)

    fonts = _filter_candidate_fonts(_candidate_fonts(), list(args.font_label))
    doc = fitz.open(source_pdf)
    page_count = int(doc.page_count)
    all_page_results: dict[int, list[dict[str, Any]]] = {}
    page_source_profiles: dict[int, dict[str, Any]] = {}
    font_success: dict[str, list[dict[str, Any]]] = {label: [] for label, _path in fonts}
    font_path_by_label = {label: path for label, path in fonts}
    started_at = time.time()

    for page_index in range(1, page_count + 1):
        print(f"[page {page_index:02d}/{page_count:02d}] export/source", flush=True)
        page_svg = page_svg_dir / f"page_{page_index:02d}.svg"
        if not (args.resume and page_svg.exists() and page_svg.is_file()):
            prep._export_pdf_page_to_mupdf_svg(source_pdf, page_index - 1, page_svg)
        page_source_profiles[page_index] = _source_page_visual_profile(page_svg)
        ink_ratio = _pdf_page_ink_ratio(source_pdf, page_index)
        page_source_profiles[page_index]["ink_ratio"] = round(float(ink_ratio), 8)
        page_source_profiles[page_index]["blank_like"] = bool(ink_ratio <= float(BLANK_PAGE_INK_RATIO_MAX))
        results: list[dict[str, Any]] = []
        page_variants = [("always", "always")] if bool(page_source_profiles[page_index].get("image_heavy")) else list(TOE_RENDER_VARIANTS)
        for font_label, font_path in fonts:
            print(f"  - {font_label}", flush=True)
            font_slug = _slugify(font_label)
            for variant_label, contours_mode in page_variants:
                variant_slug = font_slug if variant_label == "always" else f"{font_slug}__{variant_label}"
                prefix = candidates_dir / f"page_{page_index:02d}" / variant_slug / f"page_{page_index:02d}"
                prefix.parent.mkdir(parents=True, exist_ok=True)
                row = None
                if args.resume:
                    row = _load_existing_candidate(
                        source_pdf=source_pdf,
                        page_index=page_index,
                        font_label=font_label,
                        font_path=font_path,
                        prefix=prefix,
                    )
                if row is None:
                    if variant_label == "always":
                        row = prep._prepare_toe_page(
                            source_pdf=source_pdf,
                            page_index=page_index,
                            page_svg=page_svg,
                            font_label=font_label,
                            font_path=font_path,
                            prefix=prefix,
                        )
                    else:
                        prep._configure_toe_backend(font_path)
                        prep.backend.IMAGE_CONTOUR_MODE = contours_mode
                        prep.backend.IMAGE_CONTOUR_ENABLED = contours_mode != "off"
                        prep.backend.IMAGE_CONTOUR_WORD_ONLY = contours_mode == "word_only"
                        logs: list[str] = []
                        nc_path = prefix.with_suffix(".nc")
                        ok, msg = prep.backend.run_pipeline(page_svg, logs.append, send_to_plotter=False, output_path=nc_path)
                        row = {
                            "item": f"page_{page_index:02d}",
                            "ok": bool(ok),
                            "message": msg,
                            "logs": logs,
                            "font_label": font_label,
                            "font_path": str(font_path),
                        }
                        if ok:
                            bridge = prep.BackendBridge(PROJECT_ROOT)
                            svg_path = prefix.with_suffix(".svg")
                            pdf_path = prefix.with_suffix(".pdf")
                            preview_ok, preview_err = bridge._build_vector_preview_from_gcode(
                                nc_path,
                                svg_path,
                                pdf_path,
                                backend=prep.backend,
                                log=logs.append,
                            )
                            if not preview_ok:
                                row["ok"] = False
                                row["message"] = preview_err
                            else:
                                gcode_path = prefix.with_suffix(".gcode")
                                prep._copy_file(nc_path, gcode_path)
                                row.update(
                                    {
                                        "layout_similarity": prep._layout_similarity_pdf(source_pdf, pdf_path, source_page_index=page_index - 1),
                                        "metrics": prep._analyze_gcode(nc_path),
                                        "svg": str(svg_path),
                                        "pdf": str(pdf_path),
                                        "nc": str(nc_path),
                                        "gcode": str(gcode_path),
                                        "notes": f"contours={contours_mode}",
                                    }
                                )
                row["font_slug"] = font_slug
                row["variant_label"] = variant_label
                row["image_contours_mode"] = contours_mode
                row["page_index"] = int(page_index)
                row["source_image_count"] = int(page_source_profiles[page_index].get("image_count", 0) or 0)
                row["source_text_count"] = int(page_source_profiles[page_index].get("text_count", 0) or 0)
                row["source_path_count"] = int(page_source_profiles[page_index].get("path_count", 0) or 0)
                if bool(row.get("ok")):
                    quality_metrics = _compute_quality_metrics(Path(str(row["nc"])))
                    row["quality_metrics"] = quality_metrics
                    overlay_png = prefix.parent / f"{prefix.name}_overlay.png"
                    row["overlay_metrics"] = _build_overlay_metrics(
                        source_pdf=source_pdf,
                        source_page_index=page_index - 1,
                        preview_pdf=Path(str(row["pdf"])),
                        out_png=overlay_png,
                    )
                    row["overlay_png"] = str(overlay_png)
                    row["quality_gate"] = _quality_gate(
                        row,
                        max_duplicate_ratio=float(args.max_duplicate_ratio),
                        max_tiny_ratio=float(args.max_tiny_ratio),
                    )
                    row["score"] = _candidate_score(row)
                    font_success[font_label].append(row)
                else:
                    row["quality_metrics"] = {}
                    row["quality_gate"] = {"accepted": False}
                    row["overlay_metrics"] = {}
                    row["overlay_png"] = ""
                    row["score"] = -1e9
                results.append(row)
        all_page_results[page_index] = results

    font_report_rows: list[dict[str, Any]] = []
    for font_label, _path in fonts:
        raw_rows = font_success.get(font_label, [])
        best_by_page: dict[int, dict[str, Any]] = {}
        for row in raw_rows:
            page_index = int(row.get("page_index", 0) or 0)
            if page_index <= 0:
                continue
            prev = best_by_page.get(page_index)
            if prev is None or _candidate_score(row) > _candidate_score(prev):
                best_by_page[page_index] = row
        rows = list(best_by_page.values())
        sims = [float(row.get("layout_similarity", 0.0) or 0.0) for row in rows]
        scores = [float(row.get("score", -1e9) or -1e9) for row in rows]
        font_report_rows.append(
            {
                "font_label": font_label,
                "pages_ok": len(rows),
                "avg_layout_similarity": round(float(statistics.fmean(sims)), 6) if sims else 0.0,
                "min_layout_similarity": round(min(sims), 6) if sims else 0.0,
                "avg_score": round(float(statistics.fmean(scores)), 6) if scores else -1e9,
                "doc_score": round(_font_doc_score(rows), 6) if rows else -1e9,
            }
        )

    primary_font = max(font_report_rows, key=lambda row: (float(row.get("doc_score", -1e9)), float(row.get("avg_layout_similarity", 0.0))))["font_label"]

    rows: list[prep.ArtifactRow] = []
    report: dict[str, Any] = {
        "source_pdf": str(source_pdf),
        "package_dir": str(package_dir),
        "kind": "toe_handwriting",
        "page_count": page_count,
        "fonts_evaluated": font_report_rows,
        "selected_primary_font": primary_font,
        "generated_at_epoch": started_at,
        "items": [],
    }

    for page_index in range(1, page_count + 1):
        page_results = all_page_results[page_index]
        selected = _select_page_result(
            primary_label=str(primary_font),
            page_results=page_results,
            override_similarity_gain=float(args.override_similarity_gain),
        )
        base_selected = selected
        source_profile = dict(page_source_profiles.get(page_index, {}))
        blank_selected = False
        image_fallback_selected = False
        low_similarity_fallback_selected = False
        lineart_rescue_selected = False
        graph_rescue_selected = False
        region_rescue_selected = False
        dominating_promoted = False
        if bool(source_profile.get("blank_like")):
            blank_candidate = _build_blank_like_candidate(
                source_pdf=source_pdf,
                page_index=page_index,
                package_dir=package_dir,
                font_label=str(selected.get("font_label") or primary_font),
                source_profile=source_profile,
            )
            page_results.append(blank_candidate)
            selected = blank_candidate
            blank_selected = True
        elif bool(source_profile.get("image_heavy")):
            fallback_font_label = str(selected.get("font_label") or primary_font)
            fallback_font_path = font_path_by_label.get(fallback_font_label) or font_path_by_label[str(primary_font)]
            fallback = _build_image_heavy_fallback_candidate(
                source_pdf=source_pdf,
                page_index=page_index,
                page_svg=page_svg_dir / f"page_{page_index:02d}.svg",
                package_dir=package_dir,
                font_label=fallback_font_label,
                font_path=fallback_font_path,
                source_profile=source_profile,
                max_duplicate_ratio=float(args.max_duplicate_ratio),
                max_tiny_ratio=float(args.max_tiny_ratio),
                resume=bool(args.resume),
            )
            page_results.append(fallback)
            if _should_prefer_image_heavy_fallback(
                selected=selected,
                fallback=fallback,
                source_profile=source_profile,
            ):
                selected = fallback
                image_fallback_selected = True
        elif (
            float(selected.get("layout_similarity", 0.0) or 0.0)
            <= _fallback_threshold_for_source_profile(source_profile)
            and str(selected.get("variant_label", "always") or "always") != "raster_safe"
        ):
            fallback_font_label = str(selected.get("font_label") or primary_font)
            fallback_font_path = font_path_by_label.get(fallback_font_label) or font_path_by_label[str(primary_font)]
            fallback = _build_image_heavy_fallback_candidate(
                source_pdf=source_pdf,
                page_index=page_index,
                page_svg=page_svg_dir / f"page_{page_index:02d}.svg",
                package_dir=package_dir,
                font_label=fallback_font_label,
                font_path=fallback_font_path,
                source_profile=source_profile,
                max_duplicate_ratio=float(args.max_duplicate_ratio),
                max_tiny_ratio=float(args.max_tiny_ratio),
                resume=bool(args.resume),
            )
            page_results.append(fallback)
            if _should_prefer_low_similarity_fallback(
                selected=selected,
                fallback=fallback,
            ):
                selected = fallback
                low_similarity_fallback_selected = True
        if (
            int(source_profile.get("image_count", 0) or 0) > 0
            and float(selected.get("layout_similarity", 0.0) or 0.0) <= float(LINEART_RESCUE_SIMILARITY_THRESHOLD)
        ):
            rescue_font_label = str(selected.get("font_label") or primary_font)
            rescue_font_path = font_path_by_label.get(rescue_font_label) or font_path_by_label[str(primary_font)]
            rescue = _build_lineart_rescue_candidate(
                source_pdf=source_pdf,
                page_index=page_index,
                page_svg=page_svg_dir / f"page_{page_index:02d}.svg",
                package_dir=package_dir,
                font_label=rescue_font_label,
                font_path=rescue_font_path,
                source_profile=source_profile,
                max_duplicate_ratio=float(args.max_duplicate_ratio),
                max_tiny_ratio=float(args.max_tiny_ratio),
                resume=bool(args.resume),
            )
            page_results.append(rescue)
            if _should_prefer_lineart_rescue(
                selected=selected,
                rescue=rescue,
            ):
                selected = rescue
                lineart_rescue_selected = True
        if (
            _source_profile_graph_like(source_profile)
            and float(selected.get("layout_similarity", 0.0) or 0.0) <= float(GRAPH_RESCUE_SIMILARITY_THRESHOLD)
        ):
            rescue_font_label = str(selected.get("font_label") or primary_font)
            rescue_font_path = font_path_by_label.get(rescue_font_label) or font_path_by_label[str(primary_font)]
            graph_rescue = _build_graph_rescue_candidate(
                source_pdf=source_pdf,
                page_index=page_index,
                page_svg=page_svg_dir / f"page_{page_index:02d}.svg",
                package_dir=package_dir,
                font_label=rescue_font_label,
                font_path=rescue_font_path,
                source_profile=source_profile,
                max_duplicate_ratio=float(args.max_duplicate_ratio),
                max_tiny_ratio=float(args.max_tiny_ratio),
                resume=bool(args.resume),
            )
            page_results.append(graph_rescue)
            if _should_prefer_graph_rescue(
                selected=selected,
                rescue=graph_rescue,
            ):
                selected = graph_rescue
                graph_rescue_selected = True
        if float(selected.get("layout_similarity", 0.0) or 0.0) <= float(REGION_RESCUE_SIMILARITY_THRESHOLD):
            region_source = selected
            region_candidates: list[dict[str, Any]] = []
            region_alternatives = [
                row
                for row in page_results
                if bool(row.get("ok"))
                and row is not region_source
                and str(row.get("variant_label", "")) in {"raster_safe", "lineart_safe", "graph_safe"}
            ]
            region_alternatives.sort(
                key=lambda row: (
                    float(row.get("score", -1e9) or -1e9),
                    float(row.get("layout_similarity", 0.0) or 0.0),
                ),
                reverse=True,
            )
            for region_alt in region_alternatives[: int(REGION_RESCUE_MAX_ALTERNATIVES)]:
                region_candidate = _build_region_rescue_candidate(
                    source_pdf=source_pdf,
                    page_index=page_index,
                    package_dir=package_dir,
                    source_profile=source_profile,
                    base_selected=region_source,
                    rescue_source=region_alt,
                    font_label=str(region_source.get("font_label") or primary_font),
                    font_path=font_path_by_label.get(str(region_source.get("font_label") or primary_font))
                    or font_path_by_label[str(primary_font)],
                    max_duplicate_ratio=float(args.max_duplicate_ratio),
                    max_tiny_ratio=float(args.max_tiny_ratio),
                    resume=bool(args.resume),
                )
                page_results.append(region_candidate)
                if bool(region_candidate.get("ok")):
                    region_candidates.append(region_candidate)
            if region_candidates:
                best_region = max(
                    region_candidates,
                    key=lambda row: (
                        float(row.get("score", -1e9) or -1e9),
                        float(row.get("layout_similarity", 0.0) or 0.0),
                    ),
                )
                if _should_prefer_region_rescue(
                    selected=region_source,
                    rescue=best_region,
                ):
                    selected = best_region
                    region_rescue_selected = True
        pre_dominating_selected = selected
        selected = _prefer_dominating_candidate(
            selected=selected,
            page_results=page_results,
        )
        dominating_promoted = selected is not pre_dominating_selected
        changed_from_base = selected is not base_selected
        selection_reason_parts = _selection_reason_parts(
            source_profile=source_profile,
            selected=selected,
            primary_font=str(primary_font),
            changed_from_base=changed_from_base,
            blank_selected=blank_selected,
            image_fallback_selected=image_fallback_selected,
            low_similarity_fallback_selected=low_similarity_fallback_selected,
            lineart_rescue_selected=lineart_rescue_selected,
            graph_rescue_selected=graph_rescue_selected,
            region_rescue_selected=region_rescue_selected,
            dominating_promoted=dominating_promoted,
        )
        final_prefix = pages_dir / f"page_{page_index:02d}"
        if bool(selected.get("ok")):
            _copy_selected_artifacts(selected, final_prefix)
            page_logs = list(selected.get("logs", []))
            page_logs.append(
                "source_profile="
                f"images={int(source_profile.get('image_count', 0) or 0)};"
                f" texts={int(source_profile.get('text_count', 0) or 0)};"
                f" paths={int(source_profile.get('path_count', 0) or 0)}"
            )
            page_logs.append(f"selected_primary_font={primary_font}")
            page_logs.append(f"selected_font={selected.get('font_label')}")
            page_logs.append(f"selected_variant={selected.get('variant_label')}")
            page_logs.append(f"selected_contours={selected.get('image_contours_mode')}")
            page_logs.append(f"selected_score={float(selected.get('score', 0.0)):.6f}")
            page_logs.append("selection_reason=" + "; ".join(selection_reason_parts))
            gate = dict(selected.get("quality_gate", {}))
            page_logs.append(
                "quality_gate="
                f"accepted={bool(gate.get('accepted', False))};"
                f" dup_ok={bool(gate.get('duplicate_ratio_ok', False))};"
                f" tiny_ok={bool(gate.get('tiny_ratio_ok', False))};"
                f" mask_iou_ok={bool(gate.get('mask_iou_ok', True))}"
            )
            prep._write_text(logs_dir / f"page_{page_index:02d}.log.txt", "\n".join(page_logs) + "\n")
            q = dict(selected.get("quality_metrics", {}))
            rows.append(
                prep.ArtifactRow(
                    source_pdf=str(source_pdf),
                    package_dir=str(package_dir),
                    kind="toe_handwriting",
                    item=f"page_{page_index:02d}",
                    ok=True,
                    layout_similarity=float(selected.get("layout_similarity", 0.0) or 0.0),
                    draw_length_m=round(float(q.get("draw_length_mm", 0.0)) / 1000.0, 3),
                    segments_total=int(q.get("segments_total", 0) or 0),
                    bounds=prep._bounds_text({"bounds": dict(q.get("bounds", {}))}),
                    nc=str(final_prefix.with_suffix(".nc")),
                    gcode=str(final_prefix.with_suffix(".gcode")),
                    preview_pdf=str(final_prefix.with_suffix(".pdf")),
                    preview_svg=str(final_prefix.with_suffix(".svg")),
                    notes="; ".join(
                        part
                        for part in [
                            f"font={selected.get('font_label')}",
                            f"variant={selected.get('variant_label')}",
                            f"contours={selected.get('image_contours_mode')}",
                            "page_override=yes"
                            if (
                                str(selected.get("font_label", "")) != str(primary_font)
                                or str(selected.get("variant_label", "always")) != "always"
                            )
                            else "page_override=no",
                            str(selected.get("notes", "")),
                            f"iou={float(dict(selected.get('overlay_metrics', {})).get('mask_iou', 0.0)):.6f}",
                            *selection_reason_parts,
                        ]
                        if part
                    ),
                )
            )
        else:
            prep._write_text(
                logs_dir / f"page_{page_index:02d}.log.txt",
                "\n".join(str(row.get("message", "")) for row in page_results) + "\n",
            )
            rows.append(
                prep.ArtifactRow(
                    source_pdf=str(source_pdf),
                    package_dir=str(package_dir),
                    kind="toe_handwriting",
                    item=f"page_{page_index:02d}",
                    ok=False,
                    layout_similarity=None,
                    draw_length_m=None,
                    segments_total=None,
                    bounds="",
                    nc="",
                    gcode="",
                    preview_pdf="",
                    preview_svg="",
                    notes="all candidates failed",
                )
            )
        report["items"].append(
            {
                "page_index": page_index,
                "selected_font": selected.get("font_label"),
                "selected_variant": selected.get("variant_label"),
                "selected_contours_mode": selected.get("image_contours_mode"),
                "selected_layout_similarity": selected.get("layout_similarity"),
                "selected_score": selected.get("score"),
                "selected_quality_gate": selected.get("quality_gate"),
                "selected_overlay_metrics": selected.get("overlay_metrics"),
                "selected_reason": "; ".join(selection_reason_parts),
                "source_strategy": _source_profile_strategy(source_profile),
                "font_first_preferred": bool(_source_profile_prefers_font_first(source_profile)),
                "fallback_threshold": _fallback_threshold_for_source_profile(source_profile),
                "source_profile": source_profile,
                "candidates": page_results,
            }
        )

    prep._write_json(package_dir / "report.json", report)
    prep._write_csv(package_dir / "summary.csv", rows)
    prep._mirror_package_root_artifacts(package_dir, rows)
    ok_rows = [row for row in rows if bool(row.ok) and row.layout_similarity is not None]
    prep._write_json(
        package_dir / "final_overview.json",
        {
            "source_pdf": str(source_pdf),
            "selected_primary_font": primary_font,
            "fonts_evaluated": font_report_rows,
            "pages_ok": sum(1 for row in rows if bool(row.ok)),
            "page_count": page_count,
            "elapsed_s": round(time.time() - started_at, 3),
            "avg_layout_similarity": round(float(statistics.fmean([float(row.layout_similarity or 0.0) for row in ok_rows])), 6)
            if ok_rows
            else None,
            "min_layout_similarity": round(min(float(row.layout_similarity or 0.0) for row in ok_rows), 6)
            if ok_rows
            else None,
        },
    )
    print(f"Prepared: {package_dir}")
    print(f"Primary font: {primary_font}")
    print(f"Pages ok: {sum(1 for row in rows if bool(row.ok))}/{page_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
