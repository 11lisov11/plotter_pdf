"""Optional frameless, single-pass title block for registered A2/A1 jobs only."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, replace
from pathlib import Path

from .small_sheet_tiling import (
    Point, Polyline, Rect, SHEET_SIZES, StitchConfig, Tile, _clip_segment, _cross,
    _point_segment_distance, _write_nc, clip_paths, plan_tiles,
    prepare_stitched_job, registration_marks, to_machine,
)


def title_block_bbox(paths: list[Polyline], width: float, height: float) -> Rect | None:
    candidates = []
    for poly in paths:
        for a, b in zip(poly, poly[1:]):
            left, right = sorted((a[0], b[0]))
            if (abs(a[1] - b[1]) < 0.01 and 175 <= right - left <= 195
                    and left > width * 0.5 and right > width * 0.9 and a[1] > height * 0.75):
                candidates.append((left, a[1], right))
    for left, top, right in sorted(candidates, key=lambda item: item[1]):
        bottoms = [y for x0, y, x1 in candidates
                   if abs(x0 - left) < 0.15 and abs(x1 - right) < 0.15 and 40 <= y - top <= 80]
        if bottoms:
            return left, top, right, max(bottoms)
    return None


def remove_sheet_frame(paths: list[Polyline], width: float, height: float,
                       stamp: Rect | None) -> list[Polyline]:
    """Remove long page-border segments, preserving shared title-block edges."""
    output = []
    for poly in paths:
        current = []
        for a, b in zip(poly, poly[1:]):
            horizontal = (abs(a[1] - b[1]) < 0.01 and abs(a[0] - b[0]) > width * 0.7
                          and (a[1] < 10 or a[1] > height - 10))
            vertical = (abs(a[0] - b[0]) < 0.01 and abs(a[1] - b[1]) > height * 0.7
                        and (a[0] < 25 or a[0] > width - 10))
            segment = _clip_segment(a, b, stamp) if stamp is not None else None
            pieces = ([segment] if segment is not None else []) if horizontal or vertical else [(a, b)]
            if not pieces:
                if len(current) > 1:
                    output.append(current)
                current = []
            for start, end in pieces:
                if current and math.dist(current[-1], start) < 1e-7:
                    current.append(end)
                else:
                    if len(current) > 1:
                        output.append(current)
                    current = [start, end]
        if len(current) > 1:
            output.append(current)
    return output


def _outside_paths(paths: list[Polyline], rect: Rect) -> list[Polyline]:
    result = []
    for poly in paths:
        current = []
        for a, b in zip(poly, poly[1:]):
            inside = _clip_segment(a, b, rect)
            if inside is None:
                pieces = [(a, b)]
            else:
                start, end = inside
                pieces = [(p, q) for p, q in ((a, start), (end, b)) if math.dist(p, q) > 1e-7]
            if not pieces:
                if len(current) > 1:
                    result.append(current)
                current = []
            for start, end in pieces:
                if current and math.dist(current[-1], start) < 1e-7:
                    current.append(end)
                else:
                    if len(current) > 1:
                        result.append(current)
                    current = [start, end]
        if len(current) > 1:
            result.append(current)
    return result


def _registration_for_stamp(previous: Tile, following: Tile, paths: list[Polyline],
                            config: StitchConfig) -> tuple[Point, Point]:
    a, b = previous.window_mm, following.window_mm
    left, top, right, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    clearance = config.mark_radius_mm + config.mark_clearance_mm
    margin = max(clearance + 0.5, min(12.0, (right - left) * 0.04))
    start, finish = left + margin, right - margin
    separation = max(20.0, min(80.0, (right - left) * 0.55))
    if finish - start < separation or bottom - top <= 2 * (clearance + 0.5):
        raise ValueError("Not enough shared paper for two title-block registration marks")
    segments = [(p, q) for poly in paths for p, q in zip(poly, poly[1:])
                if max(p[0], q[0]) >= left - clearance and min(p[0], q[0]) <= right + clearance
                and max(p[1], q[1]) >= top - clearance and min(p[1], q[1]) <= bottom + clearance]
    positions = [start + i * 2 for i in range(math.floor((finish - start) / 2) + 1)] + [finish]
    # Blank table cells are still part of the title block, not registration
    # space. Reserve the WHOLE block, not only its existing ink strokes.
    stamp = following.draw_rect_mm
    reserved = (stamp[0] - clearance, stamp[1] - clearance,
                stamp[2] + clearance, stamp[3] + clearance)
    y = bottom - clearance - 0.5
    while y >= top + clearance + 0.5:
        free = [(x, y) for x in positions
                if not (reserved[0] <= x <= reserved[2] and reserved[1] <= y <= reserved[3])
                and all(_point_segment_distance((x, y), p, q) > clearance for p, q in segments)]
        if free and math.dist(free[0], free[-1]) >= separation:
            return free[0], free[-1]
        y -= 1
    raise ValueError("No clear pair of registration marks for the separate title-block pass")


def _compact_body_order(grid: list[Tile], body: list[Polyline], stamp_tile: Tile,
                        avoidance: list[Polyline], config: StitchConfig) -> tuple[list[Tile], tuple[Point, Point]]:
    active = {(tile.row, tile.column): tile for tile in grid if clip_paths(body, tile.draw_rect_mm)}
    if not active:
        raise ValueError("No drawing geometry remains outside the title block")
    rows = sorted({key[0] for key in active})
    columns = sorted({key[1] for key in active})
    candidates = []
    edge_marks = {}
    seen = set()
    # Row- and column-serpentine alternatives allow a nonempty-only route to
    # finish beside the stamp, instead of traversing blank outer grid cells.
    for column_first in (False, True):
        for reverse_outer in (False, True):
            for reverse_inner in (False, True):
                outer = list(columns if column_first else rows)
                if reverse_outer:
                    outer.reverse()
                order = []
                for position, major in enumerate(outer):
                    inner = list(rows if column_first else columns)
                    if bool(position % 2) != reverse_inner:
                        inner.reverse()
                    for minor in inner:
                        key = (minor, major) if column_first else (major, minor)
                        if key in active:
                            order.append(active[key])
                identity = tuple((tile.row, tile.column) for tile in order)
                if identity in seen:
                    continue
                seen.add(identity)
                if any(abs(a.row - b.row) + abs(a.column - b.column) != 1 for a, b in zip(order, order[1:])):
                    continue
                try:
                    for a, b in zip(order, order[1:]):
                        edge = tuple(sorted(((a.row, a.column), (b.row, b.column))))
                        if edge not in edge_marks:
                            edge_marks[edge] = registration_marks(a, b, avoidance, config)
                    marks = _registration_for_stamp(order[-1], stamp_tile, avoidance, config)
                except ValueError:
                    continue
                score = (order[0].row, order[0].column,
                         sum(math.dist(a.origin_mm, b.origin_mm) for a, b in zip(order, order[1:])))
                candidates.append((score, order, marks))
    if not candidates:
        raise ValueError("No safe nonempty-only registration route to the title block; "
                         "layout must be revised rather than silently drawing blank passes")
    _, order, marks = min(candidates, key=lambda candidate: candidate[0])
    return [replace(tile, number=number) for number, tile in enumerate(order, 1)], marks


def _save_job(output: Path, job: dict) -> None:
    (output / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="ascii")
    referenced = {job["initialize"]["file"], *(tile["file"] for tile in job["tiles"])}
    for transition in job["transitions"]:
        referenced.update((transition["check_secondary"]["file"], transition["return_primary"]["file"]))
    # Only obsolete files owned by this generator, never arbitrary user files.
    for path in output.glob("*.nc"):
        if re.fullmatch(r"(?:pass_\d+|align_\d+_[AB])\.nc", path.name) and path.name not in referenced:
            path.unlink()


def prepare_sheet_job(paths: list[Polyline], width: float, height: float, sheet_format: str,
                      output: Path, *, config: StitchConfig = StitchConfig(),
                      trial_first_two: bool = False, no_frame: bool = False,
                      whole_stamp: bool = False, fit_format: bool = False) -> dict:
    if fit_format:
        if trial_first_two or not no_frame or not whole_stamp:
            raise ValueError("Explicit format fitting currently requires a complete --no-frame --whole-stamp job")
        name = sheet_format.upper()
        if name not in SHEET_SIZES:
            raise ValueError("Explicit format fitting supports A2/A1 only")
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            raise ValueError("Invalid source page dimensions")
        original_box = title_block_bbox(paths, width, height)
        if original_box is None:
            raise ValueError("Could not identify the original title block before format fitting")
        cleaned_source = remove_sheet_frame(paths, width, height, original_box)
        original_stamp = clip_paths(cleaned_source, original_box)
        original_body = _outside_paths(cleaned_source, original_box)
        target_width, target_height = SHEET_SIZES[name]
        if width < height:
            target_width, target_height = target_height, target_width
        source_scale = min(target_width / width, target_height / height)
        fitted_body = [[(x * source_scale, y * source_scale) for x, y in poly] for poly in original_body]
        # The paper format changes the drawing scale, not the standard title
        # block size. Keep its native vectors/text and let the dedicated pass
        # reduce ONLY that block to the established 180 mm work-field width.
        dx = target_width - 5.0 - original_box[2]
        dy = target_height - 5.0 - original_box[3]
        translated_stamp = [[(x + dx, y + dy) for x, y in poly] for poly in original_stamp]
        job = prepare_sheet_job([*fitted_body, *translated_stamp], target_width, target_height, name,
                                output, config=config, no_frame=False, whole_stamp=True)
        job["frame_removed"] = True
        job["drawing_scale"] = source_scale
        job["source_fit"] = {"source_size_mm": [width, height],
                             "target_size_mm": [target_width, target_height],
                             "uniform_drawing_scale": source_scale,
                             "title_block_scaled_independently": True,
                             "title_block_edge_margin_mm": 5.0}
        job["title_block"]["drawing_scale"] = source_scale
        _save_job(output, job)
        return job
    if not no_frame and not whole_stamp:
        return prepare_stitched_job(paths, width, height, sheet_format, output,
                                    config=config, trial_first_two=trial_first_two)
    if trial_first_two:
        raise ValueError("Frame/title-block options require a complete source sheet, not the synthetic trial")
    bbox = title_block_bbox(paths, width, height)
    cleaned = remove_sheet_frame(paths, width, height, bbox) if no_frame else paths
    if not whole_stamp:
        job = prepare_stitched_job(cleaned, width, height, sheet_format, output, config=config)
        job["frame_removed"] = no_frame
        _save_job(output, job)
        return job
    if bbox is None:
        raise ValueError("Could not identify the complete bottom-right title block; refusing to guess")
    original_stamp = clip_paths(cleaned, bbox)
    body = _outside_paths(cleaned, bbox)
    factor = min(1.0, config.work_width / (bbox[2] - bbox[0]))
    scaled = [[(bbox[2] - (bbox[2] - x) * factor, bbox[3] - (bbox[3] - y) * factor)
               for x, y in poly] for poly in original_stamp]
    target = (bbox[2] - (bbox[2] - bbox[0]) * factor,
              bbox[3] - (bbox[3] - bbox[1]) * factor, bbox[2], bbox[3])
    if target[3] - target[1] > config.work_height:
        raise ValueError("Title block is too tall for a single pass")
    full_grid, _ = plan_tiles(width, height, sheet_format, config)
    origin = (bbox[2] - config.work_width, height - config.work_height)
    provisional_stamp = Tile(0, 0, 0, origin,
                      (origin[0], origin[1], bbox[2], height), target)
    avoidance = [*body, *scaled]
    grid, marks = _compact_body_order(full_grid, body, provisional_stamp, avoidance, config)
    previous = grid[-1]
    number = previous.number + 1
    stamp_tile = replace(provisional_stamp, number=number)
    # All geometry/layout decisions above are resolved before executable files.
    job = prepare_stitched_job(body, width, height, sheet_format, output, config=config,
                               tiles_override=grid, registration_paths=avoidance)
    previous_index = previous.number - 1
    prefix = job["tiles"][:previous_index + 1]
    previous_ink = clip_paths(body, previous.draw_rect_mm)
    for center in marks:
        previous_ink.extend(_cross(center, config.mark_radius_mm))
    old_points = [to_machine(p, previous, config) for p in marks]
    next_points = [to_machine(p, stamp_tile, config) for p in marks]
    previous_machine = [[to_machine(p, previous, config) for p in poly] for poly in previous_ink]
    prefix[-1].update(_write_nc(output / prefix[-1]["file"], previous_machine, next_points[0], config))
    prefix[-1]["end_park_mm"] = next_points[0]
    prefix[-1]["pen_down_paths"] = len(previous_machine)
    stamp_machine = [[to_machine(p, stamp_tile, config) for p in poly] for poly in scaled]
    stamp_record = {**asdict(stamp_tile),
                    **_write_nc(output / f"pass_{number:02d}.nc", stamp_machine, (0, 0), config),
                    "role": "title_block", "stamp_bbox_mm": target, "stamp_scale": factor,
                    "end_park_mm": (0, 0), "pen_down_paths": len(stamp_machine)}
    transition = {"from_pass": previous.number, "to_pass": number,
                  "marks_paper_mm": marks, "previous_machine_mm": old_points, "next_machine_mm": next_points,
                  "check_secondary": _write_nc(output / f"align_{number:02d}_B.nc", [], next_points[1], config),
                  "return_primary": _write_nc(output / f"align_{number:02d}_A.nc", [], next_points[0], config)}
    job["tiles"] = [*prefix, stamp_record]
    job["transitions"] = [*job["transitions"][:previous_index], transition]
    job["full_pass_count"] = len(job["tiles"])
    job["grid_pass_count"] = len(prefix)
    job["start_window_mm"] = prefix[0]["window_mm"]
    job["empty_passes_removed"] = True
    job["frame_removed"] = no_frame
    job["title_block"] = {"original_bbox_mm": bbox, "target_bbox_mm": target,
                          "scale": factor, "width_mm": target[2] - target[0],
                          "pass_number": number, "dedicated_pass": True,
                          "anchor": "original_bottom_right", "drawing_scale": 1.0}
    _save_job(output, job)
    return job
