from __future__ import annotations

from typing import List


def build_safe_park_release_commands(
    *,
    sleep: bool = False,
    release: bool = True,
    hold: bool = False,
    home: bool = True,
    home_x: float = 0.0,
    home_y: float = 0.0,
    z_up: float = 0.0,
    z_down: float | None = None,
    z_feed: float = 2500.0,
    force_lift_mm: float = 4.0,
    travel_feed: float = 15000.0,
    unlock: bool = True,
    energize_before_motion: bool = True,
) -> List[str]:
    """Return the canonical safe end/stop sequence for the plotter.

    Motors must stay energized while lifting and returning home. Only after the
    head is parked with the pen up do we release steppers with ``$1=0``.
    """
    commands: List[str] = []
    if unlock:
        commands.append("$X")
    if energize_before_motion:
        commands.append("$1=255")
    if z_down is not None:
        direction = 1.0 if float(z_down) >= float(z_up) else -1.0
        lift = min(abs(float(z_down) - float(z_up)), max(0.0, float(force_lift_mm)))
        commands.append(f"G92 Z{float(z_up) + direction * lift:.4f}")
    commands.extend(
        [
            "G90",
            f"G1 Z{float(z_up):.4f} F{float(z_feed):.1f}",
            "G4 P0.05",
            "M5",
        ]
    )
    if home:
        commands.extend(
            [
                f"G1 X{float(home_x):.4f} Y{float(home_y):.4f} F{float(travel_feed):.1f}",
                f"G1 Z{float(z_up):.4f} F{float(z_feed):.1f}",
                "G4 P0.05",
                "M5",
            ]
        )
    commands.append("$1=0" if sleep or (release and not hold) else "$1=255")
    if sleep:
        commands.append("$SLP")
    return commands


def safe_park_release_message(*, sleep: bool = False, release: bool = True, hold: bool = False) -> str:
    if sleep:
        return "Returned home; pen lifted; motors released ($1=0, $SLP)."
    if release and not hold:
        return "Returned home; pen lifted; motors released ($1=0)."
    return "Returned home; pen lifted; motors held ($1=255)."
