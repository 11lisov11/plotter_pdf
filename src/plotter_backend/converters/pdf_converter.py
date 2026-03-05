from __future__ import annotations

from pathlib import Path
from typing import Callable, List

from ..errors import ConversionError, ToolDependencyError


def _format_exc(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


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


def _clip_output_block(text: str, *, max_len: int = 500) -> str:
    block = str(text or "").strip()
    if block and len(block) > max_len:
        block = block[:max_len] + " ..."
    return block


def try_inkscape_export(
    pdf_path: Path,
    target_svg: Path,
    logger,
    *,
    find_inkscape,
    run_cmd,
    get_inkscape_version,
) -> tuple[bool, str]:
    try:
        exe = find_inkscape()
    except Exception as exc:
        return False, f"{ToolDependencyError.__name__}: Inkscape unavailable ({_format_exc(exc)})"

    logger(f"Using Inkscape: {exe}")
    last_error = ""
    commands = build_inkscape_pdf_to_svg_candidates(
        exe,
        pdf_path,
        target_svg,
        get_inkscape_version=get_inkscape_version,
    )
    for i, cmd in enumerate(commands, start=1):
        logger(f"Inkscape command #{i}: {' '.join([Path(str(cmd[0])).name] + [str(x) for x in cmd[1:]])}")
        rc, out, err = run_cmd(cmd)
        if rc == 0 and target_svg.exists() and target_svg.stat().st_size > 0:
            return True, "ok"
        block = _clip_output_block((out + "\n" + err).strip())
        logger(f"Inkscape command #{i} failed or produced empty SVG: {block}")
        if block:
            last_error = block
    return False, last_error or "unknown Inkscape export failure"


def try_pdftocairo_export(
    pdf_path: Path,
    target_svg: Path,
    logger,
    *,
    find_pdftocairo,
    run_cmd,
) -> tuple[bool, str]:
    try:
        cairo = find_pdftocairo()
    except Exception as exc:
        return False, f"{ToolDependencyError.__name__}: pdftocairo unavailable ({_format_exc(exc)})"
    cairo_prefix = target_svg.with_suffix("")
    cmd = [cairo, "-svg", "-f", "1", "-l", "1", str(pdf_path), str(cairo_prefix)]
    logger(f"Trying pdftocairo: {' '.join(cmd)}")
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        block = _clip_output_block((out + "\n" + err).strip())
        detail = block or f"rc={rc}"
        return False, f"{ConversionError.__name__}: pdftocairo export failed ({detail})"
    if ensure_generated_svg_exists(cairo_prefix, target_svg, logger):
        return True, "ok"
    return False, f"{ConversionError.__name__}: pdftocairo export produced no SVG output"


def collect_pdf_converter_exports(
    pdf_path: Path,
    svg_path: Path,
    logger,
    *,
    try_inkscape: bool,
    postprocess: Callable[[Path], tuple[bool, int]],
    svg_has_text_nodes,
    find_inkscape,
    run_cmd,
    get_inkscape_version,
    find_pdftocairo,
) -> List[tuple[str, Path, bool, int]]:
    exports: List[tuple[str, Path, bool, int]] = []

    # 1) Inkscape PDF import is optional and disabled by default to avoid interactive
    # "PDF import options" dialog windows.
    if try_inkscape:
        ink_svg = svg_path.with_name(f"{svg_path.stem}_inkscape.svg")
        ok_ink, msg_ink = try_inkscape_export(
            pdf_path,
            ink_svg,
            logger,
            find_inkscape=find_inkscape,
            run_cmd=run_cmd,
            get_inkscape_version=get_inkscape_version,
        )
        if ok_ink:
            try:
                had_text, handwriting_nodes = postprocess(ink_svg)
                exports.append(("inkscape", ink_svg, had_text, handwriting_nodes))
            except Exception as exc:
                logger(f"Inkscape output rejected in postprocess ({_format_exc(exc)})")
                exports.append(("inkscape", ink_svg, svg_has_text_nodes(ink_svg), 0))
        else:
            logger(f"Inkscape export failed: {msg_ink}")
    else:
        logger("Inkscape PDF import disabled (USE_INKSCAPE_PDF_IMPORT=False and handwriting=off).")

    # 2) pdftocairo fallback/candidate for auto-choice.
    cairo_svg = svg_path.with_name(f"{svg_path.stem}_pdftocairo.svg")
    ok_cairo, msg_cairo = try_pdftocairo_export(
        pdf_path,
        cairo_svg,
        logger,
        find_pdftocairo=find_pdftocairo,
        run_cmd=run_cmd,
    )
    if ok_cairo:
        try:
            had_text, handwriting_nodes = postprocess(cairo_svg)
            exports.append(("pdftocairo", cairo_svg, had_text, handwriting_nodes))
        except Exception as exc:
            logger(f"pdftocairo output rejected in postprocess ({_format_exc(exc)})")
            exports.append(("pdftocairo", cairo_svg, svg_has_text_nodes(cairo_svg), 0))
    else:
        logger(f"pdftocairo export failed: {msg_cairo}")

    return exports


def score_converter_exports(
    exports: List[tuple[str, Path, bool, int]],
    logger,
    *,
    score_svg_quality,
) -> List[tuple[str, Path, float, str, bool, int]]:
    scored: List[tuple[str, Path, float, str, bool, int]] = []
    for name, candidate, had_text, handwriting_nodes in exports:
        score, details = score_svg_quality(candidate)
        logger(
            f"Converter metrics [{name}]: {details}, "
            f"had_text={'yes' if had_text else 'no'}, handwriting_nodes={handwriting_nodes}"
        )
        scored.append((name, candidate, score, details, had_text, handwriting_nodes))
    return scored


def select_best_scored_export(
    scored: List[tuple[str, Path, float, str, bool, int]],
    logger,
    *,
    handwriting_enabled: bool,
) -> tuple[str, Path, float, str, bool, int]:
    preferred = scored
    if handwriting_enabled:
        with_handwriting = [row for row in scored if row[5] > 0]
        with_text = [row for row in scored if row[4]]
        if with_handwriting:
            preferred = with_handwriting
            logger(
                "Handwriting mode: forcing converter with editable text "
                f"(font applied to {sum(row[5] for row in with_handwriting)} node(s) total)."
            )
        elif with_text:
            preferred = with_text
            logger(
                "Handwriting mode: forcing converter that preserved text nodes "
                "(font substitution reported 0 changed nodes)."
            )
        else:
            inkscape_only = [row for row in scored if row[0] == "inkscape"]
            if inkscape_only:
                preferred = inkscape_only
                logger(
                    "Handwriting mode warning: no converter produced editable text; "
                    "using Inkscape geometry for contour-only fallback."
                )
            else:
                logger(
                    "Handwriting mode warning: no converter produced editable text; "
                    "font substitution cannot be applied for this PDF page."
                )
    return min(preferred, key=lambda row: row[2])


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
        return float("inf"), f"metric-error ({_format_exc(exc)})"
