from collections import Counter
import random

from src.plotter_backend.geometry.stroke_routing import continuous_trails, optimize_pen_paths, route_metrics


def edges(paths):
    return Counter(tuple(sorted((a, b))) for p in paths for a, b in zip(p, p[1:]) if a != b)


def test_exact_graph_and_disconnected_components():
    paths = [[(0., 0.), (1., 0.)], [(1., 0.), (2., 0.)],
             [(1., 0.), (1., 1.)], [(5., 0.), (6., 0.)]]
    result = continuous_trails(paths)
    assert edges(result) == edges(paths)
    assert len(result) == 3


def test_no_connector_across_small_white_gap():
    paths = [[(0., 0.), (1., 0.)], [(1.001, 0.), (2., 0.)]]
    assert edges(continuous_trails(paths)) == edges(paths)
    assert len(continuous_trails(paths)) == 2


def test_closed_loop_and_zero_length():
    paths = [[(0., 0.), (1., 0.), (1., 1.), (0., 0.)], [(9., 9.), (9., 9.)]]
    result = continuous_trails(paths)
    assert edges(result) == edges(paths)
    assert len(result) == 1 and result[0][0] == result[0][-1]


def test_random_graphs_and_cost_guard():
    rng = random.Random(834)
    for _ in range(150):
        paths = [[(float(rng.randrange(8)), float(rng.randrange(8))),
                  (float(rng.randrange(8)), float(rng.randrange(8)))] for _ in range(35)]
        assert edges(continuous_trails(paths)) == edges(paths)
        result = optimize_pen_paths(paths)
        assert edges(result) == edges(paths)
        assert route_metrics(result)['nominal_non_drawing_seconds'] <= route_metrics(paths)['nominal_non_drawing_seconds'] + 1e-8


def test_empty():
    assert continuous_trails([]) == []
    assert optimize_pen_paths([]) == []
