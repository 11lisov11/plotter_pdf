from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import fitz  # type: ignore
import numpy as np  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import prepare_folder1_packages as prep
import run_pdf_handwriting_acceptance as acceptance


FONT_CANDIDATES = [
    ("Marck Script", PROJECT_ROOT / "data" / "fonts" / "MarckScript-Regular.ttf"),
    ("Bad Script", PROJECT_ROOT / "data" / "fonts" / "BadScript-Regular.ttf"),
    ("Caveat", PROJECT_ROOT / "data" / "fonts" / "Caveat-wght.ttf"),
    ("Neucha", PROJECT_ROOT / "data" / "fonts" / "Neucha.ttf"),
]
TOE_RENDER_VARIANTS = [
    ("always", "always"),
    ("contours_off", "off"),
]
SOFT_OVERRIDE_MAX_DUPLICATE_RATIO = 0.005
SOFT_OVERRIDE_MAX_TINY_RATIO = 0.040
SOFT_OVERRIDE_MAX_SHORT_RATIO = 0.180
SOFT_OVERRIDE_MIN_SCORE_GAIN = 0.001


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip().lower())
    return text.strip("_") or "font"


def _candidate_fonts() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for label, path in FONT_CANDIDATES:
        if path.exists() and path.is_file():
            out.append((label, path))
    if not out:
        raise FileNotFoundError("No candidate handwriting fonts found in data/fonts.")
    return out


def _compute_quality_metrics(nc_path: Path) -> dict[str, Any]:
    return acceptance._analyze_gcode(
        nc_path,
        z_up=float(prep.backend.Z_UP),
        z_down=float(prep.backend.Z_DOWN),
    )


def _load_existing_candidate(
    *,
    source_pdf: Path,
    page_index: int,
    font_label: str,
    font_path: Path,
    prefix: Path,
) -> dict[str, Any] | None:
    svg_path, pdf_path, nc_path, gcode_path = prep._bridge_preview_copy_targets(prefix)
    if not all(path.exists() and path.is_file() for path in (svg_path, pdf_path, nc_path, gcode_path)):
        return None
    similarity = prep._layout_similarity_pdf(source_pdf, pdf_path, source_page_index=page_index - 1)
    return {
        "item": f"page_{page_index:02d}",
        "ok": True,
        "message": "reused existing candidate",
        "logs": ["reused existing candidate artifacts"],
        "font_label": font_label,
        "font_path": str(font_path),
        "layout_similarity": similarity,
        "metrics": prep._analyze_gcode(nc_path),
        "svg": str(svg_path),
        "pdf": str(pdf_path),
        "nc": str(nc_path),
        "gcode": str(gcode_path),
        "notes": "reused_existing",
    }


def _build_overlay_metrics(
    *,
    source_pdf: Path,
    source_page_index: int,
    preview_pdf: Path,
    out_png: Path,
) -> dict[str, float]:
    src = prep._crop_content(prep._render_pdf_page_gray(source_pdf, page_index=source_page_index))
    cur = prep._crop_content(prep._render_pdf_page_gray(preview_pdf, page_index=0))
    size = (900, 900)
    src = cv2.resize(src, size, interpolation=cv2.INTER_AREA)
    cur = cv2.resize(cur, size, interpolation=cv2.INTER_AREA)
    src = cv2.GaussianBlur(src, (0, 0), 1.0)
    cur = cv2.GaussianBlur(cur, (0, 0), 1.0)

    src_mask = src < 228
    cur_mask = cur < 228
    inter = int(np.count_nonzero(src_mask & cur_mask))
    union = int(np.count_nonzero(src_mask | cur_mask))
    src_count = int(np.count_nonzero(src_mask))
    cur_count = int(np.count_nonzero(cur_mask))
    iou = float(inter / union) if union > 0 else 1.0
    recall = float(inter / src_count) if src_count > 0 else 1.0
    precision = float(inter / cur_count) if cur_count > 0 else 1.0

    overlay = np.full((size[1], size[0], 3), 255, dtype=np.uint8)
    overlay[src_mask & cur_mask] = (35, 35, 35)
    overlay[src_mask & ~cur_mask] = (40, 40, 220)
    overlay[cur_mask & ~src_mask] = (220, 40, 40)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_png), overlay)
    return {
        "mask_iou": round(iou, 6),
        "mask_recall": round(recall, 6),
        "mask_precision": round(precision, 6),
    }


def _candidate_score(row: dict[str, Any]) -> float:
    sim = float(row.get("layout_similarity", 0.0) or 0.0)
    g = dict(row.get("quality_metrics", {}))
    overlay = dict(row.get("overlay_metrics", {}))
    dup = float(g.get("segments_duplicate_ratio", 0.0) or 0.0)
    tiny = float(g.get("segments_tiny_ratio", 0.0) or 0.0)
    short = float(g.get("segments_short_ratio", 0.0) or 0.0)
    iou = float(overlay.get("mask_iou", 0.0) or 0.0)
    return round(sim + (iou * 0.08) - (dup * 0.30) - (tiny * 0.12) - (short * 0.03), 6)


def _font_doc_score(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return -1e9
    scores = [_candidate_score(row) for row in rows if bool(row.get("ok"))]
    if not scores:
        return -1e9
    min_similarity = min(float(row.get("layout_similarity", 0.0) or 0.0) for row in rows if bool(row.get("ok")))
    return float(statistics.fmean(scores)) + (min_similarity * 0.02)


def _quality_gate(row: dict[str, Any], *, max_duplicate_ratio: float, max_tiny_ratio: float) -> dict[str, Any]:
    g = dict(row.get("quality_metrics", {}))
    dup = float(g.get("segments_duplicate_ratio", 0.0) or 0.0)
    tiny = float(g.get("segments_tiny_ratio", 0.0) or 0.0)
    return {
        "max_duplicate_ratio": float(max_duplicate_ratio),
        "max_tiny_ratio": float(max_tiny_ratio),
        "duplicate_ratio_ok": dup <= float(max_duplicate_ratio),
        "tiny_ratio_ok": tiny <= float(max_tiny_ratio),
        "accepted": dup <= float(max_duplicate_ratio) and tiny <= float(max_tiny_ratio),
    }


def _candidate_soft_ok(row: dict[str, Any]) -> bool:
    q = dict(row.get("quality_metrics", {}))
    dup = float(q.get("segments_duplicate_ratio", 0.0) or 0.0)
    tiny = float(q.get("segments_tiny_ratio", 0.0) or 0.0)
    short = float(q.get("segments_short_ratio", 0.0) or 0.0)
    return (
        dup <= float(SOFT_OVERRIDE_MAX_DUPLICATE_RATIO)
        and tiny <= float(SOFT_OVERRIDE_MAX_TINY_RATIO)
        and short <= float(SOFT_OVERRIDE_MAX_SHORT_RATIO)
    )


def _select_page_result(
    *,
    primary_label: str,
    page_results: list[dict[str, Any]],
    override_similarity_gain: float,
) -> dict[str, Any]:
    successful = [row for row in page_results if bool(row.get("ok"))]
    if not successful:
        return max(page_results, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))

    primary_candidates = [row for row in successful if str(row.get("font_label", "")) == str(primary_label)]
    base = next(
        (
            row for row in primary_candidates
            if str(row.get("variant_label", "always")) == "always"
        ),
        None,
    )
    if base is None and primary_candidates:
        base = max(
            primary_candidates,
            key=lambda row: (_candidate_score(row), float(row.get("layout_similarity", 0.0) or 0.0)),
        )
    if base is None:
        return max(successful, key=lambda row: (_candidate_score(row), float(row.get("layout_similarity", 0.0) or 0.0)))

    accepted = [row for row in successful if bool(dict(row.get("quality_gate", {})).get("accepted", False))]
    if accepted:
        best_accepted = max(accepted, key=lambda row: (_candidate_score(row), float(row.get("layout_similarity", 0.0) or 0.0)))
        base_accepted = bool(dict(base.get("quality_gate", {})).get("accepted", False))
        if not base_accepted:
            base_sim = float(base.get("layout_similarity", 0.0) or 0.0)
            cand_sim = float(best_accepted.get("layout_similarity", 0.0) or 0.0)
            base_iou = float(dict(base.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
            cand_iou = float(dict(best_accepted.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
            if base_sim < 0.93 or (cand_sim >= (base_sim - 0.002) and cand_iou >= (base_iou - 0.01)):
                base = best_accepted

    soft_candidates = [row for row in successful if _candidate_soft_ok(row)]
    if not soft_candidates:
        return base

    best_soft = max(soft_candidates, key=lambda row: (_candidate_score(row), float(row.get("layout_similarity", 0.0) or 0.0)))
    best_score = float(best_soft.get("score", -1e9) or -1e9)
    base_score = float(base.get("score", -1e9) or -1e9)
    sim_gain = float(best_soft.get("layout_similarity", 0.0) or 0.0) - float(base.get("layout_similarity", 0.0) or 0.0)
    best_iou = float(dict(best_soft.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    base_iou = float(dict(base.get("overlay_metrics", {})).get("mask_iou", 0.0) or 0.0)
    iou_gain = best_iou - base_iou
    if best_score >= (base_score + float(SOFT_OVERRIDE_MIN_SCORE_GAIN)):
        if str(best_soft.get("font_label", "")) != str(base.get("font_label", "")):
            if sim_gain >= float(override_similarity_gain) and iou_gain >= -0.005:
                return best_soft
            if iou_gain >= 0.03 and sim_gain >= -0.001:
                return best_soft
        else:
            if sim_gain >= -0.002 and iou_gain >= 0.01:
                return best_soft
    return base


def _copy_selected_artifacts(selected: dict[str, Any], prefix: Path) -> None:
    for src_key, dst_path in zip(["svg", "pdf", "nc", "gcode"], prep._bridge_preview_copy_targets(prefix)):
        prep._copy_file(Path(str(selected[src_key])), dst_path)
    overlay_src = Path(str(selected.get("overlay_png", "")))
    if overlay_src.exists():
        prep._copy_file(overlay_src, prefix.parent / f"{prefix.name}_overlay.png")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a root TOE PDF handwriting package with self-check and font search.")
    parser.add_argument("--pdf", default="TOE_Zadachi_1_2_Variant_4.pdf", help="Source TOE PDF in project root.")
    parser.add_argument("--out-dir", default="", help="Optional output package directory. Defaults to <pdf>_pack.")
    parser.add_argument("--max-duplicate-ratio", type=float, default=0.002)
    parser.add_argument("--max-tiny-ratio", type=float, default=0.015)
    parser.add_argument("--override-similarity-gain", type=float, default=0.012)
    parser.add_argument("--resume", action="store_true", help="Reuse existing package/candidate artifacts and continue from them.")
    args = parser.parse_args()

    source_pdf = (PROJECT_ROOT / str(args.pdf)).resolve()
    if not source_pdf.exists():
        raise FileNotFoundError(f"PDF not found: {source_pdf}")
    package_dir = (PROJECT_ROOT / str(args.out_dir)).resolve() if str(args.out_dir).strip() else source_pdf.with_name(f"{source_pdf.stem}_pack")

    if args.resume:
        package_dir.mkdir(parents=True, exist_ok=True)
    else:
        prep._ensure_clean_dir(package_dir)
    pages_dir = package_dir / "pages"
    logs_dir = package_dir / "logs"
    candidates_dir = package_dir / "_candidates"
    page_svg_dir = package_dir / "_page_svg"
    pages_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    page_svg_dir.mkdir(parents=True, exist_ok=True)

    fonts = _candidate_fonts()
    doc = fitz.open(source_pdf)
    page_count = int(doc.page_count)
    all_page_results: dict[int, list[dict[str, Any]]] = {}
    font_success: dict[str, list[dict[str, Any]]] = {label: [] for label, _path in fonts}
    started_at = time.time()

    for page_index in range(1, page_count + 1):
        print(f"[page {page_index:02d}/{page_count:02d}] export/source", flush=True)
        page_svg = page_svg_dir / f"page_{page_index:02d}.svg"
        if not (args.resume and page_svg.exists() and page_svg.is_file()):
            prep._export_pdf_page_to_mupdf_svg(source_pdf, page_index - 1, page_svg)
        results: list[dict[str, Any]] = []
        for font_label, font_path in fonts:
            print(f"  - {font_label}", flush=True)
            font_slug = _slugify(font_label)
            for variant_label, contours_mode in TOE_RENDER_VARIANTS:
                variant_slug = font_slug if variant_label == "always" else f"{font_slug}__{variant_label}"
                prefix = candidates_dir / f"page_{page_index:02d}" / variant_slug / f"page_{page_index:02d}"
                prefix.parent.mkdir(parents=True, exist_ok=True)
                row = None
                if args.resume:
                    row = _load_existing_candidate(
                        source_pdf=source_pdf,
                        page_index=page_index,
                        font_label=font_label,
                        font_path=font_path,
                        prefix=prefix,
                    )
                if row is None:
                    if variant_label == "always":
                        row = prep._prepare_toe_page(
                            source_pdf=source_pdf,
                            page_index=page_index,
                            page_svg=page_svg,
                            font_label=font_label,
                            font_path=font_path,
                            prefix=prefix,
                        )
                    else:
                        prep._configure_toe_backend(font_path)
                        prep.backend.IMAGE_CONTOUR_MODE = contours_mode
                        prep.backend.IMAGE_CONTOUR_ENABLED = contours_mode != "off"
                        prep.backend.IMAGE_CONTOUR_WORD_ONLY = contours_mode == "word_only"
                        logs: list[str] = []
                        nc_path = prefix.with_suffix(".nc")
                        ok, msg = prep.backend.run_pipeline(page_svg, logs.append, send_to_plotter=False, output_path=nc_path)
                        row = {
                            "item": f"page_{page_index:02d}",
                            "ok": bool(ok),
                            "message": msg,
                            "logs": logs,
                            "font_label": font_label,
                            "font_path": str(font_path),
                        }
                        if ok:
                            bridge = prep.BackendBridge(PROJECT_ROOT)
                            svg_path = prefix.with_suffix(".svg")
                            pdf_path = prefix.with_suffix(".pdf")
                            preview_ok, preview_err = bridge._build_vector_preview_from_gcode(
                                nc_path,
                                svg_path,
                                pdf_path,
                                backend=prep.backend,
                                log=logs.append,
                            )
                            if not preview_ok:
                                row["ok"] = False
                                row["message"] = preview_err
                            else:
                                gcode_path = prefix.with_suffix(".gcode")
                                prep._copy_file(nc_path, gcode_path)
                                row.update(
                                    {
                                        "layout_similarity": prep._layout_similarity_pdf(source_pdf, pdf_path, source_page_index=page_index - 1),
                                        "metrics": prep._analyze_gcode(nc_path),
                                        "svg": str(svg_path),
                                        "pdf": str(pdf_path),
                                        "nc": str(nc_path),
                                        "gcode": str(gcode_path),
                                        "notes": f"contours={contours_mode}",
                                    }
                                )
                row["font_slug"] = font_slug
                row["variant_label"] = variant_label
                row["image_contours_mode"] = contours_mode
                row["page_index"] = int(page_index)
                if bool(row.get("ok")):
                    quality_metrics = _compute_quality_metrics(Path(str(row["nc"])))
                    row["quality_metrics"] = quality_metrics
                    row["quality_gate"] = _quality_gate(
                        row,
                        max_duplicate_ratio=float(args.max_duplicate_ratio),
                        max_tiny_ratio=float(args.max_tiny_ratio),
                    )
                    overlay_png = prefix.parent / f"{prefix.name}_overlay.png"
                    row["overlay_metrics"] = _build_overlay_metrics(
                        source_pdf=source_pdf,
                        source_page_index=page_index - 1,
                        preview_pdf=Path(str(row["pdf"])),
                        out_png=overlay_png,
                    )
                    row["overlay_png"] = str(overlay_png)
                    row["score"] = _candidate_score(row)
                    font_success[font_label].append(row)
                else:
                    row["quality_metrics"] = {}
                    row["quality_gate"] = {"accepted": False}
                    row["overlay_metrics"] = {}
                    row["overlay_png"] = ""
                    row["score"] = -1e9
                results.append(row)
        all_page_results[page_index] = results

    font_report_rows: list[dict[str, Any]] = []
    for font_label, _path in fonts:
        raw_rows = font_success.get(font_label, [])
        best_by_page: dict[int, dict[str, Any]] = {}
        for row in raw_rows:
            page_index = int(row.get("page_index", 0) or 0)
            if page_index <= 0:
                continue
            prev = best_by_page.get(page_index)
            if prev is None or _candidate_score(row) > _candidate_score(prev):
                best_by_page[page_index] = row
        rows = list(best_by_page.values())
        sims = [float(row.get("layout_similarity", 0.0) or 0.0) for row in rows]
        scores = [float(row.get("score", -1e9) or -1e9) for row in rows]
        font_report_rows.append(
            {
                "font_label": font_label,
                "pages_ok": len(rows),
                "avg_layout_similarity": round(float(statistics.fmean(sims)), 6) if sims else 0.0,
                "min_layout_similarity": round(min(sims), 6) if sims else 0.0,
                "avg_score": round(float(statistics.fmean(scores)), 6) if scores else -1e9,
                "doc_score": round(_font_doc_score(rows), 6) if rows else -1e9,
            }
        )

    primary_font = max(font_report_rows, key=lambda row: (float(row.get("doc_score", -1e9)), float(row.get("avg_layout_similarity", 0.0))))["font_label"]

    rows: list[prep.ArtifactRow] = []
    report: dict[str, Any] = {
        "source_pdf": str(source_pdf),
        "package_dir": str(package_dir),
        "kind": "toe_handwriting",
        "page_count": page_count,
        "fonts_evaluated": font_report_rows,
        "selected_primary_font": primary_font,
        "generated_at_epoch": started_at,
        "items": [],
    }

    for page_index in range(1, page_count + 1):
        page_results = all_page_results[page_index]
        selected = _select_page_result(
            primary_label=str(primary_font),
            page_results=page_results,
            override_similarity_gain=float(args.override_similarity_gain),
        )
        final_prefix = pages_dir / f"page_{page_index:02d}"
        if bool(selected.get("ok")):
            _copy_selected_artifacts(selected, final_prefix)
            page_logs = list(selected.get("logs", []))
            page_logs.append(f"selected_primary_font={primary_font}")
            page_logs.append(f"selected_font={selected.get('font_label')}")
            page_logs.append(f"selected_variant={selected.get('variant_label')}")
            page_logs.append(f"selected_contours={selected.get('image_contours_mode')}")
            page_logs.append(f"selected_score={float(selected.get('score', 0.0)):.6f}")
            gate = dict(selected.get("quality_gate", {}))
            page_logs.append(
                "quality_gate="
                f"accepted={bool(gate.get('accepted', False))};"
                f" dup_ok={bool(gate.get('duplicate_ratio_ok', False))};"
                f" tiny_ok={bool(gate.get('tiny_ratio_ok', False))}"
            )
            prep._write_text(logs_dir / f"page_{page_index:02d}.log.txt", "\n".join(page_logs) + "\n")
            q = dict(selected.get("quality_metrics", {}))
            rows.append(
                prep.ArtifactRow(
                    source_pdf=str(source_pdf),
                    package_dir=str(package_dir),
                    kind="toe_handwriting",
                    item=f"page_{page_index:02d}",
                    ok=True,
                    layout_similarity=float(selected.get("layout_similarity", 0.0) or 0.0),
                    draw_length_m=round(float(q.get("draw_length_mm", 0.0)) / 1000.0, 3),
                    segments_total=int(q.get("segments_total", 0) or 0),
                    bounds=prep._bounds_text({"bounds": dict(q.get("bounds", {}))}),
                    nc=str(final_prefix.with_suffix(".nc")),
                    gcode=str(final_prefix.with_suffix(".gcode")),
                    preview_pdf=str(final_prefix.with_suffix(".pdf")),
                    preview_svg=str(final_prefix.with_suffix(".svg")),
                    notes="; ".join(
                        part
                        for part in [
                            f"font={selected.get('font_label')}",
                            f"variant={selected.get('variant_label')}",
                            f"contours={selected.get('image_contours_mode')}",
                            "page_override=yes"
                            if (
                                str(selected.get("font_label", "")) != str(primary_font)
                                or str(selected.get("variant_label", "always")) != "always"
                            )
                            else "page_override=no",
                            str(selected.get("notes", "")),
                            f"iou={float(dict(selected.get('overlay_metrics', {})).get('mask_iou', 0.0)):.6f}",
                        ]
                        if part
                    ),
                )
            )
        else:
            prep._write_text(
                logs_dir / f"page_{page_index:02d}.log.txt",
                "\n".join(str(row.get("message", "")) for row in page_results) + "\n",
            )
            rows.append(
                prep.ArtifactRow(
                    source_pdf=str(source_pdf),
                    package_dir=str(package_dir),
                    kind="toe_handwriting",
                    item=f"page_{page_index:02d}",
                    ok=False,
                    layout_similarity=None,
                    draw_length_m=None,
                    segments_total=None,
                    bounds="",
                    nc="",
                    gcode="",
                    preview_pdf="",
                    preview_svg="",
                    notes="all candidates failed",
                )
            )
        report["items"].append(
            {
                "page_index": page_index,
                "selected_font": selected.get("font_label"),
                "selected_variant": selected.get("variant_label"),
                "selected_contours_mode": selected.get("image_contours_mode"),
                "selected_layout_similarity": selected.get("layout_similarity"),
                "selected_score": selected.get("score"),
                "selected_quality_gate": selected.get("quality_gate"),
                "selected_overlay_metrics": selected.get("overlay_metrics"),
                "candidates": page_results,
            }
        )

    prep._write_json(package_dir / "report.json", report)
    prep._write_csv(package_dir / "summary.csv", rows)
    prep._mirror_package_root_artifacts(package_dir, rows)
    prep._write_json(
        package_dir / "final_overview.json",
        {
            "source_pdf": str(source_pdf),
            "selected_primary_font": primary_font,
            "fonts_evaluated": font_report_rows,
            "pages_ok": sum(1 for row in rows if bool(row.ok)),
            "page_count": page_count,
            "elapsed_s": round(time.time() - started_at, 3),
        },
    )
    print(f"Prepared: {package_dir}")
    print(f"Primary font: {primary_font}")
    print(f"Pages ok: {sum(1 for row in rows if bool(row.ok))}/{page_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
