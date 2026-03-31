from __future__ import annotations

import re
from typing import Callable, Iterable, Optional


ROLE_BODY_HANDWRITING = "body_handwriting"
ROLE_PRINT_FORMULA = "print_formula"
ROLE_PRINT_SHORT_TECH = "print_short_tech"
ROLE_PRINT_TABLE = "print_table"
ROLE_PRINT_CAPTION = "print_caption"

_PRINT_TECH_TOKEN_RE = re.compile(r"^[0-9A-Za-z\u0400-\u04FF\u0401\u0451]{1,12}$")
_FORMULA_OPERATOR_RE = re.compile(r"[=+*/^_<>≈≤≥±×÷√∑∫∂\[\]{}|]")
_CAPTION_KEYWORDS = (
    "\u0442\u0430\u0431\u043b\u0438\u0446",
    "\u0440\u0438\u0441\u0443\u043d\u043e\u043a",
    "\u0440\u0438\u0441.",
    "\u0441\u0445\u0435\u043c",
    "\u0432\u0430\u0440\u0438\u0430\u043d\u0442",
)
_TABLE_TOKEN_RE = re.compile(r"^[0-9A-Za-z\u0410-\u042f\u0430-\u044f\u0401\u0451./,-]{1,10}$")
_SHORT_NUMERIC_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_TABLE_UNIT_TOKENS = {
    "a",
    "v",
    "s",
    "w",
    "hz",
    "ohm",
    "\u043e\u043c",
    "\u043e\u043c\u043d",
    "\u043c\u0430",
    "mv",
    "\u043a\u0432",
}


def _split_words(text: str) -> list[str]:
    return [part for part in re.split(r"\s+", str(text or "").strip(), flags=re.UNICODE) if part]


def _compact_token(word: str) -> str:
    return re.sub(r"[^\w./,-]+", "", str(word or ""), flags=re.UNICODE)


def _looks_short_numeric(text: str) -> bool:
    return bool(_SHORT_NUMERIC_RE.fullmatch(str(text or "")))


def _looks_unit_token(text: str) -> bool:
    return str(text or "").casefold() in _TABLE_UNIT_TOKENS


def text_has_caption_keyword(text: str) -> bool:
    lower_text = str(text or "").casefold()
    words = _split_words(lower_text)
    has_digits = any(ch.isdigit() for ch in lower_text)
    for token in _CAPTION_KEYWORDS:
        if lower_text.startswith(token) and has_digits:
            return True
        if token in lower_text and has_digits and len(words) <= 8 and len(lower_text) <= 72:
            return True
    return False


def text_looks_table_like(text: str, *, font_size: Optional[float]) -> bool:
    words = _split_words(text)
    if not words:
        return False
    if len(words) < 2:
        return False
    if len(words) > 14:
        return False
    if font_size is not None and float(font_size) > 13.0:
        return False

    short_like = 0
    strong_table_tokens = 0
    for word in words:
        compact = _compact_token(word)
        if not compact:
            continue
        if not _TABLE_TOKEN_RE.fullmatch(compact):
            return False
        short_like += 1
        if _looks_unit_token(compact):
            strong_table_tokens += 1
        elif _looks_short_numeric(compact):
            strong_table_tokens += 1
        elif any(ch.isdigit() for ch in compact):
            strong_table_tokens += 1
        elif compact.upper() == compact and compact.lower() != compact:
            strong_table_tokens += 1
        elif len(compact) <= 3:
            strong_table_tokens += 1

    if short_like <= 0 or short_like != len(words):
        return False
    return strong_table_tokens >= max(2, len(words) // 2)


def classify_text_content_role(
    text: str,
    *,
    font_size: Optional[float],
    font_names: Iterable[str] | None = None,
    text_contains_formula_script_fn: Callable[[str], bool],
) -> str:
    src = str(text or "").strip()
    if not src:
        return ROLE_BODY_HANDWRITING

    compact = re.sub(r"\s+", "", src, flags=re.UNICODE)
    if not compact:
        return ROLE_BODY_HANDWRITING

    lower_font_names = " ".join(str(name or "") for name in (font_names or ())).casefold()
    alpha = sum(1 for ch in compact if ch.isalpha())
    digits = sum(1 for ch in compact if ch.isdigit())
    words = _split_words(src)

    if text_contains_formula_script_fn(compact):
        return ROLE_PRINT_FORMULA
    if "math" in lower_font_names:
        return ROLE_PRINT_FORMULA
    if _FORMULA_OPERATOR_RE.search(compact) and (alpha + digits) >= 2:
        return ROLE_PRINT_FORMULA

    if text_has_caption_keyword(src):
        return ROLE_PRINT_CAPTION

    if text_looks_table_like(src, font_size=font_size):
        return ROLE_PRINT_TABLE

    if len(words) <= 2:
        compact_words = [_compact_token(word) for word in words]
        compact_words = [word for word in compact_words if word]
        if compact_words and all(_looks_unit_token(word) or _looks_short_numeric(word) for word in compact_words):
            return ROLE_PRINT_SHORT_TECH

    if font_size is not None and float(font_size) <= 9.6 and len(words) <= 4 and len(compact) <= 24:
        return ROLE_PRINT_SHORT_TECH
    if _looks_unit_token(compact):
        return ROLE_PRINT_SHORT_TECH
    if _looks_short_numeric(compact) and len(compact) <= 6:
        return ROLE_PRINT_SHORT_TECH
    if digits > 0 and alpha > 0 and len(compact) <= 12:
        return ROLE_PRINT_SHORT_TECH
    if _PRINT_TECH_TOKEN_RE.fullmatch(compact) and digits > 0:
        return ROLE_PRINT_SHORT_TECH
    if len(compact) <= 6 and alpha > 0 and compact.upper() == compact and compact.lower() != compact:
        return ROLE_PRINT_SHORT_TECH

    return ROLE_BODY_HANDWRITING


def text_prefers_print_font(
    text: str,
    *,
    font_size: Optional[float],
    font_names: Iterable[str] | None = None,
    text_contains_formula_script_fn: Callable[[str], bool],
) -> bool:
    return (
        classify_text_content_role(
            text,
            font_size=font_size,
            font_names=font_names,
            text_contains_formula_script_fn=text_contains_formula_script_fn,
        )
        != ROLE_BODY_HANDWRITING
    )
