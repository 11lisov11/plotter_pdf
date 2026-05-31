import argparse
import math
import re
from pathlib import Path

GCODE_MOVES_WITH_XY = {"G0", "G1", "G2", "G3", "G5", "G80", "G81", "G82", "G83", "G84", "G85", "G86", "G87", "G88", "G89"}


def parse_args():
    parser = argparse.ArgumentParser(description="Add pen-lift logic to XY gcode.")
    parser.add_argument("input_file", help="Source gcode file")
    parser.add_argument("--output", "-o", help="Output gcode file")
    parser.add_argument(
        "--mode",
        choices=["z", "spindle"],
        default="z",
        help="Pen control mode: z (G0 Z) or spindle (M3/M5)",
    )
    parser.add_argument("--z-down", type=float, default=0.0, help="Z value for pen down")
    parser.add_argument("--z-up", type=float, default=0.0, help="Z value for pen up")
    parser.add_argument("--spindle-speed", type=float, default=1000.0, help="S value for M3")
    parser.add_argument("--delay", type=float, default=0.05, help="Seconds for G4 after pen switch")
    parser.add_argument("--delay-up", type=float, default=None, help="Seconds for G4 after pen up (defaults to --delay)")
    parser.add_argument("--z-feed-down-approach", type=float, default=700.0, help="Feed for approach before touchdown (mm/min)")
    parser.add_argument("--z-feed-down-touch", type=float, default=180.0, help="Feed for final pen touchdown (mm/min)")
    parser.add_argument("--z-feed-up", type=float, default=700.0, help="Feed for main pen lift (mm/min)")
    parser.add_argument("--z-feed-up-final", type=float, default=220.0, help="Feed for final near-top pen lift segment (mm/min)")
    parser.add_argument("--z-soft-down-mm", type=float, default=0.8, help="Last mm moved slowly before Z-down")
    parser.add_argument("--z-soft-up-mm", type=float, default=0.5, help="Last mm moved slowly before Z-up")
    parser.add_argument(
        "--z-travel-lift-mm",
        type=float,
        default=3.0,
        help="Inter-path lift distance from Z-down towards Z-up (mm). Full Z-up is still used at job end.",
    )
    parser.add_argument("--dynamic-z-enable", action="store_true", help="Adjust Z-down dynamically as draw length accumulates.")
    parser.add_argument("--dynamic-base-z-down", type=float, default=None, help="Base Z-down without wear compensation.")
    parser.add_argument("--dynamic-initial-wear-mm", type=float, default=0.0, help="Current estimated wear at job start (mm).")
    parser.add_argument("--dynamic-wear-mm-per-m", type=float, default=0.01, help="Estimated wear increase per drawn meter.")
    parser.add_argument("--dynamic-z-comp-per-wear", type=float, default=1.0, help="Extra Z mm per 1 mm estimated wear.")
    parser.add_argument("--dynamic-z-max-comp-mm", type=float, default=0.8, help="Maximum dynamic Z compensation (mm).")
    parser.add_argument("--stroke-z-jitter-enable", action="store_true", help="Add tiny deterministic per-stroke Z variation for pencil naturalness.")
    parser.add_argument("--stroke-z-jitter-mm", type=float, default=0.0, help="Amplitude of per-stroke Z jitter (mm).")
    parser.add_argument("--stroke-z-jitter-seed", type=int, default=173, help="Seed for deterministic per-stroke Z jitter.")
    parser.add_argument(
        "--merge-short-travel-enable",
        action="store_true",
        help="Keep pen down on very short G0 XY hops (useful for handwriting continuity).",
    )
    parser.add_argument("--merge-short-travel-mm", type=float, default=0.0, help="Max XY distance for short-travel merge.")
    parser.add_argument("--merge-short-travel-feed", type=float, default=2200.0, help="Feed for merged short travel moves.")
    return parser.parse_args()


def split_comment(line: str):
    if ";" in line:
        body, comment = line.split(";", 1)
        return body.rstrip(), ";" + comment
    if "(" in line:
        idx = line.find("(")
        return line[:idx].rstrip(), line[idx:]
    return line.rstrip("\n"), ""


def parse_tokens(body: str):
    return [t for t in body.strip().split() if t]


def first_gcode(tokens):
    for token in tokens:
        up = token.upper()
        if re.fullmatch(r"G\d+(?:\.\d+)?", up):
            return up
    return ""


def has_axis(tokens, axis):
    for token in tokens:
        up = token.upper()
        if up.startswith(axis):
            return True
    return False


def axis_value(tokens, axis):
    ax = axis.upper()
    for token in tokens:
        up = token.upper()
        if up.startswith(ax):
            try:
                return float(up[1:])
            except Exception:
                return None
    return None


def arc_length_xy(x0, y0, x1, y1, i, j, cw):
    try:
        cx = x0 + i
        cy = y0 + j
        r = math.hypot(x0 - cx, y0 - cy)
        if r <= 1e-9:
            return math.hypot(x1 - x0, y1 - y0)
        if math.hypot(x1 - x0, y1 - y0) <= 1e-9:
            return 2.0 * math.pi * r
        a0 = math.atan2(y0 - cy, x0 - cx)
        a1 = math.atan2(y1 - cy, x1 - cx)
        if cw:
            sweep = a0 - a1
            if sweep <= 0.0:
                sweep += 2.0 * math.pi
        else:
            sweep = a1 - a0
            if sweep <= 0.0:
                sweep += 2.0 * math.pi
        return abs(r * sweep)
    except Exception:
        return math.hypot(x1 - x0, y1 - y0)


def touch_pen_down(
    lines,
    z_down,
    delay_down,
    z_up,
    mode,
    spindle_speed,
    delay_up=None,
    z_feed_down_approach=700.0,
    z_feed_down_touch=180.0,
    z_feed_up=700.0,
    z_feed_up_final=220.0,
    z_soft_down_mm=0.8,
    z_soft_up_mm=0.5,
    z_travel_lift_mm=3.0,
    dynamic_z_enable=False,
    dynamic_base_z_down=None,
    dynamic_initial_wear_mm=0.0,
    dynamic_wear_mm_per_m=0.01,
    dynamic_z_comp_per_wear=1.0,
    dynamic_z_max_comp_mm=0.8,
    stroke_z_jitter_enable=False,
    stroke_z_jitter_mm=0.0,
    stroke_z_jitter_seed=173,
    merge_short_travel_enable=False,
    merge_short_travel_mm=0.0,
    merge_short_travel_feed=2200.0,
):
    out = []
    pen_down = False
    current_z = float(z_up)
    current_x = None
    current_y = None
    abs_mode = True
    drawn_length_mm = 0.0
    if delay_up is None:
        delay_up = delay_down

    z_feed_down_approach = max(1.0, float(z_feed_down_approach))
    z_feed_down_touch = max(1.0, float(z_feed_down_touch))
    z_feed_up = max(1.0, float(z_feed_up))
    z_feed_up_final = max(1.0, float(z_feed_up_final))
    z_soft_down_mm = max(0.0, float(z_soft_down_mm))
    z_soft_up_mm = max(0.0, float(z_soft_up_mm))
    z_travel_lift_mm = max(0.0, float(z_travel_lift_mm))
    dynamic_initial_wear_mm = max(0.0, float(dynamic_initial_wear_mm))
    dynamic_wear_mm_per_m = max(0.0, float(dynamic_wear_mm_per_m))
    dynamic_z_comp_per_wear = max(0.0, float(dynamic_z_comp_per_wear))
    dynamic_z_max_comp_mm = max(0.0, float(dynamic_z_max_comp_mm))
    stroke_z_jitter_mm = max(0.0, float(stroke_z_jitter_mm))
    stroke_z_jitter_enable = bool(stroke_z_jitter_enable and mode == "z" and stroke_z_jitter_mm > 0.0)
    stroke_seed = int(stroke_z_jitter_seed or 0)
    merge_short_travel_enable = bool(merge_short_travel_enable and float(merge_short_travel_mm) > 0.0)
    merge_short_travel_mm = max(0.0, float(merge_short_travel_mm))
    merge_short_travel_feed = max(1.0, float(merge_short_travel_feed))
    if dynamic_base_z_down is None:
        dynamic_base_z_down = float(z_down)
    else:
        dynamic_base_z_down = float(dynamic_base_z_down)
    dynamic_z_enable = bool(dynamic_z_enable and mode == "z")
    stroke_index = 0

    def _safe_float(text: str):
        try:
            return float(text)
        except Exception:
            return None

    def _dynamic_z_down(mm_drawn: float) -> float:
        if not dynamic_z_enable:
            return float(z_down)
        wear_now = dynamic_initial_wear_mm + (max(0.0, mm_drawn) / 1000.0) * dynamic_wear_mm_per_m
        comp = min(dynamic_z_max_comp_mm, wear_now * dynamic_z_comp_per_wear)
        return dynamic_base_z_down + comp

    def _stroke_z_offset(idx: int) -> float:
        # Deterministic pseudo-random offset per stroke.
        if not stroke_z_jitter_enable:
            return 0.0
        s = math.sin((idx + 1 + stroke_seed * 0.37) * 12.9898 + 78.233) * 43758.5453
        frac = s - math.floor(s)
        rnd = (frac * 2.0) - 1.0
        drift = math.sin((idx + 1 + stroke_seed * 0.11) * 0.43)
        return (0.72 * rnd + 0.28 * drift) * stroke_z_jitter_mm

    def _approach_target(start_z: float, target_z: float, soft_mm: float):
        dz = target_z - start_z
        if soft_mm <= 1e-9 or abs(dz) <= soft_mm + 1e-9:
            return None
        return target_z - math.copysign(soft_mm, dz)

    def _emit_z_linear(target_z: float, feed_mm_min: float):
        nonlocal current_z
        out.append(f"G1 Z{target_z:.4f} F{feed_mm_min:.1f}")
        current_z = float(target_z)

    def _travel_lift_target(start_z: float) -> float:
        # Lift only enough for XY travel to reduce cycle time.
        # Keep the target clamped between current Z and full-up.
        if abs(start_z - z_up) <= 1e-9:
            return float(z_up)
        if start_z > z_up:
            return max(float(z_up), float(start_z) - z_travel_lift_mm)
        return min(float(z_up), float(start_z) + z_travel_lift_mm)

    def add_pen_up():
        nonlocal pen_down, current_z
        if pen_down:
            if mode == "spindle":
                out.append("M5")
            else:
                start_z = current_z
                z_target = _travel_lift_target(start_z)
                z_pre = _approach_target(start_z, z_target, z_soft_up_mm)
                if z_pre is not None and abs(z_pre - start_z) > 1e-6:
                    _emit_z_linear(z_pre, z_feed_up)
                _emit_z_linear(z_target, z_feed_up_final)
            if delay_up > 0:
                out.append(f"G4 P{delay_up:.2f}")
            pen_down = False

    def add_pen_down(mm_drawn: float):
        nonlocal pen_down, current_z, stroke_index
        if not pen_down:
            stroke_index += 1
            if mode == "spindle":
                out.append(f"M3 S{spindle_speed:.0f}")
            else:
                z_target = _dynamic_z_down(mm_drawn)
                if stroke_z_jitter_enable:
                    z_target += _stroke_z_offset(stroke_index)
                    # Keep jitter in a safe range around the current dynamic baseline.
                    base_now = _dynamic_z_down(mm_drawn)
                    if z_down >= z_up:
                        z_target = max(z_up + 0.03, z_target)
                        z_target = min(z_target, base_now + stroke_z_jitter_mm)
                    else:
                        z_target = min(z_up - 0.03, z_target)
                        z_target = max(z_target, base_now - stroke_z_jitter_mm)
                start_z = current_z
                z_pre = _approach_target(start_z, z_target, z_soft_down_mm)
                if z_pre is not None and abs(z_pre - start_z) > 1e-6:
                    _emit_z_linear(z_pre, z_feed_down_approach)
                _emit_z_linear(z_target, z_feed_down_touch)
            if delay_down > 0:
                out.append(f"G4 P{delay_down:.2f}")
            pen_down = True

    for line in lines:
        raw = line.rstrip("\n")
        body, comment = split_comment(raw)

        if not body.strip() or body.lstrip().startswith("("):
            out.append(raw)
            continue

        tokens = parse_tokens(body)
        if not tokens:
            out.append(raw)
            continue

        code = first_gcode(tokens)
        if not code:
            out.append(raw)
            continue

        if code == "G90":
            abs_mode = True
            out.append(raw)
            continue
        if code == "G91":
            abs_mode = False
            out.append(raw)
            continue

        xy_move = (code in GCODE_MOVES_WITH_XY) and (has_axis(tokens, "X") or has_axis(tokens, "Y"))
        z_move_only = (code in GCODE_MOVES_WITH_XY) and has_axis(tokens, "Z") and not (has_axis(tokens, "X") or has_axis(tokens, "Y"))

        if z_move_only:
            # Keep user-defined Z moves; synchronize internal state by value.
            for token in tokens:
                up = token.upper()
                if up.startswith("Z"):
                    value = _safe_float(up[1:])
                    if value is None:
                        continue
                    current_z = float(value)
                    if abs(value - z_up) < 1e-6:
                        pen_down = False
                    elif abs(value - z_down) < 1e-6:
                        pen_down = True
                    break
            out.append(raw)
            continue

        if code.startswith("G0"):
            if xy_move:
                x0, y0 = current_x, current_y
                x_tok = axis_value(tokens, "X")
                y_tok = axis_value(tokens, "Y")
                x1 = x_tok if (x_tok is not None and (abs_mode or current_x is None)) else (current_x + x_tok if x_tok is not None and current_x is not None else current_x)
                y1 = y_tok if (y_tok is not None and (abs_mode or current_y is None)) else (current_y + y_tok if y_tok is not None and current_y is not None else current_y)
                short_merge = False
                if (
                    merge_short_travel_enable
                    and pen_down
                    and x0 is not None
                    and y0 is not None
                    and x1 is not None
                    and y1 is not None
                ):
                    dxy = math.hypot(x1 - x0, y1 - y0)
                    short_merge = dxy <= merge_short_travel_mm
                if short_merge:
                    xy_tokens = []
                    for token in tokens:
                        up = token.upper()
                        if up.startswith("X") or up.startswith("Y"):
                            xy_tokens.append(token)
                    if xy_tokens:
                        merged = " ".join(["G1", *xy_tokens, f"F{merge_short_travel_feed:.1f}"]).strip()
                        if comment:
                            merged = f"{merged} {comment}"
                        out.append(merged)
                    else:
                        out.append(raw)
                    if x0 is not None and y0 is not None and x1 is not None and y1 is not None:
                        drawn_length_mm += max(0.0, math.hypot(x1 - x0, y1 - y0))
                    current_x, current_y = x1, y1
                    continue

                add_pen_up()
                current_x, current_y = x1, y1
            out.append(raw)
            continue

        if code.startswith("G1") and xy_move:
            x0, y0 = current_x, current_y
            x_tok = axis_value(tokens, "X")
            y_tok = axis_value(tokens, "Y")
            x1 = x_tok if (x_tok is not None and (abs_mode or current_x is None)) else (current_x + x_tok if x_tok is not None and current_x is not None else current_x)
            y1 = y_tok if (y_tok is not None and (abs_mode or current_y is None)) else (current_y + y_tok if y_tok is not None and current_y is not None else current_y)
            add_pen_down(drawn_length_mm)
            out.append(raw)
            if x0 is not None and y0 is not None and x1 is not None and y1 is not None:
                drawn_length_mm += max(0.0, math.hypot(x1 - x0, y1 - y0))
            current_x, current_y = x1, y1
            continue

        if code in {"G2", "G3"} and xy_move:
            x0, y0 = current_x, current_y
            x_tok = axis_value(tokens, "X")
            y_tok = axis_value(tokens, "Y")
            i_tok = axis_value(tokens, "I")
            j_tok = axis_value(tokens, "J")
            x1 = x_tok if (x_tok is not None and (abs_mode or current_x is None)) else (current_x + x_tok if x_tok is not None and current_x is not None else current_x)
            y1 = y_tok if (y_tok is not None and (abs_mode or current_y is None)) else (current_y + y_tok if y_tok is not None and current_y is not None else current_y)
            add_pen_down(drawn_length_mm)
            out.append(raw)
            if x0 is not None and y0 is not None and x1 is not None and y1 is not None:
                if i_tok is not None and j_tok is not None:
                    drawn_length_mm += max(0.0, arc_length_xy(x0, y0, x1, y1, i_tok, j_tok, cw=(code == "G2")))
                else:
                    drawn_length_mm += max(0.0, math.hypot(x1 - x0, y1 - y0))
            current_x, current_y = x1, y1
            continue

        out.append(raw)

    if pen_down:
        if mode == "spindle":
            out.append("M5")
        else:
            start_z = current_z
            z_pre = _approach_target(start_z, z_up, z_soft_up_mm)
            if z_pre is not None and abs(z_pre - start_z) > 1e-6:
                _emit_z_linear(z_pre, z_feed_up)
            _emit_z_linear(z_up, z_feed_up_final)
        if delay_up > 0:
            out.append(f"G4 P{delay_up:.2f}")

    return out


if __name__ == "__main__":
    args = parse_args()
    input_path = Path(args.input_file)
    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_pen{input_path.suffix}")

    raw_lines = input_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    processed = touch_pen_down(
        raw_lines,
        args.z_down,
        args.delay,
        args.z_up,
        args.mode,
        args.spindle_speed,
        args.delay_up,
        args.z_feed_down_approach,
        args.z_feed_down_touch,
        args.z_feed_up,
        args.z_feed_up_final,
        args.z_soft_down_mm,
        args.z_soft_up_mm,
        args.z_travel_lift_mm,
        args.dynamic_z_enable,
        args.dynamic_base_z_down,
        args.dynamic_initial_wear_mm,
        args.dynamic_wear_mm_per_m,
        args.dynamic_z_comp_per_wear,
        args.dynamic_z_max_comp_mm,
        args.stroke_z_jitter_enable,
        args.stroke_z_jitter_mm,
        args.stroke_z_jitter_seed,
        args.merge_short_travel_enable,
        args.merge_short_travel_mm,
        args.merge_short_travel_feed,
    )
    output_path.write_text("\n".join(processed) + "\n", encoding="utf-8")
    print(f"saved: {output_path}")
