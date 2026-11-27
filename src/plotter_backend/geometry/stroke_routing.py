"""Exact pen-down trail routing; never adds a connector or repeats an edge."""
from collections import defaultdict


def continuous_trails(polylines, precision=3):
    """Euler-decompose each endpoint-connected component into minimal trails.

    Coordinates are quantized to the output precision, not a fuzzy joining
    radius. Virtual edges to odd-degree vertices are removed before export.
    Consequently separate letters/gaps cannot acquire new ink connections.
    """
    adjacency = defaultdict(list)
    edges = []
    for poly in polylines:
        for a, b in zip(poly, poly[1:]):
            a = tuple(round(float(v), precision) for v in a)
            b = tuple(round(float(v), precision) for v in b)
            if a == b:
                continue
            i = len(edges)
            edges.append((a, b))
            adjacency[a].append((b, i))
            adjacency[b].append((a, i))
    unseen = set(adjacency)
    output = []
    used = set()
    for start in sorted(adjacency):
        if start not in unseen:
            continue
        component = {start}
        pending = [start]
        while pending:
            vertex = pending.pop()
            for other, _ in adjacency[vertex]:
                if other not in component:
                    component.add(other)
                    pending.append(other)
        unseen.difference_update(component)
        odd = sorted(v for v in component if len(adjacency[v]) % 2)
        # None is a temporary hub, never a drawing coordinate.
        if odd:
            adjacency[None] = []
            for vertex in odd:
                i = len(edges)
                edges.append((None, vertex))
                adjacency[None].append((vertex, i))
                adjacency[vertex].append((None, i))
            start = None
        stack = [start]
        circuit = []
        while stack:
            vertex = stack[-1]
            while adjacency[vertex] and adjacency[vertex][-1][1] in used:
                adjacency[vertex].pop()
            if not adjacency[vertex]:
                circuit.append(stack.pop())
            else:
                other, edge = adjacency[vertex].pop()
                if edge not in used:
                    used.add(edge)
                    stack.append(other)
        trail = []
        for vertex in reversed(circuit):
            if vertex is None:
                if len(trail) > 1:
                    output.append(trail)
                trail = []
            else:
                trail.append(vertex)
        if len(trail) > 1:
            output.append(trail)
    return output


def nearest_trails(paths, start=(0.0, 0.0)):
    """Nearest endpoint routing without the quadratic Python nested loop."""
    import numpy as np
    paths = [list(p) for p in paths if len(p) > 1]
    if not paths:
        return []
    ends = np.asarray([[p[0], p[-1]] for p in paths], dtype=float)
    available = np.ones(len(paths), dtype=bool)
    ordered = []
    position = start
    for _ in paths:
        delta = ends - position
        distance = np.sum(delta * delta, axis=2)
        distance[~available] = np.inf
        index, reverse = divmod(int(np.argmin(distance)), 2)
        poly = paths[index][::-1] if reverse else paths[index]
        ordered.append(poly)
        available[index] = False
        position = poly[-1]
    return ordered


def route_metrics(paths, *, home=(0.0, 0.0), park=None, z_up=0.0,
                  z_down=11.9, z_feed=2500.0, feed_travel=15000.0):
    import math
    position = home
    travel = 0.0
    count = 0
    for poly in paths:
        if len(poly) < 2:
            continue
        travel += math.dist(position, poly[0])
        position = poly[-1]
        count += 1
    travel += math.dist(position, park if park is not None else home)
    overhead = travel * 60 / feed_travel + count * (2 * abs(z_down - z_up) * 60 / z_feed + .04)
    return {'pen_down_paths': count, 'pen_up_travel_mm': travel,
            'nominal_non_drawing_seconds': overhead}


def optimize_pen_paths(paths, *, precision=3, home=(0.0, 0.0), park=None,
                       z_up=0.0, z_down=11.9, z_feed=2500.0, feed_travel=15000.0):
    """Use the exact trail route only if its estimated lift/travel cost improves."""
    source = [list(p) for p in paths if len(p) > 1]
    candidate = nearest_trails(continuous_trails(source, precision), start=home)
    options = dict(home=home, park=park, z_up=z_up, z_down=z_down,
                   z_feed=z_feed, feed_travel=feed_travel)
    old = route_metrics(source, **options)
    new = route_metrics(candidate, **options)
    return candidate if new['nominal_non_drawing_seconds'] <= old['nominal_non_drawing_seconds'] else source
