import argparse
import math
import re
from pathlib import Path

from src.plotter_backend.gcode.bounds import pen_down_from_z_level
from src.plotter_backend.geometry.arc_fit import arc_center_from_radius


def _split_comment(line: str) -> str:
    s = line.strip()
    if not s:
        return ""
    if ";" in s:
        s = s.split(";", 1)[0].strip()
    out: list[str] = []
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip()


_G_RE = re.compile(r"\bG\d+(?:\.\d+)?\b", re.IGNORECASE)
_WORD_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


def _parse_words(body: str) -> dict:
    # Returns word map, e.g. {"X": 10.0, "Y": -5.0, "I": 1.2}
    out: dict[str, float] = {}
    for k_raw, v in _WORD_RE.findall(body):
        k = k_raw.upper()
        if k in {"G", "M"}:
            continue
        try:
            out[k] = float(v)
        except Exception:
            continue
    return out


def _arc_points(start, end, center, cw: bool, step_deg: float = 3.0):
    sx, sy = start
    ex, ey = end
    cx, cy = center
    r = math.hypot(sx - cx, sy - cy)
    if r <= 1e-9:
        return [end]
    a0 = math.atan2(sy - cy, sx - cx)
    a1 = math.atan2(ey - cy, ex - cx)

    # Unwrap according to direction.
    if cw:
        while a1 > a0:
            a1 -= 2.0 * math.pi
    else:
        while a1 < a0:
            a1 += 2.0 * math.pi

    sweep = a1 - a0
    step = math.radians(max(0.5, float(step_deg)))
    n = max(1, int(math.ceil(abs(sweep) / step)))
    pts = []
    for i in range(1, n + 1):
        t = a0 + sweep * (i / n)
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def gcode_to_polylines(lines: list[str], *, z_down: float | None = None, z_up: float | None = None):
    # Extract drawn polylines based on G codes + optional Z state.
    # If z_up/z_down provided: "pen down" when Z is closer to z_down than z_up.
    cur_x = 0.0
    cur_y = 0.0
    cur_z = 0.0
    abs_mode = True  # assume G90, but accept G91
    ijk_abs = False  # GRBL default is incremental IJK; we accept G90.1/G91.1
    # Motion is modal in G-code: persist last G0/G1/G2/G3 if not repeated.
    motion_mode = 0

    pen_down = False
    out: list[list[tuple[float, float]]] = []
    cur_poly: list[tuple[float, float]] = []

    def _update_pen_state():
        nonlocal pen_down
        if z_down is None or z_up is None:
            return
        # A bit tolerant: pick closest.
        if abs(cur_z - z_down) <= abs(cur_z - z_up):
            pen_down = True
        else:
            pen_down = False

    _update_pen_state()

    for raw in lines:
        body = _split_comment(raw)
        if not body:
            continue

        # Ignore $ commands and non-motion M codes.
        if body.startswith("$"):
            continue

        for m_raw in re.findall(r"M\s*(\d+(?:\.\d+)?)", body, flags=re.IGNORECASE):
            try:
                mval = int(round(float(m_raw)))
            except Exception:
                continue
            if mval == 3:
                pen_down = True
            elif mval == 5:
                if cur_poly and len(cur_poly) >= 2:
                    out.append(cur_poly)
                cur_poly = []
                pen_down = False

        # First, handle G modal changes and extract motion command, if any.
        motion_g = None
        coordinate_reset = False
        for gtok in _G_RE.findall(body):
            try:
                gval = float(gtok[1:])
            except Exception:
                continue
            if abs(gval - 90.0) <= 1e-6:
                abs_mode = True
            elif abs(gval - 91.0) <= 1e-6:
                abs_mode = False
            elif abs(gval - 90.1) <= 1e-6:
                ijk_abs = True
            elif abs(gval - 91.1) <= 1e-6:
                ijk_abs = False
            elif abs(gval - 92.0) <= 1e-6:
                coordinate_reset = True
            elif abs(gval - 0.0) <= 1e-6:
                motion_g = 0
            elif abs(gval - 1.0) <= 1e-6:
                motion_g = 1
            elif abs(gval - 2.0) <= 1e-6:
                motion_g = 2
            elif abs(gval - 3.0) <= 1e-6:
                motion_g = 3

        words = _parse_words(body)

        # Track Z even on non-draw.
        if "Z" in words:
            z = float(words["Z"])
            cur_z = z if abs_mode else (cur_z + z)
            if z_down is not None and z_up is not None:
                pen_down = pen_down_from_z_level(cur_z, float(z_up), float(z_down))

        if coordinate_reset:
            if cur_poly and len(cur_poly) >= 2:
                out.append(cur_poly)
            cur_poly = []
            if "X" in words:
                cur_x = float(words["X"])
            if "Y" in words:
                cur_y = float(words["Y"])
            if "Z" in words:
                cur_z = float(words["Z"])
                if z_down is not None and z_up is not None:
                    pen_down = pen_down_from_z_level(cur_z, float(z_up), float(z_down))
            continue

        if motion_g is not None:
            motion_mode = motion_g
        g = motion_mode

        # Determine target XY.
        tx = cur_x
        ty = cur_y
        if "X" in words:
            x = float(words["X"])
            tx = x if abs_mode else (cur_x + x)
        if "Y" in words:
            y = float(words["Y"])
            ty = y if abs_mode else (cur_y + y)

        start = (cur_x, cur_y)
        end = (tx, ty)

        is_draw_move = (g in (1, 2, 3)) and (("X" in words) or ("Y" in words))
        if z_down is None or z_up is None:
            # No Z context: assume G0 is travel, others are draw.
            is_pen_down_now = is_draw_move
        else:
            # With Z context: draw only if pen is down and XY changes.
            is_pen_down_now = pen_down and (("X" in words) or ("Y" in words))

        if is_pen_down_now:
            if not cur_poly:
                cur_poly = [start]
            if g in (2, 3) and (("I" in words) or ("J" in words)):
                i = float(words.get("I", 0.0))
                j = float(words.get("J", 0.0))
                center = (i, j) if ijk_abs else (cur_x + i, cur_y + j)
                pts = _arc_points(start, end, center, cw=(g == 2))
                cur_poly.extend(pts)
            elif g in (2, 3) and "R" in words:
                center = arc_center_from_radius(start, end, float(words["R"]), cw=(g == 2))
                if center is None:
                    cur_poly.append(end)
                else:
                    cur_poly.extend(_arc_points(start, end, center, cw=(g == 2)))
            else:
                cur_poly.append(end)
        else:
            if cur_poly and len(cur_poly) >= 2:
                out.append(cur_poly)
            cur_poly = []

        cur_x, cur_y = end

    if cur_poly and len(cur_poly) >= 2:
        out.append(cur_poly)
    return out


def bounds(polylines: list[list[tuple[float, float]]]):
    xs = [x for p in polylines for x, _ in p]
    ys = [y for p in polylines for _, y in p]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), max(xs), min(ys), max(ys))


def write_svg(polylines: list[list[tuple[float, float]]], out_path: Path, *, invert_y: bool = True, pad_mm: float = 2.0):
    x0, x1, y0, y1 = bounds(polylines)
    if invert_y:
        # Flip the Y axis to match a page-like coordinate system (downwards positive).
        flipped = [[(x, -y) for x, y in poly] for poly in polylines]
        polylines = flipped
        x0, x1, y0, y1 = bounds(polylines)

    w = max(1e-6, x1 - x0)
    h = max(1e-6, y1 - y0)
    pad = max(0.0, float(pad_mm))
    vb_x = x0 - pad
    vb_y = y0 - pad
    vb_w = w + 2 * pad
    vb_h = h + 2 * pad

    translate_y = -(y0 + y1)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"',
        f'     width="{vb_w:.3f}mm" height="{vb_h:.3f}mm" viewBox="{vb_x:.3f} {vb_y:.3f} {vb_w:.3f} {vb_h:.3f}">',
        # Invert Y by flipping around the midline; keeps text readable while mapping to page-like coords.
        f'  <g fill="none" stroke="#000" stroke-width="0.25" stroke-linecap="round" stroke-linejoin="round"'
        f' transform="scale(1,-1) translate(0,{translate_y:.4f})">',
    ]

    for poly in polylines:
        if len(poly) < 2:
            continue
        d = f"M {poly[0][0]:.4f} {poly[0][1]:.4f} "
        d += " ".join(f"L {x:.4f} {y:.4f}" for x, y in poly[1:])
        parts.append(f'    <path d="{d}" />')

    parts.append("  </g>")
    parts.append("</svg>\n")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render GRBL-ish G-code to an SVG preview (pen-down paths only).")
    ap.add_argument("input", help="Input .nc/.gcode file")
    ap.add_argument("-o", "--output", help="Output .svg file")
    ap.add_argument("--z-up", type=float, default=None, help="Optional: Z value for pen up (use with --z-down)")
    ap.add_argument("--z-down", type=float, default=None, help="Optional: Z value for pen down (use with --z-up)")
    ap.add_argument("--no-invert-y", action="store_true", help="Do not invert Y in SVG (keep G-code coordinates)")
    ap.add_argument("--pad-mm", type=float, default=2.0, help="Padding (mm) around drawing in viewBox")
    ns = ap.parse_args(argv[1:])

    in_path = Path(ns.input)
    if not in_path.exists():
        raise SystemExit(f"File not found: {in_path}")

    out_path = Path(ns.output) if ns.output else in_path.with_suffix(".svg")
    lines = in_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    polylines = gcode_to_polylines(lines, z_down=ns.z_down, z_up=ns.z_up)
    # SVG preview is for human inspection: invert Y so it looks like on paper.
    write_svg(polylines, out_path, invert_y=(not ns.no_invert_y), pad_mm=ns.pad_mm)
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv))
