from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str = ""
    manufacturer: str = ""
    hwid: str = ""

    @property
    def label(self) -> str:
        details = " ".join(part for part in [self.description, self.manufacturer] if part).strip()
        return f"{self.device} - {details}" if details else self.device

    @property
    def search_text(self) -> str:
        return " ".join([self.device, self.description, self.manufacturer, self.hwid]).lower()


def _com_num(device: str) -> int:
    match = re.match(r"COM(\d+)$", str(device).upper())
    if not match:
        return 10**9
    try:
        return int(match.group(1))
    except Exception:
        return 10**9


def _port_info_from_obj(port: object) -> SerialPortInfo:
    return SerialPortInfo(
        device=str(getattr(port, "device", "") or ""),
        description=str(getattr(port, "description", "") or ""),
        manufacturer=str(getattr(port, "manufacturer", "") or ""),
        hwid=str(getattr(port, "hwid", "") or ""),
    )


def list_serial_ports(*, ports: Optional[Sequence[object]] = None) -> list[SerialPortInfo]:
    if ports is None:
        try:
            import serial.tools.list_ports  # type: ignore
        except Exception:
            return []
        ports = list(serial.tools.list_ports.comports())
    infos = [_port_info_from_obj(port) for port in ports]
    return sorted([info for info in infos if info.device], key=lambda info: _com_num(info.device))


def _plotter_port_score(info: SerialPortInfo) -> int:
    text = info.search_text
    score = 0
    weighted_keywords = [
        ("grbl", 120),
        ("plotter", 110),
        ("arduino", 90),
        ("ch340", 85),
        ("wch", 80),
        ("usb-serial", 75),
        ("usb serial", 75),
        ("cp210", 70),
        ("silicon labs", 70),
        ("ftdi", 70),
        ("usb serial device", 60),
        ("usb", 30),
    ]
    for keyword, weight in weighted_keywords:
        if keyword in text:
            score += weight
    if "bluetooth" in text or "rfcomm" in text or "bthenum" in text:
        score -= 25
    return score


def suggest_plotter_port(preferred: Optional[str] = None, *, ports: Optional[Sequence[object]] = None) -> Optional[str]:
    infos = list_serial_ports(ports=ports)
    if not infos:
        return preferred or None
    available = {info.device.upper(): info.device for info in infos}
    if preferred:
        selected = available.get(str(preferred).upper())
        if selected:
            return selected
    if len(infos) == 1:
        return infos[0].device
    scored = sorted(infos, key=lambda info: (-_plotter_port_score(info), _com_num(info.device)))
    if scored and _plotter_port_score(scored[0]) > 0:
        return scored[0].device
    return infos[0].device


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
