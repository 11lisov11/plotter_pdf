from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path
from typing import Iterable

import fitz

import prepare_folder1_packages as prep


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "Начерт"
A3_TASK_NUMBERS = {3, 10}


def _task_number_from_name(name: str) -> int | None:
    match = re.search(r"(\d+)", str(name or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _write_single_page_pdf(source_pdf: Path, page_index0: int, out_pdf: Path) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    src = fitz.open(source_pdf)
    dst = fitz.open()
    try:
        dst.insert_pdf(src, from_page=page_index0, to_page=page_index0)
        dst.save(out_pdf)
    finally:
        dst.close()
        src.close()


def _merge_split_a3_pdf(source_pdf: Path, out_pdf: Path) -> None:
    src = fitz.open(source_pdf)
    if src.page_count != 2:
        raise ValueError(f"Expected exactly 2 pages for split A3 source: {source_pdf}")
    left = src[0]
    right = src[1]
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    dst = fitz.open()
    try:
        page = dst.new_page(width=float(left.rect.width + right.rect.width), height=float(max(left.rect.height, right.rect.height)))
        page.show_pdf_page(fitz.Rect(0, 0, float(left.rect.width), float(left.rect.height)), src, 0)
        page.show_pdf_page(
            fitz.Rect(float(left.rect.width), 0, float(left.rect.width + right.rect.width), float(right.rect.height)),
            src,
            1,
        )
        dst.save(out_pdf)
    finally:
        dst.close()
        src.close()


def _prepare_frw_source_pdf(source_path: Path, generated_dir: Path) -> tuple[Path, dict[str, object]]:
    generated_dir.mkdir(parents=True, exist_ok=True)
    raw_pdf = generated_dir / f"{source_path.stem}__kompas.pdf"
    prep.backend.frw_to_pdf(source_path, raw_pdf, lambda *_args, **_kwargs: None)
    doc = fitz.open(raw_pdf)
    page_count = int(doc.page_count)
    page_sizes = [
        [
            round(float(page.rect.width) * 25.4 / 72.0, 3),
            round(float(page.rect.height) * 25.4 / 72.0, 3),
        ]
        for page in doc
    ]
    doc.close()

    task_number = _task_number_from_name(source_path.stem)
    if task_number in A3_TASK_NUMBERS and page_count == 2:
        merged_pdf = generated_dir / f"{source_path.stem}.pdf"
        _merge_split_a3_pdf(raw_pdf, merged_pdf)
        return merged_pdf, {
            "source_kind": "frw",
            "task_number": task_number,
            "kompas_pdf": str(raw_pdf),
            "page_count": page_count,
            "page_sizes_mm": page_sizes,
            "merged_a3_pdf": str(merged_pdf),
        }

    if page_count != 1:
        raise RuntimeError(
            f"Unexpected FRW->PDF page count for {source_path.name}: {page_count}. "
            "Only 1-page A4 or 2-page split A3 are supported."
        )
    final_pdf = generated_dir / f"{source_path.stem}.pdf"
    shutil.copy2(raw_pdf, final_pdf)
    return final_pdf, {
        "source_kind": "frw",
        "task_number": task_number,
        "kompas_pdf": str(raw_pdf),
        "page_count": page_count,
        "page_sizes_mm": page_sizes,
    }


def _iter_variant_sources(variant_dir: Path, generated_dir: Path) -> list[tuple[int, str, Path, dict[str, object]]]:
    entries: list[tuple[int, str, Path, dict[str, object]]] = []

    frw_files = sorted(variant_dir.glob("*.frw"), key=lambda p: (_task_number_from_name(p.stem) or 999, p.name.lower()))
    if frw_files:
        for frw in frw_files:
            task_number = _task_number_from_name(frw.stem)
            if task_number is None:
                raise RuntimeError(f"Cannot parse task number from FRW name: {frw.name}")
            source_pdf, meta = _prepare_frw_source_pdf(frw, generated_dir)
            entries.append((task_number, frw.stem, source_pdf, meta))
        return entries

    pdf_files = sorted(variant_dir.glob("*.pdf"), key=lambda p: p.name.lower())
    if not pdf_files:
        raise FileNotFoundError(f"No FRW or PDF sources found in {variant_dir}")
    if len(pdf_files) != 1:
        raise RuntimeError(f"Expected exactly one multipage PDF in {variant_dir}, found {len(pdf_files)}")

    multi_pdf = pdf_files[0]
    doc = fitz.open(multi_pdf)
    page_count = int(doc.page_count)
    for page_index in range(page_count):
        task_number = page_index + 1
        task_name = f"Задача {task_number}"
        page_pdf = generated_dir / f"{task_name}.pdf"
        _write_single_page_pdf(multi_pdf, page_index, page_pdf)
        page = doc[page_index]
        meta = {
            "source_kind": "pdf_split",
            "source_pdf": str(multi_pdf),
            "task_number": task_number,
            "page_index": page_index,
            "page_size_mm": [
                round(float(page.rect.width) * 25.4 / 72.0, 3),
                round(float(page.rect.height) * 25.4 / 72.0, 3),
            ],
        }
        entries.append((task_number, task_name, page_pdf, meta))
    doc.close()
    return entries


def _write_variant_reports(
    variant_dir: Path,
    *,
    rows: list[prep.ArtifactRow],
    reports: list[dict[str, object]],
    source_index: list[dict[str, object]],
    started_at: float,
) -> None:
    if rows:
        prep._write_csv(variant_dir / "_prepared_summary.csv", rows)
    prep._write_json(
        variant_dir / "_prepared_reports.json",
        {
            "generated_at_epoch": started_at,
            "sources": source_index,
            "reports": reports,
        },
    )


def _prepare_variant(variant_dir: Path) -> None:
    started_at = time.time()
    generated_dir = variant_dir / "_generated_pdf"
    generated_dir.mkdir(parents=True, exist_ok=True)
    source_entries = _iter_variant_sources(variant_dir, generated_dir)

    all_rows: list[prep.ArtifactRow] = []
    all_reports: list[dict[str, object]] = []
    source_index: list[dict[str, object]] = []

    for idx, (task_number, task_name, source_pdf, meta) in enumerate(source_entries, start=1):
        print(f"  [{idx}/{len(source_entries)}] {task_name}: {source_pdf.name}")
        package_dir = variant_dir / f"{task_name}_pack"
        report, rows = prep._prepare_drawing_package(source_pdf, package_dir)
        report["task_number"] = task_number
        report["task_name"] = task_name
        report["source_meta"] = meta
        prep._write_json(package_dir / "report.json", report)
        if rows:
            prep._write_csv(package_dir / "summary.csv", rows)
        all_rows.extend(rows)
        all_reports.append(report)
        source_index.append(
            {
                "task_number": task_number,
                "task_name": task_name,
                "prepared_source_pdf": str(source_pdf),
                **meta,
            }
        )
    _write_variant_reports(
        variant_dir,
        rows=all_rows,
        reports=all_reports,
        source_index=source_index,
        started_at=started_at,
    )


def _iter_variant_dirs(root_dir: Path, only_variants: Iterable[str]) -> list[Path]:
    dirs = sorted([path for path in root_dir.iterdir() if path.is_dir()], key=lambda p: p.name.casefold())
    only = [str(item or "").casefold() for item in only_variants if str(item or "").strip()]
    if not only:
        return dirs
    return [path for path in dirs if any(token in path.name.casefold() for token in only)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare drawing packages for Начерт variants.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Root folder with variant subfolders.")
    parser.add_argument("--only-variant", action="append", default=[], help="Optional substring filter for variant dirs.")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    if not root_dir.exists():
        raise FileNotFoundError(f"Root folder not found: {root_dir}")

    variant_dirs = _iter_variant_dirs(root_dir, args.only_variant)
    if not variant_dirs:
        print("No variant folders matched.")
        return 0

    started_at = time.time()
    for index, variant_dir in enumerate(variant_dirs, start=1):
        print(f"[{index}/{len(variant_dirs)}] {variant_dir.name}")
        _prepare_variant(variant_dir)

    elapsed = time.time() - started_at
    print(f"done in {elapsed / 60.0:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
