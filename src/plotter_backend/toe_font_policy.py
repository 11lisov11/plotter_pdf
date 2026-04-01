from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_TOE_FONT_LABELS = ["Marck Script"]
DEFAULT_FORMULA_FONT_FAMILY = "Times New Roman"
DEFAULT_FORMULA_FONT_PATH_CANDIDATES = ("times.ttf", "cambria.ttc", "arial.ttf")

DEFAULT_HANDWRITING_BACKEND = "autotrace3"
DEFAULT_IMAGE_CONTOUR_MODE = "always"
DEFAULT_IMAGE_VECTORIZE_MODE = "centerline"
DEFAULT_FORMULA_VECTORIZE_MODE = "centerline"
DEFAULT_FORMULA_OCR_ENABLED = True
DEFAULT_FORMULA_OCR_MIN_CONFIDENCE = 0.88
DEFAULT_TOOL_MODE = "pencil"


@dataclass(frozen=True)
class ToeHandwritingProfile:
    label: str
    filename: str
    description: str
    default: bool = False


@dataclass(frozen=True)
class ToeFontFirstPolicy:
    formula_font_family: str = DEFAULT_FORMULA_FONT_FAMILY
    handwriting_backend: str = DEFAULT_HANDWRITING_BACKEND
    image_contours_mode: str = DEFAULT_IMAGE_CONTOUR_MODE
    image_vectorize_mode: str = DEFAULT_IMAGE_VECTORIZE_MODE
    formula_vectorize_mode: str = DEFAULT_FORMULA_VECTORIZE_MODE
    formula_ocr_enabled: bool = DEFAULT_FORMULA_OCR_ENABLED
    formula_ocr_min_confidence: float = DEFAULT_FORMULA_OCR_MIN_CONFIDENCE
    tool_mode: str = DEFAULT_TOOL_MODE
    direct_vector_text_enabled: bool = True
    handwriting_text_enabled: bool = True
    cyrillic_prefer_ttf: bool = True
    allow_ttf_fallback: bool = True

    def backend_settings(self, font_path: Path | str) -> dict[str, object]:
        return {
            "HANDWRITING_TEXT_ENABLED": bool(self.handwriting_text_enabled),
            "HANDWRITING_FONT_FAMILY": str(font_path),
            "HANDWRITING_CYRILLIC_FONT_FAMILY": str(font_path),
            "HANDWRITING_SINGLELINE_TTF_BACKEND": str(self.handwriting_backend),
            "HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED": bool(self.direct_vector_text_enabled),
            "HANDWRITING_CYRILLIC_PREFER_TTF": bool(self.cyrillic_prefer_ttf),
            "HANDWRITING_ALLOW_TTF_FALLBACK": bool(self.allow_ttf_fallback),
            "IMAGE_CONTOUR_MODE": str(self.image_contours_mode),
            "IMAGE_CONTOUR_ENABLED": True,
            "IMAGE_CONTOUR_WORD_ONLY": False,
            "IMAGE_CONTOUR_VECTORIZE_MODE": str(self.image_vectorize_mode),
            "IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE": str(self.formula_vectorize_mode),
            "IMAGE_CONTOUR_FORMULA_OCR_ENABLED": bool(self.formula_ocr_enabled),
            "IMAGE_CONTOUR_FORMULA_OCR_MIN_CONFIDENCE": float(self.formula_ocr_min_confidence),
            "FORCE_TEXT_TO_PATH": False,
            "USE_INKSCAPE_PDF_IMPORT": False,
            "EXACT_GEOMETRY_MODE": False,
            "MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW": 0.0,
            "SAFE_PEN_TRAVEL_UP": False,
            "TOOL_MODE": str(self.tool_mode),
        }


TOE_HANDWRITING_PROFILES: tuple[ToeHandwritingProfile, ...] = (
    ToeHandwritingProfile(
        label="Marck Script",
        filename="MarckScript-Regular.ttf",
        description="Primary TOE handwriting profile.",
        default=True,
    ),
    ToeHandwritingProfile(
        label="Bad Script",
        filename="BadScript-Regular.ttf",
        description="Livelier fallback handwriting profile.",
    ),
    ToeHandwritingProfile(
        label="Caveat",
        filename="Caveat-wght.ttf",
        description="Soft fallback handwriting profile.",
    ),
    ToeHandwritingProfile(
        label="Neucha",
        filename="Neucha.ttf",
        description="Cleaner fallback handwriting profile.",
    ),
)


KNOWN_TOE_VARIANT_PROFILE_LABELS: dict[str, str] = {
    "TOE_Zadachi_1_2_Variant_4": "Marck Script",
    "TOE_Zadachi_1_2_Variant_11": "Marck Script",
    "TOE_Zadachi_1_2_Variant_14": "Marck Script",
    "TOE_Zadachi_1_2_Variant_25": "Marck Script",
    "TOE_Zadachi_1_2_Variant_26": "Marck Script",
}


def toe_fonts_dir(project_root: Path) -> Path:
    return Path(project_root) / "data" / "fonts"


def toe_font_first_policy() -> ToeFontFirstPolicy:
    return ToeFontFirstPolicy()


def toe_profile_for_source_stem(source_stem: str) -> ToeHandwritingProfile:
    requested = KNOWN_TOE_VARIANT_PROFILE_LABELS.get(str(source_stem or "").strip(), DEFAULT_TOE_FONT_LABELS[0])
    for profile in TOE_HANDWRITING_PROFILES:
        if profile.label == requested:
            return profile
    return TOE_HANDWRITING_PROFILES[0]


def resolve_toe_handwriting_profiles(project_root: Path) -> list[tuple[str, Path]]:
    fonts_dir = toe_fonts_dir(project_root)
    out: list[tuple[str, Path]] = []
    for profile in TOE_HANDWRITING_PROFILES:
        path = fonts_dir / profile.filename
        if path.exists() and path.is_file():
            out.append((profile.label, path))
    if not out:
        raise FileNotFoundError("No candidate handwriting fonts found in data/fonts.")
    return out


def filter_toe_handwriting_profiles(
    profiles: Sequence[tuple[str, Path]],
    selected_labels: Iterable[str],
    *,
    default_labels: Sequence[str] | None = None,
) -> list[tuple[str, Path]]:
    requested = [str(label or "").strip().lower() for label in selected_labels if str(label or "").strip()]
    if not requested:
        requested = [str(label).strip().lower() for label in (default_labels or DEFAULT_TOE_FONT_LABELS)]
    if not requested:
        return list(profiles)
    requested_set = set(requested)
    filtered = [(label, path) for label, path in profiles if str(label).strip().lower() in requested_set]
    if not filtered:
        raise FileNotFoundError(f"Requested font labels not found: {', '.join(str(label) for label in selected_labels)}")
    return filtered
