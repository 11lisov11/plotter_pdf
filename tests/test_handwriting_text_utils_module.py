from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from src.plotter_backend import handwriting_text_utils


class HandwritingTextUtilsModuleTests(unittest.TestCase):
    def test_token_split_and_normalization(self) -> None:
        self.assertEqual(
            handwriting_text_utils.split_text_tokens_keep_spaces("ab  cd"),
            ["ab", "  ", "cd"],
        )
        normalized = handwriting_text_utils.normalize_handwriting_text_token(
            "V\u00b2 \u03b1",
            strip_unpaired_surrogates=lambda text, replacement=" ": text,
        )
        self.assertEqual(normalized, "V^2 a")

    def test_sentence_case_normalization_skips_formulas(self) -> None:
        self.assertEqual(
            handwriting_text_utils.normalize_handwriting_sentence_case(
                "\u0421\u041e\u0421\u0422\u0410\u0412\u0418\u041c \u0421\u0418\u0421\u0422\u0415\u041c\u0423 \u0423\u0420\u0410\u0412\u041d\u0415\u041d\u0418\u0419",
                text_contains_formula_script_fn=lambda text: False,
            ),
            "\u0421\u043e\u0441\u0442\u0430\u0432\u0438\u043c \u0441\u0438\u0441\u0442\u0435\u043c\u0443 \u0443\u0440\u0430\u0432\u043d\u0435\u043d\u0438\u0439",
        )
        self.assertEqual(
            handwriting_text_utils.normalize_handwriting_text_string(
                "I=U/R",
                strip_unpaired_surrogates=lambda text, replacement=" ": text,
                text_contains_formula_script_fn=lambda text: False,
            ),
            "I=U/R",
        )
        self.assertTrue(
            handwriting_text_utils.text_prefers_print_font(
                "R12",
                font_size=9.0,
                text_contains_formula_script_fn=lambda text: False,
            )
        )
        self.assertFalse(
            handwriting_text_utils.text_prefers_print_font(
                "\u0421\u043e\u0441\u0442\u0430\u0432\u0438\u043c \u0441\u0438\u0441\u0442\u0435\u043c\u0443",
                font_size=12.0,
                text_contains_formula_script_fn=lambda text: False,
            )
        )
        self.assertEqual(
            handwriting_text_utils.normalize_handwriting_sentence_case(
                "\u0420\u0410\u0421\u0421\u0427\u0418\u0422\u0410\u0422\u042c \u0422\u041e\u041a\u0418 \u041f\u041e \u041f\u0415\u0420\u0412\u041e\u041c\u0423-\u0412\u0422\u041e\u0420\u041e\u041c\u0423 \u0417\u0410\u041a\u041e\u041d\u0423",
                text_contains_formula_script_fn=lambda text: False,
            ),
            "\u0420\u0430\u0441\u0441\u0447\u0438\u0442\u0430\u0442\u044c \u0442\u043e\u043a\u0438 \u043f\u043e \u043f\u0435\u0440\u0432\u043e\u043c\u0443-\u0432\u0442\u043e\u0440\u043e\u043c\u0443 \u0437\u0430\u043a\u043e\u043d\u0443",
        )
        self.assertFalse(
            handwriting_text_utils.text_prefers_print_font(
                "\u0421\u0445\u0435\u043c\u0430 \u043f\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u0430 \u043d\u0430 \u0440\u0438\u0441.2.1",
                font_size=11.0,
                text_contains_formula_script_fn=lambda text: False,
            )
        )
        self.assertFalse(
            handwriting_text_utils.text_prefers_print_font(
                "\u0441\u0442\u043e\u044f\u043d\u043d\u043e\u0433\u043e \u0442\u043e\u043a\u0430 \u043f\u0440\u0438\u0432\u0435\u0434\u0435\u043d\u0430 \u043d\u0430 \u0440\u0438\u0441 1.1.",
                font_size=12.0,
                text_contains_formula_script_fn=lambda text: False,
            )
        )
        self.assertFalse(
            handwriting_text_utils.text_prefers_print_font(
                "1. \u0420\u0410\u0421\u0421\u0427\u0418\u0422\u0410\u0422\u042c \u0422\u041e\u041a\u0418 \u0412\u041e \u0412\u0421\u0415\u0425 \u0412\u0415\u0422\u0412\u042f\u0425 \u041f\u0420\u0418\u0415\u041c\u041d\u0418\u041a\u0410",
                font_size=12.0,
                text_contains_formula_script_fn=lambda text: False,
            )
        )
        self.assertFalse(
            handwriting_text_utils.text_prefers_print_font(
                "3. \u041e\u041f\u0420\u0415\u0414\u0415\u041b\u0418\u0422\u042c \u041f\u041e\u041a\u0410\u0417\u0410\u041d\u0418\u042f \u041f\u0420\u0418\u0411\u041e\u0420\u041e\u0412: \u0410\u041c\u041f\u0415\u0420\u041c\u0415\u0422\u0420\u0410 \u0410, \u0412\u041e\u041b\u042c\u0422\u041c\u0415\u0422\u0420\u0410 V \u0418",
                font_size=12.0,
                text_contains_formula_script_fn=lambda text: False,
            )
        )

    def test_native_vector_and_line_spacing_helpers(self) -> None:
        self.assertTrue(
            handwriting_text_utils.text_prefers_native_vector(
                "\uE000\uE001\uE002a1",
                strip_unpaired_surrogates=lambda text, replacement=" ": text,
            )
        )
        min_step = handwriting_text_utils.handwriting_min_line_step_mm(
            10.0,
            "\u041f\u0440\u0438\u0432\u0435\u0442",
            text_contains_cyrillic=lambda text: any("\u0410" <= ch <= "\u044f" for ch in text),
            line_step_factor=1.24,
            line_step_factor_cyr=1.34,
            line_step_extra_mm=0.70,
        )
        self.assertAlmostEqual(min_step, 13.4)
        adjusted = handwriting_text_utils.adjust_handwriting_tspan_dy(
            5.0,
            font_size=10.0,
            text="\u041f\u0440\u0438\u0432\u0435\u0442",
            is_first_visible_line=False,
            auto_line_spacing_enabled=True,
            handwriting_min_line_step_fn=lambda font_size, text: 13.4,
        )
        self.assertAlmostEqual(adjusted, 13.4)

    def test_style_merge_sanitize_visibility_and_color(self) -> None:
        node = ET.fromstring('<text style="fill:#111"><tspan>\u03b1\u00b2</tspan> z</text>')
        merged = handwriting_text_utils.merge_svg_text_style(
            {"stroke": "#222"},
            node,
            read_style_dict_preserve=lambda style: {"fill": "#111"} if style else {},
        )
        self.assertEqual(merged["fill"], "#111")
        self.assertEqual(merged["stroke"], "#222")
        changed = handwriting_text_utils.sanitize_svg_text_node_for_vector(
            node,
            normalize_handwriting_text_token_fn=lambda text: text.replace("\u03b1", "a").replace("\u00b2", "^2"),
        )
        self.assertTrue(changed)
        self.assertEqual("".join(node.itertext()), "a^2 z")
        self.assertTrue(
            handwriting_text_utils.svg_text_node_is_visible(
                {"fill": "#000"},
                parse_svg_number=lambda value, default=0.0: float(value or default),
            )
        )
        self.assertEqual(
            handwriting_text_utils.pick_svg_text_stroke_color({"fill": "#123456"}),
            "#123456",
        )

    def test_profile_analysis_and_font_pickers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_handwriting_text_") as td:
            svg_path = Path(td) / "profile.svg"
            svg_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><text>A1 B2 C3 D4 E5 F6 G7 H8 I9 J10 K11 L12 M13 N14 O15 P16 Q17 R18</text></svg>',
                encoding="utf-8",
            )
            profile = handwriting_text_utils.analyze_svg_text_profile(
                svg_path,
                tag_name=lambda tag: tag.split("}")[-1],
                text_node_tags={"text", "tspan"},
                extract_svg_text_plain=lambda node: "".join(node.itertext()),
            )
        self.assertTrue(profile["technical_like"])
        self.assertEqual(
            handwriting_text_utils.pick_hershey_font_name(
                "Mono Console",
                handwriting_stroke_font_name="cursive",
            ),
            "futural",
        )
        self.assertEqual(
            handwriting_text_utils.pick_hershey_font_name_for_text(
                "Script Cyr",
                "\u041f\u0440\u0438\u0432\u0435\u0442",
                text_contains_cyrillic=lambda text: any("\u0410" <= ch <= "\u044f" for ch in text),
                pick_hershey_font_name_fn=lambda name: "fallback",
                handwriting_stroke_cyr_font_name="cyrilc_1",
            ),
            "cyrilc_1",
        )


if __name__ == "__main__":
    unittest.main()
