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


def test_clean_gcode_lines_filters_motor_release_by_default() -> None:
    text = "G21\n$1=0\nG0 X1 Y2\n$SLP\n"

    lines = send_grbl_file._clean_gcode_lines(text)

    assert lines == ["G21", "G0 X1 Y2"]


def test_clean_gcode_lines_can_allow_explicit_motor_release() -> None:
    text = "G21\n$1=0\nG0 X1 Y2\n$SLP\n"

    lines = send_grbl_file._clean_gcode_lines(text, allow_motor_release=True)

    assert lines == ["G21", "$1=0", "G0 X1 Y2", "$SLP"]


def test_release_axes_holds_motors_by_default() -> None:
    ser = _FakeSerial()

    send_grbl_file.release_axes(ser, wait=False)

    assert "$1=255" in ser.commands
    assert "$1=0" not in ser.commands


def test_release_axes_releases_only_when_requested() -> None:
    ser = _FakeSerial()

    send_grbl_file.release_axes(ser, release=True, wait=False)

    assert "$1=0" in ser.commands
