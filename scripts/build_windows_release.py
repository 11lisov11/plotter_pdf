from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "PlotterPDF"
VERSION = "0.1.0"


def copy_tree(src: Path, dst: Path) -> None:
    if src.exists():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("gui_settings.json", "pencil_state.json", "pencil_profile.json"))


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def main() -> int:
    shutil.rmtree(DIST, ignore_errors=True)
    (ROOT / "dist").mkdir(exist_ok=True)
    run([sys.executable, "-m", "PyInstaller", "packaging/plotter_pdf_cli.spec", "--noconfirm"])
    run([sys.executable, "-m", "PyInstaller", "packaging/plotter_pdf_gui.spec", "--noconfirm"])
    copy_tree(ROOT / "config", DIST / "config")
    examples = DIST / "examples"; examples.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tests/fixtures/simple_square.svg", examples / "simple_square.svg")
    (examples / "README_examples.md").write_text("Open simple_square.svg in the GUI and run Preview before Draw.\n", encoding="utf-8")
    shutil.copy2(ROOT / "packaging/README_START_HERE.md", DIST / "README_START_HERE.md")
    (DIST / "licenses").mkdir(exist_ok=True)
    zip_path = ROOT / "dist" / f"plotter_pdf_windows_{VERSION}.zip"
    if zip_path.exists(): zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in DIST.rglob("*"):
            zf.write(path, path.relative_to(ROOT / "dist"))
    print(f"Built {zip_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
