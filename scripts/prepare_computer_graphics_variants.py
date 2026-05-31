from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

import prepare_folder1_packages as prep


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "Компьютерная графика"


def _prune_package_outputs(package_dir: Path, *, is_a3: bool, source_pdf: Path) -> None:
    keep_files = (
        {"pass_01.pdf", "pass_01.gcode", "pass_02.pdf", "pass_02.gcode", source_pdf.name}
        if is_a3
        else {"page_01.pdf", "page_01.gcode", source_pdf.name}
    )
    source_copy = package_dir / source_pdf.name
    source_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, source_copy)
    for child in list(package_dir.iterdir()):
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            continue
        if child.name not in keep_files:
            child.unlink(missing_ok=True)


def _iter_variant_pdfs(variant_dir: Path) -> list[Path]:
    return sorted([path for path in variant_dir.glob("*.pdf") if path.is_file()], key=lambda p: p.name.casefold())


def _prepare_variant(variant_dir: Path) -> None:
    pdfs = _iter_variant_pdfs(variant_dir)
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {variant_dir}")

    for idx, source_pdf in enumerate(pdfs, start=1):
        package_dir = variant_dir / source_pdf.stem
        print(f"[{idx}/{len(pdfs)}] processing: {source_pdf.name}")
        report, _rows = prep._prepare_drawing_package(source_pdf, package_dir)
        is_a3 = bool(report.get("a3_two_pass", False))
        if bool(report.get("custom_tiled", False)):
            raise RuntimeError(
                f"Unexpected custom_tiled output for {source_pdf.name}. "
                "Variants 20/22 must be prepared as A4 single-page or A3 two-pass."
            )
        _prune_package_outputs(package_dir, is_a3=is_a3, source_pdf=source_pdf)
        print(f"    done: {'A3-2pass' if is_a3 else 'A4'} -> {package_dir.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare compact drawing packages for Computer Graphics variants.")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Root folder with variant subfolders, default: Компьютерная графика",
    )
    parser.add_argument(
        "--variants",
        nargs="*",
        default=[],
        help='Variant folder names to process, for example: "20 вариант" "22 вариант"',
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Root folder not found: {root}")

    requested = {str(item).casefold() for item in (args.variants or []) if str(item).strip()}
    variant_dirs = [path for path in sorted(root.iterdir(), key=lambda p: p.name.casefold()) if path.is_dir()]
    if requested:
        variant_dirs = [path for path in variant_dirs if path.name.casefold() in requested]
    if not variant_dirs:
        raise FileNotFoundError("No matching variant directories found.")

    started_at = time.time()
    for variant_dir in variant_dirs:
        print(f"== {variant_dir.name} ==")
        _prepare_variant(variant_dir)
    elapsed = time.time() - started_at
    print(f"done in {elapsed / 60.0:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
