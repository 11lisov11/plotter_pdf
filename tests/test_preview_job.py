from __future__ import annotations

import importlib
from pathlib import Path

from src.plotter_backend.jobs.models import JobResult, JobSettings

preview_mod = importlib.import_module("src.plotter_backend.jobs.preview_job")


def test_preview_job_writes_and_reports_visual_svg(tmp_path, monkeypatch) -> None:
    nc_path = tmp_path / "sample.nc"
    nc_path.write_text(
        "\n".join(
            [
                "G21",
                "G90",
                "G0 Z0",
                "G0 X0 Y0",
                "G1 Z11.9",
                "G1 X10 Y0",
                "G0 Z0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_prepare(_settings: JobSettings) -> JobResult:
        return JobResult(True, "ok", output_dir=tmp_path, nc_path=nc_path)

    monkeypatch.setattr(preview_mod, "prepare_gcode_job", fake_prepare)
    monkeypatch.setattr(preview_mod, "_open_preview", lambda _path: None)

    result = preview_mod.preview_job(JobSettings(input_path=Path("drawing.svg"), output_dir=tmp_path))

    assert result.ok is True
    assert result.preview_svg_path == nc_path.with_suffix(".preview.svg")
    assert result.preview_svg_path is not None
    assert result.preview_svg_path.exists()
    assert "Предпросмотр открыт" in result.message
    assert "<svg" in result.preview_svg_path.read_text(encoding="utf-8")
