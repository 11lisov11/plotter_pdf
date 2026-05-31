from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Tuple


def _resolve_first_existing_tool(candidates: Iterable[str], *, which=shutil.which) -> Optional[str]:
    for candidate in candidates:
        found = which(candidate)
        if found:
            return str(Path(found))
        if Path(candidate).is_file():
            return str(Path(candidate))
    return None


def find_inkscape(
    candidates: Sequence[str],
    *,
    which=shutil.which,
    dependency_error_cls=RuntimeError,
) -> str:
    resolved = _resolve_first_existing_tool(candidates, which=which)
    if resolved:
        return resolved
    raise dependency_error_cls("Inkscape not found. Install and add it to PATH.")


def find_pdftocairo(
    candidates: Sequence[str],
    *,
    which=shutil.which,
    dependency_error_cls=RuntimeError,
) -> str:
    resolved = _resolve_first_existing_tool(candidates, which=which)
    if resolved:
        return resolved
    raise dependency_error_cls("pdftocairo not found.")


def find_pdftotext(
    candidates: Sequence[str],
    *,
    find_pdftocairo: Callable[[], str],
    which=shutil.which,
    dependency_error_cls=RuntimeError,
) -> str:
    resolved = _resolve_first_existing_tool(candidates, which=which)
    if resolved:
        return resolved

    # Common case: pdftocairo is discoverable and pdftotext sits in the same Poppler bin.
    try:
        cairo = Path(find_pdftocairo())
        siblings = [
            cairo.with_name("pdftotext.exe"),
            cairo.with_name("pdftotext"),
        ]
        for candidate in siblings:
            if candidate.is_file():
                return str(candidate)
    except Exception:
        pass

    raise dependency_error_cls("pdftotext not found.")


def detect_com_port(
    preferred: Optional[str] = None,
    *,
    default_port: str,
    ports: Optional[Sequence[object]] = None,
    serial_factory: Optional[Callable[..., object]] = None,
) -> str:
    if ports is None:
        try:
            import serial.tools.list_ports  # type: ignore
        except Exception:
            return preferred or default_port
        ports = list(serial.tools.list_ports.comports())

    if serial_factory is None:
        try:
            import serial  # type: ignore
        except Exception:
            serial_factory = None
        else:
            serial_factory = serial.Serial

    if not ports:
        return preferred or default_port

    available = {str(getattr(p, "device", "") or "").upper(): str(getattr(p, "device", "") or "") for p in ports if getattr(p, "device", None)}

    def _com_num(device: str) -> int:
        match = re.match(r"COM(\d+)$", str(device).upper())
        if not match:
            return 10**9
        try:
            return int(match.group(1))
        except Exception:
            return 10**9

    def _is_writable(device: str) -> bool:
        if serial_factory is None:
            return False
        try:
            conn = serial_factory(device, 115200, timeout=0.2, write_timeout=0.2)
            close = getattr(conn, "close", None)
            if callable(close):
                close()
            return True
        except Exception:
            return False

    if preferred:
        selected = available.get(preferred.upper())
        if selected:
            return selected

    bt_ports = []
    for port in ports:
        text = " ".join(
            [
                str(getattr(port, "description", "") or ""),
                str(getattr(port, "manufacturer", "") or ""),
                str(getattr(port, "hwid", "") or ""),
            ]
        ).lower()
        if "bluetooth" in text or "rfcomm" in text or "bthenum" in text:
            bt_ports.append(str(getattr(port, "device", "") or ""))

    for device in sorted(set(bt_ports), key=_com_num):
        if device and _is_writable(device):
            return device

    for candidate in ("COM6", "COM5", "COM4", "COM3", "COM7", "COM8", "COM9", "COM10"):
        selected = available.get(candidate)
        if selected:
            return selected

    devices = sorted((str(getattr(p, "device", "") or "") for p in ports if getattr(p, "device", None)), key=_com_num)
    if devices:
        return devices[0]
    return preferred or default_port


def get_inkscape_version(
    exe: str,
    *,
    run_cmd: Callable[..., Tuple[int, str, str]],
) -> Tuple[int, int, int]:
    rc, out, err = run_cmd([exe, "--version"], timeout_s=10.0)
    text = (out + "\n" + err).strip()
    match = re.search(r"Inkscape\s*v?(\d+)\.(\d+)(?:\.(\d+))?", text, re.IGNORECASE)
    if not match:
        return 1, 0, 0
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return major, minor, patch


def pdf_text_questionmark_metrics(
    pdf_path: Path,
    *,
    find_pdftotext: Callable[[], str],
    run_cmd: Callable[..., Tuple[int, str, str]],
    ensure_local_tmp_root: Callable[[], Path],
    logger=print,
) -> Optional[Tuple[float, int, int]]:
    try:
        exe = find_pdftotext()
    except Exception:
        return None

    with tempfile.TemporaryDirectory(dir=str(ensure_local_tmp_root()), ignore_cleanup_errors=True) as td:
        txt_path = Path(td) / "text.txt"
        cmd = [exe, "-q", "-enc", "UTF-8", str(pdf_path), str(txt_path)]
        rc, out, err = run_cmd(cmd, timeout_s=25.0)
        if rc != 0 or not txt_path.exists():
            block = (out + "\n" + err).strip()
            if block:
                logger(f"pdftotext warning: {block[:300]}")
            return None
        try:
            text = txt_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    if not text:
        return None

    qmarks = text.count("?")
    qmarks += text.count("\ufffd")
    meaningful = sum(1 for ch in text if not ch.isspace())
    if meaningful <= 0:
        return None
    ratio = float(qmarks) / float(meaningful)
    return ratio, qmarks, meaningful
