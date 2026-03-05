from __future__ import annotations

import unittest

from src.plotter_backend.geometry import clipping as clipping_mod


class GeometryClippingModuleTests(unittest.TestCase):
    def test_clamp_to_rect(self) -> None:
        self.assertEqual(clipping_mod.clamp_to_rect(-1.0, 5.0, 0.0, 2.0, 1.0, 3.0), (0.0, 3.0))

    def test_point_in_rect_with_eps(self) -> None:
        self.assertTrue(clipping_mod.point_in_rect(1.01, 0.0, 0.0, 1.0, -1.0, 1.0, eps=0.02))
        self.assertFalse(clipping_mod.point_in_rect(1.05, 0.0, 0.0, 1.0, -1.0, 1.0, eps=0.02))

    def test_clip_segment_to_rect(self) -> None:
        clipped = clipping_mod.clip_segment_to_rect(-1.0, 0.0, 2.0, 0.0, 0.0, 1.0, -1.0, 1.0)
        self.assertEqual(clipped, ((0.0, 0.0), (1.0, 0.0)))
        self.assertIsNone(clipping_mod.clip_segment_to_rect(-2.0, 2.0, -1.0, 3.0, 0.0, 1.0, -1.0, 1.0))

    def test_clip_polylines_to_rect_keeps_visible_segments(self) -> None:
        polys = [[(-1.0, 0.0), (0.5, 0.0), (2.0, 0.0)]]
        out = clipping_mod.clip_polylines_to_rect(
            polys,
            0.0,
            1.0,
            -1.0,
            1.0,
            continuity_eps_mm=0.1,
        )
        self.assertEqual(out, [[(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]])

    def test_clip_polylines_to_rect_splits_disconnected_visible_parts(self) -> None:
        polys = [[(0.2, 0.5), (0.8, 0.5), (0.8, 2.0), (1.2, 2.0), (1.2, 0.5), (1.8, 0.5)]]
        out = clipping_mod.clip_polylines_to_rect(
            polys,
            0.0,
            2.0,
            0.0,
            1.0,
            continuity_eps_mm=0.01,
        )
        self.assertEqual(len(out), 2)
        self.assertGreaterEqual(len(out[0]), 2)
        self.assertGreaterEqual(len(out[1]), 2)

    def test_clip_polylines_logs_drop_stats(self) -> None:
        logs: list[str] = []
        polys = [[(-5.0, -5.0), (-4.0, -4.0)]]
        out = clipping_mod.clip_polylines_to_rect(
            polys,
            0.0,
            1.0,
            0.0,
            1.0,
            continuity_eps_mm=0.01,
            logger=logs.append,
        )
        self.assertEqual(out, [])
        self.assertTrue(any("dropped" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
