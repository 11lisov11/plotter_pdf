from __future__ import annotations

from src.plotter_backend.jobs.fake_grbl import FakeGrblController, FakeSerial


def test_fake_grbl_ok_and_status() -> None:
    fake = FakeSerial(FakeGrblController())
    fake.open()
    fake.read(4096)
    fake.write(b"$X\n")
    assert fake.read(4096).decode("ascii").strip() == "ok"
    fake.write(b"?\n")
    assert fake.read(4096).decode("ascii").startswith("<Idle|")


def test_fake_grbl_error_and_alarm() -> None:
    controller = FakeGrblController(error_code=33)
    assert controller.handle_command("G2 X1") == "error:33"
    controller.error_code = None
    controller.alarm = True
    assert controller.handle_command("G1 X1") == "ALARM:1"
