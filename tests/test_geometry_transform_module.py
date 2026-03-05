from __future__ import annotations

import unittest

from src.plotter_backend.geometry import transform as transform_mod


class GeometryTransformModuleTests(unittest.TestCase):
    def test_mat_apply_translation(self) -> None:
        m = (1.0, 0.0, 0.0, 1.0, 10.0, -3.0)
        p = transform_mod.mat_apply(m, (2.5, 4.0))
        self.assertEqual(p, (12.5, 1.0))

    def test_mat_mul_composition_order(self) -> None:
        translate = (1.0, 0.0, 0.0, 1.0, 5.0, 7.0)
        scale = (2.0, 0.0, 0.0, 3.0, 0.0, 0.0)
        composed = transform_mod.mat_mul(translate, scale)
        # mat_mul(a, b) composes as b * a
        out = transform_mod.mat_apply(composed, (1.0, 1.0))
        self.assertEqual(out, (12.0, 24.0))

    def test_parse_transform_rotate_about_center(self) -> None:
        m = transform_mod.parse_transform("rotate(90 1 1)")
        x, y = transform_mod.mat_apply(m, (2.0, 1.0))
        self.assertAlmostEqual(x, 1.0, places=6)
        self.assertAlmostEqual(y, 2.0, places=6)

    def test_parse_transform_identity_for_empty_and_unknown(self) -> None:
        self.assertEqual(transform_mod.parse_transform(""), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
        self.assertEqual(
            transform_mod.parse_transform("unsupported(10)"),
            (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        )

    def test_parse_points_accepts_commas_spaces_and_exponents(self) -> None:
        pts = transform_mod.parse_points("1,2 3 4 -1e1,5e-1")
        self.assertEqual(pts, [(1.0, 2.0), (3.0, 4.0), (-10.0, 0.5)])

    def test_transform_points_applies_matrix_then_scale(self) -> None:
        pts = [(1.0, 1.0), (2.0, 3.0)]
        matrix = transform_mod.parse_transform("translate(1,2) scale(2)")
        out = transform_mod.transform_points(pts, matrix, 0.5)
        self.assertEqual(out, [(2.0, 3.0), (3.0, 5.0)])


if __name__ == "__main__":
    unittest.main()

