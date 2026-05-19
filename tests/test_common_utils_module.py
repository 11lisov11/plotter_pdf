from __future__ import annotations

import re
import tempfile
import types
import unittest
from pathlib import Path

from src.plotter_backend import common_utils


class _AxisBackend:
    def __init__(self, primary: Path, fallback: Path) -> None:
        self.AXIS_PROFILE_PATH = primary
        self.AXIS_PROFILE_FALLBACK_PATH = fallback
        self.AXIS_INVERT_X = None
        self.AXIS_INVERT_Y = None


class CommonUtilsModuleTests(unittest.TestCase):
    def test_strip_unpaired_surrogates_and_safe_log_text(self) -> None:
        raw = "ok" + "\ud800" + "done"
        self.assertEqual(common_utils.strip_unpaired_surrogates(raw, replacement="?"), "ok?done")
        self.assertEqual(common_utils.safe_log_text(raw), "ok?done")

    def test_repair_mojibake_text_recovers_cyrillic_paths(self) -> None:
        self.assertEqual(common_utils.repair_mojibake_text("РљРѕРјРїСЊСЋС‚РµСЂРЅР°СЏ РіСЂР°С„РёРєР°"), "Компьютерная графика")
        cleaned = common_utils.clean_report_value({"path": "РљРќР“.01.20.01 - РњР°С…РѕРІРёРє"})
        self.assertEqual(cleaned["path"], "КНГ.01.20.01 - Маховик")

    def test_resolve_bundle_and_work_root(self) -> None:
        fake_sys = types.SimpleNamespace(_MEIPASS="C:/bundle", frozen=False, executable="C:/bin/app.exe")
        bundle = common_utils.resolve_bundle_root(file_path="C:/repo/src/plotter_pdf_drawer.py", sys_module=fake_sys)
        work = common_utils.resolve_work_root(bundle, sys_module=fake_sys)
        self.assertEqual(bundle, Path("C:/bundle"))
        self.assertEqual(work, Path("C:/bundle"))

        fake_sys2 = types.SimpleNamespace(frozen=True, executable="C:/app/app.exe")
        bundle2 = common_utils.resolve_bundle_root(file_path="C:/repo/src/plotter_pdf_drawer.py", sys_module=fake_sys2)
        work2 = common_utils.resolve_work_root(bundle2, sys_module=fake_sys2)
        self.assertEqual(work2, Path("C:/app"))

    def test_load_axis_profile_prefers_primary_and_applies_defaults(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_axis_profile_") as td:
            root = Path(td)
            primary = root / "axis_profile.json"
            fallback = root / "axis_profile_fallback.json"
            primary.write_text('{"axis":{"invert_x":true}}', encoding="utf-8")
            backend = _AxisBackend(primary, fallback)
            common_utils.load_axis_profile(backend)
            self.assertTrue(backend.AXIS_INVERT_X)
            self.assertFalse(backend.AXIS_INVERT_Y)

    def test_svg_basic_parsers(self) -> None:
        self.assertEqual(common_utils.tag_name("{urn:test}path", tag_re=re.compile(r".*}(.*)")), "path")
        self.assertEqual(common_utils.parse_floats("1,-2 3.5", float_re=re.compile(r"[-+]?(?:\d*\.\d+|\d+)")), [1.0, -2.0, 3.5])
        self.assertEqual(common_utils.parse_length("12.5mm", length_re=re.compile(r"^\s*([-+]?\d*\.?\d+)([a-zA-Z%]*)\s*$")), (12.5, "mm"))
        self.assertAlmostEqual(common_utils.unit_to_mm(96.0, "px"), 25.4)
