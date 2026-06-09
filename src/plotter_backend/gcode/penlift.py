from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from ..errors import ConversionError


def run_penlift_postprocess(
    xy_gcode: Path,
    pen_gcode: Path,
    *,
    python_executable: str,
    script_path: Path,
    z_down: float,
    z_up: float,
    pen_lift_mode: str,
    pen_spindle_speed: int,
    z_delay_down: float,
    z_delay_up: float,
    z_feed_down_approach: float,
    z_feed_down_touch: float,
    z_feed_up: float,
    z_feed_up_final: float,
    z_soft_down_mm: float,
    z_soft_up_mm: float,
    z_travel_lift_mm: float,
    dynamic_z_enable: bool,
    dynamic_base_z_down: Optional[float],
    dynamic_initial_wear_mm: float,
    dynamic_wear_mm_per_m: float,
    dynamic_z_comp_per_wear: float,
    dynamic_z_max_comp_mm: float,
    stroke_z_jitter_enable: bool,
    stroke_z_jitter_mm: float,
    stroke_z_jitter_seed: int,
    merge_short_travel_enable: bool,
    merge_short_travel_mm: float,
    merge_short_travel_feed: float,
    run_cmd: Callable[[Sequence[str]], Tuple[int, str, str]],
) -> None:
    cmd = [
        str(python_executable),
        str(script_path),
        str(xy_gcode),
        "--output",
        str(pen_gcode),
        "--z-down",
        f"{float(z_down):.3f}",
        "--z-up",
        f"{float(z_up):.4f}",
        "--mode",
        str(pen_lift_mode),
        "--spindle-speed",
        str(int(pen_spindle_speed)),
        "--delay",
        f"{float(z_delay_down):.2f}",
        "--delay-up",
        f"{float(z_delay_up):.2f}",
        "--z-feed-down-approach",
        f"{float(z_feed_down_approach):.1f}",
        "--z-feed-down-touch",
        f"{float(z_feed_down_touch):.1f}",
        "--z-feed-up",
        f"{float(z_feed_up):.1f}",
        "--z-feed-up-final",
        f"{float(z_feed_up_final):.1f}",
        "--z-soft-down-mm",
        f"{float(z_soft_down_mm):.3f}",
        "--z-soft-up-mm",
        f"{float(z_soft_up_mm):.3f}",
        "--z-travel-lift-mm",
        f"{float(z_travel_lift_mm):.3f}",
    ]
    if bool(dynamic_z_enable):
        base_z = float(z_down) if dynamic_base_z_down is None else float(dynamic_base_z_down)
        cmd.extend(
            [
                "--dynamic-z-enable",
                "--dynamic-base-z-down",
                f"{base_z:.4f}",
                "--dynamic-initial-wear-mm",
                f"{max(0.0, float(dynamic_initial_wear_mm)):.6f}",
                "--dynamic-wear-mm-per-m",
                f"{max(0.0, float(dynamic_wear_mm_per_m)):.6f}",
                "--dynamic-z-comp-per-wear",
                f"{max(0.0, float(dynamic_z_comp_per_wear)):.6f}",
                "--dynamic-z-max-comp-mm",
                f"{max(0.0, float(dynamic_z_max_comp_mm)):.6f}",
            ]
        )
        if bool(stroke_z_jitter_enable):
            cmd.extend(
                [
                    "--stroke-z-jitter-enable",
                    "--stroke-z-jitter-mm",
                    f"{max(0.0, float(stroke_z_jitter_mm)):.6f}",
                    "--stroke-z-jitter-seed",
                    str(int(stroke_z_jitter_seed)),
                ]
            )
    if bool(merge_short_travel_enable):
        cmd.extend(
            [
                "--merge-short-travel-enable",
                "--merge-short-travel-mm",
                f"{max(0.0, float(merge_short_travel_mm)):.3f}",
                "--merge-short-travel-feed",
                f"{max(1.0, float(merge_short_travel_feed)):.1f}",
            ]
        )

    if getattr(sys, "frozen", False):
        try:
            from src import penlift_postprocess

            result = penlift_postprocess.main(cmd[2:])
        except SystemExit as exc:
            result = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:
            raise ConversionError(f"PenLift postprocess failed: {type(exc).__name__}: {exc}") from exc
        if result not in (None, 0):
            raise ConversionError(f"PenLift postprocess failed: exit code {result}")
        return

    rc, out, err = run_cmd(cmd)
    if int(rc) != 0:
        detail = (str(err or "").strip() or str(out or "").strip() or f"rc={int(rc)}")
        raise ConversionError(f"PenLift postprocess failed: {detail}")

