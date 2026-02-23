from __future__ import annotations

import unittest

from pathlib import Path

from plotter_studio.core import protocol


class RenderModeProfileTests(unittest.TestCase):
    def test_normalize_render_mode_defaults_to_drawing(self) -> None:
        self.assertEqual(protocol.normalize_render_mode("drawing"), "drawing")
        self.assertEqual(protocol.normalize_render_mode("handwriting"), "handwriting")
        self.assertEqual(protocol.normalize_render_mode("AUTO"), "drawing")
        self.assertEqual(protocol.normalize_render_mode(""), "drawing")

    def test_resolve_render_flags_for_drawing(self) -> None:
        mode, exact, handwriting = protocol.resolve_render_flags(
            "drawing",
            exact_geometry_mode=False,
            handwriting_enabled=True,
        )
        self.assertEqual(mode, "drawing")
        self.assertTrue(exact)
        self.assertFalse(handwriting)

    def test_resolve_render_flags_for_handwriting(self) -> None:
        mode, exact, handwriting = protocol.resolve_render_flags(
            "handwriting",
            exact_geometry_mode=True,
            handwriting_enabled=False,
        )
        self.assertEqual(mode, "handwriting")
        self.assertFalse(exact)
        self.assertTrue(handwriting)

    def test_select_cyrillic_handwriting_font_accepts_explicit_ttf(self) -> None:
        class _Backend:
            @staticmethod
            def _resolve_handwriting_ttf_path(_name: str):
                return None

        chosen = protocol._select_cyrillic_handwriting_font(_Backend(), r"C:\fonts\custom.ttf")
        self.assertEqual(chosen, r"C:\fonts\custom.ttf")

    def test_select_cyrillic_handwriting_font_uses_resolved_name(self) -> None:
        class _Backend:
            @staticmethod
            def _resolve_handwriting_ttf_path(name: str):
                if name == "ofont.ru_Veles.ttf":
                    return Path("ofont.ru_Veles.ttf")
                return None

        chosen = protocol._select_cyrillic_handwriting_font(_Backend(), "ofont.ru_Veles.ttf")
        self.assertEqual(chosen, "ofont.ru_Veles.ttf")

    def test_select_cyrillic_handwriting_font_falls_back_for_unknown_name(self) -> None:
        class _Backend:
            @staticmethod
            def _resolve_handwriting_ttf_path(_name: str):
                return None

        chosen = protocol._select_cyrillic_handwriting_font(_Backend(), "Unknown Fancy Script")
        self.assertEqual(chosen, "Marck Script")

    def test_order_polylines_line_lr_orders_top_to_bottom_left_to_right(self) -> None:
        polys = [
            [(40.0, 8.0), (30.0, 8.0)],   # row 2, right->left (should be reversed)
            [(5.0, 4.0), (15.0, 4.0)],    # row 1, left->right
            [(22.0, 4.1), (28.0, 4.1)],   # row 1, to the right of first
        ]
        out = protocol.BackendBridge._order_polylines_line_lr(polys, row_tol_mm=1.0)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0][0], (5.0, 4.0))
        self.assertEqual(out[1][0], (22.0, 4.1))
        self.assertEqual(out[2][0], (30.0, 8.0))
        self.assertEqual(out[2][-1], (40.0, 8.0))


if __name__ == "__main__":
    unittest.main()
