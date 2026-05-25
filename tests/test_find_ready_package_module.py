from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.find_ready_package import find_first_ready_package, _normalize_item, _normalize_kind


def _write_minimal_ready_variant(tmp_path: Path) -> tuple[Path, Path]:
    variant = tmp_path / "Компьютерная графика" / "22 вариант"
    first = variant / "КНГ.01.20.01 - Маховик_pack"
    second = variant / "МЧ00.60.00.00 Вентиль_pack"
    first.mkdir(parents=True)
    second.mkdir()
    nc = first / "page_01.nc"
    nc.write_text("G21\nG90\nG0 X0 Y0\n", encoding="utf-8")
    with (first / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["item", "ok", "nc", "gcode", "preview_pdf", "preview_svg", "bounds", "draw_length_m"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "item": "page_01",
                "ok": "True",
                "nc": str(nc),
                "gcode": str(first / "page_01.gcode"),
                "preview_pdf": str(first / "page_01.pdf"),
                "preview_svg": str(first / "page_01.svg"),
                "bounds": "0.000..180.000 x, -285.000..-5.000 y",
                "draw_length_m": "7.197",
            }
        )
    (variant / "_ready_to_plot_audit.json").write_text(
        json.dumps({"ok": True, "failed_packages": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (variant / "_audit.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "task": "КНГ.01.20.01 - Маховик_pack",
                        "kind": "a4",
                        "package_dir": str(first),
                        "layout_similarity": 0.948414,
                        "selected_variant": "mupdf_svg_paths",
                    },
                    {"task": "МЧ00.60.00.00 Вентиль_pack", "kind": "a4", "package_dir": str(second)},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return variant, nc


def test_find_first_ready_a4_package_uses_audit_order_and_summary(tmp_path: Path) -> None:
    variant, nc = _write_minimal_ready_variant(tmp_path)

    selection = find_first_ready_package(variant, kind="a4")

    assert selection.task == "КНГ.01.20.01 - Маховик_pack"
    assert selection.nc == str(nc)
    assert selection.line_count == 3
    assert selection.draw_length_m == 7.197


def test_find_first_ready_package_accepts_utf8_sig_reports(tmp_path: Path) -> None:
    variant, nc = _write_minimal_ready_variant(tmp_path)
    package = nc.parent
    (package / "summary.csv").write_text(
        "\ufeffitem,ok,nc,draw_length_m\n"
        f"page_01,True,{nc},7.197\n",
        encoding="utf-8",
    )
    audit_text = (variant / "_audit.json").read_text(encoding="utf-8")
    (variant / "_audit.json").write_text("\ufeff" + audit_text, encoding="utf-8")
    ready_text = (variant / "_ready_to_plot_audit.json").read_text(encoding="utf-8")
    (variant / "_ready_to_plot_audit.json").write_text("\ufeff" + ready_text, encoding="utf-8")

    selection = find_first_ready_package(variant, kind="a4")

    assert selection.nc == str(nc)
    assert selection.draw_length_m == 7.197


def test_find_first_ready_package_requires_ready_audit(tmp_path: Path) -> None:
    variant, _nc = _write_minimal_ready_variant(tmp_path)
    (variant / "_ready_to_plot_audit.json").unlink()

    try:
        find_first_ready_package(variant, kind="a4")
    except RuntimeError as exc:
        assert "_ready_to_plot_audit.json" in str(exc)
    else:
        raise AssertionError("missing ready audit must reject ready package selection")


def test_find_first_ready_package_rejects_string_false_ready_audit(tmp_path: Path) -> None:
    variant, _nc = _write_minimal_ready_variant(tmp_path)
    (variant / "_ready_to_plot_audit.json").write_text(
        json.dumps({"ok": "false", "failed_packages": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    try:
        find_first_ready_package(variant, kind="a4")
    except RuntimeError as exc:
        assert "_ready_to_plot_audit.json" in str(exc)
    else:
        raise AssertionError("string false ready audit must reject ready package selection")


def test_find_first_ready_package_selects_requested_a3_item(tmp_path: Path) -> None:
    variant = tmp_path / "Компьютерная графика" / "22 вариант"
    package = variant / "МЧ00.60.00.00 СБ Вентиль_pack"
    package.mkdir(parents=True)
    pass_01 = package / "pass_01.nc"
    pass_02 = package / "pass_02.nc"
    pass_01.write_text("G0 X0 Y0\n", encoding="utf-8")
    pass_02.write_text("G0 X2 Y2\nG1 X3 Y3\n", encoding="utf-8")
    with (package / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["item", "ok", "nc", "gcode", "preview_pdf", "preview_svg", "bounds", "draw_length_m"],
        )
        writer.writeheader()
        writer.writerow({"item": "pass_01", "ok": "True", "nc": str(pass_01), "draw_length_m": "6.7"})
        writer.writerow({"item": "pass_02", "ok": "True", "nc": str(pass_02), "draw_length_m": "6.9"})
    (variant / "_audit.json").write_text(
        json.dumps(
            {"items": [{"task": package.name, "kind": "a3_two_pass", "package_dir": str(package)}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (variant / "_ready_to_plot_audit.json").write_text(
        json.dumps({"ok": True, "failed_packages": []}),
        encoding="utf-8",
    )

    selection = find_first_ready_package(variant, kind="a3", item="pass_02")

    assert selection.item == "pass_02"
    assert selection.nc == str(pass_02)
    assert selection.line_count == 2


def test_find_first_ready_package_replaces_stale_external_nc_with_local_file(tmp_path: Path) -> None:
    variant, local_nc = _write_minimal_ready_variant(tmp_path)
    external = tmp_path / "old" / "page_01.nc"
    external.parent.mkdir()
    external.write_text("G0 X99 Y99\n", encoding="utf-8")
    package = local_nc.parent
    with (package / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["item", "ok", "nc", "draw_length_m"])
        writer.writeheader()
        writer.writerow({"item": "page_01", "ok": "True", "nc": str(external), "draw_length_m": "1.0"})

    selection = find_first_ready_package(variant, kind="a4")

    assert selection.nc == str(local_nc)
    assert selection.line_count == 3


def test_find_first_ready_package_resolves_side_artifacts_from_pages_fallback(tmp_path: Path) -> None:
    variant, local_nc = _write_minimal_ready_variant(tmp_path)
    package = local_nc.parent
    pages_dir = package / "pages"
    pages_dir.mkdir()
    page_gcode = pages_dir / "page_01.gcode"
    page_pdf = pages_dir / "page_01.pdf"
    page_svg = pages_dir / "page_01.svg"
    page_gcode.write_text("G0 X0 Y0\n", encoding="utf-8")
    page_pdf.write_text("%PDF\n", encoding="utf-8")
    page_svg.write_text("<svg />", encoding="utf-8")
    stale_dir = tmp_path / "old_root" / package.name / "pages"
    stale_dir.mkdir(parents=True)
    with (package / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["item", "ok", "nc", "gcode", "preview_pdf", "preview_svg", "draw_length_m"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "item": "page_01",
                "ok": "True",
                "nc": str(local_nc),
                "gcode": str(stale_dir / "page_01.gcode"),
                "preview_pdf": str(stale_dir / "page_01.pdf"),
                "preview_svg": str(stale_dir / "page_01.svg"),
                "draw_length_m": "1.0",
            }
        )

    selection = find_first_ready_package(variant, kind="a4")

    assert selection.gcode == str(page_gcode)
    assert selection.preview_pdf == str(page_pdf)
    assert selection.preview_svg == str(page_svg)


def test_find_first_ready_package_skips_external_nc_without_local_fallback(tmp_path: Path) -> None:
    variant, local_nc = _write_minimal_ready_variant(tmp_path)
    external = tmp_path / "old" / "other.nc"
    external.parent.mkdir()
    external.write_text("G0 X99 Y99\n", encoding="utf-8")
    package = local_nc.parent
    local_nc.unlink()
    with (package / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["item", "ok", "nc", "draw_length_m"])
        writer.writeheader()
        writer.writerow({"item": "page_01", "ok": "True", "nc": str(external), "draw_length_m": "1.0"})

    try:
        find_first_ready_package(variant, kind="a4")
    except RuntimeError as exc:
        assert "No ready package" in str(exc)
    else:
        raise AssertionError("external nc without local fallback must not be selected")


def test_find_first_ready_package_skips_package_without_ok_summary_rows(tmp_path: Path) -> None:
    variant, local_nc = _write_minimal_ready_variant(tmp_path)
    package = local_nc.parent
    with (package / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["item", "ok", "nc", "draw_length_m"])
        writer.writeheader()
        writer.writerow({"item": "page_01", "ok": "False", "nc": str(local_nc), "draw_length_m": "1.0"})

    try:
        find_first_ready_package(variant, kind="a4")
    except RuntimeError as exc:
        assert "No ready package" in str(exc)
    else:
        raise AssertionError("summary rows without ok=True must not be selected")


def test_find_first_ready_package_skips_empty_summary_even_if_fallback_nc_exists(tmp_path: Path) -> None:
    variant, local_nc = _write_minimal_ready_variant(tmp_path)
    package = local_nc.parent
    with (package / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["item", "ok", "nc", "draw_length_m"])
        writer.writeheader()

    try:
        find_first_ready_package(variant, kind="a4")
    except RuntimeError as exc:
        assert "No ready package" in str(exc)
    else:
        raise AssertionError("empty summary must not be selected via fallback nc")


def test_find_first_ready_package_falls_back_to_requested_item_nc(tmp_path: Path) -> None:
    variant = tmp_path / "cg" / "22"
    package = variant / "a3_pack"
    package.mkdir(parents=True)
    (package / "pass_01.nc").write_text("G0 X0 Y0\n", encoding="utf-8")
    pass_02 = package / "pass_02.nc"
    pass_02.write_text("G0 X2 Y2\nG1 X3 Y3\n", encoding="utf-8")
    with (package / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["item", "ok", "draw_length_m"])
        writer.writeheader()
        writer.writerow({"item": "pass_01", "ok": "True", "draw_length_m": "6.7"})
        writer.writerow({"item": "pass_02", "ok": "True", "draw_length_m": "6.9"})
    (variant / "_audit.json").write_text(
        json.dumps({"items": [{"task": package.name, "kind": "a3_two_pass", "package_dir": str(package)}]}),
        encoding="utf-8",
    )
    (variant / "_ready_to_plot_audit.json").write_text(json.dumps({"ok": True, "failed_packages": []}), encoding="utf-8")

    selection = find_first_ready_package(variant, kind="a3", item="pass_02")

    assert selection.nc == str(pass_02)
    assert selection.item == "pass_02"


def test_find_first_ready_package_does_not_fall_back_to_page_for_pass_item(tmp_path: Path) -> None:
    variant = tmp_path / "cg" / "22"
    package = variant / "a3_pack"
    package.mkdir(parents=True)
    (package / "page_01.nc").write_text("G0 X99 Y99\n", encoding="utf-8")
    with (package / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["item", "ok", "draw_length_m"])
        writer.writeheader()
        writer.writerow({"item": "pass_02", "ok": "True", "draw_length_m": "6.9"})
    (variant / "_audit.json").write_text(
        json.dumps({"items": [{"task": package.name, "kind": "a3_two_pass", "package_dir": str(package)}]}),
        encoding="utf-8",
    )
    (variant / "_ready_to_plot_audit.json").write_text(json.dumps({"ok": True, "failed_packages": []}), encoding="utf-8")

    try:
        find_first_ready_package(variant, kind="a3", item="pass_02")
    except RuntimeError as exc:
        assert "No ready package" in str(exc)
    else:
        raise AssertionError("requested pass_02 must not fall back to page_01.nc")


def test_ready_kind_aliases_match_audit_kind_names() -> None:
    assert _normalize_kind("a3") == "a3_two_pass"
    assert _normalize_kind("a3-two") == "a3_two_pass"
    assert _normalize_kind("first_a4") == "a4"


def test_ready_item_aliases_match_summary_item_names() -> None:
    assert _normalize_item("2") == "pass_02"
    assert _normalize_item("pass02") == "pass_02"
    assert _normalize_item("page01") == "page_01"
