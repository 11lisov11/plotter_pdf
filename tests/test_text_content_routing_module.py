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

    def test_math_font_forces_formula_role(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "q1 q2",
            font_size=10.0,
            font_names=["Cambria Math"],
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

    def test_figure_reference_sentence_is_not_caption(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "\u0421\u0445\u0435\u043c\u0430 \u043f\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u0430 \u043d\u0430 \u0440\u0438\u0441.2.1",
            font_size=11.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_BODY_HANDWRITING)

    def test_sentence_with_figure_reference_is_not_table(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "\u0441\u0442\u043e\u044f\u043d\u043d\u043e\u0433\u043e \u0442\u043e\u043a\u0430 \u043f\u0440\u0438\u0432\u0435\u0434\u0435\u043d\u0430 \u043d\u0430 \u0440\u0438\u0441 1.1.",
            font_size=12.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_BODY_HANDWRITING)

    def test_uppercase_instruction_line_is_not_formula(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "\u0420\u0410\u0421\u0421\u0427\u0418\u0422\u0410\u0422\u042c \u0422\u041e\u041a\u0418 \u0412\u041e \u0412\u0421\u0415\u0425 \u0412\u0415\u0422\u0412\u042f\u0425 \u041f\u041e \u041f\u0415\u0420\u0412\u041e\u041c\u0423-\u0412\u0422\u041e\u0420\u041e\u041c\u0423 \u0417\u0410\u041a\u041e\u041d\u0423",
            font_size=11.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_BODY_HANDWRITING)

    def test_numbered_uppercase_instruction_is_not_table(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "1. \u0420\u0410\u0421\u0421\u0427\u0418\u0422\u0410\u0422\u042c \u0422\u041e\u041a\u0418 \u0412\u041e \u0412\u0421\u0415\u0425 \u0412\u0415\u0422\u0412\u042f\u0425 \u041f\u0420\u0418\u0415\u041c\u041d\u0418\u041a\u0410",
            font_size=12.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_BODY_HANDWRITING)

    def test_numbered_instruction_with_device_units_is_not_table(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "3. \u041e\u041f\u0420\u0415\u0414\u0415\u041b\u0418\u0422\u042c \u041f\u041e\u041a\u0410\u0417\u0410\u041d\u0418\u042f \u041f\u0420\u0418\u0411\u041e\u0420\u041e\u0412: \u0410\u041c\u041f\u0415\u0420\u041c\u0415\u0422\u0420\u0410 \u0410, \u0412\u041e\u041b\u042c\u0422\u041c\u0415\u0422\u0420\u0410 V \u0418",
            font_size=12.0,
            text_contains_formula_script_fn=lambda text: False,
        )
        self.assertEqual(role, text_content_routing.ROLE_BODY_HANDWRITING)

    def test_uppercase_requirement_sentence_is_not_table(self) -> None:
        role = text_content_routing.classify_text_content_role(
            "\u0412\u042c\u0415\u0412 \u0418 \u0414\u041e\u041f\u041e\u041b\u041d\u0415\u041d\u0418\u0419 \u0414\u041e\u041b\u0416\u041d\u041e \u0411\u042b\u0422\u042c \u041d\u0415 \u041c\u0415\u041d\u0415\u0415 \u041a\u041e\u041b\u0418\u0427\u0415\u0421\u0422\u0412\u0410 \u0423\u0417\u041b\u041e\u0412",
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

    def test_title_block_designations_prefer_print_role(self) -> None:
        for text in ("МЧ00.19.00.08", "КНГ.09.01.02", "МЧ00 19 00 07", "ЭТ-520-3"):
            with self.subTest(text=text):
                role = text_content_routing.classify_text_content_role(
                    text,
                    font_size=10.0,
                    text_contains_formula_script_fn=lambda value: False,
                )
                self.assertEqual(role, text_content_routing.ROLE_PRINT_SHORT_TECH)

    def test_title_block_labels_prefer_print_role(self) -> None:
        for text in ("ПГУПС", "Изм.", "№ докум.", "Подп.", "Дата", "Масштаб", "Листов"):
            with self.subTest(text=text):
                role = text_content_routing.classify_text_content_role(
                    text,
                    font_size=8.0,
                    text_contains_formula_script_fn=lambda value: False,
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
