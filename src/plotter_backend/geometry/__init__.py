from __future__ import annotations

from .arc_fit import arc_extents_xy, fit_circle_kasa, polyline_fit_arc, polyline_is_near_line, solve_3x3, unwrap_angles
from .clipping import clip_polylines_to_rect, clip_segment_to_rect, clamp_to_rect, point_in_rect
from .fitting import fit_polylines_to_area
from .hatching import (
    hatch_polygon,
    intersects_for_scanline,
    polygon_area,
    polygon_bbox,
    rotate_point,
    rotate_polyline,
    should_hatch_polygon,
)
from .path_processing import (
    bounds_path_items,
    clip_to_content_area,
    clip_path_items_to_rect,
    filter_outer_frame_path_items,
    normalize_path_units_to_page,
    poly_inside_bbox,
)
from .polyline import bounds_polylines, points_distance, polyline_length, total_draw_length_mm, translate_polylines
from .sheet_tiling import (
    compute_pass_shift,
    plan_tiled_passes_for_sheet,
    resolve_sheet_size_mm,
    sheet_pass_post_translation_mm,
    sheet_pass_rotation_deg,
    tile_window_start,
)
from .simplify import path_is_closed, point_line_distance, rdp_simplify_polyline, simplify_polyline
from .svg_path import arc_to_polyline, cubic_approx, parse_path_tokens, quadratic_approx
from .transform import mat_apply, mat_mul, parse_points, parse_transform, transform_points
from .work_area import base_work_area_bounds, configure_active_work_area, work_area_bounds

__all__ = [
    "hatch_polygon",
    "intersects_for_scanline",
    "bounds_polylines",
    "bounds_path_items",
    "clip_path_items_to_rect",
    "clip_to_content_area",
    "arc_extents_xy",
    "fit_circle_kasa",
    "fit_polylines_to_area",
    "clip_polylines_to_rect",
    "clip_segment_to_rect",
    "clamp_to_rect",
    "cubic_approx",
    "mat_apply",
    "mat_mul",
    "path_is_closed",
    "parse_points",
    "parse_transform",
    "polyline_fit_arc",
    "polyline_is_near_line",
    "point_in_rect",
    "polygon_area",
    "polygon_bbox",
    "point_line_distance",
    "points_distance",
    "poly_inside_bbox",
    "polyline_length",
    "parse_path_tokens",
    "rdp_simplify_polyline",
    "rotate_point",
    "rotate_polyline",
    "compute_pass_shift",
    "plan_tiled_passes_for_sheet",
    "resolve_sheet_size_mm",
    "sheet_pass_post_translation_mm",
    "sheet_pass_rotation_deg",
    "simplify_polyline",
    "quadratic_approx",
    "solve_3x3",
    "should_hatch_polygon",
    "normalize_path_units_to_page",
    "filter_outer_frame_path_items",
    "tile_window_start",
    "total_draw_length_mm",
    "translate_polylines",
    "transform_points",
    "unwrap_angles",
    "arc_to_polyline",
    "base_work_area_bounds",
    "configure_active_work_area",
    "work_area_bounds",
]
