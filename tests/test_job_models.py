from pathlib import Path

from src.plotter_backend.jobs.models import JobResult, JobSettings


def test_job_settings_defaults_and_output_dir(tmp_path):
    s = JobSettings(input_path=tmp_path / "in.svg")
    assert s.tool == "pen"
    assert s.normalized_output_dir() == tmp_path


def test_job_result_to_dict_stringifies_paths(tmp_path):
    r = JobResult(True, "ok", output_dir=tmp_path, gcode_path=Path("a.gcode"))
    d = r.to_dict()
    assert d["ok"] is True
    assert d["gcode_path"] == "a.gcode"
