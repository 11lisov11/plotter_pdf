"""Translate canonical mm paths into registered A2/A1 small-plotter passes.

This is deliberately downstream of recognition and separate from A4/A3.
Paper coordinates: top-left origin, X right, Y down. No reflection/rotation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

Point = tuple[float, float]
Polyline = list[Point]
Rect = tuple[float, float, float, float]
SCHEMA = "small-sheet-stitch/v1"
PAPER_REGISTRATION = "a4_top_at_y_min_v1"
SHEET_SIZES = {"A2": (594.0, 420.0), "A1": (841.0, 594.0)}


@dataclass(frozen=True)
class StitchConfig:
    work_width: float = 180.0
    work_height: float = 280.0
    work_min_y: float = -285.0
    overlap_mm: float = 5.0
    stroke_overlap_mm: float = 0.3
    mark_radius_mm: float = 1.2
    mark_clearance_mm: float = 0.8
    z_up: float = 0.0
    z_down: float = 11.9
    z_feed: float = 2500.0
    feed_draw: float = 2200.0
    feed_travel: float = 15000.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("Non-finite stitching configuration")
        if not 0 < self.stroke_overlap_mm < self.overlap_mm < min(self.work_width, self.work_height):
            raise ValueError("Require 0 < stroke overlap < field overlap < work field")
        if self.mark_radius_mm <= 0 or self.mark_clearance_mm <= 0:
            raise ValueError("Registration marks need a positive radius and clearance")
        if 2 * self.mark_radius_mm + 0.5 > self.overlap_mm:
            raise ValueError("Registration marks do not fit inside the overlap")
        if self.z_up >= self.z_down or min(self.z_feed, self.feed_draw, self.feed_travel) <= 0:
            raise ValueError("Invalid small-plotter pen positions or feeds")


@dataclass(frozen=True)
class Tile:
    number: int
    row: int
    column: int
    origin_mm: Point
    window_mm: Rect
    draw_rect_mm: Rect


def to_machine(point: Point, tile: Tile, config: StitchConfig) -> Point:
    return point[0] - tile.origin_mm[0], config.work_min_y + point[1] - tile.origin_mm[1]


def to_paper(point: Point, tile: Tile, config: StitchConfig) -> Point:
    return point[0] + tile.origin_mm[0], point[1] - config.work_min_y + tile.origin_mm[1]


def _clip_segment(a: Point, b: Point, rect: Rect) -> tuple[Point, Point] | None:
    dx, dy = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0] - rect[0]), (dx, rect[2] - a[0]),
                 (-dy, a[1] - rect[1]), (dy, rect[3] - a[1])):
        if abs(p) < 1e-12:
            if q < -1e-9:
                return None
            continue
        ratio = q / p
        if p < 0:
            low = max(low, ratio)
        else:
            high = min(high, ratio)
        if low > high:
            return None
    start = (a[0] + low * dx, a[1] + low * dy)
    end = (a[0] + high * dx, a[1] + high * dy)
    return (start, end) if math.dist(start, end) > 1e-8 else None


def clip_paths(paths: Iterable[Polyline], rect: Rect) -> list[Polyline]:
    """Clip without connecting disjoint fragments or closing dashed gaps."""
    output: list[Polyline] = []
    for path in paths:
        current: Polyline = []
        for a, b in zip(path, path[1:]):
            segment = _clip_segment(a, b, rect)
            if segment is None:
                if len(current) > 1:
                    output.append(current)
                current = []
                continue
            start, end = segment
            if current and math.dist(current[-1], start) < 1e-8:
                current.append(end)
            else:
                if len(current) > 1:
                    output.append(current)
                current = [start, end]
        if len(current) > 1:
            output.append(current)
    return output


def plan_tiles(width: float, height: float, sheet_format: str,
               config: StitchConfig = StitchConfig()) -> tuple[list[Tile], tuple[int, int]]:
    name = sheet_format.upper()
    if name not in SHEET_SIZES:
        raise ValueError("This separate mode supports only A2/A1; use the existing A4/A3 pipeline")
    nominal = SHEET_SIZES[name]
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("Invalid source page dimensions")
    if max(abs(a - b) for a, b in zip(sorted((width, height)), sorted(nominal))) > 1.0:
        raise ValueError(f"Source dimensions {width:g} x {height:g} mm do not match {name}; no implicit scaling")
    step_x, step_y = config.work_width - config.overlap_mm, config.work_height - config.overlap_mm
    columns = max(1, math.ceil((width - config.work_width) / step_x) + 1)
    rows = max(1, math.ceil((height - config.work_height) / step_y) + 1)
    half = (config.overlap_mm - config.stroke_overlap_mm) / 2
    tiles = []
    for row in range(rows):
        order = range(columns) if row % 2 == 0 else reversed(range(columns))
        for column in order:
            x, y = column * step_x, row * step_y
            window = (x, y, min(width, x + config.work_width), min(height, y + config.work_height))
            owned = (x + (half if column else 0), y + (half if row else 0),
                     min(width, x + config.work_width - (half if column < columns - 1 else 0)),
                     min(height, y + config.work_height - (half if row < rows - 1 else 0)))
            tiles.append(Tile(len(tiles) + 1, row + 1, column + 1, (x, y), window, owned))
    return tiles, (columns, rows)


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
    return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)


def registration_marks(previous: Tile, following: Tile, source: list[Polyline],
                       config: StitchConfig) -> tuple[Point, Point]:
    a, b = previous.window_mm, following.window_mm
    shared = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    vertical = previous.column != following.column
    if abs(previous.row - following.row) + abs(previous.column - following.column) != 1:
        raise ValueError("Registration requires edge-adjacent passes")
    low, high = (shared[1], shared[3]) if vertical else (shared[0], shared[2])
    span = high - low
    radius = config.mark_radius_mm + config.mark_clearance_mm
    margin = max(radius + 0.1, min(12.0, span * 0.12))
    start, finish = low + margin, high - margin
    separation = max(20.0, min(80.0, span * 0.55))
    if finish - start < separation:
        raise ValueError("Shared strip is too short for two useful registration marks")
    center = (shared[0] + shared[2]) / 2 if vertical else (shared[1] + shared[3]) / 2
    # Limit collision checks to segments near this shared strip.
    nearby = [(p, q) for poly in source for p, q in zip(poly, poly[1:])
              if max(p[0], q[0]) >= shared[0] - radius and min(p[0], q[0]) <= shared[2] + radius
              and max(p[1], q[1]) >= shared[1] - radius and min(p[1], q[1]) <= shared[3] + radius]
    candidates = [start + i * 2 for i in range(math.floor((finish - start) / 2) + 1)]
    candidates.append(finish)
    clear = []
    for along in candidates:
        point = (center, along) if vertical else (along, center)
        if all(_point_segment_distance(point, p, q) > radius for p, q in nearby):
            clear.append(point)
    if not clear or math.dist(clear[0], clear[-1]) < separation:
        raise ValueError(f"No blank space for BOTH marks between passes {previous.number}/{following.number}; "
                         "choose another layout or reserve blank registration strips, not ink over the drawing")
    return clear[0], clear[-1]


def _cross(center: Point, radius: float) -> list[Polyline]:
    x, y = center
    return [[(x - radius, y), (x + radius, y)], [(x, y - radius), (x, y + radius)]]


def _write_nc(path: Path, paths: list[Polyline], park: Point, config: StitchConfig) -> dict:
    lines = ["; STITCH-ONLY: send_small_sheet_tiles.py; keep this session open between passes",
             "; No XY zero reset, no reflection, no automatic continuation",
             "G21", "G90", "G94", "G17", f"G0 Z{config.z_up:.4f} F{config.z_feed:.1f}", "G4 P0.06"]
    for poly in paths:
        for x, y in poly:
            if not (-1e-6 <= x <= config.work_width + 1e-6 and
                    config.work_min_y - 1e-6 <= y <= config.work_min_y + config.work_height + 1e-6):
                raise ValueError("Pen-down point outside the small plotter field")
        x, y = poly[0]
        lines += [f"G0 X{x:.3f} Y{y:.3f} F{config.feed_travel:.1f}",
                  f"G1 Z{config.z_down:.4f} F{config.z_feed:.1f}", "G4 P0.02"]
        lines.extend(f"G1 X{x:.3f} Y{y:.3f}" + (f" F{config.feed_draw:.1f}" if i == 0 else "")
                     for i, (x, y) in enumerate(poly[1:]))
        lines += [f"G0 Z{config.z_up:.4f} F{config.z_feed:.1f}", "G4 P0.02"]
    lines += [f"G0 Z{config.z_up:.4f} F{config.z_feed:.1f}",
              f"G0 X{park[0]:.3f} Y{park[1]:.3f} F{config.feed_travel:.1f}", "G4 P0.05",
              "; STOP: pen up, motors remain held; do not re-zero or move the carriage by hand"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return file_record(path)


def file_record(path: Path) -> dict:
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def prepare_stitched_job(source: Iterable[Polyline], width: float, height: float, sheet_format: str,
                         output: Path, *, config: StitchConfig = StitchConfig(),
                         trial_first_two: bool = False, tiles_override: list[Tile] | None = None,
                         registration_paths: list[Polyline] | None = None) -> dict:
    """Public pipeline hook: canonical mm paths in, independent registered job out."""
    paths = [[(float(x), float(y)) for x, y in poly] for poly in source]
    if not all(math.isfinite(v) for poly in paths for point in poly for v in point):
        raise ValueError("Non-finite source coordinates")
    paths = clip_paths(paths, (0, 0, width, height))
    if not paths:
        raise ValueError("Empty source geometry")
    all_tiles, grid = plan_tiles(width, height, sheet_format, config)
    source_grid_count = len(all_tiles)
    if tiles_override is not None:
        if trial_first_two or not tiles_override:
            raise ValueError("An explicit nonempty queue cannot be combined with the two-pass trial")
        original = {(tile.row, tile.column): tile for tile in all_tiles}
        seen = set()
        for number, tile in enumerate(tiles_override, 1):
            reference = original.get((tile.row, tile.column))
            if (tile.number != number or reference is None or (tile.row, tile.column) in seen
                    or tile.origin_mm != reference.origin_mm or tile.window_mm != reference.window_mm
                    or tile.draw_rect_mm != reference.draw_rect_mm):
                raise ValueError("Explicit queue must contain unique, sequentially numbered original grid windows")
            seen.add((tile.row, tile.column))
        all_tiles = list(tiles_override)
    tiles = all_tiles[:2] if trial_first_two else all_tiles
    # Resolve every alignment before writing any executable output.
    transitions = []
    for previous, following in zip(tiles, tiles[1:]):
        marks = registration_marks(previous, following,
                                   paths if registration_paths is None else registration_paths, config)
        transitions.append({"from_pass": previous.number, "to_pass": following.number,
                            "marks_paper_mm": marks,
                            "previous_machine_mm": [to_machine(p, previous, config) for p in marks],
                            "next_machine_mm": [to_machine(p, following, config) for p in marks]})
    output.mkdir(parents=True, exist_ok=True)
    initialize = output / "initialize.nc"
    # The established small-plotter reference procedure, exactly ONCE per job.
    initialize.write_text("\n".join(["; ONCE per session; pen must have clearance for the usual 4 mm lift",
                                     "$1=255", "G21", "G90", "G94", "G92 Z4.0000", "G0 Z0.0000 F800.0",
                                     "G4 P0.06", "G92 Z0.0000", f"G0 Z{config.z_up:.4f} F{config.z_feed:.1f}",
                                     "G4 P0.06"]) + "\n", encoding="ascii")
    records = []
    for index, tile in enumerate(tiles):
        ink = clip_paths(paths, tile.draw_rect_mm)
        if index < len(transitions):
            for center in transitions[index]["marks_paper_mm"]:
                ink.extend(_cross(center, config.mark_radius_mm))
            park = tuple(transitions[index]["next_machine_mm"][0])
        else:
            park = (0.0, 0.0)
        machine_paths = [[to_machine(p, tile, config) for p in poly] for poly in ink]
        record = {**asdict(tile), **_write_nc(output / f"pass_{tile.number:02d}.nc", machine_paths, park, config),
                  "end_park_mm": park, "pen_down_paths": len(machine_paths)}
        records.append(record)
    for transition in transitions:
        number = transition["to_pass"]
        primary, secondary = transition["next_machine_mm"]
        transition["check_secondary"] = _write_nc(output / f"align_{number:02d}_B.nc", [], tuple(secondary), config)
        transition["return_primary"] = _write_nc(output / f"align_{number:02d}_A.nc", [], tuple(primary), config)
    job = {"schema": SCHEMA, "machine_profile": "a4_desktop", "paper_registration": PAPER_REGISTRATION,
           "sheet_format": sheet_format.upper(), "sheet_size_mm": [width, height], "scale": 1.0,
           "config": asdict(config), "grid_columns_rows": grid, "full_pass_count": len(all_tiles),
           "source_grid_pass_count": source_grid_count,
           "empty_grid_slots_skipped": source_grid_count - len(all_tiles),
           "trial_first_two": trial_first_two, "initialize": file_record(initialize),
           "tiles": records, "transitions": transitions}
    (output / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="ascii")
    return job
