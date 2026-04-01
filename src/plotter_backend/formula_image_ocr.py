from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:
    cv2 = None
    np = None

try:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore
except Exception:
    RapidOCR = None


@dataclass(frozen=True)
class FormulaOCRLine:
    text: str
    confidence: float
    bbox_px: tuple[float, float, float, float]


@dataclass(frozen=True)
class FormulaOCRResult:
    lines: tuple[FormulaOCRLine, ...]
    confidence: float
    variant: str
    engine: str


_FORMULA_OPERATOR_RE = re.compile(r"[=+\-*/()|[\]{}<>]")
_R_REPLACEMENT_RE = re.compile(r"(?<![A-Za-z])R\(")
_IM_REPLACEMENT_RE = re.compile(r"(?<![A-Za-z])[3J]\(")
_ABS_S_RE = re.compile(r"\bI?S[|I)\]]\b")
_EQ_LOAD_RE = re.compile(r"\bZe[gq]\b", flags=re.IGNORECASE)
_SUSPICIOUS_FORMULA_RE = re.compile(
    r"(?:[\[\]\{\}]|(?:^|[ ,])I[iIl1]?\|=\||\bIU\d|\blacos\b|[А-Яа-яЁё])",
    flags=re.IGNORECASE,
)

_RAPIDOCR_ENGINE: Optional[object] = None
_RAPIDOCR_ENGINE_READY = False


def rapidocr_available() -> bool:
    return RapidOCR is not None and cv2 is not None and np is not None


def _get_rapidocr_engine() -> Optional[object]:
    global _RAPIDOCR_ENGINE, _RAPIDOCR_ENGINE_READY
    if _RAPIDOCR_ENGINE_READY:
        return _RAPIDOCR_ENGINE
    _RAPIDOCR_ENGINE_READY = True
    if not rapidocr_available():
        _RAPIDOCR_ENGINE = None
        return None
    try:
        _RAPIDOCR_ENGINE = RapidOCR()
    except Exception:
        _RAPIDOCR_ENGINE = None
    return _RAPIDOCR_ENGINE


def _sanitize_formula_text(text: str) -> str:
    out = str(text or "").strip()
    if not out:
        return ""
    out = (
        out.replace("—", "-")
        .replace("–", "-")
        .replace("−", "-")
        .replace("×", "*")
        .replace("÷", "/")
    )
    out = re.sub(r"\s+", " ", out, flags=re.UNICODE).strip()
    out = _R_REPLACEMENT_RE.sub("Re(", out)
    out = _IM_REPLACEMENT_RE.sub("Im(", out)
    out = _ABS_S_RE.sub("|S|", out)
    out = _EQ_LOAD_RE.sub("Zeq", out)
    out = out.replace("Eq/", "Eq,")
    out = out.replace(" var", " var")
    out = re.sub(r"\s+([,.;:)\]])", r"\1", out)
    out = re.sub(r"([(\[])\s+", r"\1", out)
    out = re.sub(r"\s+([=+*/])\s+", r" \1 ", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()


def _formula_signal_score(text: str) -> float:
    compact = re.sub(r"\s+", "", str(text or ""), flags=re.UNICODE)
    if not compact:
        return 0.0
    digits = sum(1 for ch in compact if ch.isdigit())
    alpha = sum(1 for ch in compact if ch.isalpha())
    ops = len(_FORMULA_OPERATOR_RE.findall(compact))
    score = 0.0
    score += min(10, digits) * 0.035
    score += min(8, ops) * 0.055
    score += min(12, alpha) * 0.015
    score += min(80, len(compact)) * 0.002
    return score


def _formula_text_is_safe(text: str, *, confidence: float) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""), flags=re.UNICODE)
    if not compact:
        return False
    if confidence < 0.84:
        return False
    if _SUSPICIOUS_FORMULA_RE.search(text):
        return False
    if compact.count("|") >= 4 and confidence < 0.90:
        return False
    return True


def _bbox_from_quad(quad: object, *, scale_back: float) -> tuple[float, float, float, float]:
    pts = list(quad or [])
    xs = [float(pt[0]) / max(1e-9, scale_back) for pt in pts if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    ys = [float(pt[1]) / max(1e-9, scale_back) for pt in pts if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    if not xs or not ys:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _run_rapidocr(engine: object, image_array: "np.ndarray") -> list[FormulaOCRLine]:
    if cv2 is None or np is None:
        return []
    try:
        result, _ = engine(image_array)
    except Exception:
        return []
    if not result:
        return []
    lines: list[FormulaOCRLine] = []
    for item in result:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        quad, raw_text, confidence = item[0], item[1], item[2]
        text = _sanitize_formula_text(str(raw_text or ""))
        if len(text) < 4:
            continue
        bbox = _bbox_from_quad(quad, scale_back=1.0)
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        lines.append(
            FormulaOCRLine(
                text=text,
                confidence=float(confidence or 0.0),
                bbox_px=bbox,
            )
        )
    lines.sort(key=lambda line: (round(line.bbox_px[1], 2), round(line.bbox_px[0], 2)))
    return lines


def _rescaled_lines(lines: list[FormulaOCRLine], *, scale_back: float) -> list[FormulaOCRLine]:
    out: list[FormulaOCRLine] = []
    for line in lines:
        x0, y0, x1, y1 = line.bbox_px
        out.append(
            FormulaOCRLine(
                text=_sanitize_formula_text(line.text),
                confidence=line.confidence,
                bbox_px=(
                    x0 / max(1e-9, scale_back),
                    y0 / max(1e-9, scale_back),
                    x1 / max(1e-9, scale_back),
                    y1 / max(1e-9, scale_back),
                ),
            )
        )
    return out


def _iter_preprocessed_variants(img: "np.ndarray") -> list[tuple[str, "np.ndarray", float]]:
    if cv2 is None or np is None:
        return []
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
    except Exception:
        return []
    variants: list[tuple[str, "np.ndarray", float]] = [("orig", img, 1.0)]
    try:
        variants.append(("inv_gray", cv2.bitwise_not(gray), 1.0))
    except Exception:
        pass
    try:
        up = cv2.resize(img, dsize=None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        variants.append(("up2", up, 2.0))
    except Exception:
        pass
    return variants


def ocr_formula_image(img: "np.ndarray") -> Optional[FormulaOCRResult]:
    engine = _get_rapidocr_engine()
    if engine is None or cv2 is None or np is None or img is None:
        return None

    best: Optional[FormulaOCRResult] = None
    best_score = -1e30
    for variant_label, arr, scale_back in _iter_preprocessed_variants(img):
        lines = _run_rapidocr(engine, arr)
        if not lines:
            continue
        lines = _rescaled_lines(lines, scale_back=scale_back)
        avg_conf = sum(line.confidence for line in lines) / float(len(lines))
        text_blob = " ".join(line.text for line in lines)
        signal = _formula_signal_score(text_blob)
        score = avg_conf + signal
        if score > best_score:
            best_score = score
            best = FormulaOCRResult(
                lines=tuple(lines),
                confidence=float(avg_conf),
                variant=str(variant_label),
                engine="rapidocr",
            )

    if best is None:
        return None
    if best.confidence < 0.72:
        return None
    if _formula_signal_score(" ".join(line.text for line in best.lines)) < 0.36:
        return None
    if not all(_formula_text_is_safe(line.text, confidence=line.confidence) for line in best.lines):
        return None
    return best
