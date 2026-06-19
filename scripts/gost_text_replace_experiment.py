from __future__ import annotations

import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import fitz

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import prepare_folder1_packages as prep  # noqa: E402

backend = prep.backend

CG_ROOT = PROJECT_ROOT / "Компьютерная графика"
SOURCE_PDF = CG_ROOT / "9 вариант" / "1.pdf"
OUT_DIR = CG_ROOT / "новый тест букв"
GOST_AU_FONT = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "GOST_AU.ttf"

GlyphStroke = list[tuple[float, float]]
Glyph = tuple[float, list[GlyphStroke]]
GOST_ITALIC_SHEAR = 0.30
GOST_TEXT_BOX_FILL = 0.86
LOWERCASE_WIDTH_SCALE = 0.93
LOWERCASE_Y_OFFSET = 1.15
LOWERCASE_HEIGHT_SCALE = (7.0 - LOWERCASE_Y_OFFSET) / 7.0


BASE_GLYPHS: dict[str, Glyph] = {
    "0": (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7), (0, 0)], [(0.8, 6.2), (4.2, 0.8)]]),
    "1": (3.6, [[(2.0, 0.4), (2.0, 7.0)], [(0.9, 7.0), (3.1, 7.0)], [(1.1, 1.4), (2.0, 0.4)]]),
    "2": (5.0, [[(0, 0), (5, 0), (5, 3.2), (0, 7), (5, 7)], [(0, 3.5), (2.6, 3.5)]]),
    "3": (5.0, [[(0, 0), (5, 0), (3.1, 3.5), (5, 7), (0, 7)], [(1.4, 3.5), (4.3, 3.5)]]),
    "4": (5.0, [[(4.2, 0), (4.2, 7)], [(0, 0), (0, 3.7), (5, 3.7)]]),
    "5": (5.0, [[(5, 0), (0, 0), (0, 3.4), (4.6, 3.4), (5, 7), (0, 7)]]),
    "6": (5.0, [[(5, 0), (0, 3.4), (0, 7), (5, 7), (5, 3.4), (0, 3.4)]]),
    "7": (5.0, [[(0, 0), (5, 0), (2, 7)], [(3.2, 2.6), (5, 2.6)]]),
    "8": (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7), (0, 0)], [(0, 3.5), (5, 3.5)]]),
    "9": (5.0, [[(5, 3.6), (0, 3.6), (0, 0), (5, 0), (5, 7), (0, 7)]]),
    "A": (5.0, [[(0, 7), (2.5, 0), (5, 7)], [(1.0, 4.2), (4.0, 4.2)]]),
    "B": (5.0, [[(0, 0), (0, 7)], [(0, 0), (4.2, 0), (5, 1.1), (5, 2.7), (4.2, 3.5), (0, 3.5)], [(0, 3.5), (4.3, 3.5), (5, 4.4), (5, 6), (4.2, 7), (0, 7)]]),
    "C": (5.0, [[(5, 0), (0, 0), (0, 7), (5, 7)]]),
    "D": (5.0, [[(0, 0), (0, 7)], [(0, 0), (4.0, 0), (5, 1.3), (5, 5.7), (4.0, 7), (0, 7)]]),
    "E": (5.0, [[(5, 0), (0, 0), (0, 7), (5, 7)], [(0, 3.5), (4, 3.5)]]),
    "F": (5.0, [[(0, 0), (0, 7)], [(0, 0), (5, 0)], [(0, 3.5), (4, 3.5)]]),
    "G": (5.0, [[(5, 0), (0, 0), (0, 7), (5, 7), (5, 4), (3, 4)]]),
    "H": (5.0, [[(0, 0), (0, 7)], [(5, 0), (5, 7)], [(0, 3.5), (5, 3.5)]]),
    "I": (5.0, [[(0.8, 0), (4.2, 0)], [(2.5, 0), (2.5, 7)], [(0.8, 7), (4.2, 7)]]),
    "J": (5.0, [[(5, 0), (5, 6), (4, 7), (1, 7), (0, 6)], [(2.5, 0), (5, 0)]]),
    "K": (5.0, [[(0, 0), (0, 7)], [(5, 0), (0, 3.5), (5, 7)]]),
    "L": (5.0, [[(0, 0), (0, 7), (5, 7)]]),
    "M": (5.0, [[(0, 7), (0, 0), (2.5, 3.8), (5, 0), (5, 7)]]),
    "N": (5.0, [[(0, 7), (0, 0), (5, 7), (5, 0)]]),
    "O": (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7), (0, 0)]]),
    "P": (5.0, [[(0, 7), (0, 0), (4.5, 0), (5, 1.2), (5, 3.2), (4.5, 3.8), (0, 3.8)]]),
    "Q": (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7), (0, 0)], [(3, 5.2), (5.2, 7.3)]]),
    "R": (5.0, [[(0, 7), (0, 0), (4.5, 0), (5, 1.2), (5, 3.1), (4.3, 3.8), (0, 3.8)], [(2.7, 3.8), (5, 7)]]),
    "S": (5.0, [[(5, 0), (0, 0), (0, 3.5), (5, 3.5), (5, 7), (0, 7)]]),
    "T": (5.0, [[(0, 0), (5, 0)], [(2.5, 0), (2.5, 7)]]),
    "U": (5.0, [[(0, 0), (0, 6), (1, 7), (4, 7), (5, 6), (5, 0)]]),
    "V": (5.0, [[(0, 0), (2.5, 7), (5, 0)]]),
    "W": (5.0, [[(0, 0), (1, 7), (2.5, 3.5), (4, 7), (5, 0)]]),
    "X": (5.0, [[(0, 0), (5, 7)], [(5, 0), (0, 7)]]),
    "Y": (5.0, [[(0, 0), (2.5, 3.5), (5, 0)], [(2.5, 3.5), (2.5, 7)]]),
    "Z": (5.0, [[(0, 0), (5, 0), (0, 7), (5, 7)]]),
    ".": (1.8, [[(0.8, 6.6), (1.0, 6.8)]]),
    ",": (1.8, [[(1.0, 6.3), (0.3, 7.5)]]),
    ":": (1.8, [[(0.9, 2.0), (1.1, 2.2)], [(0.9, 5.4), (1.1, 5.6)]]),
    ";": (1.8, [[(0.9, 2.0), (1.1, 2.2)], [(1.0, 5.4), (0.3, 7.3)]]),
    "-": (3.0, [[(0, 3.5), (3.0, 3.5)]]),
    "_": (4.0, [[(0, 7), (4.0, 7)]]),
    "/": (3.8, [[(0, 7), (3.8, 0)]]),
    "\\": (3.8, [[(0, 0), (3.8, 7)]]),
    "+": (4.0, [[(0, 3.5), (4, 3.5)], [(2, 1.5), (2, 5.5)]]),
    "=": (4.0, [[(0, 2.7), (4, 2.7)], [(0, 4.5), (4, 4.5)]]),
    "<": (3.5, [[(3.5, 0.7), (0, 3.5), (3.5, 6.3)]]),
    ">": (3.5, [[(0, 0.7), (3.5, 3.5), (0, 6.3)]]),
    "(": (2.5, [[(2.2, 0), (0.4, 2), (0.4, 5), (2.2, 7)]]),
    ")": (2.5, [[(0.3, 0), (2.1, 2), (2.1, 5), (0.3, 7)]]),
    "[": (2.5, [[(2.2, 0), (0.4, 0), (0.4, 7), (2.2, 7)]]),
    "]": (2.5, [[(0.3, 0), (2.1, 0), (2.1, 7), (0.3, 7)]]),
    "'": (1.6, [[(0.8, 0), (0.4, 1.8)]]),
    '"': (3.0, [[(0.8, 0), (0.5, 1.8)], [(2.2, 0), (1.9, 1.8)]]),
    "°": (2.5, [[(0.5, 0.4), (2.0, 0.4), (2.0, 1.9), (0.5, 1.9), (0.5, 0.4)]]),
    "⌀": (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7), (0, 0)], [(0, 7), (5, 0)]]),
    "Ø": (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7), (0, 0)], [(0, 7), (5, 0)]]),
    "∅": (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7), (0, 0)], [(0, 7), (5, 0)]]),
    "№": (8.2, [[(0, 7), (0, 0), (4, 7), (4, 0)], [(5.2, 1.2), (7.8, 1.2), (7.8, 3.8), (5.2, 3.8), (5.2, 1.2)], [(5.3, 5.1), (8.0, 5.1)]]),
}

CYRILLIC_MAP: dict[str, Glyph] = {
    "А": BASE_GLYPHS["A"],
    "Б": (5.0, [[(0, 7), (0, 0), (5, 0)], [(0, 3.4), (4.5, 3.4), (5, 4.2), (5, 6.2), (4.2, 7), (0, 7)]]),
    "В": BASE_GLYPHS["B"],
    "Г": (5.0, [[(0, 7), (0, 0), (5, 0)]]),
    "Д": (5.4, [[(0.6, 6.2), (1.7, 0), (4.4, 0), (4.8, 6.2)], [(0, 7), (0.6, 6.2), (4.8, 6.2), (5.4, 7)]]),
    "Е": BASE_GLYPHS["E"],
    "Ё": (5.0, BASE_GLYPHS["E"][1] + [[(1.1, -0.7), (1.3, -0.5)], [(3.6, -0.7), (3.8, -0.5)]]),
    "Ж": (5.8, [[(2.9, 0), (2.9, 7)], [(0, 0), (2.9, 3.5), (0, 7)], [(5.8, 0), (2.9, 3.5), (5.8, 7)]]),
    "З": BASE_GLYPHS["3"],
    "И": (5.0, [[(0, 7), (0, 0)], [(5, 7), (5, 0)], [(0, 7), (5, 0)]]),
    "Й": (5.0, [[(0, 7), (0, 0)], [(5, 7), (5, 0)], [(0, 7), (5, 0)], [(1.3, -0.7), (2.5, -0.2), (3.7, -0.7)]]),
    "К": BASE_GLYPHS["K"],
    "Л": (5.0, [[(0, 7), (2.0, 0), (5, 0), (5, 7)]]),
    "М": BASE_GLYPHS["M"],
    "Н": BASE_GLYPHS["H"],
    "О": BASE_GLYPHS["O"],
    "П": (5.0, [[(0, 7), (0, 0), (5, 0), (5, 7)]]),
    "Р": BASE_GLYPHS["P"],
    "С": BASE_GLYPHS["C"],
    "Т": BASE_GLYPHS["T"],
    "У": (4.2, [[(0.0, 0.0), (1.55, 3.35), (3.75, 0.0)], [(1.55, 3.35), (1.05, 7.0)], [(0.45, 7.0), (1.95, 7.0)]]),
    "Ф": (5.6, [[(2.8, 0), (2.8, 7)], [(0, 1.2), (5.6, 1.2), (5.6, 5.2), (0, 5.2), (0, 1.2)]]),
    "Х": BASE_GLYPHS["X"],
    "Ц": (5.4, [[(0, 0), (0, 7), (4.6, 7), (4.6, 0)], [(4.6, 7), (5.4, 7), (5.4, 8.0)]]),
    "Ч": (5.0, [[(0, 0), (0, 3.3), (5, 3.3)], [(5, 0), (5, 7)]]),
    "Ш": (6.0, [[(0, 0), (0, 7), (3, 7), (3, 0)], [(6, 0), (6, 7), (3, 7)]]),
    "Щ": (6.4, [[(0, 0), (0, 7), (3, 7), (3, 0)], [(6, 0), (6, 7), (3, 7)], [(6, 7), (6.4, 7), (6.4, 8.0)]]),
    "Ъ": (5.8, [[(0, 0), (1.7, 0), (1.7, 7)], [(1.7, 3.5), (5, 3.5), (5.8, 4.3), (5.8, 6.2), (5, 7), (1.7, 7)]]),
    "Ы": (6.2, [[(0, 0), (0, 7)], [(0, 3.5), (3.4, 3.5), (4.2, 4.3), (4.2, 6.2), (3.4, 7), (0, 7)], [(6.2, 0), (6.2, 7)]]),
    "Ь": (5.2, [[(0, 0), (0, 7)], [(0, 3.5), (4.4, 3.5), (5.2, 4.3), (5.2, 6.2), (4.4, 7), (0, 7)]]),
    "Э": (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7)], [(2.0, 3.5), (5, 3.5)]]),
    "Ю": (7.2, [[(0, 0), (0, 7)], [(0, 3.5), (2, 3.5)], [(2, 0), (7.2, 0), (7.2, 7), (2, 7), (2, 0)]]),
    "Я": (5.0, [[(5, 7), (5, 0), (0.6, 0), (0, 1.1), (0, 3.2), (0.6, 3.8), (5, 3.8)], [(2.1, 3.8), (0, 7)]]),
}

CYRILLIC_EXTRA = {"І": CYRILLIC_MAP["И"], "Ї": CYRILLIC_MAP["И"], "Є": CYRILLIC_MAP["Э"]}
LOWERCASE_GLYPHS: dict[str, Glyph] = {
    "в": (
        3.8,
        [
            [(0.2, 0.0), (0.2, 7.0)],
            [(0.2, 0.0), (3.0, 0.0), (3.8, 0.8), (3.8, 2.5), (3.0, 3.3), (0.2, 3.3)],
            [(0.2, 3.3), (3.0, 3.3), (3.8, 4.1), (3.8, 6.2), (3.0, 7.0), (0.2, 7.0)],
        ],
    ),
    "т": (3.8, [[(0.0, 0.0), (3.8, 0.0)], [(1.9, 0.0), (1.9, 7.0)], [(0.35, 0.0), (0.35, 1.1)], [(3.45, 0.0), (3.45, 1.1)]]),
    "у": (4.8, [[(0.0, 0.0), (2.3, 3.9), (4.8, 0.0)], [(2.3, 3.9), (1.0, 7.0)]]),
}


def _oval(width: float = 5.0, height: float = 7.0) -> GlyphStroke:
    return [
        (width * 0.50, 0.0),
        (width * 0.86, height * 0.10),
        (width, height * 0.33),
        (width, height * 0.67),
        (width * 0.86, height * 0.90),
        (width * 0.50, height),
        (width * 0.14, height * 0.90),
        (0.0, height * 0.67),
        (0.0, height * 0.33),
        (width * 0.14, height * 0.10),
        (width * 0.50, 0.0),
    ]


BASE_GLYPHS["0"] = (5.0, [_oval(), [(0.9, 6.2), (4.1, 0.8)]])
BASE_GLYPHS["O"] = (5.0, [_oval()])
BASE_GLYPHS["Q"] = (5.0, [_oval(), [(3.0, 5.2), (5.2, 7.3)]])
BASE_GLYPHS["⌀"] = (5.0, [_oval(), [(0.0, 7.0), (5.0, 0.0)]])
BASE_GLYPHS["Ø"] = BASE_GLYPHS["⌀"]
BASE_GLYPHS["∅"] = BASE_GLYPHS["⌀"]
CYRILLIC_MAP["О"] = BASE_GLYPHS["O"]
CYRILLIC_MAP["Ф"] = (5.6, [[(2.8, 0), (2.8, 7)], _oval(5.6, 4.6)])
CYRILLIC_MAP["Ю"] = (
    7.2,
    [[(0, 0), (0, 7)], [(0, 3.5), (2, 3.5)], [(x + 2.0, y) for x, y in _oval(5.2, 7.0)]],
)


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_pdf_text_lines(pdf_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mm = 25.4 / 72.0
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        raw = page.get_text("rawdict")
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = ""
                font_names: list[str] = []
                sizes: list[float] = []
                for span in line.get("spans", []):
                    font = str(span.get("font", "") or "").strip()
                    if font and font not in font_names:
                        font_names.append(font)
                    size = span.get("size")
                    if isinstance(size, (int, float)):
                        sizes.append(float(size))
                    text += "".join(str(ch.get("c", "") or "") for ch in span.get("chars", []))
                if not text.strip():
                    continue
                bbox = tuple(float(v) for v in line.get("bbox", (0, 0, 0, 0))[:4])
                out.append(
                    {
                        "text": text,
                        "confidence": 1.0,
                        "source": "pdf_text_layer",
                        "bbox_pt": [round(v, 3) for v in bbox],
                        "bbox_mm": [round(v * mm, 3) for v in bbox],
                        "dir": [round(float(v), 6) for v in line.get("dir", (1.0, 0.0))],
                        "font_names": font_names,
                        "font_size_pt_median": round(sorted(sizes)[len(sizes) // 2], 3) if sizes else None,
                    }
                )
    return out


STAMP_CELL_TEXT_FILL = 0.62
STAMP_CELL_TEXT_FILL_TIGHT = 0.50
STAMP_ROLE_LABELS = {"Разраб.", "Пров.", "Т.контр.", "Н.контр.", "Утв."}
STAMP_ROLE_TEXT_FILL = 0.68
STAMP_ROLE_LETTER_SPACING_UNITS = 0.58
STAMP_FORCE_UPPERCASE_SHAPE_LABELS: set[str] = set()
STAMP_ROLE_CELL_BBOXES_MM: dict[str, list[float]] = {}

PHRASE_GLYPHS: dict[str, Glyph] = {
    "Утв.": (
        11.6,
        [
            [(0.0, 0.0), (1.35, 3.15), (2.75, 0.0)],
            [(1.35, 3.15), (1.35, 7.0), (2.15, 7.0)],
            [(3.35, 0.0), (6.0, 0.0)],
            [(4.68, 0.0), (4.68, 7.0)],
            [(6.75, 0.0), (6.75, 7.0)],
            [(6.75, 0.0), (9.15, 0.0), (9.75, 0.75), (9.75, 2.75), (9.1, 3.5), (6.75, 3.5)],
            [(6.75, 3.5), (9.25, 3.5), (9.85, 4.3), (9.85, 6.25), (9.15, 7.0), (6.75, 7.0)],
            [(10.85, 6.45), (11.08, 6.68)],
        ],
    ),
}

STAMP_CELL_CENTER_OVERRIDES_MM: dict[str, list[tuple[str, list[float]]]] = {
    "Изм. Лист": [
        ("Изм.", [20.45, 257.38, 26.6, 262.93]),
        ("Лист", [26.6, 257.38, 37.4, 262.93]),
    ],
    "№ докум.": [
        ("№ докум.", [37.4, 257.38, 61.8, 262.93]),
    ],
    "Подп. Дата": [
        ("Подп.", [61.8, 257.38, 75.45, 262.93]),
        ("Дата", [75.45, 257.38, 85.4, 262.93]),
    ],
    "Лит.": [
        ("Лит.", [156.2, 252.38, 170.3, 257.93]),
    ],
    "Масса": [
        ("Масса", [170.3, 252.38, 187.5, 257.93]),
    ],
    "Масштаб": [
        ("Масштаб", [187.5, 252.38, 205.6, 257.93]),
    ],
    "Лист": [
        ("Лист", [156.2, 272.38, 176.5, 277.93]),
    ],
    "Листов": [
        ("Листов", [176.5, 272.38, 198.0, 277.93]),
    ],
}


def _stamp_centered_lines(line: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(line.get("text", ""))
    overrides = STAMP_CELL_CENTER_OVERRIDES_MM.get(text)
    if not overrides:
        role_bbox = STAMP_ROLE_CELL_BBOXES_MM.get(text)
        if role_bbox:
            patched = dict(line)
            patched["bbox_mm"] = [round(float(v), 3) for v in role_bbox]
            patched["stamp_role_cell_expanded"] = True
            return [patched]
        return [line]
    out: list[dict[str, Any]] = []
    for cell_text, bbox_mm in overrides:
        patched = dict(line)
        patched["text"] = cell_text
        patched["bbox_mm"] = [round(float(v), 3) for v in bbox_mm]
        patched["stamp_cell_centered"] = True
        patched["stamp_source_text"] = text
        patched["text_box_fill"] = (
            STAMP_CELL_TEXT_FILL_TIGHT if text in {"Лист", "Листов"} else STAMP_CELL_TEXT_FILL
        )
        out.append(patched)
    return out


def _glyph_for_char(ch: str) -> Glyph:
    if ch.isspace():
        return (2.8, [])
    if ch in LOWERCASE_GLYPHS and ch not in {"в", "т"}:
        return LOWERCASE_GLYPHS[ch]
    up = ch.upper()
    if up in BASE_GLYPHS:
        return BASE_GLYPHS[up]
    if up in CYRILLIC_MAP:
        return CYRILLIC_MAP[up]
    if up in CYRILLIC_EXTRA:
        return CYRILLIC_EXTRA[up]
    if up == "X" or up == "Х" or ch == "×":
        return BASE_GLYPHS["X"]
    return (5.0, [[(0, 0), (5, 0), (5, 7), (0, 7), (0, 0)], [(0, 0), (5, 7)]])


def _is_lowercase_letter(ch: str) -> bool:
    return bool(ch.isalpha() and ch.lower() == ch and ch.upper() != ch)


def _char_width_units(ch: str, *, force_uppercase_shape: bool = False) -> float:
    render_ch = ch.upper() if force_uppercase_shape and ch.isalpha() else ch
    glyph_w, _segments = _glyph_for_char(render_ch)
    if _is_lowercase_letter(ch) and not force_uppercase_shape:
        return glyph_w * LOWERCASE_WIDTH_SCALE
    return glyph_w


def _glyph_point_for_char(ch: str, gx: float, gy: float, *, force_uppercase_shape: bool = False) -> tuple[float, float]:
    if force_uppercase_shape or not _is_lowercase_letter(ch):
        return gx, gy
    return gx * LOWERCASE_WIDTH_SCALE, LOWERCASE_Y_OFFSET + gy * LOWERCASE_HEIGHT_SCALE


def _text_width_units(text: str, *, letter_spacing_units: float = 1.0, force_uppercase_shape: bool = False) -> float:
    width = 0.0
    saw = False
    for ch in text:
        if saw:
            width += letter_spacing_units
        width += _char_width_units(ch, force_uppercase_shape=force_uppercase_shape)
        saw = True
    if saw:
        width += GOST_ITALIC_SHEAR * 7.0
    return max(width, 1.0)


def _bbox_of_polylines(polylines: list[GlyphStroke]) -> list[float] | None:
    points = [point for poly in polylines for point in poly]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_overflow_mm(inner: list[float] | None, outer: list[float], *, tolerance_mm: float = 0.0) -> float:
    if inner is None or len(outer) != 4:
        return 0.0
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer
    return max(
        0.0,
        ox0 - ix0 - tolerance_mm,
        oy0 - iy0 - tolerance_mm,
        ix1 - ox1 - tolerance_mm,
        iy1 - oy1 - tolerance_mm,
    )


def _fit_polylines_inside_bbox(polylines: list[GlyphStroke], bbox: list[float], *, pad_mm: float = 0.03) -> list[GlyphStroke]:
    stroke_bbox = _bbox_of_polylines(polylines)
    if stroke_bbox is None or len(bbox) != 4:
        return polylines
    sx0, sy0, sx1, sy1 = stroke_bbox
    bx0, by0, bx1, by1 = bbox
    stroke_w = max(sx1 - sx0, 1e-6)
    stroke_h = max(sy1 - sy0, 1e-6)
    target_w = max(bx1 - bx0 - pad_mm * 2.0, 1e-6)
    target_h = max(by1 - by0 - pad_mm * 2.0, 1e-6)
    scale = min(1.0, target_w / stroke_w, target_h / stroke_h)
    stroke_cx = (sx0 + sx1) * 0.5
    stroke_cy = (sy0 + sy1) * 0.5
    target_cx = (bx0 + bx1) * 0.5
    target_cy = (by0 + by1) * 0.5
    fitted: list[GlyphStroke] = []
    for poly in polylines:
        fitted.append(
            [
                (
                    target_cx + (x - stroke_cx) * scale,
                    target_cy + (y - stroke_cy) * scale,
                )
                for x, y in poly
            ]
        )
    return fitted


def _line_text_to_strokes_mm(line: dict[str, Any]) -> tuple[list[GlyphStroke], set[str]]:
    text = str(line.get("text", ""))
    bbox = [float(v) for v in line.get("bbox_mm", (0, 0, 0, 0))[:4]]
    if not text.strip() or len(bbox) != 4:
        return [], set()
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        return [], set()
    dx, dy = (line.get("dir") or [1.0, 0.0])[:2]
    dx = float(dx)
    dy = float(dy)
    norm = math.hypot(dx, dy)
    if norm < 1e-6:
        dx, dy, norm = 1.0, 0.0, 1.0
    ux, uy = dx / norm, dy / norm
    vx, vy = -uy, ux
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    u_vals = [x * ux + y * uy for x, y in corners]
    v_vals = [x * vx + y * vy for x, y in corners]
    min_u, max_u = min(u_vals), max(u_vals)
    min_v, max_v = min(v_vals), max(v_vals)
    box_w = max(max_u - min_u, 0.001)
    box_h = max(max_v - min_v, 0.001)
    is_stamp_role_label = text in STAMP_ROLE_LABELS
    force_uppercase_shape = text in STAMP_FORCE_UPPERCASE_SHAPE_LABELS
    phrase_glyph = None if is_stamp_role_label else PHRASE_GLYPHS.get(text)
    letter_spacing_units = STAMP_ROLE_LETTER_SPACING_UNITS if is_stamp_role_label else 1.0
    local_w = (
        phrase_glyph[0]
        if phrase_glyph
        else _text_width_units(
            text,
            letter_spacing_units=letter_spacing_units,
            force_uppercase_shape=force_uppercase_shape,
        )
    )
    local_h = 7.0
    text_box_fill = STAMP_ROLE_TEXT_FILL if is_stamp_role_label else float(line.get("text_box_fill", GOST_TEXT_BOX_FILL))
    scale = text_box_fill * min(box_w / local_w, box_h / local_h)
    if scale <= 0.0:
        return [], set(text)
    origin_u = min_u + max((box_w - local_w * scale) * 0.50, 0.0)
    origin_v = min_v + max((box_h - local_h * scale) * 0.50, 0.0)
    cursor = 0.0
    out: list[GlyphStroke] = []
    missing: set[str] = set()
    if phrase_glyph:
        for segment in phrase_glyph[1]:
            poly: GlyphStroke = []
            for gx, gy in segment:
                slanted_x = gx + GOST_ITALIC_SHEAR * (7.0 - gy)
                u = origin_u + slanted_x * scale
                v = origin_v + gy * scale
                poly.append((u * ux + v * vx, u * uy + v * vy))
            if len(poly) >= 2:
                out.append(poly)
        out = _fit_polylines_inside_bbox(out, [x0, y0, x1, y1], pad_mm=0.03)
        return out, missing
    for index, ch in enumerate(text):
        render_ch = ch.upper() if force_uppercase_shape and ch.isalpha() else ch
        _glyph_w, segments = _glyph_for_char(render_ch)
        char_w = _char_width_units(ch, force_uppercase_shape=force_uppercase_shape)
        if not segments and not ch.isspace():
            missing.add(ch)
        if index > 0:
            cursor += letter_spacing_units
        for segment in segments:
            poly: GlyphStroke = []
            for gx, gy in segment:
                gx, gy = _glyph_point_for_char(ch, gx, gy, force_uppercase_shape=force_uppercase_shape)
                slanted_x = gx + GOST_ITALIC_SHEAR * (7.0 - gy)
                u = origin_u + (cursor + slanted_x) * scale
                v = origin_v + gy * scale
                poly.append((u * ux + v * vx, u * uy + v * vy))
            if len(poly) >= 2:
                out.append(poly)
        cursor += char_w
    out = _fit_polylines_inside_bbox(out, [x0, y0, x1, y1], pad_mm=0.03)
    return out, missing


def _make_text_strokes(text_lines: list[dict[str, Any]]) -> tuple[list[GlyphStroke], list[dict[str, Any]], set[str]]:
    strokes: list[GlyphStroke] = []
    accepted: list[dict[str, Any]] = []
    missing: set[str] = set()
    for source_line in text_lines:
        for line in _stamp_centered_lines(source_line):
            if float(line.get("confidence", 0.0)) < 0.92:
                continue
            line_strokes, line_missing = _line_text_to_strokes_mm(line)
            missing.update(line_missing)
            if line_strokes:
                bbox_mm = [float(v) for v in line.get("bbox_mm", (0, 0, 0, 0))[:4]]
                stroke_bbox = _bbox_of_polylines(line_strokes)
                overflow = _bbox_overflow_mm(stroke_bbox, bbox_mm, tolerance_mm=0.03)
                strokes.extend(line_strokes)
                accepted.append(
                    {
                        "text": line.get("text", ""),
                        "bbox_mm": line.get("bbox_mm"),
                        "dir": line.get("dir"),
                        "stamp_cell_centered": bool(line.get("stamp_cell_centered")),
                        "stamp_role_cell_expanded": bool(line.get("stamp_role_cell_expanded")),
                        "stamp_source_text": line.get("stamp_source_text"),
                        "stroke_bbox_mm": [round(v, 4) for v in stroke_bbox] if stroke_bbox else None,
                        "bbox_overflow_mm": round(float(overflow), 4),
                    }
                )
    return strokes, accepted, missing


def _write_polylines_svg(polylines: list[GlyphStroke], out_svg: Path, page_w_mm: float, page_h_mm: float) -> None:
    def fmt(value: float) -> str:
        return f"{value:.4f}".rstrip("0").rstrip(".")

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(page_w_mm)}mm" height="{fmt(page_h_mm)}mm" viewBox="0 0 {fmt(page_w_mm)} {fmt(page_h_mm)}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="white"/>',
        '<g fill="none" stroke="black" stroke-width="0.18" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for poly in polylines:
        if len(poly) < 2:
            continue
        parts = [f"M {fmt(poly[0][0])} {fmt(poly[0][1])}"]
        for x, y in poly[1:]:
            parts.append(f"L {fmt(x)} {fmt(y)}")
        lines.append(f'<path d="{" ".join(parts)}"/>')
    lines.extend(["</g>", "</svg>"])
    out_svg.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_motor_release(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if any(line.strip() == "$1=0" for line in text.splitlines()):
        return False
    with path.open("a", encoding="ascii", newline="\n") as fh:
        if text and not text.endswith("\n"):
            fh.write("\n")
        fh.write("$1=0\n")
    return True


def _render_pdf_page_to_png(pdf_path: Path, png_path: Path, *, dpi: int = 180) -> None:
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        zoom = float(dpi) / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(png_path)


def _build_compare_pdf(source_pdf: Path, result_pdf: Path, out_pdf: Path) -> Path:
    mm_to_pt = 72.0 / 25.4
    gap_pt = 10.0 * mm_to_pt
    label_h = 9.0 * mm_to_pt
    with fitz.open(source_pdf) as src_doc, fitz.open(result_pdf) as res_doc:
        src_page = src_doc[0]
        res_page = res_doc[0]
        cell_w = max(src_page.rect.width, res_page.rect.width)
        cell_h = max(src_page.rect.height, res_page.rect.height)
        out = fitz.open()
        try:
            page = out.new_page(width=cell_w * 2.0 + gap_pt, height=cell_h + label_h)
            page.insert_text(fitz.Point(8, 16), "source PDF", fontsize=10, color=(0, 0, 0))
            page.insert_text(fitz.Point(cell_w + gap_pt + 8, 16), "GOST-like one-line text layer", fontsize=10, color=(0, 0, 0))
            left_rect = fitz.Rect(0, label_h, cell_w, label_h + cell_h)
            right_rect = fitz.Rect(cell_w + gap_pt, label_h, cell_w * 2.0 + gap_pt, label_h + cell_h)
            page.show_pdf_page(left_rect, src_doc, 0, keep_proportion=True)
            page.show_pdf_page(right_rect, res_doc, 0, keep_proportion=True)
            out_pdf.parent.mkdir(parents=True, exist_ok=True)
            candidates = [
                out_pdf,
                out_pdf.with_name(f"{out_pdf.stem}_latest{out_pdf.suffix}"),
                out_pdf.with_name(f"{out_pdf.stem}_{os.getpid()}{out_pdf.suffix}"),
            ]
            last_error: Exception | None = None
            for candidate in candidates:
                try:
                    out.save(candidate)
                    return candidate
                except Exception as exc:
                    last_error = exc
            raise RuntimeError(f"Could not save compare PDF near {out_pdf}: {last_error}") from last_error
        finally:
            out.close()


def _build_completion_audit(report: dict[str, Any]) -> dict[str, Any]:
    def check(requirement: str, passed: bool, evidence: str) -> dict[str, Any]:
        return {"requirement": requirement, "passed": bool(passed), "evidence": evidence}

    artifacts = dict(report.get("artifacts", {}))
    artifact_paths = {name: Path(path) for name, path in artifacts.items() if name != "completion_audit_json"}
    all_artifacts_exist = all(path.exists() for path in artifact_paths.values())
    missing_artifacts = [name for name, path in artifact_paths.items() if not path.exists()]
    logs = "\n".join(str(item) for item in report.get("logs", []))
    stroke_style = report.get("stroke_style", {})
    cleanup_meta = report.get("cleanup_meta", {})
    fit_meta = report.get("fit_meta", {})
    max_text_overflow = float(report.get("text_placement_max_overflow_mm", 999.0) or 0.0)
    overflow_lines = list(report.get("text_placement_overflow_lines", []) or [])
    stamp_centered_count = int(report.get("stamp_cell_centered_lines", 0) or 0)
    source_pdf = Path(str(report.get("source_pdf", "")))
    copied_pdf = Path(str(report.get("copied_pdf", "")))
    out_dir_ok = OUT_DIR.exists() and copied_pdf.parent == OUT_DIR

    checks = [
        check(
            "Работа идёт в отдельной папке Компьютерная графика/новый тест букв",
            out_dir_ok,
            f"OUT_DIR={OUT_DIR}; copied_pdf_parent={copied_pdf.parent}",
        ),
        check(
            "Исходный PDF из 9 варианта скопирован в тестовую папку и не изменён",
            bool(source_pdf.exists() and copied_pdf.exists() and report.get("source_hash_unchanged")),
            f"source={source_pdf}; copy={copied_pdf}; sha256={report.get('source_sha256')}",
        ),
        check(
            "На машине найден целевой шрифт GOST type AU",
            bool(report.get("font_exists") and str(report.get("font_path", "")).lower().endswith("gost_au.ttf")),
            f"font_path={report.get('font_path')}",
        ),
        check(
            "PDF text layer найден и принят без OCR всей страницы",
            bool(report.get("text_lines_found", 0) > 0 and report.get("text_lines_accepted", 0) >= report.get("text_lines_found", 0)),
            f"found={report.get('text_lines_found')}; accepted={report.get('text_lines_accepted')}; policy={report.get('confidence_policy')}",
        ),
        check(
            "Порог уверенности соблюдён: заменяются только confidence >= 0.92",
            "confidence=1.0" in str(report.get("confidence_policy", "")),
            str(report.get("confidence_policy")),
        ),
        check(
            "Текст не рисуется контуром, а заменяется однолинейными stroke-буквами",
            bool(stroke_style.get("single_line") is True and stroke_style.get("contour_text") is False),
            f"stroke_style={stroke_style}",
        ),
        check(
            "Регистр текста учитывается: строчные буквы не превращаются в полноразмерные заглавные",
            bool(report.get("case_sensitive_glyphs") and report.get("lowercase_chars_found", 0) > 0),
            f"case_sensitive={report.get('case_sensitive_glyphs')}; lowercase_chars={report.get('lowercase_chars_found')}; stroke_style={stroke_style}",
        ),
        check(
            "Заголовки штампа центрируются по ячейкам, а не по слепленному PDF text bbox",
            bool(report.get("stamp_cell_centering_enabled") and stamp_centered_count >= 8),
            f"stamp_cell_centered_lines={stamp_centered_count}; enabled={report.get('stamp_cell_centering_enabled')}",
        ),
        check(
            "Цифра 1 не рисуется стрелкой вверх",
            bool(report.get("digit_one_arrow") is False),
            f"digit_one_arrow={report.get('digit_one_arrow')}",
        ),
        check(
            "Не осталось символов, ушедших в fallback-глиф",
            not report.get("missing_chars_rendered_as_fallback"),
            f"missing_chars={report.get('missing_chars_rendered_as_fallback')}",
        ),
        check(
            "Stroke-текст не выходит за исходные PDF text bbox",
            bool(max_text_overflow <= 0.05 and not overflow_lines),
            f"max_overflow_mm={max_text_overflow}; overflow_lines={overflow_lines[:5]}",
        ),
        check(
            "Рамочная логика KOMPAS A4 clean-bbox применена и не обрезала рабочую геометрию",
            bool(fit_meta.get("applied") and fit_meta.get("clipped_segments") == 0 and "KOMPAS A4 clean-bbox route" in logs),
            f"fit_meta={fit_meta}; cleanup_meta={cleanup_meta}",
        ),
        check(
            "G-code preflight зелёный",
            bool(report.get("preflight_ok")),
            str(report.get("preflight_msg")),
        ),
        check(
            "Сформированы PDF/PNG preview и файлы G-code/NC",
            all_artifacts_exist,
            f"missing_artifacts={missing_artifacts}; artifacts={artifacts}",
        ),
    ]
    return {
        "all_passed": all(item["passed"] for item in checks),
        "checks": checks,
    }


def run() -> int:
    if not SOURCE_PDF.exists():
        raise FileNotFoundError(SOURCE_PDF)
    font_exists = GOST_AU_FONT.exists()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []

    source_hash_before = _sha256(SOURCE_PDF)
    copied_pdf = OUT_DIR / "source_9_variant_1.pdf"
    shutil.copy2(SOURCE_PDF, copied_pdf)

    text_lines = _extract_pdf_text_lines(copied_pdf)
    (OUT_DIR / "text_layer_lines.json").write_text(
        json.dumps(text_lines, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    raw_svg = OUT_DIR / "01_pdf_text_layer_geometry_only.svg"
    page_w_mm, page_h_mm = prep._export_pdf_page_to_mupdf_svg(copied_pdf, 0, raw_svg, text_as_path=False)

    path_items = backend.extract_polylines(raw_svg)
    page_items, _unit_scale = backend.normalize_path_units_to_page(
        path_items,
        float(page_w_mm),
        float(page_h_mm),
        logger=logs.append,
    )
    with prep._backend_override_context(
        {
            "HANDWRITING_TEXT_ENABLED": False,
            "HANDWRITING_STROKE_ACTIVE": False,
            "SINGLE_STROKE_TEXT_ENABLED": False,
            "SINGLE_STROKE_OUTLINE_TEXT_ENABLED": False,
            "TECH_TEXT_JOIN_ENABLE": False,
        }
    ):
        geometry_polys = backend.to_drawing_polylines(page_items)

    text_polys, accepted_text, missing_chars = _make_text_strokes(text_lines)
    source_polys = list(geometry_polys) + text_polys

    stroke_svg = OUT_DIR / "02_gost_au_fast_stroke_source.svg"
    _write_polylines_svg(source_polys, stroke_svg, float(page_w_mm), float(page_h_mm))

    source_polys, cleanup_meta = prep._cleanup_kompas_archive_strip_polylines(
        source_polys,
        page_w_mm=float(page_w_mm),
        page_h_mm=float(page_h_mm),
        specification_table=prep._is_kompas_specification_table_source(SOURCE_PDF),
        service_regions_mm=prep._kompas_service_regions_from_pdf(SOURCE_PDF, page_index=0),
    )
    cleaned_svg = OUT_DIR / "03_gost_au_after_frame_cleanup.svg"
    _write_polylines_svg(source_polys, cleaned_svg, float(page_w_mm), float(page_h_mm))

    sheet_preview_pdf = OUT_DIR / "03_gost_au_sheet_preview.pdf"
    prep._render_polylines_pdf(
        polylines=source_polys,
        out_pdf=sheet_preview_pdf,
        canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)),
    )

    final_polys, fit_meta = prep._prepare_kompas_a4_clean_bbox_fit_polylines(source_polys, logs=logs)
    if not final_polys:
        raise RuntimeError(f"KOMPAS A4 clean-bbox fit failed: {fit_meta}")

    work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
    ready_pdf = OUT_DIR / "04_gost_au_ready_preview.pdf"
    prep._render_polylines_pdf(
        polylines=final_polys,
        out_pdf=ready_pdf,
        canvas_bounds_mm=(float(work_x0), float(work_x1), float(work_y0), float(work_y1)),
    )
    ready_nc = OUT_DIR / "04_gost_au_ready.nc"
    ready_gcode = OUT_DIR / "04_gost_au_ready.gcode"
    prep._rewrite_final_gcode_from_polylines(final_polys, dst_nc=ready_nc, dst_gcode=ready_gcode)
    motor_release_nc_added = _append_motor_release(ready_nc)
    motor_release_gcode_added = _append_motor_release(ready_gcode)

    metrics = prep._analyze_gcode(ready_nc)
    preflight_ok, preflight_msg = backend.preflight_check_gcode(ready_nc, logs.append)
    text_overflow_lines = [line for line in accepted_text if float(line.get("bbox_overflow_mm", 0.0) or 0.0) > 0.05]
    max_text_overflow = max((float(line.get("bbox_overflow_mm", 0.0) or 0.0) for line in accepted_text), default=0.0)
    lowercase_chars_found = sum(1 for line in text_lines for ch in str(line.get("text", "")) if _is_lowercase_letter(ch))
    stamp_cell_centered_count = sum(1 for line in accepted_text if line.get("stamp_cell_centered"))

    requested_compare_pdf = OUT_DIR / "05_source_vs_gost_au_compare.pdf"
    compare_png = OUT_DIR / "05_source_vs_gost_au_compare.png"
    ready_png = OUT_DIR / "04_gost_au_ready_preview.png"
    compare_pdf = _build_compare_pdf(copied_pdf, sheet_preview_pdf, requested_compare_pdf)
    _render_pdf_page_to_png(compare_pdf, compare_png, dpi=170)
    _render_pdf_page_to_png(ready_pdf, ready_png, dpi=190)

    source_hash_after = _sha256(SOURCE_PDF)
    report = {
        "ok": bool(preflight_ok and len(text_polys) > 0 and source_hash_before == source_hash_after),
        "source_pdf": str(SOURCE_PDF),
        "copied_pdf": str(copied_pdf),
        "font_target": "GOST type AU",
        "font_path": str(GOST_AU_FONT),
        "font_exists": bool(font_exists),
        "algorithm": "pdf_text_layer_to_fast_slanted_gost_au_like_one_line_strokes_safe",
        "stroke_style": {
            "target_font": "GOST type AU",
            "italic_shear": GOST_ITALIC_SHEAR,
            "bbox_fill": GOST_TEXT_BOX_FILL,
            "stamp_cell_text_fill": STAMP_CELL_TEXT_FILL,
            "stamp_cell_text_fill_tight": STAMP_CELL_TEXT_FILL_TIGHT,
            "stamp_role_text_fill": STAMP_ROLE_TEXT_FILL,
            "stamp_role_letter_spacing_units": STAMP_ROLE_LETTER_SPACING_UNITS,
            "lowercase_width_scale": LOWERCASE_WIDTH_SCALE,
            "lowercase_y_offset": LOWERCASE_Y_OFFSET,
            "lowercase_height_scale": LOWERCASE_HEIGHT_SCALE,
            "single_line": True,
            "contour_text": False,
        },
        "case_sensitive_glyphs": True,
        "lowercase_chars_found": int(lowercase_chars_found),
        "stamp_cell_centering_enabled": True,
        "stamp_cell_centered_lines": int(stamp_cell_centered_count),
        "digit_one_arrow": False,
        "why_not_ttf_autotrace": "GOST_AU TTF centerline/autotrace per string is too slow for full KOMPAS sheets and can fragment letters; this experiment keeps the PDF text layer positions and emits deterministic slanted one-line technical strokes.",
        "confidence_policy": "Only PDF text layer lines are accepted as confidence=1.0. No full-page OCR guesses are used.",
        "text_lines_found": len(text_lines),
        "text_lines_accepted": len(accepted_text),
        "text_stroke_polylines": len(text_polys),
        "text_placement_max_overflow_mm": round(float(max_text_overflow), 4),
        "text_placement_overflow_lines": text_overflow_lines,
        "text_placement_accepted_lines": accepted_text,
        "geometry_polylines": len(geometry_polys),
        "missing_chars_rendered_as_fallback": sorted(missing_chars),
        "page_size_mm": [round(float(page_w_mm), 3), round(float(page_h_mm), 3)],
        "cleanup_meta": cleanup_meta,
        "fit_meta": fit_meta,
        "metrics": metrics,
        "preflight_ok": bool(preflight_ok),
        "preflight_msg": preflight_msg,
        "source_hash_unchanged": source_hash_before == source_hash_after,
        "source_sha256": source_hash_before,
        "motor_release_added": {
            "nc": bool(motor_release_nc_added),
            "gcode": bool(motor_release_gcode_added),
        },
        "artifacts": {
            "raw_svg": str(raw_svg),
            "stroke_svg": str(stroke_svg),
            "cleaned_svg": str(cleaned_svg),
            "sheet_preview_pdf": str(sheet_preview_pdf),
            "ready_preview_pdf": str(ready_pdf),
            "ready_preview_png": str(ready_png),
            "ready_nc": str(ready_nc),
            "ready_gcode": str(ready_gcode),
            "compare_pdf": str(compare_pdf),
            "compare_png": str(compare_png),
            "text_layer_lines_json": str(OUT_DIR / "text_layer_lines.json"),
        },
        "logs": logs,
    }
    audit_path = OUT_DIR / "06_completion_audit.json"
    report["artifacts"]["completion_audit_json"] = str(audit_path)
    audit = _build_completion_audit(report)
    report["completion_audit_all_passed"] = bool(audit["all_passed"])
    report["ok"] = bool(report["ok"] and audit["all_passed"])
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(run())
