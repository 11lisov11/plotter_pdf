from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_AREA = (0.0, 180.0, -295.0, 0.0)
DEFAULT_Z_UP = 0.0
DEFAULT_Z_DOWN = 11.9
_TOKEN_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


@dataclass
class GcodeValidation:
    ok: bool
    lines: int = 0
    draw_moves: int = 0
    travel_moves: int = 0
    duplicate_segments: int = 0
    bounds: tuple[float, float, float, float] | None = None
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


def _motion_code(line: str, previous: str | None) -> str | None:
    upper = line.upper()
    for code in ("G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"):
        if re.search(rf"(^|\s){code}(\s|$)", upper):
            if code in {"G00"}:
                return "G0"
            if code in {"G01"}:
                return "G1"
            if code in {"G02"}:
                return "G2"
            if code in {"G03"}:
                return "G3"
            return code
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
    spindle_down = False
    first_pen_down_seen = False
    first_xy_seen = False
    draw_bounds: list[float] | None = None
    segments_seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
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

        if "M3" in upper or "M03" in upper:
            spindle_down = True
            first_pen_down_seen = True
        if "M5" in upper or "M05" in upper:
            spindle_down = False

        old_x, old_y, old_z = cur_x, cur_y, cur_z
        modal = _motion_code(line, modal)

        # G92 sets the current coordinate system; for preflight we treat it as the
        # current machine position because the generated files use it for Z lift.
        if re.search(r"(^|\s)G92(\s|$)", upper):
            cur_x = vals.get("X", cur_x)
            cur_y = vals.get("Y", cur_y)
            cur_z = vals.get("Z", cur_z)
            continue

        next_x = vals.get("X", cur_x)
        next_y = vals.get("Y", cur_y)
        next_z = vals.get("Z", cur_z)
        has_xy = "X" in vals or "Y" in vals
        has_z = "Z" in vals

        was_down = _is_pen_down(cur_z, z_up, z_down, spindle_down)
        would_be_down = _is_pen_down(next_z, z_up, z_down, spindle_down)
        if has_z and not was_down and would_be_down:
            first_pen_down_seen = True
            if has_xy:
                problems.append(f"{gcode_path.name}: line {lines}: pen-down command also moves XY")

        if has_xy:
            first_xy_seen = True
            if not first_pen_down_seen and would_be_down:
                problems.append(f"{gcode_path.name}: line {lines}: first XY move happens with pen down")
            if modal == "G0" and would_be_down:
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
                    if draw_bounds is None:
                        draw_bounds = [x0, x1, y0, y1]
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
        bounds=bounds,
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


def _require_file(package_dir: Path, rel: str, problems: list[str]) -> None:
    if not (package_dir / rel).exists():
        problems.append(f"missing {rel}")


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
    duplicate_count = _metrics_duplicate_count(selected_item)
    if duplicate_count > 0:
        problems.append(f"selected route reports duplicate segments={duplicate_count}")

    items = {str(row.get("item") or "") for row in rows}
    gcode_paths: list[Path] = []
    if items == {"page_01"}:
        _require_file(package_dir, "a4_clean_source.pdf", problems)
        _require_file(package_dir, "page_01.pdf", problems)
        _require_file(package_dir, "page_01.gcode", problems)
        gcode_paths.append(package_dir / "page_01.gcode")
    elif {"pass_01", "pass_02"}.issubset(items):
        _require_file(package_dir, "combined_preview.pdf", problems)
        for pass_name in ("pass_01", "pass_02"):
            _require_file(package_dir, f"{pass_name}.pdf", problems)
            _require_file(package_dir, f"{pass_name}.gcode", problems)
            gcode_paths.append(package_dir / f"{pass_name}.gcode")
    else:
        problems.append(f"unknown package items: {sorted(items)}")

    gcode_results: dict[str, GcodeValidation] = {}
    for gcode_path in gcode_paths:
        if not gcode_path.exists():
            continue
        result = validate_gcode_file(gcode_path)
        gcode_results[gcode_path.name] = result
        problems.extend(result.problems)
        warnings.extend(result.warnings)

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
    payload = {
        "variant_dir": str(variant_dir),
        "ok": not failed,
        "packages": len(packages),
        "failed_packages": [
            {
                "package_dir": pkg.package_dir,
                "problems": pkg.problems,
                "warnings": pkg.warnings,
            }
            for pkg in failed
        ],
        "warnings": warnings,
        "preflight": {
            "checked_gcode_files": sum(len(pkg.gcode) for pkg in packages),
            "duplicate_segments": sum(result.duplicate_segments for pkg in packages for result in pkg.gcode.values()),
        },
    }
    if write_reports:
        (variant_dir / "_ready_to_plot_audit.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
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
