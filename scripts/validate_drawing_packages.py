from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import plotter_pdf_drawer as backend  # noqa: E402


DEFAULT_ROOTS = [
    PROJECT_ROOT / "Компьютерная графика",
    PROJECT_ROOT / "Начерт",
]
REQUIRED_REPORT_FIELDS = {
    "frame_class",
    "route_class",
    "selected_variant",
    "selection_reason",
    "source_fidelity_score",
    "fragmentation_score",
    "compare_generated",
}
BAD_AUTO_FINAL_VARIANTS = {"strict_1to1_clip"}
BAD_KOMPAS_VARIANTS = {"a4_hybrid_frame", "strict_1to1_clip"}


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str
    path: str


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_summary_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        return list(csv.DictReader(path.open("r", encoding="utf-8-sig", newline="")))
    except Exception:
        return []


def _under_dir(path: Path, name: str) -> bool:
    token = name.casefold()
    return any(token in part.casefold() for part in path.parts)


def _is_ignored_nested_dir(path: Path) -> bool:
    ignored = {"logs", "pages", "_candidates", "_audit", "_generated_pdf", "__pycache__"}
    return any(part in ignored for part in path.parts)


def collect_package_dirs(roots: list[Path]) -> list[Path]:
    packages: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        root = root.resolve()
        if not root.exists():
            continue
        candidates = [root] if root.name.endswith("_pack") else list(root.rglob("*_pack"))
        for candidate in candidates:
            if not candidate.is_dir() or _is_ignored_nested_dir(candidate.relative_to(root) if candidate != root else candidate):
                continue
            key = str(candidate.resolve()).casefold()
            if key in seen:
                continue
            packages.append(candidate)
            seen.add(key)
    return sorted(packages, key=lambda p: str(p).casefold())


def _strip_comments(line: str) -> str:
    text = (line or "").strip()
    if ";" in text:
        text = text.split(";", 1)[0].strip()
    while "(" in text and ")" in text:
        left = text.find("(")
        right = text.find(")", left + 1)
        if right < 0:
            break
        text = (text[:left] + " " + text[right + 1 :]).strip()
    return text


def first_xy_pen_down_issue(path: Path) -> dict[str, Any] | None:
    x_re = re.compile(r"\bX(-?\d+(?:\.\d+)?)")
    y_re = re.compile(r"\bY(-?\d+(?:\.\d+)?)")
    z_re = re.compile(r"\bZ(-?\d+(?:\.\d+)?)")
    z_up = float(backend.Z_UP)
    z_down = float(backend.Z_DOWN)
    cur_z = z_up
    pen_down = backend._pen_down_from_z_level(cur_z, z_up, z_down)
    for line_no, raw in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        line = _strip_comments(raw)
        if not line:
            continue
        if re.search(r"\bM3\b", line):
            pen_down = True
        if re.search(r"\bM5\b", line):
            pen_down = False
        z_match = z_re.search(line)
        if z_match:
            cur_z = float(z_match.group(1))
            pen_down = backend._pen_down_from_z_level(cur_z, z_up, z_down)
        if x_re.search(line) or y_re.search(line):
            if pen_down:
                return {"line": line_no, "text": raw.strip()}
            return None
    return None


def _canonical_segment_key(a: tuple[float, float], b: tuple[float, float], ndigits: int = 3) -> tuple[tuple[float, float], tuple[float, float]]:
    p0 = (round(float(a[0]), ndigits), round(float(a[1]), ndigits))
    p1 = (round(float(b[0]), ndigits), round(float(b[1]), ndigits))
    return (p0, p1) if p0 <= p1 else (p1, p0)


def duplicate_segment_metrics(paths: list[Path]) -> dict[str, Any]:
    x_re = re.compile(r"\bX(-?\d+(?:\.\d+)?)")
    y_re = re.compile(r"\bY(-?\d+(?:\.\d+)?)")
    z_re = re.compile(r"\bZ(-?\d+(?:\.\d+)?)")
    g_re = re.compile(r"\bG(\d+(?:\.\d+)?)")
    m_re = re.compile(r"\bM(\d+(?:\.\d+)?)")
    z_up = float(backend.Z_UP)
    z_down = float(backend.Z_DOWN)
    total = 0
    duplicate = 0
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for path in paths:
        cur_x = 0.0
        cur_y = 0.0
        cur_z = z_up
        pen_down = backend._pen_down_from_z_level(cur_z, z_up, z_down)
        last_motion: int | None = None
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = _strip_comments(raw)
            if not line:
                continue
            motion = None
            for gm in g_re.findall(line):
                try:
                    val = int(float(gm))
                except Exception:
                    continue
                if val in {0, 1, 2, 3}:
                    motion = val
            if motion is None:
                motion = last_motion
            elif motion in {0, 1, 2, 3}:
                last_motion = motion
            for mm in m_re.findall(line):
                try:
                    m_val = int(float(mm))
                except Exception:
                    continue
                if m_val == 3:
                    pen_down = True
                elif m_val == 5:
                    pen_down = False
            z_match = z_re.search(line)
            if z_match:
                cur_z = float(z_match.group(1))
                pen_down = backend._pen_down_from_z_level(cur_z, z_up, z_down)
            x_match = x_re.search(line)
            y_match = y_re.search(line)
            next_x = float(x_match.group(1)) if x_match else cur_x
            next_y = float(y_match.group(1)) if y_match else cur_y
            if pen_down and motion == 1 and (x_match or y_match):
                if math.hypot(next_x - cur_x, next_y - cur_y) > 1e-6:
                    total += 1
                    key = _canonical_segment_key((cur_x, cur_y), (next_x, next_y))
                    if key in seen:
                        duplicate += 1
                    else:
                        seen.add(key)
            cur_x = next_x
            cur_y = next_y
    ratio = float(duplicate) / float(total) if total else 0.0
    return {"segments": total, "duplicate_segments": duplicate, "duplicate_ratio": round(ratio, 6)}


def _add_issue(issues: list[ValidationIssue], severity: str, code: str, message: str, path: Path) -> None:
    issues.append(ValidationIssue(severity=severity, code=code, message=message, path=str(path)))


def _expected_frame_class(package_dir: Path) -> str | None:
    if _under_dir(package_dir, "Начерт"):
        return "standard_frame"
    if _under_dir(package_dir, "Компьютерная графика"):
        return "kompas_full_frame"
    return None


def _production_gcode_paths(package_dir: Path, is_a3: bool) -> list[Path]:
    names = ["pass_01.gcode", "pass_02.gcode"] if is_a3 else ["page_01.gcode"]
    return [package_dir / name for name in names if (package_dir / name).exists()]


def validate_package(package_dir: Path) -> dict[str, Any]:
    issues: list[ValidationIssue] = []
    report_path = package_dir / "report.json"
    summary_path = package_dir / "summary.csv"
    report = _load_json(report_path) if report_path.exists() else {}
    rows = _read_summary_rows(summary_path)
    is_a3 = bool(report.get("a3_two_pass", False)) or (package_dir / "pass_01.gcode").exists()

    for required in [report_path, summary_path, package_dir / "logs", package_dir / "pages"]:
        if not required.exists():
            _add_issue(issues, "fail", "missing_required_artifact", f"Missing required artifact: {required.name}", required)

    for ext in ("pdf", "png"):
        compare_path = package_dir / f"source_vs_gcode_compare.{ext}"
        if not compare_path.exists():
            _add_issue(issues, "fail", "missing_compare", f"Missing source_vs_gcode_compare.{ext}", compare_path)

    if report:
        missing_fields = sorted(field for field in REQUIRED_REPORT_FIELDS if field not in report)
        for field in missing_fields:
            _add_issue(issues, "fail", "missing_report_field", f"Missing report field: {field}", report_path)
        if not bool(report.get("compare_generated", False)):
            _add_issue(issues, "fail", "compare_not_marked_generated", "report.compare_generated is not true", report_path)
        expected_frame = _expected_frame_class(package_dir)
        frame_class = str(report.get("frame_class", "") or "")
        if expected_frame and frame_class != expected_frame:
            _add_issue(issues, "fail", "frame_class_mismatch", f"Expected {expected_frame}, got {frame_class or '<empty>'}", report_path)
        selected = str(report.get("selected_variant", "") or "")
        if selected in BAD_AUTO_FINAL_VARIANTS:
            _add_issue(issues, "fail", "bad_auto_final_variant", f"Production package selected {selected}", report_path)
        if expected_frame == "kompas_full_frame" and selected in BAD_KOMPAS_VARIANTS:
            _add_issue(issues, "fail", "bad_kompas_variant", f"KOMPAS package selected forbidden variant {selected}", report_path)
        if expected_frame == "standard_frame" and selected == "mupdf_svg_paths":
            _add_issue(issues, "fail", "bad_nachert_variant", "Nachert standard frame selected direct KOMPAS route", report_path)
        if bool(report.get("custom_tiled", False)):
            _add_issue(issues, "fail", "custom_tiled_forbidden", "Production drawing package used custom_tiled", report_path)

    required_files = (
        ["pass_01.pdf", "pass_01.gcode", "pass_02.pdf", "pass_02.gcode", "combined_preview.pdf"]
        if is_a3
        else ["a4_clean_source.pdf", "page_01.pdf", "page_01.gcode"]
    )
    for name in required_files:
        path = package_dir / name
        if not path.exists():
            _add_issue(issues, "fail", "missing_output_file", f"Missing output file: {name}", path)

    gcode_paths = sorted(
        set(package_dir.glob("*.gcode"))
        | set(package_dir.glob("*.nc"))
        | set((package_dir / "pages").glob("*.gcode"))
        | set((package_dir / "pages").glob("*.nc")),
        key=lambda p: str(p).casefold(),
    )
    if not gcode_paths:
        _add_issue(issues, "fail", "missing_gcode", "No G-code files found", package_dir)
    for gcode_path in gcode_paths:
        ok, msg = backend.preflight_check_gcode(gcode_path, logger=lambda *_args: None)
        if not ok:
            _add_issue(issues, "fail", "gcode_preflight_failed", msg, gcode_path)
        start_issue = first_xy_pen_down_issue(gcode_path)
        if start_issue:
            _add_issue(
                issues,
                "fail",
                "first_xy_with_pen_down",
                f"First XY move happens with pen down at line {start_issue['line']}: {start_issue['text']}",
                gcode_path,
            )

    production_paths = _production_gcode_paths(package_dir, is_a3)
    duplicate_metrics = duplicate_segment_metrics(production_paths)
    if float(duplicate_metrics["duplicate_ratio"]) > 0.08:
        _add_issue(
            issues,
            "warn",
            "duplicate_segments_high",
            f"Duplicate drawn segment ratio is {duplicate_metrics['duplicate_ratio']}",
            package_dir,
        )

    frag = {"pen_down_strokes": 0, "tiny_strokes_lt_08_mm": 0, "point_like_strokes": 0}
    for row in rows:
        for key in frag:
            try:
                frag[key] += int(float(row.get(key, "0") or 0))
            except Exception:
                pass
    if frag["point_like_strokes"] > 1200 or frag["tiny_strokes_lt_08_mm"] > 2500:
        _add_issue(issues, "warn", "fragmentation_high", f"High fragmentation metrics: {frag}", summary_path)

    failed = [issue for issue in issues if issue.severity == "fail"]
    warnings = [issue for issue in issues if issue.severity == "warn"]
    return {
        "package_dir": str(package_dir),
        "ok": not failed,
        "kind": "a3_two_pass" if is_a3 else "a4",
        "report": {
            "frame_class": report.get("frame_class"),
            "route_class": report.get("route_class"),
            "selected_variant": report.get("selected_variant"),
            "selected_layout_similarity": report.get("selected_layout_similarity"),
            "source_fidelity_score": report.get("source_fidelity_score"),
            "fragmentation_score": report.get("fragmentation_score"),
        },
        "preflight": {"checked_files": len(gcode_paths), "failed": len([i for i in failed if i.code == "gcode_preflight_failed"])},
        "pen_start": {"failed": len([i for i in failed if i.code == "first_xy_with_pen_down"])},
        "bounds": {"checked_by_preflight": True},
        "fragmentation": frag,
        "duplicates": duplicate_metrics,
        "compare": {
            "pdf": str(package_dir / "source_vs_gcode_compare.pdf"),
            "png": str(package_dir / "source_vs_gcode_compare.png"),
            "generated": bool(report.get("compare_generated", False)),
        },
        "issues": [asdict(issue) for issue in issues],
        "warnings": [asdict(issue) for issue in warnings],
    }


def validate_roots(roots: list[Path]) -> dict[str, Any]:
    packages = collect_package_dirs(roots)
    package_results = [validate_package(package) for package in packages]
    failed = [item for item in package_results if not bool(item.get("ok"))]
    warnings = [issue for item in package_results for issue in item.get("warnings", [])]
    return {
        "ok": not failed,
        "roots": [str(path) for path in roots],
        "package_count": len(package_results),
        "failed_count": len(failed),
        "warning_count": len(warnings),
        "failed_packages": [item["package_dir"] for item in failed],
        "warnings": warnings,
        "packages": package_results,
    }


def _write_text_report(report: dict[str, Any], path: Path) -> None:
    lines = [
        f"ok={report['ok']}",
        f"package_count={report['package_count']}",
        f"failed_count={report['failed_count']}",
        f"warning_count={report['warning_count']}",
    ]
    for item in report.get("packages", []):
        status = "OK" if item.get("ok") else "FAIL"
        lines.append(f"{status} {item.get('package_dir')}")
        for issue in item.get("issues", []):
            lines.append(f"  {issue['severity']} {issue['code']}: {issue['message']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate drawing packages before plotting, without touching the machine.")
    parser.add_argument("--root", action="append", default=[], help="Root or *_pack directory to validate. Defaults to Computer Graphics and Nachert.")
    parser.add_argument("--output-json", default=str(PROJECT_ROOT / "_tmp" / "ready_to_plot_report.json"))
    parser.add_argument("--output-txt", default=str(PROJECT_ROOT / "_tmp" / "ready_to_plot_report.txt"))
    parser.add_argument("--allow-warnings", action="store_true", help="Exit 0 when only warnings are present. Failures still return non-zero.")
    args = parser.parse_args()

    roots = [Path(item).resolve() for item in args.root] if args.root else [path.resolve() for path in DEFAULT_ROOTS]
    report = validate_roots(roots)
    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    _write_text_report(report, Path(args.output_txt))
    print(json.dumps({k: report[k] for k in ("ok", "package_count", "failed_count", "warning_count")}, ensure_ascii=False))
    if report["failed_count"]:
        return 1
    if report["warning_count"] and not args.allow_warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
