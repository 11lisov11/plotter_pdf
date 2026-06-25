from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps


Point = tuple[float, float]
Polyline = list[Point]
PhotoMode = Literal["hatch", "scribble", "portrait", "sketch", "classic"]
PhotoQuality = Literal["fast", "normal", "detailed"]
PortraitSampling = Literal["grid", "blue_noise"]


HATCH_PHOTO_QUALITY_PRESETS: dict[PhotoQuality, dict[str, Any]] = {
    "fast": {
        "max_side_px": 650,
        "hatch_spacing_mm": 1.45,
        "hatch_levels": (0.28, 0.48, 0.68),
        "hatch_angles_deg": (-28.0,),
        "edge_min_length_mm": 18.0,
        "min_segment_mm": 1.20,
    },
    "normal": {
        "max_side_px": 850,
        "hatch_spacing_mm": 0.88,
        "hatch_levels": (0.14, 0.28, 0.42, 0.56, 0.70, 0.82),
        "hatch_angles_deg": (-28.0,),
        "edge_min_length_mm": 8.0,
        "min_segment_mm": 0.60,
    },
    "detailed": {
        "max_side_px": 1200,
        "hatch_spacing_mm": 0.58,
        "hatch_levels": (0.10, 0.20, 0.30, 0.42, 0.54, 0.66, 0.78, 0.88),
        "hatch_angles_deg": (-28.0,),
        "edge_min_length_mm": 4.0,
        "min_segment_mm": 0.40,
    },
}


CLASSIC_PHOTO_QUALITY_PRESETS: dict[PhotoQuality, dict[str, Any]] = {
    "fast": {
        "max_side_px": 600,
        "classic_spacing_mm": 3.0,
        "classic_levels": (0.24, 0.44, 0.64, 0.82),
        "classic_angles_deg": (0.0, 45.0, -45.0, 90.0),
        "classic_smooth_sigma_px": 1.25,
        "edge_min_length_mm": 14.0,
    },
    "normal": {
        "max_side_px": 800,
        "classic_spacing_mm": 2.15,
        "classic_levels": (0.18, 0.34, 0.50, 0.66, 0.82),
        "classic_angles_deg": (0.0, 45.0, -45.0, 90.0, 22.5),
        "classic_smooth_sigma_px": 1.15,
        "edge_min_length_mm": 10.0,
    },
    "detailed": {
        "max_side_px": 900,
        "classic_spacing_mm": 1.45,
        "classic_levels": (0.14, 0.26, 0.38, 0.52, 0.66, 0.80),
        "classic_angles_deg": (0.0, 45.0, -45.0, 90.0, 22.5, -22.5),
        "classic_smooth_sigma_px": 1.05,
        "edge_min_length_mm": 6.0,
    },
}


SKETCH_PHOTO_QUALITY_PRESETS: dict[PhotoQuality, dict[str, Any]] = {
    "fast": {
        "max_side_px": 600,
        "sketch_stroke_spacing_mm": 4.20,
        "sketch_stroke_length_mm": 12.0,
        "sketch_threshold": 0.20,
        "sketch_density": 0.14,
        "sketch_density_gamma": 1.25,
        "sketch_min_center_distance_mm": 3.10,
        "sketch_contour_levels": (0.20, 0.38, 0.58),
        "edge_min_length_mm": 20.0,
        "portrait_jitter_mm": 0.45,
        "scribble_step_mm": 1.15,
        "min_segment_mm": 1.20,
    },
    "normal": {
        "max_side_px": 800,
        "sketch_stroke_spacing_mm": 3.15,
        "sketch_stroke_length_mm": 13.5,
        "sketch_threshold": 0.18,
        "sketch_density": 0.22,
        "sketch_density_gamma": 1.15,
        "sketch_min_center_distance_mm": 2.25,
        "sketch_contour_levels": (0.18, 0.32, 0.48, 0.64),
        "edge_min_length_mm": 13.0,
        "portrait_jitter_mm": 0.65,
        "scribble_step_mm": 0.90,
        "min_segment_mm": 0.90,
    },
    "detailed": {
        "max_side_px": 900,
        "sketch_stroke_spacing_mm": 2.45,
        "sketch_stroke_length_mm": 14.5,
        "sketch_threshold": 0.16,
        "sketch_density": 0.32,
        "sketch_density_gamma": 1.05,
        "sketch_min_center_distance_mm": 1.65,
        "sketch_contour_levels": (0.15, 0.28, 0.42, 0.58, 0.72),
        "edge_min_length_mm": 9.0,
        "portrait_jitter_mm": 0.80,
        "scribble_step_mm": 0.72,
        "min_segment_mm": 0.70,
    },
}


def classic_photo_quality_preset(quality: str) -> dict[str, Any]:
    key = quality.strip().lower()
    if key not in CLASSIC_PHOTO_QUALITY_PRESETS:
        allowed = ", ".join(CLASSIC_PHOTO_QUALITY_PRESETS)
        raise ValueError(f"unknown classic photo quality: {quality!r}; expected one of: {allowed}")
    return dict(CLASSIC_PHOTO_QUALITY_PRESETS[key])  # type: ignore[index]


def hatch_photo_quality_preset(quality: str) -> dict[str, Any]:
    key = quality.strip().lower()
    if key not in HATCH_PHOTO_QUALITY_PRESETS:
        allowed = ", ".join(HATCH_PHOTO_QUALITY_PRESETS)
        raise ValueError(f"unknown hatch photo quality: {quality!r}; expected one of: {allowed}")
    return dict(HATCH_PHOTO_QUALITY_PRESETS[key])  # type: ignore[index]


def sketch_photo_quality_preset(quality: str) -> dict[str, Any]:
    key = quality.strip().lower()
    if key not in SKETCH_PHOTO_QUALITY_PRESETS:
        allowed = ", ".join(SKETCH_PHOTO_QUALITY_PRESETS)
        raise ValueError(f"unknown sketch photo quality: {quality!r}; expected one of: {allowed}")
    return dict(SKETCH_PHOTO_QUALITY_PRESETS[key])  # type: ignore[index]


@dataclass(frozen=True)
class WorkArea:
    min_x: float = 0.0
    max_x: float = 180.0
    min_y: float = -280.0
    max_y: float = 0.0


@dataclass(frozen=True)
class PhotoPlotConfig:
    mode: PhotoMode = "sketch"
    margin_mm: float = 5.0
    target_width_mm: float | None = None
    target_height_mm: float | None = None
    max_side_px: int = 900
    contrast: float = 1.12
    gamma: float = 1.05
    blur_px: int = 3
    hatch_spacing_mm: float = 2.2
    hatch_levels: tuple[float, ...] = (0.34, 0.58, 0.78)
    hatch_angles_deg: tuple[float, ...] = (0.0, -30.0, 30.0)
    classic_spacing_mm: float = 2.15
    classic_levels: tuple[float, ...] = (0.18, 0.34, 0.50, 0.66, 0.82)
    classic_angles_deg: tuple[float, ...] = (0.0, 45.0, -45.0, 90.0, 22.5)
    classic_smooth_sigma_px: float = 1.15
    sketch_stroke_spacing_mm: float = 3.15
    sketch_stroke_length_mm: float = 13.5
    sketch_threshold: float = 0.18
    sketch_density: float = 0.22
    sketch_density_gamma: float = 1.15
    sketch_min_center_distance_mm: float = 2.25
    sketch_tone_line_spacing_mm: float = 0.0
    sketch_tone_step_mm: float = 0.5
    sketch_tone_amplitude_mm: float = 1.25
    sketch_tonal_contours: bool = True
    sketch_contour_levels: tuple[float, ...] = (0.18, 0.32, 0.48, 0.64)
    sketch_pencil_edges: bool = True
    sketch_pencil_sigma_s: int = 60
    sketch_pencil_sigma_r: float = 0.07
    sketch_pencil_shade_factor: float = 0.045
    min_segment_mm: float = 0.8
    merge_gap_mm: float = 0.55
    edge_enabled: bool = True
    edge_low_threshold: int = 70
    edge_high_threshold: int = 170
    edge_min_length_mm: float = 20.0
    scribble_line_spacing_mm: float = 1.25
    scribble_step_mm: float = 0.75
    scribble_amplitude_mm: float = 1.6
    scribble_threshold: float = 0.16
    portrait_stroke_spacing_mm: float = 1.9
    portrait_stroke_length_mm: float = 7.0
    portrait_threshold: float = 0.24
    portrait_jitter_mm: float = 0.45
    portrait_seed: int = 12345
    portrait_cleanup_enabled: bool = True
    portrait_cleanup_threshold: float = 0.18
    portrait_min_component_area_mm2: float = 130.0
    portrait_mask_dilate_mm: float = 1.2
    portrait_sampling: PortraitSampling = "blue_noise"
    portrait_density: float = 1.0
    portrait_min_center_distance_mm: float = 1.15
    route_optimize: bool = True
    route_optimize_limit: int = 4500


@dataclass(frozen=True)
class PhotoPlotResult:
    mode: str
    source_size_px: tuple[int, int]
    processed_size_px: tuple[int, int]
    target_size_mm: tuple[float, float]
    placement_bounds: tuple[float, float, float, float]
    polylines: list[Polyline]
    stats: dict[str, Any]


def _polyline_length(polyline: Sequence[Point]) -> float:
    if len(polyline) < 2:
        return 0.0
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(polyline, polyline[1:]))


def _chaikin_smooth_open(polyline: Sequence[Point], *, iterations: int = 1) -> Polyline:
    pts = [(float(x), float(y)) for x, y in polyline]
    if len(pts) < 4:
        return pts
    for _ in range(max(0, int(iterations))):
        smoothed: Polyline = [pts[0]]
        for p0, p1 in zip(pts, pts[1:]):
            q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
            r = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
            smoothed.extend([q, r])
        smoothed.append(pts[-1])
        pts = smoothed
    return pts


def _all_points(polylines: Sequence[Sequence[Point]]) -> Iterable[Point]:
    for polyline in polylines:
        yield from polyline


def polylines_bounds(polylines: Sequence[Sequence[Point]]) -> tuple[float, float, float, float]:
    pts = list(_all_points(polylines))
    if not pts:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), max(xs), min(ys), max(ys))


def _load_darkness(image_path: Path, config: PhotoPlotConfig) -> tuple[np.ndarray, tuple[int, int], tuple[int, int], np.ndarray]:
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)
    source_size = img.size
    img = img.convert("RGB")
    max_side = max(32, int(config.max_side_px))
    if max(img.size) > max_side:
        scale = max_side / float(max(img.size))
        new_size = (max(1, int(round(img.size[0] * scale))), max(1, int(round(img.size[1] * scale))))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    rgb = np.asarray(img, dtype=np.float32) / 255.0
    luma = (0.299 * rgb[:, :, 0]) + (0.587 * rgb[:, :, 1]) + (0.114 * rgb[:, :, 2])
    value = np.max(rgb, axis=2)
    # For plotter sketches, saturated blue/green areas should not become dark
    # just because grayscale luma is low. Bias toward the brightest channel so
    # skies stay open and dark clothes/trees still receive dense strokes.
    tone = np.maximum(luma, value * 0.92)
    p_low, p_high = np.percentile(tone, (1.0, 99.2))
    if p_high > p_low:
        tone = np.clip((tone - p_low) / (p_high - p_low), 0.0, 1.0)
    darkness = 1.0 - tone
    if config.contrast > 0:
        darkness = np.clip((darkness - 0.5) * float(config.contrast) + 0.5, 0.0, 1.0)
    if config.gamma > 0:
        darkness = np.clip(darkness, 0.0, 1.0) ** float(config.gamma)
    blur = int(config.blur_px)
    if blur > 1:
        if blur % 2 == 0:
            blur += 1
        darkness = cv2.GaussianBlur(darkness, (blur, blur), 0)
    processed_gray = np.clip((1.0 - darkness) * 255.0, 0, 255).astype(np.uint8)
    if config.mode == "sketch" and bool(config.sketch_pencil_edges) and hasattr(cv2, "pencilSketch"):
        try:
            rgb_u8 = np.asarray(img, dtype=np.uint8)
            bgr_u8 = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
            pencil_gray, _color = cv2.pencilSketch(
                bgr_u8,
                sigma_s=max(1, int(config.sketch_pencil_sigma_s)),
                sigma_r=max(0.01, float(config.sketch_pencil_sigma_r)),
                shade_factor=max(0.01, float(config.sketch_pencil_shade_factor)),
            )
            processed_gray = pencil_gray.astype(np.uint8)
        except cv2.error:
            pass
    return darkness.astype(np.float32), source_size, img.size, processed_gray


def _fit_image_to_work_area(
    image_size: tuple[int, int],
    work_area: WorkArea,
    config: PhotoPlotConfig,
) -> tuple[float, float, float, float, float]:
    img_w, img_h = image_size
    if img_w <= 0 or img_h <= 0:
        raise ValueError("image has invalid size")
    margin = max(0.0, float(config.margin_mm))
    available_w = max(1.0, float(work_area.max_x) - float(work_area.min_x) - 2.0 * margin)
    available_h = max(1.0, float(work_area.max_y) - float(work_area.min_y) - 2.0 * margin)
    aspect = float(img_w) / float(img_h)

    if config.target_width_mm is not None and config.target_height_mm is not None:
        target_w = min(float(config.target_width_mm), available_w)
        target_h = min(float(config.target_height_mm), available_h)
        scale = min(target_w / float(img_w), target_h / float(img_h))
        target_w = float(img_w) * scale
        target_h = float(img_h) * scale
    elif config.target_width_mm is not None:
        target_w = min(float(config.target_width_mm), available_w)
        target_h = target_w / aspect
        if target_h > available_h:
            target_h = available_h
            target_w = target_h * aspect
        scale = target_w / float(img_w)
    elif config.target_height_mm is not None:
        target_h = min(float(config.target_height_mm), available_h)
        target_w = target_h * aspect
        if target_w > available_w:
            target_w = available_w
            target_h = target_w / aspect
        scale = target_h / float(img_h)
    else:
        scale = min(available_w / float(img_w), available_h / float(img_h))
        target_w = float(img_w) * scale
        target_h = float(img_h) * scale

    x_left = float(work_area.min_x) + margin + (available_w - target_w) * 0.5
    y_top = float(work_area.max_y) - margin - (available_h - target_h) * 0.5
    return x_left, y_top, target_w, target_h, scale


def _image_to_machine(points: Sequence[Point], *, x_left: float, y_top: float, scale_mm_per_px: float) -> Polyline:
    return [(x_left + x * scale_mm_per_px, y_top - y * scale_mm_per_px) for x, y in points]


def _rot(point: Point, angle_rad: float) -> Point:
    x, y = point
    ca = math.cos(angle_rad)
    sa = math.sin(angle_rad)
    return (ca * x - sa * y, sa * x + ca * y)


def _inv_rot(point: Point, angle_rad: float) -> Point:
    x, y = point
    ca = math.cos(angle_rad)
    sa = math.sin(angle_rad)
    return (ca * x + sa * y, -sa * x + ca * y)


def _merge_intervals(intervals: list[tuple[float, float]], max_gap: float) -> list[tuple[float, float]]:
    if not intervals:
        return []
    merged: list[tuple[float, float]] = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start - last_end <= max_gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _scan_hatch_segments(
    mask: np.ndarray,
    *,
    angle_deg: float,
    spacing_px: float,
    offset_px: float = 0.0,
    min_segment_px: float,
    merge_gap_px: float,
) -> list[list[Point]]:
    h, w = mask.shape[:2]
    if h <= 1 or w <= 1:
        return []
    spacing = max(1.0, float(spacing_px))
    angle = math.radians(float(angle_deg))
    cx = (w - 1) * 0.5
    cy = (h - 1) * 0.5
    corners = [(-cx, -cy), (w - 1 - cx, -cy), (w - 1 - cx, h - 1 - cy), (-cx, h - 1 - cy)]
    rcorners = [_rot(p, angle) for p in corners]
    min_rx = math.floor(min(p[0] for p in rcorners)) - 1.0
    max_rx = math.ceil(max(p[0] for p in rcorners)) + 1.0
    min_ry = math.floor(min(p[1] for p in rcorners)) - 1.0
    max_ry = math.ceil(max(p[1] for p in rcorners)) + 1.0
    out: list[list[Point]] = []
    y = min_ry + (float(offset_px) % spacing)
    sample_step = 1.0
    while y <= max_ry:
        intervals: list[tuple[float, float]] = []
        start: float | None = None
        x = min_rx
        while x <= max_rx:
            ix, iy = _inv_rot((x, y), angle)
            px = int(round(ix + cx))
            py = int(round(iy + cy))
            active = 0 <= px < w and 0 <= py < h and bool(mask[py, px])
            if active and start is None:
                start = x
            elif not active and start is not None:
                intervals.append((start, x - sample_step))
                start = None
            x += sample_step
        if start is not None:
            intervals.append((start, max_rx))
        for x0, x1 in _merge_intervals(intervals, max(0.0, float(merge_gap_px))):
            if (x1 - x0) < float(min_segment_px):
                continue
            p0 = _inv_rot((x0, y), angle)
            p1 = _inv_rot((x1, y), angle)
            out.append([(p0[0] + cx, p0[1] + cy), (p1[0] + cx, p1[1] + cy)])
        y += spacing
    return out


def _generate_hatch_px(darkness: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> list[list[Point]]:
    spacing_px = max(1.0, float(config.hatch_spacing_mm) / max(1e-9, scale_mm_per_px))
    min_segment_px = max(1.0, float(config.min_segment_mm) / max(1e-9, scale_mm_per_px))
    merge_gap_px = max(0.0, float(config.merge_gap_mm) / max(1e-9, scale_mm_per_px))
    levels = tuple(sorted(float(v) for v in config.hatch_levels if 0.0 < float(v) < 1.0))
    angles = tuple(float(v) for v in config.hatch_angles_deg) or (0.0,)
    if not levels:
        return []

    tone = cv2.GaussianBlur(darkness.astype(np.float32), (0, 0), sigmaX=1.1)
    out: list[list[Point]] = []
    for idx, level in enumerate(levels):
        mask = _clean_tonal_mask(tone >= level, scale_mm_per_px, level_index=idx)
        if not np.any(mask):
            continue
        remaining = len(levels) - idx - 1
        layer_spacing_px = spacing_px * float(2 ** max(0, remaining))
        layer_offset_px = spacing_px * float(2 ** max(0, remaining - 1) if remaining > 0 else 0)
        out.extend(
            _scan_hatch_segments(
                mask,
                angle_deg=angles[idx % len(angles)],
                spacing_px=layer_spacing_px,
                offset_px=layer_offset_px,
                min_segment_px=min_segment_px,
                merge_gap_px=merge_gap_px,
            )
        )
    return out


def _clean_tonal_mask(mask: np.ndarray, scale_mm_per_px: float, *, level_index: int) -> np.ndarray:
    raw = mask.astype(np.uint8)
    if not np.any(raw):
        return raw.astype(bool)

    close_px = max(1, int(round((0.45 + 0.12 * level_index) / max(1e-9, scale_mm_per_px))))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px * 2 + 1, close_px * 2 + 1))
    raw = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, close_kernel)

    open_px = max(1, int(round(0.18 / max(1e-9, scale_mm_per_px))))
    if open_px > 1:
        open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_px * 2 + 1, open_px * 2 + 1))
        raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, open_kernel)

    labels_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(raw, connectivity=8)
    min_area_mm2 = 20.0 + 12.0 * float(level_index)
    min_area_px = max(5, int(round(min_area_mm2 / max(1e-9, scale_mm_per_px * scale_mm_per_px))))
    keep = np.zeros_like(raw)
    for label in range(1, labels_count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area_px:
            keep[labels == label] = 1
    if not np.any(keep):
        keep = raw
    return keep.astype(bool)


def _generate_classic_px(darkness: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> list[list[Point]]:
    """Generate classic tonal cross-hatching: darker regions receive more line layers."""
    base_spacing_px = max(1.0, float(config.classic_spacing_mm) / max(1e-9, scale_mm_per_px))
    min_segment_px = max(1.0, float(config.min_segment_mm) / max(1e-9, scale_mm_per_px))
    merge_gap_px = max(0.0, float(config.merge_gap_mm) / max(1e-9, scale_mm_per_px))
    levels = tuple(float(v) for v in config.classic_levels if 0.0 < float(v) < 1.0)
    angles = tuple(float(v) for v in config.classic_angles_deg) or (0.0,)
    if not levels:
        return []

    smooth_sigma = max(0.0, float(config.classic_smooth_sigma_px))
    tone = darkness.astype(np.float32)
    if smooth_sigma > 0.0:
        tone = cv2.GaussianBlur(tone, (0, 0), sigmaX=smooth_sigma)

    out: list[list[Point]] = []
    for idx, level in enumerate(levels):
        mask = _clean_tonal_mask(tone >= level, scale_mm_per_px, level_index=idx)
        if not np.any(mask):
            continue
        # Later layers are only reached by darker tones. Keeping their spacing a
        # little tighter makes shadows visibly denser without filling highlights.
        layer_spacing_px = base_spacing_px * max(0.72, 1.0 - 0.045 * idx)
        out.extend(
            _scan_hatch_segments(
                mask,
                angle_deg=angles[idx % len(angles)],
                spacing_px=layer_spacing_px,
                min_segment_px=min_segment_px,
                merge_gap_px=merge_gap_px,
            )
        )
    return out


def _generate_tonal_contours_px(darkness: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> list[list[Point]]:
    if not bool(config.sketch_tonal_contours):
        return []
    levels = tuple(float(v) for v in config.sketch_contour_levels if 0.0 < float(v) < 1.0)
    if not levels:
        return []
    smooth = cv2.GaussianBlur(darkness.astype(np.float32), (0, 0), sigmaX=1.6)
    min_len_base_px = max(4.0, float(config.edge_min_length_mm) * 0.65 / max(1e-9, scale_mm_per_px))
    out: list[list[Point]] = []
    for idx, level in enumerate(levels):
        mask = _clean_tonal_mask(smooth >= level, scale_mm_per_px, level_index=idx)
        raw = mask.astype(np.uint8) * 255
        contours, _hier = cv2.findContours(raw, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        min_len_px = min_len_base_px * (1.0 + 0.10 * idx)
        for contour in contours:
            if len(contour) < 5:
                continue
            x, y, cw, ch = cv2.boundingRect(contour)
            touches_border = x <= 1 or y <= 1 or (x + cw) >= raw.shape[1] - 1 or (y + ch) >= raw.shape[0] - 1
            if touches_border and (cw >= raw.shape[1] * 0.70 or ch >= raw.shape[0] * 0.70):
                continue
            approx = cv2.approxPolyDP(contour, epsilon=0.75 + 0.10 * idx, closed=True)
            pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
            if len(pts) >= 3:
                first = pts[0]
                last = pts[-1]
                if math.hypot(first[0] - last[0], first[1] - last[1]) > 1.5:
                    pts.append(first)
            pts = _chaikin_smooth_open(pts, iterations=1)
            if len(pts) >= 2 and _polyline_length(pts) >= min_len_px:
                out.append(pts)
    return out


def _generate_sketch_px(darkness: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> list[list[Point]]:
    threshold = max(0.0, min(1.0, float(config.sketch_threshold)))
    step_px = max(1.0, float(config.scribble_step_mm) / max(1e-9, scale_mm_per_px))
    jitter_px = max(0.0, float(config.portrait_jitter_mm) / max(1e-9, scale_mm_per_px))
    min_segment_px = max(1.0, float(config.min_segment_mm) / max(1e-9, scale_mm_per_px))
    mask = _clean_tonal_mask(darkness >= threshold, scale_mm_per_px, level_index=1)
    drawing_darkness = np.where(mask, darkness, 0.0).astype(np.float32)
    out: list[list[Point]] = _generate_tonal_contours_px(drawing_darkness, config, scale_mm_per_px)
    if float(config.sketch_tone_line_spacing_mm) > 0.0:
        tone_cfg = replace(
            config,
            scribble_line_spacing_mm=max(0.45, float(config.sketch_tone_line_spacing_mm)),
            scribble_step_mm=max(0.25, float(config.sketch_tone_step_mm)),
            scribble_amplitude_mm=max(0.1, float(config.sketch_tone_amplitude_mm)),
            scribble_threshold=threshold,
        )
        out.extend(_generate_scribble_px(drawing_darkness, tone_cfg, scale_mm_per_px))

    base_spacing_mm = max(0.6, float(config.sketch_stroke_spacing_mm))
    base_length_mm = max(1.0, float(config.sketch_stroke_length_mm))
    base_density = max(0.05, float(config.sketch_density))
    density_gamma = max(0.25, float(config.sketch_density_gamma))
    base_min_distance_mm = max(0.3, float(config.sketch_min_center_distance_mm))
    layers = (
        (threshold, base_spacing_mm, base_length_mm, base_density, base_min_distance_mm, 0.0, 0),
        (max(0.30, threshold + 0.14), base_spacing_mm * 0.88, base_length_mm * 0.92, base_density * 0.42, base_min_distance_mm * 0.90, math.radians(34.0), 173),
        (max(0.48, threshold + 0.30), base_spacing_mm * 0.78, base_length_mm * 0.82, base_density * 0.30, base_min_distance_mm * 0.82, math.radians(-40.0), 349),
        (max(0.66, threshold + 0.46), base_spacing_mm * 0.68, base_length_mm * 0.68, base_density * 0.22, base_min_distance_mm * 0.72, math.radians(70.0), 521),
    )

    for idx, (level, spacing_mm, length_mm, density, min_distance_mm, angle_bias, seed_offset) in enumerate(layers):
        layer_mask = _clean_tonal_mask(drawing_darkness >= level, scale_mm_per_px, level_index=idx + 1)
        layer_darkness = np.where(layer_mask, drawing_darkness, 0.0).astype(np.float32)
        if not np.any(layer_darkness >= level):
            continue
        # Use a wider structure field for sketch mode. Fine grass/noise gradients
        # make random-looking strokes; broad gradients produce hand-like shading.
        smooth = cv2.GaussianBlur(layer_darkness, (0, 0), sigmaX=max(1.5, 3.2 - 0.55 * idx))
        grad_x = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)
        rng = np.random.default_rng(int(config.portrait_seed) + seed_offset)
        centers = _grid_sketch_centers(
            layer_darkness,
            spacing_px=max(2.0, max(spacing_mm, min_distance_mm * 0.85) / max(1e-9, scale_mm_per_px)),
            jitter_px=jitter_px * 0.45,
            threshold=level,
            density_scale=density,
            density_gamma=density_gamma,
            rng=rng,
        )
        length_px = max(2.0, length_mm / max(1e-9, scale_mm_per_px))
        for sx, sy, dark in centers:
            local_length = length_px * (0.45 + 0.85 * min(1.0, float(dark)))
            fallback_angle = (
                math.sin((sx + float(config.portrait_seed + seed_offset) * 0.017) * 0.047)
                + math.cos((sy - float(config.portrait_seed + seed_offset) * 0.011) * 0.039)
            ) * 0.55
            stroke = _trace_portrait_stroke(
                layer_darkness,
                grad_x,
                grad_y,
                center=(sx, sy),
                length_px=local_length,
                step_px=step_px,
                threshold=level,
                fallback_angle=fallback_angle,
                angle_bias_rad=angle_bias,
            )
            if len(stroke) >= 2 and _polyline_length(stroke) >= min_segment_px:
                out.append(_chaikin_smooth_open(stroke, iterations=1))
    return out


def _generate_scribble_px(darkness: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> list[list[Point]]:
    h, w = darkness.shape[:2]
    spacing = max(1.0, float(config.scribble_line_spacing_mm) / max(1e-9, scale_mm_per_px))
    step = max(1.0, float(config.scribble_step_mm) / max(1e-9, scale_mm_per_px))
    amplitude = max(0.1, float(config.scribble_amplitude_mm) / max(1e-9, scale_mm_per_px))
    threshold = max(0.0, min(1.0, float(config.scribble_threshold)))
    min_segment_px = max(1.0, float(config.min_segment_mm) / max(1e-9, scale_mm_per_px))
    merge_gap_px = max(0.0, float(config.merge_gap_mm) / max(1e-9, scale_mm_per_px))
    out: list[list[Point]] = []
    y = spacing * 0.5
    row_index = 0
    while y < h:
        y0 = max(0, int(round(y - spacing * 0.5)))
        y1 = min(h, int(round(y + spacing * 0.5)) + 1)
        band = darkness[y0:y1, :]
        if band.size <= 0:
            y += spacing
            row_index += 1
            continue
        profile = np.percentile(band, 85, axis=0)
        active = profile >= threshold
        intervals: list[tuple[float, float]] = []
        start: int | None = None
        for idx, is_active in enumerate(active):
            if bool(is_active) and start is None:
                start = idx
            elif not bool(is_active) and start is not None:
                intervals.append((float(start), float(idx - 1)))
                start = None
        if start is not None:
            intervals.append((float(start), float(w - 1)))
        intervals = [
            (x0, x1)
            for x0, x1 in _merge_intervals(intervals, merge_gap_px)
            if (x1 - x0) >= min_segment_px
        ]
        if row_index % 2 == 1:
            intervals = list(reversed(intervals))
        phase_offset = row_index * math.pi * 0.37
        wave_period = max(3.0, 5.0 / max(1e-9, scale_mm_per_px))
        for x0, x1 in intervals:
            xs = np.arange(x0, x1 + 0.5 * step, step, dtype=np.float32)
            if len(xs) == 0 or float(xs[-1]) < x1:
                xs = np.append(xs, np.float32(x1))
            if row_index % 2 == 1:
                xs = xs[::-1]
            pts: list[Point] = []
            for x in xs:
                px = int(max(0, min(w - 1, round(float(x)))))
                py = int(max(0, min(h - 1, round(float(y)))))
                dark = float(darkness[py, px])
                amp = amplitude * (dark ** 1.2)
                yy = float(y) + math.sin((float(x) / wave_period) * (2.0 * math.pi) + phase_offset) * amp
                yy = max(0.0, min(float(h - 1), yy))
                pts.append((float(x), yy))
            if len(pts) >= 2:
                out.append(pts)
        y += spacing
        row_index += 1
    return out


def _sample_tangent(
    grad_x: np.ndarray,
    grad_y: np.ndarray,
    x: float,
    y: float,
    fallback_angle: float,
) -> Point:
    h, w = grad_x.shape[:2]
    px = int(max(0, min(w - 1, round(float(x)))))
    py = int(max(0, min(h - 1, round(float(y)))))
    gx = float(grad_x[py, px])
    gy = float(grad_y[py, px])
    mag = math.hypot(gx, gy)
    if mag <= 1e-5:
        return (math.cos(fallback_angle), math.sin(fallback_angle))
    # Draw along local isophotes. This follows face/shape contours instead of a rigid grid.
    return (-gy / mag, gx / mag)


def _rotate_vector(dx: float, dy: float, angle_rad: float) -> Point:
    if abs(angle_rad) <= 1e-9:
        return (dx, dy)
    ca = math.cos(angle_rad)
    sa = math.sin(angle_rad)
    return (dx * ca - dy * sa, dx * sa + dy * ca)


def _trace_portrait_stroke(
    darkness: np.ndarray,
    grad_x: np.ndarray,
    grad_y: np.ndarray,
    *,
    center: Point,
    length_px: float,
    step_px: float,
    threshold: float,
    fallback_angle: float,
    angle_bias_rad: float = 0.0,
) -> list[Point]:
    h, w = darkness.shape[:2]
    cx, cy = center
    if not (0 <= cx < w and 0 <= cy < h):
        return []
    cpx = int(max(0, min(w - 1, round(cx))))
    cpy = int(max(0, min(h - 1, round(cy))))
    if float(darkness[cpy, cpx]) < threshold:
        return []

    def walk(sign: float) -> list[Point]:
        pts: list[Point] = []
        x, y = cx, cy
        dx, dy = _sample_tangent(grad_x, grad_y, x, y, fallback_angle)
        dx, dy = _rotate_vector(dx, dy, angle_bias_rad)
        dx *= sign
        dy *= sign
        traveled = 0.0
        while traveled < length_px * 0.5:
            tx, ty = _sample_tangent(grad_x, grad_y, x, y, fallback_angle)
            tx, ty = _rotate_vector(tx, ty, angle_bias_rad)
            tx *= sign
            ty *= sign
            # Keep tangent orientation continuous; otherwise Sobel sign flips create zig-zag jumps.
            if tx * dx + ty * dy < 0.0:
                tx = -tx
                ty = -ty
            dx = dx * 0.72 + tx * 0.28
            dy = dy * 0.72 + ty * 0.28
            norm = max(1e-9, math.hypot(dx, dy))
            dx /= norm
            dy /= norm
            nx = x + dx * step_px
            ny = y + dy * step_px
            if not (0 <= nx < w and 0 <= ny < h):
                break
            px = int(max(0, min(w - 1, round(nx))))
            py = int(max(0, min(h - 1, round(ny))))
            dark = float(darkness[py, px])
            if dark < threshold * 0.65:
                break
            pts.append((nx, ny))
            x, y = nx, ny
            traveled += step_px
        return pts

    backward = list(reversed(walk(-1.0)))
    forward = walk(1.0)
    return backward + [(cx, cy)] + forward


def _portrait_keep_probability(dark: float, threshold: float, density_scale: float) -> float:
    density = min(1.0, max(0.0, (float(dark) - threshold) / max(1e-9, 1.0 - threshold)))
    return min(1.0, max(0.0, float(density_scale)) * (0.12 + 0.88 * (density ** 0.70)))


def _grid_portrait_centers(
    darkness: np.ndarray,
    *,
    spacing_px: float,
    jitter_px: float,
    threshold: float,
    density_scale: float,
    rng: np.random.Generator,
) -> list[tuple[float, float, float]]:
    h, w = darkness.shape[:2]
    centers: list[tuple[float, float, float]] = []
    y = spacing_px * 0.5
    row = 0
    while y < h:
        x_offset = (spacing_px * 0.5) if row % 2 else 0.0
        x = spacing_px * 0.5 + x_offset
        while x < w:
            jx = float(rng.uniform(-jitter_px, jitter_px)) if jitter_px > 0 else 0.0
            jy = float(rng.uniform(-jitter_px, jitter_px)) if jitter_px > 0 else 0.0
            sx = max(0.0, min(float(w - 1), x + jx))
            sy = max(0.0, min(float(h - 1), y + jy))
            dark = float(darkness[int(round(sy)), int(round(sx))])
            if dark >= threshold and rng.random() <= _portrait_keep_probability(dark, threshold, density_scale):
                centers.append((sx, sy, dark))
            x += spacing_px
        y += spacing_px
        row += 1
    return centers


def _sketch_keep_probability(dark: float, threshold: float, density_scale: float, gamma: float) -> float:
    density = min(1.0, max(0.0, (float(dark) - threshold) / max(1e-9, 1.0 - threshold)))
    # Sketch mode should behave like pen-plotter stippling/hatching: light
    # areas stay mostly open, while shadows accumulate substantially more ink.
    return min(1.0, max(0.0, float(density_scale)) * (density ** max(0.25, float(gamma))))


def _grid_sketch_centers(
    darkness: np.ndarray,
    *,
    spacing_px: float,
    jitter_px: float,
    threshold: float,
    density_scale: float,
    density_gamma: float,
    rng: np.random.Generator,
) -> list[tuple[float, float, float]]:
    h, w = darkness.shape[:2]
    centers: list[tuple[float, float, float]] = []
    y = spacing_px * 0.5
    row = 0
    while y < h:
        x_offset = (spacing_px * 0.5) if row % 2 else 0.0
        x = spacing_px * 0.5 + x_offset
        while x < w:
            jx = float(rng.uniform(-jitter_px, jitter_px)) if jitter_px > 0 else 0.0
            jy = float(rng.uniform(-jitter_px, jitter_px)) if jitter_px > 0 else 0.0
            sx = max(0.0, min(float(w - 1), x + jx))
            sy = max(0.0, min(float(h - 1), y + jy))
            dark = float(darkness[int(round(sy)), int(round(sx))])
            if dark >= threshold and rng.random() <= _sketch_keep_probability(dark, threshold, density_scale, density_gamma):
                centers.append((sx, sy, dark))
            x += spacing_px
        y += spacing_px
        row += 1
    return centers


def _blue_noise_portrait_centers(
    darkness: np.ndarray,
    *,
    spacing_px: float,
    jitter_px: float,
    threshold: float,
    density_scale: float,
    min_distance_px: float,
    rng: np.random.Generator,
) -> list[tuple[float, float, float]]:
    h, w = darkness.shape[:2]
    candidate_step = max(1.0, spacing_px * 0.62)
    candidates: list[tuple[float, float, float]] = []
    y = candidate_step * 0.5
    while y < h:
        x = candidate_step * 0.5
        while x < w:
            jx = float(rng.uniform(-jitter_px, jitter_px)) if jitter_px > 0 else 0.0
            jy = float(rng.uniform(-jitter_px, jitter_px)) if jitter_px > 0 else 0.0
            sx = max(0.0, min(float(w - 1), x + jx))
            sy = max(0.0, min(float(h - 1), y + jy))
            dark = float(darkness[int(round(sy)), int(round(sx))])
            if dark >= threshold and rng.random() <= _portrait_keep_probability(dark, threshold, density_scale):
                candidates.append((sx, sy, dark))
            x += candidate_step
        y += candidate_step

    rng.shuffle(candidates)
    cell = max(1.0, float(min_distance_px))
    occupied: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
    accepted: list[tuple[float, float, float]] = []
    max_centers = max(1, int((float(w) * float(h) / max(1.0, spacing_px * spacing_px)) * 0.34 * max(0.25, density_scale)))

    for sx, sy, dark in candidates:
        local_min = max(0.5, float(min_distance_px) * (1.12 - 0.42 * min(1.0, dark)))
        key = (int(math.floor(sx / cell)), int(math.floor(sy / cell)))
        too_close = False
        for gy in range(key[1] - 2, key[1] + 3):
            for gx in range(key[0] - 2, key[0] + 3):
                for ox, oy, odark in occupied.get((gx, gy), []):
                    neighbor_min = max(0.5, float(min_distance_px) * (1.12 - 0.42 * min(1.0, odark)))
                    min_allowed = min(local_min, neighbor_min)
                    if math.hypot(sx - ox, sy - oy) < min_allowed:
                        too_close = True
                        break
                if too_close:
                    break
            if too_close:
                break
        if too_close:
            continue
        accepted.append((sx, sy, dark))
        occupied.setdefault(key, []).append((sx, sy, dark))
        if len(accepted) >= max_centers:
            break
    return accepted


def _portrait_centers(
    darkness: np.ndarray,
    config: PhotoPlotConfig,
    *,
    spacing_px: float,
    jitter_px: float,
    threshold: float,
    scale_mm_per_px: float,
    rng: np.random.Generator,
) -> list[tuple[float, float, float]]:
    sampling = str(config.portrait_sampling or "blue_noise").strip().lower()
    density_scale = max(0.05, float(config.portrait_density))
    if sampling == "grid":
        return _grid_portrait_centers(
            darkness,
            spacing_px=spacing_px,
            jitter_px=jitter_px,
            threshold=threshold,
            density_scale=density_scale,
            rng=rng,
        )
    min_distance_px = max(0.5, float(config.portrait_min_center_distance_mm) / max(1e-9, scale_mm_per_px))
    return _blue_noise_portrait_centers(
        darkness,
        spacing_px=spacing_px,
        jitter_px=jitter_px,
        threshold=threshold,
        density_scale=density_scale,
        min_distance_px=min_distance_px,
        rng=rng,
    )


def _generate_portrait_px(darkness: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> list[list[Point]]:
    spacing_px = max(2.0, float(config.portrait_stroke_spacing_mm) / max(1e-9, scale_mm_per_px))
    length_px = max(2.0, float(config.portrait_stroke_length_mm) / max(1e-9, scale_mm_per_px))
    step_px = max(1.0, float(config.scribble_step_mm) / max(1e-9, scale_mm_per_px))
    threshold = max(0.0, min(1.0, float(config.portrait_threshold)))
    jitter_px = max(0.0, float(config.portrait_jitter_mm) / max(1e-9, scale_mm_per_px))
    min_segment_px = max(1.0, float(config.min_segment_mm) / max(1e-9, scale_mm_per_px))

    smooth = cv2.GaussianBlur(darkness.astype(np.float32), (0, 0), sigmaX=1.2)
    grad_x = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)
    rng = np.random.default_rng(int(config.portrait_seed))

    out: list[list[Point]] = []
    for sx, sy, dark in _portrait_centers(
        darkness,
        config,
        spacing_px=spacing_px,
        jitter_px=jitter_px,
        threshold=threshold,
        scale_mm_per_px=scale_mm_per_px,
        rng=rng,
    ):
        local_length = length_px * (0.35 + 0.9 * dark)
        fallback_angle = (
            math.sin((sx + float(config.portrait_seed) * 0.017) * 0.047)
            + math.cos((sy - float(config.portrait_seed) * 0.011) * 0.039)
        ) * 0.55
        stroke = _trace_portrait_stroke(
            darkness,
            grad_x,
            grad_y,
            center=(sx, sy),
            length_px=local_length,
            step_px=step_px,
            threshold=threshold,
            fallback_angle=fallback_angle,
        )
        if len(stroke) >= 2 and _polyline_length(stroke) >= min_segment_px:
            out.append(stroke)
    return out


def _portrait_content_mask(darkness: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> np.ndarray:
    threshold = max(0.0, min(1.0, float(config.portrait_cleanup_threshold)))
    raw = (darkness >= threshold).astype(np.uint8)
    if not bool(config.portrait_cleanup_enabled):
        return raw.astype(bool)
    if not np.any(raw):
        return raw.astype(bool)

    kernel_px = max(1, int(round(1.2 / max(1e-9, scale_mm_per_px))))
    if kernel_px > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_px * 2 + 1, kernel_px * 2 + 1))
        raw = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, kernel)

    min_area_px = max(8, int(round(float(config.portrait_min_component_area_mm2) / max(1e-9, scale_mm_per_px * scale_mm_per_px))))
    labels_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(raw, connectivity=8)
    keep = np.zeros_like(raw, dtype=np.uint8)
    for label in range(1, labels_count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area_px:
            keep[labels == label] = 1

    if not np.any(keep):
        # If the image is extremely sparse, fall back to the raw mask instead of dropping everything.
        keep = raw

    dilate_px = max(0, int(round(float(config.portrait_mask_dilate_mm) / max(1e-9, scale_mm_per_px))))
    if dilate_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_px * 2 + 1, dilate_px * 2 + 1))
        keep = cv2.dilate(keep, kernel, iterations=1)
    return keep.astype(bool)


def _apply_mask_to_darkness(darkness: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    if mask is None:
        return darkness
    return np.where(mask, darkness, 0.0).astype(np.float32)


def _polyline_mask_ratio(polyline: Sequence[Point], mask: np.ndarray) -> float:
    if not polyline:
        return 0.0
    h, w = mask.shape[:2]
    inside = 0
    for x, y in polyline:
        px = int(max(0, min(w - 1, round(float(x)))))
        py = int(max(0, min(h - 1, round(float(y)))))
        if bool(mask[py, px]):
            inside += 1
    return inside / float(len(polyline))


def _generate_edge_px(
    processed_gray: np.ndarray,
    config: PhotoPlotConfig,
    scale_mm_per_px: float,
    include_mask: np.ndarray | None = None,
) -> list[list[Point]]:
    if not config.edge_enabled:
        return []
    low = max(0, min(255, int(config.edge_low_threshold)))
    high = max(low + 1, min(255, int(config.edge_high_threshold)))
    edges = cv2.Canny(processed_gray, low, high)
    contours, _hier = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    min_len_px = max(2.0, float(config.edge_min_length_mm) / max(1e-9, scale_mm_per_px))
    out: list[list[Point]] = []
    for contour in contours:
        if len(contour) < 3:
            continue
        approx = cv2.approxPolyDP(contour, epsilon=0.9, closed=False)
        pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
        pts = _chaikin_smooth_open(pts, iterations=1)
        if include_mask is not None and _polyline_mask_ratio(pts, include_mask) < 0.30:
            continue
        if len(pts) >= 2 and _polyline_length(pts) >= min_len_px:
            out.append(pts)
    return out


def order_polylines_nearest(polylines: Sequence[Sequence[Point]], *, limit: int = 4500) -> list[Polyline]:
    remaining = [list(poly) for poly in polylines if len(poly) >= 2]
    if len(remaining) <= 2 or len(remaining) > int(limit):
        return remaining
    ordered: list[Polyline] = []
    current = remaining.pop(0)
    ordered.append(current)
    tail = current[-1]
    while remaining:
        best_idx = 0
        best_reverse = False
        best_dist = float("inf")
        for idx, cand in enumerate(remaining):
            d0 = math.hypot(cand[0][0] - tail[0], cand[0][1] - tail[1])
            d1 = math.hypot(cand[-1][0] - tail[0], cand[-1][1] - tail[1])
            if d0 < best_dist:
                best_idx = idx
                best_reverse = False
                best_dist = d0
            if d1 < best_dist:
                best_idx = idx
                best_reverse = True
                best_dist = d1
        nxt = remaining.pop(best_idx)
        if best_reverse:
            nxt = list(reversed(nxt))
        ordered.append(nxt)
        tail = nxt[-1]
    return ordered


def generate_photo_plot(
    image_path: Path | str,
    config: PhotoPlotConfig | None = None,
    work_area: WorkArea | None = None,
) -> PhotoPlotResult:
    cfg = config or PhotoPlotConfig()
    if cfg.mode not in {"hatch", "scribble", "portrait", "sketch", "classic"}:
        raise ValueError(f"unsupported photo plot mode: {cfg.mode}")
    area = work_area or WorkArea()
    path = Path(image_path)
    darkness, source_size, processed_size, processed_gray = _load_darkness(path, cfg)
    x_left, y_top, target_w, target_h, scale = _fit_image_to_work_area(processed_size, area, cfg)
    content_mask: np.ndarray | None = None
    drawing_darkness = darkness
    edge_gray = processed_gray
    if cfg.mode == "portrait":
        content_mask = _portrait_content_mask(darkness, cfg, scale)
        drawing_darkness = _apply_mask_to_darkness(darkness, content_mask)

    if cfg.mode == "classic":
        px_polylines = _generate_classic_px(drawing_darkness, cfg, scale)
    elif cfg.mode == "hatch":
        px_polylines = _generate_hatch_px(drawing_darkness, cfg, scale)
    elif cfg.mode == "scribble":
        px_polylines = _generate_scribble_px(drawing_darkness, cfg, scale)
    elif cfg.mode == "portrait":
        px_polylines = _generate_portrait_px(drawing_darkness, cfg, scale)
    else:
        px_polylines = _generate_sketch_px(drawing_darkness, cfg, scale)
    px_polylines.extend(_generate_edge_px(edge_gray, cfg, scale, include_mask=content_mask))

    machine_polylines = [
        _image_to_machine(poly, x_left=x_left, y_top=y_top, scale_mm_per_px=scale)
        for poly in px_polylines
        if len(poly) >= 2
    ]
    if cfg.route_optimize:
        machine_polylines = order_polylines_nearest(machine_polylines, limit=int(cfg.route_optimize_limit))

    draw_length = sum(_polyline_length(poly) for poly in machine_polylines)
    point_count = sum(len(poly) for poly in machine_polylines)
    bounds = polylines_bounds(machine_polylines)
    stats = {
        "polyline_count": len(machine_polylines),
        "point_count": point_count,
        "draw_length_mm": round(draw_length, 3),
        "bounds": [round(v, 3) for v in bounds],
        "config": asdict(cfg),
    }
    if content_mask is not None:
        stats["portrait_content_mask_px"] = int(np.count_nonzero(content_mask))
    return PhotoPlotResult(
        mode=cfg.mode,
        source_size_px=(int(source_size[0]), int(source_size[1])),
        processed_size_px=(int(processed_size[0]), int(processed_size[1])),
        target_size_mm=(round(target_w, 3), round(target_h, 3)),
        placement_bounds=(round(x_left, 3), round(x_left + target_w, 3), round(y_top - target_h, 3), round(y_top, 3)),
        polylines=machine_polylines,
        stats=stats,
    )
