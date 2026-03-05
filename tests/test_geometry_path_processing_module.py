from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import List, Tuple

from src.plotter_backend.geometry import clipping, polyline, simplify
from src.plotter_backend.geometry import path_processing


@dataclass
class _Item:
    points: List[Tuple[float, float]] = field(default_factory=list)
    closed: bool = False
    is_stroke: bool = True
    is_fill: bool = False


def _bounds_polylines(polylines: List[List[Tuple[float, float]]]) -> Tuple[float, float, float, float]:
    points = [p for poly in polylines for p in poly]
    return (
        min(p[0] for p in points),
        max(p[0] for p in points),
        min(p[1] for p in points),
        max(p[1] for p in points),
    )


def _is_axis_aligned_rectangle(poly: List[Tuple[float, float]]) -> bool:
    if len(poly) < 4:
        return False
    pts = list(poly)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) != 4:
        return False
    xs = sorted({round(p[0], 6) for p in pts})
    ys = sorted({round(p[1], 6) for p in pts})
    return len(xs) == 2 and len(ys) == 2


class PathProcessingModuleTests(unittest.TestCase):
    def test_bounds_path_items_returns_none_for_empty_input(self) -> None:
        self.assertIsNone(path_processing.bounds_path_items([]))

    def test_bounds_path_items_returns_expected_bbox(self) -> None:
        items = [
            _Item(points=[(1.0, 2.0), (4.0, -1.0)]),
            _Item(points=[(-3.0, 5.0), (2.0, 3.0)]),
        ]
        self.assertEqual(path_processing.bounds_path_items(items), (-3.0, 4.0, -1.0, 5.0))

    def test_poly_inside_bbox_respects_tolerance(self) -> None:
        poly = [(0.0, 0.0), (10.0, 5.0)]
        self.assertTrue(path_processing.poly_inside_bbox(poly, 0.0, 10.0, 0.0, 5.0, eps=0.0))
        self.assertTrue(path_processing.poly_inside_bbox(poly, 0.1, 9.9, 0.1, 4.9, eps=0.2))
        self.assertFalse(path_processing.poly_inside_bbox(poly, 0.1, 9.9, 0.1, 4.9, eps=0.05))

    def test_normalize_path_units_to_page_scales_points(self) -> None:
        items = [_Item(points=[(0.0, 0.0), (200.0, 100.0)])]
        logs: List[str] = []
        out, scale = path_processing.normalize_path_units_to_page(
            items,
            page_w_mm=100.0,
            page_h_mm=50.0,
            logger=logs.append,
        )
        self.assertIs(out, items)
        self.assertAlmostEqual(scale, 0.5, places=6)
        self.assertEqual(items[0].points[0], (0.0, 0.0))
        self.assertAlmostEqual(items[0].points[1][0], 100.0, places=6)
        self.assertAlmostEqual(items[0].points[1][1], 50.0, places=6)
        self.assertTrue(any("Normalized SVG units" in msg for msg in logs))

    def test_normalize_path_units_to_page_keeps_original_on_nonuniform_ratio(self) -> None:
        items = [_Item(points=[(0.0, 0.0), (220.0, 60.0)])]
        _, scale = path_processing.normalize_path_units_to_page(
            items,
            page_w_mm=100.0,
            page_h_mm=50.0,
            logger=None,
        )
        self.assertEqual(scale, 1.0)
        self.assertEqual(items[0].points, [(0.0, 0.0), (220.0, 60.0)])

    def test_filter_outer_frame_path_items_picks_closed_outer_rectangle(self) -> None:
        outer = _Item(
            points=[(0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0), (0.0, 0.0)],
            closed=True,
            is_stroke=True,
        )
        inner = _Item(
            points=[(20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 30.0), (20.0, 20.0)],
            closed=True,
            is_stroke=True,
        )
        kept, frames = path_processing.filter_outer_frame_path_items(
            [outer, inner],
            auto_trim_outer_frame=True,
            outer_frame_edge_eps_mm=0.5,
            outer_frame_side_ratio=0.80,
            outer_frame_min_fill_ratio=0.70,
            outer_frame_cover_ratio=0.97,
            bounds_polylines_fn=_bounds_polylines,
            is_axis_aligned_rectangle_fn=_is_axis_aligned_rectangle,
            logger=None,
        )
        self.assertEqual(frames, [outer])
        self.assertEqual(kept, [inner])

    def test_filter_outer_frame_path_items_fallback_separate_lines(self) -> None:
        left = _Item(points=[(0.0, 0.0), (0.0, 80.0)], closed=False, is_stroke=True)
        right = _Item(points=[(100.0, 0.0), (100.0, 80.0)], closed=False, is_stroke=True)
        bottom = _Item(points=[(0.0, 0.0), (100.0, 0.0)], closed=False, is_stroke=True)
        top = _Item(points=[(0.0, 80.0), (100.0, 80.0)], closed=False, is_stroke=True)
        inner = _Item(points=[(20.0, 20.0), (30.0, 30.0)], closed=False, is_stroke=True)
        kept, frames = path_processing.filter_outer_frame_path_items(
            [left, right, bottom, top, inner],
            auto_trim_outer_frame=True,
            outer_frame_edge_eps_mm=0.5,
            outer_frame_side_ratio=0.80,
            outer_frame_min_fill_ratio=0.70,
            outer_frame_cover_ratio=0.97,
            bounds_polylines_fn=_bounds_polylines,
            is_axis_aligned_rectangle_fn=_is_axis_aligned_rectangle,
            logger=None,
        )
        self.assertEqual(len(frames), 4)
        self.assertEqual(kept, [inner])

    def test_clip_path_items_to_rect_clips_polyline_inside_window(self) -> None:
        src = _Item(points=[(-5.0, 0.0), (5.0, 0.0), (15.0, 0.0)], closed=False, is_stroke=True)

        def _factory(points: List[Tuple[float, float]], source_item: _Item, closed: bool) -> _Item:
            return _Item(
                points=list(points),
                closed=closed,
                is_stroke=source_item.is_stroke,
                is_fill=source_item.is_fill,
            )

        clipped_items, written, dropped = path_processing.clip_path_items_to_rect(
            [src],
            min_x=0.0,
            max_x=10.0,
            min_y=-1.0,
            max_y=1.0,
            clip_segment_to_rect_fn=clipping.clip_segment_to_rect,
            clamp_to_rect_fn=clipping.clamp_to_rect,
            point_in_rect_fn=clipping.point_in_rect,
            points_distance_fn=polyline.points_distance,
            path_is_closed_fn=simplify.path_is_closed,
            item_factory=_factory,
            clip_continuity_eps_mm=0.2,
            logger=None,
        )

        self.assertEqual(dropped, 0)
        self.assertEqual(written, 2)
        self.assertEqual(len(clipped_items), 1)
        self.assertEqual(clipped_items[0].points, [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])

    def test_clip_path_items_to_rect_drops_fully_outside_segment(self) -> None:
        src = _Item(points=[(-5.0, 0.0), (-1.0, 0.0), (5.0, 0.0)], closed=False, is_stroke=True)

        def _factory(points: List[Tuple[float, float]], source_item: _Item, closed: bool) -> _Item:
            return _Item(
                points=list(points),
                closed=closed,
                is_stroke=source_item.is_stroke,
                is_fill=source_item.is_fill,
            )

        clipped_items, written, dropped = path_processing.clip_path_items_to_rect(
            [src],
            min_x=0.0,
            max_x=10.0,
            min_y=-1.0,
            max_y=1.0,
            clip_segment_to_rect_fn=clipping.clip_segment_to_rect,
            clamp_to_rect_fn=clipping.clamp_to_rect,
            point_in_rect_fn=clipping.point_in_rect,
            points_distance_fn=polyline.points_distance,
            path_is_closed_fn=simplify.path_is_closed,
            item_factory=_factory,
            clip_continuity_eps_mm=0.2,
            logger=None,
        )

        self.assertEqual(dropped, 1)
        self.assertEqual(written, 1)
        self.assertEqual(len(clipped_items), 1)
        self.assertEqual(clipped_items[0].points, [(0.0, 0.0), (5.0, 0.0)])

    def test_clip_to_content_area_skips_when_disabled(self) -> None:
        items = [_Item(points=[(0.0, 0.0), (10.0, 10.0)])]
        out, applied = path_processing.clip_to_content_area(
            items,
            page_w=210.0,
            page_h=297.0,
            page_margin_enabled=False,
            page_margin_left_mm=20.0,
            page_margin_right_mm=5.0,
            page_margin_top_mm=10.0,
            page_margin_bottom_mm=5.0,
            page_margin_a4_only=False,
            page_a4_tol_mm=2.0,
            clip_path_items_to_rect_fn=lambda *_: (_ for _ in ()).throw(AssertionError("must not be called")),
            logger=None,
        )
        self.assertIs(out, items)
        self.assertFalse(applied)

    def test_clip_to_content_area_skips_non_a4_when_a4_only(self) -> None:
        items = [_Item(points=[(0.0, 0.0), (10.0, 10.0)])]
        out, applied = path_processing.clip_to_content_area(
            items,
            page_w=100.0,
            page_h=100.0,
            page_margin_enabled=True,
            page_margin_left_mm=20.0,
            page_margin_right_mm=5.0,
            page_margin_top_mm=10.0,
            page_margin_bottom_mm=5.0,
            page_margin_a4_only=True,
            page_a4_tol_mm=2.0,
            clip_path_items_to_rect_fn=lambda *_: (_ for _ in ()).throw(AssertionError("must not be called")),
            logger=None,
        )
        self.assertIs(out, items)
        self.assertFalse(applied)

    def test_clip_to_content_area_applies_and_returns_clipped(self) -> None:
        items = [_Item(points=[(0.0, 0.0), (210.0, 297.0)])]
        clipped = [_Item(points=[(20.0, 10.0), (205.0, 292.0)])]
        calls: List[Tuple[float, float, float, float]] = []

        def _clip_cb(src_items: List[_Item], x0: float, x1: float, y0: float, y1: float) -> Tuple[List[_Item], int, int]:
            self.assertIs(src_items, items)
            calls.append((x0, x1, y0, y1))
            return clipped, 1, 0

        out, applied = path_processing.clip_to_content_area(
            items,
            page_w=210.0,
            page_h=297.0,
            page_margin_enabled=True,
            page_margin_left_mm=20.0,
            page_margin_right_mm=5.0,
            page_margin_top_mm=10.0,
            page_margin_bottom_mm=5.0,
            page_margin_a4_only=True,
            page_a4_tol_mm=2.0,
            clip_path_items_to_rect_fn=_clip_cb,
            logger=None,
        )

        self.assertTrue(applied)
        self.assertIs(out, clipped)
        self.assertEqual(calls, [(20.0, 205.0, 10.0, 292.0)])

    def test_clip_to_content_area_keeps_original_when_clip_result_empty(self) -> None:
        items = [_Item(points=[(0.0, 0.0), (210.0, 297.0)])]
        out, applied = path_processing.clip_to_content_area(
            items,
            page_w=210.0,
            page_h=297.0,
            page_margin_enabled=True,
            page_margin_left_mm=20.0,
            page_margin_right_mm=5.0,
            page_margin_top_mm=10.0,
            page_margin_bottom_mm=5.0,
            page_margin_a4_only=False,
            page_a4_tol_mm=2.0,
            clip_path_items_to_rect_fn=lambda *_: ([], 0, 5),
            logger=None,
        )
        self.assertIs(out, items)
        self.assertFalse(applied)


if __name__ == "__main__":
    unittest.main()
