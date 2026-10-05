from __future__ import annotations

import re
from pathlib import Path


_WORD_RE = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.IGNORECASE)


def _words(line: str) -> list[tuple[str, float]]:
    command = re.sub(r"\([^)]*\)", "", line.split(";", 1)[0])
    return [(letter.upper(), float(value)) for letter, value in _WORD_RE.findall(command)]


def _xy_position(lines: list[str], x: float, y: float) -> tuple[float, float]:
    for line in lines:
        words = _words(line)
        if any(letter == "G" and abs(value - 91.0) < 1e-6 for letter, value in words):
            raise ValueError("A2 safe-home routing requires absolute XY coordinates.")
        if any(letter == "G" and abs(value - 92.0) < 1e-6 for letter, value in words) and any(
            letter in {"X", "Y"} for letter, _ in words
        ):
            raise ValueError("A2 safe-home routing cannot follow a G92 XY reset.")
        for letter, value in words:
            if letter == "X":
                x = value
            elif letter == "Y":
                y = value
    return x, y


def _route_around_home_clamps(
    body: str,
    *,
    z_up: float,
    z_down: float,
    home_x: float,
    home_y: float,
    safe_y: float,
    feed_travel: float,
) -> str:
    lines = body.splitlines()
    threshold = (z_up + z_down) * 0.5
    down_lines = [
        index
        for index, line in enumerate(lines)
        if any(letter == "Z" and value < threshold for letter, value in _words(line))
    ]
    if not down_lines:
        raise ValueError("A2 job has no pen-down command.")
    first_down, last_down = down_lines[0], down_lines[-1]
    last_up = next(
        (
            index
            for index in range(last_down + 1, len(lines))
            if any(letter == "Z" and value >= z_up - 0.05 for letter, value in _words(lines[index]))
        ),
        None,
    )
    if last_up is None:
        raise ValueError("A2 job does not lift the pen after its last stroke.")

    first_x, first_y = _xy_position(lines[:first_down], home_x, home_y)
    last_x, last_y = _xy_position(lines[first_down:last_up + 1], first_x, first_y)
    if first_y < safe_y - 1e-6 or last_y < safe_y - 1e-6:
        raise ValueError("A2 drawing starts or ends inside the home clamp corridor.")
    before = [line for line in lines[:first_down] if not any(axis in {"X", "Y"} for axis, _ in _words(line))]
    after = [line for line in lines[last_up + 1:] if not any(axis in {"X", "Y"} for axis, _ in _words(line))]
    travel = f"F{feed_travel:.1f}"
    return "\n".join([
        *before,
        f"G1 X{home_x:.4f} Y{safe_y:.4f} {travel}",
        f"G1 X{first_x:.4f} Y{first_y:.4f} {travel}",
        *lines[first_down:last_up + 1],
        f"G1 X{home_x:.4f} Y{last_y:.4f} {travel}",
        f"G1 X{home_x:.4f} Y{home_y:.4f} {travel}",
        *after,
    ]) + "\n"


def make_final_with_preamble(
    prepared_gcode: Path,
    final_gcode: Path,
    *,
    z_up: float,
    safe_lift_feed: float,
    z_delay_up: float,
    home_x: float,
    home_y: float,
    feed_travel: float,
    go_home_before_draw: bool,
    go_home_after_draw: bool,
    z_down: float | None = None,
    startup_force_z_lift_mm: float = 4.0,
    hold_steppers_during_job: bool = True,
    release_steppers_after_draw: bool = False,
    home_clearance_y_mm: float | None = None,
) -> None:
    forced_lift = max(0.0, float(startup_force_z_lift_mm))
    # Some plotters lower the pen towards positive Z, while the A2 CoreXY kit
    # lowers it towards negative Z.  The forced startup lift must move away
    # from paper in both coordinate systems.
    down_direction = 1.0 if z_down is None or float(z_down) >= float(z_up) else -1.0
    startup_z = float(z_up) + down_direction * forced_lift
    lines = ["$X"]
    if hold_steppers_during_job:
        # Classic GRBL only. FluidNC uses $ME/$MD in the serial sender.
        lines.append("$1=255")
    lines.extend([
        "G21",
        "G90",
        # The controller's remembered Z work coordinate can be stale after an
        # abort/reset. Force the current physical pen position to be below Z_UP,
        # then lift before any XY move.
        *([f"G92 Z{startup_z:.4f}"] if forced_lift > 0.0 else []),
        f"G0 Z{float(z_up):.4f} F{float(safe_lift_feed):.1f}",
        f"G4 P{float(z_delay_up):.2f}",
        *([f"G92 Z{float(z_up):.4f}"] if forced_lift > 0.0 else []),
        f"G0 Z{float(z_up):.4f} F{float(safe_lift_feed):.1f}",
        (
            f"G0 X{float(home_x):.4f} Y{float(home_y):.4f} F{float(feed_travel):.1f}"
            if bool(go_home_before_draw)
            else ""
        ),
        "",
    ])
    g = prepared_gcode.read_text(encoding="utf-8", errors="ignore")
    if home_clearance_y_mm is not None:
        g = _route_around_home_clamps(
            g,
            z_up=float(z_up),
            z_down=float(z_down),
            home_x=float(home_x),
            home_y=float(home_y),
            safe_y=float(home_clearance_y_mm),
            feed_travel=float(feed_travel),
        )
    trailer = [
        "",
        f"G0 Z{float(z_up):.4f} F{float(safe_lift_feed):.1f}",
        f"G4 P{float(z_delay_up):.2f}",
        (
            f"G0 X{float(home_x):.4f} Y{float(home_y):.4f} F{float(feed_travel):.1f}"
            if bool(go_home_after_draw)
            else ""
        ),
        "M5",
        "G4 P0.10",
    ]
    if release_steppers_after_draw:
        trailer.append("$1=0")
    final_gcode.write_text("\n".join(lines) + g + "\n".join(trailer) + "\n", encoding="utf-8")

