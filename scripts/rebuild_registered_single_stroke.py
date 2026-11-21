"""OFFLINE ONLY: rebuild registered NC without re-recognizing text or moving a plotter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from scripts.prepare_small_sheet_tiles import preview_from_gcode
from src.plotter_backend.geometry.small_sheet_tiling import SCHEMA, StitchConfig, _write_nc

WORDS = re.compile(r"([A-Z])([-+]?\d+(?:\.\d*)?)")


def decode_nc(payload: bytes, config: StitchConfig):
    """Strict modal replay of the registered linear dialect; keep tiny strokes."""
    x = y = None
    z = config.z_up
    path = None
    paths = []
    mm = absolute = False
    for raw in payload.decode("ascii").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        words = {k: float(v) for k, v in WORDS.findall(line)}
        g = words.get("G")
        if g == 21:
            mm = True
        elif g == 90:
            absolute = True
        elif g in (94, 17, 4):
            pass
        elif g in (0, 1):
            if not mm or not absolute:
                raise ValueError("Motion before absolute millimeter setup")
            nx, ny, nz = words.get("X", x), words.get("Y", y), words.get("Z", z)
            if "Z" in words:
                if nz not in (config.z_up, config.z_down):
                    raise ValueError("Unexpected pen height")
                if nz == config.z_down and z == config.z_up:
                    if x is None or y is None:
                        raise ValueError("Pen lowered without an XY position")
                    path = [(x, y)]
                if nz == config.z_up and path is not None:
                    if len(path) > 1:
                        paths.append(path)
                    path = None
            if "X" in words or "Y" in words:
                if nx is None or ny is None:
                    raise ValueError("Incomplete XY position")
                if z == config.z_down:
                    if g != 1 or path is None:
                        raise ValueError("Unsafe pen-down rapid")
                    if (nx, ny) != (x, y):
                        path.append((nx, ny))
                elif g != 0:
                    raise ValueError("Unexpected pen-up drawing move")
            x, y, z = nx, ny, nz
        else:
            raise ValueError(f"Unsupported registered command: {line}")
    if z != config.z_up or path is not None:
        raise ValueError("File does not end pen-up")
    return paths, (x, y)


def coverage(paths):
    """Independent interval audit of serialized 0.001-mm segments."""
    lines = defaultdict(list)
    exact = Counter()
    length = 0.0
    count = 0
    for poly in paths:
        for a, b in zip(poly, poly[1:]):
            a = tuple(int(round(v * 1000)) for v in a)
            b = tuple(int(round(v * 1000)) for v in b)
            dx, dy = b[0] - a[0], b[1] - a[1]
            divisor = math.gcd(abs(dx), abs(dy))
            if not divisor:
                continue
            ux, uy = dx // divisor, dy // divisor
            if ux < 0 or (ux == 0 and uy < 0):
                ux, uy = -ux, -uy
            key = ux, uy, ux * a[1] - uy * a[0]
            lines[key].append(tuple(sorted((ux * a[0] + uy * a[1], ux * b[0] + uy * b[1]))))
            exact[tuple(sorted((a, b)))] += 1
            length += math.hypot(dx, dy) / 1000
            count += 1
    union = {}
    union_length = 0.0
    for key, intervals in lines.items():
        merged = []
        for lo, hi in sorted(intervals):
            if merged and lo <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(hi, merged[-1][1])
            else:
                merged.append((lo, hi))
        union[key] = merged
        union_length += sum(hi - lo for lo, hi in merged) / math.hypot(key[0], key[1]) / 1000
    return union, {"segments": count, "draw_length_mm": round(length, 6),
                   "exact_repeated_segments": sum(n - 1 for n in exact.values()),
                   "overdraw_mm": round(max(0.0, length - union_length), 6)}


def rebuild(folder: Path, backup_root: Path):
    folder = folder.resolve()
    manifest = folder / "job.json"
    original_manifest = manifest.read_bytes()
    job = json.loads(original_manifest)
    if job.get("schema") != SCHEMA or job.get("machine_profile") != "a4_desktop":
        raise ValueError("Not a registered small-plotter job")
    config = StitchConfig(**job["config"])
    records = [job["initialize"], *job["tiles"]]
    for transition in job["transitions"]:
        records += [transition["check_secondary"], transition["return_primary"]]
    inputs = {}
    for record in records:
        path = (folder / record["file"]).resolve()
        if path.parent != folder:
            raise ValueError("File escapes job directory")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError(f"Input hash mismatch: {path.name}")
        inputs[path.name] = payload
    backup = backup_root / folder.name
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "job.json").write_bytes(original_manifest)
    for name, payload in inputs.items():
        (backup / name).write_bytes(payload)
    summaries = []
    for record in job["tiles"]:
        name = record["file"]
        before, old_park = decode_nc(inputs[name], config)
        target = tuple(record["end_park_mm"])
        if math.dist(old_park, target) > 0.002:
            raise ValueError("Original parking position mismatch")
        old_union, old_stats = coverage(before)
        result = _write_nc(folder / name, before, target, config)
        # Requested proof/preview uses the actual newly serialized NC.
        after, new_park = decode_nc((folder / name).read_bytes(), config)
        new_union, new_stats = coverage(after)
        if new_union != old_union:
            raise ValueError(f"Geometry coverage changed: {name}; original is in {backup}")
        if new_stats["exact_repeated_segments"] or new_stats["overdraw_mm"] > 0.000001:
            raise ValueError(f"Retracing remains: {name}")
        if math.dist(new_park, target) > 0.002:
            raise ValueError("Rebuilt parking position mismatch")
        record.update(result)
        summaries.append({"file": name, "before": old_stats, "after": new_stats,
                          "geometry_coverage_unchanged": True, "parking_unchanged": True})
    job["single_stroke_output"] = {"version": "integer-interval-union/v1", "precision_mm": 0.001,
                                   "geometry_source": "previous_serialized_nc_no_text_recognition",
                                   "previous_files": str(backup), "passes": summaries}
    manifest.write_text(json.dumps(job, indent=2) + "\n", encoding="ascii")
    pdf = preview_from_gcode(folder, job)
    preview_dir = ROOT / "tmp" / "pdfs"
    preview_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf) as doc:
        overview = preview_dir / f"{folder.name}_single_stroke_overview.png"
        doc[0].get_pixmap(matrix=fitz.Matrix(0.8, 0.8), alpha=False).save(overview)
        # A complete stamp on its real work-field page, with a tight image crop.
        stamp_record = next((r for r in job["tiles"] if r.get("role") == "title_block"), None)
        stamp_image = None
        if stamp_record:
            paths, _ = decode_nc((folder / stamp_record["file"]).read_bytes(), config)
            points = [point for poly in paths for point in poly]
            xs, ys = zip(*points)
            mm = 72 / 25.4
            rect = fitz.Rect((15 + min(xs) - 3) * mm, (8.5 + min(ys) - config.work_min_y - 3) * mm,
                             (15 + max(xs) + 3) * mm, (8.5 + max(ys) - config.work_min_y + 3) * mm)
            stamp_image = preview_dir / f"{folder.name}_single_stroke_stamp.png"
            doc[stamp_record["number"]].get_pixmap(matrix=fitz.Matrix(3, 3), clip=rect, alpha=False).save(stamp_image)
    return {"job": str(folder), "passes": summaries, "backup": str(backup),
            "pdf": str(pdf), "overview": str(overview), "stamp_image": str(stamp_image),
            "hardware_accessed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="+", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_UTC") + "_" + uuid4().hex[:6]
    backup = ROOT / "backups" / "single_stroke" / stamp
    for folder in args.jobs:
        print(json.dumps(rebuild(folder, backup), ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
