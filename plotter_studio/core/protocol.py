from __future__ import annotations

import importlib.util
import math
import re
import sys
import tempfile
from xml.etree import ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from serial.tools import list_ports

from .serial_worker import OperationContext

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
            raise RuntimeError(f"Backend script not found: {self._backend_path}")
        spec = importlib.util.spec_from_file_location("plotter_pdf_drawer_backend", str(self._backend_path))
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load backend module.")
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
            return False, f"Preview generation failed: {exc}"

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

    def _run_method3_centerline_page(self, backend, gray, log: LogFn) -> list[list[tuple[float, float]]]:
        autotrace_exe = backend._resolve_autotrace_executable()
        if autotrace_exe is None:
            raise RuntimeError("autotrace.exe not found (tools/autotrace/autotrace.exe).")
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
        return best_polys

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

            if fitz is not None:
                try:
                    with fitz.open(str(pdf_src)) as doc:
                        page_count = int(doc.page_count)
                    if page > page_count:
                        return False, f"Page {page} is out of range (total pages: {page_count})."
                    log(f"Source pages: {page_count}, selected: {page}")
                except Exception:
                    pass

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

            polys_px = self._run_method3_centerline_page(backend, arr, log)
            if not polys_px:
                return False, "Method3 centerline produced no paths."

            sx = float(page_w_mm) / float(max(1, img_w))
            sy = float(page_h_mm) / float(max(1, img_h))
            polys_mm: list[list[tuple[float, float]]] = []
            for poly in polys_px:
                p = [(float(x) * sx, float(y) * sy) for x, y in poly]
                if len(p) >= 2 and backend.polyline_length(p) >= 0.25:
                    polys_mm.append(p)

            polys_mm = backend.stitch_polylines(polys_mm, eps=0.08, logger=None, gap_eps=0.16, angle_tol_deg=35.0)
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

    def probe_connection(self, com_port: str, baud: str, log: LogFn) -> tuple[bool, str]:
        backend = self._backend()
        ok, text = backend.grbl_send_manual_commands(
            com_port,
            baud,
            ["$X", "$I", "?", "$$"],
            soft_reset_first=True,
            read_tail=True,
        )
        if ok:
            log(f"Подключение к {com_port} успешно.")
            return True, text or "ok"
        return False, text

    def emergency_stop(self, com_port: str, baud: str, log: LogFn) -> tuple[bool, str]:
        backend = self._backend()
        ok, text = backend.grbl_send_manual_commands(
            com_port,
            baud,
            ["!", "M5", "$X", "$1=0", "M18", "M84", "?"],
            soft_reset_first=True,
            read_tail=True,
        )
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
        return backend.grbl_send_manual_commands(
            com_port,
            baud,
            commands,
            soft_reset_first=soft_reset_first,
            read_tail=read_tail,
        )

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
        backend.EXACT_GEOMETRY_MODE = bool(effective_exact_mode)
        backend.SAFE_PEN_TRAVEL_UP = bool(safe_travel_lift)
        backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.98 if bool(strict_one_to_one) else 0.0
        backend.HANDWRITING_TEXT_ENABLED = bool(effective_handwriting)
        selected_hw_font = str((handwriting_font or "").strip() or "Marck Script")
        selected_formula_font = str((handwriting_formula_font or "").strip() or "Times New Roman")
        source_page = max(1, int(source_page_index))
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
            log(
                "Method3 page mode: "
                f"page={source_page}, body_font='{selected_hw_font}', formula_font='{selected_formula_font}'."
            )
            with self._track_backend_subprocess(ctx):
                ok_prep, prep_msg = self._prepare_method3_page(
                    backend=backend,
                    input_path=input_path,
                    source_page_index=source_page,
                    body_font=selected_hw_font,
                    formula_font=selected_formula_font,
                    output_svg=svg_path,
                    output_pdf=pdf_path,
                    output_nc=nc_path,
                    log=log,
                )
            if not ok_prep:
                return False, prep_msg

            ctx.check_canceled()
            if calibrate_before_draw:
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
            ctx.check_canceled()
            with self._track_backend_subprocess(ctx):
                plot_time_s = backend.send_to_grbl(
                    nc_path,
                    com_port,
                    baud,
                    log,
                    sleep_after=True,
                    auto_resume=False,
                )
            return (
                True,
                f"Done: page {source_page} sent. "
                f"Preview ready: {svg_path} | Preview PDF: {pdf_path} | "
                f"Plot time: {float(plot_time_s):.1f} s",
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
        backend.EXACT_GEOMETRY_MODE = bool(effective_exact_mode)
        backend.SAFE_PEN_TRAVEL_UP = bool(safe_travel_lift)
        backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.98 if bool(strict_one_to_one) else 0.0
        backend.HANDWRITING_TEXT_ENABLED = bool(effective_handwriting)
        selected_hw_font = str((handwriting_font or "").strip() or "Marck Script")
        selected_formula_font = str((handwriting_formula_font or "").strip() or "Times New Roman")
        source_page = max(1, int(source_page_index))
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
            log(
                "Method3 page preview: "
                f"page={source_page}, body_font='{selected_hw_font}', formula_font='{selected_formula_font}'."
            )
            with self._track_backend_subprocess(ctx):
                ok_prep, prep_msg = self._prepare_method3_page(
                    backend=backend,
                    input_path=input_path,
                    source_page_index=source_page,
                    body_font=selected_hw_font,
                    formula_font=selected_formula_font,
                    output_svg=svg_path,
                    output_pdf=pdf_path,
                    output_nc=nc_path,
                    log=log,
                )
            if not ok_prep:
                return False, prep_msg
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
            return False, f"Ошибка сброса состояния карандаша: {exc}"

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
