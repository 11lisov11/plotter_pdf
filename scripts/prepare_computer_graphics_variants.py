from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import prepare_folder1_packages as prep
import prepare_plotter_ready_new_algorithm as new_algo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "Компьютерная графика"


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _copy_source_pdf_to_package(package_dir: Path, source_pdf: Path) -> None:
    # Keep a human-readable source copy. The public package is intentionally
    # compact: source.pdf, plot_preview.pdf and plotter.nc are produced by the
    # new algorithm below; debug reports stay opt-in there.
    source_copy = package_dir / source_pdf.name
    source_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, source_copy)


def _write_report_for_new_algorithm(package_dir: Path, report: dict) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _new_algorithm_settings(*, keep_debug_artifacts: bool) -> new_algo.Settings:
    return new_algo.Settings(
        drawing_mode="computer_graphics",
        keep_debug_artifacts=bool(keep_debug_artifacts),
    )


def _iter_variant_pdfs(variant_dir: Path) -> list[Path]:
    return sorted([path for path in variant_dir.glob("*.pdf") if path.is_file()], key=lambda p: p.name.casefold())


def _looks_like_variant_dir(path: Path) -> bool:
    name = path.name.casefold()
    return bool(re.search(r"\d+", name) and ("вариант" in name or "variant" in name))


def _iter_variant_dirs(root: Path, requested: set[str]) -> list[Path]:
    variant_dirs = [path for path in sorted(root.iterdir(), key=lambda p: p.name.casefold()) if path.is_dir()]
    if requested:
        return [path for path in variant_dirs if path.name.casefold() in requested]
    return [path for path in variant_dirs if _looks_like_variant_dir(path)]


def _prepare_variant(variant_dir: Path, *, keep_debug_artifacts: bool = False) -> None:
    pdfs = _iter_variant_pdfs(variant_dir)
    if not pdfs:
        print(f"    skip: no PDF files found in {variant_dir}")
        return

    settings = _new_algorithm_settings(keep_debug_artifacts=keep_debug_artifacts)
    for idx, source_pdf in enumerate(pdfs, start=1):
        package_dir = variant_dir / f"{source_pdf.stem}_pack"
        print(f"[{idx}/{len(pdfs)}] processing: {source_pdf.name}")
        report, _rows = prep._prepare_drawing_package(source_pdf, package_dir)
        is_a3 = bool(report.get("a3_two_pass", False))
        if bool(report.get("custom_tiled", False)):
            raise RuntimeError(
                f"Unexpected custom_tiled output for {source_pdf.name}. "
                "Computer Graphics variants must be prepared as A4 single-page or A3 two-pass."
            )
        _copy_source_pdf_to_package(package_dir, source_pdf)
        _write_report_for_new_algorithm(package_dir, report)
        new_algo._prepare_one_pack(package_dir, settings)
        print(f"    done: {'A3-2pass' if is_a3 else 'A4'} -> {package_dir.name}")


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Prepare clean plotter packages for Computer Graphics variants.")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Root folder with variant subfolders.",
    )
    parser.add_argument(
        "--variants",
        nargs="*",
        default=[],
        help='Variant folder names to process, for example: "9 вариант" "26 вариант"',
    )
    parser.add_argument(
        "--keep-debug-artifacts",
        action="store_true",
        help="Keep reports, logs and intermediate previews instead of publishing only clean plotter files.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Root folder not found: {root}")

    requested = {str(item).casefold() for item in (args.variants or []) if str(item).strip()}
    variant_dirs = _iter_variant_dirs(root, requested)
    if not variant_dirs:
        raise FileNotFoundError("No matching variant directories found.")

    started_at = time.time()
    for variant_dir in variant_dirs:
        print(f"== {variant_dir.name} ==")
        _prepare_variant(variant_dir, keep_debug_artifacts=bool(args.keep_debug_artifacts))
    elapsed = time.time() - started_at
    print(f"done in {elapsed / 60.0:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
