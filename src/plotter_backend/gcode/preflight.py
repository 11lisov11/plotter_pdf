from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional, Tuple


_TOKEN_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


def _strip_gcode_comments(line: str) -> str:
    raw = str(line or "").split(";", 1)[0]
    out: list[str] = []
    depth = 0
    for ch in raw:
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def _has_explicit_pen_control(gcode_path: Path) -> bool:
    try:
        raw_lines = Path(gcode_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return True
    for raw in raw_lines:
        line = _strip_gcode_comments(raw)
        tokens = _TOKEN_RE.findall(line)
        for axis, raw_value in tokens:
            letter = axis.upper()
            if letter == "Z":
                return True
            if letter != "M":
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            rounded = int(round(value))
            if abs(value - float(rounded)) <= 1e-9 and rounded in {3, 5}:
                return True
    return False


def preflight_check_gcode(
    gcode_path: Path,
    logger,
    *,
    preflight_enabled: bool,
    preflight_max_gcode_lines: int,
    preflight_max_travel_to_draw_ratio: float,
    preflight_bounds_margin_mm: float,
    z_up: float,
    z_down: float,
    bounds: Optional[Tuple[float, float, float, float]],
    work_area_bounds: Callable[[], Tuple[float, float, float, float]],
    summarize_gcode_file: Callable[[Path], Tuple[int, int, int, Tuple[float, float, float, float]]],
    gcode_draw_bounds: Callable[[Path, float, float], Optional[Tuple[float, float, float, float]]],
) -> Tuple[bool, str]:
    if not bool(preflight_enabled):
        return True, "disabled"

    lines, draw_moves, travel_moves, g_bounds = summarize_gcode_file(gcode_path)
    if lines <= 0:
        return False, "empty or invalid G-code."
    if draw_moves <= 0:
        return False, "no drawing moves (G1/G2/G3)."
    if lines > int(preflight_max_gcode_lines):
        return False, f"too many G-code lines: {lines} > {int(preflight_max_gcode_lines)}."

    ratio = float(travel_moves) / max(1.0, float(draw_moves))
    if ratio > float(preflight_max_travel_to_draw_ratio):
        logger(
            "Preflight warning: high travel ratio "
            f"{ratio:.2f} (travel={travel_moves}, draw={draw_moves}). "
            "Trajectory may be inefficient."
        )

    min_x, max_x, min_y, max_y = bounds if bounds is not None else work_area_bounds()
    margin = max(0.0, float(preflight_bounds_margin_mm))
    gx0, gx1, gy0, gy1 = g_bounds

    draw_bounds = None
    try:
        draw_bounds = gcode_draw_bounds(gcode_path, float(z_up), float(z_down))
    except Exception as exc:
        return False, f"cannot compute pen-down draw bounds ({type(exc).__name__}: {exc})."
    if draw_bounds is None:
        if _has_explicit_pen_control(gcode_path):
            return False, "no pen-down drawing bounds."
    else:
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

