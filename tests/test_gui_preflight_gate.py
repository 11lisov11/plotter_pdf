from src.plotter_backend.jobs.models import JobSettings
from plotter_app.viewmodels.job_viewmodel import JobViewModel


def test_draw_gate_requires_input_com_preflight_confirmation():
    vm = JobViewModel(JobSettings(input_path="in.svg", com=""))
    vm.preflight_ok = True
    vm.hardware_confirmed = True
    assert not vm.can_draw()
    vm.update_settings(com="COM6")
    vm.preflight_ok = True
    assert vm.hardware_confirmed is True
    assert vm.can_draw()
    vm.preflight_ok = False
    assert not vm.can_draw()
