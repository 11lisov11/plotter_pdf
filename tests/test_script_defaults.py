from __future__ import annotations

from pathlib import Path


def test_release_motors_batch_defaults_to_wired_com6() -> None:
    text = Path("scripts/release_motors.bat").read_text(encoding="utf-8")

    assert 'if "%COM%"=="" set "COM=COM6"' in text
    assert 'set "COM=COM5"' not in text
