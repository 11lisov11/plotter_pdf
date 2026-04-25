from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import validate_drawing_packages as mod


def _write_ready_a4_package(package: Path, *, selected_variant: str = "fit_full") -> None:
    package.mkdir(parents=True)
    (package / "logs").mkdir()
    (package / "pages").mkdir()
    for name in ("a4_clean_source.pdf", "page_01.pdf", "source_vs_gcode_compare.pdf", "source_vs_gcode_compare.png"):
        (package / name).write_bytes(b"%PDF-1.4\n")
    gcode = "\n".join(
        [
            "G21",
            "G90",
            "G0 Z0.0000",
            "G0 X0.0000 Y0.0000",
            "G1 Z11.9000 F1000.0",
            "G1 X10.0000 Y-10.0000 F1000.0",
            "G0 Z0.0000",
            "M2",
        ]
    )
    (package / "page_01.gcode").write_text(gcode, encoding="utf-8")
    (package / "page_01.nc").write_text(gcode, encoding="utf-8")
    (package / "pages" / "page_01.gcode").write_text(gcode, encoding="utf-8")
    (package / "report.json").write_text(
        mod.json.dumps(
            {
                "frame_class": "kompas_full_frame",
                "route_class": "A4 drawing with full KOMPAS frame",
                "selected_variant": selected_variant,
                "selection_reason": "test",
                "source_fidelity_score": 0.99,
                "fragmentation_score": 0.99,
                "compare_generated": True,
                "a3_two_pass": False,
                "custom_tiled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (package / "summary.csv").write_text(
        "pen_down_strokes,tiny_strokes_lt_08_mm,point_like_strokes\n1,0,0\n",
        encoding="utf-8",
    )


def test_validate_ready_a4_kompas_package(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "Компьютерная графика" / "20 вариант" / "Sheet_pack"
    _write_ready_a4_package(package)
    monkeypatch.setattr(mod.backend, "preflight_check_gcode", lambda *_args, **_kwargs: (True, "ok"))

    result = mod.validate_package(package)

    assert result["ok"] is True
    assert result["preflight"]["checked_files"] == 3
    assert result["pen_start"]["failed"] == 0
    assert result["duplicates"]["duplicate_segments"] == 0


def test_validate_rejects_forbidden_kompas_hybrid_variant(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "Компьютерная графика" / "20 вариант" / "Sheet_pack"
    _write_ready_a4_package(package, selected_variant="a4_hybrid_frame")
    monkeypatch.setattr(mod.backend, "preflight_check_gcode", lambda *_args, **_kwargs: (True, "ok"))

    result = mod.validate_package(package)

    assert result["ok"] is False
    assert any(issue["code"] == "bad_kompas_variant" for issue in result["issues"])


def test_first_xy_pen_down_issue_detects_bad_start(tmp_path: Path) -> None:
    gcode = tmp_path / "bad.gcode"
    gcode.write_text(
        "\n".join(
            [
                "G21",
                "G90",
                "G1 Z11.9000 F1000.0",
                "G1 X10.0000 Y-10.0000 F1000.0",
            ]
        ),
        encoding="utf-8",
    )

    issue = mod.first_xy_pen_down_issue(gcode)

    assert issue is not None
    assert issue["line"] == 4


def test_ready_to_plot_scope_manifest_defines_release_contract() -> None:
    manifest = mod.json.loads((PROJECT_ROOT / "ready_to_plot_scope.json").read_text(encoding="utf-8"))

    production_roots = manifest["production_roots"]
    assert sum(root["expected_packages"] for root in production_roots) == 68
    assert {root["class"] for root in production_roots} == {"kompas_full_frame", "standard_frame"}

    reference_only = {entry["path"] for entry in manifest["reference_only"]}
    assert "Компьютерная графика/Задание" in reference_only
    assert manifest["acceptance"]["required_validator_result"] == {
        "ok": True,
        "failed_count": 0,
        "warning_count": 0,
    }
