from __future__ import annotations

from pathlib import Path
from typing import List


def ensure_generated_svg_exists(prefix: Path, target_svg: Path, logger) -> bool:
    candidates = []
    for cand in [
        prefix.with_suffix(".svg"),
        prefix,
        Path(f"{prefix}-1"),
        Path(f"{prefix}-1.svg"),
    ]:
        candidates.append(cand)

    try:
        candidates.extend(sorted(prefix.parent.glob(f"{prefix.name}*")))
    except Exception:
        pass

    seen = set()
    ordered: List[Path] = []
    for cand in candidates:
        rp = Path(cand)
        if rp in seen:
            continue
        seen.add(rp)
        ordered.append(rp)

    for candidate in ordered:
        if not candidate.exists() or not candidate.is_file():
            continue
        if candidate.stat().st_size <= 0:
            continue
        if candidate == target_svg:
            return True
        if candidate.suffix.lower() == "" and candidate.with_suffix(".svg").exists():
            # Prefer explicit .svg files over extension-less names.
            continue
        if target_svg.exists():
            target_svg.unlink()
        candidate.replace(target_svg)
        logger(f"Using generated SVG: {candidate}")
        return True

    if target_svg.exists() and target_svg.stat().st_size > 0:
        return True
    return False


def build_inkscape_pdf_to_svg_candidates(exe: str, pdf_path: Path, target_svg: Path, *, get_inkscape_version) -> List[List[str]]:
    major, _, _ = get_inkscape_version(exe)
    if major >= 1:
        return [
            [
                exe,
                str(pdf_path),
                "--export-type=svg",
                "--export-area-page",
                "--export-overwrite",
                f"--export-filename={target_svg}",
                "--pdf-page=1",
                "--pdf-poppler",
            ],
            [
                exe,
                str(pdf_path),
                "--export-type=svg",
                "--export-area-page",
                "--export-overwrite",
                f"--export-filename={target_svg}",
                "--pdf-page=1",
            ],
            [
                exe,
                str(pdf_path),
                "--actions=select-all;object-to-path;export-text-to-path",
                "--export-overwrite",
                "--export-area-page",
                f"--export-filename={target_svg}",
                "--pdf-page=1",
            ],
            [
                exe,
                str(pdf_path),
                "--actions=select-all;object-to-path;export-text-to-path",
                "--export-overwrite",
                "--export-area-page",
                "--export-plain-svg",
                f"--export-filename={target_svg}",
                "--pdf-page=1",
            ],
        ]
    return [
        [
            exe,
            "--export-area-page",
            f"--export-plain-svg={target_svg}",
            str(pdf_path),
        ],
        [
            exe,
            "-D",
            "--export-plain-svg",
            str(target_svg),
            str(pdf_path),
        ],
        [
            exe,
            "-z",
            "-l",
            str(target_svg),
            str(pdf_path),
        ],
    ]


def score_svg_quality(
    svg_target: Path,
    *,
    extract_polylines,
    to_drawing_polylines,
    points_distance,
    svg_page_size_mm,
    bounds_path_items,
) -> tuple[float, str]:
    # Lower score is better. Use scale-independent metrics so px/mm export differences
    # do not bias converter selection.
    try:
        items = extract_polylines(svg_target)
        if not items:
            return float("inf"), "no paths"
        polylines = to_drawing_polylines(items)
        if not polylines:
            return float("inf"), "no drawable geometry"

        seg_lengths: List[float] = []
        for poly in polylines:
            for i in range(len(poly) - 1):
                d = points_distance(poly[i], poly[i + 1])
                if d > 0.0:
                    seg_lengths.append(d)
        if not seg_lengths:
            return float("inf"), "empty segment set"

        seg_count = len(seg_lengths)
        lengths_sorted = sorted(seg_lengths)
        med = lengths_sorted[len(lengths_sorted) // 2]
        tiny_th = max(1e-9, med * 0.20)
        short_th = max(1e-9, med * 0.40)
        tiny_rel = sum(1 for d in seg_lengths if d <= tiny_th)
        short_rel = sum(1 for d in seg_lengths if d <= short_th)
        score = float(seg_count) + (2.5 * float(tiny_rel)) + (1.0 * float(short_rel)) + (0.2 * float(len(polylines)))

        overflow_penalty = 0.0
        page_w_mm, page_h_mm = svg_page_size_mm(svg_target)
        b = bounds_path_items(items)
        if b is not None and page_w_mm > 0.0 and page_h_mm > 0.0:
            x0, x1, y0, y1 = b
            bw = max(0.0, x1 - x0)
            bh = max(0.0, y1 - y0)
            ox = max(0.0, (bw / page_w_mm) - 1.15)
            oy = max(0.0, (bh / page_h_mm) - 1.15)
            overflow_penalty = 4000.0 * (ox + oy)
            score += overflow_penalty

        details = (
            f"score={score:.1f}, paths={len(polylines)}, seg={seg_count}, "
            f"med={med:.4f}, tiny<=0.2*med={tiny_rel}, short<=0.4*med={short_rel}, "
            f"overflow_penalty={overflow_penalty:.1f}"
        )
        return score, details
    except Exception as exc:
        return float("inf"), f"metric-error: {exc}"
