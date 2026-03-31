from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = Path(__file__).resolve().with_name("prepare_toe_handwriting_package.py")
KNOWN_VARIANT_NUMBERS = ("4", "11", "14", "25", "26")


def variant_pdf_name(variant: str) -> str:
    return f"TOE_Zadachi_1_2_Variant_{str(variant).strip()}.pdf"


def resolve_selected_pdfs(
    *,
    variants: Iterable[str],
    pdfs: Iterable[str],
    all_known: bool,
) -> list[Path]:
    selected: list[Path] = []
    seen: set[str] = set()

    if all_known:
        variants = list(KNOWN_VARIANT_NUMBERS)

    for variant in variants:
        name = variant_pdf_name(variant)
        path = (PROJECT_ROOT / name).resolve()
        key = str(path).lower()
        if key not in seen:
            selected.append(path)
            seen.add(key)

    for pdf in pdfs:
        path = (PROJECT_ROOT / str(pdf)).resolve()
        key = str(path).lower()
        if key not in seen:
            selected.append(path)
            seen.add(key)

    return selected


def build_prepare_command(
    *,
    pdf_path: Path,
    resume: bool,
    max_duplicate_ratio: float,
    max_tiny_ratio: float,
    override_similarity_gain: float,
    font_labels: Iterable[str],
) -> list[str]:
    cmd = [
        sys.executable,
        str(PREPARE_SCRIPT),
        "--pdf",
        str(pdf_path.name),
        "--out-dir",
        f"{pdf_path.stem}_pack",
        "--max-duplicate-ratio",
        str(max_duplicate_ratio),
        "--max-tiny-ratio",
        str(max_tiny_ratio),
        "--override-similarity-gain",
        str(override_similarity_gain),
    ]
    if resume:
        cmd.append("--resume")
    for label in font_labels:
        cmd.extend(["--font-label", str(label)])
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare one or more TOE PDF packages using the font-first pipeline.")
    parser.add_argument("--variant", action="append", default=[], help="TOE variant number, e.g. 25. Can be passed multiple times.")
    parser.add_argument("--pdf", action="append", default=[], help="Explicit TOE PDF filename in project root. Can be passed multiple times.")
    parser.add_argument("--all-known", action="store_true", help="Prepare the known TOE variants shipped in this repository.")
    parser.add_argument("--resume", action="store_true", help="Reuse existing candidate artifacts when possible.")
    parser.add_argument("--max-duplicate-ratio", type=float, default=0.002)
    parser.add_argument("--max-tiny-ratio", type=float, default=0.015)
    parser.add_argument("--override-similarity-gain", type=float, default=0.012)
    parser.add_argument("--font-label", action="append", default=[], help="Optional explicit handwriting font label.")
    args = parser.parse_args(argv)

    pdf_paths = resolve_selected_pdfs(
        variants=list(args.variant),
        pdfs=list(args.pdf),
        all_known=bool(args.all_known),
    )
    if not pdf_paths:
        parser.error("No TOE PDFs selected. Use --variant, --pdf or --all-known.")

    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

    for pdf_path in pdf_paths:
        cmd = build_prepare_command(
            pdf_path=pdf_path,
            resume=bool(args.resume),
            max_duplicate_ratio=float(args.max_duplicate_ratio),
            max_tiny_ratio=float(args.max_tiny_ratio),
            override_similarity_gain=float(args.override_similarity_gain),
            font_labels=list(args.font_label),
        )
        print(f"[toe] preparing {pdf_path.name}", flush=True)
        subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
