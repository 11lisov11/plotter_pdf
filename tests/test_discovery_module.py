from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend import discovery
from src.plotter_backend.errors import ToolDependencyError


class _Port:
    def __init__(self, device: str, *, description: str = "", manufacturer: str = "", hwid: str = "") -> None:
        self.device = device
        self.description = description
        self.manufacturer = manufacturer
        self.hwid = hwid


class _Conn:
    def close(self) -> None:
        return None


class DiscoveryModuleTests(unittest.TestCase):
    def test_get_inkscape_version_parses_semver_and_falls_back_when_missing(self) -> None:
        parsed = discovery.get_inkscape_version(
            "inkscape.exe",
            run_cmd=lambda *_args, **_kwargs: (0, "Inkscape 1.3.2 (091e20ef0f, 2023-11-25)", ""),
        )
        self.assertEqual(parsed, (1, 3, 2))

        fallback = discovery.get_inkscape_version(
            "inkscape.exe",
            run_cmd=lambda *_args, **_kwargs: (0, "unexpected output", ""),
        )
        self.assertEqual(fallback, (1, 0, 0))

    def test_find_pdftotext_uses_sibling_of_pdftocairo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_discovery_") as td:
            root = Path(td)
            cairo = root / "pdftocairo.exe"
            text = root / "pdftotext.exe"
            cairo.write_text("", encoding="utf-8")
            text.write_text("", encoding="utf-8")

            resolved = discovery.find_pdftotext(
                ["Z:/missing/pdftotext.exe"],
                find_pdftocairo=lambda: str(cairo),
                which=lambda _candidate: None,
                dependency_error_cls=ToolDependencyError,
            )

            self.assertEqual(Path(resolved), text)

    def test_pdf_text_questionmark_metrics_counts_questionmarks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_discovery_qm_") as td:
            root = Path(td)

            def _run_cmd(cmd, **_kwargs):
                out_path = Path(cmd[-1])
                out_path.write_text("abc??\n", encoding="utf-8")
                return 0, "", ""

            result = discovery.pdf_text_questionmark_metrics(
                root / "sample.pdf",
                find_pdftotext=lambda: "pdftotext.exe",
                run_cmd=_run_cmd,
                ensure_local_tmp_root=lambda: root,
                logger=lambda _msg: None,
            )

            self.assertEqual(result, (0.4, 2, 5))

    def test_detect_com_port_prefers_writable_bluetooth_port(self) -> None:
        ports = [
            _Port("COM6", description="USB Serial Device"),
            _Port("COM11", description="Standard Serial over Bluetooth link", hwid="BTHENUM\\X"),
        ]

        def serial_factory(device: str, *_args, **_kwargs):
            if device == "COM11":
                return _Conn()
            raise OSError("busy")

        resolved = discovery.detect_com_port(
            default_port="COM6",
            ports=ports,
            serial_factory=serial_factory,
        )

        self.assertEqual(resolved, "COM11")

    def test_detect_com_port_falls_back_to_known_usb_order_then_default(self) -> None:
        ports = [
            _Port("COM9", description="USB Serial Device"),
            _Port("COM7", description="USB Serial Device"),
        ]

        resolved = discovery.detect_com_port(
            default_port="COM6",
            ports=ports,
            serial_factory=lambda *_args, **_kwargs: (_Conn()),
        )
        self.assertEqual(resolved, "COM7")

        resolved_empty = discovery.detect_com_port(
            preferred=None,
            default_port="COM6",
            ports=[],
            serial_factory=lambda *_args, **_kwargs: (_Conn()),
        )
        self.assertEqual(resolved_empty, "COM6")

    def test_suggest_plotter_port_uses_preferred_if_available(self) -> None:
        ports = [
            _Port("COM3", description="USB-SERIAL CH340"),
            _Port("COM4", description="Arduino Uno"),
        ]

        resolved = discovery.suggest_plotter_port("COM4", ports=ports)

        self.assertEqual(resolved, "COM4")

    def test_suggest_plotter_port_selects_likely_usb_plotter(self) -> None:
        ports = [
            _Port("COM3", description="Standard Serial over Bluetooth link", hwid="BTHENUM\\X"),
            _Port("COM9", description="USB-SERIAL CH340", manufacturer="wch.cn"),
        ]

        resolved = discovery.suggest_plotter_port(None, ports=ports)

        self.assertEqual(resolved, "COM9")

    def test_suggest_plotter_port_selects_single_port(self) -> None:
        resolved = discovery.suggest_plotter_port(None, ports=[_Port("COM7", description="USB Serial Device")])

        self.assertEqual(resolved, "COM7")
