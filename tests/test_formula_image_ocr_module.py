from __future__ import annotations

import unittest
from unittest import mock

from src.plotter_backend import formula_image_ocr as mod


class FormulaImageOCRModuleTests(unittest.TestCase):
    def test_sanitize_formula_text_normalizes_common_math_tokens(self) -> None:
        text = "P=R(S)=55.416 W, Q= 3(S)=-81.618 var, ISI=98.653 VA"
        self.assertEqual(
            mod._sanitize_formula_text(text),
            "P=Re(S)=55.416 W, Q= Im(S)=-81.618 var, |S|=98.653 VA",
        )

    def test_formula_signal_score_rewards_formula_like_content(self) -> None:
        self.assertGreater(mod._formula_signal_score("S=U17*I1=-78.52-j2.7"), 0.5)
        self.assertLess(mod._formula_signal_score("обычный текст"), 0.5)

    def test_formula_text_is_safe_rejects_suspicious_ocr_artifacts(self) -> None:
        self.assertFalse(mod._formula_text_is_safe("Ii|=| -0.67-j1.06|= 1.256 A", confidence=0.91))
        self.assertFalse(mod._formula_text_is_safe("Pw= Uvlacos ОІ= 78.564", confidence=0.91))
        self.assertTrue(mod._formula_text_is_safe("P=Re(S)=55.416 W, Q= Im(S)=-81.618 var", confidence=0.91))

    def test_ocr_formula_image_picks_best_variant_and_rescales_boxes(self) -> None:
        if mod.np is None:
            self.skipTest("numpy unavailable")

        img = mod.np.zeros((12, 24, 3), dtype=mod.np.uint8)
        fake_engine = object()

        def _fake_run(engine, image_array):
            self.assertIs(engine, fake_engine)
            width = int(image_array.shape[1])
            if width >= 40:
                return [
                    mod.FormulaOCRLine(
                        text="P=R(S)=55.416 W, Q= 3(S)=-81.618 var, ISI=98.653 VA",
                        confidence=0.91,
                        bbox_px=(4.0, 2.0, 40.0, 10.0),
                    )
                ]
            return [
                mod.FormulaOCRLine(
                    text="обычный текст",
                    confidence=0.74,
                    bbox_px=(2.0, 2.0, 20.0, 10.0),
                )
            ]

        with (
            mock.patch.object(mod, "_get_rapidocr_engine", return_value=fake_engine),
            mock.patch.object(mod, "_run_rapidocr", side_effect=_fake_run),
        ):
            result = mod.ocr_formula_image(img)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.variant, "up2")
        self.assertGreaterEqual(result.confidence, 0.9)
        self.assertEqual(result.lines[0].text, "P=Re(S)=55.416 W, Q= Im(S)=-81.618 var, |S|=98.653 VA")
        self.assertEqual(result.lines[0].bbox_px, (2.0, 1.0, 20.0, 5.0))

    def test_ocr_formula_image_rejects_low_signal_result(self) -> None:
        if mod.np is None:
            self.skipTest("numpy unavailable")

        img = mod.np.zeros((12, 24, 3), dtype=mod.np.uint8)
        fake_engine = object()
        weak_lines = [mod.FormulaOCRLine(text="abc", confidence=0.98, bbox_px=(1.0, 1.0, 10.0, 5.0))]

        with (
            mock.patch.object(mod, "_get_rapidocr_engine", return_value=fake_engine),
            mock.patch.object(mod, "_run_rapidocr", return_value=weak_lines),
        ):
            result = mod.ocr_formula_image(img)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
