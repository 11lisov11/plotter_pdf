from __future__ import annotations

import re
import unittest
from xml.etree import ElementTree as ET

from src.plotter_backend import svg_filter_utils


class SvgFilterUtilsModuleTests(unittest.TestCase):
    def test_infer_scale_and_root_page_size(self) -> None:
        root = ET.fromstring('<svg width="210mm" height="297mm" viewBox="0 0 210 297" />')
        viewbox_re = re.compile(r"\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[,\s]+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
        parse_length = lambda value: (float(str(value).rstrip("mm")), "mm")
        unit_to_mm = lambda value, unit: value if unit == "mm" else value
        self.assertAlmostEqual(
            svg_filter_utils.infer_scale(
                root,
                viewbox_re=viewbox_re,
                parse_length=parse_length,
                unit_to_mm=unit_to_mm,
            ),
            1.0,
        )
        self.assertEqual(
            svg_filter_utils.root_page_size_mm(
                root,
                parse_length=parse_length,
                unit_to_mm=unit_to_mm,
                viewbox_re=viewbox_re,
            ),
            (210.0, 297.0),
        )

    def test_style_filter_and_length_conversion(self) -> None:
        path = ET.fromstring('<path stroke="none" fill="none" />')
        style_value = lambda style, element, key: style.get(key, element.attrib.get(key, "")).strip().lower()
        is_none_style = lambda value: value in (None, "", "none", "transparent")
        self.assertFalse(
            svg_filter_utils.apply_style_filter(
                {"stroke": "none", "fill": "none"},
                "path",
                path,
                style_value=style_value,
                is_none_style=is_none_style,
            )
        )
        parse_length = lambda value: (float(str(value).rstrip("mm")), "mm")
        unit_to_mm = lambda value, unit: value if unit == "mm" else value
        self.assertEqual(
            svg_filter_utils.length_to_user_units(
                "20mm",
                2.0,
                parse_length=parse_length,
                unit_to_mm=unit_to_mm,
            ),
            10.0,
        )

    def test_white_fill_and_full_page_rect_detection(self) -> None:
        elem = ET.fromstring('<rect style="fill:#ffffff;fill-opacity:1" />')
        read_style_dict = lambda style: {
            part.partition(":")[0].strip().lower(): part.partition(":")[2].strip().lower()
            for part in (style or "").split(";")
            if part.partition(":")[0].strip()
        }
        parse_color = lambda value: (1.0, 1.0, 1.0, 1.0) if value.lower() in {"#fff", "#ffffff", "white"} else None
        self.assertTrue(
            svg_filter_utils.is_nearly_white_fill(
                elem,
                read_style_dict=read_style_dict,
                parse_color_to_rgb_like=parse_color,
                background_fill_min_channel=0.97,
                background_fill_min_opacity=0.85,
            )
        )
        poly = [(0.0, 0.0), (210.0, 0.0), (210.0, 297.0), (0.0, 297.0), (0.0, 0.0)]
        self.assertTrue(svg_filter_utils.is_axis_aligned_rectangle(poly))
        self.assertTrue(
            svg_filter_utils.is_full_page_white_fill_rect(
                poly,
                elem,
                210.0,
                297.0,
                is_axis_aligned_rectangle=svg_filter_utils.is_axis_aligned_rectangle,
                tag_name=lambda tag: tag.split("}")[-1],
                is_nearly_white_fill=lambda node: svg_filter_utils.is_nearly_white_fill(
                    node,
                    read_style_dict=read_style_dict,
                    parse_color_to_rgb_like=parse_color,
                    background_fill_min_channel=0.97,
                    background_fill_min_opacity=0.85,
                ),
                read_style_dict=read_style_dict,
            )
        )

    def test_pure_white_shape_detection(self) -> None:
        elem = ET.fromstring('<rect fill="#ffffff" stroke="none" />')
        self.assertTrue(
            svg_filter_utils.is_pure_white_shape(
                {},
                elem,
                is_none_style=lambda value: value in (None, "", "none", "transparent"),
                parse_color_to_rgb_like=lambda value: (1.0, 1.0, 1.0, 1.0) if value.lower() == "#ffffff" else None,
            )
        )
