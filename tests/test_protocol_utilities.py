from __future__ import annotations

import unittest

from plotter_studio.core import protocol


class ProtocolUtilitiesTests(unittest.TestCase):
    def test_normalize_render_mode_defaults_to_drawing(self) -> None:
        self.assertEqual(protocol.normalize_render_mode(None), "drawing")
        self.assertEqual(protocol.normalize_render_mode("unknown"), "drawing")
        self.assertEqual(protocol.normalize_render_mode("handwriting"), "handwriting")

    def test_resolve_render_flags_for_handwriting_mode(self) -> None:
        mode, exact_geometry, handwriting = protocol.resolve_render_flags(
            "handwriting",
            exact_geometry_mode=True,
            handwriting_enabled=False,
        )
        self.assertEqual(mode, "handwriting")
        self.assertFalse(exact_geometry)
        self.assertTrue(handwriting)

    def test_looks_like_font_file_spec(self) -> None:
        self.assertTrue(protocol._looks_like_font_file_spec("C:/fonts/test.ttf"))  # type: ignore[attr-defined]
        self.assertTrue(protocol._looks_like_font_file_spec("relative/path/font.otf"))  # type: ignore[attr-defined]
        self.assertFalse(protocol._looks_like_font_file_spec("Marck Script"))  # type: ignore[attr-defined]

    def test_resolve_formula_font_normalizes_file_path_to_stem(self) -> None:
        class _Backend:
            @staticmethod
            def _normalize_word_font_name(name: str, default: str = "") -> str:
                return name or default

        logs: list[str] = []
        resolved = protocol._resolve_formula_font(  # type: ignore[attr-defined]
            _Backend(),
            "C:/fonts/ofont.ru_Times_New_Roman.ttf",
            logs.append,
        )
        self.assertEqual(resolved, "Times_New_Roman")
        self.assertTrue(any("normalized from file path" in line for line in logs))

    def test_split_comment_and_parse_words(self) -> None:
        body = protocol._split_comment("G1 X10.5 Y-2.0 ; hi")  # type: ignore[attr-defined]
        self.assertEqual(body, "G1 X10.5 Y-2.0")
        words = protocol._parse_words("G1 X10.5 Y-2.0 F1000 Afoo")  # type: ignore[attr-defined]
        self.assertEqual(words.get("X"), 10.5)
        self.assertEqual(words.get("Y"), -2.0)
        self.assertEqual(words.get("F"), 1000.0)
        self.assertNotIn("A", words)

    def test_split_comment_preserves_words_after_parenthetical_comment(self) -> None:
        body = protocol._split_comment("G1 X10 (ignore X99) Y-2 ; tail")  # type: ignore[attr-defined]

        words = protocol._parse_words(body)  # type: ignore[attr-defined]

        self.assertEqual(words.get("X"), 10.0)
        self.assertEqual(words.get("Y"), -2.0)

    def test_parse_words_handles_compact_grbl_words(self) -> None:
        words = protocol._parse_words("G1X10.5Y-2.0F1.2e3M3S1000")  # type: ignore[attr-defined]
        self.assertEqual(words.get("X"), 10.5)
        self.assertEqual(words.get("Y"), -2.0)
        self.assertEqual(words.get("F"), 1200.0)
        self.assertEqual(words.get("S"), 1000.0)
        self.assertNotIn("G", words)
        self.assertNotIn("M", words)

    def test_arc_points_returns_points_ending_at_target(self) -> None:
        points = protocol._arc_points(  # type: ignore[attr-defined]
            (1.0, 0.0),
            (0.0, 1.0),
            (0.0, 0.0),
            cw=False,
            step_deg=30.0,
        )
        self.assertTrue(points)
        self.assertAlmostEqual(points[-1][0], 0.0, places=6)
        self.assertAlmostEqual(points[-1][1], 1.0, places=6)

    def test_prune_short_polyline_segments_removes_micro_steps(self) -> None:
        poly = [(0.0, 0.0), (0.03, 0.0), (0.06, 0.0), (1.0, 0.0)]
        out = protocol._prune_short_polyline_segments(  # type: ignore[attr-defined]
            poly,
            min_seg_mm=0.08,
        )
        self.assertTrue(out)
        self.assertEqual(out[0], (0.0, 0.0))
        self.assertEqual(out[-1], (1.0, 0.0))
        self.assertLess(len(out), len(poly))

    def test_gcode_to_polylines_supports_spindle_pen_control(self) -> None:
        lines = [
            "G90",
            "G0 X0 Y0",
            "M3",
            "G1 X10 Y0",
            "M5",
            "G0 X20 Y0",
        ]
        polys = protocol._gcode_to_polylines(lines, z_up=0.0, z_down=11.9)  # type: ignore[attr-defined]
        self.assertEqual(len(polys), 1)
        self.assertEqual(polys[0][0], (0.0, 0.0))
        self.assertEqual(polys[0][-1], (10.0, 0.0))

    def test_gcode_to_polylines_supports_compact_modal_spindle_gcode(self) -> None:
        lines = [
            "G90",
            "G0X0Y0",
            "M3S1000",
            "G1X10Y0",
            "X10Y5",
            "M5",
            "G0X20Y20",
        ]
        polys = protocol._gcode_to_polylines(lines, z_up=0.0, z_down=11.9)  # type: ignore[attr-defined]
        self.assertEqual(len(polys), 1)
        self.assertEqual(polys[0], [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)])

    def test_gcode_to_polylines_keeps_coordinates_after_parenthetical_comment(self) -> None:
        lines = [
            "G90",
            "G0 X0 Y0",
            "M3",
            "G1 X10 (inline note) Y-2",
            "M5",
        ]
        polys = protocol._gcode_to_polylines(lines, z_up=0.0, z_down=11.9)  # type: ignore[attr-defined]

        self.assertEqual(polys, [[(0.0, 0.0), (10.0, -2.0)]])

    def test_gcode_to_polylines_supports_arc_motion(self) -> None:
        lines = [
            "G90",
            "M3",
            "G0 X1 Y0",
            "G2 X0 Y-1 I-1 J0",
            "M5",
        ]
        polys = protocol._gcode_to_polylines(lines, z_up=0.0, z_down=11.9)  # type: ignore[attr-defined]
        self.assertEqual(len(polys), 1)
        self.assertGreaterEqual(len(polys[0]), 2)
        self.assertAlmostEqual(polys[0][-1][0], 0.0, places=6)
        self.assertAlmostEqual(polys[0][-1][1], -1.0, places=6)


if __name__ == "__main__":
    unittest.main()
