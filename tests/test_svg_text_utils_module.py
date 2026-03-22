from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from src.plotter_backend import svg_text_utils


class SvgTextUtilsModuleTests(unittest.TestCase):
    def test_style_helpers_and_color_parser(self) -> None:
        style = svg_text_utils.read_style_dict("fill:#fff; stroke : none")
        self.assertEqual(style["fill"], "#fff")
        self.assertEqual(style["stroke"], "none")
        self.assertEqual(svg_text_utils.parse_color_to_rgb_like("#ffffff"), (1.0, 1.0, 1.0, 1.0))
        self.assertTrue(svg_text_utils.is_none_style("transparent"))

    def test_svg_text_detection_and_cyrillic_detection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_svg_text_") as td:
            path = Path(td) / "sample.svg"
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Привет</text></svg>', encoding="utf-8")
            tag_name = lambda tag: tag.split("}")[-1]
            self.assertTrue(svg_text_utils.svg_has_text_nodes(path, tag_name=tag_name))
            self.assertEqual(svg_text_utils.svg_text_node_count(path, tag_name=tag_name), 1)
            self.assertTrue(svg_text_utils.svg_has_cyrillic_text_nodes(path, tag_name=tag_name))

    def test_extract_plain_text_and_style_flags(self) -> None:
        node = ET.fromstring('<text x="1" y="2"> A \n B </text>')
        plain = svg_text_utils.extract_svg_text_plain(node, strip_unpaired_surrogates=lambda text, replacement=" ": text)
        self.assertEqual(plain, "A\nB")

        rect = ET.fromstring('<rect fill="#000" stroke="none" />')
        has_stroke, has_fill = svg_text_utils.parse_style_flags(
            {},
            rect,
            "rect",
            is_pure_white_shape=lambda _style, _element: False,
        )
        self.assertFalse(has_stroke)
        self.assertTrue(has_fill)
