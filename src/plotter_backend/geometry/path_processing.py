from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]


def bounds_path_items(path_items: Sequence[Any]) -> Optional[Tuple[float, float, float, float]]:
    points = [p for item in path_items for p in list(getattr(item, "points", []) or [])]
    if not points:
        return None
    min_x = min(float(p[0]) for p in points)
    max_x = max(float(p[0]) for p in points)
    min_y = min(float(p[1]) for p in points)
    max_y = max(float(p[1]) for p in points)
    return min_x, max_x, min_y, max_y


def normalize_path_units_to_page(
    items: List[Any],
    page_w_mm: float,
    page_h_mm: float,
    *,
    ratio_min: float = 1.5,
    ratio_max: float = 20.0,
    ratio_uniform_tol: float = 0.20,
    logger=print,
) -> Tuple[List[Any], float]:
    # Some PDF->SVG converters output path coordinates in px while page size is in mm.
    if not items or page_w_mm <= 0.0 or page_h_mm <= 0.0:
        return items, 1.0
    bounds = bounds_path_items(items)
    if bounds is None:
        return items, 1.0
    x0, x1, y0, y1 = bounds
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    if w <= 0.0 or h <= 0.0:
        return items, 1.0

    rx = w / float(page_w_mm)
    ry = h / float(page_h_mm)
    if rx < ratio_min or ry < ratio_min:
        return items, 1.0
    if rx > ratio_max or ry > ratio_max:
        return items, 1.0
    if abs(rx - ry) / max(rx, ry) > ratio_uniform_tol:
        return items, 1.0

    ratio = 0.5 * (rx + ry)
    if ratio <= 0.0:
        return items, 1.0
    scale = 1.0 / ratio

    for item in items:
        pts = list(getattr(item, "points", []) or [])
        if not pts:
            continue
        item.points = [(float(x) * scale, float(y) * scale) for x, y in pts]

    if logger:
        logger(
            "Normalized SVG units to page mm: "
            f"ratio~{ratio:.3f} (rx={rx:.3f}, ry={ry:.3f}), scale={scale:.6f}"
        )
    return items, scale


def poly_inside_bbox(
    poly: Sequence[Point],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    eps: float,
) -> bool:
    return all(
        (x_min - eps) <= float(x) <= (x_max + eps) and (y_min - eps) <= float(y) <= (y_max + eps)
        for x, y in poly
    )


def filter_outer_frame_path_items(
    items: List[Any],
    *,
    auto_trim_outer_frame: bool,
    outer_frame_edge_eps_mm: float,
    outer_frame_side_ratio: float,
    outer_frame_min_fill_ratio: float,
    outer_frame_cover_ratio: float,
    bounds_polylines_fn: Callable[[List[List[Point]]], Tuple[float, float, float, float]],
    is_axis_aligned_rectangle_fn: Callable[[List[Point]], bool],
    poly_inside_bbox_fn: Callable[[Sequence[Point], float, float, float, float, float], bool] = poly_inside_bbox,
    logger=print,
) -> Tuple[List[Any], List[Any]]:
    if not auto_trim_outer_frame or len(items) < 2:
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

    bbox_tol = max(float(outer_frame_edge_eps_mm), min(all_w, all_h) * 0.002)

    def candidate_score(item: Any) -> Optional[Tuple[float, Tuple[float, float, float, float]]]:
        pts = list(getattr(item, "points", []) or [])
        if not pts or not bool(getattr(item, "closed", False)):
            return None
        if not is_axis_aligned_rectangle_fn(pts):
            return None
        if not bool(getattr(item, "is_stroke", False)):
            return None

        x0, x1, y0, y1 = bounds_polylines_fn([pts])
        w = x1 - x0
        h = y1 - y0
        if w <= 0.0 or h <= 0.0:
            return None

        width_ratio = w / all_w
        height_ratio = h / all_h
        area_ratio = (w * h) / all_area if all_area > 0.0 else 0.0
        if width_ratio < outer_frame_side_ratio or height_ratio < outer_frame_side_ratio:
            return None
        if area_ratio < outer_frame_min_fill_ratio:
            return None

        touches_left = abs(x0 - all_x0) <= bbox_tol
        touches_right = abs(x1 - all_x1) <= bbox_tol
        touches_bottom = abs(y0 - all_y0) <= bbox_tol
        touches_top = abs(y1 - all_y1) <= bbox_tol
        if not (touches_left and touches_right and touches_bottom and touches_top):
            return None

        inner = [other for other in items if other is not item]
        if not inner:
            return None

        all_inner = 0
        inside = 0
        for other in inner:
            other_points = list(getattr(other, "points", []) or [])
            all_inner += len(other_points)
            for pt in other_points:
                if poly_inside_bbox_fn([pt], x0, x1, y0, y1, bbox_tol):
                    inside += 1

        if all_inner == 0:
            return None
        cover_ratio = inside / float(all_inner)
        if cover_ratio < outer_frame_cover_ratio:
            return None

        score = area_ratio + 0.5 * cover_ratio + 0.05 * max(width_ratio, height_ratio)
        return score, (x0, x1, y0, y1)

    scored: List[Tuple[float, Tuple[float, float, float, float], Any]] = []
    for item in items:
        if not list(getattr(item, "points", []) or []):
            continue
        score = candidate_score(item)
        if score is not None:
            scored.append((score[0], score[1], item))

    if not scored:
        # Fallback: outer border may be exported as 4 separate axis-aligned lines.
        edge_candidates: Dict[str, List[Tuple[float, Any]]] = {"left": [], "right": [], "bottom": [], "top": []}
        for item in items:
            pts = list(getattr(item, "points", []) or [])
            if not bool(getattr(item, "is_stroke", False)) or not pts:
                continue
            x0, x1, y0, y1 = bounds_polylines_fn([pts])
            w = x1 - x0
            h = y1 - y0
            if w <= 0.0 and h <= 0.0:
                continue

            center_x = (x0 + x1) * 0.5
            center_y = (y0 + y1) * 0.5
            if abs(w) <= bbox_tol and (h / all_h) >= outer_frame_side_ratio:
                if abs(x0 - all_x0) <= bbox_tol or abs(x1 - all_x0) <= bbox_tol or abs(center_x - all_x0) <= bbox_tol:
                    edge_candidates["left"].append((h, item))
                if abs(x0 - all_x1) <= bbox_tol or abs(x1 - all_x1) <= bbox_tol or abs(center_x - all_x1) <= bbox_tol:
                    edge_candidates["right"].append((h, item))
            if abs(h) <= bbox_tol and (w / all_w) >= outer_frame_side_ratio:
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
                if logger:
                    logger(
                        "Detected outer border from separate axis-aligned lines: "
                        f"left/right/bottom/top candidates={len(edge_candidates['left'])}/{len(edge_candidates['right'])}/"
                        f"{len(edge_candidates['bottom'])}/{len(edge_candidates['top'])}"
                    )
                return [it for it in items if id(it) not in chosen_ids], [it for it in items if id(it) in chosen_ids]
        return items, []

    scored.sort(key=lambda x: x[0], reverse=True)
    _, chosen_bounds, chosen_item = scored[0]
    chosen_points = list(getattr(chosen_item, "points", []) or [])
    if logger:
        logger(
            "Detected outer border candidate: "
            f"bbox=({chosen_bounds[0]:.2f},{chosen_bounds[1]:.2f},{chosen_bounds[2]:.2f},{chosen_bounds[3]:.2f}) "
            f"points={len(chosen_points)}"
        )
    return [it for it in items if it is not chosen_item], [chosen_item]


def clip_path_items_to_rect(
    items: List[Any],
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    *,
    clip_segment_to_rect_fn: Callable[
        [float, float, float, float, float, float, float, float], Optional[Tuple[Point, Point]]
    ],
    clamp_to_rect_fn: Callable[[float, float, float, float, float, float], Point],
    point_in_rect_fn: Callable[[float, float, float, float, float, float], bool],
    points_distance_fn: Callable[[Point, Point], float],
    path_is_closed_fn: Callable[[List[Point]], bool],
    item_factory: Callable[[List[Point], Any, bool], Any],
    clip_continuity_eps_mm: float,
    logger=print,
) -> Tuple[List[Any], int, int]:
    if not items:
        return [], 0, 0

    clipped_all: List[Any] = []
    dropped_segments = 0
    written_segments = 0

    def flush_polyline(source_item: Any, poly: List[Point]) -> List[Point]:
        if len(poly) >= 2:
            out_item = item_factory(poly, source_item, path_is_closed_fn(poly))
            clipped_all.append(out_item)
        return []

    for item in items:
        points = list(getattr(item, "points", []) or [])
        if len(points) < 2:
            continue
        out_poly: List[Point] = []
        for i in range(1, len(points)):
            x1, y1 = points[i - 1]
            x2, y2 = points[i]
            clipped = clip_segment_to_rect_fn(float(x1), float(y1), float(x2), float(y2), min_x, max_x, min_y, max_y)
            if clipped is None:
                dropped_segments += 1
                out_poly = flush_polyline(item, out_poly)
                continue

            (cx1, cy1), (cx2, cy2) = clipped
            cx1, cy1 = clamp_to_rect_fn(cx1, cy1, min_x, max_x, min_y, max_y)
            cx2, cy2 = clamp_to_rect_fn(cx2, cy2, min_x, max_x, min_y, max_y)

            if not point_in_rect_fn(cx1, cy1, min_x, max_x, min_y, max_y):
                dropped_segments += 1
                out_poly = flush_polyline(item, out_poly)
                continue

            if not out_poly:
                out_poly = [(cx1, cy1)]

            if points_distance_fn((cx1, cy1), out_poly[-1]) > float(clip_continuity_eps_mm):
                out_poly = flush_polyline(item, out_poly)
                out_poly = [(cx1, cy1)]
            else:
                cx1, cy1 = out_poly[-1]

            if points_distance_fn((cx2, cy2), out_poly[-1]) > 1e-6:
                out_poly.append((cx2, cy2))
                written_segments += 1

        out_poly = flush_polyline(item, out_poly)

    if logger and dropped_segments:
        logger(f"Page/content clip: kept {written_segments} visible segments, dropped {dropped_segments} out-of-area segments.")
    return clipped_all, written_segments, dropped_segments


def clip_to_content_area(
    items: List[Any],
    page_w: float,
    page_h: float,
    *,
    page_margin_enabled: bool,
    page_margin_left_mm: float,
    page_margin_right_mm: float,
    page_margin_top_mm: float,
    page_margin_bottom_mm: float,
    page_margin_a4_only: bool,
    page_a4_tol_mm: float,
    clip_path_items_to_rect_fn: Callable[[List[Any], float, float, float, float], Tuple[List[Any], int, int]],
    logger=print,
) -> Tuple[List[Any], bool]:
    if (
        not page_margin_enabled
        or page_w <= 1.0
        or page_h <= 1.0
        or (page_margin_left_mm <= 0 and page_margin_right_mm <= 0 and page_margin_top_mm <= 0 and page_margin_bottom_mm <= 0)
    ):
        return items, False

    left = float(page_margin_left_mm)
    right = float(page_margin_right_mm)
    top = float(page_margin_top_mm)
    bottom = float(page_margin_bottom_mm)
    if left < 0.0 or right < 0.0 or top < 0.0 or bottom < 0.0:
        if logger:
            logger("Warning: page margin is negative, skipping content area crop.")
        return items, False

    if page_margin_a4_only:
        is_a4 = (abs(page_w - 210.0) <= page_a4_tol_mm and abs(page_h - 297.0) <= page_a4_tol_mm) or (
            abs(page_w - 297.0) <= page_a4_tol_mm and abs(page_h - 210.0) <= page_a4_tol_mm
        )
        if not is_a4:
            if logger:
                logger(f"Page {page_w:.1f}x{page_h:.1f} mm not A4; skipping content area crop.")
            return items, False

    content_min_x = left
    content_max_x = page_w - right
    content_min_y = top
    content_max_y = page_h - bottom

    if not (content_min_x < content_max_x and content_min_y < content_max_y):
        if logger:
            logger("Warning: invalid page content area, skipping content area crop.")
        return items, False

    clipped_items, _, dropped = clip_path_items_to_rect_fn(items, content_min_x, content_max_x, content_min_y, content_max_y)
    if not clipped_items:
        if logger:
            logger("Content area crop removed all paths; keeping original geometry.")
        return items, False

    if logger:
        logger(
            f"Applied content area crop: x({content_min_x:.1f},{content_max_x:.1f}) y({content_min_y:.1f},{content_max_y:.1f}) "
            f"dropped segments={dropped}"
        )
    return clipped_items, True
