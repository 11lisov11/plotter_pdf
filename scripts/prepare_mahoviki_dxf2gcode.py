from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Iterable

import fitz  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import plotter_pdf_drawer as backend

MM_TO_PT = 72.0 / 25.4
DXF2GCODE = PROJECT_ROOT / "tools" / "dxf2gcode" / "dxf2gcode" / "dxf2gcode.py"
MAHOVIKI_DIR = PROJECT_ROOT / "Компьютерная графика" / "Маховики"
SOURCE_PDF_DIR = MAHOVIKI_DIR / "_generated_pdf"
OUT_DIR = MAHOVIKI_DIR / "dwg2gcode"
PLOTTER_W_MM = 180.0
PLOTTER_H_MM = 274.0
PLOTTER_MARGIN_MM = 4.0


Point = tuple[float, float]
Polyline = list[Point]


def _pdf_point_to_mm(point: fitz.Point, page_h_mm: float) -> Point:
    x = float(point.x) * 25.4 / 72.0
    y = page_h_mm - (float(point.y) * 25.4 / 72.0)
    return x, y


def _dist(a: Point, b: Point) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1.0 - t
    return (
        (u**3 * p0[0]) + (3.0 * u * u * t * p1[0]) + (3.0 * u * t * t * p2[0]) + (t**3 * p3[0]),
        (u**3 * p0[1]) + (3.0 * u * u * t * p1[1]) + (3.0 * u * t * t * p2[1]) + (t**3 * p3[1]),
    )


def _append_polyline(polylines: list[Polyline], current: Polyline) -> None:
    cleaned: Polyline = []
    for pt in current:
        if not cleaned or _dist(cleaned[-1], pt) >= 0.03:
            cleaned.append(pt)
    if len(cleaned) >= 2:
        polylines.append(cleaned)


def _pdf_to_polylines(pdf_path: Path) -> tuple[list[Polyline], tuple[float, float]]:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        page_w_mm = float(page.rect.width) * 25.4 / 72.0
        page_h_mm = float(page.rect.height) * 25.4 / 72.0
        polylines: list[Polyline] = []
        for drawing in page.get_drawings():
            current: Polyline = []
            for item in drawing.get("items", []):
                if not item:
                    continue
                op = item[0]
                if op == "l" and len(item) >= 3:
                    a = _pdf_point_to_mm(item[1], page_h_mm)
                    b = _pdf_point_to_mm(item[2], page_h_mm)
                    if _dist(a, b) >= 0.03:
                        if current and _dist(current[-1], a) > 0.10:
                            _append_polyline(polylines, current)
                            current = []
                        if not current:
                            current = [a]
                        current.append(b)
                elif op == "re" and len(item) >= 2:
                    _append_polyline(polylines, current)
                    current = []
                    rect = item[1]
                    x0 = float(rect.x0) * 25.4 / 72.0
                    x1 = float(rect.x1) * 25.4 / 72.0
                    y0 = page_h_mm - (float(rect.y0) * 25.4 / 72.0)
                    y1 = page_h_mm - (float(rect.y1) * 25.4 / 72.0)
                    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
                    _append_polyline(polylines, pts)
                elif op == "c" and len(item) >= 5:
                    p0 = _pdf_point_to_mm(item[1], page_h_mm)
                    p1 = _pdf_point_to_mm(item[2], page_h_mm)
                    p2 = _pdf_point_to_mm(item[3], page_h_mm)
                    p3 = _pdf_point_to_mm(item[4], page_h_mm)
                    samples = [_cubic(p0, p1, p2, p3, step / 16.0) for step in range(17)]
                    if current and _dist(current[-1], samples[0]) > 0.10:
                        _append_polyline(polylines, current)
                        current = []
                    if not current:
                        current = [samples[0]]
                    current.extend(samples[1:])
            _append_polyline(polylines, current)
        return polylines, (page_w_mm, page_h_mm)
    finally:
        doc.close()


def _write_dxf(polylines: list[Polyline], dxf_path: Path) -> None:
    lines = [
        "0",
        "SECTION",
        "2",
        "HEADER",
        "9",
        "$ACADVER",
        "1",
        "AC1009",
        "0",
        "ENDSEC",
        "0",
        "SECTION",
        "2",
        "ENTITIES",
    ]
    for idx, poly in enumerate(polylines):
        if len(poly) < 2:
            continue
        layer = f"P{idx:05d}"
        lines.extend(
            [
                "0",
                "POLYLINE",
                "8",
                layer,
                "66",
                "1",
                "70",
                "0",
            ]
        )
        for pt in poly:
            lines.extend(
                [
                    "0",
                    "VERTEX",
                    "8",
                    layer,
                    "10",
                    f"{pt[0]:.6f}",
                    "20",
                    f"{pt[1]:.6f}",
                    "30",
                    "0.0",
                ]
            )
        lines.extend(["0", "SEQEND"])
    lines.extend(["0", "ENDSEC", "0", "EOF", ""])
    dxf_path.write_text("\n".join(lines), encoding="ascii")


def _run_dxf2gcode(dxf_path: Path, raw_gcode: Path) -> dict[str, object]:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    ascii_dir = PROJECT_ROOT / "_tmp" / "dxf2gcode_ascii" / f"{dxf_path.stem}_{time.time_ns()}"
    ascii_dir.mkdir(parents=True, exist_ok=True)
    ascii_dxf = ascii_dir / "input.dxf"
    ascii_raw = ascii_dir / "output.ngc"
    shutil.copy2(dxf_path, ascii_dxf)
    cmd = [sys.executable, str(DXF2GCODE), "-q", "-e", str(ascii_raw), str(ascii_dxf)]
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
    )
    if ascii_raw.exists():
        shutil.copy2(ascii_raw, raw_gcode)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "command": cmd,
    }


def _strip_comments(line: str) -> str:
    line = re.sub(r"\([^)]*\)", " ", line)
    line = line.split(";", 1)[0]
    return line.strip()


def _words(line: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for letter, value in re.findall(r"([A-Za-z])\s*([-+]?\d+(?:\.\d+)?)", line):
        out[letter.upper()] = float(value)
    return out


def _motion(line: str, previous: str | None) -> str | None:
    match = re.search(r"(?i)(?:^|\s)G0*([0123])(?:\s|$)", line)
    if match:
        return "G" + match.group(1)
    return previous


def _arc_points(start: Point, end: Point, center: Point, *, clockwise: bool) -> list[Point]:
    radius = max(1e-9, _dist(start, center))
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    if clockwise:
        if a1 >= a0:
            a1 -= 2.0 * math.pi
    else:
        if a1 <= a0:
            a1 += 2.0 * math.pi
    sweep = abs(a1 - a0)
    steps = max(6, min(96, int(math.ceil(sweep * radius / 1.0))))
    return [
        (center[0] + radius * math.cos(a0 + (a1 - a0) * idx / steps), center[1] + radius * math.sin(a0 + (a1 - a0) * idx / steps))
        for idx in range(1, steps + 1)
    ]


def _raw_gcode_to_polylines(raw_gcode: Path) -> list[Polyline]:
    x = y = 0.0
    z = float(backend.Z_UP)
    modal: str | None = None
    drawing = False
    current: Polyline = []
    polylines: list[Polyline] = []

    def finish() -> None:
        nonlocal current
        if len(current) >= 2:
            polylines.append(current)
        current = []

    for raw in raw_gcode.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = _strip_comments(raw)
        if not line:
            continue
        modal = _motion(line, modal)
        word = _words(line)
        old_x, old_y, old_z = x, y, z
        if "X" in word:
            x = float(word["X"])
        if "Y" in word:
            y = float(word["Y"])
        if "Z" in word:
            z = float(word["Z"])

        if "Z" in word and z >= 0.0 and old_z < 0.0:
            finish()
            drawing = False
        if "Z" in word and z < 0.0 and old_z >= 0.0:
            current = [(old_x, old_y)]
            drawing = True

        has_xy = "X" in word or "Y" in word
        if has_xy and drawing and z < 0.0 and modal in {"G1", "G2", "G3"}:
            if not current:
                current = [(old_x, old_y)]
            if _dist(current[-1], (old_x, old_y)) > 0.02:
                finish()
                current = [(old_x, old_y)]
            if modal == "G1":
                if _dist(current[-1], (x, y)) >= 0.02:
                    current.append((x, y))
            else:
                i = float(word.get("I", 0.0))
                j = float(word.get("J", 0.0))
                pts = _arc_points((old_x, old_y), (x, y), (old_x + i, old_y + j), clockwise=(modal == "G2"))
                for pt in pts:
                    if _dist(current[-1], pt) >= 0.02:
                        current.append(pt)
    finish()
    return polylines


def _dedupe_segments(polylines: list[Polyline]) -> list[Polyline]:
    seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    out: list[Polyline] = []

    def key(a: Point, b: Point) -> tuple[tuple[int, int], tuple[int, int]]:
        pa = (round(a[0] * 50.0), round(a[1] * 50.0))
        pb = (round(b[0] * 50.0), round(b[1] * 50.0))
        return (pa, pb) if pa <= pb else (pb, pa)

    for poly in polylines:
        current: Polyline = []
        for a, b in zip(poly, poly[1:]):
            if _dist(a, b) < 0.02:
                continue
            k = key(a, b)
            if k in seen:
                if len(current) >= 2:
                    out.append(current)
                current = []
                continue
            seen.add(k)
            if not current or _dist(current[-1], a) > 0.02:
                if len(current) >= 2:
                    out.append(current)
                current = [a]
            current.append(b)
        if len(current) >= 2:
            out.append(current)
    return out


def _bbox(polylines: list[Polyline]) -> tuple[float, float, float, float]:
    xs = [float(x) for poly in polylines for x, _ in poly]
    ys = [float(y) for poly in polylines for _, y in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _fit_to_plotter(polylines: list[Polyline]) -> list[Polyline]:
    x0, y0, x1, y1 = _bbox(polylines)
    width = max(1e-9, x1 - x0)
    height = max(1e-9, y1 - y0)
    target_w = PLOTTER_W_MM - (2.0 * PLOTTER_MARGIN_MM)
    target_h = PLOTTER_H_MM - (2.0 * PLOTTER_MARGIN_MM)
    scale = min(target_w / width, target_h / height)
    used_w = width * scale
    used_h = height * scale
    ox = PLOTTER_MARGIN_MM + (target_w - used_w) * 0.5
    oy = PLOTTER_MARGIN_MM + (target_h - used_h) * 0.5
    fitted: list[Polyline] = []
    for poly in polylines:
        fitted.append(
            [
                (
                    ox + (float(x) - x0) * scale,
                    -(oy + (float(y) - y0) * scale),
                )
                for x, y in poly
            ]
        )
    return fitted


def _write_plotter_gcode(polylines: list[Polyline], out_gcode: Path) -> None:
    feed_z = float(getattr(backend, "FEED_Z", getattr(backend, "FEED_Z_UP", 1000.0)))
    lines = [
        "G21",
        "G90",
        "G17",
        f"G0 Z{float(backend.Z_UP):.4f}",
    ]
    for poly in polylines:
        if len(poly) < 2:
            continue
        x0, y0 = poly[0]
        lines.append(f"G0 X{x0:.4f} Y{y0:.4f} F{float(backend.FEED_TRAVEL):.1f}")
        lines.append(f"G1 Z{float(backend.Z_DOWN):.4f} F{feed_z:.1f}")
        for x, y in poly[1:]:
            lines.append(f"G1 X{x:.4f} Y{y:.4f} F{float(backend.FEED_DRAW):.1f}")
        lines.append(f"G1 Z{float(backend.Z_UP):.4f} F{feed_z:.1f}")
    lines.extend(["G0 X0.0000 Y0.0000", "M2", ""])
    out_gcode.write_text("\n".join(lines), encoding="utf-8")


def _render_preview(polylines: list[Polyline], out_pdf: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=PLOTTER_W_MM * MM_TO_PT, height=PLOTTER_H_MM * MM_TO_PT)
        shape = page.new_shape()
        for poly in polylines:
            if len(poly) < 2:
                continue
            pts = [(float(x) * MM_TO_PT, (PLOTTER_H_MM + float(y)) * MM_TO_PT) for x, y in poly]
            for a, b in zip(pts, pts[1:]):
                shape.draw_line(fitz.Point(*a), fitz.Point(*b))
        shape.finish(color=(0, 0, 0), width=0.18 * MM_TO_PT)
        shape.commit()
        doc.save(str(out_pdf))
    finally:
        doc.close()


def _draw_length(polylines: Iterable[Polyline]) -> float:
    return sum(_dist(a, b) for poly in polylines for a, b in zip(poly, poly[1:]))


def prepare_one(pdf_path: Path) -> dict[str, object]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    dxf_path = OUT_DIR / f"{stem}_dxf2gcode_input.dxf"
    raw_gcode = OUT_DIR / f"{stem}_dxf2gcode_raw.ngc"
    plotter_gcode = OUT_DIR / f"{stem}_dxf2gcode.gcode"
    preview_pdf = OUT_DIR / f"{stem}_dxf2gcode_preview.pdf"

    source_polylines, page_size_mm = _pdf_to_polylines(pdf_path)
    _write_dxf(source_polylines, dxf_path)
    run = _run_dxf2gcode(dxf_path, raw_gcode)
    if int(run["returncode"]) != 0 or not raw_gcode.exists():
        return {
            "source_pdf": str(pdf_path),
            "ok": False,
            "message": "DXF2GCODE failed",
            "dxf": str(dxf_path),
            "raw_gcode": str(raw_gcode),
            "run": run,
        }

    raw_polys = _raw_gcode_to_polylines(raw_gcode)
    deduped = _dedupe_segments(raw_polys)
    fitted = _fit_to_plotter(deduped)
    _write_plotter_gcode(fitted, plotter_gcode)
    _render_preview(fitted, preview_pdf)
    x0, y0, x1, y1 = _bbox(fitted)
    return {
        "source_pdf": str(pdf_path),
        "ok": True,
        "page_size_mm": [round(page_size_mm[0], 3), round(page_size_mm[1], 3)],
        "pdf_polylines": len(source_polylines),
        "pdf_segments": sum(max(0, len(poly) - 1) for poly in source_polylines),
        "raw_polylines": len(raw_polys),
        "deduped_polylines": len(deduped),
        "draw_length_m": round(_draw_length(fitted) / 1000.0, 3),
        "bounds_mm": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
        "dxf": str(dxf_path),
        "raw_gcode": str(raw_gcode),
        "plotter_gcode": str(plotter_gcode),
        "preview_pdf": str(preview_pdf),
        "run": run,
    }


def main() -> int:
    pdfs = sorted(SOURCE_PDF_DIR.glob("*.pdf"))
    if not DXF2GCODE.exists():
        print(f"DXF2GCODE not found: {DXF2GCODE}", file=sys.stderr)
        return 2
    if not pdfs:
        print(f"No source PDFs found: {SOURCE_PDF_DIR}", file=sys.stderr)
        return 2
    reports = []
    for pdf in pdfs:
        print(f"processing {pdf.name}")
        report = prepare_one(pdf)
        reports.append(report)
        print(f"  ok={report.get('ok')} gcode={report.get('plotter_gcode', report.get('raw_gcode'))}")
    (OUT_DIR / "dxf2gcode_report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(bool(row.get("ok")) for row in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
