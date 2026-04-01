from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from . import text_content_routing


_HANDWRITING_TEXT_NORMALIZE_TRANSLATIONS = {
    ord("⁰"): "^0",
    ord("¹"): "^1",
    ord("²"): "^2",
    ord("³"): "^3",
    ord("⁴"): "^4",
    ord("⁵"): "^5",
    ord("⁶"): "^6",
    ord("⁷"): "^7",
    ord("⁸"): "^8",
    ord("⁹"): "^9",
    ord("₀"): "_0",
    ord("₁"): "_1",
    ord("₂"): "_2",
    ord("₃"): "_3",
    ord("₄"): "_4",
    ord("₅"): "_5",
    ord("₆"): "_6",
    ord("₇"): "_7",
    ord("₈"): "_8",
    ord("₉"): "_9",
    ord("−"): "-",
    ord("–"): "-",
    ord("—"): "-",
    ord("×"): "x",
    ord("⋅"): "*",
    ord("·"): ".",
    ord("ˆ"): "^",
}

_HANDWRITING_GREEK_ASCII_FALLBACK = {
    "α": "a",
    "β": "b",
    "γ": "g",
    "δ": "d",
    "ε": "e",
    "ζ": "z",
    "η": "n",
    "θ": "th",
    "ι": "i",
    "κ": "k",
    "λ": "l",
    "μ": "m",
    "ν": "n",
    "ξ": "x",
    "ο": "o",
    "π": "p",
    "ρ": "p",
    "σ": "s",
    "τ": "t",
    "υ": "u",
    "φ": "f",
    "χ": "x",
    "ψ": "ps",
    "ω": "w",
    "Α": "A",
    "Β": "B",
    "Γ": "G",
    "Δ": "D",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Θ": "TH",
    "Ι": "I",
    "Κ": "K",
    "Λ": "L",
    "Μ": "M",
    "Ν": "N",
    "Ξ": "X",
    "Ο": "O",
    "Π": "P",
    "Ρ": "P",
    "Σ": "S",
    "Τ": "T",
    "Υ": "Y",
    "Φ": "F",
    "Χ": "X",
    "Ψ": "PS",
    "Ω": "W",
}

_PROFILE_TOKEN_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FFЁё]+")
_HANDWRITING_CASE_SKIP_MATH_RE = re.compile(r"[=+\-*/^_<>≈≤≥±×÷√∑∫∞\[\]{}|]")


_PRINT_TECH_TOKEN_RE = re.compile(r"^[0-9A-Za-z\u0400-\u04FFРЃС‘]{1,12}$")


def split_text_tokens_keep_spaces(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"\S+|\s+", text, flags=re.UNICODE)


def normalize_handwriting_text_token(
    text: str,
    *,
    strip_unpaired_surrogates: Callable[[str, str], str],
) -> str:
    if not text:
        return text
    normalized = strip_unpaired_surrogates(text, replacement=" ")
    normalized = normalized.translate(_HANDWRITING_TEXT_NORMALIZE_TRANSLATIONS)
    out_chars: List[str] = []
    for ch in normalized:
        cp = ord(ch)
        if 0xD400 <= cp <= 0xD7FF:
            try:
                expanded = unicodedata.normalize("NFKD", chr(cp + 0x10000))
            except Exception:
                expanded = " "
        elif 0x1D400 <= cp <= 0x1D7FF:
            try:
                expanded = unicodedata.normalize("NFKD", ch)
            except Exception:
                expanded = " "
        else:
            expanded = ch

        for part in (expanded or " "):
            if part in _HANDWRITING_GREEK_ASCII_FALLBACK:
                out_chars.append(_HANDWRITING_GREEK_ASCII_FALLBACK[part])
                continue
            if part == "\u00A0":
                out_chars.append(" ")
                continue
            category = unicodedata.category(part)
            if category in {"Cc", "Cs", "Co", "Cn"}:
                out_chars.append(" ")
                continue
            out_chars.append(part)
    return "".join(out_chars)


def normalize_handwriting_sentence_case(
    text: str,
    *,
    text_contains_formula_script_fn: Callable[[str], bool],
) -> str:
    src = str(text or "")
    if not src:
        return src
    if text_content_routing.text_looks_formula_like(
        src,
        text_contains_formula_script_fn=text_contains_formula_script_fn,
    ):
        return src

    letters = [ch for ch in src if ch.isalpha()]
    if len(letters) < 2:
        return src
    upper_count = sum(1 for ch in letters if ch.isupper())
    lower_count = sum(1 for ch in letters if ch.islower())
    if upper_count < 2:
        return src
    if lower_count > max(1, upper_count // 3):
        return src

    out_chars: List[str] = []
    sentence_start = True
    changed = False
    for ch in src:
        if ch.isalpha():
            repl = ch.upper() if sentence_start else ch.lower()
            if repl != ch:
                changed = True
            out_chars.append(repl)
            sentence_start = False
            continue
        out_chars.append(ch)
        if ch in {".", "!", "?", "\n", "\r"}:
            sentence_start = True
    return "".join(out_chars) if changed else src


def normalize_handwriting_text_string(
    text: str,
    *,
    strip_unpaired_surrogates: Callable[[str, str], str],
    text_contains_formula_script_fn: Callable[[str], bool],
) -> str:
    normalized = normalize_handwriting_text_token(
        text,
        strip_unpaired_surrogates=strip_unpaired_surrogates,
    )
    return normalize_handwriting_sentence_case(
        normalized,
        text_contains_formula_script_fn=text_contains_formula_script_fn,
    )


def style_prefers_native_vector(style: Optional[dict]) -> bool:
    return False


def text_contains_formula_script(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if 0x0370 <= cp <= 0x03FF:
            return True
        if 0x1D400 <= cp <= 0x1D7FF:
            return True
        if 0xD400 <= cp <= 0xD7FF:
            return True
    return False


def text_prefers_native_vector(
    text: str,
    *,
    strip_unpaired_surrogates: Callable[[str, str], str],
) -> bool:
    src = strip_unpaired_surrogates(text or "", replacement=" ")
    if not src:
        return False
    letters = sum(1 for ch in src if ch.isalpha())
    digits = sum(1 for ch in src if ch.isdigit())
    private_use = sum(1 for ch in src if 0xE000 <= ord(ch) <= 0xF8FF)
    broken_math = sum(1 for ch in src if 0xD400 <= ord(ch) <= 0xD7FF)
    replacement = src.count("\uFFFD")
    return (private_use + broken_math + replacement) >= 3 and letters <= 2 and digits <= 2


def text_prefers_print_font(
    text: str,
    *,
    font_size: Optional[float],
    font_names: Optional[list[str]] = None,
    text_contains_formula_script_fn: Callable[[str], bool],
) -> bool:
    return text_content_routing.text_prefers_print_font(
        text,
        font_size=font_size,
        font_names=font_names,
        text_contains_formula_script_fn=text_contains_formula_script_fn,
    )


def handwriting_min_line_step_mm(
    font_size: float,
    text: str = "",
    *,
    text_contains_cyrillic: Callable[[str], bool],
    line_step_factor: float,
    line_step_factor_cyr: float,
    line_step_extra_mm: float,
) -> float:
    fs = max(1.0, float(font_size))
    factor = float(line_step_factor_cyr) if text_contains_cyrillic(text or "") else float(line_step_factor)
    return max(fs * factor, fs + float(line_step_extra_mm))


def adjust_handwriting_tspan_dy(
    dy: float,
    *,
    font_size: float,
    text: str,
    is_first_visible_line: bool,
    auto_line_spacing_enabled: bool,
    handwriting_min_line_step_fn: Callable[[float, str], float],
) -> float:
    if not auto_line_spacing_enabled:
        return float(dy)
    d = float(dy)
    if is_first_visible_line and abs(d) <= 1e-9:
        return d
    min_step = handwriting_min_line_step_fn(font_size, text)
    if d >= 0.0:
        return max(d, min_step)
    return min(d, -min_step)


def merge_svg_text_style(
    parent_style: dict,
    node: ET.Element,
    *,
    read_style_dict_preserve: Callable[[Optional[str]], dict],
) -> dict:
    merged = dict(parent_style)
    merged.update(read_style_dict_preserve(node.attrib.get("style")))
    for key in (
        "fill",
        "stroke",
        "font-size",
        "font-family",
        "-inkscape-font-specification",
        "font",
        "display",
        "visibility",
        "opacity",
        "fill-opacity",
        "stroke-opacity",
    ):
        if key in node.attrib:
            merged[key] = str(node.attrib.get(key, "")).strip()
    return merged


def sanitize_svg_text_node_for_vector(
    node: ET.Element,
    *,
    normalize_handwriting_text_token_fn: Callable[[str], str],
) -> bool:
    def _sanitize_local(text: Optional[str]) -> Tuple[Optional[str], bool]:
        if text is None:
            return None, False
        normalized = normalize_handwriting_text_token_fn(text)
        return normalized, (normalized != text)

    changed = False
    new_text, changed_text = _sanitize_local(node.text)
    if changed_text:
        node.text = new_text
        changed = True

    for child in list(node):
        child_changed = sanitize_svg_text_node_for_vector(
            child,
            normalize_handwriting_text_token_fn=normalize_handwriting_text_token_fn,
        )
        if child_changed:
            changed = True
        new_tail, changed_tail = _sanitize_local(child.tail)
        if changed_tail:
            child.tail = new_tail
            changed = True
    return changed


def svg_text_node_is_visible(
    style: Optional[dict],
    node: Optional[ET.Element] = None,
    *,
    parse_svg_number: Callable[[Optional[str], float], float],
) -> bool:
    st = style or {}

    def _pick_style_val(key: str) -> str:
        value = st.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
        if node is not None:
            return str(node.attrib.get(key, "")).strip()
        return ""

    display = _pick_style_val("display").lower()
    if display == "none":
        return False
    visibility = _pick_style_val("visibility").lower()
    if visibility in {"hidden", "collapse"}:
        return False

    opacity = parse_svg_number(_pick_style_val("opacity"), default=1.0)
    if opacity <= 1e-6:
        return False

    fill = _pick_style_val("fill").lower()
    stroke = _pick_style_val("stroke").lower()
    fill_none = fill in {"", "none", "transparent"}
    stroke_none = stroke in {"", "none", "transparent"}

    fill_opacity = parse_svg_number(_pick_style_val("fill-opacity"), default=1.0)
    stroke_opacity = parse_svg_number(_pick_style_val("stroke-opacity"), default=1.0)

    if fill_none and stroke_none:
        if "fill" not in st and "stroke" not in st and (node is None or ("fill" not in node.attrib and "stroke" not in node.attrib)):
            return True
        return False
    if (fill_none or fill_opacity <= 1e-6) and (stroke_none or stroke_opacity <= 1e-6):
        return False
    return True


def pick_svg_text_stroke_color(style: Optional[dict]) -> Optional[str]:
    st = style or {}
    stroke_raw = str(st.get("stroke", "")).strip()
    fill_raw = str(st.get("fill", "")).strip()
    stroke = stroke_raw.lower()
    fill = fill_raw.lower()
    stroke_none = stroke in {"", "none", "transparent"}
    fill_none = fill in {"", "none", "transparent"}

    if not stroke_none:
        return stroke_raw
    if not fill_none:
        return fill_raw
    if ("stroke" in st and stroke_none) or ("fill" in st and fill_none):
        return None
    return "#000000"


def analyze_svg_text_profile(
    svg_path: Path,
    *,
    tag_name: Callable[[str], str],
    text_node_tags: set[str],
    extract_svg_text_plain: Callable[[ET.Element], str],
) -> Dict[str, object]:
    profile: Dict[str, object] = {
        "tokens": 0,
        "short_ratio": 0.0,
        "digit_ratio": 0.0,
        "long_ratio": 0.0,
        "technical_like": False,
    }
    try:
        root = ET.parse(svg_path).getroot()
    except Exception:
        return profile

    tokens: List[str] = []
    for node in root.iter():
        if tag_name(node.tag).lower() not in text_node_tags:
            continue
        text = extract_svg_text_plain(node)
        if not text:
            continue
        for token in _PROFILE_TOKEN_RE.findall(text):
            stripped = token.strip()
            if stripped:
                tokens.append(stripped)

    total = len(tokens)
    if total <= 0:
        return profile

    short = sum(1 for token in tokens if len(token) <= 3)
    long = sum(1 for token in tokens if len(token) >= 6)
    digit = sum(1 for token in tokens if re.fullmatch(r"\d+", token))
    short_ratio = short / float(total)
    long_ratio = long / float(total)
    digit_ratio = digit / float(total)
    technical_like = (
        (total >= 18 and short_ratio >= 0.62 and (digit_ratio >= 0.18 or long_ratio <= 0.18))
        or (total >= 12 and short_ratio >= 0.72 and long_ratio <= 0.12)
    )

    profile["tokens"] = total
    profile["short_ratio"] = short_ratio
    profile["digit_ratio"] = digit_ratio
    profile["long_ratio"] = long_ratio
    profile["technical_like"] = technical_like
    return profile


def pick_hershey_font_name(font_name: str, *, handwriting_stroke_font_name: str) -> str:
    requested = (font_name or "").strip().lower()
    if not requested:
        return handwriting_stroke_font_name
    if any(key in requested for key in ("script", "cursive", "hand")):
        return "cursive"
    if any(key in requested for key in ("mono", "console", "type")):
        return "futural"
    return handwriting_stroke_font_name


def pick_hershey_font_name_for_text(
    font_name: str,
    text: str,
    *,
    text_contains_cyrillic: Callable[[str], bool],
    pick_hershey_font_name_fn: Callable[[str], str],
    handwriting_stroke_cyr_font_name: str,
) -> str:
    if text_contains_cyrillic(text):
        requested = (font_name or "").strip().lower()
        default_cyr = (handwriting_stroke_cyr_font_name or "cyrilc_1").strip().lower()
        if any(key in requested for key in ("mono", "console", "type")):
            return "cyrillic"
        if "cyr" in requested:
            if any(key in requested for key in ("1", "script", "cursive", "hand")):
                return "cyrilc_1"
            return "cyrillic"
        if any(key in requested for key in ("script", "cursive", "hand")):
            return default_cyr
        return default_cyr
    return pick_hershey_font_name_fn(font_name)
