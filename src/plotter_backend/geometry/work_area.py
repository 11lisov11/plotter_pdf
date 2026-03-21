from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple


def base_work_area_bounds(
    *,
    work_area_min_x: float,
    work_area_max_x: float,
    work_area_min_y: float,
    work_area_max_y: float,
    work_offset_x_mm: float,
    work_offset_y_mm: float,
) -> Tuple[float, float, float, float]:
    min_x = min(work_area_min_x + work_offset_x_mm, work_area_max_x + work_offset_x_mm)
    max_x = max(work_area_min_x + work_offset_x_mm, work_area_max_x + work_offset_x_mm)
    min_y = min(work_area_min_y + work_offset_y_mm, work_area_max_y + work_offset_y_mm)
    max_y = max(work_area_min_y + work_offset_y_mm, work_area_max_y + work_offset_y_mm)
    return min_x, max_x, min_y, max_y


def work_area_bounds(
    *,
    active_work_area_bounds: Optional[Tuple[float, float, float, float]],
    base_work_area_bounds_fn,
) -> Tuple[float, float, float, float]:
    if active_work_area_bounds is not None:
        x0, x1, y0, y1 = active_work_area_bounds
        return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    return base_work_area_bounds_fn()


def configure_active_work_area(
    *,
    sheet_format: str,
    sheet_width_mm: Optional[float],
    sheet_height_mm: Optional[float],
    anchor: str,
    offset_x_mm: float,
    offset_y_mm: float,
    base_bounds: Tuple[float, float, float, float],
    sheet_presets_mm: Dict[str, Optional[Tuple[float, float]]],
    sheet_anchor_choices: Sequence[str],
    logger=print,
) -> Tuple[float, float, float, float]:
    base_min_x, base_max_x, base_min_y, base_max_y = base_bounds
    base_w = max(1e-9, base_max_x - base_min_x)
    base_h = max(1e-9, base_max_y - base_min_y)

    fmt = (sheet_format or "work").strip().lower()
    if fmt == "custom":
        if sheet_width_mm is None or sheet_height_mm is None:
            raise ValueError("--sheet-format custom requires --sheet-width-mm and --sheet-height-mm")
        target_w = float(sheet_width_mm)
        target_h = float(sheet_height_mm)
    elif fmt in sheet_presets_mm:
        preset = sheet_presets_mm[fmt]
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

    anc = (anchor or "center").strip().lower()
    if anc not in sheet_anchor_choices:
        raise ValueError(f"Unknown --sheet-anchor '{anchor}'.")

    if anc == "center":
        sheet_x0 = base_min_x + (base_w - target_w) * 0.5
        sheet_y0 = base_min_y + (base_h - target_h) * 0.5
    elif anc == "lower_left":
        sheet_x0 = base_min_x
        sheet_y0 = base_min_y
    elif anc == "upper_left":
        sheet_x0 = base_min_x
        sheet_y0 = base_max_y - target_h
    elif anc == "lower_right":
        sheet_x0 = base_max_x - target_w
        sheet_y0 = base_min_y
    else:  # upper_right
        sheet_x0 = base_max_x - target_w
        sheet_y0 = base_max_y - target_h

    sheet_x0 += float(offset_x_mm)
    sheet_y0 += float(offset_y_mm)
    sheet_x1 = sheet_x0 + target_w
    sheet_y1 = sheet_y0 + target_h

    x0 = max(base_min_x, sheet_x0)
    x1 = min(base_max_x, sheet_x1)
    y0 = max(base_min_y, sheet_y0)
    y1 = min(base_max_y, sheet_y1)
    active_w = max(0.0, x1 - x0)
    active_h = max(0.0, y1 - y0)

    if active_w <= 1e-6 or active_h <= 1e-6:
        raise ValueError(
            f"Sheet placement has no overlap with workspace: "
            f"sheet bounds x({sheet_x0:.3f},{sheet_x1:.3f}) y({sheet_y0:.3f},{sheet_y1:.3f})"
        )

    if logger:
        if target_w > base_w or target_h > base_h:
            logger(
                f"Sheet {target_w:.1f}x{target_h:.1f} mm is larger than workspace {base_w:.1f}x{base_h:.1f} mm. "
                "Using the overlapped sheet/workspace window."
            )
        elif (
            sheet_x0 < base_min_x
            or sheet_x1 > base_max_x
            or sheet_y0 < base_min_y
            or sheet_y1 > base_max_y
        ):
            logger("Sheet placement extends outside workspace. Using the overlapped sheet/workspace window.")
        logger(
            f"Active area: {active_w:.1f}x{active_h:.1f} mm, "
            f"bounds x({x0:.3f},{x1:.3f}) y({y0:.3f},{y1:.3f}), "
            f"sheet_bounds x({sheet_x0:.3f},{sheet_x1:.3f}) y({sheet_y0:.3f},{sheet_y1:.3f}), "
            f"sheet={fmt}, anchor={anc}, offset=({offset_x_mm:.2f},{offset_y_mm:.2f})"
        )

    return x0, x1, y0, y1
