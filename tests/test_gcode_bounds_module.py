from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.plotter_backend.gcode import bounds as gcode_bounds


class GcodeBoundsModuleTests(unittest.TestCase):
    def test_strip_gcode_comments_removes_semicolon_and_parentheses(self) -> None:
        line = "G1 X10 Y20 ; comment (inner)"
        self.assertEqual(gcode_bounds.strip_gcode_comments(line), "G1 X10 Y20")

    def test_pen_down_from_z_level_handles_normal_z_direction(self) -> None:
        self.assertTrue(gcode_bounds.pen_down_from_z_level(11.8, 0.0, 11.9))
        self.assertFalse(gcode_bounds.pen_down_from_z_level(0.2, 0.0, 11.9))

    def test_gcode_draw_bounds_tracks_pen_down_segments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_bounds_mod_") as td:
            gcode = Path(td) / "sample.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0 X0 Y0",
                        "M3",
                        "G1 X10 Y0",
                        "M5",
                        "G0 X50 Y50",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            bounds = gcode_bounds.gcode_draw_bounds(
                gcode,
                z_up=0.0,
                z_down=11.9,
                points_distance=lambda _a, _b: 1.0,
                arc_extents_xy=lambda *_args, **_kwargs: (0.0, 0.0, 0.0, 0.0),
            )

            self.assertEqual(bounds, (0.0, 10.0, 0.0, 0.0))

    def test_gcode_draw_bounds_handles_compact_and_modal_xy_moves(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_bounds_compact_") as td:
            gcode = Path(td) / "compact.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "G0X0Y0",
                        "M3",
                        "G1X10Y0",
                        "X12Y-2",
                        "M5",
                        "G0X50Y50",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            bounds = gcode_bounds.gcode_draw_bounds(
                gcode,
                z_up=0.0,
                z_down=11.9,
                points_distance=lambda _a, _b: 1.0,
                arc_extents_xy=lambda *_args, **_kwargs: (0.0, 0.0, 0.0, 0.0),
            )

            self.assertEqual(bounds, (0.0, 12.0, -2.0, 0.0))

    def test_gcode_draw_bounds_uses_arc_extents_for_arc_motion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_bounds_arc_") as td:
            gcode = Path(td) / "arc.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "M3",
                        "G0 X0 Y0",
                        "G2 X10 Y0 I5 J0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            arc_extents = mock.Mock(return_value=(-2.0, 12.0, -3.0, 4.0))
            bounds = gcode_bounds.gcode_draw_bounds(
                gcode,
                z_up=0.0,
                z_down=11.9,
                points_distance=lambda _a, _b: 1.0,
                arc_extents_xy=arc_extents,
            )

            self.assertEqual(bounds, (-2.0, 12.0, -3.0, 4.0))
            arc_extents.assert_called_once()

    def test_gcode_draw_bounds_full_circle_arc_uses_radius_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_bounds_circle_") as td:
            gcode = Path(td) / "circle.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G21",
                        "G90",
                        "M3",
                        "G0 X0 Y0",
                        "G2 X0 Y0 I5 J0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            bounds = gcode_bounds.gcode_draw_bounds(
                gcode,
                z_up=0.0,
                z_down=11.9,
                points_distance=lambda _a, _b: 0.0,
                arc_extents_xy=lambda *_args, **_kwargs: (-999.0, 999.0, -999.0, 999.0),
            )

            self.assertEqual(bounds, (0.0, 10.0, -5.0, 5.0))


if __name__ == "__main__":
    unittest.main()

