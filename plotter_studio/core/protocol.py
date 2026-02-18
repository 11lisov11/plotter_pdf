from __future__ import annotations

import importlib.util
import math
import re
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Optional

from serial.tools import list_ports

from .serial_worker import OperationContext


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
        quality_profile: str,
        force_text_to_path: bool,
        exact_geometry_mode: bool,
        safe_travel_lift: bool,
        strict_one_to_one: bool,
        log: LogFn,
    ) -> tuple[bool, str]:
        backend = self._backend()
        ctx.check_canceled()
        self.set_tool_mode(tool_mode)
        backend.EXACT_GEOMETRY_MODE = bool(exact_geometry_mode)
        backend.SAFE_PEN_TRAVEL_UP = bool(safe_travel_lift)
        backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.98 if bool(strict_one_to_one) else 0.0
        backend.apply_quality_profile(
            quality=(quality_profile or backend.DEFAULT_QUALITY_PROFILE),
            force_text_to_path=bool(force_text_to_path),
        )
        log(f"Drawing profile: {backend.quality_state()}")
        self._configure_sheet(sheet, log)
        with self._track_backend_subprocess(ctx):
            return backend.run_pipeline_with_corner_calibration(
                input_path,
                log,
                com=com_port,
                baud=baud,
                send_to_plotter=True,
                output_path=None,
                skip_calibration=not calibrate_before_draw,
                skip_confirmation=True,
                corner_mark_size=2.0,
                feed_travel=backend.FEED_TRAVEL,
                feed_draw=backend.FEED_DRAW,
                auto_resume=False,
            )

    def run_preview(
        self,
        ctx: OperationContext,
        input_path: Path,
        sheet: SheetConfig,
        tool_mode: str,
        quality_profile: str,
        force_text_to_path: bool,
        exact_geometry_mode: bool,
        safe_travel_lift: bool,
        strict_one_to_one: bool,
        log: LogFn,
    ) -> tuple[bool, str]:
        backend = self._backend()
        ctx.check_canceled()
        self.set_tool_mode(tool_mode)
        backend.EXACT_GEOMETRY_MODE = bool(exact_geometry_mode)
        backend.SAFE_PEN_TRAVEL_UP = bool(safe_travel_lift)
        backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.98 if bool(strict_one_to_one) else 0.0
        backend.apply_quality_profile(
            quality=(quality_profile or backend.DEFAULT_QUALITY_PROFILE),
            force_text_to_path=bool(force_text_to_path),
        )
        self._configure_sheet(sheet, log)

        previews_dir = self._project_root / "_tmp" / "previews"
        previews_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stem = re.sub(r"[^0-9A-Za-zА-Яа-я_\-]+", "_", input_path.stem).strip("_") or "preview"
        nc_path = previews_dir / f"{safe_stem}_{stamp}.nc"
        svg_path = previews_dir / f"{safe_stem}_{stamp}.svg"

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

        try:
            lines = nc_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            polylines = _gcode_to_polylines(
                lines,
                z_up=float(backend.Z_UP),
                z_down=float(backend.Z_DOWN),
            )
            _write_svg_preview(polylines, svg_path)
            log(f"Preview SVG: {svg_path}")
        except Exception as exc:
            return False, f"Ошибка генерации SVG-предпросмотра: {exc}"

        return True, f"Предпросмотр готов: {svg_path} | G-code: {nc_path}"

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
