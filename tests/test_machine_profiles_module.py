from __future__ import annotations

from pathlib import Path

from src.plotter_backend.machine.profiles import resolve_machine_profile


ROOT = Path(__file__).resolve().parents[1]


def test_a2_builtin_motion_matches_verified_controller_settings() -> None:
    profile = resolve_machine_profile("a2_corexy")

    assert profile["motion"]["feed_travel_mm_min"] == 3200.0
    assert profile["motion"]["feed_draw_mm_min"] == 1500.0
    assert profile["motion"]["controlled_g1_motion"] is True
    assert profile["pen"]["startup_force_lift_mm"] == 0.0


def test_a2_packaged_profile_matches_builtin_motion() -> None:
    profile = resolve_machine_profile("a2_corexy", ROOT / "config" / "machine_profiles.json")

    assert profile["motion"]["feed_travel_mm_min"] == 3200.0
    assert profile["motion"]["feed_draw_mm_min"] == 1500.0
    assert profile["motion"]["controlled_g1_motion"] is True
    assert profile["pen"]["startup_force_lift_mm"] == 0.0
