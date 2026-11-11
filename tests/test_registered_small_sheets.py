from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

import fitz
import pytest

from scripts import prepare_small_sheet_tiles as preview
from scripts import send_small_sheet_tiles as sender
from scripts.stitch_gcode_polylines import read_draw_polylines
from src.plotter_backend.geometry.pdf_stroke_paths import native_pdf_strokes
from src.plotter_backend.geometry.sheet_title_block import _registration_for_stamp
from src.plotter_backend.geometry.small_sheet_tiling import (
    StitchConfig, Tile, clip_paths, plan_tiles, prepare_stitched_job, to_machine, to_paper,
)

ROOT = Path(__file__).resolve().parents[1]


def _black_segments(page):
    return [item for drawing in page.get_drawings() if drawing.get("color") == (0.0, 0.0, 0.0)
            for item in drawing["items"]]


def test_open_nc_preview_does_not_add_a_closing_segment():
    with fitz.open() as document:
        page = document.new_page(width=200, height=200)
        preview._ink(page, [[(1, 1), (10, 1), (10, 10)]])
        # PyMuPDF can report closePath=False even when 'h' was expanded into
        # an extra line. Inspect the REAL segments, not that metadata flag.
        segments = _black_segments(page)
        assert len(segments) == 2
        assert all(item[0] == "l" for item in segments)


def test_hybrid_preview_does_not_add_a_closing_segment():
    from scripts.prepare_lab_hybrid_a4 import add_paths
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        add_paths(page, [[(1, -280), (10, -280), (10, -270)]])
        assert len(_black_segments(page)) == 2


def test_clipped_grid_guides_never_become_diagonals():
    with fitz.open() as document:
        page = document.new_page(width=200, height=200)
        preview._guide_rectangle(page, (0, 0, 20, 20), (2, 2), (15, 15, 25, 25))
        segments = [item for drawing in page.get_drawings() for item in drawing["items"]]
        assert segments
        assert all(item[0] == "l" and (abs(item[1].x - item[2].x) < 0.001
                                       or abs(item[1].y - item[2].y) < 0.001) for item in segments)


@pytest.mark.parametrize("sheet,width,height,count", [("A2", 594, 420, 8), ("A1", 841, 594, 15)])
def test_full_sheet_planning_and_unmirrored_mapping(sheet, width, height, count):
    config = StitchConfig()
    tiles, _ = plan_tiles(width, height, sheet, config)
    assert len(tiles) == count
    for a, b in zip(tiles, tiles[1:]):
        assert abs(a.row - b.row) + abs(a.column - b.column) == 1
    for tile in tiles:
        for point in (tile.window_mm[:2], tile.window_mm[2:]):
            machine = to_machine(point, tile, config)
            assert to_paper(machine, tile, config) == pytest.approx(point)
        assert to_machine(tile.origin_mm, tile, config) == (0, -285)


@pytest.mark.parametrize("sheet", ["A4", "A3"])
def test_registered_mode_does_not_replace_existing_a4_a3(sheet):
    with pytest.raises(ValueError, match="existing A4/A3"):
        plan_tiles(420, 297, sheet)


def test_clipping_does_not_join_across_an_outside_gap():
    paths = [[(-1, 2), (5, 2), (5, 5), (-1, 5)]]
    assert clip_paths(paths, (0, 0, 4, 6)) == [[(0, 2), (4, 2)], [(4, 5), (0, 5)]]


def test_stamp_marks_avoid_even_empty_table_cells():
    config = StitchConfig(mark_radius_mm=0.75, mark_clearance_mm=0.35)
    previous = Tile(6, 2, 4, (525, 275), (525, 275, 705, 555), (527.35, 277.35, 702.65, 552.65))
    stamp = Tile(7, 0, 0, (655.956, 314.078), (655.956, 314.078, 835.956, 594.078),
                 (655.956, 535.576, 835.956, 589.082))
    marks = _registration_for_stamp(previous, stamp, [], config)
    clearance = config.mark_radius_mm + config.mark_clearance_mm
    x0, y0, x1, y1 = stamp.draw_rect_mm
    assert math.dist(*marks) >= 20
    for x, y in marks:
        assert not (x0 - clearance <= x <= x1 + clearance and y0 - clearance <= y <= y1 + clearance)
        assert 525 <= x <= 705 and 314.078 <= y <= 555


def test_stamp_marks_fail_instead_of_using_a_fully_reserved_field():
    previous = Tile(1, 1, 1, (0, 0), (0, 0, 180, 280), (0, 0, 180, 280))
    stamp = Tile(2, 0, 0, (0, 0), (0, 0, 180, 280), (0, 0, 180, 280))
    with pytest.raises(ValueError, match="No clear pair"):
        _registration_for_stamp(previous, stamp, [], StitchConfig())


@pytest.fixture
def trial_job(tmp_path):
    return tmp_path, prepare_stitched_job([[(20, 20), (330, 20), (330, 60)]], 594, 420, "A2", tmp_path,
                                          trial_first_two=True)


def test_pdf_black_segments_match_the_serialized_nc(trial_job):
    folder, job = trial_job
    pdf = preview.preview_from_gcode(folder, job)
    expected = [sum(len(poly) - 1 for poly in read_draw_polylines(folder / tile["file"], z_up=0, z_down=11.9))
                for tile in job["tiles"]]
    with fitz.open(pdf) as document:
        assert len(document) == 3
        assert len(_black_segments(document[0])) == sum(expected)
        for index, count in enumerate(expected, 1):
            assert len(_black_segments(document[index])) == count


def test_native_pdf_retains_curves(tmp_path):
    path = tmp_path / "curves.pdf"
    with fitz.open() as document:
        page = document.new_page(width=600, height=400)
        page.draw_oval(fitz.Rect(40, 30, 550, 350))
        document.save(path)
    paths = native_pdf_strokes(path)
    points = [point for poly in paths for point in poly]
    assert len(points) > 40
    assert min(x for x, _ in points) == pytest.approx(40 * 25.4 / 72, abs=0.02)
    assert max(x for x, _ in points) == pytest.approx(550 * 25.4 / 72, abs=0.02)


def test_native_pdf_preserves_dash_gaps(tmp_path):
    path = tmp_path / "dashes.pdf"
    with fitz.open() as document:
        page = document.new_page(width=200, height=100)
        page.draw_line((0, 50), (200, 50), dashes="[10 10] 0")
        document.save(path)
    paths = native_pdf_strokes(path)
    assert len(paths) == 10
    assert sum(math.dist(a, b) for poly in paths for a, b in zip(poly, poly[1:])) == pytest.approx(100 * 25.4 / 72)


class FakeWire:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, value):
        self.writes.append(value)

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *, wrong_board=False, busy=False, fail_initialize=False):
        self.serial = FakeWire()
        self.wrong_board = wrong_board
        self.busy = busy
        self.fail_initialize = fail_initialize
        self.commands = []

    def command(self, line):
        self.commands.append(line)
        if line == "$I":
            return ["OTHER_BOARD" if self.wrong_board else sender.EXPECTED_BOARD]
        if line == "$$":
            return ["$1=0"]
        return []

    def idle(self, **kwargs):
        if self.busy:
            assert kwargs.get("require_idle") is True
            raise RuntimeError("Controller is busy")
        return {"wco": (0, 0, 0), "position": (0, 0, 0)}

    def send_file(self, path):
        if self.fail_initialize:
            raise RuntimeError("Initialization failed after motion ownership")


def _mock_sender(monkeypatch, folder, session, response="START"):
    monkeypatch.setattr(sender, "Session", lambda *args: session)
    monkeypatch.setattr("builtins.input", lambda *args: response)
    monkeypatch.setattr(sys, "argv", ["sender", str(folder / "job.json"), "--port", "FAKE"])
    monkeypatch.setattr(sender.time, "sleep", lambda *args: None)


def test_rejected_board_never_receives_hold_or_reset(monkeypatch, trial_job):
    folder, _ = trial_job
    session = FakeSession(wrong_board=True)
    _mock_sender(monkeypatch, folder, session)
    with pytest.raises(RuntimeError, match="known SMALL"):
        sender.main()
    assert session.commands == ["$I"]
    assert session.serial.writes == []
    assert session.serial.closed


def test_initially_busy_controller_is_not_interrupted(monkeypatch, trial_job):
    folder, _ = trial_job
    session = FakeSession(busy=True)
    _mock_sender(monkeypatch, folder, session)
    with pytest.raises(RuntimeError, match="busy"):
        sender.main()
    assert session.commands == ["$I"]
    assert session.serial.writes == []
    assert session.serial.closed


def test_own_failed_initialization_does_clear_its_queue(monkeypatch, trial_job):
    folder, _ = trial_job
    session = FakeSession(fail_initialize=True)
    _mock_sender(monkeypatch, folder, session)
    with pytest.raises(RuntimeError, match="Initialization failed"):
        sender.main()
    assert session.serial.writes == [b"!", b"\x18"]
    assert session.serial.closed


def test_disconnect_during_abort_still_closes_port(monkeypatch, trial_job):
    folder, _ = trial_job
    session = FakeSession(fail_initialize=True)
    _mock_sender(monkeypatch, folder, session)

    def disconnected(value):
        raise OSError("Cable disconnected")

    monkeypatch.setattr(session.serial, "write", disconnected)
    with pytest.raises(RuntimeError, match="Initialization failed"):
        sender.main()
    assert session.serial.closed


def test_initial_busy_status_guard_does_not_send_motion():
    session = sender.Session.__new__(sender.Session)
    session.serial = FakeWire()
    session.wco = None
    session.line = lambda: "<Run|MPos:10,20,0|WCO:0,0,0>"
    with pytest.raises(RuntimeError, match="existing motion was not interrupted"):
        session.idle(timeout=1, require_idle=True)
    assert session.serial.writes == [b"?"]


def _audit_nc(path, config):
    position = None
    up = False
    absolute = False
    millimeters = False
    for raw in path.read_text(encoding="ascii").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line == "G21":
            millimeters = True
        if line == "G90":
            absolute = True
        assert not line.startswith(("G20", "G91", "$X", "$H", "M"))
        if line.startswith(("G0 ", "G1 ")):
            words = {key: float(value) for key, value in re.findall(r"([XYZ])(-?\d+(?:\.\d+)?)", line)}
            if "Z" in words:
                assert words["Z"] in (config["z_up"], config["z_down"])
                up = words["Z"] == config["z_up"]
            if "X" in words or "Y" in words:
                assert absolute and millimeters
                assert "X" in words and "Y" in words
                x, y = position = (words["X"], words["Y"])
                assert -0.001 <= x <= 180.001
                assert -285.001 <= y <= (0.001 if up else -4.999)
                assert (line.startswith("G0 ") and up) or (line.startswith("G1 ") and not up)
    assert up
    return position


@pytest.mark.parametrize("name", ["Small_stitch_trial", "VB-6_A1_small_stitch", "VB-6_A2_small_stitch"])
def test_published_jobs_have_safe_nc_consistent_registration_and_single_stamp(name):
    folder = ROOT / "_plotter_jobs" / name
    job = json.loads((folder / "job.json").read_text(encoding="ascii"))
    tiles = job["tiles"]
    assert [tile["number"] for tile in tiles] == list(range(1, len(tiles) + 1))
    assert len(job["transitions"]) == len(tiles) - 1
    records = [job["initialize"], *tiles]
    for transition in job["transitions"]:
        records += [transition["check_secondary"], transition["return_primary"]]
    for record in records:
        path = folder / record["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    config = StitchConfig(**job["config"])
    expected_segments = []
    for tile in tiles:
        assert _audit_nc(folder / tile["file"], job["config"]) == pytest.approx(tile["end_park_mm"], abs=0.001)
        paths = read_draw_polylines(folder / tile["file"], z_up=0, z_down=11.9)
        expected_segments.append(sum(len(poly) - 1 for poly in paths))
        if tile.get("role") != "title_block" and not job["trial_first_two"]:
            assert len(paths) > 4  # Not a blank pass containing only registration crosses.
    for index, transition in enumerate(job["transitions"]):
        assert (transition["from_pass"], transition["to_pass"]) == (index + 1, index + 2)
        assert math.dist(*transition["marks_paper_mm"]) >= 20
        for tile_record, key in ((tiles[index], "previous_machine_mm"), (tiles[index + 1], "next_machine_mm")):
            tile = Tile(**{key: tile_record[key] for key in ("number", "row", "column", "origin_mm", "window_mm", "draw_rect_mm")})
            for paper, machine in zip(transition["marks_paper_mm"], transition[key]):
                assert to_machine(paper, tile, config) == pytest.approx(machine, abs=0.001)
                assert -0.001 <= machine[0] <= 180.001 and -285.001 <= machine[1] <= -4.999
        for key, target in (("check_secondary", transition["next_machine_mm"][1]),
                            ("return_primary", transition["next_machine_mm"][0])):
            path = folder / transition[key]["file"]
            assert _audit_nc(path, job["config"]) == pytest.approx(target, abs=0.001)
            assert read_draw_polylines(path, z_up=0, z_down=11.9) == []
    if job.get("title_block"):
        assert len(tiles) == 7
        assert tiles[-1]["role"] == "title_block" and job["title_block"]["pass_number"] == 7
        x0, y0, x1, y1 = job["title_block"]["target_bbox_mm"]
        assert x1 - x0 == pytest.approx(180)
        clearance = config.mark_radius_mm + config.mark_clearance_mm
        for transition in job["transitions"]:
            for x, y in transition["marks_paper_mm"]:
                assert not (x0 - clearance <= x <= x1 + clearance and y0 - clearance <= y <= y1 + clearance)
        expected = {record["file"] for record in records}
        actual = {path.name for path in folder.glob("*.nc")}
        assert actual == expected
    with fitz.open(folder / "Preview_from_Gcode.pdf") as document:
        assert len(document) == len(tiles) + 1
        # PDF extraction can combine four straight rectangle sides into a
        # single 're'/'qu' item. Count the actual sides, not item records.
        counts = [sum(4 if item[0] in ("re", "qu") else 1 for item in _black_segments(page))
                  for page in document]
        assert counts[0] == sum(expected_segments)
        assert counts[1:] == expected_segments
    if job.get("title_block"):
        with fitz.open(folder / "Title_block_from_Gcode.pdf") as document:
            assert len(document) == 1
            count = sum(4 if item[0] in ("re", "qu") else 1 for item in _black_segments(document[0]))
            assert count == expected_segments[-1]
