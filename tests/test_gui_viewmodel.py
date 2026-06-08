from src.plotter_backend.jobs.models import JobResult, JobSettings
from plotter_app.viewmodels.job_viewmodel import JobViewModel


def test_viewmodel_preview_sets_preflight_ok(tmp_path):
    vm = JobViewModel(JobSettings(input_path=tmp_path / "in.svg"))
    result = vm.run_preview(lambda settings, logger: JobResult(True, "ok", gcode_path=tmp_path / "out.nc"))
    assert result.ok
    assert vm.preflight_ok
