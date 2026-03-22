from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend import runtime_utils


class RuntimeUtilsModuleTests(unittest.TestCase):
    def test_format_duration_hms_formats_minutes_and_hours(self) -> None:
        self.assertEqual(runtime_utils.format_duration_hms(5.2), "00:05")
        self.assertEqual(runtime_utils.format_duration_hms(65.0), "01:05")
        self.assertEqual(runtime_utils.format_duration_hms(3661.0), "01:01:01")

    def test_format_internal_exception_includes_type_name(self) -> None:
        message = runtime_utils.format_internal_exception("Failure", ValueError("bad"))
        self.assertEqual(message, "Failure (ValueError): bad")

    def test_ensure_local_tmp_root_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_runtime_") as td:
            target = Path(td) / "nested" / "tmp"
            resolved = runtime_utils.ensure_local_tmp_root(target)
            self.assertEqual(resolved, target)
            self.assertTrue(target.is_dir())

    def test_wait_until_path_unlocked_succeeds_for_missing_and_existing_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_runtime_unlock_") as td:
            root = Path(td)
            missing = root / "missing.txt"
            existing = root / "existing.txt"
            existing.write_text("ok", encoding="utf-8")

            self.assertTrue(runtime_utils.wait_until_path_unlocked(missing, timeout_s=0.2, poll_s=0.05))
            self.assertTrue(runtime_utils.wait_until_path_unlocked(existing, timeout_s=0.2, poll_s=0.05))
