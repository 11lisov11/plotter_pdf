from __future__ import annotations

import pytest

from src import plotter_pdf_drawer as backend
from src.plotter_backend import cli_entry


def test_output_orientation_rotates_180_without_changing_bounds() -> None:
    original = (
        backend.OUTPUT_ROTATION_DEG,
        backend.OUTPUT_MIRROR_X,
        backend.OUTPUT_MIRROR_Y,
        backend.MACHINE_SOURCE_MIRROR_X,
        backend.MACHINE_SOURCE_MIRROR_Y,
    )
    original_bounds = backend.ACTIVE_WORK_AREA_BOUNDS
    try:
        backend.ACTIVE_WORK_AREA_BOUNDS = (0.0, 100.0, 0.0, 200.0)
        backend.OUTPUT_ROTATION_DEG = 180
        backend.OUTPUT_MIRROR_X = False
        backend.OUTPUT_MIRROR_Y = False
        backend.MACHINE_SOURCE_MIRROR_X = False
        backend.MACHINE_SOURCE_MIRROR_Y = False
        output = backend.transform_polylines_for_output_orientation([[(10.0, 20.0), (30.0, 40.0)]], logger=None)
        assert output == [[(90.0, 180.0), (70.0, 160.0)]]
    finally:
        (
            backend.OUTPUT_ROTATION_DEG,
            backend.OUTPUT_MIRROR_X,
            backend.OUTPUT_MIRROR_Y,
            backend.MACHINE_SOURCE_MIRROR_X,
            backend.MACHINE_SOURCE_MIRROR_Y,
        ) = original
        backend.ACTIVE_WORK_AREA_BOUNDS = original_bounds


def test_machine_source_mirror_can_be_toggled_by_user_mirror() -> None:
    original = (
        backend.OUTPUT_ROTATION_DEG,
        backend.OUTPUT_MIRROR_X,
        backend.OUTPUT_MIRROR_Y,
        backend.MACHINE_SOURCE_MIRROR_X,
        backend.MACHINE_SOURCE_MIRROR_Y,
        backend.ACTIVE_WORK_AREA_BOUNDS,
    )
    try:
        backend.ACTIVE_WORK_AREA_BOUNDS = (0.0, 100.0, 0.0, 200.0)
        backend.OUTPUT_ROTATION_DEG = 0
        backend.OUTPUT_MIRROR_X = False
        backend.OUTPUT_MIRROR_Y = False
        backend.MACHINE_SOURCE_MIRROR_X = False
        backend.MACHINE_SOURCE_MIRROR_Y = True
        assert backend.transform_polylines_for_output_orientation([[(10.0, 20.0)]], logger=None) == [[(10.0, 180.0)]]

        backend.OUTPUT_MIRROR_Y = True
        assert backend.transform_polylines_for_output_orientation([[(10.0, 20.0)]], logger=None) == [[(10.0, 20.0)]]
    finally:
        (
            backend.OUTPUT_ROTATION_DEG,
            backend.OUTPUT_MIRROR_X,
            backend.OUTPUT_MIRROR_Y,
            backend.MACHINE_SOURCE_MIRROR_X,
            backend.MACHINE_SOURCE_MIRROR_Y,
            backend.ACTIVE_WORK_AREA_BOUNDS,
        ) = original


def test_cli_parser_exposes_rotation_and_mirrors() -> None:
    parser = cli_entry.build_cli_parser(backend)
    args = parser.parse_args(["drawing.pdf", "--output-rotation", "90", "--mirror-x", "--mirror-y"])
    assert args.output_rotation == 90
    assert args.mirror_x is True
    assert args.mirror_y is True


def test_cli_rejects_impossible_eight_full_size_a4_layout() -> None:
    parser = cli_entry.build_cli_parser(backend)
    with pytest.raises(SystemExit):
        parser.parse_args(["--calibrate-corners", "--calibration-layout", "a2_8xa4"])
