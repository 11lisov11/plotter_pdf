from __future__ import annotations

from pathlib import Path

from plotter_app.viewmodels import JobViewModel
from src.plotter_backend.jobs import JobSettings


def test_job_viewmodel_can_preview_existing_input(tmp_path) -> None:
    input_file = tmp_path / "sample.pdf"
    input_file.write_bytes(b"%PDF-1.4\n")
    vm = JobViewModel(JobSettings(input_path=input_file, output_dir=tmp_path))
    assert vm.can_preview() is True
    vm.set_input_path(Path("missing.pdf"))
    assert vm.can_preview() is False


def test_job_viewmodel_accepts_multiple_layout_items(tmp_path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"%PDF-1.4\n")
    second.write_bytes(b"%PDF-1.4\n")
    vm = JobViewModel(JobSettings(output_dir=tmp_path))

    vm.set_layout_items([(first, 0, 90), (second, 1, 180)])

    assert vm.can_preview() is True
    assert vm.settings.input_paths == [str(first), str(second)]
    assert vm.settings.input_pages == [0, 1]
    assert vm.settings.input_rotations == [90, 180]


def test_job_viewmodel_blocks_draw_without_current_preflight(tmp_path) -> None:
    input_file = tmp_path / "sample.pdf"
    input_file.write_bytes(b"%PDF-1.4\n")
    vm = JobViewModel(JobSettings(input_path=input_file, output_dir=tmp_path, com="COM99", dry_run=False))
    vm.set_hardware_confirmed(True)

    result = vm.draw()

    assert result.ok is False
    assert result.errors == ["preflight_required"]


def test_generation_signature_changes_with_output_geometry_settings(tmp_path) -> None:
    input_file = tmp_path / "sample.pdf"
    input_file.write_bytes(b"%PDF-1.4\n")
    vm = JobViewModel(JobSettings(input_path=input_file, output_dir=tmp_path))
    original = vm.generation_signature()

    vm.settings.output_rotation_deg = 90

    assert vm.generation_signature() != original
