from __future__ import annotations

from plotter_app.viewmodels import JobViewModel
from src.plotter_backend.jobs import JobSettings


def test_draw_enabled_after_input_com_and_preflight(tmp_path) -> None:
    input_file = tmp_path / "sample.pdf"
    input_file.write_bytes(b"%PDF-1.4\n")
    vm = JobViewModel(JobSettings(input_path=input_file, output_dir=tmp_path))
    assert vm.can_draw() is False
    vm.set_com("COM9")
    assert vm.can_draw() is False
    vm.preflight_ok = True
    assert vm.can_draw() is True
