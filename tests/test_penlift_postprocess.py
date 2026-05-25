from __future__ import annotations

import re
import unittest

from src import penlift_postprocess as pp


class PenliftPostprocessTests(unittest.TestCase):
    @staticmethod
    def _touchdown_z(lines: list[str], touch_feed: float) -> list[float]:
        out: list[float] = []
        patt = re.compile(rf"^G1 Z(-?\d+(?:\.\d+)?) F{touch_feed:.1f}$")
        for line in lines:
            m = patt.match(line.strip())
            if not m:
                continue
            out.append(float(m.group(1)))
        return out

    def test_stroke_z_jitter_is_deterministic_and_varies_between_strokes(self) -> None:
        src = [
            "G21",
            "G90",
            "G0 X0 Y0",
            "G1 X10 Y0 F800",
            "G0 X20 Y0",
            "G1 X30 Y0 F800",
        ]
        out1 = pp.touch_pen_down(
            src,
            z_down=10.0,
            delay_down=0.0,
            z_up=0.0,
            mode="z",
            spindle_speed=1000.0,
            delay_up=0.0,
            z_feed_down_approach=700.0,
            z_feed_down_touch=123.0,
            z_feed_up=700.0,
            z_feed_up_final=220.0,
            z_soft_down_mm=0.8,
            z_soft_up_mm=0.5,
            z_travel_lift_mm=3.0,
            dynamic_z_enable=True,
            dynamic_base_z_down=10.0,
            dynamic_initial_wear_mm=0.0,
            dynamic_wear_mm_per_m=0.01,
            dynamic_z_comp_per_wear=1.0,
            dynamic_z_max_comp_mm=0.8,
            stroke_z_jitter_enable=True,
            stroke_z_jitter_mm=0.2,
            stroke_z_jitter_seed=7,
        )
        out2 = pp.touch_pen_down(
            src,
            z_down=10.0,
            delay_down=0.0,
            z_up=0.0,
            mode="z",
            spindle_speed=1000.0,
            delay_up=0.0,
            z_feed_down_approach=700.0,
            z_feed_down_touch=123.0,
            z_feed_up=700.0,
            z_feed_up_final=220.0,
            z_soft_down_mm=0.8,
            z_soft_up_mm=0.5,
            z_travel_lift_mm=3.0,
            dynamic_z_enable=True,
            dynamic_base_z_down=10.0,
            dynamic_initial_wear_mm=0.0,
            dynamic_wear_mm_per_m=0.01,
            dynamic_z_comp_per_wear=1.0,
            dynamic_z_max_comp_mm=0.8,
            stroke_z_jitter_enable=True,
            stroke_z_jitter_mm=0.2,
            stroke_z_jitter_seed=7,
        )

        self.assertEqual(out1, out2)
        z_vals = self._touchdown_z(out1, 123.0)
        self.assertGreaterEqual(len(z_vals), 2)
        self.assertNotAlmostEqual(z_vals[0], z_vals[1], places=6)

    def test_without_stroke_jitter_touchdown_is_constant(self) -> None:
        src = [
            "G21",
            "G90",
            "G0 X0 Y0",
            "G1 X10 Y0 F800",
            "G0 X20 Y0",
            "G1 X30 Y0 F800",
        ]
        out = pp.touch_pen_down(
            src,
            z_down=10.0,
            delay_down=0.0,
            z_up=0.0,
            mode="z",
            spindle_speed=1000.0,
            delay_up=0.0,
            z_feed_down_approach=700.0,
            z_feed_down_touch=123.0,
            z_feed_up=700.0,
            z_feed_up_final=220.0,
            z_soft_down_mm=0.8,
            z_soft_up_mm=0.5,
            z_travel_lift_mm=3.0,
            dynamic_z_enable=False,
            dynamic_base_z_down=10.0,
            dynamic_initial_wear_mm=0.0,
            dynamic_wear_mm_per_m=0.01,
            dynamic_z_comp_per_wear=1.0,
            dynamic_z_max_comp_mm=0.8,
            stroke_z_jitter_enable=False,
            stroke_z_jitter_mm=0.2,
            stroke_z_jitter_seed=7,
        )
        z_vals = self._touchdown_z(out, 123.0)
        self.assertGreaterEqual(len(z_vals), 2)
        self.assertAlmostEqual(z_vals[0], 10.0, places=6)
        self.assertAlmostEqual(z_vals[1], 10.0, places=6)

    def test_compact_gcode_gets_pen_lift_commands(self) -> None:
        src = [
            "G21",
            "G90",
            "G0X0Y0",
            "G1X10Y0F800",
            "G0X20Y0",
        ]

        out = pp.touch_pen_down(
            src,
            z_down=10.0,
            delay_down=0.0,
            z_up=0.0,
            mode="z",
            spindle_speed=1000.0,
            delay_up=0.0,
            z_feed_down_approach=700.0,
            z_feed_down_touch=123.0,
            z_feed_up=700.0,
            z_feed_up_final=220.0,
            z_soft_down_mm=0.8,
            z_soft_up_mm=0.5,
            z_travel_lift_mm=3.0,
        )

        self.assertIn("G1 Z10.0000 F123.0", out)
        self.assertTrue(any(line.strip() == "G1X10Y0F800" for line in out))
        self.assertTrue(any(line.strip() == "G1 Z7.0000 F220.0" for line in out))

    def test_zero_padded_g01_is_treated_as_draw_move(self) -> None:
        src = [
            "G21",
            "G90",
            "G0X0Y0",
            "G01X10Y0F800",
        ]

        out = pp.touch_pen_down(
            src,
            z_down=10.0,
            delay_down=0.0,
            z_up=0.0,
            mode="z",
            spindle_speed=1000.0,
            delay_up=0.0,
            z_feed_down_approach=700.0,
            z_feed_down_touch=123.0,
            z_feed_up=700.0,
            z_feed_up_final=220.0,
            z_soft_down_mm=0.8,
            z_soft_up_mm=0.5,
            z_travel_lift_mm=3.0,
        )

        self.assertIn("G1 Z10.0000 F123.0", out)

    def test_modal_and_motion_gcodes_on_same_line_are_both_processed(self) -> None:
        src = [
            "G21",
            "G90 G0 X0 Y0",
            "G90 G1 X10 Y0 F800",
        ]

        out = pp.touch_pen_down(
            src,
            z_down=10.0,
            delay_down=0.0,
            z_up=0.0,
            mode="z",
            spindle_speed=1000.0,
            delay_up=0.0,
            z_feed_down_approach=700.0,
            z_feed_down_touch=123.0,
            z_feed_up=700.0,
            z_feed_up_final=220.0,
            z_soft_down_mm=0.8,
            z_soft_up_mm=0.5,
            z_travel_lift_mm=3.0,
        )

        self.assertIn("G1 Z10.0000 F123.0", out)
        self.assertTrue(any(line.strip() == "G90 G1 X10 Y0 F800" for line in out))

    def test_merge_short_travel_keeps_single_stroke(self) -> None:
        src = [
            "G21",
            "G90",
            "G0 X0 Y0",
            "G1 X10 Y0 F800",
            "G0 X10.15 Y0.10",
            "G1 X20 Y0 F800",
        ]
        out = pp.touch_pen_down(
            src,
            z_down=10.0,
            delay_down=0.0,
            z_up=0.0,
            mode="z",
            spindle_speed=1000.0,
            delay_up=0.0,
            z_feed_down_approach=700.0,
            z_feed_down_touch=123.0,
            z_feed_up=700.0,
            z_feed_up_final=220.0,
            z_soft_down_mm=0.8,
            z_soft_up_mm=0.5,
            z_travel_lift_mm=3.0,
            dynamic_z_enable=False,
            dynamic_base_z_down=10.0,
            dynamic_initial_wear_mm=0.0,
            dynamic_wear_mm_per_m=0.01,
            dynamic_z_comp_per_wear=1.0,
            dynamic_z_max_comp_mm=0.8,
            stroke_z_jitter_enable=False,
            stroke_z_jitter_mm=0.0,
            stroke_z_jitter_seed=7,
            merge_short_travel_enable=True,
            merge_short_travel_mm=0.3,
            merge_short_travel_feed=2000.0,
        )
        z_vals = self._touchdown_z(out, 123.0)
        self.assertEqual(len(z_vals), 1)
        self.assertTrue(any(line.strip().startswith("G1 X10.15 Y0.10 F2000.0") for line in out))

    def test_dynamic_z_uses_absolute_ijk_arc_length(self) -> None:
        src = [
            "G21",
            "G90",
            "G90.1",
            "G0 X10 Y0",
            "G3 X0 Y10 I0 J0 F800",
            "G0 X20 Y0",
            "G1 X21 Y0 F800",
        ]

        out = pp.touch_pen_down(
            src,
            z_down=10.0,
            delay_down=0.0,
            z_up=0.0,
            mode="z",
            spindle_speed=1000.0,
            delay_up=0.0,
            z_feed_down_approach=700.0,
            z_feed_down_touch=123.0,
            z_feed_up=700.0,
            z_feed_up_final=220.0,
            z_soft_down_mm=0.8,
            z_soft_up_mm=0.5,
            z_travel_lift_mm=3.0,
            dynamic_z_enable=True,
            dynamic_base_z_down=10.0,
            dynamic_initial_wear_mm=0.0,
            dynamic_wear_mm_per_m=100.0,
            dynamic_z_comp_per_wear=1.0,
            dynamic_z_max_comp_mm=10.0,
            stroke_z_jitter_enable=False,
            stroke_z_jitter_mm=0.0,
            stroke_z_jitter_seed=7,
        )

        z_vals = self._touchdown_z(out, 123.0)
        self.assertGreaterEqual(len(z_vals), 2)
        self.assertAlmostEqual(z_vals[0], 10.0, places=4)
        self.assertAlmostEqual(z_vals[1], 11.5708, places=4)


if __name__ == "__main__":
    unittest.main()
