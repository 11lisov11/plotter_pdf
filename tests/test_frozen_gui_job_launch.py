from __future__ import annotations

import subprocess
import importlib
from pathlib import Path
from unittest import mock

from src.plotter_backend.jobs.models import JobSettings

draw_job = importlib.import_module("src.plotter_backend.jobs.draw_job")
prepare_job = importlib.import_module("src.plotter_backend.jobs.prepare_job")


def test_prepare_job_uses_cli_exe_when_frozen(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    gui_exe = bundle / "PlotterPDF_GUI.exe"
    cli_exe = bundle / "plotter-pdf.exe"
    input_file = bundle / "simple_square.svg"
    gui_exe.write_text("", encoding="utf-8")
    cli_exe.write_text("", encoding="utf-8")
    input_file.write_text("<svg/>", encoding="utf-8")
    captured: dict[str, list[str]] = {}

    def _run(cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 2, stdout="forced failure")

    settings = JobSettings(input_path=input_file, output_dir=tmp_path / "out")
    with (
        mock.patch.object(prepare_job.sys, "frozen", True, create=True),
        mock.patch.object(prepare_job.sys, "executable", str(gui_exe)),
        mock.patch.object(prepare_job.subprocess, "run", side_effect=_run),
    ):
        result = prepare_job.prepare_gcode_job(settings)

    assert not result.ok
    assert captured["cmd"][0] == str(cli_exe)
    assert "main.py" not in captured["cmd"]
    assert "--skip-calibration" in captured["cmd"]


def test_draw_job_uses_cli_exe_when_frozen(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    gui_exe = bundle / "PlotterPDF_GUI.exe"
    cli_exe = bundle / "plotter-pdf.exe"
    input_file = bundle / "simple_square.svg"
    gui_exe.write_text("", encoding="utf-8")
    cli_exe.write_text("", encoding="utf-8")
    input_file.write_text("<svg/>", encoding="utf-8")
    captured: dict[str, list[str]] = {}

    def _run(cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 2, stdout="forced failure")

    settings = JobSettings(input_path=input_file, output_dir=tmp_path / "out", com="COM99", dry_run=False)
    with (
        mock.patch.object(prepare_job.sys, "frozen", True, create=True),
        mock.patch.object(prepare_job.sys, "executable", str(gui_exe)),
        mock.patch.object(draw_job.subprocess, "run", side_effect=_run),
    ):
        result = draw_job.draw_job(settings, confirm_hardware=True)

    assert not result.ok
    assert captured["cmd"][0] == str(cli_exe)
    assert "main.py" not in captured["cmd"]


def test_prepare_job_rejects_success_without_nc_output(tmp_path: Path) -> None:
    input_file = tmp_path / "simple_square.svg"
    input_file.write_text("<svg/>", encoding="utf-8")
    settings = JobSettings(input_path=input_file, output_dir=tmp_path / "out")
    completed = subprocess.CompletedProcess(["plotter-pdf"], 0, stdout="ok")

    with mock.patch.object(prepare_job.subprocess, "run", return_value=completed):
        result = prepare_job.prepare_gcode_job(settings)

    assert not result.ok
    assert result.errors == ["missing_or_empty_nc_output"]


def test_prepare_job_removes_stale_nc_before_generation(tmp_path: Path) -> None:
    input_file = tmp_path / "simple_square.svg"
    input_file.write_text("<svg/>", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    stale = output_dir / "simple_square_prepared.nc"
    stale.write_text("OLD DRAWING", encoding="utf-8")
    settings = JobSettings(input_path=input_file, output_dir=output_dir)
    completed = subprocess.CompletedProcess(["plotter-pdf"], 0, stdout="ok")

    with mock.patch.object(prepare_job.subprocess, "run", return_value=completed):
        result = prepare_job.prepare_gcode_job(settings)

    assert not result.ok
    assert not stale.exists()


def test_draw_job_uses_built_layout_page_for_multiple_inputs(tmp_path: Path) -> None:
    layout_page = tmp_path / "layout_page.pdf"
    layout_page.write_bytes(b"%PDF-1.4\n")
    captured: dict[str, list[str]] = {}

    def _run(cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        output_index = cmd.index("--output") + 1
        Path(cmd[output_index]).write_text("G21\nG90\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok")

    settings = JobSettings(
        input_paths=[str(tmp_path / "first.pdf"), str(tmp_path / "second.pdf")],
        output_dir=tmp_path / "out",
        com="COM99",
        dry_run=False,
    )
    with (
        mock.patch.object(draw_job, "_resolve_input", return_value=(layout_page, None)),
        mock.patch.object(draw_job.subprocess, "run", side_effect=_run),
    ):
        result = draw_job.draw_job(settings, confirm_hardware=True)

    assert result.ok
    assert str(layout_page) in captured["cmd"]


def test_draw_job_rejects_success_without_nc_output(tmp_path: Path) -> None:
    input_file = tmp_path / "simple_square.svg"
    input_file.write_text("<svg/>", encoding="utf-8")
    settings = JobSettings(
        input_path=input_file,
        output_dir=tmp_path / "out",
        com="COM99",
        dry_run=False,
    )
    completed = subprocess.CompletedProcess(["plotter-pdf"], 0, stdout="ok")

    with mock.patch.object(draw_job.subprocess, "run", return_value=completed):
        result = draw_job.draw_job(settings, confirm_hardware=True)

    assert not result.ok
    assert result.errors == ["missing_or_empty_nc_output"]
