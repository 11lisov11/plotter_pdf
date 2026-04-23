from __future__ import annotations

import sys
from pathlib import Path

import fitz

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import prepare_nachert_packages as mod


def _write_one_page_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()


def _write_two_page_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()


def test_iter_variant_sources_falls_back_to_generated_pdf(tmp_path: Path) -> None:
    variant_dir = tmp_path / "1 вариант"
    generated_dir = variant_dir / "_generated_pdf"
    generated_dir.mkdir(parents=True)
    _write_one_page_pdf(generated_dir / "Задача 2.pdf")
    _write_one_page_pdf(generated_dir / "Задача 1.pdf")
    _write_one_page_pdf(generated_dir / "Задача 3__kompas.pdf")
    _write_one_page_pdf(generated_dir / "Задача 4__regen_1.pdf")

    entries = mod._iter_variant_sources(variant_dir, generated_dir)

    assert [item[0] for item in entries] == [1, 2]
    assert [item[1] for item in entries] == ["Задача 1", "Задача 2"]
    assert all(item[3]["source_kind"] == "generated_pdf" for item in entries)


def test_prepare_variant_respects_only_tasks_filter(tmp_path: Path, monkeypatch) -> None:
    variant_dir = tmp_path / "1 вариант"
    generated_dir = variant_dir / "_generated_pdf"
    generated_dir.mkdir(parents=True)
    _write_one_page_pdf(generated_dir / "Задача 1.pdf")
    _write_one_page_pdf(generated_dir / "Задача 2.pdf")

    called: list[int] = []

    def _fake_prepare(source_pdf: Path, package_dir: Path):
        called.append(int(package_dir.name.split()[1].split("_")[0]))
        return ({"ok": True}, [])

    monkeypatch.setattr(mod.prep, "_prepare_drawing_package", _fake_prepare)
    monkeypatch.setattr(mod.prep, "_write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod.prep, "_write_csv", lambda *args, **kwargs: None)

    mod._prepare_variant(variant_dir, only_tasks={2})

    assert called == [2]


def test_prepare_variant_only_tasks_preserves_other_rows(tmp_path: Path, monkeypatch) -> None:
    variant_dir = tmp_path / "1 вариант"
    generated_dir = variant_dir / "_generated_pdf"
    generated_dir.mkdir(parents=True)
    _write_one_page_pdf(generated_dir / "Задача 1.pdf")
    _write_one_page_pdf(generated_dir / "Задача 2.pdf")

    existing_rows = [
        mod.prep.ArtifactRow(
            source_pdf="old1.pdf",
            package_dir=str(variant_dir / "Задача 1_pack"),
            kind="drawing",
            item="page_01",
            ok=True,
            layout_similarity=0.91,
            selected_variant="fit_full",
            source_fidelity_score=0.91,
            fragmentation_score=0.99,
            draw_length_m=0.1,
            segments_total=1,
            pen_down_strokes=1,
            tiny_strokes_lt_08_mm=0,
            point_like_strokes=0,
            bounds="",
            nc="a.nc",
            gcode="a.gcode",
            preview_pdf="a.pdf",
            preview_svg="a.svg",
            notes="old1",
        ),
        mod.prep.ArtifactRow(
            source_pdf="old2.pdf",
            package_dir=str(variant_dir / "Задача 2_pack"),
            kind="drawing",
            item="page_01",
            ok=True,
            layout_similarity=0.92,
            selected_variant="fit_full",
            source_fidelity_score=0.92,
            fragmentation_score=0.99,
            draw_length_m=0.2,
            segments_total=2,
            pen_down_strokes=2,
            tiny_strokes_lt_08_mm=0,
            point_like_strokes=0,
            bounds="",
            nc="b.nc",
            gcode="b.gcode",
            preview_pdf="b.pdf",
            preview_svg="b.svg",
            notes="old2",
        ),
    ]
    mod.prep._write_csv(variant_dir / "_prepared_summary.csv", existing_rows)
    (variant_dir / "_prepared_reports.json").write_text(
        mod.json.dumps(
            {
                "sources": [{"task_number": 1}, {"task_number": 2}],
                "reports": [{"task_number": 1, "task_name": "Задача 1"}, {"task_number": 2, "task_name": "Задача 2"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def _fake_prepare(source_pdf: Path, package_dir: Path):
        package_dir.mkdir(parents=True, exist_ok=True)
        return (
            {"ok": True},
            [
                mod.prep.ArtifactRow(
                    source_pdf=str(source_pdf),
                    package_dir=str(package_dir),
                    kind="drawing",
                    item="page_01",
                    ok=True,
                    layout_similarity=0.99,
                    selected_variant="fit_full",
                    source_fidelity_score=0.99,
                    fragmentation_score=0.99,
                    draw_length_m=0.9,
                    segments_total=9,
                    pen_down_strokes=9,
                    tiny_strokes_lt_08_mm=0,
                    point_like_strokes=0,
                    bounds="",
                    nc="new.nc",
                    gcode="new.gcode",
                    preview_pdf="new.pdf",
                    preview_svg="new.svg",
                    notes="new",
                )
            ],
        )

    monkeypatch.setattr(mod.prep, "_prepare_drawing_package", _fake_prepare)
    mod._prepare_variant(variant_dir, only_tasks={2})

    rows = mod.prep._read_rows_from_csv(variant_dir / "_prepared_summary.csv")
    assert [Path(row.package_dir).name for row in rows] == ["Задача 1_pack", "Задача 2_pack"]
    assert [row.notes for row in rows] == ["old1", "new"]


def test_prepare_frw_source_pdf_merges_two_page_export_for_nonlegacy_task(tmp_path: Path, monkeypatch) -> None:
    variant_dir = tmp_path / "4 РІР°СЂРёРЅС‚"
    generated_dir = variant_dir / "_generated_pdf"
    generated_dir.mkdir(parents=True)
    frw_path = variant_dir / "Р—Р°РґР°С‡Р° 7.frw"
    frw_path.write_text("stub", encoding="utf-8")

    def _fake_frw_to_pdf(_source: Path, target: Path, _logger) -> None:
        _write_two_page_pdf(target)

    monkeypatch.setattr(mod.prep.backend, "frw_to_pdf", _fake_frw_to_pdf)

    merged_pdf, meta = mod._prepare_frw_source_pdf(frw_path, generated_dir)

    assert merged_pdf.exists()
    assert meta["task_number"] == 7
    assert meta["page_count"] == 2
    assert "merged_a3_pdf" in meta
    doc = fitz.open(merged_pdf)
    try:
        assert doc.page_count == 1
    finally:
        doc.close()


def test_prune_package_outputs_keeps_only_final_files_and_source_pdf(tmp_path: Path) -> None:
    package = tmp_path / "task_pack"
    package.mkdir(parents=True)
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    for name in ("page_01.pdf", "page_01.gcode", "page_01.nc", "page_01.svg", "report.json", "summary.csv"):
        (package / name).write_text(name, encoding="utf-8")
    (package / "logs").mkdir()
    (package / "pages").mkdir()

    mod._prune_package_outputs(package, is_a3=False, source_pdf=source_pdf)

    names = {p.name for p in package.iterdir()}
    assert names == {"page_01.pdf", "page_01.gcode", "source_kompas.pdf"}
