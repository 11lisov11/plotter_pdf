from __future__ import annotations

import math
from typing import Dict, Optional, Tuple


def plan_tiled_passes_for_sheet(
    sheet_w_mm: float,
    sheet_h_mm: float,
    *,
    area_w_mm: float,
    area_h_mm: float,
) -> dict:
    area_w = max(1e-9, float(area_w_mm))
    area_h = max(1e-9, float(area_h_mm))

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
    sheet_presets_mm: Dict[str, Optional[Tuple[float, float]]],
    work_area_size_mm: Optional[Tuple[float, float]] = None,
) -> Tuple[float, float]:
    fmt = (sheet_format or "work").strip().lower()
    if fmt == "custom":
        if sheet_width_mm is None or sheet_height_mm is None:
            raise ValueError("--sheet-format custom requires --sheet-width-mm and --sheet-height-mm")
        return float(sheet_width_mm), float(sheet_height_mm)
    if fmt in sheet_presets_mm:
        preset = sheet_presets_mm[fmt]
        if preset is None:
            if work_area_size_mm is None:
                raise ValueError("work area size is required for sheet format mapped to active area")
            return float(work_area_size_mm[0]), float(work_area_size_mm[1])
        w, h = preset
        if sheet_width_mm is not None:
            w = float(sheet_width_mm)
        if sheet_height_mm is not None:
            h = float(sheet_height_mm)
        return float(w), float(h)
    raise ValueError(f"Unknown --sheet-format '{sheet_format}'.")


def tile_window_start(total_mm: float, window_mm: float, idx0: int, count: int) -> float:
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
    *,
    pass_cols: int,
    pass_rows: int,
    pass_col: int,
    pass_row: int,
) -> Tuple[float, float, dict]:
    cols = max(1, int(pass_cols))
    rows = max(1, int(pass_rows))
    col = min(max(1, int(pass_col)), cols)
    row = min(max(1, int(pass_row)), rows)

    w = max(1e-9, float(source_w_mm))
    h = max(1e-9, float(source_h_mm))
    win_w = min(max(1e-9, float(window_w_mm)), w)
    win_h = min(max(1e-9, float(window_h_mm)), h)

    sx = tile_window_start(w, win_w, col - 1, cols)
    sy = tile_window_start(h, win_h, row - 1, rows)

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

