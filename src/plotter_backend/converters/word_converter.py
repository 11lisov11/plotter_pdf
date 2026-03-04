from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from ..errors import ConversionError, PipelineValidationError, ToolDependencyError


def normalize_word_font_name(font_name: Optional[str], default: str = "") -> str:
    raw = str(font_name or "").strip().strip("'").strip('"')
    if not raw:
        return str(default or "").strip()
    stem = Path(raw).stem if raw.lower().endswith((".ttf", ".otf", ".ttc")) else ""
    candidates: List[str] = []
    if stem:
        candidates.append(stem)
        candidates.append(stem.replace("_", " "))
        if stem.lower().startswith("ofont.ru_"):
            short = stem.split("_", 1)[1]
            candidates.append(short)
            candidates.append(short.replace("_", " "))
    candidates.append(raw)
    for cand in candidates:
        name = str(cand or "").strip()
        if name:
            return name
    return str(default or "").strip()


def apply_word_formula_font(doc, formula_font: Optional[str], logger, *, handwriting_word_keep_math: bool) -> int:
    apply_math = bool(formula_font) or bool(handwriting_word_keep_math)
    if not apply_math:
        return 0
    target_math = normalize_word_font_name(formula_font, default="Cambria Math")
    restored_math = 0
    try:
        omaths = getattr(doc, "OMaths", None)
        count = int(getattr(omaths, "Count", 0) or 0) if omaths is not None else 0
        for i in range(1, count + 1):
            try:
                rng = omaths.Item(i).Range
                rng.Font.Name = target_math
                try:
                    rng.Font.NameAscii = target_math
                    rng.Font.NameFarEast = target_math
                    rng.Font.NameOther = target_math
                except Exception:
                    pass
                restored_math += 1
            except Exception:
                continue
    except Exception:
        restored_math = 0
    if restored_math > 0:
        logger(f"Word export: formula font '{target_math}', runs={restored_math}")
    return restored_math


def apply_word_handwriting_font(
    doc,
    font_name: str,
    logger,
    *,
    normalize_handwriting_font_name,
    handwriting_word_keep_math: bool,
    math_font: Optional[str] = None,
) -> tuple[bool, int]:
    target = normalize_word_font_name(font_name, default=normalize_handwriting_font_name(font_name))
    try:
        doc.Content.Font.Name = target
        try:
            doc.Content.Font.NameAscii = target
            doc.Content.Font.NameFarEast = target
            doc.Content.Font.NameOther = target
        except Exception:
            pass
    except Exception as exc:
        logger(f"Word handwriting mode warning: cannot force font '{target}': {exc}")
        return False, 0

    restored_math = apply_word_formula_font(
        doc,
        math_font,
        logger,
        handwriting_word_keep_math=handwriting_word_keep_math,
    )
    logger(
        f"Word handwriting mode: forcing font '{target}' before PDF export; "
        f"math_runs_restored={restored_math}"
    )
    return True, restored_math


def word_to_pdf(
    word_path: Path,
    pdf_path: Path,
    logger,
    *,
    normalize_handwriting_font_name,
    pdf_text_questionmark_metrics,
    handwriting_word_max_qmark_count: int,
    handwriting_word_max_qmark_ratio: float,
    handwriting_word_keep_math: bool,
    wait_until_path_unlocked_fn,
    override_font: Optional[str] = None,
    formula_font: Optional[str] = None,
) -> None:
    logger("Converting Word file to PDF ...")

    if word_path.suffix.lower() not in {".doc", ".docx"}:
        raise PipelineValidationError(f"Expected Word file (.doc/.docx), got: {word_path}")

    word_abs = word_path.resolve()
    pdf_abs = pdf_path.resolve()
    pdf_abs.parent.mkdir(parents=True, exist_ok=True)

    try:
        import win32com.client
    except Exception as exc:
        raise ToolDependencyError("pywin32 is required to convert Word files. Install with: pip install pywin32") from exc

    pythoncom = None
    try:
        import pythoncom as _pythoncom  # type: ignore

        _pythoncom.CoInitialize()
        pythoncom = _pythoncom
    except Exception:
        pythoncom = None

    word_busy_codes = {-2147418111, -2147417846}
    max_attempts = 6

    def _contains_busy_code(value: object) -> bool:
        if isinstance(value, int):
            return value in word_busy_codes
        if isinstance(value, (tuple, list)):
            for item in value:
                if _contains_busy_code(item):
                    return True
        return False

    def _is_word_busy_error(exc: Exception) -> bool:
        text = str(exc).lower()
        if "call was rejected" in text or "вызов был отклонен" in text or "server busy" in text:
            return True
        hresult = getattr(exc, "hresult", None)
        if _contains_busy_code(hresult):
            return True
        return _contains_busy_code(getattr(exc, "args", ()))

    def _retry_delay_s(attempt: int) -> float:
        return min(2.0, 0.30 * float(attempt))

    app = None
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                # Isolate conversion from an interactive Word session.
                app = win32com.client.DispatchEx("Word.Application")
                break
            except Exception as exc:
                if attempt >= max_attempts or not _is_word_busy_error(exc):
                    raise
                delay_s = _retry_delay_s(attempt)
                logger(
                    f"Word COM busy during app startup; retry {attempt}/{max_attempts} "
                    f"in {delay_s:.2f}s."
                )
                time.sleep(delay_s)
        if app is None:
            raise ConversionError("Word COM startup failed without explicit exception.")

        app.Visible = False
        app.DisplayAlerts = 0

        def _export_once(font_override: Optional[str]) -> None:
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                doc = None
                try:
                    try:
                        if pdf_abs.exists():
                            pdf_abs.unlink()
                    except Exception:
                        pass

                    doc = app.Documents.Open(
                        str(word_abs),
                        ConfirmConversions=False,
                        ReadOnly=False,
                        AddToRecentFiles=False,
                    )
                    if font_override:
                        # Apply in-memory only (document is closed without save).
                        apply_word_handwriting_font(
                            doc,
                            font_override,
                            logger,
                            math_font=formula_font,
                            normalize_handwriting_font_name=normalize_handwriting_font_name,
                            handwriting_word_keep_math=handwriting_word_keep_math,
                        )
                    elif formula_font:
                        apply_word_formula_font(
                            doc,
                            formula_font,
                            logger,
                            handwriting_word_keep_math=handwriting_word_keep_math,
                        )
                    # Word Export format constants:
                    # 17 = wdExportFormatPDF
                    # Keep call minimal/positional for compatibility across Office versions.
                    doc.ExportAsFixedFormat(str(pdf_abs), 17)
                    if not pdf_abs.exists() or pdf_abs.stat().st_size == 0:
                        raise ConversionError(f"Word->PDF produced no output: {pdf_abs}")
                    return
                except Exception as exc:
                    last_exc = exc
                    if attempt >= max_attempts or not _is_word_busy_error(exc):
                        raise
                    delay_s = _retry_delay_s(attempt)
                    logger(
                        f"Word COM busy during export; retry {attempt}/{max_attempts} "
                        f"in {delay_s:.2f}s."
                    )
                    time.sleep(delay_s)
                finally:
                    if doc is not None:
                        try:
                            doc.Close(False)
                        except Exception:
                            pass
            if last_exc is not None:
                raise last_exc

        # First pass: requested mode (with optional handwriting font).
        _export_once(override_font if override_font else None)

        # Safety fallback: if forced handwriting font produced many "?" symbols,
        # re-export with native fonts to preserve readable content.
        if override_font:
            qm = pdf_text_questionmark_metrics(pdf_abs, logger=logger)
            if qm is not None:
                ratio, qmarks, meaningful = qm
                if qmarks >= int(handwriting_word_max_qmark_count) and ratio >= float(handwriting_word_max_qmark_ratio):
                    logger(
                        "Word handwriting mode warning: exported PDF looks garbled "
                        f"(qmarks={qmarks}/{meaningful}, ratio={ratio:.3f}). "
                        "Retrying export with native fonts to preserve text."
                    )
                    _export_once(None)
    except Exception as exc:
        raise ConversionError(f"Word conversion failed: {exc}") from exc
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
        if not wait_until_path_unlocked_fn(pdf_abs, timeout_s=8.0, poll_s=0.25):
            logger(
                "Warning: Word->PDF output file is still locked after export. "
                "Continuing with best effort."
            )

