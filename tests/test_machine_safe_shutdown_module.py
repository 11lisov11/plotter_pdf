from __future__ import annotations

from src.plotter_backend.machine.safe_shutdown import build_safe_park_release_commands


def test_safe_park_release_lifts_homes_then_releases() -> None:
    commands = build_safe_park_release_commands()

    lift_before_home = next(i for i, cmd in enumerate(commands) if cmd.startswith("G1 Z0.0000"))
    home = commands.index("G1 X0.0000 Y0.0000 F15000.0")
    lift_after_home = next(
        i for i, cmd in enumerate(commands[home + 1 :], start=home + 1) if cmd.startswith("G1 Z0.0000")
    )
    release = commands.index("$1=0")

    assert commands[:3] == ["$X", "$1=255", "G90"]
    assert lift_before_home < home < lift_after_home < release
    assert commands[-1] == "$1=0"


def test_safe_park_release_sleep_releases_before_sleep() -> None:
    commands = build_safe_park_release_commands(sleep=True)

    assert commands[-2:] == ["$1=0", "$SLP"]


def test_safe_park_release_hold_keeps_motors_enabled_after_home() -> None:
    commands = build_safe_park_release_commands(release=False)

    assert "$1=0" not in commands
    assert commands[-1] == "$1=255"
