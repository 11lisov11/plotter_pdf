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
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return 0


def _local_artifact_path(package_dir: Path, raw: str, fallback_name: str) -> str:
    candidate = Path(str(raw or ""))
    if not str(raw or "").strip():
        candidate = package_dir / fallback_name
    elif not candidate.is_absolute():
        candidate = package_dir / candidate
    if candidate.name and (not candidate.exists() or not _is_within(candidate, package_dir)):
        local = package_dir / candidate.name
        if local.exists():
            candidate = local
    if not candidate.exists() and fallback_name:
        local = package_dir / fallback_name
        if local.exists():
            candidate = local
    return str(candidate)


def _audit_items(variant_dir: Path) -> list[dict[str, Any]]:
    payload = _load_json(variant_dir / "_audit.json")
    items = payload.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _ready_audit_ok(variant_dir: Path) -> bool:
    payload = _load_json(variant_dir / "_ready_to_plot_audit.json")
    if not payload:
        return True
    return bool(payload.get("ok", False)) and not list(payload.get("failed_packages") or [])


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


def find_first_ready_package(variant_dir: Path, *, kind: str = "a4") -> ReadyPackageSelection:
    variant_dir = Path(variant_dir)
    if not variant_dir.exists():
        raise FileNotFoundError(f"Variant directory not found: {variant_dir}")
    if not _ready_audit_ok(variant_dir):
        raise RuntimeError(f"Variant is not ready to plot: {variant_dir / '_ready_to_plot_audit.json'}")

    wanted_kind = _normalize_kind(kind)
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
        if task_dir.exists() and not _is_within(package_dir, variant_dir):
            package_dir = task_dir
        elif name_dir.exists() and not _is_within(package_dir, variant_dir):
            package_dir = name_dir
        elif not package_dir.exists():
            if task_dir.exists():
                package_dir = task_dir
            elif name_dir.exists():
                package_dir = name_dir
        summary_rows = _csv_rows(package_dir / "summary.csv")
        row = next((r for r in summary_rows if str(r.get("ok", "")).strip().lower() == "true"), None)
        if row is None:
            row = summary_rows[0] if summary_rows else {}
        row = clean_report_value(row)
        nc = Path(str(row.get("nc") or package_dir / "page_01.nc"))
        if not nc.is_absolute():
            nc = package_dir / nc
        if nc.name and (not nc.exists() or not _is_within(nc, package_dir)):
            local_nc = package_dir / nc.name
            if local_nc.exists():
                nc = local_nc
        if not nc.exists():
            pages_nc = package_dir / "pages" / "page_01.nc"
            if pages_nc.exists():
                nc = pages_nc
        if not nc.exists():
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
            gcode=_local_artifact_path(package_dir, str(row.get("gcode") or ""), "page_01.gcode"),
            preview_pdf=_local_artifact_path(package_dir, str(row.get("preview_pdf") or ""), "page_01.pdf"),
            preview_svg=_local_artifact_path(package_dir, str(row.get("preview_svg") or ""), "page_01.svg"),
            bounds=str(row.get("bounds") or ""),
            line_count=_line_count(nc),
            draw_length_m=draw_length_m,
            layout_similarity=layout_similarity,
            selected_variant=str(item.get("selected_variant") or row.get("selected_variant") or ""),
        )
        return ReadyPackageSelection(**clean_report_value(asdict(selection)))
    raise RuntimeError(f"No ready package with kind={wanted_kind!r} found in {variant_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find the first ready-to-plot package in a prepared variant directory.")
    parser.add_argument("variant_dir", help="Prepared variant directory, e.g. 'Компьютерная графика\\22 вариант'")
    parser.add_argument("--kind", default="a4", help="Package kind to select (default: a4)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        selection = find_first_ready_package(Path(args.variant_dir), kind=args.kind)
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
