from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.plotter_backend.common_utils import clean_report_value

DEFAULT_ROOT = PROJECT_ROOT / "Начерт"


def _collect_variant_dirs(root: Path) -> list[Path]:
    if (root / "_prepared_summary.csv").exists():
        return [root]
    return [
        p
        for p in sorted(root.iterdir(), key=lambda p: p.name.casefold())
        if p.is_dir() and (p / "_prepared_summary.csv").exists()
    ]


def _render_pdf(pdf_path: Path, zoom: float = 1.25) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    finally:
        doc.close()


def _fit_image(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    out = img.copy()
    out.thumbnail((max_w, max_h))
    return out


def _make_panel(images: list[tuple[str, Image.Image]], title: str) -> Image.Image:
    cell_w = 320
    cell_h = 260
    label_h = 36
    cols = len(images)
    panel = Image.new("RGB", (cell_w * cols, cell_h + label_h + 26), "white")
    draw = ImageDraw.Draw(panel)
    draw.text((8, 6), title, fill="black")
    for idx, (label, img) in enumerate(images):
        thumb = _fit_image(img, cell_w - 12, cell_h - 12)
        x0 = idx * cell_w
        x = x0 + (cell_w - thumb.width) // 2
        y = 24 + (cell_h - thumb.height) // 2
        panel.paste(thumb, (x, y))
        draw.text((x0 + 8, cell_h + 26), label, fill="black")
    return panel


def _save_package_compare_artifacts(package_dir: Path, panel: Image.Image) -> tuple[Path, Path]:
    png_path = package_dir / "source_vs_gcode_compare.png"
    pdf_path = package_dir / "source_vs_gcode_compare.pdf"
    panel.save(png_path)
    panel.convert("RGB").save(pdf_path, "PDF", resolution=150.0)
    return png_path, pdf_path


def _audit_variant(variant_dir: Path) -> None:
    summary_path = variant_dir / "_prepared_summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary not found: {summary_path}")

    audit_dir = variant_dir / "_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(summary_path.open(encoding="utf-8-sig")))
    rows_by_package: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        rows_by_package.setdefault(row["package_dir"], []).append(row)

    audit_rows: list[dict[str, object]] = []
    panels: list[Image.Image] = []
    for package_dir_str, package_rows in sorted(rows_by_package.items()):
        package_dir = Path(package_dir_str)
        source_pdf = Path(package_rows[0]["source_pdf"])
        report_path = package_dir / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        title = package_dir.name

        if len(package_rows) == 1 and package_rows[0]["item"] == "page_01":
            preview_pdf = Path(package_rows[0]["preview_pdf"])
            reference_pdf = source_pdf
            clean_meta = dict(report.get("a4_clean_source", {}) or {})
            clean_pdf_raw = str(clean_meta.get("pdf", "") or "").strip()
            clean_pdf = Path(clean_pdf_raw) if clean_pdf_raw else None
            if clean_pdf and clean_pdf.exists() and clean_pdf.is_file():
                reference_pdf = clean_pdf
            panel = _make_panel(
                [
                    ("source", _render_pdf(reference_pdf, 1.0)),
                    ("preview", _render_pdf(preview_pdf, 1.0)),
                ],
                title,
            )
            compare_png, compare_pdf = _save_package_compare_artifacts(package_dir, panel)
            layout_similarity = package_rows[0]["layout_similarity"]
            audit_rows.append(
                {
                    "task": title,
                    "kind": "a4",
                    "layout_similarity": float(layout_similarity) if layout_similarity else None,
                    "preview": str(preview_pdf),
                    "reference_source": str(reference_pdf),
                    "source": str(source_pdf),
                    "compare_png": str(compare_png),
                    "compare_pdf": str(compare_pdf),
                }
            )
        else:
            pass1 = next(row for row in package_rows if row["item"] == "pass_01")
            pass2 = next(row for row in package_rows if row["item"] == "pass_02")
            combined_meta = dict(report.get("combined_preview", {}) or {})
            combined_pdf_raw = str(combined_meta.get("pdf", "") or "").strip()
            combined_pdf = Path(combined_pdf_raw) if combined_pdf_raw else Path(pass1["preview_pdf"])
            reference_pdf_raw = str(combined_meta.get("reference_pdf", "") or "").strip()
            reference_pdf = Path(reference_pdf_raw) if reference_pdf_raw else source_pdf
            if not combined_pdf.exists() or not combined_pdf.is_file():
                combined_pdf = Path(pass1["preview_pdf"])
            if not reference_pdf.exists() or not reference_pdf.is_file():
                reference_pdf = source_pdf
            panel = _make_panel(
                [
                    ("source", _render_pdf(reference_pdf, 0.75)),
                    ("combined", _render_pdf(combined_pdf, 0.75)),
                    ("pass_01", _render_pdf(Path(pass1["preview_pdf"]), 1.0)),
                    ("pass_02", _render_pdf(Path(pass2["preview_pdf"]), 1.0)),
                ],
                title,
            )
            compare_png, compare_pdf = _save_package_compare_artifacts(package_dir, panel)
            audit_rows.append(
                {
                    "task": title,
                    "kind": "a3_two_pass",
                    "reference_source": str(reference_pdf),
                    "combined_preview": str(combined_pdf),
                    "combined_layout_similarity": combined_meta.get("layout_similarity"),
                    "pass_01_preview": pass1["preview_pdf"],
                    "pass_02_preview": pass2["preview_pdf"],
                    "source": str(source_pdf),
                    "notes": [pass1["notes"], pass2["notes"]],
                    "compare_png": str(compare_png),
                    "compare_pdf": str(compare_pdf),
                }
            )

        panel_path = audit_dir / f"{title}.png"
        panel.save(panel_path)
        panels.append(panel)

    if panels:
        contact = Image.new("RGB", (panels[0].width, sum(p.height for p in panels)), "#dddddd")
        y = 0
        for panel in panels:
            contact.paste(panel, (0, y))
            y += panel.height
        contact.save(variant_dir / "_audit_contact.png")

    (variant_dir / "_audit.json").write_text(
        json.dumps(clean_report_value({"variant_dir": str(variant_dir), "items": audit_rows}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ranked_rows: list[tuple[float, str]] = []
    for row in audit_rows:
        sim = row.get("layout_similarity")
        if sim is None:
            sim = row.get("combined_layout_similarity")
        if sim in (None, ""):
            continue
        try:
            ranked_rows.append((float(sim), str(row.get("task", ""))))
        except (TypeError, ValueError):
            continue
    ranked_rows.sort(key=lambda item: item[0])
    summary_lines = [variant_dir.name]
    for score, task in ranked_rows:
        summary_lines.append(f"{task}: {score:.6f}")
    (variant_dir / "_audit.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit prepared Начерт drawing packages.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Root folder with variant subfolders.")
    parser.add_argument("--only-variant", action="append", default=[], help="Optional substring filter.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Root not found: {root}")

    tokens = [str(item or "").casefold() for item in args.only_variant if str(item or "").strip()]
    variant_dirs = _collect_variant_dirs(root)
    if tokens:
        variant_dirs = [p for p in variant_dirs if any(token in p.name.casefold() for token in tokens)]
    if not variant_dirs:
        if tokens:
            print("No prepared Начерт variant dirs match filter.")
        else:
            print("No prepared Начерт variant dirs found.")
        return 2

    for variant_dir in variant_dirs:
        print(variant_dir.name)
        _audit_variant(variant_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
