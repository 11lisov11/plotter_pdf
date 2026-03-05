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
) -> None:
    lines = [
        "$X",
        # Hold steppers while a job is running (prevents Z from back-driving).
        "$1=255",
        "G21",
        "G90",
        f"G0 Z{float(z_up):.4f} F{float(safe_lift_feed):.1f}",
        f"G4 P{float(z_delay_up):.2f}",
        f"G92 Z{float(z_up):.4f}",
        f"G0 Z{float(z_up):.4f} F{float(safe_lift_feed):.1f}",
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
        "$1=0",
    ]
    final_gcode.write_text("\n".join(lines) + g + "\n".join(trailer) + "\n", encoding="utf-8")

