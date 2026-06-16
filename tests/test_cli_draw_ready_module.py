from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from src import plotter_pdf_drawer as backend


def _write_ready_variant(root: Path) -> Path:
    variant = root / "22 вариант"
    package = variant / "КНГ.01.20.01 - Маховик_pack"
    package.mkdir(parents=True)
    (package / "page_01.nc").write_text("G0 X0 Y-10\nG1 X1 Y-11\n", encoding="utf-8")
    (package / "summary.csv").write_text(
        "ok,item,nc,draw_length_m,bounds,preview_pdf,preview_svg,gcode\n"
        "True,page_01,page_01.nc,1.23,\"x(0,1) y(-11,-10)\",page_01.pdf,page_01.svg,page_01.gcode\n",
        encoding="utf-8",
    )
    (variant / "_audit.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "kind": "a4",
                        "task": "КНГ.01.20.01 - Маховик_pack",
                        "package_dir": str(package),
                        "layout_similarity": 0.99,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (variant / "_ready_to_plot_audit.json").write_text(
        json.dumps({"ok": True, "failed_packages": []}),
        encoding="utf-8",
    )
    return variant


def _write_ready_a3_variant(root: Path) -> Path:
    variant = root / "22 вариант"
    package = variant / "МЧ00.60.00.00 СБ Вентиль_pack"
    package.mkdir(parents=True)
    (package / "pass_01.nc").write_text("G0 X0 Y-10\nG1 X1 Y-11\n", encoding="utf-8")
    (package / "pass_02.nc").write_text("G0 X2 Y-12\nG1 X3 Y-13\n", encoding="utf-8")
    (package / "summary.csv").write_text(
        "ok,item,nc,draw_length_m,bounds,preview_pdf,preview_svg,gcode\n"
        "True,pass_01,pass_01.nc,6.7,\"x(0,1) y(-11,-10)\",pass_01.pdf,pass_01.svg,pass_01.gcode\n"
        "True,pass_02,pass_02.nc,6.9,\"x(2,3) y(-13,-12)\",pass_02.pdf,pass_02.svg,pass_02.gcode\n",
        encoding="utf-8",
    )
    (variant / "_audit.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "kind": "a3_two_pass",
                        "task": package.name,
                        "package_dir": str(package),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (variant / "_ready_to_plot_audit.json").write_text(
        json.dumps({"ok": True, "failed_packages": []}),
        encoding="utf-8",
    )
    return variant


def _write_bad_ready_variant(root: Path) -> Path:
    variant = _write_ready_variant(root)
    package = next(variant.glob("*_pack"))
    (package / "page_01.nc").write_text("G90\nG92 X0 Y0\nG1 X10 Y-10\n", encoding="utf-8")
    return variant


def test_main_draw_ready_dry_run_selects_package_without_sender(tmp_path: Path) -> None:
    variant = _write_ready_variant(tmp_path)
    with (
        mock.patch.object(backend, "load_pencil_profile", return_value={}),
        mock.patch.object(backend, "apply_pencil_profile"),
        mock.patch.object(backend, "configure_active_work_area"),
        mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(210.0, 297.0)),
        mock.patch.object(backend, "detect_com_port", return_value="COM6"),
        mock.patch.object(backend, "apply_quality_profile"),
        mock.patch.object(backend, "quality_state", return_value="mock-profile"),
        mock.patch.object(backend, "send_to_grbl") as send_to_grbl,
        mock.patch("builtins.print"),
    ):
        rc = backend.main(["--draw-ready", str(variant), "--kind", "a4", "--dry-run", "--com", "COM6"])

    assert rc == 0
    send_to_grbl.assert_not_called()


def test_main_draw_ready_dry_run_allows_z_only_g92_header(tmp_path: Path) -> None:
    variant = _write_ready_variant(tmp_path)
    package = next(variant.glob("*_pack"))
    (package / "page_01.nc").write_text("G90\nG92 Z4.0\nG0 Z0.0\nG92 Z0.0\nG1 X10 Y-10\n", encoding="utf-8")
    with (
        mock.patch.object(backend, "load_pencil_profile", return_value={}),
        mock.patch.object(backend, "apply_pencil_profile"),
        mock.patch.object(backend, "configure_active_work_area"),
        mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(210.0, 297.0)),
        mock.patch.object(backend, "detect_com_port", return_value="COM6"),
        mock.patch.object(backend, "apply_quality_profile"),
        mock.patch.object(backend, "quality_state", return_value="mock-profile"),
        mock.patch.object(backend, "send_to_grbl") as send_to_grbl,
        mock.patch("builtins.print"),
    ):
        rc = backend.main(["--draw-ready", str(variant), "--kind", "a4", "--dry-run", "--com", "COM6"])

    assert rc == 0
    send_to_grbl.assert_not_called()


def test_main_draw_ready_dry_run_rejects_failed_preflight(tmp_path: Path) -> None:
    variant = _write_bad_ready_variant(tmp_path)
    with (
        mock.patch.object(backend, "load_pencil_profile", return_value={}),
        mock.patch.object(backend, "apply_pencil_profile"),
        mock.patch.object(backend, "configure_active_work_area"),
        mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(210.0, 297.0)),
        mock.patch.object(backend, "detect_com_port", return_value="COM6"),
        mock.patch.object(backend, "apply_quality_profile"),
        mock.patch.object(backend, "quality_state", return_value="mock-profile"),
        mock.patch.object(backend, "send_to_grbl") as send_to_grbl,
        mock.patch("builtins.print"),
    ):
        rc = backend.main(["--draw-ready", str(variant), "--kind", "a4", "--dry-run", "--com", "COM6"])

    assert rc == 1
    send_to_grbl.assert_not_called()


def test_main_draw_ready_sends_selected_nc(tmp_path: Path) -> None:
    variant = _write_ready_variant(tmp_path)
    with (
        mock.patch.object(backend, "load_pencil_profile", return_value={}),
        mock.patch.object(backend, "apply_pencil_profile"),
        mock.patch.object(backend, "configure_active_work_area"),
        mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(210.0, 297.0)),
        mock.patch.object(backend, "detect_com_port", return_value="COM6"),
        mock.patch.object(backend, "apply_quality_profile"),
        mock.patch.object(backend, "quality_state", return_value="mock-profile"),
        mock.patch.object(backend, "send_to_grbl", return_value=12.0) as send_to_grbl,
        mock.patch.object(backend, "format_duration_hms", return_value="00:12"),
        mock.patch("builtins.print"),
    ):
        rc = backend.main(["--draw-ready", str(variant), "--kind", "a4", "--com", "COM6", "--no-ready-sleep"])

    assert rc == 0
    assert send_to_grbl.call_args.args[0] == variant / "КНГ.01.20.01 - Маховик_pack" / "page_01.nc"
    assert send_to_grbl.call_args.kwargs["sleep_after"] is False


def test_main_draw_ready_rejects_failed_preflight_before_sender(tmp_path: Path) -> None:
    variant = _write_bad_ready_variant(tmp_path)
    with (
        mock.patch.object(backend, "load_pencil_profile", return_value={}),
        mock.patch.object(backend, "apply_pencil_profile"),
        mock.patch.object(backend, "configure_active_work_area"),
        mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(210.0, 297.0)),
        mock.patch.object(backend, "detect_com_port", return_value="COM6"),
        mock.patch.object(backend, "apply_quality_profile"),
        mock.patch.object(backend, "quality_state", return_value="mock-profile"),
        mock.patch.object(backend, "send_to_grbl") as send_to_grbl,
        mock.patch("builtins.print"),
    ):
        rc = backend.main(["--draw-ready", str(variant), "--kind", "a4", "--com", "COM6"])

    assert rc == 1
    send_to_grbl.assert_not_called()


def test_main_draw_ready_sends_requested_a3_pass_item(tmp_path: Path) -> None:
    variant = _write_ready_a3_variant(tmp_path)
    with (
        mock.patch.object(backend, "load_pencil_profile", return_value={}),
        mock.patch.object(backend, "apply_pencil_profile"),
        mock.patch.object(backend, "configure_active_work_area"),
        mock.patch.object(backend, "resolve_sheet_size_mm", return_value=(420.0, 297.0)),
        mock.patch.object(backend, "detect_com_port", return_value="COM6"),
        mock.patch.object(backend, "apply_quality_profile"),
        mock.patch.object(backend, "quality_state", return_value="mock-profile"),
        mock.patch.object(backend, "send_to_grbl", return_value=12.0) as send_to_grbl,
        mock.patch.object(backend, "format_duration_hms", return_value="00:12"),
        mock.patch("builtins.print"),
    ):
        rc = backend.main(
            ["--draw-ready", str(variant), "--kind", "a3", "--item", "pass_02", "--com", "COM6", "--no-ready-sleep"]
        )

    assert rc == 0
    assert send_to_grbl.call_args.args[0] == variant / "МЧ00.60.00.00 СБ Вентиль_pack" / "pass_02.nc"
