from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.plotter_backend import toe_font_policy


class ToeFontPolicyModuleTests(unittest.TestCase):
    def test_resolve_toe_handwriting_profiles_reads_existing_fonts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="toe_font_policy_") as td:
            root = Path(td)
            fonts_dir = root / "data" / "fonts"
            fonts_dir.mkdir(parents=True, exist_ok=True)
            (fonts_dir / "MarckScript-Regular.ttf").write_bytes(b"font")
            (fonts_dir / "BadScript-Regular.ttf").write_bytes(b"font")
            profiles = toe_font_policy.resolve_toe_handwriting_profiles(root)
        self.assertEqual(
            profiles,
            [
                ("Marck Script", fonts_dir / "MarckScript-Regular.ttf"),
                ("Bad Script", fonts_dir / "BadScript-Regular.ttf"),
            ],
        )

    def test_filter_toe_handwriting_profiles_defaults_to_primary_profile(self) -> None:
        profiles = [
            ("Marck Script", Path("marck.ttf")),
            ("Bad Script", Path("bad.ttf")),
            ("Neucha", Path("neucha.ttf")),
        ]
        filtered = toe_font_policy.filter_toe_handwriting_profiles(profiles, [])
        self.assertEqual(filtered, [("Marck Script", Path("marck.ttf"))])

    def test_toe_profile_for_source_stem_uses_known_variant_or_default(self) -> None:
        self.assertEqual(
            toe_font_policy.toe_profile_for_source_stem("TOE_Zadachi_1_2_Variant_25").label,
            "Marck Script",
        )
        self.assertEqual(
            toe_font_policy.toe_profile_for_source_stem("unknown_variant").label,
            "Marck Script",
        )

    def test_toe_font_first_policy_backend_settings_are_centralized(self) -> None:
        settings = toe_font_policy.toe_font_first_policy().backend_settings(Path("body.ttf"))
        self.assertTrue(settings["HANDWRITING_TEXT_ENABLED"])
        self.assertEqual(settings["HANDWRITING_FONT_FAMILY"], "body.ttf")
        self.assertEqual(settings["HANDWRITING_SINGLELINE_TTF_BACKEND"], "autotrace3")
        self.assertTrue(settings["HANDWRITING_CYRILLIC_PREFER_TTF"])
        self.assertTrue(settings["HANDWRITING_ALLOW_TTF_FALLBACK"])
        self.assertEqual(settings["IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE"], "centerline")
        self.assertTrue(settings["IMAGE_CONTOUR_FORMULA_OCR_ENABLED"])
        self.assertEqual(settings["IMAGE_CONTOUR_FORMULA_OCR_MIN_CONFIDENCE"], 0.88)
        self.assertEqual(settings["TOOL_MODE"], "pencil")


if __name__ == "__main__":
    unittest.main()
