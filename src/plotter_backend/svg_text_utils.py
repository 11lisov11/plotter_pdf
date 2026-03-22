from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from xml.etree import ElementTree as ET


CYRILLIC_TEXT_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F]")
TEXT_NODE_TAGS = {"text", "tspan", "textpath", "flowroot", "flowpara", "flowspan"}
XLINK_NS = "http://www.w3.org/1999/xlink"


def read_style_dict(style: Optional[str]) -> dict:
    if not style:
        return {}
    return {k.strip().lower(): v.strip().lower() for k, _, v in (part.partition(":") for part in style.split(";")) if k.strip()}


def get_href(element: ET.Element) -> Optional[str]:
    href = element.attrib.get("href")
    if not href:
        href = element.attrib.get("xlink:href")
    if not href:
        href = element.attrib.get(f"{{{XLINK_NS}}}href")
    if not href:
        return None
    if href.startswith("#"):
        return href[1:]
    return href


def parse_color_to_rgb_like(value: str) -> Optional[Tuple[float, float, float, float]]:
    if not value:
        return None
    v = value.strip().lower()
    if v in {"none", "transparent"}:
        return None
    if v in {"white", "#fff", "#ffffff"}:
        return 1.0, 1.0, 1.0, 1.0
    if v.startswith("#") and len(v) == 7:
        try:
            r = int(v[1:3], 16) / 255.0
            g = int(v[3:5], 16) / 255.0
            b = int(v[5:7], 16) / 255.0
            return r, g, b, 1.0
        except Exception:
            return None
    if v.startswith("rgb"):
        match = re.match(r"rgba?\(([^)]+)\)", v)
        if not match:
            return None
        parts = [p.strip() for p in match.group(1).split(",")]
        if len(parts) < 3:
            return None
        try:
            is_pct = "%" in parts[0] or "%" in parts[1] or "%" in parts[2]
            nums = [float(p.rstrip("%")) for p in parts[:3]]
            if is_pct:
                return (nums[0] / 100.0, nums[1] / 100.0, nums[2] / 100.0, 1.0)
            return (nums[0] / 255.0, nums[1] / 255.0, nums[2] / 255.0, 1.0)
        except Exception:
            return None
    return None


def svg_has_text_nodes(svg_path: Path, *, tag_name: Callable[[str], str]) -> bool:
    try:
        root = ET.parse(svg_path).getroot()
        return any(tag_name(node.tag).lower() in TEXT_NODE_TAGS for node in root.iter())
    except Exception:
        return False


def svg_text_node_count(svg_path: Path, *, tag_name: Callable[[str], str]) -> int:
    try:
        root = ET.parse(svg_path).getroot()
        return sum(1 for node in root.iter() if tag_name(node.tag).lower() in TEXT_NODE_TAGS)
    except Exception:
        return 0


def read_style_dict_preserve(style: Optional[str]) -> dict:
    if not style:
        return {}
    out: dict = {}
    for part in style.split(";"):
        key, _, value = part.partition(":")
        key_s = key.strip()
        if not key_s:
            continue
        out[key_s] = value.strip()
    return out


def style_dict_to_string(style: dict) -> str:
    parts: List[str] = []
    for key, value in style.items():
        k = str(key).strip()
        v = str(value).strip()
        if not k:
            continue
        parts.append(f"{k}:{v}")
    return ";".join(parts)


def parse_svg_number(value: Optional[str], default: float = 0.0) -> float:
    if value is None:
        return default
    s = str(value).strip()
    if not s:
        return default
    token = s.replace(",", " ").split()[0]
    token = re.sub(r"[^0-9eE+\-\.]", "", token)
    try:
        return float(token)
    except Exception:
        return default


def parse_svg_number_list(value: Optional[str]) -> List[float]:
    if value is None:
        return []
    src = str(value).replace(",", " ").strip()
    if not src:
        return []
    out: List[float] = []
    for tok in src.split():
        t = re.sub(r"[^0-9eE+\-\.]", "", tok)
        if not t:
            continue
        try:
            out.append(float(t))
        except Exception:
            continue
    return out


def extract_svg_text_plain(node: ET.Element, *, strip_unpaired_surrogates: Callable[[str, str], str]) -> str:
    raw = strip_unpaired_surrogates("".join(node.itertext()), replacement=" ")
    if not raw:
        return ""

    def _repair_cp1251_single_byte(text: str) -> str:
        out_chars: List[str] = []
        changed = False
        for ch in text:
            code = ord(ch)
            if CYRILLIC_TEXT_RE.search(ch):
                out_chars.append(ch)
                continue
            if code in {0xA8, 0xB8} or (0xC0 <= code <= 0xFF):
                repaired = ""
                try:
                    repaired = bytes([code]).decode("cp1251")
                except Exception:
                    repaired = ""
                if repaired and len(repaired) == 1 and CYRILLIC_TEXT_RE.search(repaired):
                    out_chars.append(repaired)
                    changed = True
                    continue
            out_chars.append(ch)
        if not changed:
            return text
        return "".join(out_chars)

    if not CYRILLIC_TEXT_RE.search(raw):
        raw = _repair_cp1251_single_byte(raw)
    if not CYRILLIC_TEXT_RE.search(raw):
        if any(tok in raw for tok in ("Р", "С", "Ð", "Ñ")):
            for src_enc in ("cp1251", "latin1"):
                try:
                    repaired = raw.encode(src_enc, errors="strict").decode("utf-8", errors="strict")
                except Exception:
                    continue
                if CYRILLIC_TEXT_RE.search(repaired):
                    raw = repaired
                    break
    lines = []
    for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        lines.append(re.sub(r"[ \t]+", " ", ln).strip())
    return "\n".join(ln for ln in lines if ln)


def text_contains_cyrillic(text: str) -> bool:
    return bool(CYRILLIC_TEXT_RE.search(text or ""))


def svg_has_cyrillic_text_nodes(svg_path: Path, *, tag_name: Callable[[str], str]) -> bool:
    try:
        root = ET.parse(svg_path).getroot()
    except Exception:
        return False
    for node in root.iter():
        if tag_name(node.tag).lower() not in TEXT_NODE_TAGS:
            continue
        if text_contains_cyrillic("".join(node.itertext())):
            return True
    return False


def style_value(style: dict, element: ET.Element, key: str) -> str:
    value = style.get(key)
    if value is not None:
        return value.strip().lower()
    return element.attrib.get(key, "").strip().lower()


def is_none_style(value: Optional[str]) -> bool:
    return value in (None, "", "none", "transparent")


def parse_style_flags(
    style: dict,
    element: ET.Element,
    tag: str,
    *,
    is_pure_white_shape: Callable[[dict, ET.Element], bool],
) -> Tuple[bool, bool]:
    if is_pure_white_shape(style, element):
        return False, False

    has_stroke = False
    has_fill = False
    if tag == "line":
        stroke = style_value(style, element, "stroke")
        has_stroke = not is_none_style(stroke)
        fill_val = style_value(style, element, "fill")
        has_fill = not is_none_style(fill_val) and fill_val not in {"", "none"}
        return has_stroke, has_fill

    stroke = style_value(style, element, "stroke")
    fill = style_value(style, element, "fill")
    explicit_stroke = "stroke" in style or "stroke" in element.attrib
    explicit_fill = "fill" in style or "fill" in element.attrib

    if tag in {"rect", "polygon", "polyline", "circle", "ellipse", "path"}:
        has_stroke = not is_none_style(stroke) if explicit_stroke else False
        if explicit_fill:
            has_fill = not is_none_style(fill)
        else:
            has_fill = True
    else:
        has_stroke = not is_none_style(stroke) if explicit_stroke else False
        if explicit_fill:
            has_fill = not is_none_style(fill)
        else:
            has_fill = not is_none_style(fill)

    if explicit_stroke and explicit_fill and not has_stroke and not has_fill:
        return False, False

    if not explicit_stroke and not explicit_fill and tag in {"line", "polyline", "polygon", "rect", "circle", "ellipse", "path"}:
        if tag == "line":
            has_stroke = True
    return has_stroke, has_fill
