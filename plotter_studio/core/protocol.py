from __future__ import annotations

import importlib.util
import math
import re
import shutil
import sys
import tempfile
import threading
from xml.etree import ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from serial.tools import list_ports

from .serial_worker import OperationContext

try:
    from src.plotter_backend.errors import ToolDependencyError
except Exception:  # pragma: no cover - fallback for non-package layouts
    try:
        from plotter_backend.errors import ToolDependencyError  # type: ignore
    except Exception:  # pragma: no cover - defensive fallback
        class ToolDependencyError(RuntimeError):
            pass

try:
    import fitz  # type: ignore
except Exception:
    fitz = None


LogFn = Callable[[str], None]


@dataclass
class SheetConfig:
    sheet_format: str = "a4"  # work | a4 | a3 | notebook | custom
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    anchor: str = "lower_left"
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    pass_cols: int = 1
    pass_rows: int = 1
    pass_col: int = 1
    pass_row: int = 1


def _format_user_exception(exc: Exception, *, prefix: str = "") -> str:
    base = f"{type(exc).__name__}: {exc}"
    if prefix:
        return f"{prefix} ({base})"
    return base


def normalize_render_mode(mode: Optional[str]) -> str:
    value = (mode or "").strip().lower()
    return value if value in {"drawing", "handwriting"} else "drawing"


def resolve_render_flags(
    render_mode: Optional[str],
    *,
    exact_geometry_mode: bool,
    handwriting_enabled: bool,
) -> tuple[str, bool, bool]:
    mode = normalize_render_mode(render_mode)
    if mode == "handwriting":
        # Handwriting profile: force single-line handwriting logic.
        return mode, False, True
    # Drawing profile: keep technical geometry exact and disable handwriting transforms.
    return mode, True, False


def _looks_like_font_file_spec(value: str) -> bool:
    s = (value or "").strip().lower()
    if not s:
        return False
    if s.endswith((".ttf", ".otf", ".ttc")):
        return True
    return ("\\" in s) or ("/" in s) or (":" in s)


def _select_cyrillic_handwriting_font(backend, selected_hw_font: str) -> str:
    # Keep user-selected custom font when it is explicitly file-like or
    # can be resolved by backend font lookup; otherwise use a safe fallback.
    selected = str((selected_hw_font or "").strip() or "Marck Script")
    if _looks_like_font_file_spec(selected):
        return selected

    resolver = getattr(backend, "_resolve_handwriting_ttf_path", None)
    if callable(resolver):
        try:
            if resolver(selected) is not None:
                return selected
        except Exception:
            pass

    lower = selected.lower()
    if any(
        token in lower
        for token in (
            "marck",
            "bad script",
            "caveat",
            "neucha",
            "comic sans",
            "arial",
            "segoe script",
            "katherine",
            "katerine",
            "veles",
            "gogol",
            "kosolapa",
        )
    ):
        return selected
    return "Marck Script"


def _resolve_handwriting_font(backend, requested_font: str, log: Optional[LogFn] = None) -> str:
    selected = str((requested_font or "").strip() or "Marck Script")
    if _looks_like_font_file_spec(selected):
        p = Path(selected)
        if p.exists() and p.is_file():
            return str(p)

    resolver = getattr(backend, "_resolve_handwriting_ttf_path", None)
    if callable(resolver):
        try:
            if resolver(selected) is not None:
                return selected
        except Exception:
            pass
    fallback = "Marck Script"
    if log is not None and selected != fallback:
        log(f"Handwriting font fallback: '{selected}' -> '{fallback}'")
    return fallback


def _resolve_formula_font(backend, requested_font: str, log: Optional[LogFn] = None) -> str:
    selected = str((requested_font or "").strip() or "Times New Roman")
    normalizer = getattr(backend, "_normalize_word_font_name", None)
    if callable(normalizer):
        try:
            selected = str(normalizer(selected, default="Times New Roman") or "Times New Roman").strip()
        except Exception:
            selected = str((requested_font or "").strip() or "Times New Roman")
    selected = selected.strip().strip("'").strip('"')
    if not selected:
        selected = "Times New Roman"
    # Word formula font expects a family-like name, not a path.
    if _looks_like_font_file_spec(selected):
        stem = Path(selected).stem.strip()
        if stem:
            cleaned = stem.split("_", 1)[-1] if stem.lower().startswith("ofont.ru_") else stem
            if log is not None:
                log(f"Formula font normalized from file path: '{selected}' -> '{cleaned}'")
            return cleaned
        if log is not None and selected != "Times New Roman":
            log(f"Formula font fallback: '{selected}' -> 'Times New Roman'")
        return "Times New Roman"
    return selected


def _split_comment(line: str) -> str:
    s = (line or "").strip()
    if not s:
        return ""
    if ";" in s:
        s = s.split(";", 1)[0].strip()
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    return s


_G_RE = re.compile(r"\bG\d+(?:\.\d+)?\b", re.IGNORECASE)
_M_RE = re.compile(r"\bM\d+(?:\.\d+)?\b", re.IGNORECASE)


def _parse_words(body: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for tok in body.split():
        if not tok:
            continue
        k = tok[0].upper()
        if k in {"G", "M"}:
            continue
        try:
            out[k] = float(tok[1:])
        except Exception:
            continue
    return out


def _arc_points(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    *,
    cw: bool,
    step_deg: float = 3.0,
) -> list[tuple[float, float]]:
    sx, sy = start
    ex, ey = end
    cx, cy = center
    radius = math.hypot(sx - cx, sy - cy)
    if radius <= 1e-9:
        return [end]
    a0 = math.atan2(sy - cy, sx - cx)
    a1 = math.atan2(ey - cy, ex - cx)
    if cw:
        while a1 > a0:
            a1 -= 2.0 * math.pi
    else:
        while a1 < a0:
            a1 += 2.0 * math.pi
    sweep = a1 - a0
    step = math.radians(max(0.5, float(step_deg)))
    n = max(1, int(math.ceil(abs(sweep) / step)))
    pts: list[tuple[float, float]] = []
    for i in range(1, n + 1):
        t = a0 + sweep * (i / n)
        pts.append((cx + radius * math.cos(t), cy + radius * math.sin(t)))
    return pts


def _prune_short_polyline_segments(
    poly: list[tuple[float, float]],
    *,
    min_seg_mm: float,
) -> list[tuple[float, float]]:
    if len(poly) < 2:
        return []
    tol = max(1e-6, float(min_seg_mm))
    out: list[tuple[float, float]] = [poly[0]]
    for pt in poly[1:-1]:
        if math.hypot(float(pt[0]) - float(out[-1][0]), float(pt[1]) - float(out[-1][1])) >= tol:
            out.append((float(pt[0]), float(pt[1])))
    end = (float(poly[-1][0]), float(poly[-1][1]))
    if math.hypot(end[0] - float(out[-1][0]), end[1] - float(out[-1][1])) >= tol:
        out.append(end)
    elif len(out) >= 2:
        # Keep original end-point for geometry fidelity when the tail segment is tiny.
        out[-1] = end
    else:
        out.append(end)

    deduped: list[tuple[float, float]] = [out[0]]
    for pt in out[1:]:
        if math.hypot(float(pt[0]) - float(deduped[-1][0]), float(pt[1]) - float(deduped[-1][1])) >= 1e-9:
            deduped.append(pt)
    return deduped if len(deduped) >= 2 else []


def _collapse_immediate_backtracks(
    poly: list[tuple[float, float]],
    *,
    close_eps: float,
) -> list[tuple[float, float]]:
    """Drop immediate A->B->A backtracks that create doubled text strokes."""
    if len(poly) < 3:
        return [(float(x), float(y)) for x, y in poly] if len(poly) >= 2 else []
    eps = max(1e-6, float(close_eps))
    out: list[tuple[float, float]] = []
    for x, y in poly:
        pt = (float(x), float(y))
        if out and math.hypot(pt[0] - out[-1][0], pt[1] - out[-1][1]) <= (eps * 0.25):
            continue
        out.append(pt)
        while len(out) >= 3:
            a = out[-3]
            c = out[-1]
            if math.hypot(c[0] - a[0], c[1] - a[1]) > eps:
                break
            # Remove B and trailing A~ to collapse "... A B A ..." into "... A ...".
            out.pop()
            out.pop()
    if len(out) < 2:
        return []
    deduped: list[tuple[float, float]] = [out[0]]
    for pt in out[1:]:
        if math.hypot(pt[0] - deduped[-1][0], pt[1] - deduped[-1][1]) > 1e-9:
            deduped.append(pt)
    return deduped if len(deduped) >= 2 else []


def _straighten_axis_aligned_polyline_mm(
    poly: list[tuple[float, float]],
    *,
    min_span_mm: float = 8.0,
    max_thickness_mm: float = 1.6,
    dominance_ratio: float = 4.0,
) -> list[tuple[float, float]]:
    if len(poly) < 2:
        return []
    pts = [(float(x), float(y)) for x, y in poly]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0 = min(xs)
    x1 = max(xs)
    y0 = min(ys)
    y1 = max(ys)
    w = x1 - x0
    h = y1 - y0
    if w <= 0.0 and h <= 0.0:
        return []

    total_dx = 0.0
    total_dy = 0.0
    for i in range(1, len(pts)):
        total_dx += abs(pts[i][0] - pts[i - 1][0])
        total_dy += abs(pts[i][1] - pts[i - 1][1])

    if w >= float(min_span_mm) and h <= float(max_thickness_mm):
        if total_dx >= float(dominance_ratio) * max(1e-9, total_dy):
            ys_sorted = sorted(ys)
            y_med = ys_sorted[len(ys_sorted) // 2]
            return [(x0, y_med), (x1, y_med)]
    if h >= float(min_span_mm) and w <= float(max_thickness_mm):
        if total_dy >= float(dominance_ratio) * max(1e-9, total_dx):
            xs_sorted = sorted(xs)
            x_med = xs_sorted[len(xs_sorted) // 2]
            return [(x_med, y0), (x_med, y1)]
    return pts


def _point_segment_distance_mm(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    vv = (vx * vx) + (vy * vy)
    if vv <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((wx * vx) + (wy * vy)) / vv
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    qx = ax + (t * vx)
    qy = ay + (t * vy)
    return math.hypot(px - qx, py - qy)


def _resample_polyline_mm(
    poly: list[tuple[float, float]],
    *,
    target_points: int = 16,
) -> list[tuple[float, float]]:
    if len(poly) < 2:
        return []
    pts = [(float(x), float(y)) for x, y in poly]
    seg_lens: list[float] = []
    total = 0.0
    for i in range(1, len(pts)):
        ln = math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        seg_lens.append(ln)
        total += ln
    if total <= 1e-9:
        return [pts[0], pts[-1]]

    n = max(4, int(target_points))
    out: list[tuple[float, float]] = []
    step = total / float(n - 1)
    cur_seg = 0
    cur_pos = 0.0
    acc = 0.0
    for i in range(n):
        target = min(total, i * step)
        while cur_seg < len(seg_lens) and (acc + seg_lens[cur_seg]) < target:
            acc += seg_lens[cur_seg]
            cur_seg += 1
            cur_pos = 0.0
        if cur_seg >= len(seg_lens):
            out.append(pts[-1])
            continue
        seg_len = max(1e-12, seg_lens[cur_seg])
        a = pts[cur_seg]
        b = pts[cur_seg + 1]
        t = (target - acc) / seg_len
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _polyline_distance_to_polyline_mm(
    sample_poly: list[tuple[float, float]],
    ref_poly: list[tuple[float, float]],
) -> float:
    if len(sample_poly) < 2 or len(ref_poly) < 2:
        return float("inf")
    total = 0.0
    count = 0
    for px, py in sample_poly:
        best = float("inf")
        for i in range(1, len(ref_poly)):
            ax, ay = ref_poly[i - 1]
            bx, by = ref_poly[i]
            d = _point_segment_distance_mm(px, py, ax, ay, bx, by)
            if d < best:
                best = d
        total += best
        count += 1
    if count <= 0:
        return float("inf")
    return total / float(count)


def _dedup_near_text_polylines_mm(
    polys: list[list[tuple[float, float]]],
    *,
    max_offset_mm: float = 0.11,
) -> tuple[list[list[tuple[float, float]]], int]:
    if len(polys) < 2:
        return polys, 0

    items: list[dict[str, object]] = []
    for idx, poly in enumerate(polys):
        if len(poly) < 2:
            continue
        pts = [(float(x), float(y)) for x, y in poly]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        ln = 0.0
        for i in range(1, len(pts)):
            ln += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        if ln < 0.30:
            continue
        items.append(
            {
                "idx": idx,
                "poly": pts,
                "bbox": (x0, x1, y0, y1),
                "len": ln,
                "pts": len(pts),
            }
        )
    if len(items) < 2:
        return polys, 0

    removed: set[int] = set()
    eps = float(max(0.03, max_offset_mm))
    for i in range(len(items)):
        a = items[i]
        ia = int(a["idx"])  # type: ignore[arg-type]
        if ia in removed:
            continue
        ax0, ax1, ay0, ay1 = a["bbox"]  # type: ignore[assignment]
        alen = float(a["len"])  # type: ignore[arg-type]
        apoly = a["poly"]  # type: ignore[assignment]
        for j in range(i + 1, len(items)):
            b = items[j]
            ib = int(b["idx"])  # type: ignore[arg-type]
            if ib in removed:
                continue
            bx0, bx1, by0, by1 = b["bbox"]  # type: ignore[assignment]
            blen = float(b["len"])  # type: ignore[arg-type]
            bpoly = b["poly"]  # type: ignore[assignment]

            # Fast reject by bbox and length similarity.
            if (ax1 + eps) < bx0 or (bx1 + eps) < ax0 or (ay1 + eps) < by0 or (by1 + eps) < ay0:
                continue
            if abs(alen - blen) > (0.45 * max(alen, blen)):
                continue

            as0 = apoly[0]
            as1 = apoly[-1]
            bs0 = bpoly[0]
            bs1 = bpoly[-1]
            d_same = math.hypot(as0[0] - bs0[0], as0[1] - bs0[1]) + math.hypot(as1[0] - bs1[0], as1[1] - bs1[1])
            d_flip = math.hypot(as0[0] - bs1[0], as0[1] - bs1[1]) + math.hypot(as1[0] - bs0[0], as1[1] - bs0[1])
            if min(d_same, d_flip) > 0.70:
                continue

            a_s = _resample_polyline_mm(apoly, target_points=14)
            b_s = _resample_polyline_mm(bpoly, target_points=14)
            if not a_s or not b_s:
                continue
            ab = _polyline_distance_to_polyline_mm(a_s, bpoly)
            ba = _polyline_distance_to_polyline_mm(b_s, apoly)
            mean_d = 0.5 * (ab + ba)
            if mean_d > eps:
                continue

            # Remove lower-quality duplicate: shorter then fewer points.
            if alen < blen:
                removed.add(ia)
                break
            if blen < alen:
                removed.add(ib)
                continue
            a_pts = int(a["pts"])  # type: ignore[arg-type]
            b_pts = int(b["pts"])  # type: ignore[arg-type]
            if a_pts <= b_pts:
                removed.add(ia)
                break
            removed.add(ib)

    if not removed:
        return polys, 0
    out = [poly for k, poly in enumerate(polys) if k not in removed]
    return out, len(removed)


def _estimate_polyline_thickness_px(poly: list[tuple[float, float]], dist_map) -> float:
    if not poly:
        return 0.0
    h, w = dist_map.shape[:2]
    sample: list[float] = []
    step = max(1, int(len(poly) // 40))
    for i in range(0, len(poly), step):
        x, y = poly[i]
        xi = int(round(float(x)))
        yi = int(round(float(y)))
        if 0 <= xi < w and 0 <= yi < h:
            sample.append(float(dist_map[yi, xi]) * 2.0)
    if not sample:
        return 0.0
    sample.sort()
    return float(sample[len(sample) // 2])


def _offset_polyline_mm(poly: list[tuple[float, float]], offset_mm: float) -> list[tuple[float, float]]:
    if len(poly) < 2:
        return []
    off = float(offset_mm)
    if abs(off) <= 1e-9:
        return [(float(x), float(y)) for x, y in poly]
    pts = [(float(x), float(y)) for x, y in poly]
    out: list[tuple[float, float]] = []
    for i in range(len(pts)):
        p = pts[i]
        p_prev = pts[i - 1] if i > 0 else pts[i]
        p_next = pts[i + 1] if i + 1 < len(pts) else pts[i]
        tx = float(p_next[0] - p_prev[0])
        ty = float(p_next[1] - p_prev[1])
        tlen = math.hypot(tx, ty)
        if tlen <= 1e-9:
            if i > 0:
                tx = float(p[0] - pts[i - 1][0])
                ty = float(p[1] - pts[i - 1][1])
                tlen = math.hypot(tx, ty)
            if tlen <= 1e-9 and i + 1 < len(pts):
                tx = float(pts[i + 1][0] - p[0])
                ty = float(pts[i + 1][1] - p[1])
                tlen = math.hypot(tx, ty)
        if tlen <= 1e-9:
            out.append(p)
            continue
        nx = -ty / tlen
        ny = tx / tlen
        out.append((p[0] + off * nx, p[1] + off * ny))
    deduped: list[tuple[float, float]] = [out[0]]
    for pt in out[1:]:
        if math.hypot(pt[0] - deduped[-1][0], pt[1] - deduped[-1][1]) > 1e-9:
            deduped.append(pt)
    return deduped if len(deduped) >= 2 else []


def _is_detail_polyline_mm(
    poly: list[tuple[float, float]],
    *,
    page_w_mm: float,
    page_h_mm: float,
    crop_left_mm: float = 0.0,
    crop_right_mm: float = 0.0,
    crop_top_mm: float = 0.0,
    crop_bottom_mm: float = 0.0,
) -> bool:
    if len(poly) < 2:
        return False
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    bw = max(0.0, x1 - x0)
    bh = max(0.0, y1 - y0)
    if bw <= 0.0 and bh <= 0.0:
        return False

    edge_margin = 5.0
    if x0 <= edge_margin or x1 >= (float(page_w_mm) - edge_margin):
        return False
    if y0 <= edge_margin or y1 >= (float(page_h_mm) - edge_margin):
        return False

    # Exclude crop-border frame strokes (after left/right/top/bottom content crop).
    # These lines are part of the page frame/title block and must stay single-pass.
    crop_x0 = max(0.0, float(crop_left_mm))
    crop_x1 = max(crop_x0, float(page_w_mm) - max(0.0, float(crop_right_mm)))
    crop_y0 = max(0.0, float(crop_top_mm))
    crop_y1 = max(crop_y0, float(page_h_mm) - max(0.0, float(crop_bottom_mm)))
    near_crop_eps = 1.8
    if bw <= 1.2 and bh >= 18.0:
        if abs(x0 - crop_x0) <= near_crop_eps or abs(x1 - crop_x1) <= near_crop_eps:
            return False
    if bh <= 1.2 and bw >= 18.0:
        if abs(y0 - crop_y0) <= near_crop_eps or abs(y1 - crop_y1) <= near_crop_eps:
            return False

    # Exclude bottom title-block/table region from multipass.
    if y1 >= (0.78 * float(page_h_mm)):
        return False

    # Exclude very long axis-aligned frame/table strokes.
    if bh <= 0.9 and bw >= (0.55 * float(page_w_mm)):
        return False
    if bw <= 0.9 and bh >= (0.55 * float(page_h_mm)):
        return False
    return True


def _pen_down_from_z(cur_z: float, z_up: float, z_down: float) -> bool:
    """Treat pen as down only when Z is near the down level.

    This avoids false "draw" segments in previews when partial travel-lifts are used.
    """
    rng = abs(float(z_down) - float(z_up))
    if rng <= 1e-9:
        return True
    tol = max(0.05, rng * 0.18)
    if z_down >= z_up:
        return cur_z >= (z_down - tol)
    return cur_z <= (z_down + tol)


def _gcode_to_polylines(lines: list[str], *, z_up: float, z_down: float) -> list[list[tuple[float, float]]]:
    cur_x = 0.0
    cur_y = 0.0
    cur_z = z_up
    abs_mode = True
    ijk_abs = False
    pen_down = False
    out: list[list[tuple[float, float]]] = []
    cur_poly: list[tuple[float, float]] = []

    def _update_pen() -> None:
        nonlocal pen_down
        pen_down = _pen_down_from_z(cur_z, z_up, z_down)

    _update_pen()

    for raw in lines:
        body = _split_comment(raw)
        if not body or body.startswith("$"):
            continue

        motion_g: Optional[int] = None
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
            elif abs(gval - 0.0) <= 1e-6:
                motion_g = 0
            elif abs(gval - 1.0) <= 1e-6:
                motion_g = 1
            elif abs(gval - 2.0) <= 1e-6:
                motion_g = 2
            elif abs(gval - 3.0) <= 1e-6:
                motion_g = 3

        # Support spindle-style pen control (M3/M5) in preview parsing.
        for mtok in _M_RE.findall(body):
            m = mtok.upper()
            if m == "M3":
                pen_down = True
            elif m == "M5":
                pen_down = False

        words = _parse_words(body)
        if "Z" in words:
            z = float(words["Z"])
            cur_z = z if abs_mode else (cur_z + z)
            _update_pen()
        if motion_g is None:
            continue

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
        has_xy = ("X" in words) or ("Y" in words)
        is_draw = pen_down and has_xy and motion_g in (1, 2, 3)
        if is_draw:
            if not cur_poly:
                cur_poly = [start]
            if motion_g in (2, 3) and (("I" in words) or ("J" in words)):
                i = float(words.get("I", 0.0))
                j = float(words.get("J", 0.0))
                center = (i, j) if ijk_abs else (cur_x + i, cur_y + j)
                cur_poly.extend(_arc_points(start, end, center, cw=(motion_g == 2)))
            else:
                cur_poly.append(end)
        else:
            if len(cur_poly) >= 2:
                out.append(cur_poly)
            cur_poly = []

        cur_x, cur_y = end

    if len(cur_poly) >= 2:
        out.append(cur_poly)
    return out


def _preview_bounds(polylines: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [x for poly in polylines for x, _ in poly]
    ys = [y for poly in polylines for _, y in poly]
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), max(xs), min(ys), max(ys)


def _write_svg_preview(polylines: list[list[tuple[float, float]]], out_path: Path, *, pad_mm: float = 2.0) -> None:
    x0, x1, y0, y1 = _preview_bounds(polylines)
    flipped = [[(x, -y) for x, y in poly] for poly in polylines]
    x0, x1, y0, y1 = _preview_bounds(flipped)
    width = max(1e-6, x1 - x0)
    height = max(1e-6, y1 - y0)
    pad = max(0.0, float(pad_mm))
    vb_x = x0 - pad
    vb_y = y0 - pad
    vb_w = width + 2.0 * pad
    vb_h = height + 2.0 * pad
    center_y = (y0 + y1) * 0.5
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"',
        f'     width="{vb_w:.3f}mm" height="{vb_h:.3f}mm" viewBox="{vb_x:.3f} {vb_y:.3f} {vb_w:.3f} {vb_h:.3f}">',
        f'  <g fill="none" stroke="#111827" stroke-width="0.25" stroke-linecap="round" stroke-linejoin="round" transform="scale(1,-1) translate(0,-{2.0 * center_y:.4f})">',
    ]
    for poly in flipped:
        if len(poly) < 2:
            continue
        d = f"M {poly[0][0]:.4f} {poly[0][1]:.4f} " + " ".join(f"L {x:.4f} {y:.4f}" for x, y in poly[1:])
        parts.append(f'    <path d="{d}" />')
    parts.extend(["  </g>", "</svg>", ""])
    out_path.write_text("\n".join(parts), encoding="utf-8")


def _write_pdf_preview(polylines: list[list[tuple[float, float]]], out_path: Path, *, pad_mm: float = 2.0) -> None:
    if fitz is None:
        return

    x0, x1, y0, y1 = _preview_bounds(polylines)
    flipped = [[(x, -y) for x, y in poly] for poly in polylines]
    x0, x1, y0, y1 = _preview_bounds(flipped)
    width = max(1e-6, x1 - x0)
    height = max(1e-6, y1 - y0)
    pad = max(0.0, float(pad_mm))
    vb_x = x0 - pad
    vb_y = y0 - pad
    vb_w = width + 2.0 * pad
    vb_h = height + 2.0 * pad
    mm_to_pt = 72.0 / 25.4

    doc = fitz.open()
    try:
        page = doc.new_page(width=vb_w * mm_to_pt, height=vb_h * mm_to_pt)
        shape = page.new_shape()
        for poly in flipped:
            if len(poly) < 2:
                continue
            for i in range(1, len(poly)):
                x0_mm, y0_mm = poly[i - 1]
                x1_mm, y1_mm = poly[i]
                p0 = (
                    (x0_mm - vb_x) * mm_to_pt,
                    (vb_h - (y0_mm - vb_y)) * mm_to_pt,
                )
                p1 = (
                    (x1_mm - vb_x) * mm_to_pt,
                    (vb_h - (y1_mm - vb_y)) * mm_to_pt,
                )
                shape.draw_line(p0, p1)
        shape.finish(color=(0.07, 0.10, 0.16), width=0.72)
        shape.commit()
        doc.save(out_path)
    finally:
        doc.close()


class BackendBridge:
    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._backend_path = project_root / "src" / "plotter_pdf_drawer.py"
        self._backend_module = None
        self._default_baud_cache = "115200"

    def _backend(self):
        if self._backend_module is not None:
            return self._backend_module

        # Primary path: static import so PyInstaller collects backend dependencies.
        try:
            from src import plotter_pdf_drawer as module  # type: ignore
            self._backend_module = module
            return module
        except Exception:
            pass

        # Fallback for environments where src is not importable as a package.
        if not self._backend_path.exists():
            raise ToolDependencyError(f"Backend script not found: {self._backend_path}")
        spec = importlib.util.spec_from_file_location("plotter_pdf_drawer_backend", str(self._backend_path))
        if spec is None or spec.loader is None:
            raise ToolDependencyError("Cannot load backend module.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self._backend_module = module
        return module

    def list_com_ports(self) -> list[str]:
        ports: list[str] = []
        for p in list_ports.comports():
            if p.device:
                ports.append(str(p.device))
        ports.sort()
        return ports

    def detect_com_port(self, preferred: Optional[str] = None) -> str:
        backend = self._backend()
        return str(backend.detect_com_port(preferred))

    def default_baud(self) -> str:
        # Fast path for app startup: avoid loading heavy backend module
        # just to read baud value.
        if self._backend_module is None:
            return self._default_baud_cache
        try:
            self._default_baud_cache = str(self._backend_module.DEFAULT_BAUD)
        except Exception:
            pass
        return self._default_baud_cache

    def z_down_sign(self) -> float:
        backend = self._backend()
        return 1.0 if (float(backend.PENCIL_BASE_Z_DOWN) - float(backend.Z_UP)) >= 0.0 else -1.0

    def _configure_sheet(self, sheet: SheetConfig, log: LogFn) -> None:
        backend = self._backend()
        backend.PASS_COLS = max(1, int(sheet.pass_cols))
        backend.PASS_ROWS = max(1, int(sheet.pass_rows))
        backend.PASS_COL = min(max(1, int(sheet.pass_col)), backend.PASS_COLS)
        backend.PASS_ROW = min(max(1, int(sheet.pass_row)), backend.PASS_ROWS)
        backend.configure_active_work_area(
            sheet_format=sheet.sheet_format,
            sheet_width_mm=sheet.width_mm,
            sheet_height_mm=sheet.height_mm,
            anchor=sheet.anchor,
            offset_x_mm=sheet.offset_x_mm,
            offset_y_mm=sheet.offset_y_mm,
            logger=log,
        )

    def set_tool_mode(self, tool_mode: str) -> None:
        backend = self._backend()
        backend.TOOL_MODE = "pencil" if (tool_mode or "").strip().lower() == "pencil" else "pen"

    def _build_vector_preview_from_gcode(
        self,
        gcode_path: Path,
        svg_path: Path,
        pdf_path: Path,
        *,
        backend,
        log: LogFn,
    ) -> tuple[bool, str]:
        if not gcode_path.exists():
            return False, f"G-code file not found: {gcode_path}"
        try:
            lines = gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            polylines = _gcode_to_polylines(
                lines,
                z_up=float(backend.Z_UP),
                z_down=float(backend.Z_DOWN),
            )
            if not polylines:
                return False, "Generated G-code has no drawable paths."
            _write_svg_preview(polylines, svg_path)
            _write_pdf_preview(polylines, pdf_path)
            log(f"Preview SVG: {svg_path}")
            if pdf_path.exists():
                log(f"Preview PDF: {pdf_path}")
            return True, ""
        except Exception as exc:
            return False, _format_user_exception(exc, prefix="Preview generation failed")

    @staticmethod
    def _method3_threshold_candidates(backend, gray) -> list[int]:
        cands = int(max(3, min(17, backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CANDIDATES)))
        vals = [int(round(256.0 * (1 + i) / float(cands + 1))) for i in range(cands)]
        try:
            otsu_thr, _ = backend.cv2.threshold(gray, 0, 255, backend.cv2.THRESH_BINARY + backend.cv2.THRESH_OTSU)
            vals.append(int(max(1, min(254, int(otsu_thr)))))
        except Exception:
            pass
        vals.append(int(max(1, min(254, int(backend.HANDWRITING_SINGLELINE_TTF_BIN_THRESHOLD)))))
        vals = [max(1, min(254, int(v))) for v in vals]
        return list(dict.fromkeys(vals))

    @staticmethod
    def _method3_score_polylines_px(
        backend,
        polys: list[list[tuple[float, float]]],
        *,
        idx: int,
        total: int,
        w: int,
        h: int,
    ) -> float:
        if not polys:
            return -1e30
        length = sum(backend.polyline_length(p) for p in polys if len(p) >= 2)
        points = sum(len(p) for p in polys if len(p) >= 2)
        segments = sum(max(0, len(p) - 1) for p in polys if len(p) >= 2)
        offset = ((float(total) / 2.0) - float(idx)) ** 2 * float(w + h)
        return (length * 5.0) - (offset * 0.005) - (points * 0.20) - (segments * 20.0)

    @staticmethod
    def _order_polylines_line_lr(polys: list[list[tuple[float, float]]], *, row_tol_mm: float) -> list[list[tuple[float, float]]]:
        remaining = [p for p in polys if len(p) >= 2]
        if not remaining:
            return []
        tol = max(0.6, float(row_tol_mm))
        entries: list[tuple[int, float, float, float, float, list[tuple[float, float]]]] = []
        for idx, poly in enumerate(remaining):
            xs = [pt[0] for pt in poly]
            ys = [pt[1] for pt in poly]
            min_x = min(xs)
            max_x = max(xs)
            min_y = min(ys)
            max_y = max(ys)
            cy = 0.5 * (min_y + max_y)
            entries.append((idx, min_x, max_x, min_y, cy, poly))

        entries.sort(key=lambda row: (row[4], row[1], row[0]))
        rows: list[tuple[float, list[tuple[int, float, float, float, float, list[tuple[float, float]]]]]] = []
        for ent in entries:
            if not rows:
                rows.append((ent[4], [ent]))
                continue
            last_y, last_items = rows[-1]
            if abs(ent[4] - last_y) <= tol:
                last_items.append(ent)
                rows[-1] = ((last_y * (len(last_items) - 1) + ent[4]) / len(last_items), last_items)
            else:
                rows.append((ent[4], [ent]))

        ordered: list[list[tuple[float, float]]] = []
        for _, row_items in rows:
            row_items.sort(key=lambda row: (row[1], row[0]))
            for _, min_x, max_x, _min_y, _cy, poly in row_items:
                out_poly = list(poly)
                if len(out_poly) >= 2:
                    sx, ex = out_poly[0][0], out_poly[-1][0]
                    span_x = max(0.0, max_x - min_x)
                    if (sx - ex) > max(0.6, 0.15 * span_x):
                        out_poly = list(reversed(out_poly))
                ordered.append(out_poly)
        return ordered

    def _run_method3_centerline_page(
        self,
        backend,
        gray,
        log: LogFn,
    ) -> tuple[list[list[tuple[float, float]]], int]:
        autotrace_exe = backend._resolve_autotrace_executable()
        if autotrace_exe is None:
            raise ToolDependencyError("autotrace.exe not found (tools/autotrace/autotrace.exe).")
        if gray.ndim != 2:
            gray = backend.cv2.cvtColor(gray, backend.cv2.COLOR_BGR2GRAY)

        thresholds = self._method3_threshold_candidates(backend, gray)
        h, w = gray.shape[:2]
        best_score = -1e30
        best_thr = thresholds[0]
        best_polys: list[list[tuple[float, float]]] = []

        for idx, thr in enumerate(thresholds):
            mask = ((gray < int(thr)).astype(backend.np.uint8)) * 255
            if int(backend.np.count_nonzero(mask)) <= 0:
                continue
            try:
                kernel = backend.np.ones((2, 2), dtype=backend.np.uint8)
                mask = backend.cv2.morphologyEx(mask, backend.cv2.MORPH_CLOSE, kernel, iterations=1)
            except Exception:
                pass
            binary = backend.np.where(mask > 0, 0, 255).astype(backend.np.uint8)
            polys = backend._run_autotrace_centerline_on_binary(
                binary,
                autotrace_exe=autotrace_exe,
                error_threshold=float(backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_ERROR_THRESHOLD),
                filter_iterations=int(backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_FILTER_ITERATIONS),
                curve_step_px=float(backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CURVE_STEP_PX),
            )
            if not polys:
                continue
            cleaned: list[list[tuple[float, float]]] = []
            for poly in polys:
                if len(poly) < 2:
                    continue
                p = backend.simplify_polyline([(float(x), float(y)) for x, y in poly], eps=1e-6)
                if len(p) >= 3:
                    p = backend.rdp_simplify_polyline(p, eps=0.45)
                if len(p) < 2:
                    continue
                if backend.polyline_length(p) < 2.2:
                    continue
                cleaned.append(p)
            if not cleaned:
                continue
            score = self._method3_score_polylines_px(backend, cleaned, idx=idx, total=len(thresholds), w=w, h=h)
            if score > best_score:
                best_score = score
                best_thr = int(thr)
                best_polys = cleaned

        if best_polys:
            log(
                f"Method3 centerline: threshold={best_thr}, "
                f"candidates={len(thresholds)}, paths={len(best_polys)}"
            )
        return best_polys, int(best_thr)

    @staticmethod
    def _split_method3_text_graphics_masks(backend, gray, threshold: int):
        # Build two masks:
        # 1) text/formula-like smaller components -> centerline tracing
        # 2) large/filled drawing-image blocks -> contour outlining
        base = ((gray < int(threshold)).astype(backend.np.uint8)) * 255
        if int(backend.np.count_nonzero(base)) <= 0:
            return base, backend.np.zeros_like(base, dtype=backend.np.uint8)

        h, w = gray.shape[:2]
        page_area = float(max(1, h * w))
        text_mask = backend.np.zeros_like(base, dtype=backend.np.uint8)
        graphics_mask = backend.np.zeros_like(base, dtype=backend.np.uint8)
        num_labels, labels, stats, _ = backend.cv2.connectedComponentsWithStats(base, connectivity=8)

        max_w_large = max(20.0, 0.18 * float(w))
        max_h_large = max(20.0, 0.12 * float(h))
        area_large = 0.010 * page_area
        area_medium = 0.0022 * page_area

        for label in range(1, int(num_labels)):
            bw = int(stats[label, backend.cv2.CC_STAT_WIDTH])
            bh = int(stats[label, backend.cv2.CC_STAT_HEIGHT])
            area = float(stats[label, backend.cv2.CC_STAT_AREA])
            if bw <= 0 or bh <= 0 or area <= 0.0:
                continue
            box_area = float(max(1, bw * bh))
            fill = area / box_area
            is_graphics = (
                (area >= area_large)
                or (bw >= max_w_large and bh >= max_h_large)
                or (area >= area_medium and fill >= 0.38)
            )
            target = graphics_mask if is_graphics else text_mask
            target[labels == label] = 255

        # Force long axis-aligned frame/table lines into graphics so they do not
        # merge with nearby text glyphs during centerline tracing.
        try:
            h_len = max(28, int(round(0.060 * float(w))))
            v_len = max(28, int(round(0.060 * float(h))))
            h_kernel = backend.cv2.getStructuringElement(backend.cv2.MORPH_RECT, (h_len, 1))
            v_kernel = backend.cv2.getStructuringElement(backend.cv2.MORPH_RECT, (1, v_len))
            h_lines = backend.cv2.morphologyEx(base, backend.cv2.MORPH_OPEN, h_kernel, iterations=1)
            v_lines = backend.cv2.morphologyEx(base, backend.cv2.MORPH_OPEN, v_kernel, iterations=1)
            line_mask = backend.cv2.bitwise_or(h_lines, v_lines)
            if int(backend.np.count_nonzero(line_mask)) > 0:
                graphics_mask = backend.cv2.bitwise_or(graphics_mask, line_mask)
                text_mask[line_mask > 0] = 0
        except Exception:
            pass

        try:
            text_mask = backend.cv2.morphologyEx(
                text_mask,
                backend.cv2.MORPH_OPEN,
                backend.np.ones((2, 2), dtype=backend.np.uint8),
                iterations=1,
            )
        except Exception:
            pass
        return text_mask, graphics_mask

    @staticmethod
    def _polyline_mask_overlap_ratio(poly: list[tuple[float, float]], mask) -> float:
        if not poly:
            return 0.0
        h, w = mask.shape[:2]
        inside = 0
        valid = 0
        for x, y in poly:
            xi = int(round(float(x)))
            yi = int(round(float(y)))
            if xi < 0 or yi < 0 or xi >= w or yi >= h:
                continue
            valid += 1
            if int(mask[yi, xi]) > 0:
                inside += 1
        if valid <= 0:
            return 0.0
        return float(inside) / float(valid)

    def _extract_graphics_outline_polylines_px(self, backend, graphics_mask) -> list[list[tuple[float, float]]]:
        if int(backend.np.count_nonzero(graphics_mask)) <= 0:
            return []
        try:
            contours, _hier = backend.cv2.findContours(
                graphics_mask,
                backend.cv2.RETR_LIST,
                backend.cv2.CHAIN_APPROX_NONE,
            )
        except Exception:
            return []
        out: list[list[tuple[float, float]]] = []
        for cnt in contours:
            if cnt is None or len(cnt) < 2:
                continue
            poly = [(float(pt[0][0]), float(pt[0][1])) for pt in cnt]
            if len(poly) >= 3:
                poly = backend.rdp_simplify_polyline(poly, eps=0.65)
            if len(poly) < 2:
                continue
            if backend.polyline_length(poly) < 4.0:
                continue
            out.append(poly)
        return out

    def _extract_graphics_centerline_polylines_px(
        self,
        backend,
        graphics_mask,
        log: LogFn,
    ) -> list[list[tuple[float, float]]]:
        if int(backend.np.count_nonzero(graphics_mask)) <= 0:
            return []
        autotrace_exe = backend._resolve_autotrace_executable()
        if autotrace_exe is None:
            return []

        mask = graphics_mask
        try:
            # Connect tiny breaks before centerline tracing.
            kernel = backend.np.ones((2, 2), dtype=backend.np.uint8)
            mask = backend.cv2.morphologyEx(mask, backend.cv2.MORPH_CLOSE, kernel, iterations=1)
        except Exception:
            pass

        binary = backend.np.where(mask > 0, 0, 255).astype(backend.np.uint8)
        polys = backend._run_autotrace_centerline_on_binary(
            binary,
            autotrace_exe=autotrace_exe,
            error_threshold=float(max(0.8, backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_ERROR_THRESHOLD)),
            filter_iterations=int(max(2, backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_FILTER_ITERATIONS)),
            curve_step_px=float(max(0.75, backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CURVE_STEP_PX)),
        )
        if not polys:
            return []

        out: list[list[tuple[float, float]]] = []
        for poly in polys:
            if len(poly) < 2:
                continue
            p = backend.simplify_polyline([(float(x), float(y)) for x, y in poly], eps=1e-6)
            if len(p) >= 3:
                p = backend.rdp_simplify_polyline(p, eps=0.65)
            if len(p) < 2:
                continue
            if backend.polyline_length(p) < 3.0:
                continue
            out.append(p)
        if out:
            log(f"Method3 graphics centerline: paths={len(out)}")
        return out

    @staticmethod
    def _polyline_bbox_px(poly: list[tuple[float, float]]) -> Optional[tuple[float, float, float, float]]:
        if not poly:
            return None
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        if not xs or not ys:
            return None
        return min(xs), max(xs), min(ys), max(ys)

    def _filter_bottom_row_text_polylines_px(
        self,
        text_polys: list[list[tuple[float, float]]],
        *,
        img_h: int,
        img_w: int,
    ) -> tuple[list[list[tuple[float, float]]], int]:
        if not text_polys:
            return [], 0
        # Remove only the very bottom metadata row (e.g. "Формат A4")
        # and keep title-block rows above it (Н.контр/Утв and similar).
        bottom_cut = float(img_h) * 0.985
        tail_cut = float(img_h) * 0.992
        max_glyph_h = max(28.0, float(img_h) * 0.055)
        max_glyph_w = max(200.0, float(img_w) * 0.40)
        tail_max_h = max(22.0, float(img_h) * 0.020)
        tail_max_w = max(120.0, float(img_w) * 0.18)
        out: list[list[tuple[float, float]]] = []
        removed = 0
        for poly in text_polys:
            b = self._polyline_bbox_px(poly)
            if b is None:
                continue
            x0, x1, y0, y1 = b
            bh = max(0.0, y1 - y0)
            bw = max(0.0, x1 - x0)
            if y0 >= bottom_cut and bh <= max_glyph_h and bw <= max_glyph_w:
                removed += 1
                continue
            if y0 >= tail_cut and bh <= tail_max_h and bw <= tail_max_w:
                removed += 1
                continue
            out.append(poly)
        return out, removed

    def _filter_left_upper_column_text_polylines_px(
        self,
        text_polys: list[list[tuple[float, float]]],
        *,
        img_h: int,
        img_w: int,
        left_ratio: float = 0.148,
        keep_bottom_from_ratio: float = 0.72,
    ) -> tuple[list[list[tuple[float, float]]], int]:
        if not text_polys:
            return [], 0
        x_cut = float(img_w) * float(max(0.06, min(0.28, left_ratio)))
        y_keep_from = float(img_h) * float(max(0.50, min(0.92, keep_bottom_from_ratio)))
        out: list[list[tuple[float, float]]] = []
        removed = 0
        for poly in text_polys:
            b = self._polyline_bbox_px(poly)
            if b is None:
                continue
            _x0, x1, y0, _y1 = b
            if x1 <= x_cut and y0 < y_keep_from:
                removed += 1
                continue
            out.append(poly)
        return out, removed

    def _filter_outer_frame_polylines_px(
        self,
        polys: list[list[tuple[float, float]]],
        *,
        img_w: int,
        img_h: int,
    ) -> tuple[list[list[tuple[float, float]]], int]:
        if not polys:
            return [], 0
        margin = max(8.0, 0.008 * float(min(img_w, img_h)))
        thin_h = max(6.0, 0.020 * float(img_h))
        thin_w = max(6.0, 0.020 * float(img_w))
        long_h_span = 0.90 * float(img_w)
        long_v_span = 0.90 * float(img_h)

        out: list[list[tuple[float, float]]] = []
        removed = 0
        for poly in polys:
            b = self._polyline_bbox_px(poly)
            if b is None:
                continue
            x0, x1, y0, y1 = b
            bw = max(0.0, x1 - x0)
            bh = max(0.0, y1 - y0)
            poly_points = int(len(poly))
            touch_l = x0 <= margin
            touch_r = x1 >= (float(img_w) - margin)
            touch_t = y0 <= margin
            touch_b = y1 >= (float(img_h) - margin)

            is_outer_hline = (bw >= long_h_span) and (bh <= thin_h) and (touch_t or touch_b)
            is_outer_vline = (bh >= long_v_span) and (bw <= thin_w) and (touch_l or touch_r)
            is_full_edge_loop = touch_l and touch_r and touch_t and touch_b
            # Outer frame can be represented as one sparse open path around 3 sides.
            is_sparse_outer_box = (bw >= long_h_span) and (bh >= long_v_span) and (poly_points <= 24)
            if is_sparse_outer_box:
                # If the sparse box hugs full page edges, this is the external contour:
                # drop it and keep only the inner frame.
                if touch_l and touch_r and touch_t and touch_b:
                    removed += 1
                    continue
                # Rebuild interior sparse frame as a closed rectangle
                # to avoid open-corner gaps.
                xx0 = float(x0)
                xx1 = float(x1)
                yy0 = float(y0)
                yy1 = float(y1)
                out.append([(xx0, yy0), (xx1, yy0)])  # top
                out.append([(xx1, yy0), (xx1, yy1)])  # right
                out.append([(xx1, yy1), (xx0, yy1)])  # bottom
                out.append([(xx0, yy1), (xx0, yy0)])  # left
                removed += 1
                continue
            if is_outer_hline or is_outer_vline or is_full_edge_loop:
                removed += 1
                continue
            out.append(poly)
        return out, removed

    def _extract_pdf_filled_micro_strokes_mm(
        self,
        *,
        pdf_path: Path,
        page_index: int,
        page_w_mm: float,
        page_h_mm: float,
        log: LogFn,
    ) -> list[list[tuple[float, float]]]:
        # Recover tiny filled details (dimension arrowheads, etc.) from vector PDF paths.
        if fitz is None:
            return []
        if not pdf_path.exists():
            return []

        try:
            with fitz.open(str(pdf_path)) as doc:
                if page_index < 1 or page_index > int(doc.page_count):
                    return []
                page = doc[page_index - 1]
                drawings = page.get_drawings()
                page_rect = page.rect
        except Exception:
            return []

        pt_to_mm = 25.4 / 72.0
        src_w_mm = float(page_rect.width) * pt_to_mm
        src_h_mm = float(page_rect.height) * pt_to_mm
        sx = float(page_w_mm) / src_w_mm if src_w_mm > 1e-9 else 1.0
        sy = float(page_h_mm) / src_h_mm if src_h_mm > 1e-9 else 1.0

        max_dim_mm = 6.2
        max_box_area_mm2 = 22.0
        bottom_cut_mm = float(page_h_mm) * 0.93

        def _pt_xy_mm(pt) -> Optional[tuple[float, float]]:
            try:
                x_pt = float(pt.x)
                y_pt = float(pt.y)
            except Exception:
                try:
                    x_pt = float(pt[0])
                    y_pt = float(pt[1])
                except Exception:
                    return None
            return (x_pt * pt_to_mm * sx, y_pt * pt_to_mm * sy)

        out: list[list[tuple[float, float]]] = []
        kept_paths = 0
        for d in drawings:
            fill = d.get("fill")
            if fill is None:
                continue
            try:
                if isinstance(fill, (list, tuple)) and len(fill) >= 3:
                    lum = (0.2126 * float(fill[0])) + (0.7152 * float(fill[1])) + (0.0722 * float(fill[2]))
                    if lum > 0.55:
                        continue
            except Exception:
                pass

            rect = d.get("rect")
            if rect is None:
                continue
            rw_mm = float(rect.width) * pt_to_mm * sx
            rh_mm = float(rect.height) * pt_to_mm * sy
            y0_mm = float(rect.y0) * pt_to_mm * sy
            if rw_mm <= 0.0 or rh_mm <= 0.0:
                continue
            if max(rw_mm, rh_mm) > max_dim_mm:
                continue
            if (rw_mm * rh_mm) > max_box_area_mm2:
                continue
            if y0_mm >= bottom_cut_mm:
                continue

            items = d.get("items") or []
            seg_count = 0
            for item in items:
                if not item:
                    continue
                op = str(item[0]).lower()
                if op == "l" and len(item) >= 3:
                    p0 = _pt_xy_mm(item[1])
                    p1 = _pt_xy_mm(item[2])
                    if p0 is None or p1 is None:
                        continue
                    if math.hypot(float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])) < 0.03:
                        continue
                    out.append([p0, p1])
                    seg_count += 1
                elif op == "re" and len(item) >= 2:
                    r = item[1]
                    try:
                        x0 = float(r.x0) * pt_to_mm * sx
                        y0 = float(r.y0) * pt_to_mm * sy
                        x1 = float(r.x1) * pt_to_mm * sx
                        y1 = float(r.y1) * pt_to_mm * sy
                    except Exception:
                        continue
                    box_poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
                    if max(abs(x1 - x0), abs(y1 - y0)) < 0.03:
                        continue
                    out.append(box_poly)
                    seg_count += 1
            if seg_count > 0:
                kept_paths += 1

        if out:
            log(f"Method3 filled accents: paths={kept_paths}, segments={len(out)}")
        return out

    def _drop_tiny_bottom_artifacts_mm(
        self,
        polys_mm: list[list[tuple[float, float]]],
        *,
        page_h_mm: float,
    ) -> tuple[list[list[tuple[float, float]]], int]:
        if not polys_mm:
            return [], 0
        # Remove only tiny speckles in the very bottom tail strip.
        artifact_cut = float(page_h_mm) * 0.98
        max_w = 5.0
        max_h = 5.0
        max_len = 15.0
        out: list[list[tuple[float, float]]] = []
        removed = 0
        for poly in polys_mm:
            b = self._polyline_bbox_px(poly)
            if b is None:
                continue
            x0, x1, y0, y1 = b
            bw = max(0.0, x1 - x0)
            bh = max(0.0, y1 - y0)
            plen = 0.0
            if len(poly) >= 2:
                for i in range(len(poly) - 1):
                    plen += math.hypot(
                        float(poly[i + 1][0]) - float(poly[i][0]),
                        float(poly[i + 1][1]) - float(poly[i][1]),
                    )
            if y0 >= artifact_cut and bw <= max_w and bh <= max_h and plen <= max_len:
                removed += 1
                continue
            out.append(poly)
        return out, removed

    def _select_graphics_outline_accents_px(
        self,
        outlines: list[list[tuple[float, float]]],
        *,
        img_w: int,
        img_h: int,
    ) -> list[list[tuple[float, float]]]:
        # Keep compact closed outlines (dimension arrowheads and similar accents)
        # so they don't disappear when graphics are centerlined.
        if not outlines:
            return []
        max_dim = max(24.0, 0.015 * float(min(img_w, img_h)))
        max_area = max_dim * max_dim * 0.70
        out: list[list[tuple[float, float]]] = []
        for poly in outlines:
            if len(poly) < 3:
                continue
            b = self._polyline_bbox_px(poly)
            if b is None:
                continue
            x0, x1, y0, y1 = b
            bw = max(0.0, x1 - x0)
            bh = max(0.0, y1 - y0)
            if bw <= 0.0 or bh <= 0.0:
                continue
            if bw > max_dim or bh > max_dim or (bw * bh) > max_area:
                continue
            p0 = poly[0]
            p1 = poly[-1]
            if math.hypot(float(p0[0]) - float(p1[0]), float(p0[1]) - float(p1[1])) > 3.0:
                continue
            out.append(poly)
        return out

    @staticmethod
    def _write_method3_svg(
        out_svg: Path,
        polys_mm: list[list[tuple[float, float]]],
        *,
        page_w_mm: float,
        page_h_mm: float,
    ) -> None:
        ns = "http://www.w3.org/2000/svg"
        ET.register_namespace("", ns)
        root = ET.Element(
            "{" + ns + "}svg",
            {
                "width": f"{page_w_mm:.3f}mm",
                "height": f"{page_h_mm:.3f}mm",
                "viewBox": f"0 0 {page_w_mm:.6f} {page_h_mm:.6f}",
                "version": "1.1",
            },
        )
        grp = ET.SubElement(
            root,
            "{" + ns + "}g",
            {
                "fill": "none",
                "stroke": "#111111",
                "stroke-width": "0.22",
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
            },
        )
        for poly in polys_mm:
            if len(poly) < 2:
                continue
            d = [f"M {poly[0][0]:.4f} {poly[0][1]:.4f}"]
            for x, y in poly[1:]:
                d.append(f"L {x:.4f} {y:.4f}")
            ET.SubElement(grp, "{" + ns + "}path", {"d": " ".join(d)})
        ET.ElementTree(root).write(out_svg, encoding="utf-8", xml_declaration=True)

    def _prepare_method3_page(
        self,
        *,
        backend,
        input_path: Path,
        source_page_index: int,
        body_font: str,
        formula_font: str,
        output_svg: Path,
        output_pdf: Path,
        output_nc: Optional[Path],
        log: LogFn,
        source_pdf_path: Optional[Path] = None,
        source_page_count: Optional[int] = None,
    ) -> tuple[bool, str]:
        if backend.cv2 is None or backend.np is None:
            return False, "OpenCV/Numpy unavailable for method3 centerline."

        page = max(1, int(source_page_index))
        dpi = 420
        output_svg.parent.mkdir(parents=True, exist_ok=True)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        if output_nc is not None:
            output_nc.parent.mkdir(parents=True, exist_ok=True)

        for p in [output_svg, output_pdf, output_nc]:
            if p is not None and p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        with tempfile.TemporaryDirectory(dir=str(backend.ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
            work = Path(td)
            ext = input_path.suffix.lower()
            if source_pdf_path is not None:
                pdf_src = Path(source_pdf_path)
            else:
                if ext in {".doc", ".docx"}:
                    pdf_src = work / "source.pdf"
                    backend.word_to_pdf(
                        input_path,
                        pdf_src,
                        log,
                        override_font=(body_font or None),
                        formula_font=(formula_font or None),
                    )
                elif ext == ".pdf":
                    pdf_src = input_path
                else:
                    return False, f"Method3 page mode supports .doc/.docx/.pdf, got: {ext}"

            page_count = int(source_page_count) if source_page_count is not None else 0
            if fitz is not None and page_count <= 0:
                try:
                    with fitz.open(str(pdf_src)) as doc:
                        page_count = int(doc.page_count)
                except Exception:
                    pass
            if page_count > 0:
                if page > page_count:
                    return False, f"Page {page} is out of range (total pages: {page_count})."
                log(f"Source pages: {page_count}, selected: {page}")

            png = work / "page.png"
            cmd = [
                backend.find_inkscape(),
                str(pdf_src),
                "--export-type=png",
                "--export-overwrite",
                "--export-area-page",
                f"--export-filename={png}",
                "--export-dpi",
                str(int(max(72, dpi))),
                "--pdf-page",
                str(page),
                "--pdf-poppler",
            ]
            rc, out, err = backend.run_cmd(cmd, timeout_s=180.0)
            if rc != 0 or (not png.exists()) or png.stat().st_size <= 0:
                return False, (
                    "Inkscape PNG export failed: "
                    f"rc={rc}, out={(out or '').strip()[:180]}, err={(err or '').strip()[:180]}"
                )

            arr = backend.cv2.imread(str(png), backend.cv2.IMREAD_GRAYSCALE)
            if arr is None or arr.size <= 0:
                return False, "Failed to load exported page PNG."
            img_h, img_w = arr.shape[:2]
            page_w_mm = float(img_w) * 25.4 / float(max(1, int(dpi)))
            page_h_mm = float(img_h) * 25.4 / float(max(1, int(dpi)))

            text_centerline_px, best_thr = self._run_method3_centerline_page(backend, arr, log)
            if not text_centerline_px:
                return False, "Method3 centerline produced no paths."
            text_mask, graphics_mask = self._split_method3_text_graphics_masks(backend, arr, best_thr)
            filtered_text_px: list[list[tuple[float, float]]] = []
            for poly in text_centerline_px:
                overlap = self._polyline_mask_overlap_ratio(poly, graphics_mask)
                if overlap >= 0.55:
                    continue
                filtered_text_px.append(poly)

            filtered_text_px, removed_bottom_text = self._filter_bottom_row_text_polylines_px(
                filtered_text_px,
                img_h=img_h,
                img_w=img_w,
            )
            filtered_text_px, removed_left_upper_text = self._filter_left_upper_column_text_polylines_px(
                filtered_text_px,
                img_h=img_h,
                img_w=img_w,
                left_ratio=0.148,
                keep_bottom_from_ratio=0.68,
            )
            cleaned_text_px: list[list[tuple[float, float]]] = []
            removed_text_backtracks = 0
            for poly in filtered_text_px:
                cleaned = _collapse_immediate_backtracks(poly, close_eps=1.6)
                if len(cleaned) >= 2:
                    cleaned_text_px.append(cleaned)
                removed_text_backtracks += max(0, len(poly) - len(cleaned))
            filtered_text_px = cleaned_text_px
            graphics_centerline_px = self._extract_graphics_centerline_polylines_px(backend, graphics_mask, log)
            graphics_outline_px = self._extract_graphics_outline_polylines_px(backend, graphics_mask)
            graphics_accents_px = self._select_graphics_outline_accents_px(
                graphics_outline_px,
                img_w=img_w,
                img_h=img_h,
            )
            if graphics_centerline_px:
                graphics_px = [*graphics_centerline_px, *graphics_accents_px]
            else:
                graphics_px = graphics_outline_px
            graphics_px, removed_bottom_graphics = self._filter_bottom_row_text_polylines_px(
                graphics_px,
                img_h=img_h,
                img_w=img_w,
            )
            graphics_px, removed_left_upper_graphics = self._filter_left_upper_column_text_polylines_px(
                graphics_px,
                img_h=img_h,
                img_w=img_w,
                left_ratio=0.145,
                keep_bottom_from_ratio=0.68,
            )
            cleaned_graphics_px: list[list[tuple[float, float]]] = []
            removed_graphics_backtracks = 0
            for poly in graphics_px:
                cleaned = _collapse_immediate_backtracks(poly, close_eps=1.2)
                if len(cleaned) >= 2:
                    cleaned_graphics_px.append(cleaned)
                removed_graphics_backtracks += max(0, len(poly) - len(cleaned))
            graphics_px = cleaned_graphics_px

            filtered_text_px, removed_text_frame = self._filter_outer_frame_polylines_px(
                filtered_text_px,
                img_w=img_w,
                img_h=img_h,
            )
            graphics_px, removed_graphics_frame = self._filter_outer_frame_polylines_px(
                graphics_px,
                img_w=img_w,
                img_h=img_h,
            )
            if graphics_px:
                log(
                    "Method3 layer split: "
                    f"text_paths={len(filtered_text_px)}, "
                    f"graphics_centerline={len(graphics_centerline_px)}, "
                    f"graphics_outline={len(graphics_outline_px)}, "
                    f"graphics_accents={len(graphics_accents_px)}"
                )
            if removed_bottom_text > 0:
                log(f"Method3 cleanup: removed bottom-row text paths={removed_bottom_text}")
            if removed_bottom_graphics > 0:
                log(f"Method3 cleanup: removed bottom-row graphics-glyph paths={removed_bottom_graphics}")
            if removed_left_upper_text > 0:
                log(f"Method3 cleanup: removed left-column text paths={removed_left_upper_text}")
            if removed_left_upper_graphics > 0:
                log(f"Method3 cleanup: removed left-column graphics-glyph paths={removed_left_upper_graphics}")
            if removed_text_backtracks > 0:
                log(f"Method3 cleanup: collapsed text backtracks points={removed_text_backtracks}")
            if removed_graphics_backtracks > 0:
                log(f"Method3 cleanup: collapsed graphics backtracks points={removed_graphics_backtracks}")
            if (removed_text_frame + removed_graphics_frame) > 0:
                log(
                    "Method3 cleanup: removed outer-frame paths="
                    f"{removed_text_frame + removed_graphics_frame}"
                )
            if not filtered_text_px and not graphics_px:
                return False, "Method3 centerline produced no paths."

            sx = float(page_w_mm) / float(max(1, img_w))
            sy = float(page_h_mm) / float(max(1, img_h))
            text_polys_mm: list[list[tuple[float, float]]] = []
            for poly in filtered_text_px:
                p = [(float(x) * sx, float(y) * sy) for x, y in poly]
                if len(p) >= 2 and backend.polyline_length(p) >= 0.25:
                    text_polys_mm.append(p)
            text_polys_mm, removed_text_near_dup = _dedup_near_text_polylines_mm(text_polys_mm)
            if removed_text_near_dup > 0:
                log(f"Method3 cleanup: deduped near text strokes={removed_text_near_dup}")
            graphics_polys_mm: list[list[tuple[float, float]]] = []
            graphics_dist_map = None
            try:
                mask_u8 = (graphics_mask > 0).astype(backend.np.uint8)
                graphics_dist_map = backend.cv2.distanceTransform(mask_u8, backend.cv2.DIST_L2, 3)
            except Exception:
                graphics_dist_map = None
            detail_thick = 0
            detail_extra_passes = 0
            for poly in graphics_px:
                p = [(float(x) * sx, float(y) * sy) for x, y in poly]
                if len(p) >= 2 and backend.polyline_length(p) >= 0.25:
                    graphics_polys_mm.append(p)
                    if graphics_dist_map is None:
                        continue
                    if not _is_detail_polyline_mm(
                        p,
                        page_w_mm=float(page_w_mm),
                        page_h_mm=float(page_h_mm),
                        crop_left_mm=float(getattr(backend, "PAGE_MARGIN_LEFT_MM", 0.0)),
                        crop_right_mm=float(getattr(backend, "PAGE_MARGIN_RIGHT_MM", 0.0)),
                        crop_top_mm=float(getattr(backend, "PAGE_MARGIN_TOP_MM", 0.0)),
                        crop_bottom_mm=float(getattr(backend, "PAGE_MARGIN_BOTTOM_MM", 0.0)),
                    ):
                        continue
                    thick_px = _estimate_polyline_thickness_px(poly, graphics_dist_map)
                    passes = 1
                    offset_mm = 0.0
                    if thick_px >= 8.0:
                        passes = 3
                        offset_mm = 0.07
                    elif thick_px >= 5.4:
                        passes = 2
                        offset_mm = 0.05
                    if passes <= 1:
                        continue
                    detail_thick += 1
                    if passes == 2:
                        p2 = _offset_polyline_mm(p, offset_mm)
                        if len(p2) >= 2 and backend.polyline_length(p2) >= 0.25:
                            graphics_polys_mm.append(p2)
                            detail_extra_passes += 1
                    else:
                        p2 = _offset_polyline_mm(p, offset_mm)
                        p3 = _offset_polyline_mm(p, -offset_mm)
                        if len(p2) >= 2 and backend.polyline_length(p2) >= 0.25:
                            graphics_polys_mm.append(p2)
                            detail_extra_passes += 1
                        if len(p3) >= 2 and backend.polyline_length(p3) >= 0.25:
                            graphics_polys_mm.append(p3)
                            detail_extra_passes += 1
            if detail_extra_passes > 0:
                log(
                    "Method3 detail thick-lines multipass: "
                    f"candidates={detail_thick}, extra_passes={detail_extra_passes}"
                )

            filled_accents_mm = self._extract_pdf_filled_micro_strokes_mm(
                pdf_path=pdf_src,
                page_index=page,
                page_w_mm=page_w_mm,
                page_h_mm=page_h_mm,
                log=log,
            )
            if filled_accents_mm:
                graphics_polys_mm.extend(filled_accents_mm)

            polys_mm = [*text_polys_mm, *graphics_polys_mm]
            polys_mm, removed_bottom_tiny = self._drop_tiny_bottom_artifacts_mm(
                polys_mm,
                page_h_mm=page_h_mm,
            )
            if removed_bottom_tiny > 0:
                log(f"Method3 cleanup: removed tiny bottom artifacts={removed_bottom_tiny}")

            pre_prune_segments = sum(max(0, len(poly) - 1) for poly in polys_mm)
            min_seg_mm = 0.08
            pruned_polys_mm: list[list[tuple[float, float]]] = []
            for poly in polys_mm:
                cleaned = _prune_short_polyline_segments(poly, min_seg_mm=min_seg_mm)
                if len(cleaned) >= 2 and backend.polyline_length(cleaned) >= 0.25:
                    pruned_polys_mm.append(cleaned)
            polys_mm = pruned_polys_mm
            post_prune_segments = sum(max(0, len(poly) - 1) for poly in polys_mm)
            if post_prune_segments < pre_prune_segments:
                log(
                    "Method3 micro-segment prune: "
                    f"segments={pre_prune_segments}->{post_prune_segments}, min={min_seg_mm:.2f} mm"
                )

            straightened = 0
            straightened_polys_mm: list[list[tuple[float, float]]] = []
            for poly in polys_mm:
                fixed = _straighten_axis_aligned_polyline_mm(
                    poly,
                    min_span_mm=8.0,
                    max_thickness_mm=1.8,
                    dominance_ratio=4.5,
                )
                if len(fixed) >= 2 and fixed != poly:
                    straightened += 1
                if len(fixed) >= 2:
                    straightened_polys_mm.append(fixed)
            polys_mm = straightened_polys_mm
            if straightened > 0:
                log(f"Method3 cleanup: straightened axis-aligned lines={straightened}")

            # Conservative stitch in Method3: keep tiny continuity joins, but avoid
            # cross-connecting nearby text and table/frame strokes.
            polys_mm = backend.stitch_polylines(polys_mm, eps=0.03, logger=None, gap_eps=0.03, angle_tol_deg=18.0)
            polys_mm = self._order_polylines_line_lr(
                polys_mm,
                row_tol_mm=float(getattr(backend, "DRAW_ORDER_LINE_TOL_MM", 3.0)),
            )
            if not polys_mm:
                return False, "No usable centerline polylines after cleanup."

            self._write_method3_svg(output_svg, polys_mm, page_w_mm=page_w_mm, page_h_mm=page_h_mm)
            cmd_pdf = [
                backend.find_inkscape(),
                str(output_svg),
                "--export-type=pdf",
                "--export-overwrite",
                "--export-area-page",
                f"--export-filename={output_pdf}",
            ]
            rc_pdf, out_pdf, err_pdf = backend.run_cmd(cmd_pdf, timeout_s=120.0)
            if rc_pdf != 0 or (not output_pdf.exists()) or output_pdf.stat().st_size <= 0:
                return False, (
                    "Inkscape PDF export failed: "
                    f"rc={rc_pdf}, out={(out_pdf or '').strip()[:180]}, err={(err_pdf or '').strip()[:180]}"
                )

            if output_nc is not None:
                ok, msg = backend.run_pipeline_with_corner_calibration(
                    output_svg,
                    log,
                    com=backend.detect_com_port(None),
                    baud=backend.DEFAULT_BAUD,
                    send_to_plotter=False,
                    output_path=output_nc,
                    skip_calibration=True,
                    skip_confirmation=True,
                    corner_mark_size=2.0,
                    feed_travel=backend.FEED_TRAVEL,
                    feed_draw=backend.FEED_DRAW,
                    auto_resume=False,
                )
                if not ok:
                    return False, msg
        return True, ""

    def _resolve_method3_source_pdf(
        self,
        *,
        backend,
        input_path: Path,
        body_font: str,
        formula_font: str,
        work_dir: Path,
        log: LogFn,
    ) -> tuple[bool, Optional[Path], str]:
        ext = input_path.suffix.lower()
        if ext == ".pdf":
            return True, input_path, ""
        if ext not in {".doc", ".docx"}:
            return False, None, f"Method3 page mode supports .doc/.docx/.pdf, got: {ext}"
        pdf_src = work_dir / "source_method3.pdf"
        try:
            backend.word_to_pdf(
                input_path,
                pdf_src,
                log,
                override_font=(body_font or None),
                formula_font=(formula_font or None),
            )
        except Exception as exc:
            return False, None, _format_user_exception(exc, prefix="Word->PDF conversion failed")
        if not pdf_src.exists() or pdf_src.stat().st_size <= 0:
            return False, None, "Word->PDF conversion produced no output."
        return True, pdf_src, ""

    @staticmethod
    def _probe_pdf_page_count(pdf_path: Path) -> int:
        if fitz is None:
            return 0
        try:
            with fitz.open(str(pdf_path)) as doc:
                return max(0, int(doc.page_count))
        except Exception:
            return 0

    @staticmethod
    def _copy_latest_artifacts(
        *,
        svg_src: Path,
        pdf_src: Path,
        nc_src: Optional[Path],
        svg_dst: Path,
        pdf_dst: Path,
        nc_dst: Optional[Path],
    ) -> None:
        if svg_src.exists():
            shutil.copyfile(str(svg_src), str(svg_dst))
        if pdf_src.exists():
            shutil.copyfile(str(pdf_src), str(pdf_dst))
        if nc_src is not None and nc_dst is not None and nc_src.exists():
            shutil.copyfile(str(nc_src), str(nc_dst))

    @staticmethod
    def _run_manual_commands_with_timeout(
        backend,
        com_port: str,
        baud: str,
        commands: list[str],
        *,
        kwargs: dict[str, object],
        timeout_s: float,
    ) -> tuple[bool, str]:
        done = threading.Event()
        result: dict[str, tuple[bool, str]] = {}
        error: dict[str, Exception] = {}

        def _worker() -> None:
            try:
                ok, text = backend.grbl_send_manual_commands(
                    com_port,
                    baud,
                    commands,
                    **kwargs,
                )
                result["value"] = (bool(ok), str(text or ""))
            except Exception as exc:  # pragma: no cover - defensive path
                error["exc"] = exc
            finally:
                done.set()

        threading.Thread(target=_worker, daemon=True, name="grbl-manual-probe").start()
        wait_s = max(0.2, float(timeout_s))
        if not done.wait(wait_s):
            return False, f"Connection probe timed out after {wait_s:.1f}s."
        if "exc" in error:
            exc = error["exc"]
            return False, _format_user_exception(exc)
        return result.get("value", (False, "Connection probe failed."))

    def probe_connection(self, com_port: str, baud: str, log: LogFn) -> tuple[bool, str]:
        backend = self._backend()
        probe_cmds = ["$X", "$I", "?", "$$"]
        probe_kwargs = {
            "soft_reset_first": True,
            "read_tail": True,
            # Probe path should fail fast on missing/busy COM and not block UI for long.
            "serial_timeout_s": 0.60,
            "wake_delay_s": 0.12,
            "reset_delay_s": 0.35,
            "command_delay_s": 0.08,
            "tail_delay_s": 0.20,
            "wake_read_bytes": 2048,
            "tail_read_bytes": 4096,
        }
        ok, text = self._run_manual_commands_with_timeout(
            backend,
            com_port,
            baud,
            probe_cmds,
            kwargs=probe_kwargs,
            timeout_s=6.0,
        )
        if (not ok) and ("unexpected keyword argument" in str(text).lower()):
            # Compatibility fallback for older backend signatures without timing kwargs.
            ok, text = self._run_manual_commands_with_timeout(
                backend,
                com_port,
                baud,
                probe_cmds,
                kwargs={"soft_reset_first": True, "read_tail": True},
                timeout_s=6.0,
            )
        if ok:
            log(f"Connected to {com_port}.")
            return True, text or "ok"
        return False, text

    def emergency_stop(self, com_port: str, baud: str, log: LogFn) -> tuple[bool, str]:
        backend = self._backend()
        try:
            ok, text = backend.grbl_send_manual_commands(
                com_port,
                baud,
                ["!", "M5", "$X", "$1=0", "?"],
                soft_reset_first=True,
                read_tail=True,
            )
        except Exception as exc:
            return False, _format_user_exception(exc, prefix="Emergency stop failed")
        if ok:
            log("Аварийная остановка отправлена.")
        return ok, text

    def manual_commands(
        self,
        com_port: str,
        baud: str,
        commands: list[str],
        *,
        soft_reset_first: bool = False,
        read_tail: bool = True,
    ) -> tuple[bool, str]:
        backend = self._backend()
        try:
            return backend.grbl_send_manual_commands(
                com_port,
                baud,
                commands,
                soft_reset_first=soft_reset_first,
                read_tail=read_tail,
            )
        except Exception as exc:
            return False, _format_user_exception(exc, prefix="Manual command execution failed")

    @contextmanager
    def _track_backend_subprocess(self, ctx: OperationContext) -> Iterator[None]:
        backend = self._backend()
        original_popen = backend.subprocess.Popen

        def tracked_popen(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            ctx.set_active_process(proc)
            return proc

        backend.subprocess.Popen = tracked_popen
        try:
            yield
        finally:
            backend.subprocess.Popen = original_popen
            ctx.set_active_process(None)

    def run_calibration(self, ctx: OperationContext, com_port: str, baud: str, sheet: SheetConfig, log: LogFn) -> tuple[bool, str]:
        backend = self._backend()
        ctx.check_canceled()
        self._configure_sheet(sheet, log)
        with self._track_backend_subprocess(ctx):
            return backend.run_corner_calibration_pipeline(
                log,
                com=com_port,
                baud=baud,
                send_to_plotter=True,
                mark_size=2.0,
            )

    def run_frame(self, ctx: OperationContext, com_port: str, baud: str, sheet: SheetConfig, log: LogFn) -> tuple[bool, str]:
        backend = self._backend()
        ctx.check_canceled()
        self._configure_sheet(sheet, log)
        with self._track_backend_subprocess(ctx):
            return backend.run_frame_pipeline(
                log,
                com=com_port,
                baud=baud,
                send_to_plotter=True,
            )

    def run_draw(
        self,
        ctx: OperationContext,
        input_path: Path,
        com_port: str,
        baud: str,
        sheet: SheetConfig,
        tool_mode: str,
        calibrate_before_draw: bool,
        render_mode: str,
        quality_profile: str,
        force_text_to_path: bool,
        handwriting_enabled: bool,
        handwriting_font: str,
        handwriting_formula_font: str,
        image_contours_mode: str,
        source_page_index: int,
        source_all_pages: bool,
        exact_geometry_mode: bool,
        safe_travel_lift: bool,
        strict_one_to_one: bool,
        log: LogFn,
        sheet_swap_confirm: Callable[[int, int], bool] | None = None,
    ) -> tuple[bool, str]:
        backend = self._backend()
        ctx.check_canceled()
        self.set_tool_mode(tool_mode)
        render_mode_norm, effective_exact_mode, effective_handwriting = resolve_render_flags(
            render_mode,
            exact_geometry_mode=bool(exact_geometry_mode),
            handwriting_enabled=bool(handwriting_enabled),
        )
        # In strict 1:1 mode we must enforce dimensional guard even in handwriting profile.
        backend.EXACT_GEOMETRY_MODE = bool(effective_exact_mode or strict_one_to_one)
        backend.SAFE_PEN_TRAVEL_UP = bool(safe_travel_lift)
        backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 1.0 if bool(strict_one_to_one) else 0.0
        backend.HANDWRITING_TEXT_ENABLED = bool(effective_handwriting)
        selected_hw_font = _resolve_handwriting_font(backend, handwriting_font, log=log)
        selected_formula_font = _resolve_formula_font(backend, handwriting_formula_font, log=log)
        source_page = max(1, int(source_page_index))
        all_pages = bool(source_all_pages)
        backend.HANDWRITING_FONT_FAMILY = selected_hw_font
        backend.HANDWRITING_CYRILLIC_FONT_FAMILY = _select_cyrillic_handwriting_font(backend, selected_hw_font)
        # Lock handwriting pipeline to method #3 for stable single-line output in GUI mode.
        backend.HANDWRITING_SINGLELINE_TTF_BACKEND = "autotrace3"
        backend.HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED = True
        mode = str((image_contours_mode or "always").strip().lower())
        if mode not in {"off", "word_only", "always"}:
            mode = "always"
        backend.IMAGE_CONTOUR_MODE = mode
        backend.IMAGE_CONTOUR_ENABLED = mode != "off"
        backend.IMAGE_CONTOUR_WORD_ONLY = mode == "word_only"
        # Keep PDF import fully non-interactive in GUI mode:
        # avoid launching Inkscape PDF importer (it can show modal import options dialog).
        backend.USE_INKSCAPE_PDF_IMPORT = False
        backend.apply_quality_profile(
            quality=(quality_profile or backend.DEFAULT_QUALITY_PROFILE),
            force_text_to_path=bool(force_text_to_path),
        )
        log(
            "Render mode: "
            f"{render_mode_norm}; "
            f"ExactGeometry={'on' if backend.EXACT_GEOMETRY_MODE else 'off'}; "
            f"Handwriting={'on' if backend.HANDWRITING_TEXT_ENABLED else 'off'}"
        )
        log(f"Drawing profile: {backend.quality_state()}")
        self._configure_sheet(sheet, log)

        previews_dir = self._project_root / "_tmp"
        previews_dir.mkdir(parents=True, exist_ok=True)
        nc_path = previews_dir / "latest_draw.nc"
        svg_path = previews_dir / "latest_draw_vector.svg"
        pdf_path = previews_dir / "latest_draw_vector.pdf"
        ext = input_path.suffix.lower()
        use_method3_page = bool(effective_handwriting) and ext in {".doc", ".docx", ".pdf"}

        if use_method3_page:
            with tempfile.TemporaryDirectory(dir=str(backend.ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
                work = Path(td)
                ok_src, pdf_src, src_msg = self._resolve_method3_source_pdf(
                    backend=backend,
                    input_path=input_path,
                    body_font=selected_hw_font,
                    formula_font=selected_formula_font,
                    work_dir=work,
                    log=log,
                )
                if not ok_src or pdf_src is None:
                    return False, src_msg
                page_count = self._probe_pdf_page_count(pdf_src)
                if all_pages:
                    if page_count <= 0:
                        return False, "Cannot detect page count for all-pages mode."
                    pages = list(range(1, page_count + 1))
                else:
                    if page_count > 0 and source_page > page_count:
                        return False, f"Page {source_page} is out of range (total pages: {page_count})."
                    pages = [source_page]
                log(
                    "Method3 page mode: "
                    f"pages={pages[0]}..{pages[-1]}, body_font='{selected_hw_font}', "
                    f"formula_font='{selected_formula_font}'."
                )
                if len(pages) > 1:
                    log(
                        "Method3 draw: multi-page batch with sheet swap pauses enabled."
                    )
                    if sheet_swap_confirm is None:
                        return (
                            False,
                            "Sheet swap confirmation callback is required for multi-page draw mode.",
                        )

                if calibrate_before_draw:
                    ctx.check_canceled()
                    with self._track_backend_subprocess(ctx):
                        ok_cal, msg_cal = backend.run_corner_calibration_pipeline(
                            log,
                            com=com_port,
                            baud=baud,
                            send_to_plotter=True,
                            mark_size=2.0,
                        )
                    if not ok_cal:
                        return False, msg_cal

                total_plot_time = 0.0
                first_svg: Optional[Path] = None
                first_pdf: Optional[Path] = None
                first_nc: Optional[Path] = None
                for idx, page_no in enumerate(pages, start=1):
                    ctx.check_canceled()
                    page_svg = svg_path if len(pages) == 1 else previews_dir / f"latest_draw_p{page_no}.svg"
                    page_pdf = pdf_path if len(pages) == 1 else previews_dir / f"latest_draw_p{page_no}.pdf"
                    page_nc = nc_path if len(pages) == 1 else previews_dir / f"latest_draw_p{page_no}.nc"
                    with self._track_backend_subprocess(ctx):
                        ok_prep, prep_msg = self._prepare_method3_page(
                            backend=backend,
                            input_path=input_path,
                            source_page_index=page_no,
                            body_font=selected_hw_font,
                            formula_font=selected_formula_font,
                            output_svg=page_svg,
                            output_pdf=page_pdf,
                            output_nc=page_nc,
                            log=log,
                            source_pdf_path=pdf_src,
                            source_page_count=page_count if page_count > 0 else None,
                        )
                    if not ok_prep:
                        return False, prep_msg
                    if first_svg is None:
                        first_svg = page_svg
                        first_pdf = page_pdf
                        first_nc = page_nc
                    ctx.check_canceled()
                    with self._track_backend_subprocess(ctx):
                        plot_time_s = backend.send_to_grbl(
                            page_nc,
                            com_port,
                            baud,
                            log,
                            sleep_after=True,
                            auto_resume=False,
                        )
                    total_plot_time += float(plot_time_s)
                    log(f"Method3 draw: sent page {page_no} ({idx}/{len(pages)}).")
                    if idx < len(pages):
                        ctx.check_canceled()
                        if sheet_swap_confirm is not None:
                            log(
                                f"Sheet swap pause: page {page_no}/{len(pages)} completed. "
                                "Replace paper sheet and confirm to continue."
                            )
                            if not bool(sheet_swap_confirm(page_no, len(pages))):
                                return False, f"Canceled during sheet replacement after page {page_no}."

                if len(pages) > 1 and first_svg is not None and first_pdf is not None and first_nc is not None:
                    self._copy_latest_artifacts(
                        svg_src=first_svg,
                        pdf_src=first_pdf,
                        nc_src=first_nc,
                        svg_dst=svg_path,
                        pdf_dst=pdf_path,
                        nc_dst=nc_path,
                    )

                pages_desc = f"{pages[0]}..{pages[-1]}" if len(pages) > 1 else str(pages[0])
                return (
                    True,
                    f"Done: page(s) {pages_desc} sent. "
                    f"Preview ready: {svg_path} | Preview PDF: {pdf_path} | "
                    f"Plot time: {float(total_plot_time):.1f} s",
                )

        with self._track_backend_subprocess(ctx):
            ok, msg = backend.run_pipeline_with_corner_calibration(
                input_path,
                log,
                com=com_port,
                baud=baud,
                send_to_plotter=True,
                output_path=nc_path,
                skip_calibration=not calibrate_before_draw,
                skip_confirmation=True,
                corner_mark_size=2.0,
                feed_travel=backend.FEED_TRAVEL,
                feed_draw=backend.FEED_DRAW,
                auto_resume=False,
            )
        if not ok:
            return False, msg

        preview_ok, preview_err = self._build_vector_preview_from_gcode(
            nc_path,
            svg_path,
            pdf_path,
            backend=backend,
            log=log,
        )
        if preview_ok:
            suffix = f" | Preview PDF: {pdf_path}" if pdf_path.exists() else ""
            return True, f"{msg} | Preview ready: {svg_path}{suffix}"
        log(f"Preview generation warning: {preview_err}")
        return True, f"{msg} | Preview generation warning: {preview_err}"

    def run_preview(
        self,
        ctx: OperationContext,
        input_path: Path,
        sheet: SheetConfig,
        tool_mode: str,
        render_mode: str,
        quality_profile: str,
        force_text_to_path: bool,
        handwriting_enabled: bool,
        handwriting_font: str,
        handwriting_formula_font: str,
        image_contours_mode: str,
        source_page_index: int,
        source_all_pages: bool,
        exact_geometry_mode: bool,
        safe_travel_lift: bool,
        strict_one_to_one: bool,
        log: LogFn,
    ) -> tuple[bool, str]:
        backend = self._backend()
        ctx.check_canceled()
        self.set_tool_mode(tool_mode)
        render_mode_norm, effective_exact_mode, effective_handwriting = resolve_render_flags(
            render_mode,
            exact_geometry_mode=bool(exact_geometry_mode),
            handwriting_enabled=bool(handwriting_enabled),
        )
        # In strict 1:1 mode we must enforce dimensional guard even in handwriting profile.
        backend.EXACT_GEOMETRY_MODE = bool(effective_exact_mode or strict_one_to_one)
        backend.SAFE_PEN_TRAVEL_UP = bool(safe_travel_lift)
        backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 1.0 if bool(strict_one_to_one) else 0.0
        backend.HANDWRITING_TEXT_ENABLED = bool(effective_handwriting)
        selected_hw_font = _resolve_handwriting_font(backend, handwriting_font, log=log)
        selected_formula_font = _resolve_formula_font(backend, handwriting_formula_font, log=log)
        source_page = max(1, int(source_page_index))
        all_pages = bool(source_all_pages)
        backend.HANDWRITING_FONT_FAMILY = selected_hw_font
        backend.HANDWRITING_CYRILLIC_FONT_FAMILY = _select_cyrillic_handwriting_font(backend, selected_hw_font)
        # Lock handwriting pipeline to method #3 for stable single-line output in GUI mode.
        backend.HANDWRITING_SINGLELINE_TTF_BACKEND = "autotrace3"
        backend.HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED = True
        mode = str((image_contours_mode or "always").strip().lower())
        if mode not in {"off", "word_only", "always"}:
            mode = "always"
        backend.IMAGE_CONTOUR_MODE = mode
        backend.IMAGE_CONTOUR_ENABLED = mode != "off"
        backend.IMAGE_CONTOUR_WORD_ONLY = mode == "word_only"
        # Keep PDF import fully non-interactive in GUI mode:
        # avoid launching Inkscape PDF importer (it can show modal import options dialog).
        backend.USE_INKSCAPE_PDF_IMPORT = False
        backend.apply_quality_profile(
            quality=(quality_profile or backend.DEFAULT_QUALITY_PROFILE),
            force_text_to_path=bool(force_text_to_path),
        )
        log(
            "Render mode: "
            f"{render_mode_norm}; "
            f"ExactGeometry={'on' if backend.EXACT_GEOMETRY_MODE else 'off'}; "
            f"Handwriting={'on' if backend.HANDWRITING_TEXT_ENABLED else 'off'}"
        )
        self._configure_sheet(sheet, log)

        previews_dir = self._project_root / "_tmp"
        previews_dir.mkdir(parents=True, exist_ok=True)
        nc_path = previews_dir / "latest_preview.nc"
        svg_path = previews_dir / "latest_preview_vector.svg"
        pdf_path = previews_dir / "latest_preview_vector.pdf"
        ext = input_path.suffix.lower()
        use_method3_page = bool(effective_handwriting) and ext in {".doc", ".docx", ".pdf"}

        if use_method3_page:
            with tempfile.TemporaryDirectory(dir=str(backend.ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
                work = Path(td)
                ok_src, pdf_src, src_msg = self._resolve_method3_source_pdf(
                    backend=backend,
                    input_path=input_path,
                    body_font=selected_hw_font,
                    formula_font=selected_formula_font,
                    work_dir=work,
                    log=log,
                )
                if not ok_src or pdf_src is None:
                    return False, src_msg
                page_count = self._probe_pdf_page_count(pdf_src)
                if all_pages:
                    if page_count <= 0:
                        return False, "Cannot detect page count for all-pages mode."
                    pages = list(range(1, page_count + 1))
                else:
                    if page_count > 0 and source_page > page_count:
                        return False, f"Page {source_page} is out of range (total pages: {page_count})."
                    pages = [source_page]
                log(
                    "Method3 page preview: "
                    f"pages={pages[0]}..{pages[-1]}, body_font='{selected_hw_font}', "
                    f"formula_font='{selected_formula_font}'."
                )
                first_svg: Optional[Path] = None
                first_pdf: Optional[Path] = None
                first_nc: Optional[Path] = None
                for page_no in pages:
                    ctx.check_canceled()
                    page_svg = svg_path if len(pages) == 1 else previews_dir / f"latest_preview_p{page_no}.svg"
                    page_pdf = pdf_path if len(pages) == 1 else previews_dir / f"latest_preview_p{page_no}.pdf"
                    page_nc = nc_path if len(pages) == 1 else previews_dir / f"latest_preview_p{page_no}.nc"
                    with self._track_backend_subprocess(ctx):
                        ok_prep, prep_msg = self._prepare_method3_page(
                            backend=backend,
                            input_path=input_path,
                            source_page_index=page_no,
                            body_font=selected_hw_font,
                            formula_font=selected_formula_font,
                            output_svg=page_svg,
                            output_pdf=page_pdf,
                            output_nc=page_nc,
                            log=log,
                            source_pdf_path=pdf_src,
                            source_page_count=page_count if page_count > 0 else None,
                        )
                    if not ok_prep:
                        return False, prep_msg
                    if first_svg is None:
                        first_svg = page_svg
                        first_pdf = page_pdf
                        first_nc = page_nc

                if len(pages) > 1 and first_svg is not None and first_pdf is not None and first_nc is not None:
                    self._copy_latest_artifacts(
                        svg_src=first_svg,
                        pdf_src=first_pdf,
                        nc_src=first_nc,
                        svg_dst=svg_path,
                        pdf_dst=pdf_path,
                        nc_dst=nc_path,
                    )
                suffix = f" | PDF: {pdf_path}" if pdf_path.exists() else ""
                return True, f"Preview ready: {svg_path} | G-code: {nc_path}{suffix}"

        with self._track_backend_subprocess(ctx):
            ok, msg = backend.run_pipeline_with_corner_calibration(
                input_path,
                log,
                com=backend.detect_com_port(None),
                baud=backend.DEFAULT_BAUD,
                send_to_plotter=False,
                output_path=nc_path,
                skip_calibration=True,
                skip_confirmation=True,
                corner_mark_size=2.0,
                feed_travel=backend.FEED_TRAVEL,
                feed_draw=backend.FEED_DRAW,
                auto_resume=False,
            )
        if not ok:
            return False, msg

        preview_ok, preview_err = self._build_vector_preview_from_gcode(
            nc_path,
            svg_path,
            pdf_path,
            backend=backend,
            log=log,
        )
        if not preview_ok:
            return False, preview_err

        suffix = f" | PDF: {pdf_path}" if pdf_path.exists() else ""
        return True, f"Preview ready: {svg_path} | G-code: {nc_path}{suffix}"

    def run_wear_test(
        self,
        ctx: OperationContext,
        com_port: str,
        baud: str,
        sheet: SheetConfig,
        log: LogFn,
    ) -> tuple[bool, str]:
        backend = self._backend()
        ctx.check_canceled()
        self.set_tool_mode("pencil")
        self._configure_sheet(sheet, log)
        with self._track_backend_subprocess(ctx):
            return backend.run_pencil_wear_test_pipeline(
                log,
                com=com_port,
                baud=baud,
                send_to_plotter=True,
                output_path=None,
                feed_travel=backend.FEED_TRAVEL,
                feed_draw=backend.FEED_DRAW,
                auto_resume=False,
                levels=8,
                cols=2,
                hatch_step_mm=1.0,
                hatch_loops=1,
                margin_mm=8.0,
                gap_mm=6.0,
            )

    def reset_pencil_after_sharpen(self, log: LogFn) -> tuple[bool, str]:
        backend = self._backend()
        try:
            backend.reset_pencil_state_after_sharpen(log, reason="gui")
            return True, "Состояние карандаша сброшено."
        except Exception as exc:
            return False, _format_user_exception(exc)

    def pencil_banner_text(self) -> tuple[str, bool]:
        backend = self._backend()
        try:
            backend.apply_pencil_profile(backend.load_pencil_profile())
            state = backend.load_pencil_state()
            rem_best, _rem_wear, _rem_interval = backend.pencil_remaining_to_sharpen_m(state)
            wear_now = float(state.get("estimated_wear_mm", 0.0) or 0.0)
            alert = wear_now >= backend.PENCIL_REMIND_WEAR_MM
            if alert:
                return "ЗАТОЧИ КАРАНДАШ", True
            if rem_best != rem_best:  # nan
                return "Карандаш OK", False
            if rem_best == float("inf"):
                return "Карандаш OK. До заточки: inf", False
            return f"Карандаш OK. До заточки: {rem_best:.1f} м", False
        except Exception:
            return "Проверка карандаша недоступна", True
