from __future__ import annotations

from pathlib import Path

from src.plotter_backend.jobs import JobResult, JobSettings


def test_job_settings_normalizes_paths() -> None:
    settings = JobSettings(input_path="input.pdf", output_dir="out")
    assert settings.normalized_input_path() == Path("input.pdf")
    assert settings.normalized_output_dir() == Path("out")


def test_job_result_to_dict_serializes_paths() -> None:
    result = JobResult(True, "ok", gcode_path=Path("a.gcode"), line_count=3)
    data = result.to_dict()
    assert data["ok"] is True
    assert data["gcode_path"] == "a.gcode"
    assert data["line_count"] == 3
