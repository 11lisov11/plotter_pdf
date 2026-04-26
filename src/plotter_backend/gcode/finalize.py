from __future__ import annotations

from pathlib import Path


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
    release_steppers_after_draw: bool = False,
    startup_force_z_lift_mm: float = 0.0,
) -> None:
    z_up_v = float(z_up)
    lift_mm = max(0.0, float(startup_force_z_lift_mm))
    forced_lift_lines = []
    if lift_mm > 1e-9:
        # If Z back-drove while steppers were off, GRBL may still believe it is
        # at Z_UP. Rebase the current coordinate above Z_UP and command a real
        # upward move before the first XY travel.
        forced_lift_lines = [
            f"G92 Z{z_up_v + lift_mm:.4f}",
            f"G0 Z{z_up_v:.4f} F{float(safe_lift_feed):.1f}",
            f"G4 P{float(z_delay_up):.2f}",
            f"G92 Z{z_up_v:.4f}",
        ]

    lines = [
        "$X",
        # Hold steppers while a job is running (prevents Z from back-driving).
        "$1=255",
        "G21",
        "G90",
        *forced_lift_lines,
        f"G0 Z{z_up_v:.4f} F{float(safe_lift_feed):.1f}",
        f"G4 P{float(z_delay_up):.2f}",
        f"G92 Z{z_up_v:.4f}",
        (
            f"G0 X{float(home_x):.4f} Y{float(home_y):.4f} F{float(feed_travel):.1f}"
            if bool(go_home_before_draw)
            else ""
        ),
        "",
    ]
    g = prepared_gcode.read_text(encoding="utf-8", errors="ignore")
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
    if bool(release_steppers_after_draw):
        trailer.append("$1=0")
    final_gcode.write_text("\n".join(lines) + g + "\n".join(trailer) + "\n", encoding="utf-8")

