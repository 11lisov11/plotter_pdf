from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from src import plotter_pdf_drawer as backend


class BackendGeometryTests(unittest.TestCase):
    @staticmethod
    def _rect(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]

    def test_compute_pass_shift_for_two_columns(self) -> None:
        old = (backend.PASS_COLS, backend.PASS_ROWS, backend.PASS_COL, backend.PASS_ROW)
        try:
            backend.PASS_COLS = 2
            backend.PASS_ROWS = 1
            backend.PASS_ROW = 1

            backend.PASS_COL = 1
            shift_x_1, shift_y_1, info_1 = backend.compute_pass_shift(
                source_w_mm=400.0,
                source_h_mm=280.0,
                window_w_mm=200.0,
                window_h_mm=280.0,
            )
            backend.PASS_COL = 2
            shift_x_2, shift_y_2, info_2 = backend.compute_pass_shift(
                source_w_mm=400.0,
                source_h_mm=280.0,
                window_w_mm=200.0,
                window_h_mm=280.0,
            )

            self.assertEqual(info_1["col"], 1)
            self.assertEqual(info_2["col"], 2)
            self.assertAlmostEqual(shift_y_1, 0.0, places=6)
            self.assertAlmostEqual(shift_y_2, 0.0, places=6)
            self.assertAlmostEqual(shift_x_1, -shift_x_2, places=6)
            self.assertGreater(shift_x_1, 0.0)
            self.assertLess(shift_x_2, 0.0)
        finally:
            backend.PASS_COLS, backend.PASS_ROWS, backend.PASS_COL, backend.PASS_ROW = old

    def test_plan_tiled_passes_reports_two_pass_scale(self) -> None:
        plan = backend.plan_tiled_passes_for_sheet(420.0, 297.0)
        self.assertIn("max_two_pass_scale", plan)
        self.assertGreater(float(plan["max_two_pass_scale"]), 0.0)
        self.assertIn("nx", plan)
        self.assertIn("ny", plan)

    def test_apply_handwriting_font_updates_text_nodes(self) -> None:
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm">
  <text x="1" y="5" style="font-size:4px;fill:#000000">abc</text>
</svg>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.svg"
            path.write_text(svg, encoding="utf-8")
            changed = backend.apply_handwriting_font(path, "Segoe Script", logger=lambda *_: None)
            self.assertEqual(changed, 1)
            txt = path.read_text(encoding="utf-8")
            self.assertIn("Segoe Script", txt)

    def test_normalize_image_contour_mode_defaults_to_legacy(self) -> None:
        old_word_only = backend.IMAGE_CONTOUR_WORD_ONLY
        try:
            backend.IMAGE_CONTOUR_WORD_ONLY = True
            self.assertEqual(backend.normalize_image_contour_mode("invalid"), "word_only")
            backend.IMAGE_CONTOUR_WORD_ONLY = False
            self.assertEqual(backend.normalize_image_contour_mode("invalid"), "always")
        finally:
            backend.IMAGE_CONTOUR_WORD_ONLY = old_word_only

    def test_image_contours_enabled_for_input_mode_matrix(self) -> None:
        old_enabled = backend.IMAGE_CONTOUR_ENABLED
        old_mode = backend.IMAGE_CONTOUR_MODE
        try:
            backend.IMAGE_CONTOUR_ENABLED = True

            backend.IMAGE_CONTOUR_MODE = "off"
            self.assertFalse(backend.image_contours_enabled_for_input(False))
            self.assertFalse(backend.image_contours_enabled_for_input(True))

            backend.IMAGE_CONTOUR_MODE = "always"
            self.assertTrue(backend.image_contours_enabled_for_input(False))
            self.assertTrue(backend.image_contours_enabled_for_input(True))

            backend.IMAGE_CONTOUR_MODE = "word_only"
            self.assertFalse(backend.image_contours_enabled_for_input(False))
            self.assertTrue(backend.image_contours_enabled_for_input(True))
        finally:
            backend.IMAGE_CONTOUR_ENABLED = old_enabled
            backend.IMAGE_CONTOUR_MODE = old_mode

    def test_image_hatch_enabled_for_input_mode_matrix(self) -> None:
        old_enabled = backend.IMAGE_TONE_HATCH_ENABLED
        old_word_only = backend.IMAGE_TONE_HATCH_WORD_ONLY
        old_mode = backend.IMAGE_CONTOUR_MODE
        try:
            backend.IMAGE_TONE_HATCH_ENABLED = True
            backend.IMAGE_TONE_HATCH_WORD_ONLY = True

            backend.IMAGE_CONTOUR_MODE = "off"
            self.assertFalse(backend.image_hatch_enabled_for_input(False))
            self.assertFalse(backend.image_hatch_enabled_for_input(True))

            backend.IMAGE_CONTOUR_MODE = "always"
            self.assertFalse(backend.image_hatch_enabled_for_input(False))
            self.assertTrue(backend.image_hatch_enabled_for_input(True))

            backend.IMAGE_CONTOUR_MODE = "word_only"
            self.assertFalse(backend.image_hatch_enabled_for_input(False))
            self.assertTrue(backend.image_hatch_enabled_for_input(True))
        finally:
            backend.IMAGE_TONE_HATCH_ENABLED = old_enabled
            backend.IMAGE_TONE_HATCH_WORD_ONLY = old_word_only
            backend.IMAGE_CONTOUR_MODE = old_mode

    def test_cluster_small_fill_items_for_single_stroke_groups_nested_contours(self) -> None:
        items = [
            backend.PathItem(
                points=self._rect(0.0, 0.0, 4.0, 6.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=10,
            ),
            backend.PathItem(
                points=self._rect(1.0, 2.0, 3.0, 4.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=11,
            ),
            backend.PathItem(
                points=self._rect(20.0, 0.0, 24.0, 6.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=12,
            ),
        ]
        clusters = backend.cluster_small_fill_items_for_single_stroke(items)
        norm = [tuple(sorted(c)) for c in clusters]
        self.assertIn((0, 1), norm)
        self.assertNotIn((0, 1, 2), norm)

    def test_to_drawing_polylines_uses_cluster_centerline_and_skips_consumed(self) -> None:
        items = [
            backend.PathItem(
                points=self._rect(0.0, 0.0, 4.0, 6.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=1,
            ),
            backend.PathItem(
                points=self._rect(1.0, 2.0, 3.0, 4.0),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=2,
            ),
            backend.PathItem(
                points=[(10.0, 10.0), (20.0, 10.0)],
                closed=False,
                is_fill=False,
                is_stroke=True,
                source_id=3,
            ),
        ]
        synthetic_centerline = [[(0.5, 0.5), (3.5, 5.5)]]
        with (
            mock.patch.object(backend, "cluster_small_fill_items_for_single_stroke", return_value=[[0, 1]]),
            mock.patch.object(backend, "centerline_fill_group", return_value=synthetic_centerline),
            mock.patch.object(backend, "centerline_is_usable", return_value=True),
        ):
            out = backend.to_drawing_polylines(items)

        self.assertEqual(len(out), 2)
        self.assertIn(synthetic_centerline[0], out)
        self.assertIn(items[2].points, out)
        self.assertNotIn(items[0].points, out)
        self.assertNotIn(items[1].points, out)

    def test_apply_word_handwriting_font_restores_math_runs(self) -> None:
        class _Font:
            def __init__(self) -> None:
                self.Name = ""
                self.NameAscii = ""
                self.NameFarEast = ""
                self.NameOther = ""

        class _Range:
            def __init__(self) -> None:
                self.Font = _Font()

        class _OMathItem:
            def __init__(self) -> None:
                self.Range = _Range()

        class _OMaths:
            def __init__(self, count: int) -> None:
                self.Count = count
                self._items = [_OMathItem() for _ in range(count)]

            def Item(self, i: int) -> _OMathItem:
                return self._items[i - 1]

        class _Doc:
            def __init__(self) -> None:
                self.Content = _Range()
                self.OMaths = _OMaths(3)

        old_keep_math = backend.HANDWRITING_WORD_KEEP_MATH
        try:
            backend.HANDWRITING_WORD_KEEP_MATH = True
            doc = _Doc()
            ok, restored = backend.apply_word_handwriting_font(doc, "Segoe Script", logger=lambda *_: None)
            self.assertTrue(ok)
            self.assertEqual(restored, 3)
            self.assertEqual(doc.Content.Font.Name, "Segoe Script")
            for i in range(1, doc.OMaths.Count + 1):
                self.assertEqual(doc.OMaths.Item(i).Range.Font.Name, "Cambria Math")
        finally:
            backend.HANDWRITING_WORD_KEEP_MATH = old_keep_math

    def test_preflight_check_gcode_pass_and_fail_bounds(self) -> None:
        old_active = backend.ACTIVE_WORK_AREA_BOUNDS
        try:
            backend.ACTIVE_WORK_AREA_BOUNDS = (0.0, 100.0, -100.0, 0.0)
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                ok_path = td_path / "ok.nc"
                ok_path.write_text(
                    "\n".join(
                        [
                            "G21",
                            "G90",
                            "G0 X10 Y-10",
                            "G1 X20 Y-20 F800",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                ok, msg = backend.preflight_check_gcode(ok_path, logger=lambda *_: None)
                self.assertTrue(ok, msg)

                bad_path = td_path / "bad.nc"
                bad_path.write_text(
                    "\n".join(
                        [
                            "G21",
                            "G90",
                            "G0 X10 Y-10",
                            "G1 X20 Y10 F800",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                ok2, msg2 = backend.preflight_check_gcode(bad_path, logger=lambda *_: None)
                self.assertFalse(ok2)
                self.assertIn("exceeds active area", msg2)
        finally:
            backend.ACTIVE_WORK_AREA_BOUNDS = old_active

    def test_preflight_ignores_home_travel_with_pen_up(self) -> None:
        old_active = backend.ACTIVE_WORK_AREA_BOUNDS
        old_z_up = backend.Z_UP
        old_z_down = backend.Z_DOWN
        try:
            backend.ACTIVE_WORK_AREA_BOUNDS = (0.0, 100.0, -100.0, -10.0)
            backend.Z_UP = 0.0
            backend.Z_DOWN = 10.0
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                path = td_path / "home_travel.nc"
                path.write_text(
                    "\n".join(
                        [
                            "G21",
                            "G90",
                            "G0 Z0",
                            "G0 X10 Y-20",
                            "G0 Z10",
                            "G1 X40 Y-20 F800",
                            "G0 Z0",
                            "G0 X0 Y0",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                ok, msg = backend.preflight_check_gcode(path, logger=lambda *_: None)
                self.assertTrue(ok, msg)
        finally:
            backend.ACTIVE_WORK_AREA_BOUNDS = old_active
            backend.Z_UP = old_z_up
            backend.Z_DOWN = old_z_down

    def test_extract_image_tone_hatch_segments_px_simple(self) -> None:
        if backend.cv2 is None or backend.np is None:
            self.skipTest("opencv/numpy unavailable")
        img = backend.np.full((32, 32), 255, dtype=backend.np.uint8)
        img[10:22, 8:24] = 40
        segs = backend._extract_image_tone_hatch_segments_px(
            img,
            step_px=3,
            min_seg_px=4,
            max_paths=200,
        )
        self.assertGreater(len(segs), 0)
        self.assertTrue(all(len(s) == 2 for s in segs))

    def test_humanize_pencil_polylines_changes_curvy_stroke_but_keeps_endpoints(self) -> None:
        old_enabled = backend.PENCIL_NATURAL_STROKES_ENABLED
        old_only_hw = backend.PENCIL_NATURAL_ONLY_HANDWRITING
        try:
            backend.PENCIL_NATURAL_STROKES_ENABLED = True
            backend.PENCIL_NATURAL_ONLY_HANDWRITING = False
            poly = [(0.0, 0.0), (2.0, 1.6), (4.0, -1.2), (6.0, 1.5), (8.0, 0.0)]
            out = backend.humanize_pencil_polylines([poly], logger=lambda *_: None, handwriting_enabled=False)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0][0], poly[0])
            self.assertEqual(out[0][-1], poly[-1])
            changed = any(backend.points_distance(a, b) > 1e-6 for a, b in zip(out[0], poly[: len(out[0])]))
            self.assertTrue(changed or len(out[0]) != len(poly))
        finally:
            backend.PENCIL_NATURAL_STROKES_ENABLED = old_enabled
            backend.PENCIL_NATURAL_ONLY_HANDWRITING = old_only_hw

    def test_humanize_pencil_polylines_skips_straight_line(self) -> None:
        old_enabled = backend.PENCIL_NATURAL_STROKES_ENABLED
        old_only_hw = backend.PENCIL_NATURAL_ONLY_HANDWRITING
        try:
            backend.PENCIL_NATURAL_STROKES_ENABLED = True
            backend.PENCIL_NATURAL_ONLY_HANDWRITING = False
            straight = [(0.0, 0.0), (10.0, 0.01), (20.0, 0.0), (30.0, 0.0)]
            out = backend.humanize_pencil_polylines([straight], logger=lambda *_: None, handwriting_enabled=False)
            self.assertEqual(out[0], straight)
        finally:
            backend.PENCIL_NATURAL_STROKES_ENABLED = old_enabled
            backend.PENCIL_NATURAL_ONLY_HANDWRITING = old_only_hw

    def test_merge_handwriting_word_strokes_merges_small_same_line_gaps(self) -> None:
        old_join_enable = backend.HANDWRITING_WORD_JOIN_ENABLE
        try:
            backend.HANDWRITING_WORD_JOIN_ENABLE = True
            polylines = [
                [(0.0, 0.0), (1.0, 0.0)],
                [(1.8, 0.1), (2.8, 0.1)],
                [(5.6, 0.0), (6.5, 0.0)],
            ]
            out = backend.merge_handwriting_word_strokes(
                polylines,
                logger=lambda *_: None,
                join_gap_mm=1.2,
                join_max_dy_mm=0.3,
            )
            self.assertEqual(len(out), 2)
            self.assertEqual(out[0][0], polylines[0][0])
            self.assertEqual(out[0][-1], polylines[1][-1])
            self.assertEqual(out[1], polylines[2])
        finally:
            backend.HANDWRITING_WORD_JOIN_ENABLE = old_join_enable

    def test_merge_handwriting_word_strokes_does_not_merge_backward_jump(self) -> None:
        old_join_enable = backend.HANDWRITING_WORD_JOIN_ENABLE
        try:
            backend.HANDWRITING_WORD_JOIN_ENABLE = True
            polylines = [
                [(2.0, 0.0), (3.0, 0.0)],
                [(2.2, 0.1), (1.6, 0.2)],
            ]
            out = backend.merge_handwriting_word_strokes(
                polylines,
                logger=lambda *_: None,
                join_gap_mm=1.0,
                join_max_dy_mm=0.4,
            )
            self.assertEqual(len(out), 2)
        finally:
            backend.HANDWRITING_WORD_JOIN_ENABLE = old_join_enable

    def test_smooth_handwriting_polylines_preserves_endpoints(self) -> None:
        old_enabled = backend.HANDWRITING_SMOOTH_ENABLED
        try:
            backend.HANDWRITING_SMOOTH_ENABLED = True
            poly = [(0.0, 0.0), (0.6, 0.5), (1.2, -0.3), (1.8, 0.4), (2.4, 0.0)]
            out = backend.smooth_handwriting_polylines([poly], logger=lambda *_: None)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0][0], poly[0])
            self.assertEqual(out[0][-1], poly[-1])
            self.assertGreaterEqual(len(out[0]), 2)
        finally:
            backend.HANDWRITING_SMOOTH_ENABLED = old_enabled

    def test_prune_skeleton_spurs_removes_short_branch(self) -> None:
        if backend.np is None:
            self.skipTest("numpy unavailable")
        sk = backend.np.zeros((9, 9), dtype=backend.np.uint8)
        # main horizontal line
        sk[4, 1:8] = 255
        # short spur upwards
        sk[3, 4] = 255
        sk[2, 4] = 255
        pr = backend._prune_skeleton_spurs(sk, max_len_px=2)
        self.assertEqual(int(pr[2, 4]), 0)
        self.assertEqual(int(pr[4, 4]), 255)
        # The tip must be pruned; one junction-near pixel may remain.
        remaining_col = int((pr[:, 4] > 0).sum())
        self.assertLessEqual(remaining_col, 2)

    def test_likely_handwriting_text_group_heuristic(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 6.0, 8.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=1,
                ),
                backend.PathItem(
                    points=self._rect(1.8, 2.0, 4.2, 5.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=2,
                ),
            ]
            self.assertTrue(backend._likely_handwriting_text_group(group))
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_likely_handwriting_text_group_accepts_wide_low_bbox(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 80.0, 9.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=12,
                )
            ]
            self.assertTrue(backend._likely_handwriting_text_group(group))
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_centerline_fill_group_ignores_open_polylines(self) -> None:
        if backend.np is None or backend.cv2 is None:
            self.skipTest("opencv/numpy unavailable")
        open_item = backend.PathItem(
            points=[(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 3.0)],
            closed=False,
            is_fill=True,
            is_stroke=False,
            source_id=7,
        )
        out = backend.centerline_fill_group([open_item])
        self.assertEqual(out, [])

    def test_to_drawing_polylines_uses_outline_centerline_in_handwriting_mode(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_outline = backend.HANDWRITING_OUTLINE_CENTERLINE_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.HANDWRITING_OUTLINE_CENTERLINE_ENABLED = True
            items = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 3.0, 6.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=10,
                )
            ]
            synthetic = [[(0.4, 0.2), (1.6, 5.8)]]
            with (
                mock.patch.object(backend, "centerline_fill_group", return_value=synthetic),
                mock.patch.object(backend, "refine_centerline_paths", return_value=synthetic),
            ):
                out = backend.to_drawing_polylines(items)
            self.assertEqual(out, synthetic)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.HANDWRITING_OUTLINE_CENTERLINE_ENABLED = old_outline

    def test_cluster_small_outline_items_for_single_stroke_groups_nested_contours(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_outline = backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED = True
            items = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 4.0, 6.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=10,
                ),
                backend.PathItem(
                    points=self._rect(1.0, 2.0, 3.0, 4.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=11,
                ),
                backend.PathItem(
                    points=self._rect(20.0, 0.0, 24.0, 6.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=12,
                ),
            ]
            clusters = backend.cluster_small_outline_items_for_single_stroke(items)
            norm = [tuple(sorted(c)) for c in clusters]
            self.assertIn((0, 1), norm)
            self.assertNotIn((0, 1, 2), norm)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED = old_outline

    def test_to_drawing_polylines_uses_outline_cluster_centerline(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_outline = backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED = True
            items = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 4.0, 6.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=1,
                ),
                backend.PathItem(
                    points=self._rect(1.0, 2.0, 3.0, 4.0),
                    closed=True,
                    is_fill=False,
                    is_stroke=True,
                    source_id=2,
                ),
            ]
            synthetic = [[(0.8, 0.5), (2.6, 5.6)]]
            with (
                mock.patch.object(backend, "cluster_small_outline_items_for_single_stroke", return_value=[[0, 1]]),
                mock.patch.object(backend, "centerline_fill_group", return_value=synthetic),
                mock.patch.object(backend, "refine_centerline_paths", return_value=synthetic),
                mock.patch.object(backend, "centerline_is_usable", return_value=True),
            ):
                out = backend.to_drawing_polylines(items)
            self.assertEqual(out, synthetic)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.SINGLE_STROKE_OUTLINE_TEXT_ENABLED = old_outline

    def test_centerline_quality_ok_for_handwriting_rejects_fragment_noise(self) -> None:
        tiny = [[(0.0, 0.0), (0.15, 0.0)] for _ in range(30)]
        self.assertFalse(backend._centerline_quality_ok_for_handwriting(tiny))

    def test_centerline_quality_ok_for_handwriting_accepts_reasonable_paths(self) -> None:
        good = [
            [(0.0, 0.0), (1.2, 0.1), (2.4, 0.0)],
            [(0.0, 1.0), (1.3, 1.2), (2.7, 1.0)],
            [(0.0, 2.0), (1.4, 1.8), (2.9, 2.0)],
        ]
        self.assertTrue(backend._centerline_quality_ok_for_handwriting(good))

    def test_tiny_handwriting_text_fallback_builds_single_stroke(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 0.7, 0.6),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=101,
                )
            ]
            out = backend.tiny_handwriting_text_fallback(group, [])
            self.assertEqual(len(out), 1)
            self.assertEqual(len(out[0]), 2)
            self.assertGreater(backend.polyline_length(out[0]), 0.0)
            self.assertGreater(backend.points_distance(out[0][0], out[0][-1]), 0.0)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_to_drawing_polylines_uses_tiny_handwriting_fallback_instead_of_contour(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            item = backend.PathItem(
                points=self._rect(0.0, 0.0, 0.7, 0.6),
                closed=True,
                is_fill=True,
                is_stroke=False,
                source_id=202,
            )
            with (
                mock.patch.object(backend, "centerline_fill_group", return_value=[]),
                mock.patch.object(backend, "refine_centerline_paths", return_value=[]),
                mock.patch.object(backend, "centerline_is_usable", return_value=False),
                mock.patch.object(backend, "_centerline_quality_ok_for_handwriting", return_value=False),
            ):
                out = backend.to_drawing_polylines([item])

            self.assertEqual(len(out), 1)
            self.assertEqual(len(out[0]), 2)
            self.assertNotEqual(out[0], item.points)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw

    def test_force_single_stroke_handwriting_group_uses_centerline_even_if_unusable(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_force = backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 4.0, 5.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=303,
                )
            ]
            center = [[(0.1, 0.1), (2.0, 2.0), (3.9, 4.9)]]
            out = backend.force_single_stroke_handwriting_group(group, center)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0][0], center[0][0])
            self.assertEqual(out[0][-1], center[0][-1])
            self.assertGreater(backend.polyline_length(out[0]), 0.0)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT = old_force

    def test_force_single_stroke_handwriting_group_generates_synthetic_when_empty(self) -> None:
        old_hw = backend.HANDWRITING_TEXT_ENABLED
        old_force = backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT
        try:
            backend.HANDWRITING_TEXT_ENABLED = True
            backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT = True
            group = [
                backend.PathItem(
                    points=self._rect(0.0, 0.0, 7.0, 4.0),
                    closed=True,
                    is_fill=True,
                    is_stroke=False,
                    source_id=404,
                )
            ]
            out = backend.force_single_stroke_handwriting_group(group, [])
            self.assertEqual(len(out), 1)
            self.assertEqual(len(out[0]), 2)
            self.assertGreater(backend.polyline_length(out[0]), 0.0)
        finally:
            backend.HANDWRITING_TEXT_ENABLED = old_hw
            backend.HANDWRITING_FORCE_SINGLE_STROKE_TEXT = old_force

    def test_pick_hershey_font_name_for_text_mixed_scripts(self) -> None:
        self.assertEqual(backend._pick_hershey_font_name_for_text("Segoe Script", "Hello"), "cursive")
        self.assertEqual(backend._pick_hershey_font_name_for_text("Segoe Script", "Привет"), "cyrilc_1")
        self.assertEqual(backend._pick_hershey_font_name_for_text("Monospace", "Русский"), "cyrillic")

    def test_hershey_segments_to_polylines_joins_connected_segments(self) -> None:
        segments = [
            ((0.0, 0.0), (1.0, 0.0)),
            ((1.0, 0.0), (2.0, 0.0)),
            ((5.0, 0.0), (6.0, 0.0)),
        ]
        polylines = backend._hershey_segments_to_polylines(segments)
        self.assertEqual(len(polylines), 2)
        self.assertEqual(polylines[0], [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
        self.assertEqual(polylines[1], [(5.0, 0.0), (6.0, 0.0)])

    def test_trace_skeleton_paths_greedy_follows_simple_line(self) -> None:
        if backend.np is None:
            self.skipTest("numpy unavailable")
        skel = backend.np.zeros((7, 12), dtype=backend.np.uint8)
        skel[3, 2:10] = 255
        paths = backend._trace_skeleton_paths_greedy(skel)
        self.assertTrue(any(len(path) >= 8 for path in paths))

    def test_render_singleline_text_polylines_ttf_returns_strokes(self) -> None:
        font_path = backend._resolve_handwriting_ttf_path("Segoe Script")
        if font_path is None:
            self.skipTest("Segoe Script font not available")
        polylines = backend._render_singleline_text_polylines_ttf(
            "\u041f\u0440\u0438\u0432\u0435\u0442",
            ttf_path=font_path,
            font_size=14.0,
            baseline_x=0.0,
            baseline_y=0.0,
            logger=lambda *_: None,
        )
        self.assertGreater(len(polylines), 0)
        self.assertTrue(all(len(poly) >= 2 for poly in polylines))

    def test_run_autotrace_centerline_on_binary_works_without_pillow(self) -> None:
        if backend.np is None:
            self.skipTest("numpy unavailable")

        binary = backend.np.full((8, 16), 255, dtype=backend.np.uint8)
        binary[3:5, 2:14] = 0
        captured: dict[str, object] = {}

        def _fake_run_cmd(cmd, timeout_s=0.0):
            pbm_path = Path(cmd[-1])
            captured["pbm_exists"] = pbm_path.exists()
            captured["pbm_head"] = pbm_path.read_bytes()[:2]
            captured["timeout_s"] = float(timeout_s)
            return 0, '<svg xmlns="http://www.w3.org/2000/svg"><path d="M 0 0 L 5 0"/></svg>', ""

        with mock.patch.object(backend, "Image", None):
            with mock.patch.object(backend, "run_cmd", side_effect=_fake_run_cmd):
                polylines = backend._run_autotrace_centerline_on_binary(
                    binary,
                    autotrace_exe=Path("autotrace.exe"),
                    error_threshold=2.0,
                    filter_iterations=2,
                    curve_step_px=0.85,
                )

        self.assertTrue(bool(captured.get("pbm_exists")))
        self.assertEqual(captured.get("pbm_head"), b"P4")
        self.assertGreater(len(polylines), 0)
        self.assertGreaterEqual(len(polylines[0]), 2)

    def test_replace_svg_text_with_singleline_ttf_respects_inherited_font_size(self) -> None:
        font_path = backend._resolve_handwriting_ttf_path("Segoe Script")
        if font_path is None:
            self.skipTest("Segoe Script font not available")
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm">
  <g fill="#111111" font-family="Segoe Script" font-size="8">
    <text x="2" y="10">Привет</text>
  </g>
</svg>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.svg"
            path.write_text(svg, encoding="utf-8")
            changed = backend.replace_svg_text_with_singleline_ttf(path, "Segoe Script", logger=lambda *_: None)
            self.assertEqual(changed, 1)
            txt = path.read_text(encoding="utf-8")
            self.assertIn('stroke-width="0.1600"', txt)

    def test_replace_svg_text_with_svg_stroke_fonts_creates_paths(self) -> None:
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="40mm">
  <text x="20" y="20" style="font-size:10px;fill:#000000">Привет мир</text>
</svg>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stroke.svg"
            path.write_text(svg, encoding="utf-8")
            changed = backend.replace_svg_text_with_svg_stroke_fonts(path, "Segoe Script", logger=lambda *_: None)
            self.assertEqual(changed, 1)
            self.assertEqual(backend.svg_text_node_count(path), 0)
            txt = path.read_text(encoding="utf-8")
            self.assertIn('fill="none"', txt)
            root = backend.ET.parse(path).getroot()
            path_count = sum(1 for n in root.iter() if backend.tag_name(n.tag).lower() == "path")
            self.assertGreater(path_count, 0)
            items = backend.extract_polylines(path)
            bounds = backend.bounds_path_items(items)
            self.assertIsNotNone(bounds)
            assert bounds is not None
            self.assertGreater(bounds[1] - bounds[0], 5.0)
            self.assertGreater(bounds[3] - bounds[2], 2.0)

    def test_replace_svg_text_with_svg_stroke_fonts_respects_group_transform(self) -> None:
        svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="60mm">
  <g transform="translate(30,15)">
    <text x="10" y="20" style="font-size:12px;fill:#000000">AB</text>
  </g>
</svg>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stroke_transform.svg"
            path.write_text(svg, encoding="utf-8")
            changed = backend.replace_svg_text_with_svg_stroke_fonts(path, "Segoe Script", logger=lambda *_: None)
            self.assertEqual(changed, 1)
            items = backend.extract_polylines(path)
            bounds = backend.bounds_path_items(items)
            self.assertIsNotNone(bounds)
            assert bounds is not None
            self.assertGreater(bounds[0], 30.0)
            self.assertGreater(bounds[2], 10.0)

    def test_postprocess_singleline_text_polylines_keeps_geometry(self) -> None:
        src = [
            [(0.0, 0.0), (1.0, 0.05), (2.0, 0.0)],
            [(2.04, 0.01), (3.0, 0.05), (4.0, 0.02)],
        ]
        out = backend._postprocess_singleline_text_polylines(src, font_size=12.0, logger=None)
        self.assertGreaterEqual(len(out), 1)
        self.assertTrue(all(len(poly) >= 2 for poly in out))

    def test_simplify_polyline_allows_collinear_override(self) -> None:
        src = [(0.0, 0.0), (1.0, 0.03), (2.0, 0.0)]
        old_col = backend.POLYLINE_COLLINEAR_EPS
        try:
            backend.POLYLINE_COLLINEAR_EPS = 0.4
            default_simplified = backend.simplify_polyline(src)
            strict_simplified = backend.simplify_polyline(src, collinear_eps=0.001)
            self.assertEqual(len(default_simplified), 2)
            self.assertEqual(len(strict_simplified), 3)
        finally:
            backend.POLYLINE_COLLINEAR_EPS = old_col

    def test_split_text_tokens_keep_spaces_preserves_whitespace(self) -> None:
        tokens = backend._split_text_tokens_keep_spaces("Привет  мир\tEN")
        self.assertEqual(tokens, ["Привет", "  ", "мир", "\t", "EN"])


    def test_reorder_line_lr_goes_top_to_bottom_then_left_to_right(self) -> None:
        old_mode = backend.DRAW_ORDER_MODE
        old_reorder = backend.REORDER_ENABLED
        old_tol = backend.DRAW_ORDER_LINE_TOL_MM
        try:
            backend.DRAW_ORDER_MODE = "line_lr"
            backend.REORDER_ENABLED = True
            backend.DRAW_ORDER_LINE_TOL_MM = 3.0
            polylines = [
                [(40.0, -100.0), (50.0, -100.0)],  # bottom-right
                [(10.0, -100.0), (20.0, -100.0)],  # bottom-left
                [(35.0, -120.0), (45.0, -120.0)],  # top-right
                [(5.0, -120.0), (15.0, -120.0)],   # top-left
            ]
            out = backend.reorder_polylines(polylines, logger=lambda *_: None)
            self.assertEqual(len(out), 4)
            starts = [poly[0] for poly in out]
            self.assertEqual(starts[0], (5.0, -120.0))
            self.assertEqual(starts[1], (35.0, -120.0))
            self.assertEqual(starts[2], (10.0, -100.0))
            self.assertEqual(starts[3], (40.0, -100.0))
        finally:
            backend.DRAW_ORDER_MODE = old_mode
            backend.REORDER_ENABLED = old_reorder
            backend.DRAW_ORDER_LINE_TOL_MM = old_tol


if __name__ == "__main__":
    unittest.main()
