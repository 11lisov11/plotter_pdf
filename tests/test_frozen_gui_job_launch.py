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
