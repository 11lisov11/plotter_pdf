from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional, Tuple

from src.plotter_backend.gcode.bounds import pen_down_from_z_level


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


def _g92_xy_reset_line(gcode_path: Path) -> int | None:
    try:
        raw_lines = Path(gcode_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line_no, raw in enumerate(raw_lines, 1):
        line = _strip_gcode_comments(raw)
        tokens = _TOKEN_RE.findall(line)
        has_g92 = False
        has_xy = False
        for axis, raw_value in tokens:
            letter = axis.upper()
            if letter in {"X", "Y"}:
                has_xy = True
                continue
            if letter != "G":
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if abs(value - 92.0) <= 1e-9:
                has_g92 = True
        if has_g92 and has_xy:
            return line_no
    return None


def _is_pen_down(z: float | None, z_up: float, z_down: float, spindle_down: bool) -> bool:
    if spindle_down:
        return True
    if z is None:
        return False
    return pen_down_from_z_level(float(z), float(z_up), float(z_down))


def _unsafe_pen_motion_problem(gcode_path: Path, *, z_up: float, z_down: float) -> str | None:
    try:
        raw_lines = Path(gcode_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None

    cur_z: float | None = None
    modal: int | None = None
    abs_mode = True
    spindle_down = False
    first_xy_seen = False

    for line_no, raw in enumerate(raw_lines, 1):
        line = _strip_gcode_comments(raw).strip()
        if not line:
            continue
        tokens = _TOKEN_RE.findall(line)
        if not tokens:
            continue

        g_values: list[float] = []
        z_values: list[float] = []
        has_xy = False
        for axis, raw_value in tokens:
            letter = axis.upper()
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if letter == "G":
                g_values.append(value)
            elif letter == "M":
                rounded = int(round(value))
                if abs(value - float(rounded)) <= 1e-9:
                    if rounded == 3:
                        spindle_down = True
                    elif rounded == 5:
                        spindle_down = False
            elif letter == "Z":
                z_values.append(value)
            elif letter in {"X", "Y"}:
                has_xy = True

        has_g92 = False
        for gval in g_values:
            if abs(gval - 90.0) <= 1e-9:
                abs_mode = True
                continue
            if abs(gval - 91.0) <= 1e-9:
                abs_mode = False
                continue
            rounded = int(round(gval))
            if abs(gval - float(rounded)) > 1e-9:
                continue
            if rounded in {0, 1, 2, 3}:
                modal = rounded
            elif rounded == 92:
                has_g92 = True

        was_down = _is_pen_down(cur_z, z_up, z_down, spindle_down)

        if has_g92:
            if z_values:
                cur_z = z_values[-1]
            continue

        next_z = cur_z
        if z_values:
            z_raw = z_values[-1]
            next_z = z_raw if (abs_mode or cur_z is None) else cur_z + z_raw
        would_be_down = _is_pen_down(next_z, z_up, z_down, spindle_down)

        if z_values and has_xy and not was_down and would_be_down:
            return f"line {line_no}: pen-down command also moves XY."
        if has_xy:
            if not first_xy_seen and would_be_down:
                return f"line {line_no}: first XY move happens with pen down."
            first_xy_seen = True
            if modal == 0 and (was_down or would_be_down):
                return f"line {line_no}: rapid XY travel with pen down."

        cur_z = next_z

    if _is_pen_down(cur_z, z_up, z_down, spindle_down):
        return "file ends with pen down."
    return None


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

    g92_xy_line = _g92_xy_reset_line(gcode_path)
    if g92_xy_line is not None:
        return False, f"G92 X/Y coordinate reset is not allowed (line {g92_xy_line})."

    unsafe_pen_motion = _unsafe_pen_motion_problem(gcode_path, z_up=float(z_up), z_down=float(z_down))
    if unsafe_pen_motion is not None:
        return False, unsafe_pen_motion

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

