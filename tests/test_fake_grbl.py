from src.plotter_backend.jobs.fake_grbl import FakeGrblSerial


def test_fake_grbl_ok_and_status():
    ser = FakeGrblSerial()
    ser.open()
    ser.write(b"?\n")
    assert b"Idle" in ser.read(4096)
    ser.write(b"G0 X1\n")
    assert ser.readline().strip() == b"ok"


def test_fake_grbl_error_alarm_disconnect():
    ser = FakeGrblSerial(error_at_line=1)
    ser.open(); ser.read(4096); ser.write(b"G1 X1\n")
    assert ser.readline().startswith(b"error:")
    alarm = FakeGrblSerial(alarm_at_line=1)
    alarm.open(); alarm.read(4096); alarm.write(b"G1 X1\n")
    assert alarm.readline().startswith(b"ALARM:")
