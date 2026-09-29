from __future__ import annotations

from unittest import mock

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
        backend.ACTIVE_WORK_AREA_BOUNDS = (0.0, 390.0, 0.0, 590.0)
        assert len(backend.build_calibration_layout_corner_mark_polylines("a2")) == 8
        assert len(backend.build_calibration_layout_corner_mark_polylines("a2_2xa3")) == 14
        assert len(backend.build_calibration_layout_corner_mark_polylines("a2_4xa4")) == 24
        assert backend.calibration_layout_point_count("a2") == 4
        assert backend.calibration_layout_point_count("a2_2xa3") == 6
        assert backend.calibration_layout_point_count("a2_4xa4") == 9
        for layout in ("a3_zone_1", "a3_zone_2", "a4_zone_11", "a4_zone_12", "a4_zone_21", "a4_zone_22"):
            assert len(backend.build_calibration_layout_corner_mark_polylines(layout)) == 8
            assert backend.calibration_layout_point_count(layout) == 4
        full_bounds = (0.0, 390.0, 0.0, 590.0)
        assert backend.calibration_layout_zone_bounds("a3_zone_1", full_bounds) == (0.0, 390.0, 0.0, 295.0)
        assert backend.calibration_layout_zone_bounds("a3_zone_2", full_bounds) == (0.0, 390.0, 295.0, 590.0)
        assert backend.calibration_layout_zone_bounds("a4_zone_11", full_bounds) == (0.0, 195.0, 0.0, 295.0)
        assert backend.calibration_layout_zone_bounds("a4_zone_12", full_bounds) == (195.0, 390.0, 0.0, 295.0)
        assert backend.calibration_layout_zone_bounds("a4_zone_21", full_bounds) == (0.0, 195.0, 295.0, 590.0)
        assert backend.calibration_layout_zone_bounds("a4_zone_22", full_bounds) == (195.0, 390.0, 295.0, 590.0)
        assert backend.calibration_layout_point_count("a2_mixed_a3_near") == 8
        assert backend.calibration_layout_point_count("a2_mixed_a3_far") == 8
        with pytest.raises(ValueError):
            backend.build_calibration_layout_corner_mark_polylines("a2_8xa4")
    finally:
        backend.ACTIVE_WORK_AREA_BOUNDS = old_bounds


def test_numbered_zones_use_full_machine_bounds_after_sheet_area_is_centered() -> None:
    old_bounds = backend.ACTIVE_WORK_AREA_BOUNDS
    try:
        backend.ACTIVE_WORK_AREA_BOUNDS = (90.0, 300.0, 141.5, 438.5)
        with mock.patch.object(backend, "base_work_area_bounds", return_value=(0.0, 390.0, 0.0, 580.0)):
            assert backend.calibration_layout_zone_bounds("a3_zone_2") == (0.0, 390.0, 290.0, 580.0)
            assert backend.calibration_layout_zone_bounds("a4_zone_22") == (195.0, 390.0, 290.0, 580.0)
            marks = backend.build_calibration_layout_corner_mark_polylines("a4_zone_22")
            clipped = backend._clip_calibration_layout_polylines(marks, "a4_zone_22", logger=None)
            points = [point for polyline in clipped for point in polyline]
            assert max(x for x, _y in points) == 390.0
            assert max(y for _x, y in points) == 580.0
    finally:
        backend.ACTIVE_WORK_AREA_BOUNDS = old_bounds
