from __future__ import annotations

import importlib.util
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from ..errors import ConversionError, PipelineValidationError, ToolDependencyError

KOMPAS_PDF2D_DLLS = (
    Path(r"C:\Program Files\ASCON\KOMPAS-3D v23 Study\Bin\Pdf2d.dll"),
    Path(r"C:\Program Files\ASCON\KOMPAS-3D v24 Study\Bin\Pdf2d.dll"),
    Path(r"C:\Program Files\ASCON\KOMPAS-3D v22 Study\Bin\Pdf2d.dll"),
)

def wait_for_nonempty_file(path: Path, timeout_s: float = 15.0, poll_s: float = 0.25, stable_polls: int = 2) -> bool:
    deadline = time.time() + max(0.1, float(timeout_s))
    poll = max(0.05, float(poll_s))
    stable_need = max(1, int(stable_polls))
    last_size = -1
    stable = 0

    while time.time() < deadline:
        try:
            if path.exists():
                sz = int(path.stat().st_size)
                if sz > 0:
                    if sz == last_size:
                        stable += 1
                    else:
                        stable = 1
                    last_size = sz
                    if stable >= stable_need:
                        return True
        except Exception:
            pass
        time.sleep(poll)
    return False


def _looks_like_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(5) == b"%PDF-"
    except Exception:
        return False


def kompas_print_to_pdf(
    input_path: Path,
    output_pdf: Path,
    logger,
    *,
    wait_for_nonempty_file_fn: Optional[Callable[..., bool]] = None,
) -> None:
    import win32com.client

    wait_for_nonempty = wait_for_nonempty_file_fn or wait_for_nonempty_file
    pythoncom = None
    try:
        import pythoncom as _pythoncom  # type: ignore

        _pythoncom.CoInitialize()
        pythoncom = _pythoncom
    except Exception:
        pythoncom = None

    app = None
    try:
        app = None
        last_exc: Optional[Exception] = None
        for progid in ("KOMPAS.Application.7", "KOMPAS.Application.5", "KOMPAS.Application"):
            try:
                logger(f"KOMPAS dispatch: {progid}")
                app = win32com.client.gencache.EnsureDispatch(progid)
                break
            except Exception as exc:
                last_exc = exc
                app = None
                try:
                    logger(f"KOMPAS dispatch fallback: {progid}")
                    app = win32com.client.Dispatch(progid)
                    break
                except Exception as dispatch_exc:
                    last_exc = dispatch_exc
                    app = None
        if app is None:
            raise ToolDependencyError(f"KOMPAS COM application is unavailable: {last_exc}")

        try:
            app.Visible = False
        except Exception:
            pass
        try:
            app.SuppressAlerts = True
        except Exception:
            pass

        for converter_dll in KOMPAS_PDF2D_DLLS:
            if not converter_dll.exists():
                continue
            try:
                logger(f"KOMPAS Pdf2d converter: {converter_dll}")
                converter = app.Converter(str(converter_dll))
                for command in range(0, 6):
                    try:
                        if output_pdf.exists():
                            output_pdf.unlink()
                    except Exception:
                        pass
                    logger(f"Pdf2d.Convert (command {command}): {input_path} -> {output_pdf}")
                    result = converter.Convert(str(input_path), str(output_pdf), command, False)
                    logger(f"Pdf2d.Convert result (command {command}): {result!r}")
                    if wait_for_nonempty(output_pdf, timeout_s=6.0) and _looks_like_pdf(output_pdf):
                        return
            except Exception as exc:
                logger(f"Warning: Pdf2d converter failed: {type(exc).__name__}: {exc}")

        try:
            print_job = app.PrintJob
        except Exception as exc:
            raise ConversionError("KOMPAS PrintJob is unavailable.") from exc

        for attempt in range(1, 4):
            try:
                if output_pdf.exists():
                    output_pdf.unlink()
            except Exception:
                pass
            try:
                print_job.Clear()
            except Exception:
                pass

            logger(f"PrintJob.AddSheets (attempt {attempt}): {input_path}")
            print_job.AddSheets(str(input_path), 0, 0)
            logger(f"PrintJob.Execute (attempt {attempt}): {output_pdf}")
            result = print_job.Execute(str(output_pdf))
            logger(f"PrintJob.Execute result (attempt {attempt}): {result!r}")

            if wait_for_nonempty(output_pdf, timeout_s=18.0) and _looks_like_pdf(output_pdf):
                return
            time.sleep(0.6)

        raise ConversionError(f"KOMPAS PrintJob completed without PDF output: {output_pdf}")
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


def frw_to_pdf(
    frw_path: Path,
    pdf_path: Path,
    logger,
    *,
    ensure_local_tmp_root: Callable[[], Path],
    find_spec: Optional[Callable[[str], object]] = None,
    kompas_print_to_pdf_fn: Optional[Callable[[Path, Path, object], None]] = None,
    wait_for_nonempty_file_fn: Optional[Callable[..., bool]] = None,
) -> None:
    logger("Converting CAD file to PDF ...")

    if frw_path.suffix.lower() not in {".frw", ".cdw"}:
        raise PipelineValidationError(f"Expected CAD file (.frw/.cdw), got: {frw_path}")

    frw_abs = frw_path.resolve()
    pdf_abs = pdf_path.resolve()
    pdf_abs.parent.mkdir(parents=True, exist_ok=True)
    if not frw_abs.exists():
        raise PipelineValidationError(f"CAD file not found: {frw_abs}")

    find_spec_fn = find_spec or importlib.util.find_spec
    wait_for_nonempty = wait_for_nonempty_file_fn or wait_for_nonempty_file
    kompas_print = kompas_print_to_pdf_fn or kompas_print_to_pdf

    if find_spec_fn("win32com.client") is None:
        raise ToolDependencyError("pywin32 is required to convert CAD formats. Install with: pip install pywin32")

    primary_error: Optional[Exception] = None
    try:
        # KOMPAS can fail on non-ASCII source paths depending on locale/settings.
        # Copy to a short ASCII temp name first.
        with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
            work = Path(td)
            src_local = work / f"source{frw_abs.suffix.lower()}"
            out_local = work / "export.pdf"
            shutil.copyfile(str(frw_abs), str(src_local))

            kompas_print(src_local, out_local, logger)
            if not wait_for_nonempty(out_local, timeout_s=6.0):
                raise ConversionError(f"CAD->PDF produced no output: {out_local}")

            shutil.copyfile(str(out_local), str(pdf_abs))
            if not wait_for_nonempty(pdf_abs, timeout_s=2.0):
                raise ConversionError(f"Failed to finalize CAD PDF output: {pdf_abs}")
            return
    except Exception as exc:
        primary_error = exc
        logger(f"Warning: primary CAD conversion failed ({type(exc).__name__}): {exc}")

    # Fallback: if source folder already has an exported PDF with same stem, reuse it.
    fallback_pdf = frw_abs.with_suffix(".pdf")
    if fallback_pdf.exists() and wait_for_nonempty(fallback_pdf, timeout_s=0.5):
        logger(f"Using fallback PDF next to source: {fallback_pdf}")
        shutil.copyfile(str(fallback_pdf), str(pdf_abs))
        if wait_for_nonempty(pdf_abs, timeout_s=2.0):
            return

    if primary_error is not None:
        raise ConversionError(
            f"CAD conversion failed ({type(primary_error).__name__}): {primary_error}"
        ) from primary_error
    raise ConversionError("CAD conversion failed: unknown error")
