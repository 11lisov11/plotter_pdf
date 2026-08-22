from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


MODE_ALIASES = {
    "1": "geometry",
    "geometry": "geometry",
    "descriptive": "geometry",
    "descriptive_geometry": "geometry",
    "nachert": "geometry",
    "начерт": "geometry",
    "начертательная": "geometry",
    "начертательная_геометрия": "geometry",
    "2": "graphics",
    "graphics": "graphics",
    "computer": "graphics",
    "computer_graphics": "graphics",
    "cg": "graphics",
    "компьютерная": "graphics",
    "компьютерная_графика": "graphics",
    "3": "copy",
    "copy": "copy",
    "full": "copy",
    "full_copy": "copy",
    "pdf_copy": "copy",
    "копия": "copy",
    "полная_копия": "copy",
    "4": "photo",
    "photo": "photo",
    "фото": "photo",
}


SHEET_ALIASES = {
    "auto": "auto",
    "a4": "a4",
    "а4": "a4",
    "4": "a4",
    "a3": "a3",
    "а3": "a3",
    "3": "a3",
    "a2": "a2",
    "а2": "a2",
    "2": "a2",
}


@dataclass(frozen=True)
class CommandPlan:
    mode: str
    sheet: str
    command: list[str]
    note: str


def _normalize_token(value: str) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def normalize_mode(value: str) -> str:
    key = _normalize_token(value)
    try:
        return MODE_ALIASES[key]
    except KeyError as exc:
        allowed = "geometry|graphics|copy|photo"
        raise ValueError(f"unknown mode: {value!r}; expected {allowed}") from exc


def normalize_sheet(value: str) -> str:
    key = _normalize_token(value or "auto")
    try:
        return SHEET_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"unknown sheet: {value!r}; expected auto|a4|a3|a2") from exc


def _project_path(value: str | None, default: Path) -> Path:
    if value is None or not str(value).strip():
        return default
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _input_path(value: str | None, mode: str) -> Path:
    if not value:
        raise ValueError(f"mode {mode!r} requires an input file path")
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _script(name: str) -> Path:
    return PROJECT_ROOT / "scripts" / name


def _build_geometry_command(args: argparse.Namespace, sheet: str, passthrough: list[str]) -> CommandPlan:
    root = _project_path(args.root, PROJECT_ROOT / "Начерт")
    cmd = [PYTHON, str(_script("prepare_nachert_packages.py")), "--root", str(root)]
    for variant in args.variant:
        cmd.extend(["--only-variant", str(variant)])
    for task in args.task:
        cmd.extend(["--only-task", str(int(task))])
    if args.keep_debug_artifacts:
        cmd.append("--keep-debug-artifacts")
    cmd.extend(passthrough)
    note = "Начертательная геометрия: профиль рамок/миниатюр/штампов для Начерт."
    if sheet != "auto":
        note += f" Запрошен лист {sheet.upper()}; нижний пайплайн всё равно сверяет фактический размер PDF."
    return CommandPlan(mode="geometry", sheet=sheet, command=cmd, note=note)


def _build_graphics_command(args: argparse.Namespace, sheet: str, passthrough: list[str]) -> CommandPlan:
    root = _project_path(args.root, PROJECT_ROOT / "Компьютерная графика")
    cmd = [PYTHON, str(_script("prepare_computer_graphics_variants.py")), "--root", str(root)]
    if args.variant:
        cmd.append("--variants")
        cmd.extend(str(variant) for variant in args.variant)
    if args.keep_debug_artifacts:
        cmd.append("--keep-debug-artifacts")
    if args.machine_profile:
        cmd.extend(["--machine-profile", str(args.machine_profile)])
    cmd.extend(passthrough)
    note = "Компьютерная графика: профиль KOMPAS/GOST-штампов и новых LFF-букв."
    if sheet != "auto":
        note += f" Запрошен лист {sheet.upper()}; нижний пайплайн всё равно сверяет фактический размер PDF."
    return CommandPlan(mode="graphics", sheet=sheet, command=cmd, note=note)


def _copy_output_path(args: argparse.Namespace, source: Path, sheet: str) -> Path:
    if args.output:
        path = Path(args.output)
        return path if path.is_absolute() else PROJECT_ROOT / path
    out_dir = _project_path(args.out_dir, PROJECT_ROOT / "_plotter_jobs" / f"{source.stem}_full_copy_{sheet}_pack")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{source.stem}_full_copy_{sheet}.nc"


def _build_copy_command(args: argparse.Namespace, sheet: str, passthrough: list[str]) -> CommandPlan:
    source = _input_path(args.input, "copy")
    backend_sheet = "work" if sheet == "auto" else sheet
    output = _copy_output_path(args, source, sheet)
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "src" / "plotter_pdf_drawer.py"),
        str(source),
        "--preview",
        "--output",
        str(output),
        "--sheet-format",
        backend_sheet,
        "--force-text-to-path",
        "--quality",
        "high",
        "--draw-order",
        "source",
        "--safe-travel-up",
    ]
    if args.full_copy_no_simplify:
        cmd.extend(["--no-simplify", "--no-rdp", "--no-arcs"])
    cmd.extend(passthrough)
    note = (
        "Полная копия PDF: без CG/Начерт-правил рамок, текст уходит в контуры, "
        "COM не трогается, формируется preview/NC."
    )
    return CommandPlan(mode="copy", sheet=sheet, command=cmd, note=note)


def _build_photo_command(args: argparse.Namespace, sheet: str, passthrough: list[str]) -> CommandPlan:
    source = _input_path(args.input, "photo")
    cmd = [
        PYTHON,
        str(_script("prepare_photo_plot_package.py")),
        str(source),
        "--mode",
        str(args.photo_render),
        "--photo-quality",
        str(args.photo_quality),
    ]
    if args.out_dir:
        cmd.extend(["--out-dir", str(_project_path(args.out_dir, PROJECT_ROOT / "_plotter_jobs"))])
    if sheet == "a4":
        cmd.extend(["--target-width-mm", "170", "--target-height-mm", "270"])
    elif sheet == "a3":
        cmd.extend(["--target-width-mm", "170", "--target-height-mm", "270"])
    elif sheet == "a2":
        cmd.extend(["--target-width-mm", "380", "--target-height-mm", "570"])
    cmd.extend(passthrough)
    note = "Фото: отдельный фото-пайплайн; детализация задаётся --photo-quality fast|normal|detailed."
    if sheet == "a3":
        note += " A3 сейчас готовится как одиночная рабочая область плоттера; двухпроходную A3-нарезку фото нужно делать отдельным следующим шагом."
    return CommandPlan(mode="photo", sheet=sheet, command=cmd, note=note)


def build_plan(args: argparse.Namespace, passthrough: list[str] | None = None) -> CommandPlan:
    passthrough = list(passthrough or [])
    mode = normalize_mode(args.mode)
    sheet = normalize_sheet(args.sheet)
    if mode == "geometry":
        return _build_geometry_command(args, sheet, passthrough)
    if mode == "graphics":
        return _build_graphics_command(args, sheet, passthrough)
    if mode == "copy":
        return _build_copy_command(args, sheet, passthrough)
    if mode == "photo":
        return _build_photo_command(args, sheet, passthrough)
    raise AssertionError(f"unhandled mode: {mode}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Canonical plotter package entry point. Modes: 1 geometry, "
            "2 graphics, 3 full PDF copy, 4 photo."
        )
    )
    parser.add_argument("input", nargs="?", help="Input PDF/image for copy/photo modes.")
    parser.add_argument("--mode", required=True, help="geometry|graphics|copy|photo, or 1|2|3|4.")
    parser.add_argument("--sheet", default="auto", help="auto|a4|a3|a2. Common format flag for all four modes.")
    parser.add_argument("--root", default=None, help="Root folder for geometry/graphics modes.")
    parser.add_argument("--machine-profile", default="a4_desktop", help="Target machine profile for graphics mode.")
    parser.add_argument("--variant", action="append", default=[], help="Variant filter. Can be used multiple times.")
    parser.add_argument("--task", type=int, action="append", default=[], help="Task number filter for geometry mode.")
    parser.add_argument("--out-dir", default=None, help="Output folder for copy/photo modes.")
    parser.add_argument("--output", default=None, help="Explicit output NC path for copy mode.")
    parser.add_argument(
        "--photo-render",
        choices=["classic", "hatch", "scribble", "portrait", "sketch"],
        default="sketch",
        help="Photo drawing algorithm used only with --mode photo.",
    )
    parser.add_argument(
        "--photo-quality",
        choices=["fast", "normal", "detailed"],
        default="normal",
        help="Photo quality preset used only with --mode photo.",
    )
    parser.add_argument(
        "--full-copy-no-simplify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Disable simplification/arcs in full-copy mode for the most literal PDF path output.",
    )
    parser.add_argument("--keep-debug-artifacts", action="store_true", help="Keep internal reports/logs/candidates.")
    parser.add_argument("--plan-only", action="store_true", help="Print resolved mode command without running it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args, passthrough = parser.parse_known_args(argv)
    try:
        plan = build_plan(args, passthrough)
    except ValueError as exc:
        parser.error(str(exc))
    if args.plan_only:
        print(
            json.dumps(
                {
                    "mode": plan.mode,
                    "sheet": plan.sheet,
                    "note": plan.note,
                    "command": plan.command,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(plan.note)
    print("running:", " ".join(f'"{part}"' if " " in str(part) else str(part) for part in plan.command))
    completed = subprocess.run(plan.command, cwd=PROJECT_ROOT)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
