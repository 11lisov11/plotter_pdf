import argparse
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


def touch_pen_down(lines, z_down, delay, z_up, mode, spindle_speed):
    out = []
    pen_down = False

    def add_pen_up():
        nonlocal pen_down
        if pen_down:
            if mode == "spindle":
                out.append("M5")
            else:
                out.append(f"G0 Z{z_up:.4f}")
            if delay > 0:
                out.append(f"G4 P{delay:.2f}")
            pen_down = False

    def add_pen_down():
        nonlocal pen_down
        if not pen_down:
            if mode == "spindle":
                out.append(f"M3 S{spindle_speed:.0f}")
            else:
                out.append(f"G0 Z{z_down:.4f}")
            if delay > 0:
                out.append(f"G4 P{delay:.2f}")
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

        xy_move = (code in GCODE_MOVES_WITH_XY) and (has_axis(tokens, "X") or has_axis(tokens, "Y"))
        z_move_only = (code in GCODE_MOVES_WITH_XY) and has_axis(tokens, "Z") and not (has_axis(tokens, "X") or has_axis(tokens, "Y"))

        if z_move_only:
            # Keep user-defined Z moves; synchronize internal state by value.
            for token in tokens:
                up = token.upper()
                if up.startswith("Z"):
                    value = float(up[1:])
                    if abs(value - z_up) < 1e-6:
                        pen_down = False
                    elif abs(value - z_down) < 1e-6:
                        pen_down = True
                    break
            out.append(raw)
            continue

        if code.startswith("G0"):
            if xy_move:
                add_pen_up()
            out.append(raw)
            continue

        if code.startswith("G1") and xy_move:
            add_pen_down()
            out.append(raw)
            continue

        if code in {"G2", "G3"} and xy_move:
            add_pen_down()
            out.append(raw)
            continue

        out.append(raw)

    if pen_down:
        if mode == "spindle":
            out.append("M5")
        else:
            out.append(f"G0 Z{z_up:.4f}")
        if delay > 0:
            out.append(f"G4 P{delay:.2f}")

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
    )
    output_path.write_text("\n".join(processed) + "\n", encoding="utf-8")
    print(f"saved: {output_path}")
