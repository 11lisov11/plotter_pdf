from pathlib import Path

import pytest


@pytest.mark.build
def test_windows_build_files_exist_and_specs_readable():
    for path in ["scripts/build_windows_release.ps1", "scripts/build_windows_release.py", "packaging/plotter_pdf_cli.spec", "packaging/plotter_pdf_gui.spec", "packaging/README_START_HERE.md"]:
        p = Path(path)
        assert p.exists()
        assert p.read_text(encoding="utf-8", errors="ignore")
