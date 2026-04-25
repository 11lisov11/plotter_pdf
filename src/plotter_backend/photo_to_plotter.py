from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps


Point = tuple[float, float]
Polyline = list[Point]
PhotoMode = Literal["hatch", "scribble"]


@dataclass(frozen=True)
class WorkArea:
    min_x: float = 0.0
    max_x: float = 180.0
    min_y: float = -280.0
    max_y: float = 0.0


@dataclass(frozen=True)
class PhotoPlotConfig:
    mode: PhotoMode = "hatch"
    margin_mm: float = 5.0
    target_width_mm: float | None = None
    target_height_mm: float | None = None
    max_side_px: int = 900
    contrast: float = 1.12
    gamma: float = 1.05
    blur_px: int = 3
    hatch_spacing_mm: float = 1.2
    hatch_levels: tuple[float, ...] = (0.18, 0.34, 0.50, 0.66)
    hatch_angles_deg: tuple[float, ...] = (0.0, 45.0, -45.0, 90.0)
    min_segment_mm: float = 0.8
    merge_gap_mm: float = 0.55
    edge_enabled: bool = True
    edge_low_threshold: int = 70
    edge_high_threshold: int = 170
    edge_min_length_mm: float = 2.0
    scribble_line_spacing_mm: float = 1.25
    scribble_step_mm: float = 0.75
    scribble_amplitude_mm: float = 1.6
    scribble_threshold: float = 0.06
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
    img = img.convert("L")
    max_side = max(32, int(config.max_side_px))
    if max(img.size) > max_side:
        scale = max_side / float(max(img.size))
        new_size = (max(1, int(round(img.size[0] * scale))), max(1, int(round(img.size[1] * scale))))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    img = ImageOps.autocontrast(img)
    gray = np.asarray(img, dtype=np.float32) / 255.0
    darkness = 1.0 - gray
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
    y = min_ry
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
    levels = tuple(float(v) for v in config.hatch_levels if 0.0 < float(v) < 1.0)
    angles = tuple(float(v) for v in config.hatch_angles_deg) or (0.0,)
    out: list[list[Point]] = []
    for idx, level in enumerate(levels):
        mask = darkness >= level
        out.extend(
            _scan_hatch_segments(
                mask,
                angle_deg=angles[idx % len(angles)],
                spacing_px=spacing_px,
                min_segment_px=min_segment_px,
                merge_gap_px=merge_gap_px,
            )
        )
    return out


def _generate_scribble_px(darkness: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> list[list[Point]]:
    h, w = darkness.shape[:2]
    spacing = max(1.0, float(config.scribble_line_spacing_mm) / max(1e-9, scale_mm_per_px))
    step = max(1.0, float(config.scribble_step_mm) / max(1e-9, scale_mm_per_px))
    amplitude = max(0.1, float(config.scribble_amplitude_mm) / max(1e-9, scale_mm_per_px))
    threshold = max(0.0, min(1.0, float(config.scribble_threshold)))
    out: list[list[Point]] = []
    y = spacing * 0.5
    row_index = 0
    while y < h:
        y0 = max(0, int(round(y - spacing * 0.5)))
        y1 = min(h, int(round(y + spacing * 0.5)) + 1)
        band = darkness[y0:y1, :]
        if band.size <= 0 or float(np.percentile(band, 85)) < threshold:
            y += spacing
            row_index += 1
            continue
        xs = np.arange(0.0, float(w), step, dtype=np.float32)
        if row_index % 2 == 1:
            xs = xs[::-1]
        pts: list[Point] = []
        phase_offset = row_index * math.pi * 0.37
        wave_period = max(3.0, 5.0 / max(1e-9, scale_mm_per_px))
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


def _generate_edge_px(processed_gray: np.ndarray, config: PhotoPlotConfig, scale_mm_per_px: float) -> list[list[Point]]:
    if not config.edge_enabled:
        return []
    low = max(0, min(255, int(config.edge_low_threshold)))
    high = max(low + 1, min(255, int(config.edge_high_threshold)))
    edges = cv2.Canny(processed_gray, low, high)
    contours, _hier = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    min_len_px = max(2.0, float(config.edge_min_length_mm) / max(1e-9, scale_mm_per_px))
    out: list[list[Point]] = []
    for contour in contours:
        if len(contour) < 3:
            continue
        approx = cv2.approxPolyDP(contour, epsilon=1.1, closed=False)
        pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
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
    if cfg.mode not in {"hatch", "scribble"}:
        raise ValueError(f"unsupported photo plot mode: {cfg.mode}")
    area = work_area or WorkArea()
    path = Path(image_path)
    darkness, source_size, processed_size, processed_gray = _load_darkness(path, cfg)
    x_left, y_top, target_w, target_h, scale = _fit_image_to_work_area(processed_size, area, cfg)

    if cfg.mode == "hatch":
        px_polylines = _generate_hatch_px(darkness, cfg, scale)
    else:
        px_polylines = _generate_scribble_px(darkness, cfg, scale)
    px_polylines.extend(_generate_edge_px(processed_gray, cfg, scale))

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
    return PhotoPlotResult(
        mode=cfg.mode,
        source_size_px=(int(source_size[0]), int(source_size[1])),
        processed_size_px=(int(processed_size[0]), int(processed_size[1])),
        target_size_mm=(round(target_w, 3), round(target_h, 3)),
        placement_bounds=(round(x_left, 3), round(x_left + target_w, 3), round(y_top - target_h, 3), round(y_top, 3)),
        polylines=machine_polylines,
        stats=stats,
    )

