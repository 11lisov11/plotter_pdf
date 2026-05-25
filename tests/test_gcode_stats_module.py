from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.plotter_backend.gcode import stats as gcode_stats


class GcodeStatsModuleTests(unittest.TestCase):
    def test_summarize_gcode_file_returns_zero_bounds_for_empty_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_stats_empty_") as td:
            gcode = Path(td) / "empty.nc"
            gcode.write_text("", encoding="utf-8")

            summary = gcode_stats.summarize_gcode_file(
                gcode,
                points_distance=lambda _a, _b: 0.0,
                arc_extents_xy=lambda *_args, **_kwargs: (0.0, 0.0, 0.0, 0.0),
            )

            self.assertEqual(summary, (0, 0, 0, (0.0, 0.0, 0.0, 0.0)))

    def test_summarize_gcode_file_counts_draw_and_travel_moves(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_stats_moves_") as td:
            gcode = Path(td) / "moves.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "; comment",
                        "G21",
                        "G90",
                        "G0 X1 Y2",
                        "G1 X3 Y4",
                        "G0 X5 Y6",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            total, draw, travel, bounds = gcode_stats.summarize_gcode_file(
                gcode,
                points_distance=lambda _a, _b: 1.0,
                arc_extents_xy=lambda *_args, **_kwargs: (0.0, 0.0, 0.0, 0.0),
            )

            self.assertEqual(total, 5)
            self.assertEqual(draw, 1)
            self.assertEqual(travel, 2)
            self.assertEqual(bounds, (1.0, 5.0, 2.0, 6.0))

    def test_summarize_gcode_file_handles_compact_and_modal_xy_moves(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_stats_compact_") as td:
            gcode = Path(td) / "compact.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G90",
                        "G0X1Y2",
                        "G1X3Y4",
                        "X5Y6",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            total, draw, travel, bounds = gcode_stats.summarize_gcode_file(
                gcode,
                points_distance=lambda _a, _b: 1.0,
                arc_extents_xy=lambda *_args, **_kwargs: (0.0, 0.0, 0.0, 0.0),
            )

            self.assertEqual(total, 4)
            self.assertEqual(draw, 2)
            self.assertEqual(travel, 1)
            self.assertEqual(bounds, (1.0, 5.0, 2.0, 6.0))

    def test_summarize_gcode_file_respects_relative_xy_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_stats_relative_") as td:
            gcode = Path(td) / "relative.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G90",
                        "G0 X10 Y10",
                        "G91",
                        "G1 X2 Y-3",
                        "X1 Y1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            total, draw, travel, bounds = gcode_stats.summarize_gcode_file(
                gcode,
                points_distance=lambda _a, _b: 1.0,
                arc_extents_xy=lambda *_args, **_kwargs: (0.0, 0.0, 0.0, 0.0),
            )

            self.assertEqual(total, 5)
            self.assertEqual(draw, 2)
            self.assertEqual(travel, 1)
            self.assertEqual(bounds, (10.0, 13.0, 7.0, 10.0))

    def test_summarize_gcode_file_uses_arc_extents_for_arc_moves(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_stats_arc_") as td:
            gcode = Path(td) / "arc.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G90",
                        "G0 X0 Y0",
                        "G3 X10 Y0 I5 J0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            arc_extents = mock.Mock(return_value=(-1.0, 11.0, -2.0, 2.0))
            total, draw, travel, bounds = gcode_stats.summarize_gcode_file(
                gcode,
                points_distance=lambda _a, _b: 1.0,
                arc_extents_xy=arc_extents,
            )

            self.assertEqual(total, 3)
            self.assertEqual(draw, 1)
            self.assertEqual(travel, 1)
            self.assertEqual(bounds, (-1.0, 11.0, -2.0, 2.0))
            arc_extents.assert_called_once()

    def test_summarize_gcode_file_uses_arc_extents_for_r_word_arc_moves(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_stats_r_arc_") as td:
            gcode = Path(td) / "r_arc.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G90",
                        "G0 X10 Y0",
                        "G3 X0 Y10 R10",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            arc_extents = mock.Mock(return_value=(0.0, 10.0, 0.0, 10.0))
            total, draw, travel, bounds = gcode_stats.summarize_gcode_file(
                gcode,
                points_distance=lambda _a, _b: 1.0,
                arc_extents_xy=arc_extents,
            )

            self.assertEqual(total, 3)
            self.assertEqual(draw, 1)
            self.assertEqual(travel, 1)
            self.assertEqual(bounds, (0.0, 10.0, 0.0, 10.0))
            arc_extents.assert_called_once()

    def test_summarize_gcode_file_handles_full_circle_arc(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_gcode_stats_circle_") as td:
            gcode = Path(td) / "circle.nc"
            gcode.write_text(
                "\n".join(
                    [
                        "G90",
                        "G0 X0 Y0",
                        "G2 X0 Y0 I5 J0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            total, draw, travel, bounds = gcode_stats.summarize_gcode_file(
                gcode,
                points_distance=lambda _a, _b: 0.0,
                arc_extents_xy=lambda *_args, **_kwargs: (-999.0, 999.0, -999.0, 999.0),
            )

            self.assertEqual(total, 3)
            self.assertEqual(draw, 1)
            self.assertEqual(travel, 1)
            self.assertEqual(bounds, (0.0, 10.0, -5.0, 5.0))


if __name__ == "__main__":
    unittest.main()
