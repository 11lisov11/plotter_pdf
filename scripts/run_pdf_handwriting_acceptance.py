from __future__ import annotations
# ruff: noqa: E402

import argparse
import json
import math
import shutil
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plotter_studio.core.protocol import BackendBridge, SheetConfig, _gcode_to_polylines
from plotter_studio.core.serial_worker import OperationContext


class _DummySignal:
    def emit(self, *_args, **_kwargs) -> None:
        return


class _DummyWorker:
    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self.log_line = _DummySignal()
        self.progress = _DummySignal()

    def set_active_process(self, _proc) -> None:
        return


def _segment_key(a: tuple[float, float], b: tuple[float, float], *, ndigits: int = 3) -> tuple[tuple[float, float], tuple[float, float]]:
    p0 = (round(float(a[0]), ndigits), round(float(a[1]), ndigits))
    p1 = (round(float(b[0]), ndigits), round(float(b[1]), ndigits))
    return (p0, p1) if p0 <= p1 else (p1, p0)


def _polyline_length(poly: list[tuple[float, float]]) -> float:
    if len(poly) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(poly)):
        x0, y0 = poly[i - 1]
        x1, y1 = poly[i]
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def _analyze_gcode(gcode_path: Path, *, z_up: float, z_down: float) -> dict[str, Any]:
    lines = gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    polylines = _gcode_to_polylines(lines, z_up=float(z_up), z_down=float(z_down))
    seg_counter: Counter[tuple[tuple[float, float], tuple[float, float]]] = Counter()
    total_segments = 0
    total_draw_len = 0.0
    xs: list[float] = []
    ys: list[float] = []
    for poly in polylines:
        if len(poly) < 2:
            continue
        total_draw_len += _polyline_length(poly)
        for i in range(1, len(poly)):
            a = poly[i - 1]
            b = poly[i]
            total_segments += 1
            seg_counter[_segment_key(a, b)] += 1
            xs.extend([float(a[0]), float(b[0])])
            ys.extend([float(a[1]), float(b[1])])
    duplicate_segments = sum(max(0, cnt - 1) for cnt in seg_counter.values())
    duplicate_ratio = (float(duplicate_segments) / float(total_segments)) if total_segments > 0 else 0.0
    tiny_segments = 0
    short_segments = 0
    for poly in polylines:
        for i in range(1, len(poly)):
            a = poly[i - 1]
            b = poly[i]
            seg_len = math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
            if seg_len < 0.12:
                tiny_segments += 1
            if seg_len < 0.25:
                short_segments += 1
    tiny_ratio = (float(tiny_segments) / float(total_segments)) if total_segments > 0 else 0.0
    short_ratio = (float(short_segments) / float(total_segments)) if total_segments > 0 else 0.0
    bounds = {
        "x_min": min(xs) if xs else 0.0,
        "x_max": max(xs) if xs else 0.0,
        "y_min": min(ys) if ys else 0.0,
        "y_max": max(ys) if ys else 0.0,
    }
    return {
        "polylines": len(polylines),
        "segments_total": int(total_segments),
        "segments_duplicate": int(duplicate_segments),
        "segments_duplicate_ratio": float(duplicate_ratio),
        "segments_tiny_lt_0_12mm": int(tiny_segments),
        "segments_tiny_ratio": float(tiny_ratio),
        "segments_short_lt_0_25mm": int(short_segments),
        "segments_short_ratio": float(short_ratio),
        "draw_length_mm": float(total_draw_len),
        "bounds": bounds,
    }


def _copy_latest_artifacts(project_root: Path, out_dir: Path, stem: str) -> dict[str, str]:
    tmp = project_root / "_tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "svg": (tmp / "latest_preview_vector.svg", out_dir / f"{stem}.svg"),
        "pdf": (tmp / "latest_preview_vector.pdf", out_dir / f"{stem}.pdf"),
        "nc": (tmp / "latest_preview.nc", out_dir / f"{stem}.nc"),
    }
    out: dict[str, str] = {}
    for key, (src, dst) in mapping.items():
        if src.exists():
            shutil.copy2(src, dst)
            out[key] = str(dst)
    return out


def run_acceptance(
    *,
    project_root: Path,
    input_pdf: Path,
    pages: list[int],
    output_dir: Path,
    quality: str,
    image_contours_mode: str,
    max_duplicate_ratio: float,
    max_tiny_ratio: float,
) -> dict[str, Any]:
    bridge = BackendBridge(project_root)
    backend = bridge._backend()
    result: dict[str, Any] = {
        "project_root": str(project_root),
        "input_pdf": str(input_pdf),
        "quality": quality,
        "image_contours_mode": image_contours_mode,
        "pages": [],
    }

    for page in pages:
        page_logs: list[str] = []
        ctx = OperationContext(_DummyWorker(), f"acceptance-p{page}")
        t0 = time.perf_counter()
        ok, msg = bridge.run_preview(
            ctx=ctx,
            input_path=input_pdf,
            sheet=SheetConfig(sheet_format="a4"),
            tool_mode="pencil",
            render_mode="handwriting",
            quality_profile=quality,
            force_text_to_path=False,
            handwriting_enabled=True,
            handwriting_font="Marck Script",
            handwriting_formula_font="Times New Roman",
            image_contours_mode=image_contours_mode,
            source_page_index=int(page),
            source_all_pages=False,
            exact_geometry_mode=False,
            safe_travel_lift=True,
            strict_one_to_one=False,
            log=page_logs.append,
        )
        dt = time.perf_counter() - t0
        page_row: dict[str, Any] = {
            "page": int(page),
            "ok": bool(ok),
            "message": str(msg),
            "runtime_s": round(float(dt), 3),
            "logs_tail": page_logs[-20:],
        }
        if ok:
            stem = f"{input_pdf.stem}_p{int(page)}"
            artifacts = _copy_latest_artifacts(project_root, output_dir, stem)
            page_row["artifacts"] = artifacts
            nc = artifacts.get("nc")
            if nc:
                metrics = _analyze_gcode(
                    Path(nc),
                    z_up=float(backend.Z_UP),
                    z_down=float(backend.Z_DOWN),
                )
                page_row["gcode_metrics"] = metrics
                quality_gate = {
                    "max_duplicate_ratio": float(max_duplicate_ratio),
                    "max_tiny_ratio": float(max_tiny_ratio),
                    "duplicate_ratio_ok": float(metrics.get("segments_duplicate_ratio", 0.0)) <= float(max_duplicate_ratio),
                    "tiny_ratio_ok": float(metrics.get("segments_tiny_ratio", 0.0)) <= float(max_tiny_ratio),
                }
                quality_gate["accepted"] = bool(quality_gate["duplicate_ratio_ok"] and quality_gate["tiny_ratio_ok"])
                page_row["quality_gate"] = quality_gate
                if not bool(quality_gate["accepted"]):
                    page_row["ok"] = False
                    page_row["message"] = (
                        f"{page_row['message']} | quality-gate failed: "
                        f"dup={metrics.get('segments_duplicate_ratio', 0.0):.5f}, "
                        f"tiny={metrics.get('segments_tiny_ratio', 0.0):.5f}"
                    )
        result["pages"].append(page_row)
    return result


def build_report_comparison(
    baseline_report: dict[str, Any],
    current_report: dict[str, Any],
) -> dict[str, Any]:
    baseline_pages = {
        int(row.get("page", 0)): row
        for row in list(baseline_report.get("pages", []))
        if int(row.get("page", 0)) > 0
    }
    rows: list[dict[str, Any]] = []
    for row in list(current_report.get("pages", [])):
        page = int(row.get("page", 0))
        if page <= 0 or page not in baseline_pages:
            continue
        prev = baseline_pages[page]
        prev_metrics = dict(prev.get("gcode_metrics", {}))
        cur_metrics = dict(row.get("gcode_metrics", {}))
        prev_dup = float(prev_metrics.get("segments_duplicate_ratio", 0.0))
        cur_dup = float(cur_metrics.get("segments_duplicate_ratio", 0.0))
        prev_tiny = float(prev_metrics.get("segments_tiny_ratio", 0.0))
        cur_tiny = float(cur_metrics.get("segments_tiny_ratio", 0.0))
        prev_short = float(prev_metrics.get("segments_short_ratio", 0.0))
        cur_short = float(cur_metrics.get("segments_short_ratio", 0.0))
        rows.append(
            {
                "page": page,
                "duplicate_ratio_before": prev_dup,
                "duplicate_ratio_after": cur_dup,
                "duplicate_ratio_delta": cur_dup - prev_dup,
                "tiny_ratio_before": prev_tiny,
                "tiny_ratio_after": cur_tiny,
                "tiny_ratio_delta": cur_tiny - prev_tiny,
                "short_ratio_before": prev_short,
                "short_ratio_after": cur_short,
                "short_ratio_delta": cur_short - prev_short,
                "runtime_s_before": float(prev.get("runtime_s", 0.0)),
                "runtime_s_after": float(row.get("runtime_s", 0.0)),
                "runtime_s_delta": float(row.get("runtime_s", 0.0)) - float(prev.get("runtime_s", 0.0)),
            }
        )
    return {
        "baseline_input_pdf": str(baseline_report.get("input_pdf", "")),
        "current_input_pdf": str(current_report.get("input_pdf", "")),
        "matched_pages": len(rows),
        "rows": rows,
    }


def _parse_pages(value: str) -> list[int]:
    out: list[int] = []
    for tok in str(value or "").split(","):
        s = tok.strip()
        if not s:
            continue
        out.append(max(1, int(s)))
    if not out:
        raise ValueError("No pages provided.")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run handwriting acceptance preview on selected PDF pages.")
    parser.add_argument("--pdf", required=True, help="Path to source PDF.")
    parser.add_argument("--pages", required=True, help="Comma-separated page numbers, e.g. 1,2,3,4,5,6")
    parser.add_argument("--out-dir", default="_tmp/acceptance", help="Where to store per-page artifacts and report.")
    parser.add_argument("--quality", default="high", choices=["fast", "normal", "high"])
    parser.add_argument("--contours", default="always", choices=["off", "word_only", "always"])
    parser.add_argument("--max-duplicate-ratio", type=float, default=0.002, help="Quality gate for duplicate segment ratio.")
    parser.add_argument("--max-tiny-ratio", type=float, default=0.015, help="Quality gate for tiny segment ratio (<0.12 mm).")
    parser.add_argument(
        "--baseline-report",
        default="",
        help="Optional path to previous handwriting_acceptance_report.json for before/after comparison.",
    )
    args = parser.parse_args()

    project_root = Path.cwd()
    pdf = Path(args.pdf).resolve()
    out_dir = (project_root / args.out_dir).resolve()
    pages = _parse_pages(args.pages)

    report = run_acceptance(
        project_root=project_root,
        input_pdf=pdf,
        pages=pages,
        output_dir=out_dir,
        quality=args.quality,
        image_contours_mode=args.contours,
        max_duplicate_ratio=float(args.max_duplicate_ratio),
        max_tiny_ratio=float(args.max_tiny_ratio),
    )
    baseline_path = Path(str(args.baseline_report).strip()) if str(args.baseline_report or "").strip() else None
    if baseline_path is not None and baseline_path.exists():
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            report["comparison"] = build_report_comparison(baseline, report)
        except Exception as exc:
            report["comparison_error"] = f"{type(exc).__name__}: {exc}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "handwriting_acceptance_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok_count = sum(1 for row in report["pages"] if bool(row.get("ok")))
    print(f"Acceptance done: {ok_count}/{len(report['pages'])} pages accepted.")
    print(f"Report: {report_path}")
    return 0 if ok_count == len(report["pages"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
