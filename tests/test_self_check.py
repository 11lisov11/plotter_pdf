from __future__ import annotations

import json

from src.plotter_backend.jobs.self_check import format_self_check_report, run_self_check


def test_self_check_runs_without_touching_hardware(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PLOTTER_HARDWARE", raising=False)
    monkeypatch.delenv("PLOTTER_COM", raising=False)
    out = tmp_path / "self_check.json"
    exit_code, report = run_self_check(json_out=out)
    assert exit_code in {0, 2}
    assert report["hardware"]["skipped"] is True
    assert report["fake_grbl"]["ok"] is True
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["fake_grbl"]["ok"] is True


def test_self_check_text_contains_core_status() -> None:
    _exit_code, report = run_self_check()
    text = format_self_check_report(report)
    assert "Plotter PDF self-check" in text
    assert "Hardware tests:" in text
