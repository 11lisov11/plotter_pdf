from __future__ import annotations

import json
import sys

from src.plotter_backend.jobs import self_check_cli
from src.plotter_backend.jobs.self_check import (
    CORE_MODULES,
    OPTIONAL_MODULES,
    _apply_frozen_bundle_checks,
    format_self_check_report,
    run_self_check,
)


def _fake_report(*, ok: bool, optional_missing: list[str] | None = None, errors: list[str] | None = None) -> dict:
    return {
        "ok": ok,
        "python": "3.12.0",
        "platform": "test-platform",
        "cwd": "test-cwd",
        "axis_profile_exists": True,
        "com_ports": [],
        "fake_grbl": {"ok": True},
        "hardware": {"skipped": True},
        "optional_missing": optional_missing or [],
        "errors": errors or [],
    }


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
    assert "Проверка Plotter PDF" in text
    assert "Аппаратные тесты:" in text


def test_self_check_cli_returns_optional_missing_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(
        self_check_cli,
        "run_self_check",
        lambda *, json_out=None: (2, _fake_report(ok=True, optional_missing=["PySide6"])),
    )

    assert self_check_cli.main([]) == 2


def test_self_check_cli_returns_critical_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(
        self_check_cli,
        "run_self_check",
        lambda *, json_out=None: (1, _fake_report(ok=False, errors=["Missing core module: serial"])),
    )

    assert self_check_cli.main([]) == 1


def test_frozen_bundle_self_check_accepts_sibling_cli_exe(tmp_path, monkeypatch) -> None:
    self_check_exe = tmp_path / "plotter-pdf-self-check.exe"
    self_check_exe.write_text("", encoding="utf-8")
    (tmp_path / "plotter-pdf.exe").write_text("", encoding="utf-8")
    (tmp_path / "PlotterPDF_GUI.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(self_check_exe))

    core = dict.fromkeys(CORE_MODULES, False)
    optional = dict.fromkeys(OPTIONAL_MODULES, False)

    _apply_frozen_bundle_checks(tmp_path, core, optional)

    assert all(core.values())
    assert optional["PySide6"] is True
    assert optional["opencv"] is True
    assert optional["hershey-fonts"] is True
