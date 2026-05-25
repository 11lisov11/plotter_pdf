from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.plotter_backend.common_utils import clean_report_value

DEFAULT_WORK_AREA = (0.0, 180.0, -285.0, -5.0)
A3_TWO_PASS_WORK_AREA = (0.0, 180.0, -285.0, -2.0)
DEFAULT_Z_UP = 0.0
DEFAULT_Z_DOWN = 11.9
_TOKEN_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")
_SVG_COORD_RE = re.compile(r"[ML]\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))[\s,]+([+-]?(?:\d+(?:\.\d*)?|\.\d+))", re.I)
_SVG_POINT_RE = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))[\s,]+([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


@dataclass
class GcodeValidation:
    ok: bool
    lines: int = 0
    draw_moves: int = 0
    travel_moves: int = 0
    duplicate_segments: int = 0
    overlap_segments: int = 0
    bounds: tuple[float, float, float, float] | None = None
    final_position: tuple[float, float, float | None] | None = None
    motor_release_seen: bool = False
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PackageValidation:
    package_dir: str
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gcode: dict[str, GcodeValidation] = field(default_factory=dict)


def _strip_comment(line: str) -> str:
    line = line.split(";", 1)[0]
    out: list[str] = []
    depth = 0
    for ch in line:
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip()


def _tokens(line: str) -> dict[str, float]:
    return {axis.upper(): float(value) for axis, value in _TOKEN_RE.findall(line)}


def _has_gcode_word(line: str, letter: str, number: int) -> bool:
    return re.search(rf"(?<![A-Z0-9.]){letter.upper()}0*{number}(?![0-9.])", line.upper()) is not None


def _motion_code(line: str, previous: str | None) -> str | None:
    for number, canonical in ((0, "G0"), (1, "G1"), (2, "G2"), (3, "G3")):
        if _has_gcode_word(line, "G", number):
            return canonical
    return previous


def _is_pen_down(z: float | None, z_up: float, z_down: float, spindle_down: bool) -> bool:
    if spindle_down:
        return True
    if z is None:
        return False
    threshold = (float(z_up) + float(z_down)) / 2.0
    if z_down >= z_up:
        return float(z) > threshold
    return float(z) < threshold


def _segment_key(x0: float, y0: float, x1: float, y1: float, *, decimals: int = 2) -> tuple[tuple[float, float], tuple[float, float]]:
    p0 = (round(float(x0), decimals), round(float(y0), decimals))
    p1 = (round(float(x1), decimals), round(float(y1), decimals))
    return (p0, p1) if p0 <= p1 else (p1, p0)


def _segment_axis(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    min_len: float,
) -> tuple[float, float, float, float, float, float, float] | None:
    dx = float(x1) - float(x0)
    dy = float(y1) - float(y0)
    length = math.hypot(dx, dy)
    if length < float(min_len):
        return None
    ux = dx / length
    uy = dy / length
    if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0.0):
        ux = -ux
        uy = -uy
    nx = -uy
    ny = ux
    offset = float(x0) * nx + float(y0) * ny
    t0 = float(x0) * ux + float(y0) * uy
    t1 = float(x1) * ux + float(y1) * uy
    if t0 > t1:
        t0, t1 = t1, t0
    return ux, uy, nx, ny, offset, t0, t1


def _count_collinear_overlaps(
    segments: Iterable[tuple[float, float, float, float]],
    *,
    dist_tol: float = 0.12,
    angle_tol_deg: float = 1.0,
    min_len: float = 0.40,
    min_overlap_ratio: float = 0.90,
) -> int:
    angle_tol = math.radians(float(angle_tol_deg))
    dist_tol = float(dist_tol)
    min_len = float(min_len)
    min_ratio = max(0.0, min(1.0, float(min_overlap_ratio)))
    buckets: dict[tuple[int, int], list[tuple[float, float, float, float, float, float, float]]] = {}
    overlap_count = 0

    def _angle_key(ux: float, uy: float) -> int:
        angle = math.atan2(float(uy), float(ux))
        if angle < 0.0:
            angle += math.pi
        return int(round(angle / angle_tol))

    def _offset_key_for_angle(angle_key: int, x: float, y: float) -> int:
        bucket_angle = float(angle_key) * angle_tol
        bucket_nx = -math.sin(bucket_angle)
        bucket_ny = math.cos(bucket_angle)
        return int(round((float(x) * bucket_nx + float(y) * bucket_ny) / max(dist_tol, 1e-9)))

    for x0, y0, x1, y1 in segments:
        axis = _segment_axis(x0, y0, x1, y1, min_len=min_len)
        if axis is None:
            continue
        ux, uy, nx, ny, offset, t0, t1 = axis
        angle_key = _angle_key(ux, uy)
        overlapped = False

        for da in (-1, 0, 1):
            query_angle_key = angle_key + da
            offset_key = _offset_key_for_angle(query_angle_key, x0, y0)
            for dk in range(-3, 4):
                for other in buckets.get((query_angle_key, offset_key + dk), []):
                    oux, ouy, _onx, _ony, other_offset, other_t0, other_t1 = other
                    dot = max(-1.0, min(1.0, ux * oux + uy * ouy))
                    if math.acos(abs(dot)) > angle_tol:
                        continue
                    cur_t0 = float(x0) * oux + float(y0) * ouy
                    cur_t1 = float(x1) * oux + float(y1) * ouy
                    if cur_t0 > cur_t1:
                        cur_t0, cur_t1 = cur_t1, cur_t0
                    overlap_len = min(cur_t1, other_t1) - max(cur_t0, other_t0)
                    if overlap_len <= 0.0:
                        continue
                    other_len = max(1e-9, other_t1 - other_t0)
                    current_len_on_other = max(1e-9, cur_t1 - cur_t0)
                    if overlap_len < min_len or overlap_len / min(current_len_on_other, other_len) < min_ratio:
                        continue
                    overlap_mid_t = (max(cur_t0, other_t0) + min(cur_t1, other_t1)) * 0.5
                    other_mid_x = oux * overlap_mid_t + _onx * other_offset
                    other_mid_y = ouy * overlap_mid_t + _ony * other_offset
                    current_mid_t = (other_mid_x - float(x0)) * ux + (other_mid_y - float(y0)) * uy
                    current_mid_x = float(x0) + ux * current_mid_t
                    current_mid_y = float(y0) + uy * current_mid_t
                    if math.hypot(current_mid_x - other_mid_x, current_mid_y - other_mid_y) <= dist_tol:
                        overlapped = True
                        break
                if overlapped:
                    break
            if overlapped:
                break

        if overlapped:
            overlap_count += 1
        stored_keys: set[tuple[int, int]] = set()
        for store_angle_key in (angle_key - 1, angle_key, angle_key + 1):
            store_key = (store_angle_key, _offset_key_for_angle(store_angle_key, x0, y0))
            if store_key in stored_keys:
                continue
            stored_keys.add(store_key)
            buckets.setdefault(store_key, []).append(axis)

    return overlap_count


def validate_gcode_file(
    gcode_path: Path,
    *,
    work_area: tuple[float, float, float, float] = DEFAULT_WORK_AREA,
    z_up: float = DEFAULT_Z_UP,
    z_down: float = DEFAULT_Z_DOWN,
) -> GcodeValidation:
    problems: list[str] = []
    warnings: list[str] = []
    lines = 0
    draw_moves = 0
    travel_moves = 0
    cur_x: float | None = None
    cur_y: float | None = None
    cur_z: float | None = None
    modal: str | None = None
    abs_mode = True
    spindle_down = False
    first_xy_seen = False
    motor_release_seen = False
    last_xy_line = 0
    spindle_off_line = 0
    motor_release_line = 0
    draw_bounds: list[float] | None = None
    segments_seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    draw_segments: list[tuple[float, float, float, float]] = []
    duplicate_segments = 0

    try:
        raw_lines = gcode_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return GcodeValidation(ok=False, problems=[f"cannot read gcode: {exc}"])

    for raw_line in raw_lines:
        line = _strip_comment(raw_line)
        if not line:
            continue
        lines += 1
        upper = line.upper()
        vals = _tokens(line)
        for axis, value in _TOKEN_RE.findall(line):
            if axis.upper() != "G":
                continue
            try:
                gval = float(value)
            except ValueError:
                continue
            if abs(gval - 90.0) <= 1e-9:
                abs_mode = True
            elif abs(gval - 91.0) <= 1e-9:
                abs_mode = False

        if _has_gcode_word(upper, "M", 3):
            spindle_down = True
        if _has_gcode_word(upper, "M", 5):
            spindle_down = False
            spindle_off_line = lines
        if upper.replace(" ", "") == "$1=0":
            motor_release_seen = True
            motor_release_line = lines

        old_x, old_y, old_z = cur_x, cur_y, cur_z
        modal = _motion_code(line, modal)

        # G92 sets the current coordinate system; for preflight we treat it as the
        # current machine position because the generated files use it for Z lift.
        if _has_gcode_word(upper, "G", 92):
            cur_x = vals.get("X", cur_x)
            cur_y = vals.get("Y", cur_y)
            cur_z = vals.get("Z", cur_z)
            continue

        if "X" in vals:
            x_raw = vals["X"]
            next_x = x_raw if (abs_mode or cur_x is None) else cur_x + x_raw
        else:
            next_x = cur_x
        if "Y" in vals:
            y_raw = vals["Y"]
            next_y = y_raw if (abs_mode or cur_y is None) else cur_y + y_raw
        else:
            next_y = cur_y
        if "Z" in vals:
            z_raw = vals["Z"]
            next_z = z_raw if (abs_mode or cur_z is None) else cur_z + z_raw
        else:
            next_z = cur_z
        has_xy = "X" in vals or "Y" in vals
        has_z = "Z" in vals

        was_down = _is_pen_down(cur_z, z_up, z_down, spindle_down)
        would_be_down = _is_pen_down(next_z, z_up, z_down, spindle_down)
        if has_z and not was_down and would_be_down:
            if has_xy:
                problems.append(f"{gcode_path.name}: line {lines}: pen-down command also moves XY")

        if has_xy:
            last_xy_line = lines
            if not first_xy_seen and would_be_down:
                problems.append(f"{gcode_path.name}: line {lines}: first XY move happens with pen down")
            first_xy_seen = True
            if modal == "G0" and (was_down or would_be_down):
                problems.append(f"{gcode_path.name}: line {lines}: rapid XY travel with pen down")

            if old_x is not None and old_y is not None and next_x is not None and next_y is not None:
                if would_be_down:
                    draw_moves += 1
                    x0, y0, x1, y1 = float(old_x), float(old_y), float(next_x), float(next_y)
                    if math.hypot(x1 - x0, y1 - y0) > 0.03:
                        key = _segment_key(x0, y0, x1, y1)
                        if key in segments_seen:
                            duplicate_segments += 1
                        else:
                            segments_seen.add(key)
                        draw_segments.append((x0, y0, x1, y1))
                    if draw_bounds is None:
                        draw_bounds = [min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)]
                    else:
                        draw_bounds[0] = min(draw_bounds[0], x0, x1)
                        draw_bounds[1] = max(draw_bounds[1], x0, x1)
                        draw_bounds[2] = min(draw_bounds[2], y0, y1)
                        draw_bounds[3] = max(draw_bounds[3], y0, y1)
                else:
                    travel_moves += 1

        cur_x, cur_y, cur_z = next_x, next_y, next_z

    if lines <= 0:
        problems.append(f"{gcode_path.name}: empty gcode")
    if not first_xy_seen:
        problems.append(f"{gcode_path.name}: no XY moves")
    if draw_moves <= 0:
        problems.append(f"{gcode_path.name}: no pen-down drawing moves")
    if duplicate_segments > 0:
        problems.append(f"{gcode_path.name}: duplicate draw segments={duplicate_segments}")
    overlap_segments = _count_collinear_overlaps(draw_segments)
    if overlap_segments > 0:
        problems.append(f"{gcode_path.name}: collinear overlapping draw segments={overlap_segments}")
    if _is_pen_down(cur_z, z_up, z_down, spindle_down):
        problems.append(f"{gcode_path.name}: file ends with pen down")
    if cur_x is None or cur_y is None or abs(float(cur_x)) > 0.25 or abs(float(cur_y)) > 0.25:
        problems.append(f"{gcode_path.name}: file does not return home at end")
    if spindle_off_line <= last_xy_line:
        problems.append(f"{gcode_path.name}: missing spindle/pen-off M5 after final XY")
    if not motor_release_seen or motor_release_line <= max(last_xy_line, spindle_off_line):
        problems.append(f"{gcode_path.name}: missing motor release $1=0 after home/M5")

    if draw_bounds is None:
        bounds = None
    else:
        bounds = (draw_bounds[0], draw_bounds[1], draw_bounds[2], draw_bounds[3])
        min_x, max_x, min_y, max_y = work_area
        bx0, bx1, by0, by1 = bounds
        if bx0 < min_x - 0.25 or bx1 > max_x + 0.25 or by0 < min_y - 0.25 or by1 > max_y + 0.25:
            problems.append(
                f"{gcode_path.name}: draw bounds x({bx0:.3f},{bx1:.3f}) y({by0:.3f},{by1:.3f}) "
                f"outside work area x({min_x:.3f},{max_x:.3f}) y({min_y:.3f},{max_y:.3f})"
            )

    return GcodeValidation(
        ok=not problems,
        lines=lines,
        draw_moves=draw_moves,
        travel_moves=travel_moves,
        duplicate_segments=duplicate_segments,
        overlap_segments=overlap_segments,
        bounds=bounds,
        final_position=(float(cur_x), float(cur_y), float(cur_z) if cur_z is not None else None)
        if cur_x is not None and cur_y is not None
        else None,
        motor_release_seen=motor_release_seen,
        problems=problems,
        warnings=warnings,
    )


def collect_variant_dirs(roots: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    for root in roots:
        root = root.resolve()
        if (root / "_prepared_summary.csv").exists():
            result.append(root)
            continue
        if not root.exists():
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
            if child.is_dir() and (child / "_prepared_summary.csv").exists():
                result.append(child)
    return result


def _read_summary_rows(variant_dir: Path) -> list[dict[str, str]]:
    summary_path = variant_dir / "_prepared_summary.csv"
    with summary_path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _selected_item(report: dict[str, object]) -> dict[str, object] | None:
    selected = str(report.get("selected_variant") or "")
    for item in report.get("items", []) or []:
        if isinstance(item, dict) and str(item.get("variant") or "") == selected:
            return item
    return None


def _metrics_duplicate_count(item: dict[str, object] | None) -> int:
    if not item:
        return 0
    metrics = item.get("metrics")
    if not isinstance(metrics, dict):
        return 0
    try:
        return int(metrics.get("segments_duplicate") or 0)
    except (TypeError, ValueError):
        return 0


def _logs_contain(item: dict[str, object] | None, needle: str) -> bool:
    if not item:
        return False
    return any(needle in str(line) for line in item.get("logs", []) or [])


def _notes_contain(item: dict[str, object] | None, needle: str) -> bool:
    if not item:
        return False
    return needle in str(item.get("notes") or "")


def _require_file(package_dir: Path, rel: str, problems: list[str]) -> None:
    if not (package_dir / rel).exists():
        problems.append(f"missing {rel}")


def _append_unique_path(paths: list[Path], seen: set[Path], path: Path) -> None:
    key = path.resolve(strict=False)
    if key in seen:
        return
    seen.add(key)
    paths.append(path)


def _collect_package_plotter_files(package_dir: Path, canonical_paths: Iterable[Path]) -> list[Path]:
    """Validate every G-code-like file that may be sent to the plotter.

    The package contract requires root ``*.gcode`` files, but the pipeline also
    writes ``*.nc`` aliases and ``pages/`` mirrors. A stale alias is enough to
    reproduce a bad plot even when the canonical ``*.gcode`` is clean.
    """

    paths: list[Path] = []
    seen: set[Path] = set()
    for path in canonical_paths:
        if path.exists():
            _append_unique_path(paths, seen, path)
    for path in sorted(
        list(package_dir.rglob("*.gcode")) + list(package_dir.rglob("*.nc")),
        key=lambda p: p.relative_to(package_dir).as_posix().casefold(),
    ):
        _append_unique_path(paths, seen, path)
    return paths


def _plotter_alias_mismatch_problems(package_dir: Path, stems: Iterable[str]) -> list[str]:
    problems: list[str] = []
    for stem in sorted(set(stems)):
        paths = [
            package_dir / f"{stem}.gcode",
            package_dir / f"{stem}.nc",
            package_dir / "pages" / f"{stem}.gcode",
            package_dir / "pages" / f"{stem}.nc",
        ]
        existing = [path for path in paths if path.exists()]
        if len(existing) < 2:
            continue
        hashes: dict[str, list[str]] = {}
        for path in existing:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                problems.append(f"cannot read plotter alias {path.relative_to(package_dir).as_posix()}: {exc}")
                continue
            hashes.setdefault(digest, []).append(path.relative_to(package_dir).as_posix())
        if len(hashes) > 1:
            groups = ["+".join(group) for group in hashes.values()]
            problems.append(f"plotter aliases differ for {stem}: {' != '.join(groups)}")
    return problems


def _unexpected_plotter_file_problems(package_dir: Path, stems: Iterable[str]) -> list[str]:
    expected_stems = set(stems)
    problems: list[str] = []
    for path in sorted(
        list(package_dir.rglob("*.gcode")) + list(package_dir.rglob("*.nc")),
        key=lambda p: p.relative_to(package_dir).as_posix().casefold(),
    ):
        if path.stem in expected_stems:
            continue
        problems.append(f"unexpected plotter file {path.relative_to(package_dir).as_posix()}")
    return problems


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _svg_polyline_segments(svg_path: Path) -> list[tuple[float, float, float, float]]:
    try:
        root = ET.parse(svg_path).getroot()
    except (ET.ParseError, OSError):
        return []

    segments: list[tuple[float, float, float, float]] = []
    for elem in root.iter():
        name = _local_name(str(elem.tag))
        points: list[tuple[float, float]] = []
        if name == "path":
            points = [(float(x), float(y)) for x, y in _SVG_COORD_RE.findall(str(elem.attrib.get("d") or ""))]
        elif name in {"polyline", "polygon"}:
            points = [(float(x), float(y)) for x, y in _SVG_POINT_RE.findall(str(elem.attrib.get("points") or ""))]
            if name == "polygon" and len(points) > 1:
                points.append(points[0])
        if len(points) < 2:
            continue
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            segments.append((x0, y0, x1, y1))
    return segments


def _kompas_a3_outer_frame_problems(package_dir: Path) -> list[str]:
    svg_path = package_dir / "_candidates" / "a3_clean_source.svg"
    if not svg_path.exists():
        return []

    segments = _svg_polyline_segments(svg_path)
    if not segments:
        return []

    xs = [coord for x0, _, x1, _ in segments for coord in (x0, x1)]
    ys = [coord for _, y0, _, y1 in segments for coord in (y0, y1)]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    found: dict[str, tuple[float, float, float, float]] = {}

    for x0, y0, x1, y1 in segments:
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        if dy <= 0.15 and dx >= 300.0 and abs(y0 - min_y) <= 3.0:
            found.setdefault("top", (x0, y0, x1, y1))
        if dy <= 0.15 and dx >= 300.0 and abs(y0 - max_y) <= 3.0:
            found.setdefault("bottom", (x0, y0, x1, y1))
        if dx <= 0.15 and dy >= 220.0 and abs(x0 - min_x) <= 3.0:
            found.setdefault("left", (x0, y0, x1, y1))
        if dx <= 0.15 and dy >= 220.0 and abs(x0 - max_x) <= 3.0:
            found.setdefault("right", (x0, y0, x1, y1))

    return [
        (
            "KOMPAS A3 clean source still contains outer sheet frame "
            f"{edge} segment ({segment[0]:.2f},{segment[1]:.2f})-({segment[2]:.2f},{segment[3]:.2f})"
        )
        for edge, segment in sorted(found.items())
    ]


def validate_package(package_dir: Path, rows: list[dict[str, str]]) -> PackageValidation:
    problems: list[str] = []
    warnings: list[str] = []
    report_path = package_dir / "report.json"
    summary_path = package_dir / "summary.csv"
    _require_file(package_dir, "report.json", problems)
    _require_file(package_dir, "summary.csv", problems)
    _require_file(package_dir, "source_vs_gcode_compare.pdf", problems)
    _require_file(package_dir, "source_vs_gcode_compare.png", problems)

    report: dict[str, object] = {}
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"invalid report.json: {exc}")

    if summary_path.exists():
        try:
            with summary_path.open(encoding="utf-8-sig", newline="") as fh:
                list(csv.DictReader(fh))
        except csv.Error as exc:
            problems.append(f"invalid summary.csv: {exc}")

    selected_item = _selected_item(report)
    selected_variant = str(report.get("selected_variant") or "")
    frame_class = str(report.get("frame_class") or "")

    if selected_variant == "strict_1to1_clip":
        problems.append("strict_1to1_clip selected as production final")
    if frame_class == "kompas_full_frame" and selected_variant == "a4_hybrid_frame":
        problems.append("KOMPAS package selected forbidden a4_hybrid_frame route")
    if frame_class == "kompas_full_frame" and _logs_contain(selected_item, "Technical text join"):
        problems.append("KOMPAS selected route still runs Technical text join")
    if frame_class == "kompas_full_frame" and _logs_contain(selected_item, "KOMPAS text reroute:"):
        problems.append("KOMPAS selected route reroutes source text")
    if frame_class == "kompas_full_frame" and _notes_contain(selected_item, "kompas_text_reroute=True"):
        problems.append("KOMPAS selected route marks kompas_text_reroute=True")
    duplicate_count = _metrics_duplicate_count(selected_item)
    if duplicate_count > 0:
        problems.append(f"selected route reports duplicate segments={duplicate_count}")

    items = {str(row.get("item") or "") for row in rows}
    canonical_gcode_paths: list[Path] = []
    canonical_gcode_stems: list[str] = []
    if items == {"page_01"}:
        _require_file(package_dir, "a4_clean_source.pdf", problems)
        _require_file(package_dir, "page_01.pdf", problems)
        _require_file(package_dir, "page_01.gcode", problems)
        canonical_gcode_paths.append(package_dir / "page_01.gcode")
        canonical_gcode_stems.append("page_01")
    elif any(item.startswith("pass_") for item in items):
        _require_file(package_dir, "combined_preview.pdf", problems)
        pass_names = sorted(item for item in items if item.startswith("pass_"))
        for pass_name in pass_names:
            _require_file(package_dir, f"{pass_name}.pdf", problems)
            _require_file(package_dir, f"{pass_name}.gcode", problems)
            canonical_gcode_paths.append(package_dir / f"{pass_name}.gcode")
            canonical_gcode_stems.append(pass_name)
        if frame_class == "kompas_full_frame":
            problems.extend(_kompas_a3_outer_frame_problems(package_dir))
    else:
        problems.append(f"unknown package items: {sorted(items)}")

    problems.extend(_unexpected_plotter_file_problems(package_dir, canonical_gcode_stems))
    problems.extend(_plotter_alias_mismatch_problems(package_dir, canonical_gcode_stems))

    gcode_results: dict[str, GcodeValidation] = {}
    gcode_paths = _collect_package_plotter_files(package_dir, canonical_gcode_paths)
    for gcode_path in gcode_paths:
        if not gcode_path.exists():
            continue
        work_area = A3_TWO_PASS_WORK_AREA if gcode_path.name.startswith("pass_") else DEFAULT_WORK_AREA
        result = validate_gcode_file(gcode_path, work_area=work_area)
        rel_name = gcode_path.relative_to(package_dir).as_posix()
        gcode_results[rel_name] = result
        problems.extend(f"{rel_name}: {problem}" for problem in result.problems)
        warnings.extend(f"{rel_name}: {warning}" for warning in result.warnings)

    return PackageValidation(
        package_dir=str(package_dir),
        ok=not problems,
        problems=problems,
        warnings=warnings,
        gcode=gcode_results,
    )


def _group_rows_by_package(rows: list[dict[str, str]]) -> dict[Path, list[dict[str, str]]]:
    grouped: dict[Path, list[dict[str, str]]] = {}
    for row in rows:
        package_raw = str(row.get("package_dir") or "").strip()
        if not package_raw:
            continue
        grouped.setdefault(Path(package_raw), []).append(row)
    return grouped


def validate_variant(variant_dir: Path, *, write_reports: bool = True) -> dict[str, object]:
    rows = _read_summary_rows(variant_dir)
    grouped = _group_rows_by_package(rows)
    packages = [validate_package(package_dir, package_rows) for package_dir, package_rows in sorted(grouped.items())]
    failed = [pkg for pkg in packages if not pkg.ok]
    warnings = [warning for pkg in packages for warning in pkg.warnings]
    scope_problems: list[str] = []
    if not packages:
        scope_problems.append("no packages listed in _prepared_summary.csv")
    payload = {
        "variant_dir": str(variant_dir),
        "ok": not failed and not scope_problems,
        "packages": len(packages),
        "failed_packages": [
            {
                "package_dir": pkg.package_dir,
                "problems": pkg.problems,
                "warnings": pkg.warnings,
            }
            for pkg in failed
        ]
        + (
            [
                {
                    "package_dir": str(variant_dir),
                    "problems": scope_problems,
                    "warnings": [],
                }
            ]
            if scope_problems
            else []
        ),
        "warnings": warnings,
        "preflight": {
            "checked_gcode_files": sum(len(pkg.gcode) for pkg in packages),
            "duplicate_segments": sum(result.duplicate_segments for pkg in packages for result in pkg.gcode.values()),
            "overlap_segments": sum(result.overlap_segments for pkg in packages for result in pkg.gcode.values()),
            "missing_motor_release": sum(
                1 for pkg in packages for result in pkg.gcode.values() if not result.motor_release_seen
            ),
            "unsafe_endings": sum(
                1
                for pkg in packages
                for result in pkg.gcode.values()
                if any(
                    marker in problem
                    for problem in result.problems
                    for marker in ("file ends with pen down", "does not return home", "missing spindle/pen-off")
                )
            ),
        },
    }
    if write_reports:
        (variant_dir / "_ready_to_plot_audit.json").write_text(
            json.dumps(clean_report_value(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines = [
            f"variant={variant_dir}",
            f"ok={payload['ok']}",
            f"packages={payload['packages']}",
            f"failed={len(failed)}",
            f"warnings={len(warnings)}",
        ]
        for failed_pkg in payload["failed_packages"]:
            lines.append(str(failed_pkg["package_dir"]))
            for problem in failed_pkg["problems"]:
                lines.append(f"  FAIL: {problem}")
        (variant_dir / "_ready_to_plot_audit.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate prepared drawing packages before plotting.")
    parser.add_argument("--root", action="append", default=[], help="Prepared variant root or parent folder.")
    parser.add_argument("--expect-packages", type=int, default=None, help="Fail unless total package count matches.")
    parser.add_argument("--no-write", action="store_true", help="Do not write audit files into variant folders.")
    args = parser.parse_args()

    roots = [Path(item) for item in args.root] if args.root else [PROJECT_ROOT / "Компьютерная графика", PROJECT_ROOT / "Начерт"]
    variant_dirs = collect_variant_dirs(roots)
    if not variant_dirs:
        print("No prepared variant dirs found.")
        return 2

    results = [validate_variant(variant_dir, write_reports=not args.no_write) for variant_dir in variant_dirs]
    total_packages = sum(int(item["packages"]) for item in results)
    failed = [pkg for item in results for pkg in item["failed_packages"]]
    warnings = [warning for item in results for warning in item["warnings"]]

    if args.expect_packages is not None and total_packages != int(args.expect_packages):
        failed.append(
            {
                "package_dir": "<scope>",
                "problems": [f"package count {total_packages} != expected {int(args.expect_packages)}"],
                "warnings": [],
            }
        )

    print(f"variants={len(results)} packages={total_packages} failed={len(failed)} warnings={len(warnings)}")
    for item in results:
        print(f"{item['variant_dir']}: packages={item['packages']} ok={item['ok']}")
    if failed:
        print("FAILED PACKAGES:")
        for pkg in failed:
            print(pkg["package_dir"])
            for problem in pkg["problems"]:
                print(f"  - {problem}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
