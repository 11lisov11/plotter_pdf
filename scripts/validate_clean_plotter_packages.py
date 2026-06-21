from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = (
    PROJECT_ROOT / "Компьютерная графика",
    PROJECT_ROOT / "Начерт",
)

SINGLE_PAGE_FILES = {"source.pdf", "plot_preview.pdf", "plotter.nc"}
TWO_PASS_FILES = {"source.pdf", "plot_preview.pdf", "plotter_pass_01.nc", "plotter_pass_02.nc"}

BANNED_NAME_PARTS = (
    "_audit",
    "_prepared",
    "_new_algorithm",
    "_ready_to_plot",
    "contact",
    "summary",
    "report",
)
BANNED_SUFFIXES = {".gcode", ".png", ".svg", ".json", ".csv", ".txt"}
BANNED_DIR_NAMES = {"logs", "pages", "_candidates", "_generated_pdf", "_new_algorithm_source", "_audit"}


@dataclass(frozen=True)
class Problem:
    package: Path
    message: str


def _is_banned_file(path: Path) -> bool:
    name = path.name.casefold()
    if any(part in name for part in BANNED_NAME_PARTS):
        return True
    return path.suffix.casefold() in BANNED_SUFFIXES


def _expected_files(files: set[str]) -> set[str] | None:
    if "plotter.nc" in files:
        return SINGLE_PAGE_FILES
    if "plotter_pass_01.nc" in files or "plotter_pass_02.nc" in files:
        return TWO_PASS_FILES
    return None


def validate_package(package: Path) -> list[Problem]:
    problems: list[Problem] = []
    files = {path.name for path in package.iterdir() if path.is_file()}
    dirs = {path.name for path in package.iterdir() if path.is_dir()}

    expected = _expected_files(files)
    if expected is None:
        problems.append(Problem(package, "missing plotter output: expected plotter.nc or plotter_pass_01.nc + plotter_pass_02.nc"))
        expected = {"source.pdf", "plot_preview.pdf"}

    missing = sorted(expected - files)
    for name in missing:
        problems.append(Problem(package, f"missing required file: {name}"))

    for pdf_name in ("source.pdf", "plot_preview.pdf"):
        pdf_path = package / pdf_name
        if pdf_path.exists():
            try:
                with fitz.open(pdf_path) as doc:
                    if doc.page_count < 1:
                        problems.append(Problem(package, f"empty PDF: {pdf_name}"))
            except Exception as exc:
                problems.append(Problem(package, f"cannot open PDF {pdf_name}: {exc}"))

    for nc_name in sorted(name for name in expected if name.endswith(".nc")):
        nc_path = package / nc_name
        if not nc_path.exists():
            continue
        try:
            text = nc_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            problems.append(Problem(package, f"cannot read NC {nc_name}: {exc}"))
            continue
        if not text.strip():
            problems.append(Problem(package, f"empty NC: {nc_name}"))
        if "G0" not in text and "G1" not in text:
            problems.append(Problem(package, f"NC has no motion commands: {nc_name}"))

    extra = sorted(files - expected)
    for name in extra:
        problems.append(Problem(package, f"unexpected top-level file: {name}"))

    for path in sorted(package.iterdir(), key=lambda p: p.name.casefold()):
        if path.is_file() and _is_banned_file(path):
            problems.append(Problem(package, f"debug/legacy file leaked into package: {path.name}"))

    for dirname in sorted(dirs, key=str.casefold):
        if dirname.casefold() in BANNED_DIR_NAMES:
            problems.append(Problem(package, f"debug/legacy directory leaked into package: {dirname}"))
        else:
            problems.append(Problem(package, f"unexpected top-level directory: {dirname}"))

    has_single = "plotter.nc" in files
    has_split = "plotter_pass_01.nc" in files or "plotter_pass_02.nc" in files
    if has_single and has_split:
        problems.append(Problem(package, "mixed single-page and two-pass plotter outputs"))

    return problems


def iter_packages(roots: list[Path]) -> list[Path]:
    packages: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        packages.extend(path for path in root.rglob("*_pack") if path.is_dir())
    return sorted(packages, key=lambda p: str(p).casefold())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate clean plotter package folders.")
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="Root folder to scan. Can be repeated. Defaults to Computer Graphics and Nachert roots.",
    )
    args = parser.parse_args(argv)

    roots = [Path(item).resolve() for item in args.root] if args.root else [path.resolve() for path in DEFAULT_ROOTS]
    packages = iter_packages(roots)
    problems: list[Problem] = []
    for package in packages:
        problems.extend(validate_package(package))

    if problems:
        print(f"clean package validation failed: packages={len(packages)} problems={len(problems)}")
        for problem in problems:
            print(f"{problem.package}: {problem.message}")
        return 1

    print(f"clean package validation ok: packages={len(packages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
