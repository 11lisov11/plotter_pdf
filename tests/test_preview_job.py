from __future__ import annotations

import importlib
from pathlib import Path

from src.plotter_backend.jobs.models import JobResult, JobSettings

preview_mod = importlib.import_module("src.plotter_backend.jobs.preview_job")


def test_preview_job_writes_svg_html_and_pdf_from_final_gcode(tmp_path, monkeypatch) -> None:
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
    assert result.preview_svg_path.exists()
    assert result.preview_pdf_path == nc_path.with_suffix(".preview.pdf")
    assert result.preview_pdf_path.exists()
    assert "Предпросмотр итогового G-code готов" in result.message
    assert "<svg" in result.preview_svg_path.read_text(encoding="utf-8")
    html_path = nc_path.with_suffix(".preview.html")
    assert html_path.exists()
    assert "drawing.svg" in html_path.read_text(encoding="utf-8")
    with preview_mod.fitz.open(result.preview_pdf_path) as preview_doc:
        assert preview_doc.page_count == 1
        assert preview_doc[0].rect.width < 2000
        assert preview_doc[0].rect.height < 2000


def test_g91_1_arc_mode_does_not_enable_relative_coordinates() -> None:
    polylines = preview_mod._gcode_to_polylines(
        [
            "G90",
            "G91.1",
            "G0 X10 Y20",
            "G1 Z1",
            "G1 X15 Y25",
            "G1 X20 Y30",
            "G1 Z0",
        ],
        z_up=0.0,
        z_down=1.0,
    )

    assert polylines == [[(10.0, 20.0), (15.0, 25.0), (20.0, 30.0)]]


def test_a2_profile_uses_negative_pen_down_value() -> None:
    z_up, z_down = preview_mod._detect_pen_z(
        ["G1 Z0", "G1 Z-4"],
        JobSettings(machine_profile="a2_corexy"),
    )

    assert z_up == 0.0
    assert z_down == -4.0


def test_old_plotter_preview_applies_physical_y_orientation() -> None:
    settings = JobSettings(machine_profile="a4_desktop", sheet_format="a4")
    transformed = preview_mod._paper_orientation_polylines(
        [[(10.0, -280.0), (20.0, -10.0)]],
        settings,
    )

    assert transformed == [[(10.0, -10.0), (20.0, -280.0)]]
