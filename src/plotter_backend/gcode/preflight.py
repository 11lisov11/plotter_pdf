from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional, Tuple


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
    travel_bounds: Optional[Tuple[float, float, float, float]] = None,
    home_corridor_y_mm: Optional[float] = None,
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

    margin = max(0.0, float(preflight_bounds_margin_mm))
    gx0, gx1, gy0, gy1 = g_bounds
    min_x, max_x, min_y, max_y = bounds if bounds is not None else work_area_bounds()

    try:
        draw_bounds = gcode_draw_bounds(gcode_path, float(z_up), float(z_down))
    except Exception as exc:
        return False, f"cannot determine pen-down drawing bounds: {exc}"
    if draw_bounds is None:
        body = gcode_path.read_text(encoding="utf-8", errors="ignore")
        has_explicit_spindle_pen = re.search(r"(?i)(?<![A-Z0-9.])M0?[35](?![0-9.])", body) is not None
        if has_explicit_spindle_pen:
            return False, "no pen-down drawing moves."
        logger(
            "Preflight warning: no explicit pen-down command was found; "
            "using legacy G1/G2/G3 drawing semantics."
        )
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

    travel_min_x, travel_max_x, travel_min_y, travel_max_y = (
        travel_bounds if travel_bounds is not None else (bounds if bounds is not None else work_area_bounds())
    )
    gx0, gx1, gy0, gy1 = g_bounds
    if (
        gx0 < (travel_min_x - margin)
        or gx1 > (travel_max_x + margin)
        or gy0 < (travel_min_y - margin)
        or gy1 > (travel_max_y + margin)
    ):
        return (
            False,
            "motion exceeds machine travel area: "
            f"gcode x({gx0:.3f},{gx1:.3f}) y({gy0:.3f},{gy1:.3f}) vs "
            f"machine x({travel_min_x:.3f},{travel_max_x:.3f}) "
            f"y({travel_min_y:.3f},{travel_max_y:.3f}) (margin {margin:.3f}).",
        )

    if home_corridor_y_mm is not None:
        x = y = 0.0
        absolute = True
        motion = None
        word_re = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.IGNORECASE)
        with gcode_path.open("r", encoding="utf-8", errors="ignore") as source:
            for line_number, raw in enumerate(source, 1):
                line = re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0])
                words = [(letter.upper(), float(value)) for letter, value in word_re.findall(line)]
                g_codes = [value for letter, value in words if letter == "G"]
                if any(abs(value - 90.0) < 1e-6 for value in g_codes):
                    absolute = True
                if any(abs(value - 91.0) < 1e-6 for value in g_codes):
                    absolute = False
                if any(abs(value - 92.0) < 1e-6 for value in g_codes):
                    if any(letter in {"X", "Y"} for letter, _ in words):
                        return False, f"unsafe XY coordinate reset at line {line_number}."
                    continue
                for value in g_codes:
                    if int(value) in {0, 1, 2, 3}:
                        motion = int(value)
                values = {letter: value for letter, value in words}
                if motion not in {0, 1, 2, 3} or ("X" not in values and "Y" not in values):
                    continue
                next_x = (values["X"] if absolute else x + values["X"]) if "X" in values else x
                next_y = (values["Y"] if absolute else y + values["Y"]) if "Y" in values else y
                if min(y, next_y) < float(home_corridor_y_mm) - 1e-6 and max(x, next_x) > 1e-6:
                    return False, (
                        f"motion crosses the home clamp corridor at line {line_number}: "
                        f"({x:.3f},{y:.3f})->({next_x:.3f},{next_y:.3f}), "
                        f"required Y>={float(home_corridor_y_mm):.3f} whenever X>0."
                    )
                x, y = next_x, next_y

    return (
        True,
        f"ok: lines={lines}, draw={draw_moves}, travel={travel_moves}, ratio={ratio:.2f}",
    )

