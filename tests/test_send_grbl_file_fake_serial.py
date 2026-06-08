from pathlib import Path

import pytest

from src import send_grbl_file
from tests.fakes.fake_serial import FakeGrblSerial


def test_stream_success_fake_serial():
    ser = FakeGrblSerial(responses=[])
    send_grbl_file.stream_lines_to_grbl(ser, ["G0 X0", "G1 X1"], rx_buffer_size=128)
    assert any(b"G1 X1" in item for item in ser.written)


def test_stream_controller_error_is_clear():
    ser = FakeGrblSerial(responses=[], error_at_line=1)
    with pytest.raises(RuntimeError, match="Controller reported: error:33"):
        send_grbl_file.stream_lines_to_grbl(ser, ["G1 X1"], rx_buffer_size=128)


def test_stream_alarm_is_clear():
    ser = FakeGrblSerial(responses=[], alarm_at_line=1)
    with pytest.raises(RuntimeError, match="Controller reported: ALARM"):
        send_grbl_file.stream_lines_to_grbl(ser, ["G1 X1"], rx_buffer_size=128)


def test_line_too_long_caught():
    ser = FakeGrblSerial(responses=[])
    with pytest.raises(RuntimeError, match="Line too long"):
        send_grbl_file.stream_lines_to_grbl(ser, ["G1 X" + "1" * 200], rx_buffer_size=128)


def test_main_cleanup_closes_and_releases(monkeypatch, tmp_path: Path):
    gcode = tmp_path / "job.nc"; gcode.write_text("G0 X0\nG1 X1\n", encoding="utf-8")
    made = []
    def fake_open(port, baud):
        ser = FakeGrblSerial(responses=[])
        ser.open(); made.append(ser); return ser
    monkeypatch.setattr(send_grbl_file, "open_grbl", fake_open)
    monkeypatch.setattr(send_grbl_file, "wait_for_idle", lambda ser, timeout_s=3600: None)
    assert send_grbl_file.main(["send_grbl_file.py", "COM_FAKE", "115200", str(gcode)]) == 0
    sent = b"".join(made[0].written).decode("ascii", errors="ignore")
    assert "M5" in sent and "$1=0" in sent
    assert made[0].closed is True
