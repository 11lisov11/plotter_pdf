#!/usr/bin/env python
from __future__ import annotations
# ruff: noqa: E402

import argparse
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # type: ignore
import numpy as np  # type: ignore

import src.plotter_pdf_drawer as backend


def _log(msg: str) -> None:
    print(str(msg))


def _normalize_word_font_arg(value: str) -> str:
    raw = str(value or "").strip().strip("'").strip('"')
    if not raw:
        return ""
    normalizer = getattr(backend, "_normalize_word_font_name", None)
    if callable(normalizer):
        try:
            return str(normalizer(raw, "") or "").strip()
        except Exception:
            pass
    return str(backend.normalize_handwriting_font_name(raw)).strip()


def _word_to_pdf_mixed_fonts(
    word_path: Path,
    pdf_path: Path,
    *,
    body_font: Optional[str],
    formula_font: Optional[str],
) -> None:
    body = _normalize_word_font_arg(body_font or "")
    formula = _normalize_word_font_arg(formula_font or "")
    backend.word_to_pdf(
        word_path,
        pdf_path,
        _log,
        override_font=(body or None),
        formula_font=(formula or None),
    )


def _export_pdf_page_png(pdf_path: Path, png_path: Path, *, page: int, dpi: int) -> None:
    exe = backend.find_inkscape()
    cmd = [
        exe,
        str(pdf_path),
        "--export-type=png",
        "--export-overwrite",
        "--export-area-page",
        f"--export-filename={png_path}",
        "--export-dpi",
        str(int(max(72, dpi))),
        "--pdf-page",
        str(max(1, int(page))),
        "--pdf-poppler",
    ]
    rc, out, err = backend.run_cmd(cmd, timeout_s=120.0)
    if rc != 0 or not png_path.exists() or png_path.stat().st_size <= 0:
        raise RuntimeError(
            "Inkscape PNG export failed: "
            f"rc={rc}, out={(out or '').strip()[:200]}, err={(err or '').strip()[:200]}"
        )


def _threshold_candidates(gray: np.ndarray) -> List[int]:
    cands = int(max(3, min(17, backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CANDIDATES)))
    vals = [int(round(256.0 * (1 + i) / float(cands + 1))) for i in range(cands)]
    try:
        otsu_thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        vals.append(int(max(1, min(254, int(otsu_thr)))))
    except Exception:
        pass
    vals.append(int(max(1, min(254, int(backend.HANDWRITING_SINGLELINE_TTF_BIN_THRESHOLD)))))
    vals = [max(1, min(254, int(v))) for v in vals]
    return list(dict.fromkeys(vals))


def _score_polylines_px(
    polys: List[List[Tuple[float, float]]],
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


def _centerline_method3_page(gray: np.ndarray) -> List[List[Tuple[float, float]]]:
    autotrace_exe = backend._resolve_autotrace_executable()
    if autotrace_exe is None:
        raise RuntimeError("autotrace.exe not found (tools/autotrace/autotrace.exe).")

    if gray.ndim != 2:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    thresholds = _threshold_candidates(gray)
    h, w = gray.shape[:2]

    best_score = -1e30
    best_thr = thresholds[0]
    best_polys: List[List[Tuple[float, float]]] = []

    for idx, thr in enumerate(thresholds):
        mask = ((gray < int(thr)).astype(np.uint8)) * 255
        if np.count_nonzero(mask) <= 0:
            continue
        try:
            kernel = np.ones((2, 2), dtype=np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        except Exception:
            pass

        binary = np.where(mask > 0, 0, 255).astype(np.uint8)
        polys = backend._run_autotrace_centerline_on_binary(
            binary,
            autotrace_exe=autotrace_exe,
            error_threshold=float(backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_ERROR_THRESHOLD),
            filter_iterations=int(backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_FILTER_ITERATIONS),
            curve_step_px=float(backend.HANDWRITING_SINGLELINE_TTF_AUTOTRACE_CURVE_STEP_PX),
        )
        if not polys:
            continue

        cleaned: List[List[Tuple[float, float]]] = []
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

        score = _score_polylines_px(cleaned, idx=idx, total=len(thresholds), w=w, h=h)
        if score > best_score:
            best_score = score
            best_thr = int(thr)
            best_polys = cleaned

    if not best_polys:
        return []
    _log(f"Method3 centerline: threshold={best_thr}, candidates={len(thresholds)}, paths={len(best_polys)}")
    return best_polys


def _to_mm_polylines(
    polys_px: List[List[Tuple[float, float]]],
    *,
    img_w: int,
    img_h: int,
    page_w_mm: float,
    page_h_mm: float,
) -> List[List[Tuple[float, float]]]:
    sx = float(page_w_mm) / float(max(1, img_w))
    sy = float(page_h_mm) / float(max(1, img_h))
    out: List[List[Tuple[float, float]]] = []
    for poly in polys_px:
        p = [(float(x) * sx, float(y) * sy) for x, y in poly]
        if len(p) >= 2 and backend.polyline_length(p) >= 0.25:
            out.append(p)
    out = backend.stitch_polylines(out, eps=0.08, logger=None, gap_eps=0.16, angle_tol_deg=35.0)
    out = backend.reorder_polylines(out, logger=None)
    return out


def _write_svg_paths(
    out_svg: Path,
    polys_mm: List[List[Tuple[float, float]]],
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


def _export_svg_pdf(svg_path: Path, pdf_path: Path) -> None:
    exe = backend.find_inkscape()
    cmd = [
        exe,
        str(svg_path),
        "--export-type=pdf",
        "--export-overwrite",
        "--export-area-page",
        f"--export-filename={pdf_path}",
    ]
    rc, out, err = backend.run_cmd(cmd, timeout_s=120.0)
    if rc != 0 or not pdf_path.exists() or pdf_path.stat().st_size <= 0:
        raise RuntimeError(
            "Inkscape PDF export failed: "
            f"rc={rc}, out={(out or '').strip()[:200]}, err={(err or '').strip()[:200]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Method3 centerline for whole page (text/formulas/graph).")
    parser.add_argument("input", help="Input .doc/.docx/.pdf")
    parser.add_argument("--page", type=int, default=1, help="PDF page number (1-based)")
    parser.add_argument("--dpi", type=int, default=420, help="Raster DPI before centerline")
    parser.add_argument(
        "--body-font",
        default="",
        help="Word export font for regular text (handwritten), e.g. 'ofont.ru_Veles.ttf' or installed family.",
    )
    parser.add_argument(
        "--formula-font",
        default="",
        help="Word export font for OMath formulas, e.g. 'Times New Roman'.",
    )
    parser.add_argument("--output-prefix", default="_tmp/latest_method3", help="Output prefix without extension")
    parser.add_argument("--emit-nc", action="store_true", help="Also emit NC with existing pipeline")
    args = parser.parse_args()

    in_path = Path(args.input).resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"Input not found: {in_path}")

    prefix = Path(args.output_prefix).resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    out_svg = prefix.with_suffix(".svg")
    out_pdf = prefix.with_suffix(".pdf")
    out_nc = prefix.with_suffix(".nc")

    with tempfile.TemporaryDirectory(dir=str(backend.ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
        work = Path(td)
        if in_path.suffix.lower() in {".doc", ".docx"}:
            pdf = work / "source.pdf"
            body_font = _normalize_word_font_arg(str(args.body_font or ""))
            formula_font = _normalize_word_font_arg(str(args.formula_font or ""))
            if body_font:
                _log(f"Word export: body font='{body_font}'")
            if formula_font:
                _log(f"Word export: formula font='{formula_font}'")
            _word_to_pdf_mixed_fonts(
                in_path,
                pdf,
                body_font=(body_font or None),
                formula_font=(formula_font or None),
            )
        elif in_path.suffix.lower() == ".pdf":
            pdf = in_path
        else:
            raise RuntimeError("Only .doc/.docx/.pdf are supported for method3-page mode.")

        png = work / "page.png"
        _export_pdf_page_png(pdf, png, page=int(args.page), dpi=int(args.dpi))
        arr = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
        if arr is None or arr.size <= 0:
            raise RuntimeError("Failed to load exported page PNG.")

        img_h, img_w = arr.shape[:2]
        page_w_mm = float(img_w) * 25.4 / float(max(1, int(args.dpi)))
        page_h_mm = float(img_h) * 25.4 / float(max(1, int(args.dpi)))

        polys_px = _centerline_method3_page(arr)
        if not polys_px:
            raise RuntimeError("Method3 centerline produced no paths.")
        polys_mm = _to_mm_polylines(
            polys_px,
            img_w=img_w,
            img_h=img_h,
            page_w_mm=page_w_mm,
            page_h_mm=page_h_mm,
        )
        if not polys_mm:
            raise RuntimeError("No usable centerline polylines after cleanup.")

        _write_svg_paths(out_svg, polys_mm, page_w_mm=page_w_mm, page_h_mm=page_h_mm)
        _export_svg_pdf(out_svg, out_pdf)

    _log(f"Saved SVG: {out_svg}")
    _log(f"Saved PDF: {out_pdf}")

    if args.emit_nc:
        cmd = [
            sys.executable,
            str((ROOT / "src" / "plotter_pdf_drawer.py").resolve()),
            str(out_svg),
            "--dry-run",
            "--output",
            str(out_nc),
            "--draw-order",
            "line_lr",
            "--sheet-format",
            "a4",
            "--no-arcs",
        ]
        rc = backend.run_cmd(cmd, timeout_s=600.0)
        if rc[0] != 0 or not out_nc.exists():
            raise RuntimeError(f"NC generation failed: {rc[2] or rc[1]}")
        _log(f"Saved NC: {out_nc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
