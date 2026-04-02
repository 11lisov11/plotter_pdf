from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import prepare_toe_handwriting_package as toe_prepare


def _resolve_source_pdf(pdf_arg: str) -> Path:
    pdf_path = Path(str(pdf_arg))
    if not pdf_path.is_absolute():
        pdf_path = PROJECT_ROOT / pdf_path
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists() or not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    return pdf_path


def _resolve_package_dir(source_pdf: Path, out_dir_arg: str) -> Path:
    if str(out_dir_arg).strip():
        out_dir = Path(str(out_dir_arg))
        if not out_dir.is_absolute():
            out_dir = PROJECT_ROOT / out_dir
        return out_dir.resolve()
    return source_pdf.with_name(f"{source_pdf.stem}_pack")


def _resolve_overrides_path(package_dir: Path, overrides_arg: str) -> Path:
    if str(overrides_arg).strip():
        path = Path(str(overrides_arg))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()
    return toe_prepare._default_page_overrides_path(package_dir)


def _load_overrides_payload(overrides_path: Path) -> dict[str, Any]:
    if not overrides_path.exists() or not overrides_path.is_file():
        return {"pages": {}}
    try:
        payload = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception:
        return {"pages": {}}
    if not isinstance(payload, dict):
        return {"pages": {}}
    pages = payload.get("pages")
    if not isinstance(pages, dict):
        payload = {"pages": {}}
    return payload


def _save_overrides_payload(overrides_path: Path, payload: dict[str, Any]) -> None:
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_report(package_dir: Path) -> dict[str, Any]:
    report_path = package_dir / "report.json"
    if not report_path.exists() or not report_path.is_file():
        raise FileNotFoundError(f"Report not found: {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def _find_report_item(report: dict[str, Any], page_index: int) -> dict[str, Any] | None:
    for item in report.get("items", []):
        if int(item.get("page_index", 0) or 0) == int(page_index):
            return item
    return None


def _print_page_summary(report_item: dict[str, Any]) -> None:
    print(
        f"page_{int(report_item.get('page_index', 0)):02d}: "
        f"selected={report_item.get('selected_variant')} "
        f"font={report_item.get('selected_font')} "
        f"sim={float(report_item.get('selected_layout_similarity', 0.0) or 0.0):.6f}"
    )
    print(f"  source_strategy={report_item.get('source_strategy')}")
    print(f"  selected_reason={report_item.get('selected_reason')}")
    if report_item.get("page_override"):
        print(f"  page_override={json.dumps(report_item.get('page_override'), ensure_ascii=False)}")
        print(f"  page_override_applied={bool(report_item.get('page_override_applied'))}")
        if report_item.get("page_override_error"):
            print(f"  page_override_error={report_item.get('page_override_error')}")


def _cmd_show(args) -> int:
    source_pdf = _resolve_source_pdf(args.pdf)
    package_dir = _resolve_package_dir(source_pdf, args.out_dir)
    overrides_path = _resolve_overrides_path(package_dir, args.overrides_file)
    overrides = toe_prepare._load_page_overrides(overrides_path)
    report = _load_report(package_dir)

    if args.page:
        report_item = _find_report_item(report, int(args.page))
        if report_item is None:
            raise KeyError(f"Page not found in report: {args.page}")
        _print_page_summary(report_item)
        print("  candidates:")
        for candidate in report_item.get("candidates", []):
            if not bool(candidate.get("ok")):
                continue
            print(
                f"    {candidate.get('variant_label')} "
                f"font={candidate.get('font_label')} "
                f"contours={candidate.get('image_contours_mode')} "
                f"sim={float(candidate.get('layout_similarity', 0.0) or 0.0):.6f}"
            )
        return 0

    print(f"package={package_dir}")
    print(f"overrides_file={overrides_path}")
    print(f"page_overrides={len(overrides)}")
    for item in report.get("items", []):
        _print_page_summary(item)
    return 0


def _cmd_set(args) -> int:
    if not str(args.variant_label or "").strip() and not str(args.font_label or "").strip():
        raise ValueError("set requires at least --variant-label or --font-label")
    source_pdf = _resolve_source_pdf(args.pdf)
    package_dir = _resolve_package_dir(source_pdf, args.out_dir)
    overrides_path = _resolve_overrides_path(package_dir, args.overrides_file)
    payload = _load_overrides_payload(overrides_path)
    pages = dict(payload.get("pages") or {})
    override = toe_prepare._normalize_page_override(
        {
            "variant_label": args.variant_label,
            "font_label": args.font_label,
            "image_contours_mode": args.image_contours_mode,
            "notes": args.notes,
        }
    )
    variant_label = str(override.get("variant_label", "") or "")
    if variant_label and variant_label not in toe_prepare.MANUAL_OVERRIDE_VARIANTS:
        raise ValueError(
            f"Unsupported variant_label '{variant_label}'. "
            f"Allowed: {', '.join(sorted(toe_prepare.MANUAL_OVERRIDE_VARIANTS))}"
        )
    pages[str(int(args.page))] = override
    payload["pages"] = pages
    _save_overrides_payload(overrides_path, payload)
    print(f"saved_override page={int(args.page)} path={overrides_path}")
    return 0


def _cmd_clear(args) -> int:
    source_pdf = _resolve_source_pdf(args.pdf)
    package_dir = _resolve_package_dir(source_pdf, args.out_dir)
    overrides_path = _resolve_overrides_path(package_dir, args.overrides_file)
    payload = _load_overrides_payload(overrides_path)
    pages = dict(payload.get("pages") or {})
    pages.pop(str(int(args.page)), None)
    payload["pages"] = pages
    _save_overrides_payload(overrides_path, payload)
    print(f"cleared_override page={int(args.page)} path={overrides_path}")
    return 0


def _cmd_rebuild(args) -> int:
    source_pdf = _resolve_source_pdf(args.pdf)
    package_dir = _resolve_package_dir(source_pdf, args.out_dir)
    overrides_path = _resolve_overrides_path(package_dir, args.overrides_file)
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "prepare_toe_handwriting_package.py"),
        "--pdf",
        str(source_pdf),
        "--out-dir",
        str(package_dir),
        "--overrides-file",
        str(overrides_path),
        "--resume",
    ]
    print("running:", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    return int(completed.returncode)


def _cmd_suggest(args) -> int:
    source_pdf = _resolve_source_pdf(args.pdf)
    package_dir = _resolve_package_dir(source_pdf, args.out_dir)
    report = _load_report(package_dir)
    suggestions: dict[str, Any] = {"pages": {}}
    for item in report.get("items", []):
        candidates = [candidate for candidate in item.get("candidates", []) if isinstance(candidate, dict)]
        selected_variant = str(item.get("selected_variant", "") or "")
        selected_font = str(item.get("selected_font", "") or "")
        selected = next(
            (
                candidate
                for candidate in candidates
                if bool(candidate.get("ok"))
                and str(candidate.get("variant_label", "") or "") == selected_variant
                and str(candidate.get("font_label", "") or "") == selected_font
            ),
            None,
        )
        if selected is None:
            continue
        dominating = toe_prepare._prefer_dominating_candidate(selected=selected, page_results=candidates)
        if dominating is selected:
            continue
        page_index = int(item.get("page_index", 0) or 0)
        if page_index <= 0:
            continue
        suggestions["pages"][str(page_index)] = {
            "variant_label": str(dominating.get("variant_label", "") or ""),
            "font_label": str(dominating.get("font_label", "") or ""),
            "image_contours_mode": str(dominating.get("image_contours_mode", "") or ""),
            "notes": "auto_suggested_from_report",
        }

    if args.write:
        out_path = Path(str(args.write))
        if not out_path.is_absolute():
            out_path = package_dir / out_path
        _save_overrides_payload(out_path.resolve(), suggestions)
        print(f"saved_suggestions path={out_path.resolve()}")
    else:
        print(json.dumps(suggestions, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple TOE package override editor.")
    parser.add_argument("--pdf", required=True, help="Source TOE PDF path.")
    parser.add_argument("--out-dir", default="", help="Optional package dir. Defaults to <pdf>_pack.")
    parser.add_argument("--overrides-file", default="", help="Optional overrides file path.")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Show selected page result and candidates.")
    show.add_argument("--page", type=int, default=0, help="Optional page index.")
    show.set_defaults(func=_cmd_show)

    set_cmd = sub.add_parser("set", help="Set page override.")
    set_cmd.add_argument("--page", type=int, required=True)
    set_cmd.add_argument("--variant-label", default="", help="Manual variant label.")
    set_cmd.add_argument("--font-label", default="", help="Manual font label.")
    set_cmd.add_argument("--image-contours-mode", default="", help="Optional contours mode filter.")
    set_cmd.add_argument("--notes", default="", help="Optional free-form note.")
    set_cmd.set_defaults(func=_cmd_set)

    clear = sub.add_parser("clear", help="Clear page override.")
    clear.add_argument("--page", type=int, required=True)
    clear.set_defaults(func=_cmd_clear)

    rebuild = sub.add_parser("rebuild", help="Rebuild package with current overrides.")
    rebuild.set_defaults(func=_cmd_rebuild)

    suggest = sub.add_parser("suggest", help="Suggest page overrides from current report.")
    suggest.add_argument("--write", default="", help="Optional output JSON path for suggested overrides.")
    suggest.set_defaults(func=_cmd_suggest)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
