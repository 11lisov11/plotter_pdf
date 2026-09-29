from __future__ import annotations

import re
from pathlib import Path

from src import plotter_pdf_drawer as backend


def test_a2_corner_route_uses_only_axis_aligned_penup_transitions() -> None:
    bounds = (0.0, 390.0, 0.0, 580.0)
    marks = backend._build_corner_mark_polylines_for_bounds(bounds, mark_size=2.5)

    assert len(marks) == 8
    cursor = (0.0, 0.0)
    for mark in marks:
        start = mark[0]
        dx = abs(float(start[0]) - float(cursor[0]))
        dy = abs(float(start[1]) - float(cursor[1]))
        assert dx <= 1e-9 or dy <= 1e-9
        cursor = mark[-1]

    assert cursor == (0.0, 580.0)
    assert cursor[0] == 0.0  # Final return home is vertical.


def test_each_corner_mark_pair_finishes_at_the_same_corner() -> None:
    marks = backend._build_corner_mark_polylines_for_bounds(
        (0.0, 390.0, 0.0, 580.0),
        mark_size=2.5,
    )

    expected_corners = [
        (0.0, 0.0),
        (390.0, 0.0),
        (390.0, 580.0),
        (0.0, 580.0),
    ]
    assert [marks[index][-1] for index in range(0, len(marks), 2)] == expected_corners
    assert [marks[index][-1] for index in range(1, len(marks), 2)] == expected_corners


def test_corexy_diagonal_rapid_is_split_into_axis_aligned_legs(tmp_path: Path) -> None:
    gcode = tmp_path / "rapid.nc"
    gcode.write_text("G21\nG90\nG0 X100 Y50 F4000\n", encoding="utf-8")

    changed = backend.rewrite_corexy_diagonal_rapid_moves_as_axis_aligned(gcode)

    assert changed == 1
    assert gcode.read_text(encoding="utf-8").splitlines()[-2:] == [
        "G0 X100.0000 Y0.0000 F4000.0",
        "G0 X100 Y50 F4000",
    ]


def test_corexy_diagonal_draw_feed_is_limited_per_motor(tmp_path: Path) -> None:
    gcode = tmp_path / "draw.nc"
    gcode.write_text("G21\nG90\nG1 X100 Y100 F4000\n", encoding="utf-8")

    changed = backend.limit_corexy_motor_feed_rates(gcode, motor_max_rate=4000.0)

    assert changed == 1
    text = gcode.read_text(encoding="utf-8")
    match = re.search(r"F([0-9.]+)", text)
    assert match is not None
    assert abs(float(match.group(1)) - 2828.4) <= 0.1


def test_corexy_axis_aligned_feed_keeps_requested_rate(tmp_path: Path) -> None:
    gcode = tmp_path / "axis.nc"
    gcode.write_text("G21\nG90\nG1 X100 Y0 F4000\n", encoding="utf-8")

    changed = backend.limit_corexy_motor_feed_rates(gcode, motor_max_rate=4000.0)

    assert changed == 0
    assert "F4000.0" in gcode.read_text(encoding="utf-8")


def test_controlled_rapid_assigns_separate_xy_and_z_feeds(tmp_path: Path) -> None:
    gcode = tmp_path / "missing_feeds.nc"
    gcode.write_text("G90\nG0 Z5\nG0 X100 Y0\n", encoding="utf-8")

    changed = backend.rewrite_rapid_moves_as_controlled(
        gcode,
        feed_travel=3200.0,
        feed_z=800.0,
    )

    assert changed == 2
    lines = gcode.read_text(encoding="utf-8").splitlines()
    assert "G1 Z5 F800.0" in lines
    assert "G1 X100 Y0 F3200.0" in lines


def test_a2_send_guard_sanitizes_ready_file_without_modifying_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "ready.nc"
    original = "G21\nG90\nG0 X100 Y50 F4000\nG1 X200 Y150 F4000\n"
    source.write_text(original, encoding="utf-8")
    captured: dict[str, str] = {}

    def fake_send(path: Path, *_args, **_kwargs) -> float:
        captured["text"] = Path(path).read_text(encoding="utf-8")
        return 1.25

    monkeypatch.setattr(backend, "MACHINE_PROFILE_NAME", "a2_corexy")
    monkeypatch.setattr(backend, "COREXY_MOTOR_MAX_RATE", 4000.0)
    monkeypatch.setattr(backend, "CONTROLLED_G1_MOTION", True)
    monkeypatch.setattr(backend.grbl_sender_mod, "send_to_grbl", fake_send)
    monkeypatch.setattr(backend, "preflight_check_gcode", lambda *_args, **_kwargs: (True, "ok"))

    result = backend.send_to_grbl(source, "COM_TEST", "115200", lambda _msg: None)

    assert result == 1.25
    assert source.read_text(encoding="utf-8") == original
    safe_text = captured["text"]
    assert "G1 X100.0000 Y0.0000 F4000.0" in safe_text
    draw_line = next(line for line in safe_text.splitlines() if line.startswith("G1 X200"))
    match = re.search(r"F([0-9.]+)", draw_line)
    assert match is not None
    assert abs(float(match.group(1)) - 2828.4) <= 0.1


def test_a2_send_guard_controls_relative_diagonal_rapid(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "relative_ready.nc"
    source.write_text("G21\nG91\nG0 X100 Y100 F4000\n", encoding="utf-8")
    captured: dict[str, str] = {}

    def fake_send(path: Path, *_args, **_kwargs) -> float:
        captured["text"] = Path(path).read_text(encoding="utf-8")
        return 0.5

    monkeypatch.setattr(backend, "MACHINE_PROFILE_NAME", "a2_corexy")
    monkeypatch.setattr(backend, "COREXY_MOTOR_MAX_RATE", 4000.0)
    monkeypatch.setattr(backend, "CONTROLLED_G1_MOTION", True)
    monkeypatch.setattr(backend.grbl_sender_mod, "send_to_grbl", fake_send)
    monkeypatch.setattr(backend, "preflight_check_gcode", lambda *_args, **_kwargs: (True, "ok"))

    backend.send_to_grbl(source, "COM_TEST", "115200", lambda _msg: None)

    move = next(line for line in captured["text"].splitlines() if "X100" in line)
    assert move.startswith("G1 ")
    match = re.search(r"F([0-9.]+)", move)
    assert match is not None
    assert abs(float(match.group(1)) - 2828.4) <= 0.1


def test_a2_send_guard_blocks_failed_preflight(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "unsafe.nc"
    source.write_text("G21\nG90\nG1 X500 Y0 F1000\n", encoding="utf-8")
    sent = False

    def fake_send(*_args, **_kwargs) -> float:
        nonlocal sent
        sent = True
        return 0.0

    monkeypatch.setattr(backend, "MACHINE_PROFILE_NAME", "a2_corexy")
    monkeypatch.setattr(backend, "COREXY_MOTOR_MAX_RATE", 4000.0)
    monkeypatch.setattr(backend.grbl_sender_mod, "send_to_grbl", fake_send)
    monkeypatch.setattr(
        backend,
        "preflight_check_gcode",
        lambda *_args, **_kwargs: (False, "motion exceeds machine travel area"),
    )

    try:
        backend.send_to_grbl(source, "COM_TEST", "115200", lambda _msg: None)
    except ValueError as exc:
        assert "CoreXY send blocked" in str(exc)
    else:
        raise AssertionError("Unsafe A2 file was not blocked")
    assert not sent
