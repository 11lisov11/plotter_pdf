from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import prepare_plotter_package as mod


def _parse(argv: list[str]):
    parser = mod.build_parser()
    return parser.parse_known_args(argv)


def test_mode_aliases_are_canonical() -> None:
    assert mod.normalize_mode("1") == "geometry"
    assert mod.normalize_mode("начерт") == "geometry"
    assert mod.normalize_mode("2") == "graphics"
    assert mod.normalize_mode("компьютерная графика") == "graphics"
    assert mod.normalize_mode("3") == "copy"
    assert mod.normalize_mode("полная копия") == "copy"
    assert mod.normalize_mode("4") == "photo"
    assert mod.normalize_mode("фото") == "photo"


def test_a2_sheet_alias_is_available_without_changing_legacy_modes() -> None:
    assert mod.normalize_sheet("a2") == "a2"
    assert mod.normalize_sheet("А2") == "a2"


def test_graphics_plan_uses_computer_graphics_engine() -> None:
    args, extra = _parse(["--mode", "graphics", "--sheet", "a4", "--variant", "9 вариант", "--plan-only"])
    plan = mod.build_plan(args, extra)

    assert plan.mode == "graphics"
    assert plan.sheet == "a4"
    assert "prepare_computer_graphics_variants.py" in plan.command[1]
    assert "--variants" in plan.command
    assert "9 вариант" in plan.command


def test_geometry_plan_uses_nachert_engine_with_task_filter() -> None:
    args, extra = _parse(["--mode", "geometry", "--sheet", "a3", "--variant", "26", "--task", "7"])
    plan = mod.build_plan(args, extra)

    assert plan.mode == "geometry"
    assert plan.sheet == "a3"
    assert "prepare_nachert_packages.py" in plan.command[1]
    assert "--only-variant" in plan.command
    assert "--only-task" in plan.command


def test_copy_plan_is_preview_only_and_uses_sheet_format(tmp_path: Path) -> None:
    source = tmp_path / "drawing.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    out_dir = tmp_path / "out"
    args, extra = _parse(["--mode", "copy", "--sheet", "a4", "--out-dir", str(out_dir), str(source)])
    plan = mod.build_plan(args, extra)

    assert plan.mode == "copy"
    assert "--preview" in plan.command
    assert "--sheet-format" in plan.command
    assert "a4" in plan.command
    assert "--force-text-to-path" in plan.command
    assert "--no-simplify" in plan.command


def test_photo_plan_uses_quality_and_render_flags(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"stub")
    args, extra = _parse(
        ["--mode", "photo", "--sheet", "a4", "--photo-render", "classic", "--photo-quality", "detailed", str(source)]
    )
    plan = mod.build_plan(args, extra)

    assert plan.mode == "photo"
    assert "prepare_photo_plot_package.py" in plan.command[1]
    assert "--mode" in plan.command
    assert "classic" in plan.command
    assert "--photo-quality" in plan.command
    assert "detailed" in plan.command


def test_photo_a2_plan_uses_safe_a2_work_area(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"stub")
    args, extra = _parse(["--mode", "photo", "--sheet", "a2", str(source)])
    plan = mod.build_plan(args, extra)

    assert plan.sheet == "a2"
    width_index = plan.command.index("--target-width-mm")
    height_index = plan.command.index("--target-height-mm")
    assert plan.command[width_index + 1] == "380"
    assert plan.command[height_index + 1] == "570"
