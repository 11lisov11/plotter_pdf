from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend import pencil_state


class DummyBackend:
    def __init__(self, root: Path) -> None:
        self.PENCIL_STATE_PATH = root / "pencil_state.json"
        self.PENCIL_PROFILE_PATH = root / "pencil_profile.json"
        self.PENCIL_WEAR_TEST_LAST_PATH = root / "pencil_wear_test_last.json"
        self.PENCIL_BASE_Z_DOWN = 8.4
        self.PENCIL_WEAR_MM_PER_M = 0.04
        self.PENCIL_Z_COMP_MM_PER_WEAR_MM = 1.5
        self.PENCIL_MAX_COMP_MM = 0.25
        self.PENCIL_REMIND_WEAR_MM = 0.20
        self.PENCIL_SHARPEN_INTERVAL_M = 5.0


class PencilStateModuleTests(unittest.TestCase):
    def test_reset_pencil_state_after_sharpen_resets_state_and_updates_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            backend = DummyBackend(Path(tmp_dir))
            pencil_state.save_pencil_state(
                backend,
                {
                    "total_draw_m": 1.75,
                    "estimated_wear_mm": 0.08,
                    "jobs_done": 4,
                    "last_draw_m": 0.31,
                },
            )
            pencil_state.save_pencil_profile(
                backend,
                {
                    "sharpen_count": 2,
                    "last_sharpen_iso_utc": "",
                },
            )
            messages: list[str] = []

            pencil_state.reset_pencil_state_after_sharpen(backend, messages.append, reason="unit-test")

            state = pencil_state.load_pencil_state(backend)
            profile = pencil_state.load_pencil_profile(backend)
            self.assertEqual(state["total_draw_m"], 0.0)
            self.assertEqual(state["estimated_wear_mm"], 0.0)
            self.assertEqual(state["jobs_done"], 0)
            self.assertEqual(state["last_draw_m"], 0.0)
            self.assertEqual(profile["sharpen_count"], 3)
            self.assertEqual(profile["last_sharpen_reason"], "unit-test")
            self.assertTrue(profile["last_sharpen_iso_utc"])
            self.assertEqual(len(messages), 1)
            self.assertIn("Pencil state reset", messages[0])

    def test_wear_update_and_effective_z_follow_backend_coefficients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            backend = DummyBackend(Path(tmp_dir))
            state = pencil_state.load_pencil_state(backend)

            updated = pencil_state.apply_pencil_wear_update(backend, state, 500.0)
            effective_z, compensation = pencil_state.pencil_effective_z_down(
                backend,
                backend.PENCIL_BASE_Z_DOWN,
                updated,
            )
            rem_best, rem_wear, rem_interval = pencil_state.pencil_remaining_to_sharpen_m(
                backend,
                updated,
            )

            self.assertAlmostEqual(updated["total_draw_m"], 0.5)
            self.assertAlmostEqual(updated["estimated_wear_mm"], 0.02)
            self.assertEqual(updated["jobs_done"], 1)
            self.assertAlmostEqual(updated["last_draw_m"], 0.5)
            self.assertAlmostEqual(compensation, 0.03)
            self.assertAlmostEqual(effective_z, 8.43)
            self.assertAlmostEqual(rem_wear, 4.5)
            self.assertAlmostEqual(rem_interval, 4.5)
            self.assertAlmostEqual(rem_best, 4.5)
