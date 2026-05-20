from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts import sender_guard


class SenderGuardTests(unittest.TestCase):
    def test_find_sender_processes_filters_by_port_and_file(self) -> None:
        rows = [
            {
                "ProcessId": 10,
                "CommandLine": r'python D:\plotter_pdf\src\send_grbl_file.py COM6 115200 D:\plotter_pdf\job.nc',
            },
            {
                "ProcessId": 11,
                "CommandLine": r'python D:\plotter_pdf\src\send_grbl_file.py COM7 115200 D:\plotter_pdf\job.nc',
            },
            {"ProcessId": 12, "CommandLine": "python other.py"},
        ]

        found = sender_guard.find_sender_processes(
            port="COM6",
            file_path=r"D:\plotter_pdf\job.nc",
            process_rows=rows,
            current_pid=99,
        )

        self.assertEqual([proc.pid for proc in found], [10])

    def test_find_sender_processes_matches_relative_and_absolute_file_forms(self) -> None:
        rows = [
            {
                "ProcessId": 10,
                "CommandLine": r'python D:\plotter_pdf\src\send_grbl_file.py COM6 115200 job.nc',
            }
        ]

        found = sender_guard.find_sender_processes(
            port="COM6",
            file_path=r"D:\plotter_pdf\job.nc",
            process_rows=rows,
            current_pid=99,
        )

        self.assertEqual([proc.pid for proc in found], [10])

    def test_stop_sender_processes_uses_stop_process(self) -> None:
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        ok, msg = sender_guard.stop_sender_processes(
            [sender_guard.SenderProcess(123, "python send_grbl_file.py COM6 115200 job.nc")],
            run=fake_run,
        )

        self.assertTrue(ok)
        self.assertIn("123", msg)
        self.assertIn("Stop-Process -Id 123 -Force", " ".join(calls[0][0]))


if __name__ == "__main__":
    unittest.main()
