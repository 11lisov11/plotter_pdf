from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.plotter_backend.common_utils import clean_report_value


@dataclass(frozen=True)
class ReadyPackageSelection:
    package_dir: str
    task: str
    kind: str
    item: str
    nc: str
    gcode: str
    preview_pdf: str
    preview_svg: str
    bounds: str
    line_count: int
    draw_length_m: float | None
    layout_similarity: float | None
    selected_variant: str


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return 0


def _local_artifact_path(package_dir: Path, raw: str, fallback_name: str) -> str:
    raw_text = str(raw or "").strip()
    candidates: list[Path] = []
    raw_candidate: Path | None = None
    if raw_text:
        raw_candidate = Path(raw_text)
        candidates.append(raw_candidate if raw_candidate.is_absolute() else package_dir / raw_candidate)
    if fallback_name:
        candidates.append(package_dir / fallback_name)
        candidates.append(package_dir / "pages" / fallback_name)
    if raw_candidate is not None and raw_candidate.name:
        candidates.append(package_dir / raw_candidate.name)
        candidates.append(package_dir / "pages" / raw_candidate.name)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and _is_within(candidate, package_dir):
            return str(candidate)

    if raw_candidate is not None:
        resolved_raw = raw_candidate if raw_candidate.is_absolute() else package_dir / raw_candidate
        if _is_within(resolved_raw, package_dir):
            return str(resolved_raw)
    if fallback_name:
        return str(package_dir / fallback_name)
    return str(package_dir)


def _resolve_ready_nc(package_dir: Path, raw: str, item_name: str) -> Path | None:
    item_name = str(item_name or "page_01").strip() or "page_01"
    fallback_names = [f"{item_name}.nc"]

    raw_text = str(raw or "").strip()
    candidates: list[Path] = []
    if raw_text:
        candidate = Path(raw_text)
        candidates.append(candidate if candidate.is_absolute() else package_dir / candidate)
    candidates.extend(package_dir / name for name in fallback_names)
    candidates.extend(package_dir / "pages" / name for name in fallback_names)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and _is_within(candidate, package_dir):
            return candidate
        if candidate.name:
            local = package_dir / candidate.name
            if local.exists():
                return local
    return None


def _audit_items(variant_dir: Path) -> list[dict[str, Any]]:
    payload = _load_json(variant_dir / "_audit.json")
    items = payload.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _ready_audit_ok(variant_dir: Path) -> bool:
    audit_path = variant_dir / "_ready_to_plot_audit.json"
    if not audit_path.exists():
        return False
    payload = _load_json(audit_path)
    if not payload:
        return False
    return payload.get("ok") is True and not list(payload.get("failed_packages") or [])


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _normalize_kind(kind: str) -> str:
    value = str(kind or "a4").strip().lower().replace("-", "_")
    aliases = {
        "first_a4": "a4",
        "page": "a4",
        "a3": "a3_two_pass",
        "a3_two": "a3_two_pass",
        "two_pass": "a3_two_pass",
    }
    return aliases.get(value, value)


def _normalize_item(item: str | None) -> str:
    value = str(item or "").strip().lower().replace("-", "_")
    if not value:
        return ""
    if value.isdigit():
        return f"pass_{int(value):02d}"
    if value.startswith("pass") and value[4:].isdigit():
        return f"pass_{int(value[4:]):02d}"
    if value.startswith("page") and value[4:].isdigit():
        return f"page_{int(value[4:]):02d}"
    return value


def find_first_ready_package(variant_dir: Path, *, kind: str = "a4", item: str | None = None) -> ReadyPackageSelection:
    variant_dir = Path(variant_dir)
    if not variant_dir.exists():
        raise FileNotFoundError(f"Variant directory not found: {variant_dir}")
    if not _ready_audit_ok(variant_dir):
        raise RuntimeError(f"Variant is not ready to plot: {variant_dir / '_ready_to_plot_audit.json'}")

    wanted_kind = _normalize_kind(kind)
    wanted_item = _normalize_item(item)
    for item in _audit_items(variant_dir):
        item = clean_report_value(item)
        item_kind = str(item.get("kind") or "").strip().lower()
        if item_kind != wanted_kind:
            continue
        package_dir = Path(str(item.get("package_dir") or ""))
        if not package_dir.is_absolute():
            package_dir = variant_dir / package_dir
        task_name = str(item.get("task") or package_dir.name)
        task_dir = variant_dir / task_name
        name_dir = variant_dir / package_dir.name
        if not _is_within(package_dir, variant_dir):
            if task_dir.exists():
                package_dir = task_dir
            elif name_dir.exists():
                package_dir = name_dir
            else:
                continue
        elif not package_dir.exists():
            if task_dir.exists():
                package_dir = task_dir
            elif name_dir.exists():
                package_dir = name_dir
        if not package_dir.exists() or not _is_within(package_dir, variant_dir):
            continue
        summary_rows = _csv_rows(package_dir / "summary.csv")
        if wanted_item:
            row = next(
                (
                    r
                    for r in summary_rows
                    if str(r.get("ok", "")).strip().lower() == "true"
                    and _normalize_item(str(r.get("item") or "")) == wanted_item
                ),
                None,
            )
        else:
            row = next((r for r in summary_rows if str(r.get("ok", "")).strip().lower() == "true"), None)
        if row is None:
            continue
        row = clean_report_value(row)
        item_name = _normalize_item(str(row.get("item") or "")) or "page_01"
        nc = _resolve_ready_nc(package_dir, str(row.get("nc") or ""), item_name)
        if nc is None:
            continue
        draw_length_raw = row.get("draw_length_m")
        layout_raw = item.get("layout_similarity")
        try:
            draw_length_m = float(draw_length_raw) if str(draw_length_raw or "").strip() else None
        except Exception:
            draw_length_m = None
        try:
            layout_similarity = float(layout_raw) if layout_raw is not None else None
        except Exception:
            layout_similarity = None
        selection = ReadyPackageSelection(
            package_dir=str(package_dir),
            task=str(item.get("task") or package_dir.name),
            kind=item_kind,
            item=str(row.get("item") or "page_01"),
            nc=str(nc),
            gcode=_local_artifact_path(package_dir, str(row.get("gcode") or ""), f"{item_name}.gcode"),
            preview_pdf=_local_artifact_path(package_dir, str(row.get("preview_pdf") or ""), f"{item_name}.pdf"),
            preview_svg=_local_artifact_path(package_dir, str(row.get("preview_svg") or ""), f"{item_name}.svg"),
            bounds=str(row.get("bounds") or ""),
            line_count=_line_count(nc),
            draw_length_m=draw_length_m,
            layout_similarity=layout_similarity,
            selected_variant=str(item.get("selected_variant") or row.get("selected_variant") or ""),
        )
        return ReadyPackageSelection(**clean_report_value(asdict(selection)))
    detail = f"kind={wanted_kind!r}"
    if wanted_item:
        detail += f" item={wanted_item!r}"
    raise RuntimeError(f"No ready package with {detail} found in {variant_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find the first ready-to-plot package in a prepared variant directory.")
    parser.add_argument("variant_dir", help="Prepared variant directory, e.g. 'Компьютерная графика\\22 вариант'")
    parser.add_argument("--kind", default="a4", help="Package kind to select (default: a4)")
    parser.add_argument("--item", default=None, help="Optional package item to select, e.g. page_01, pass_01 or pass_02.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        selection = find_first_ready_package(Path(args.variant_dir), kind=args.kind, item=args.item)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    payload = clean_report_value(asdict(selection))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"task={payload['task']}")
        print(f"kind={payload['kind']} item={payload['item']}")
        print(f"nc={payload['nc']}")
        print(f"lines={payload['line_count']} draw_length_m={payload['draw_length_m']}")
        print(f"bounds={payload['bounds']}")
        print(f"preview_pdf={payload['preview_pdf']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
