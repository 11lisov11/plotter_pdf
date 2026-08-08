from __future__ import annotations

import pytest

from src import plotter_pdf_drawer as backend
from src.plotter_backend.machine.profiles import resolve_machine_profile


def test_a2_profile_preserves_legacy_a4_and_declares_lower_left_origin() -> None:
    a4 = resolve_machine_profile("a4_desktop")
    a2 = resolve_machine_profile("a2_corexy")

    assert a4["work_area"]["min_y_mm"] == -280.0
    assert a4["work_area"]["max_y_mm"] == 0.0
    assert a2["work_area"]["origin"] == "lower_left"
    assert a2["work_area"]["y_positive"] == "up"
    assert a2["paper"]["source_mirror_y"] is True


def test_a2_calibration_layouts_have_four_corners_per_full_size_sheet() -> None:
    old_bounds = backend.ACTIVE_WORK_AREA_BOUNDS
    try:
        backend.ACTIVE_WORK_AREA_BOUNDS = (0.0, 390.0, 0.0, 580.0)
        assert len(backend.build_calibration_layout_corner_mark_polylines("a2")) == 8
        assert len(backend.build_calibration_layout_corner_mark_polylines("a2_2xa3")) == 14
        assert len(backend.build_calibration_layout_corner_mark_polylines("a2_4xa4")) == 24
        assert backend.calibration_layout_point_count("a2") == 4
        assert backend.calibration_layout_point_count("a2_2xa3") == 6
        assert backend.calibration_layout_point_count("a2_4xa4") == 9
        with pytest.raises(ValueError):
            backend.build_calibration_layout_corner_mark_polylines("a2_8xa4")
    finally:
        backend.ACTIVE_WORK_AREA_BOUNDS = old_bounds
