from __future__ import annotations

from src import send_grbl_file


class _FakeSerial:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def write(self, data: bytes) -> None:
        self.commands.append(data.decode("ascii").strip())

    def flush(self) -> None:
        return

    def readline(self) -> bytes:
        return b"ok\n"

    def reset_input_buffer(self) -> None:
        return

    def reset_output_buffer(self) -> None:
        return


def test_clean_gcode_lines_filters_motor_release_by_default() -> None:
    text = "G21\n$1=0\nG0 X1 Y2\n$SLP\n"

    lines = send_grbl_file._clean_gcode_lines(text)

    assert lines == ["G21", "G0 X1 Y2"]


def test_clean_gcode_lines_can_allow_explicit_motor_release() -> None:
    text = "G21\n$1=0\nG0 X1 Y2\n$SLP\n"

    lines = send_grbl_file._clean_gcode_lines(text, allow_motor_release=True)

    assert lines == ["G21", "$1=0", "G0 X1 Y2", "$SLP"]


def test_release_axes_returns_home_lifted_then_releases_by_default() -> None:
    ser = _FakeSerial()

    send_grbl_file.release_axes(ser, wait=False)

    lift_before_home = next(i for i, cmd in enumerate(ser.commands) if cmd.startswith("G1 Z0.0000"))
    home = next(i for i, cmd in enumerate(ser.commands) if cmd.startswith("G1 X0.0000 Y0.0000"))
    lift_after_home = next(i for i, cmd in enumerate(ser.commands[home + 1 :], start=home + 1) if cmd.startswith("G1 Z0.0000"))
    release = ser.commands.index("$1=0")
    assert "$1=255" in ser.commands[:lift_before_home]
    assert lift_before_home < home < lift_after_home < release


def test_release_axes_holds_motors_when_requested() -> None:
    ser = _FakeSerial()

    send_grbl_file.release_axes(ser, release=False, wait=False)

    assert "$1=255" in ser.commands
    assert "$1=0" not in ser.commands


def test_release_axes_soft_resets_before_safe_motion_when_requested() -> None:
    ser = _FakeSerial()

    send_grbl_file.release_axes(ser, reset_queue=True, wait=False)

    assert ser.commands[0] == "\x18"
    assert "$X" in ser.commands[1:3]
