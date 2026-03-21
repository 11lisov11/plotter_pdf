from __future__ import annotations

import unittest

from src.plotter_backend.machine import windows_bt_spp as bt_spp_mod


class WindowsBluetoothSppTests(unittest.TestCase):
    def test_build_serial_open_hint_mentions_rfcomm_code_and_fallback(self) -> None:
        hint = bt_spp_mod.build_serial_open_hint(
            "COM11",
            diagnostics={
                "preferred_port": "COM11",
                "preferred_port_live": False,
                "recommended_port": "COM6",
                "ghost_spp_ports": ["COM11", "COM12"],
                "rfcomm_failed_start": True,
                "rfcomm_problem_code": 10,
                "btwriter_paired": True,
                "summary": "Windows Bluetooth RFCOMM failed to start (Code 10); ghost SPP port(s): COM11, COM12; working fallback port: COM6.",
            },
        )

        self.assertIn("COM11", hint)
        self.assertIn("Code 10", hint)
        self.assertIn("COM6", hint)
        self.assertIn("bt_spp_recovery.py", hint)

    def test_summarize_reports_stale_mapping_when_btwriter_is_paired(self) -> None:
        summary = bt_spp_mod.summarize_windows_bt_spp_issue(
            {
                "preferred_port": "COM11",
                "preferred_port_live": False,
                "recommended_port": "COM6",
                "ghost_spp_ports": ["COM11"],
                "rfcomm_failed_start": False,
                "btwriter_paired": True,
                "collection_error": "",
            }
        )

        self.assertIn("BtWriter is paired", summary)
        self.assertIn("COM11", summary)
        self.assertIn("COM6", summary)


if __name__ == "__main__":
    unittest.main()
