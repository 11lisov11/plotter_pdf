from __future__ import annotations

from typing import Callable, List, Optional, Pattern, Tuple
from xml.etree import ElementTree as ET


def infer_scale(
    root: ET.Element,
    *,
    viewbox_re: Pattern[str],
    parse_length: Callable[[str], Optional[Tuple[float, str]]],
    unit_to_mm: Callable[[float, str], float],
) -> float:
    viewbox = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    width = root.attrib.get("width", "100")
    height = root.attrib.get("height", "100")

    if not viewbox:
        return 1.0
    match = viewbox_re.match(viewbox.strip())
    if not match:
        return 1.0
    vb_w = float(match.group(3))
    vb_h = float(match.group(4))

    w_info = parse_length(width)
    h_info = parse_length(height)
    if w_info and h_info and vb_w and vb_h:
        w_mm = unit_to_mm(w_info[0], w_info[1])
        h_mm = unit_to_mm(h_info[0], h_info[1])
        sx = w_mm / vb_w
        sy = h_mm / vb_h
        return (sx + sy) * 0.5
    return 1.0


def apply_style_filter(
    style: Optional[dict],
    tag: str,
    element: Optional[ET.Element] = None,
    *,
    style_value: Callable[[dict, Optional[ET.Element], str], str],
    is_none_style: Callable[[Optional[str]], bool],
) -> bool:
    if tag != "path":
        return True

    stroke = style_value(style, element, "stroke")
    fill = style_value(style, element, "fill")

    explicit_stroke = "stroke" in style
    explicit_fill = "fill" in style
    if element is not None:
        explicit_stroke = explicit_stroke or ("stroke" in element.attrib)
        explicit_fill = explicit_fill or ("fill" in element.attrib)

    if explicit_stroke and explicit_fill and is_none_style(stroke) and is_none_style(fill):
        return False

    return True


def length_to_user_units(
    raw: str,
    scale_to_mm: float,
    *,
    parse_length: Callable[[str], Optional[Tuple[float, str]]],
    unit_to_mm: Callable[[float, str], float],
) -> Optional[float]:
    info = parse_length(str(raw or "").strip())
    if info is None:
        return None
    value, unit = info
    if unit in {"", "px"}:
        return float(value)
    mm = unit_to_mm(float(value), unit)
    if abs(scale_to_mm) <= 1e-12:
        return float(value)
    return float(mm / scale_to_mm)


def is_nearly_white_fill(
    elem: ET.Element,
    *,
    read_style_dict: Callable[[Optional[str]], dict],
    parse_color_to_rgb_like: Callable[[str], Optional[Tuple[float, float, float, float]]],
    background_fill_min_channel: float,
    background_fill_min_opacity: float,
) -> bool:
    style = read_style_dict(elem.attrib.get("style"))
    fill = style.get("fill", elem.attrib.get("fill", "")).strip().lower()
    if not fill:
        return False
    rgb = parse_color_to_rgb_like(fill)
    if rgb is None:
        return False
    r, g, b, _ = rgb
    if min(r, g, b) < float(background_fill_min_channel):
        return False
    opacity = style.get("fill-opacity", elem.attrib.get("fill-opacity", "1")).strip()
    try:
        if float(opacity) < float(background_fill_min_opacity):
            return False
    except Exception:
        pass
    return True


def is_pure_white_shape(
    style: dict,
    element: ET.Element,
    *,
    is_none_style: Callable[[Optional[str]], bool],
    parse_color_to_rgb_like: Callable[[str], Optional[Tuple[float, float, float, float]]],
) -> bool:
    fill = style.get("fill", element.attrib.get("fill", "")).strip().lower()
    stroke = style.get("stroke", element.attrib.get("stroke", "")).strip().lower()

    stroke_none = is_none_style(stroke)
    fill_none = is_none_style(fill)
    if fill_none and stroke_none:
        return False

    fill_is_white = False
    stroke_is_white = False
    if fill and not fill_none:
        fill_rgb = parse_color_to_rgb_like(fill)
        fill_is_white = fill_rgb is not None and min(fill_rgb[:3]) >= 0.99
    if stroke and not stroke_none:
        stroke_rgb = parse_color_to_rgb_like(stroke)
        stroke_is_white = stroke_rgb is not None and min(stroke_rgb[:3]) >= 0.99

    if fill_is_white and (stroke_none or stroke_is_white):
        return True
    if stroke_is_white and fill_none:
        return True
    if stroke_is_white and fill_is_white:
        return True
    return False


def is_axis_aligned_rectangle(poly: List[Tuple[float, float]]) -> bool:
    if len(poly) != 5 or poly[0] != poly[-1]:
        return False
    pts = poly[:-1]
    if len({pt for pt in pts}) != 4:
        return False
    xs = {round(p[0], 5) for p in pts}
    ys = {round(p[1], 5) for p in pts}
    if len(xs) != 2 or len(ys) != 2:
        return False
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        if abs(x1 - x2) > 1e-6 and abs(y1 - y2) > 1e-6:
            return False
    return True


def root_page_size_mm(
    root: ET.Element,
    *,
    parse_length: Callable[[str], Optional[Tuple[float, str]]],
    unit_to_mm: Callable[[float, str], float],
    viewbox_re: Pattern[str],
) -> Tuple[float, float]:
    width = parse_length(root.attrib.get("width", "0"))
    height = parse_length(root.attrib.get("height", "0"))
    if width and height:
        return unit_to_mm(width[0], width[1]), unit_to_mm(height[0], height[1])

    viewbox = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if viewbox:
        match = viewbox_re.match(viewbox.strip())
        if match:
            return float(match.group(3)), float(match.group(4))
    return 0.0, 0.0


def is_full_page_white_fill_rect(
    poly: List[Tuple[float, float]],
    elem: ET.Element,
    page_w: float,
    page_h: float,
    *,
    is_axis_aligned_rectangle: Callable[[List[Tuple[float, float]]], bool],
    tag_name: Callable[[str], str],
    is_nearly_white_fill: Callable[[ET.Element], bool],
    read_style_dict: Callable[[Optional[str]], dict],
) -> bool:
    if not is_axis_aligned_rectangle(poly):
        return False
    if tag_name(elem.tag) not in {"path", "rect", "polygon"}:
        return False
    if not is_nearly_white_fill(elem):
        return False
    style = read_style_dict(elem.attrib.get("style"))
    stroke = (style.get("stroke") or elem.attrib.get("stroke") or "").strip().lower()
    if stroke not in {"", "none"}:
        return False
    if abs(page_w) < 1e-6 or abs(page_h) < 1e-6:
        return False
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    area_ratio = ((max(xs) - min(xs)) * (max(ys) - min(ys))) / (page_w * page_h)
    return 0.95 <= area_ratio <= 1.05
