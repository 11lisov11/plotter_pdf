from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Any

import cv2  # type: ignore
import fitz  # type: ignore
import numpy as np  # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWN_VARIANT_NUMBERS = ("4", "11", "14", "25", "26")
HOTSPOT_MIN_AREA_RATIO = 0.0015
HOTSPOT_PAD_PX = 18


def variant_pack_name(variant: str) -> str:
    return f"TOE_Zadachi_1_2_Variant_{str(variant).strip()}_pack"


def resolve_selected_packs(
    *,
    variants: Iterable[str],
    packs: Iterable[str],
    all_known: bool,
) -> list[Path]:
    selected: list[Path] = []
    seen: set[str] = set()

    if all_known:
        variants = list(KNOWN_VARIANT_NUMBERS)

    for variant in variants:
        path = (PROJECT_ROOT / variant_pack_name(variant)).resolve()
        key = str(path).lower()
        if key not in seen:
            selected.append(path)
            seen.add(key)

    for pack in packs:
        path = (PROJECT_ROOT / str(pack)).resolve()
        key = str(path).lower()
        if key not in seen:
            selected.append(path)
            seen.add(key)

    return selected


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _severity_score(item: dict[str, Any]) -> float:
    sim = float(item.get("selected_layout_similarity", 0.0) or 0.0)
    overlay = dict(item.get("selected_overlay_metrics", {}))
    gate = dict(item.get("selected_quality_gate", {}))
    iou = float(overlay.get("mask_iou", 0.0) or 0.0)
    recall = float(overlay.get("mask_recall", 0.0) or 0.0)
    penalty = 0.0
    penalty += max(0.0, 0.970 - sim) * 100.0
    penalty += max(0.0, 0.360 - iou) * 18.0
    penalty += max(0.0, 0.420 - recall) * 10.0
    if not _bool(gate.get("accepted", False)):
        penalty += 3.0
    reason = str(item.get("selected_reason", "") or "")
    if "reason=region_rescue" in reason:
        penalty += 0.8
    if "reason=graph_rescue" in reason:
        penalty += 0.5
    if "reason=image_heavy_fallback" in reason:
        penalty += 0.3
    if "reason=low_similarity_fallback" in reason:
        penalty += 0.6
    return round(penalty, 6)


def _page_status(item: dict[str, Any]) -> str:
    sim = float(item.get("selected_layout_similarity", 0.0) or 0.0)
    overlay = dict(item.get("selected_overlay_metrics", {}))
    gate = dict(item.get("selected_quality_gate", {}))
    iou = float(overlay.get("mask_iou", 0.0) or 0.0)
    if not _bool(gate.get("accepted", False)) or sim < 0.945 or iou < 0.28:
        return "weak"
    if sim < 0.965 or iou < 0.36:
        return "watch"
    return "ok"


def _render_pdf_page_gray(pdf_path: Path, page_index: int = 0, dpi: int = 140) -> np.ndarray:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        zoom = float(dpi) / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    finally:
        doc.close()


def _crop_content(gray: np.ndarray) -> np.ndarray:
    mask = gray < 245
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return gray
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    pad = 8
    y0 = max(0, y0 - pad)
    y1 = min(gray.shape[0], y1 + pad)
    x0 = max(0, x0 - pad)
    x1 = min(gray.shape[1], x1 + pad)
    return gray[y0:y1, x0:x1]


def _resize_like_acceptance(gray: np.ndarray) -> np.ndarray:
    cropped = _crop_content(gray)
    size = (900, 900)
    resized = cv2.resize(cropped, size, interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(resized, (0, 0), 1.0)


def _overlay_error_mask_from_png(overlay_png: Path) -> np.ndarray | None:
    image = cv2.imread(str(overlay_png), cv2.IMREAD_COLOR)
    if image is None or image.size <= 0:
        return None
    spread = image.max(axis=2).astype(np.int16) - image.min(axis=2).astype(np.int16)
    return (spread >= 60).astype(np.uint8)


def _largest_hotspot_bbox_norm(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    if mask is None or getattr(mask, "size", 0) <= 0:
        return None
    area_min = int(round(float(mask.shape[0] * mask.shape[1]) * float(HOTSPOT_MIN_AREA_RATIO)))
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    best_area = -1
    for idx in range(1, int(num_labels)):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if area < area_min:
            continue
        if area > best_area:
            x = int(stats[idx, cv2.CC_STAT_LEFT])
            y = int(stats[idx, cv2.CC_STAT_TOP])
            w = int(stats[idx, cv2.CC_STAT_WIDTH])
            h = int(stats[idx, cv2.CC_STAT_HEIGHT])
            best = (x, y, w, h)
            best_area = area
    if best is None:
        return None
    x, y, w, h = best
    width = float(mask.shape[1])
    height = float(mask.shape[0])
    return (
        x / width,
        (x + w) / width,
        y / height,
        (y + h) / height,
    )


def _hotspot_crop_bounds_px(
    bbox_norm: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x0 = max(0, int(round(float(bbox_norm[0]) * float(width))) - int(HOTSPOT_PAD_PX))
    x1 = min(width, int(round(float(bbox_norm[1]) * float(width))) + int(HOTSPOT_PAD_PX))
    y0 = max(0, int(round(float(bbox_norm[2]) * float(height))) - int(HOTSPOT_PAD_PX))
    y1 = min(height, int(round(float(bbox_norm[3]) * float(height))) + int(HOTSPOT_PAD_PX))
    return x0, x1, y0, y1


def _write_hotspot_triptych(
    *,
    source_pdf: Path,
    page_index: int,
    preview_pdf: Path,
    overlay_png: Path,
    out_png: Path,
) -> dict[str, Any] | None:
    mask = _overlay_error_mask_from_png(overlay_png)
    if mask is None:
        return None
    bbox_norm = _largest_hotspot_bbox_norm(mask)
    if bbox_norm is None:
        return None
    source_gray = _resize_like_acceptance(_render_pdf_page_gray(source_pdf, page_index=page_index - 1))
    preview_gray = _resize_like_acceptance(_render_pdf_page_gray(preview_pdf, page_index=0))
    overlay = cv2.imread(str(overlay_png), cv2.IMREAD_COLOR)
    if overlay is None or overlay.size <= 0:
        return None
    if preview_gray.shape != source_gray.shape:
        preview_gray = cv2.resize(preview_gray, (source_gray.shape[1], source_gray.shape[0]), interpolation=cv2.INTER_AREA)
    if overlay.shape[:2] != source_gray.shape:
        overlay = cv2.resize(overlay, (source_gray.shape[1], source_gray.shape[0]), interpolation=cv2.INTER_AREA)
    x0, x1, y0, y1 = _hotspot_crop_bounds_px(
        bbox_norm,
        width=int(source_gray.shape[1]),
        height=int(source_gray.shape[0]),
    )
    src_crop = source_gray[y0:y1, x0:x1]
    prev_crop = preview_gray[y0:y1, x0:x1]
    ov_crop = overlay[y0:y1, x0:x1]
    if src_crop.size <= 0 or prev_crop.size <= 0 or ov_crop.size <= 0:
        return None
    src_rgb = cv2.cvtColor(src_crop, cv2.COLOR_GRAY2BGR)
    prev_rgb = cv2.cvtColor(prev_crop, cv2.COLOR_GRAY2BGR)
    sep = np.full((src_rgb.shape[0], 8, 3), 235, dtype=np.uint8)
    panel = np.hstack([src_rgb, sep, prev_rgb, sep, ov_crop])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_png), panel)
    return {
        "bbox_norm": [round(float(v), 6) for v in bbox_norm],
        "crop_px": [int(x0), int(x1), int(y0), int(y1)],
        "image": str(out_png),
    }


def build_page_audit(*, pack_dir: Path, item: dict[str, Any]) -> dict[str, Any]:
    page_index = int(item.get("page_index", 0) or 0)
    page_name = f"page_{page_index:02d}"
    pages_dir = pack_dir / "pages"
    row = {
        "page_index": page_index,
        "page_name": page_name,
        "status": _page_status(item),
        "severity_score": _severity_score(item),
        "selected_variant": str(item.get("selected_variant", "") or ""),
        "source_strategy": str(item.get("source_strategy", "") or ""),
        "selected_layout_similarity": float(item.get("selected_layout_similarity", 0.0) or 0.0),
        "selected_mask_iou": float(dict(item.get("selected_overlay_metrics", {})).get("mask_iou", 0.0) or 0.0),
        "selected_mask_recall": float(dict(item.get("selected_overlay_metrics", {})).get("mask_recall", 0.0) or 0.0),
        "quality_gate_accepted": _bool(dict(item.get("selected_quality_gate", {})).get("accepted", False)),
        "selected_reason": str(item.get("selected_reason", "") or ""),
        "preview_pdf": str(pages_dir / f"{page_name}.pdf"),
        "preview_svg": str(pages_dir / f"{page_name}.svg"),
        "overlay_png": str(pages_dir / f"{page_name}_overlay.png"),
        "log_path": str(pack_dir / "logs" / f"{page_name}.log.txt"),
    }
    source_pdf = Path(str(item.get("_source_pdf", "") or ""))
    preview_pdf = Path(str(row["preview_pdf"]))
    overlay_png = Path(str(row["overlay_png"]))
    if source_pdf.exists() and preview_pdf.exists() and overlay_png.exists():
        hotspot = _write_hotspot_triptych(
            source_pdf=source_pdf,
            page_index=page_index,
            preview_pdf=preview_pdf,
            overlay_png=overlay_png,
            out_png=pack_dir / "audit_hotspots" / f"{page_name}_hotspot.png",
        )
        if hotspot is not None:
            row["hotspot"] = hotspot
    return row


def build_pack_audit(*, pack_dir: Path, report: dict[str, Any], top_k: int) -> dict[str, Any]:
    source_pdf = str(report.get("source_pdf", "") or "")
    items = []
    for item in list(report.get("items", [])):
        item_copy = dict(item)
        item_copy["_source_pdf"] = source_pdf
        items.append(build_page_audit(pack_dir=pack_dir, item=item_copy))
    ranked = sorted(items, key=lambda row: (-float(row["severity_score"]), int(row["page_index"])))
    weak_pages = [row for row in ranked if str(row.get("status")) == "weak"]
    watch_pages = [row for row in ranked if str(row.get("status")) == "watch"]
    return {
        "pack_dir": str(pack_dir),
        "source_pdf": str(report.get("source_pdf", "") or ""),
        "page_count": int(report.get("page_count", 0) or 0),
        "selected_primary_font": str(report.get("selected_primary_font", "") or ""),
        "avg_layout_similarity": round(
            sum(float(row["selected_layout_similarity"]) for row in items) / float(len(items) or 1),
            6,
        ),
        "min_layout_similarity": round(
            min((float(row["selected_layout_similarity"]) for row in items), default=0.0),
            6,
        ),
        "weak_pages_count": len(weak_pages),
        "watch_pages_count": len(watch_pages),
        "weak_pages": weak_pages,
        "watch_pages": watch_pages,
        "top_pages": ranked[: max(1, int(top_k))],
    }


def _audit_text(audit: dict[str, Any]) -> str:
    lines = [
        f"pack={audit['pack_dir']}",
        f"source_pdf={audit['source_pdf']}",
        f"page_count={audit['page_count']}",
        f"selected_primary_font={audit['selected_primary_font']}",
        f"avg_layout_similarity={audit['avg_layout_similarity']:.6f}",
        f"min_layout_similarity={audit['min_layout_similarity']:.6f}",
        f"weak_pages_count={audit['weak_pages_count']}",
        f"watch_pages_count={audit['watch_pages_count']}",
        "",
        "Top pages:",
    ]
    for row in list(audit.get("top_pages", [])):
        lines.append(
            f"- {row['page_name']}: status={row['status']}; severity={float(row['severity_score']):.6f}; "
            f"sim={float(row['selected_layout_similarity']):.6f}; iou={float(row['selected_mask_iou']):.6f}; "
            f"variant={row['selected_variant']}; strategy={row['source_strategy']}"
        )
        lines.append(f"  reason={row['selected_reason']}")
        hotspot = dict(row.get("hotspot", {}))
        if hotspot:
            lines.append(
                f"  hotspot_bbox_norm={hotspot.get('bbox_norm')} hotspot_image={hotspot.get('image')}"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit TOE package quality and rank weak pages.")
    parser.add_argument("--variant", action="append", default=[], help="TOE variant number, e.g. 25. Can be passed multiple times.")
    parser.add_argument("--pack", action="append", default=[], help="Explicit TOE package directory in project root. Can be passed multiple times.")
    parser.add_argument("--all-known", action="store_true", help="Audit the known TOE variant packs shipped in this repository.")
    parser.add_argument("--top-k", type=int, default=5, help="How many weakest pages to keep in the summary.")
    args = parser.parse_args(argv)

    pack_paths = resolve_selected_packs(
        variants=list(args.variant),
        packs=list(args.pack),
        all_known=bool(args.all_known),
    )
    if not pack_paths:
        parser.error("No TOE packs selected. Use --variant, --pack or --all-known.")

    for pack_dir in pack_paths:
        report_path = pack_dir / "report.json"
        if not report_path.exists():
            raise FileNotFoundError(f"report.json not found: {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        audit = build_pack_audit(pack_dir=pack_dir, report=report, top_k=int(args.top_k))
        (pack_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        (pack_dir / "audit.txt").write_text(_audit_text(audit), encoding="utf-8")
        print(
            f"[toe-audit] {pack_dir.name}: weak={audit['weak_pages_count']} watch={audit['watch_pages_count']} "
            f"min_sim={float(audit['min_layout_similarity']):.6f}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
