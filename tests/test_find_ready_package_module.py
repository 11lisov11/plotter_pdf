from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.find_ready_package import find_first_ready_package


def test_find_first_ready_a4_package_uses_audit_order_and_summary(tmp_path: Path) -> None:
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

    selection = find_first_ready_package(variant, kind="a4")

    assert selection.task == "КНГ.01.20.01 - Маховик_pack"
    assert selection.nc == str(nc)
    assert selection.line_count == 3
    assert selection.draw_length_m == 7.197
