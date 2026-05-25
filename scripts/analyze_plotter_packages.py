from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.plotter_backend.common_utils import clean_report_value
from src.plotter_backend.gcode.bounds import pen_down_from_z_level
from src.plotter_backend.geometry.arc_fit import arc_center_from_radius

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "_tmp" / "algorithm_baseline"
TOKEN_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


@dataclass(frozen=True)
class GcodeAlgorithmMetrics:
    path: str
    total_lines: int
    g0_moves: int
    g1_moves: int
    g2_moves: int
    g3_moves: int
    draw_moves: int
    travel_moves: int
    draw_length_mm: float
    travel_length_mm: float
    travel_to_draw_ratio: float
    short_segments_lt_035_mm: int
    tiny_strokes_lt_08_mm: int
    point_like_strokes: int
    pen_down_strokes: int
    z_cycles: int


def strip_comments(line: str) -> str:
    raw = str(line or "").split(";", 1)[0]
    out: list[str] = []
    depth = 0
    for ch in raw:
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip()


def values(tokens: list[tuple[str, str]], letter: str) -> list[float]:
    target = letter.upper()
    out: list[float] = []
    for axis, value in tokens:
        if axis.upper() != target:
            continue
        try:
            out.append(float(value))
        except ValueError:
            continue
    return out


def _arc_length(x0: float, y0: float, x1: float, y1: float, i: float, j: float, *, cw: bool) -> float:
    cx = x0 + i
    cy = y0 + j
    radius = math.hypot(x0 - cx, y0 - cy)
    if radius <= 1e-9:
        return math.hypot(x1 - x0, y1 - y0)
    if math.hypot(x1 - x0, y1 - y0) <= 1e-9:
        return 2.0 * math.pi * radius
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if cw:
        sweep = a0 - a1
        if sweep <= 0.0:
            sweep += 2.0 * math.pi
    else:
        sweep = a1 - a0
        if sweep <= 0.0:
            sweep += 2.0 * math.pi
    return abs(radius * sweep)


def analyze_gcode_file(
    path: Path,
    *,
    z_up: float = 0.0,
    z_down: float = 11.9,
    z_down_threshold: float | None = None,
) -> GcodeAlgorithmMetrics:
    total_lines = 0
    motion_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    draw_moves = 0
    travel_moves = 0
    draw_length_mm = 0.0
    travel_length_mm = 0.0
    short_segments = 0
    stroke_lengths: list[float] = []
    current_stroke_mm = 0.0
    pen_down_strokes = 0
    z_cycles = 0

    cur_x: float | None = None
    cur_y: float | None = None
    cur_z: float | None = None
    last_motion: int | None = None
    abs_mode = True
    ijk_abs = False
    pen_down = False
    ever_saw_z = False
    ever_saw_spindle = False
    stroke_active = False

    def close_stroke() -> None:
        nonlocal current_stroke_mm, stroke_active
        if stroke_active:
            stroke_lengths.append(current_stroke_mm)
            current_stroke_mm = 0.0
            stroke_active = False

    def open_stroke() -> None:
        nonlocal pen_down_strokes, stroke_active
        if not stroke_active:
            pen_down_strokes += 1
            stroke_active = True

    def is_pen_down_z(z_value: float) -> bool:
        if z_down_threshold is not None:
            return float(z_value) > float(z_down_threshold)
        return pen_down_from_z_level(float(z_value), float(z_up), float(z_down))

    with Path(path).open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = strip_comments(raw)
            if not line:
                continue
            total_lines += 1
            tokens = TOKEN_RE.findall(line)
            if not tokens:
                continue

            for gval in values(tokens, "G"):
                if abs(gval - 90.0) <= 1e-9:
                    abs_mode = True
                    continue
                if abs(gval - 91.0) <= 1e-9:
                    abs_mode = False
                    continue
                if abs(gval - 90.1) <= 1e-9:
                    ijk_abs = True
                    continue
                if abs(gval - 91.1) <= 1e-9:
                    ijk_abs = False
                    continue
                rounded = int(round(gval))
                if abs(gval - rounded) <= 1e-9 and rounded in {0, 1, 2, 3}:
                    last_motion = rounded

            code = last_motion
            x_vals = values(tokens, "X")
            y_vals = values(tokens, "Y")
            z_vals = values(tokens, "Z")
            m_vals = values(tokens, "M")
            i_vals = values(tokens, "I")
            j_vals = values(tokens, "J")
            r_vals = values(tokens, "R")
            has_g92 = any(abs(gval - 92.0) <= 1e-9 for gval in values(tokens, "G"))

            for mval in m_vals:
                rounded = int(round(mval))
                if abs(mval - float(rounded)) > 1e-9:
                    continue
                if rounded == 3:
                    ever_saw_spindle = True
                    if not pen_down:
                        open_stroke()
                    pen_down = True
                elif rounded == 5:
                    ever_saw_spindle = True
                    if pen_down:
                        close_stroke()
                    pen_down = False

            if has_g92:
                if x_vals:
                    cur_x = x_vals[-1]
                if y_vals:
                    cur_y = y_vals[-1]
                if z_vals:
                    ever_saw_z = True
                    cur_z = z_vals[-1]
                    next_pen_down = is_pen_down_z(cur_z)
                    if pen_down and not next_pen_down:
                        close_stroke()
                    elif next_pen_down and not pen_down:
                        open_stroke()
                    pen_down = next_pen_down
                continue

            if z_vals:
                ever_saw_z = True
                z_raw = z_vals[-1]
                next_z = z_raw if (abs_mode or cur_z is None) else cur_z + z_raw
                next_pen_down = is_pen_down_z(next_z)
                if next_pen_down and not pen_down:
                    z_cycles += 1
                    open_stroke()
                if pen_down and not next_pen_down:
                    close_stroke()
                pen_down = next_pen_down
                cur_z = next_z

            has_xy = bool(x_vals or y_vals)
            if not has_xy or code not in {0, 1, 2, 3}:
                continue

            motion_counts[code] += 1
            x_raw = x_vals[-1] if x_vals else None
            y_raw = y_vals[-1] if y_vals else None
            next_x = cur_x if x_raw is None else (x_raw if (abs_mode or cur_x is None) else cur_x + x_raw)
            next_y = cur_y if y_raw is None else (y_raw if (abs_mode or cur_y is None) else cur_y + y_raw)

            if cur_x is None or cur_y is None or next_x is None or next_y is None:
                cur_x, cur_y = next_x, next_y
                continue

            if code in {2, 3} and (i_vals or j_vals):
                arc_i_raw = i_vals[-1] if i_vals else 0.0
                arc_j_raw = j_vals[-1] if j_vals else 0.0
                arc_i = arc_i_raw - cur_x if ijk_abs else arc_i_raw
                arc_j = arc_j_raw - cur_y if ijk_abs else arc_j_raw
                seg_len = _arc_length(cur_x, cur_y, next_x, next_y, arc_i, arc_j, cw=(code == 2))
            elif code in {2, 3} and r_vals:
                center = arc_center_from_radius((cur_x, cur_y), (next_x, next_y), r_vals[-1], cw=(code == 2))
                if center is None:
                    seg_len = math.hypot(next_x - cur_x, next_y - cur_y)
                else:
                    seg_len = _arc_length(
                        cur_x,
                        cur_y,
                        next_x,
                        next_y,
                        center[0] - cur_x,
                        center[1] - cur_y,
                        cw=(code == 2),
                    )
            else:
                seg_len = math.hypot(next_x - cur_x, next_y - cur_y)

            is_draw = code in {1, 2, 3} and (pen_down or not (ever_saw_z or ever_saw_spindle))
            if is_draw:
                if pen_down or not (ever_saw_z or ever_saw_spindle):
                    open_stroke()
                draw_moves += 1
                draw_length_mm += seg_len
                current_stroke_mm += seg_len
                if seg_len < 0.35 and seg_len > 1e-9:
                    short_segments += 1
            else:
                travel_moves += 1
                travel_length_mm += seg_len
                if pen_down or not (ever_saw_z or ever_saw_spindle):
                    close_stroke()
            cur_x, cur_y = next_x, next_y

    close_stroke()
    tiny_strokes = sum(1 for length in stroke_lengths if length < 0.8)
    point_like = sum(1 for length in stroke_lengths if length < 0.15)
    ratio = travel_length_mm / draw_length_mm if draw_length_mm > 1e-9 else 0.0
    return GcodeAlgorithmMetrics(
        path=str(Path(path)),
        total_lines=int(total_lines),
        g0_moves=int(motion_counts[0]),
        g1_moves=int(motion_counts[1]),
        g2_moves=int(motion_counts[2]),
        g3_moves=int(motion_counts[3]),
        draw_moves=int(draw_moves),
        travel_moves=int(travel_moves),
        draw_length_mm=round(draw_length_mm, 3),
        travel_length_mm=round(travel_length_mm, 3),
        travel_to_draw_ratio=round(ratio, 6),
        short_segments_lt_035_mm=int(short_segments),
        tiny_strokes_lt_08_mm=int(tiny_strokes),
        point_like_strokes=int(point_like),
        pen_down_strokes=int(pen_down_strokes),
        z_cycles=int(z_cycles),
    )


def collect_gcode_files(roots: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        root = Path(root)
        if root.is_file() and root.suffix.lower() in {".nc", ".gcode"}:
            found.append(root)
            continue
        if not root.exists() or not root.is_dir():
            continue
        for suffix in ("*.nc", "*.gcode"):
            found.extend(path for path in root.rglob(suffix) if path.is_file())
    return sorted(set(found), key=lambda p: str(p).casefold())


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except Exception:
        return False


def _load_json_dict(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _csv_dict_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _ready_audit_allows_variant(variant_dir: Path) -> bool:
    audit_path = variant_dir / "_ready_to_plot_audit.json"
    if not audit_path.exists():
        return True
    payload = clean_report_value(_load_json_dict(audit_path))
    if not payload:
        return False
    return payload.get("ok") is True and not list(payload.get("failed_packages") or [])


def _ready_package_dir(variant_dir: Path, raw: object, task: object = "") -> Path | None:
    raw_text = str(raw or "").strip()
    task_text = str(task or "").strip()
    if raw_text:
        package_dir = Path(raw_text)
        if not package_dir.is_absolute():
            package_dir = variant_dir / package_dir
    elif task_text:
        package_dir = variant_dir / task_text
    else:
        return None

    candidates = [package_dir]
    if package_dir.name:
        candidates.append(variant_dir / package_dir.name)
    if task_text:
        candidates.append(variant_dir / task_text)

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir() and _is_within(candidate, variant_dir):
            return candidate
    return None


def _variant_dirs_from_root(root: Path) -> list[Path]:
    if (root / "_audit.json").exists() or (root / "_prepared_summary.csv").exists():
        return [root]
    if not root.exists() or not root.is_dir():
        return []
    variants: dict[str, Path] = {}
    for marker in ("_prepared_summary.csv", "_audit.json"):
        for marker_path in root.rglob(marker):
            variant_dir = marker_path.parent
            variants[str(variant_dir.resolve(strict=False)).casefold()] = variant_dir
    return sorted(variants.values(), key=lambda p: str(p).casefold())


def collect_ready_package_roots(roots: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        key = path.resolve(strict=False)
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    for root in roots:
        root = Path(root)
        if root.is_file() and root.suffix.lower() in {".nc", ".gcode"}:
            add(root)
            continue
        if root.is_dir() and (root / "summary.csv").exists():
            add(root)
            continue
        for variant_dir in _variant_dirs_from_root(root):
            if not _ready_audit_allows_variant(variant_dir):
                continue
            audit = clean_report_value(_load_json_dict(variant_dir / "_audit.json"))
            items = audit.get("items") if isinstance(audit, dict) else None
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    package_dir = _ready_package_dir(variant_dir, item.get("package_dir"), item.get("task"))
                    if package_dir is not None:
                        add(package_dir)
            for row in _csv_dict_rows(variant_dir / "_prepared_summary.csv"):
                row = clean_report_value(row)
                package_dir = _ready_package_dir(variant_dir, row.get("package_dir"), row.get("task"))
                if package_dir is not None:
                    add(package_dir)

    return sorted(found, key=lambda p: str(p).casefold())


def unique_files_by_content(files: Iterable[Path]) -> tuple[list[Path], list[dict[str, object]]]:
    unique: list[Path] = []
    groups: dict[str, list[Path]] = {}
    for path in files:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            unique.append(path)
            continue
        group = groups.setdefault(digest, [])
        group.append(path)
        if len(group) == 1:
            unique.append(path)

    duplicate_groups: list[dict[str, object]] = []
    for group in groups.values():
        if len(group) <= 1:
            continue
        duplicate_groups.append(
            {
                "kept": str(group[0]),
                "duplicates": [str(path) for path in group[1:]],
                "count": len(group),
            }
        )
    return unique, duplicate_groups


def summarize(metrics: list[GcodeAlgorithmMetrics]) -> dict[str, object]:
    return {
        "files": len(metrics),
        "total_lines": sum(item.total_lines for item in metrics),
        "draw_length_mm": round(sum(item.draw_length_mm for item in metrics), 3),
        "travel_length_mm": round(sum(item.travel_length_mm for item in metrics), 3),
        "pen_down_strokes": sum(item.pen_down_strokes for item in metrics),
        "z_cycles": sum(item.z_cycles for item in metrics),
        "short_segments_lt_035_mm": sum(item.short_segments_lt_035_mm for item in metrics),
        "tiny_strokes_lt_08_mm": sum(item.tiny_strokes_lt_08_mm for item in metrics),
        "point_like_strokes": sum(item.point_like_strokes for item in metrics),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure plotter G-code topology without modifying packages.")
    parser.add_argument("paths", nargs="*", help="Variant/package directories or .nc/.gcode files.")
    parser.add_argument("--root", action="append", default=[], help="Variant/package directory or .nc/.gcode file.")
    parser.add_argument("--output", default=None, help="Output JSON path. Defaults to _tmp/algorithm_baseline/<timestamp>.json.")
    parser.add_argument("--no-write", action="store_true", help="Print JSON only; do not write a report file.")
    parser.add_argument(
        "--ready-only",
        action="store_true",
        help="When a variant root is given, analyze only ready package directories from audit/summary metadata.",
    )
    parser.add_argument(
        "--unique-content",
        action="store_true",
        help="Analyze one file per identical content hash and report skipped mirror duplicates. Enabled automatically with --ready-only.",
    )
    args = parser.parse_args(argv)

    roots = [Path(item) for item in [*args.root, *args.paths]] if (args.root or args.paths) else [PROJECT_ROOT / "Компьютерная графика"]
    scan_roots = collect_ready_package_roots(roots) if args.ready_only else roots
    files = collect_gcode_files(scan_roots)
    if not files:
        print(
            "No .nc/.gcode files found under: "
            + ", ".join(str(path) for path in scan_roots)
        )
        return 2
    files_seen = len(files)
    duplicate_groups: list[dict[str, object]] = []
    effective_unique_content = bool(args.unique_content or args.ready_only)
    if effective_unique_content:
        files, duplicate_groups = unique_files_by_content(files)
    metrics = [analyze_gcode_file(path) for path in files]
    duplicate_files_skipped = sum(int(group["count"]) - 1 for group in duplicate_groups)
    payload = {
        "generated_at_unix": int(time.time()),
        "roots": [str(path) for path in roots],
        "scan_roots": [str(path) for path in scan_roots],
        "ready_only": bool(args.ready_only),
        "unique_content": bool(effective_unique_content),
        "unique_content_requested": bool(args.unique_content),
        "files_seen": int(files_seen),
        "files_analyzed": int(len(files)),
        "duplicate_files_skipped": int(duplicate_files_skipped),
        "duplicate_content_groups": duplicate_groups,
        "summary": summarize(metrics),
        "files": [asdict(item) for item in metrics],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.no_write:
        print(text)
        return 0
    output = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"algorithm_baseline_{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")
    print(f"saved: {output}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
