from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz

from .models import JobResult, JobSettings


MM_TO_PT = 72.0 / 25.4
SHEET_SIZES_MM: dict[str, tuple[float, float]] = {
    "a4": (210.0, 297.0),
    "a3": (420.0, 297.0),
    "a2": (420.0, 594.0),
}
SHEET_CAPACITY = {"a4": 1, "a3": 2, "a2": 4}

# Slot rectangles use real A2 paper coordinates. The CoreXY reaches
# 390 x 590 mm, leaving 15 mm at left/right and 2 mm at top/bottom.
# PDF Y grows down; machine Y grows from the lower-left HOME away from us.
A2_ZONE_LAYOUTS: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "a2_single": {"A2": (15.0, 2.0, 405.0, 592.0)},
    "a3_pair": {
        "1": (15.0, 297.0, 405.0, 592.0),
        "2": (15.0, 2.0, 405.0, 297.0),
    },
    "a4_quad": {
        "11": (15.0, 297.0, 210.0, 592.0),
        "12": (210.0, 297.0, 405.0, 592.0),
        "21": (15.0, 2.0, 210.0, 297.0),
        "22": (210.0, 2.0, 405.0, 297.0),
    },
    "mixed_a3_near": {
        "1": (15.0, 297.0, 405.0, 592.0),
        "21": (15.0, 2.0, 210.0, 297.0),
        "22": (210.0, 2.0, 405.0, 297.0),
    },
    "mixed_a3_far": {
        "11": (15.0, 297.0, 210.0, 592.0),
        "12": (210.0, 297.0, 405.0, 592.0),
        "2": (15.0, 2.0, 405.0, 297.0),
    },
}


def _normalise_zone_layout(value: str | None) -> str:
    key = str(value or "none").strip().lower().replace("-", "_")
    key = {"": "none", "off": "none", "a2": "a2_single", "a3": "a3_pair", "a4": "a4_quad"}.get(key, key)
    if key != "none" and key not in A2_ZONE_LAYOUTS:
        raise ValueError(f"Unknown large-plotter zone layout: {value!r}")
    return key


def zone_layout_zones(value: str | None) -> tuple[str, ...]:
    key = _normalise_zone_layout(value)
    return tuple(A2_ZONE_LAYOUTS.get(key, {}))


@dataclass(frozen=True, slots=True)
class PdfLayoutItem:
    path: Path
    page_index: int = 0
    rotation_deg: int = 0
    zone: str = ""


@dataclass(slots=True)
class PdfLayoutBuild:
    output_pdf: Path
    preview_pdf: Path
    manifest_path: Path
    page_pdf_paths: list[Path]
    page_count: int
    placements: list[dict]


def _normalise_rotation(value: int) -> int:
    rotation = int(value) % 360
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("Поворот страницы должен быть 0, 90, 180 или 270 градусов.")
    return rotation


def _sheet_size(sheet_format: str) -> tuple[float, float]:
    key = str(sheet_format or "a4").strip().lower()
    if key not in SHEET_SIZES_MM:
        raise ValueError(f"Раскладка PDF поддерживает A4, A3 и A2, получено: {sheet_format!r}")
    return SHEET_SIZES_MM[key]


def _capacity(sheet_format: str) -> int:
    return SHEET_CAPACITY[str(sheet_format).strip().lower()]


def _candidate_grids(count: int, mode: str) -> list[tuple[int, int]]:
    count = max(1, int(count))
    key = str(mode or "auto").strip().lower()
    if key == "single":
        return [(1, 1)]
    if key == "horizontal":
        return [(count, 1)]
    if key == "vertical":
        return [(1, count)]
    if key == "grid":
        return [(2, max(1, int(math.ceil(count / 2.0))))]
    if key != "auto":
        raise ValueError(f"Неизвестный режим раскладки: {mode!r}")
    if count == 1:
        return [(1, 1)]
    if count == 2:
        return [(2, 1), (1, 2)]
    return [(2, 2)]


def _page_size_mm(item: PdfLayoutItem) -> tuple[float, float]:
    with fitz.open(item.path) as doc:
        if item.page_index >= doc.page_count:
            raise ValueError(
                f"В файле {item.path.name} нет страницы {item.page_index + 1}; всего страниц: {doc.page_count}."
            )
        rect = doc[item.page_index].rect
    width = float(rect.width) / MM_TO_PT
    height = float(rect.height) / MM_TO_PT
    if _normalise_rotation(item.rotation_deg) in {90, 270}:
        width, height = height, width
    return width, height


def _choose_grid(
    items: list[PdfLayoutItem],
    *,
    sheet_w_mm: float,
    sheet_h_mm: float,
    mode: str,
    margin_mm: float,
    gap_mm: float,
) -> tuple[int, int]:
    sizes = [_page_size_mm(item) for item in items]
    scored: list[tuple[tuple[float, float, float], tuple[int, int]]] = []
    for cols, rows in _candidate_grids(len(items), mode):
        usable_w = sheet_w_mm - 2.0 * margin_mm - gap_mm * max(0, cols - 1)
        usable_h = sheet_h_mm - 2.0 * margin_mm - gap_mm * max(0, rows - 1)
        if usable_w <= 0.0 or usable_h <= 0.0 or cols * rows < len(items):
            continue
        cell_w = usable_w / cols
        cell_h = usable_h / rows
        scales = [min(cell_w / max(w, 1e-9), cell_h / max(h, 1e-9)) for w, h in sizes]
        scored.append(((min(scales), sum(scales), -float(cols * rows - len(items))), (cols, rows)))
    if not scored:
        raise ValueError("Файлы не помещаются в выбранную сетку и поля листа.")
    return max(scored, key=lambda row: row[0])[1]


def _fit_rect_mm(
    source_w_mm: float,
    source_h_mm: float,
    slot: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = slot
    slot_w = x1 - x0
    slot_h = y1 - y0
    scale = min(slot_w / max(source_w_mm, 1e-9), slot_h / max(source_h_mm, 1e-9))
    width = source_w_mm * scale
    height = source_h_mm * scale
    left = x0 + (slot_w - width) * 0.5
    top = y0 + (slot_h - height) * 0.5
    return left, top, left + width, top + height


def _rect_pt(rect_mm: tuple[float, float, float, float]) -> fitz.Rect:
    return fitz.Rect(*(float(value) * MM_TO_PT for value in rect_mm))


def _ui_font_path() -> Path | None:
    candidates = (Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\arial.ttf"))
    return next((path for path in candidates if path.exists()), None)


def create_pdf_layout(
    items: Iterable[PdfLayoutItem],
    *,
    sheet_format: str,
    output_pdf: Path,
    preview_pdf: Path,
    manifest_path: Path,
    layout_mode: str = "auto",
    margin_mm: float = 0.0,
    gap_mm: float = 0.0,
    zone_layout: str = "none",
) -> PdfLayoutBuild:
    zone_layout_key = _normalise_zone_layout(zone_layout)
    normalized_items = [
        PdfLayoutItem(
            Path(item.path),
            max(0, int(item.page_index)),
            _normalise_rotation(item.rotation_deg),
            str(item.zone or "").strip().upper(),
        )
        for item in items
    ]
    if not normalized_items:
        raise ValueError("Для раскладки не выбрано ни одной страницы PDF.")
    for item in normalized_items:
        if not item.path.exists():
            raise FileNotFoundError(f"Файл не найден: {item.path}")
        if item.path.suffix.lower() != ".pdf":
            raise ValueError(f"Многофайловая раскладка принимает PDF, получено: {item.path.name}")

    fmt = "a2" if zone_layout_key != "none" else str(sheet_format).strip().lower()
    sheet_w_mm, sheet_h_mm = _sheet_size(fmt)
    capacity = len(A2_ZONE_LAYOUTS[zone_layout_key]) if zone_layout_key != "none" else _capacity(fmt)
    margin = max(0.0, float(margin_mm))
    gap = max(0.0, float(gap_mm))
    if zone_layout_key != "none" and len(normalized_items) > capacity:
        raise ValueError(
            f"Zone layout {zone_layout_key} has {capacity} slots, but {len(normalized_items)} files were selected."
        )
    chunks = [normalized_items] if zone_layout_key != "none" else [
        normalized_items[index : index + capacity] for index in range(0, len(normalized_items), capacity)
    ]
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    for path in (output_pdf, preview_pdf, manifest_path):
        if path.exists():
            path.unlink()

    clean_doc = fitz.open()
    placements: list[dict] = []
    source_docs: dict[Path, fitz.Document] = {}
    try:
        for output_page_index, chunk in enumerate(chunks):
            zone_slots = A2_ZONE_LAYOUTS.get(zone_layout_key, {})
            assigned: list[tuple[PdfLayoutItem, str]] = []
            if zone_slots:
                used_zones: set[str] = set()
                for item in chunk:
                    zone = item.zone or next((candidate for candidate in zone_slots if candidate not in used_zones), "")
                    if zone not in zone_slots:
                        raise ValueError(f"Zone {zone!r} is not available in layout {zone_layout_key}.")
                    if zone in used_zones:
                        raise ValueError(f"More than one file is assigned to zone {zone}.")
                    used_zones.add(zone)
                    assigned.append((item, zone))
                cols, rows = 2, 2
            else:
                cols, rows = _choose_grid(
                    chunk,
                    sheet_w_mm=sheet_w_mm,
                    sheet_h_mm=sheet_h_mm,
                    mode=layout_mode,
                    margin_mm=margin,
                    gap_mm=gap,
                )
                usable_w = sheet_w_mm - 2.0 * margin - gap * max(0, cols - 1)
                usable_h = sheet_h_mm - 2.0 * margin - gap * max(0, rows - 1)
                cell_w = usable_w / cols
                cell_h = usable_h / rows
                assigned = [(item, "") for item in chunk]
            target_page = clean_doc.new_page(width=sheet_w_mm * MM_TO_PT, height=sheet_h_mm * MM_TO_PT)
            for item_index, (item, zone) in enumerate(assigned):
                if zone:
                    slot = zone_slots[zone]
                    col = 1 if zone in {"12", "22"} else 0
                    row = 1 if zone in {"1", "11", "12"} else 0
                else:
                    col = item_index % cols
                    row = item_index // cols
                    slot_x0 = margin + col * (cell_w + gap)
                    slot_y0 = margin + row * (cell_h + gap)
                    slot = (slot_x0, slot_y0, slot_x0 + cell_w, slot_y0 + cell_h)
                source_w, source_h = _page_size_mm(item)
                fitted = _fit_rect_mm(source_w, source_h, slot)
                source_doc = source_docs.get(item.path)
                if source_doc is None:
                    source_doc = fitz.open(item.path)
                    source_docs[item.path] = source_doc
                target_page.show_pdf_page(
                    _rect_pt(fitted),
                    source_doc,
                    item.page_index,
                    rotate=item.rotation_deg,
                    keep_proportion=True,
                    overlay=True,
                )
                placements.append(
                    {
                        "output_page": output_page_index + 1,
                        "slot": zone or item_index + 1,
                        "zone": zone or None,
                        "grid": {"cols": cols, "rows": rows, "col": col + 1, "row": row + 1},
                        "source": str(item.path),
                        "source_page": item.page_index + 1,
                        "rotation_deg": item.rotation_deg,
                        "slot_rect_mm": [round(value, 4) for value in slot],
                        "content_rect_mm": [round(value, 4) for value in fitted],
                    }
                )
        clean_doc.save(output_pdf, garbage=4, deflate=True)
        page_pdf_paths: list[Path] = []
        for index in range(clean_doc.page_count):
            page_path = output_pdf.with_name(f"{output_pdf.stem}_sheet_{index + 1:02d}.pdf")
            if page_path.exists():
                page_path.unlink()
            one_page = fitz.open()
            one_page.insert_pdf(clean_doc, from_page=index, to_page=index)
            one_page.save(page_path, garbage=4, deflate=True)
            one_page.close()
            page_pdf_paths.append(page_path)

        preview_doc = fitz.open()
        header_mm = 18.0
        font_path = _ui_font_path()
        for index in range(clean_doc.page_count):
            page = preview_doc.new_page(width=sheet_w_mm * MM_TO_PT, height=(sheet_h_mm + header_mm) * MM_TO_PT)
            page.draw_rect(page.rect, color=(0.10, 0.13, 0.18), fill=(0.96, 0.97, 0.98), width=0.5)
            sheet_rect = fitz.Rect(0, header_mm * MM_TO_PT, sheet_w_mm * MM_TO_PT, (sheet_h_mm + header_mm) * MM_TO_PT)
            page.show_pdf_page(sheet_rect, clean_doc, index)
            page_placements = [row for row in placements if row["output_page"] == index + 1]
            grid = page_placements[0]["grid"] if page_placements else {"cols": 1, "rows": 1}
            title = f"Лист {index + 1}/{clean_doc.page_count} • {fmt.upper()} • раскладка {grid['cols']}×{grid['rows']}"
            details = "   ".join(
                f"{row['slot']}: {Path(row['source']).name}, стр. {row['source_page']}, {row['rotation_deg']}°"
                for row in page_placements
            )
            font_name = "helv"
            if font_path is not None:
                font_name = "layoutui"
                page.insert_font(fontname=font_name, fontfile=str(font_path))
            page.insert_text(fitz.Point(4 * MM_TO_PT, 6 * MM_TO_PT), title, fontsize=10, fontname=font_name, color=(0.05, 0.15, 0.35))
            page.insert_textbox(
                fitz.Rect(4 * MM_TO_PT, 8 * MM_TO_PT, (sheet_w_mm - 4) * MM_TO_PT, 16 * MM_TO_PT),
                details,
                fontsize=7,
                fontname=font_name,
                color=(0.15, 0.20, 0.28),
            )
            for row in page_placements:
                x0, y0, x1, y1 = row["slot_rect_mm"]
                slot_rect = fitz.Rect(x0 * MM_TO_PT, (y0 + header_mm) * MM_TO_PT, x1 * MM_TO_PT, (y1 + header_mm) * MM_TO_PT)
                page.draw_rect(slot_rect, color=(0.15, 0.39, 0.92), width=0.8, dashes="[4 2] 0")
                badge = fitz.Rect(slot_rect.x0 + 2, slot_rect.y0 + 2, slot_rect.x0 + 18, slot_rect.y0 + 18)
                page.draw_rect(badge, color=(0.15, 0.39, 0.92), fill=(0.90, 0.94, 1.0), width=0.5)
                page.insert_text(fitz.Point(badge.x0 + 5, badge.y0 + 11), str(row["slot"]), fontsize=7, fontname="helv", color=(0.05, 0.20, 0.65))
        preview_doc.save(preview_pdf, garbage=4, deflate=True)
        preview_doc.close()
        manifest_path.write_text(
            json.dumps(
                {
                    "sheet_format": fmt,
                    "sheet_size_mm": [sheet_w_mm, sheet_h_mm],
                    "layout_mode": layout_mode,
                    "zone_layout": zone_layout_key,
                    "margin_mm": margin,
                    "gap_mm": gap,
                    "page_count": clean_doc.page_count,
                    "placements": placements,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return PdfLayoutBuild(output_pdf, preview_pdf, manifest_path, page_pdf_paths, clean_doc.page_count, placements)
    finally:
        for source_doc in source_docs.values():
            source_doc.close()
        clean_doc.close()


def build_pdf_layout(settings: JobSettings) -> PdfLayoutBuild:
    items = [
        PdfLayoutItem(path, page, rotation, zone)
        for path, page, rotation, zone in settings.normalized_zone_layout_items()
    ]
    output_dir = settings.normalized_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = items[0].path.stem if items else "drawing"
    zone_layout = _normalise_zone_layout(settings.zone_layout)
    fmt = "a2" if zone_layout != "none" else str(settings.sheet_format or "a4").lower()
    suffix = f"zones_{zone_layout}" if zone_layout != "none" else fmt
    return create_pdf_layout(
        items,
        sheet_format=fmt,
        output_pdf=output_dir / f"{stem}_layout_{suffix}.pdf",
        preview_pdf=output_dir / f"{stem}_layout_{suffix}_preview.pdf",
        manifest_path=output_dir / f"{stem}_layout_{suffix}.json",
        layout_mode=settings.layout_mode,
        margin_mm=settings.layout_margin_mm,
        gap_mm=settings.layout_gap_mm,
        zone_layout=zone_layout,
    )


def build_pdf_layout_job(settings: JobSettings) -> JobResult:
    output_dir = settings.normalized_output_dir()
    try:
        build = build_pdf_layout(settings)
    except Exception as exc:
        return JobResult(False, f"Не удалось собрать раскладку PDF: {exc}", output_dir=output_dir, errors=[str(exc)])
    return JobResult(
        True,
        f"Раскладка готова: {build.preview_pdf}",
        output_dir=output_dir,
        layout_pdf_path=build.output_pdf,
        layout_preview_pdf_path=build.preview_pdf,
        layout_manifest_path=build.manifest_path,
        layout_page_paths=build.page_pdf_paths,
        layout_page_count=build.page_count,
    )
