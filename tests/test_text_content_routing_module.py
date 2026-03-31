from __future__ import annotations

import unittest

from src.plotter_backend import text_content_routing


class TextContentRoutingModuleTests(unittest.TestCase):
    def test_classify_caption_role(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "\u0422\u0430\u0431\u043b\u0438\u0446\u0430 1.1",
            font_size=11.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_PRINT_CAPTION)

    def test_classify_table_row_role(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "J0 E1 E2 E3 E4 G0 R1 R2 R3 R4 R5 R6",
            font_size=10.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_PRINT_TABLE)

    def test_classify_short_tech_role(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "R12",
            font_size=9.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_PRINT_SHORT_TECH)

    def test_classify_formula_role(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "I=U/R",
            font_size=10.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_PRINT_FORMULA)

    def test_wrapped_prose_with_hyphen_is_not_formula(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "\u0421\u0445\u0435\u043c\u0430 \u0446\u0435\u043f\u0438 \u043f\u043e-",
            font_size=12.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_BODY_HANDWRITING)

    def test_unit_token_prefers_print_role(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "Ohm",
            font_size=12.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_PRINT_SHORT_TECH)

    def test_decimal_token_prefers_print_role(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "0.4",
            font_size=12.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_PRINT_SHORT_TECH)

    def test_classify_body_role(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "\u0421\u043e\u0441\u0442\u0430\u0432\u0438\u043c \u0441\u0438\u0441\u0442\u0435\u043c\u0443 \u0443\u0440\u0430\u0432\u043d\u0435\u043d\u0438\u0439",
            font_size=12.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_BODY_HANDWRITING)


if __name__ == "__main__":
    unittest.main()
