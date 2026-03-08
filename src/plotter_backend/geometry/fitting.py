from __future__ import annotations

from typing import Callable, List, Tuple

Point = Tuple[float, float]
Polyline = List[Point]
PolylineSet = List[Polyline]


def fit_polylines_to_area(
    polylines: PolylineSet,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    *,
    fit_to_work_area: bool,
    work_area_bounds_fn: Callable[[], Tuple[float, float, float, float]],
    work_area_margin: float,
    allow_upscale_to_work_area: bool,
    exact_geometry_mode: bool,
    min_fit_scale_for_dimensional_draw: float,
    pass_cols: int,
    pass_rows: int,
    compute_pass_shift_fn: Callable[[float, float, float, float], Tuple[float, float, dict]],
    logger=print,
) -> PolylineSet:
    if not polylines or not fit_to_work_area:
        return polylines

    w = max_x - min_x
    h = max_y - min_y
    if w <= 0.0 or h <= 0.0:
        return polylines

    area_min_x, area_max_x, area_min_y, area_max_y = work_area_bounds_fn()
    area_w = max(1.0, area_max_x - area_min_x)
    area_h = max(1.0, area_max_y - area_min_y)
    usable_w = max(1.0, area_w - 2.0 * float(work_area_margin))
    usable_h = max(1.0, area_h - 2.0 * float(work_area_margin))

    raw_scale = min(usable_w / w, usable_h / h)
    fit_scale = raw_scale if allow_upscale_to_work_area else min(1.0, raw_scale)
    use_dimensional_guard = exact_geometry_mode and fit_scale < float(min_fit_scale_for_dimensional_draw)

    if use_dimensional_guard:
        scale = 1.0
        # In strict 1:1 mode, do not center overflowing width.
        # Keep the left edge anchored and clip only on the right side.
        if w > usable_w:
            tx = area_min_x + work_area_margin - min_x
        else:
            tx = area_min_x + work_area_margin + (usable_w - w) / 2.0 - min_x
        ty = area_min_y + work_area_margin + (usable_h - h) / 2.0 - min_y
        if logger:
            logger(
                "Fit guard (1:1 mm): required fit scale "
                f"{fit_scale:.4f} is below threshold {min_fit_scale_for_dimensional_draw:.3f}; "
                "keeping scale=1.0 and clipping overflow to work area."
            )
    else:
        scale = fit_scale
        scaled_w = w * scale
        scaled_h = h * scale
        tx = area_min_x + work_area_margin + (usable_w - scaled_w) / 2.0 - min_x * scale
        ty = area_min_y + work_area_margin + (usable_h - scaled_h) / 2.0 - min_y * scale

        if scale < 0.999999 or abs(tx) > 1e-9 or abs(ty) > 1e-9:
            if logger:
                logger(
                    f"Fit to work area: scale={scale:.4f}, translate=({tx:.3f},{ty:.3f}), "
                    f"from ({min_x:.3f}, {min_y:.3f})-({max_x:.3f}, {max_y:.3f})"
                )

    if int(pass_cols) > 1 or int(pass_rows) > 1:
        src_w_eff = w * scale
        src_h_eff = h * scale
        shift_x, shift_y, info = compute_pass_shift_fn(src_w_eff, src_h_eff, usable_w, usable_h)
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

    out: PolylineSet = []
    for poly in polylines:
        out.append([((x * scale) + tx, (y * scale) + ty) for x, y in poly])
    return out
