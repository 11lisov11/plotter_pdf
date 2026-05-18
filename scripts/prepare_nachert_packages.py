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
DEFAULT_ROOT = PROJECT_ROOT / "\u041d\u0430\u0447\u0435\u0440\u0442"


def _prune_package_outputs(package_dir: Path, *, is_a3: bool, source_pdf: Path) -> None:
    # Keep the full production package contract.  Older compact packages removed
    # reports, summaries, compare panels, logs, pages and clean-source PDFs; that
    # made later ready-to-plot validation impossible and hid bad G-code.
    source_copy = package_dir / "source_kompas.pdf"
    source_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, source_copy)
def _task_number_from_name(name: str) -> int | None:
    match = re.search(r"(\d+)", str(name or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _reserve_output_path(preferred: Path) -> Path:
    preferred.parent.mkdir(parents=True, exist_ok=True)
    if not preferred.exists():
        return preferred
    try:
        preferred.unlink()
        return preferred
    except Exception:
        pass
    stem = preferred.stem
    suffix = preferred.suffix
    for idx in range(1, 1000):
        candidate = preferred.with_name(f"{stem}__regen_{idx}{suffix}")
        if candidate.exists():
            try:
                candidate.unlink()
                return candidate
            except Exception:
                continue
        return candidate
    raise RuntimeError(f"Unable to allocate writable output path near: {preferred}")


def _write_single_page_pdf(source_pdf: Path, page_index0: int, out_pdf: Path) -> Path:
    out_pdf = _reserve_output_path(out_pdf)
    src = fitz.open(source_pdf)
    dst = fitz.open()
    try:
        dst.insert_pdf(src, from_page=page_index0, to_page=page_index0)
        if dst.page_count:
            page = dst[0]
            if int(page.rotation or 0) != 0:
                page.remove_rotation()
        dst.save(out_pdf)
    finally:
        dst.close()
        src.close()
    return out_pdf


def _merge_split_a3_pdf(source_pdf: Path, out_pdf: Path) -> Path:
    src = fitz.open(source_pdf)
    if src.page_count != 2:
        raise ValueError(f"Expected exactly 2 pages for split A3 source: {source_pdf}")
    left = src[0]
    right = src[1]
    out_pdf = _reserve_output_path(out_pdf)
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
    return out_pdf


def _prepare_frw_source_pdf(source_path: Path, generated_dir: Path) -> tuple[Path, dict[str, object]]:
    generated_dir.mkdir(parents=True, exist_ok=True)
    raw_pdf = _reserve_output_path(generated_dir / f"{source_path.stem}__kompas.pdf")
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
    if page_count == 2:
        merged_pdf = _merge_split_a3_pdf(raw_pdf, generated_dir / f"{source_path.stem}.pdf")
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
    final_pdf = _reserve_output_path(generated_dir / f"{source_path.stem}.pdf")
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
        generated_pdfs = sorted(
            [
                path
                for path in generated_dir.glob("*.pdf")
                if "__kompas" not in path.stem and "__regen_" not in path.stem
            ],
            key=lambda p: (_task_number_from_name(p.stem) or 999, p.name.lower()),
        )
        if generated_pdfs:
            for pdf_path in generated_pdfs:
                task_number = _task_number_from_name(pdf_path.stem)
                if task_number is None:
                    continue
                entries.append(
                    (
                        task_number,
                        pdf_path.stem,
                        pdf_path,
                        {
                            "source_kind": "generated_pdf",
                            "task_number": task_number,
                            "generated_pdf": str(pdf_path),
                        },
                    )
                )
            if entries:
                return entries
        raise FileNotFoundError(f"No FRW or PDF sources found in {variant_dir}")
    if len(pdf_files) != 1:
        raise RuntimeError(f"Expected exactly one multipage PDF in {variant_dir}, found {len(pdf_files)}")

    multi_pdf = pdf_files[0]
    doc = fitz.open(multi_pdf)
    page_count = int(doc.page_count)
    for page_index in range(page_count):
        task_number = page_index + 1
        task_name = f"Задача {task_number}"
        page_pdf = _write_single_page_pdf(multi_pdf, page_index, generated_dir / f"{task_name}.pdf")
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


def _load_variant_state(variant_dir: Path) -> tuple[list[prep.ArtifactRow], list[dict[str, object]], list[dict[str, object]]]:
    rows = prep._read_rows_from_csv(variant_dir / "_prepared_summary.csv")
    reports_path = variant_dir / "_prepared_reports.json"
    if not reports_path.exists():
        return rows, [], []
    try:
        payload = json.loads(reports_path.read_text(encoding="utf-8"))
    except Exception:
        return rows, [], []
    reports = list(payload.get("reports", []) or [])
    source_index = list(payload.get("sources", []) or [])
    return rows, reports, source_index


def _task_number_from_row_package_dir(row: prep.ArtifactRow) -> int | None:
    try:
        return _task_number_from_name(Path(row.package_dir).name)
    except Exception:
        return None


def _prepare_variant(variant_dir: Path, *, only_tasks: set[int] | None = None) -> None:
    started_at = time.time()
    generated_dir = variant_dir / "_generated_pdf"
    generated_dir.mkdir(parents=True, exist_ok=True)
    source_entries = _iter_variant_sources(variant_dir, generated_dir)
    if only_tasks:
        only_tasks = {int(v) for v in only_tasks}
        source_entries = [entry for entry in source_entries if int(entry[0]) in only_tasks]

    all_rows: list[prep.ArtifactRow] = []
    all_reports: list[dict[str, object]] = []
    source_index: list[dict[str, object]] = []
    existing_rows: list[prep.ArtifactRow] = []
    existing_reports: list[dict[str, object]] = []
    existing_sources: list[dict[str, object]] = []
    if only_tasks:
        existing_rows, existing_reports, existing_sources = _load_variant_state(variant_dir)

    for idx, (task_number, task_name, source_pdf, meta) in enumerate(source_entries, start=1):
        print(f"  [{idx}/{len(source_entries)}] {task_name}: {source_pdf.name}")
        package_dir = variant_dir / f"{task_name}_pack"
        report, rows = prep._prepare_drawing_package(source_pdf, package_dir)
        report["task_number"] = task_number
        report["task_name"] = task_name
        report["source_meta"] = meta
        report["package_dir"] = str(package_dir)
        compare_meta = prep._generate_package_compare_artifacts(package_dir, report, rows)
        report["compare_generated"] = bool(compare_meta.get("compare_generated"))
        if "compare" in compare_meta:
            report["compare"] = dict(compare_meta.get("compare", {}) or {})
        if str(compare_meta.get("compare_error", "")).strip():
            report["compare_error"] = str(compare_meta.get("compare_error", ""))
        prep._write_json(package_dir / "report.json", report)
        if rows:
            prep._write_csv(package_dir / "summary.csv", rows)
        _prune_package_outputs(package_dir, is_a3=bool(report.get("a3_two_pass", False)), source_pdf=source_pdf)
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

    if only_tasks:
        keep_tasks = {int(v) for v in only_tasks}
        all_rows = [row for row in existing_rows if _task_number_from_row_package_dir(row) not in keep_tasks] + all_rows
        all_reports = [
            report
            for report in existing_reports
            if int(report.get("task_number", -1) or -1) not in keep_tasks
        ] + all_reports
        source_index = [
            source
            for source in existing_sources
            if int(source.get("task_number", -1) or -1) not in keep_tasks
        ] + source_index

    all_rows.sort(key=lambda row: (_task_number_from_row_package_dir(row) or 999, row.item))
    all_reports.sort(key=lambda report: int(report.get("task_number", 999) or 999))
    source_index.sort(key=lambda item: int(item.get("task_number", 999) or 999))
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

    def _matches(path: Path, token: str) -> bool:
        name = path.name.casefold()
        if token == name:
            return True
        token_number = _task_number_from_name(token)
        name_number = _task_number_from_name(name)
        if token_number is not None:
            return name_number == token_number
        return token in name

    return [path for path in dirs if any(_matches(path, token) for token in only)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare drawing packages for Начерт variants.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Root folder with variant subfolders.")
    parser.add_argument("--only-variant", action="append", default=[], help="Optional variant filter; numeric tokens match exact variant number.")
    parser.add_argument("--only-task", type=int, action="append", default=[], help="Optional task number filter.")
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
        _prepare_variant(variant_dir, only_tasks=set(int(v) for v in args.only_task))

    elapsed = time.time() - started_at
    print(f"done in {elapsed / 60.0:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
