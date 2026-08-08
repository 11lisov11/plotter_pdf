from __future__ import annotations

from src import plotter_pdf_drawer as backend


def test_stitch_roundtrip_rectangle_sides_does_not_create_diagonal() -> None:
    sides = [
        [(0.0, 0.0), (100.0, 0.0), (0.0, 0.0)],
        [(100.0, 0.0), (100.0, 50.0), (100.0, 0.0)],
        [(100.0, 50.0), (0.0, 50.0), (100.0, 50.0)],
        [(0.0, 50.0), (0.0, 0.0), (0.0, 50.0)],
    ]

    stitched = backend.stitch_polylines(sides, 0.08, logger=None)
    segments = [(start, end) for polyline in stitched for start, end in zip(polyline, polyline[1:])]

    assert segments
    assert all(start[0] == end[0] or start[1] == end[1] for start, end in segments)
