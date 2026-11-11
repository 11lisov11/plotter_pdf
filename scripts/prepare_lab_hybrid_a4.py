"""Separate an existing laboratory Word reference into printer and pen layers.

Never communicates with hardware. The printer layer preserves source OOXML;
the plotter layer uses the shared single-line skeleton and small-machine writer.
All final previews are reconstructed from serialized NC, not source pictures.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import cv2
import fitz
import numpy as np
from lxml import etree as ET
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prepare_plotter_ready_new_algorithm as pipeline
from src import plotter_pdf_drawer as backend

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
MM = 72 / 25.4
SETTINGS = pipeline.settings_for_machine_profile('a4_desktop', drawing_mode='descriptive_geometry')
A4_FIELD_LEFT_MM = 15.0
A4_FIELD_TOP_MM = 8.5
PAPER_REGISTRATION = 'a4_top_at_y_min_v1'


def _paper_to_machine(x, y):
    # Physical portrait setup: the printed top is at the far, minimum-Y
    # edge of the calibrated field. Input y increases down the paper.
    return x-A4_FIELD_LEFT_MM, SETTINGS.work_min_y+y-A4_FIELD_TOP_MM


def _machine_to_paper(x, y):
    return x+A4_FIELD_LEFT_MM, y-SETTINGS.work_min_y+A4_FIELD_TOP_MM

# The bounds deliberately exclude blue legends and duplicated printed captions.
# Coordinates refer to the original embedded-image canvas, not a recropped page.
FIGURES = [
    (1, 1, 2, (30, 22, 255, 259), 'Схема дизель-генераторной установки'),
    (2, 1, 3, (5, 2, 471, 220), 'Топливная система низкого давления'),
    (3, 1, 3, (8, 8, 145, 225), 'Топливный насос высокого давления'),
    (4, 1, 4, (3, 2, 432, 332), 'Масляная система'),
    (5, 1, 5, (2, 2, 420, 270), 'Водяная система'),
    (6, 1, 6, (3, 2, 420, 327), 'Газотурбинный наддув'),
    (7, 2, 7, (20, 2, 358, 194), 'Генератор постоянного тока'),
    (8, 2, 9, (2, 2, 364, 205), 'Тяговый электродвигатель постоянного тока'),
    (9, 2, 10, (2, 2, 388, 215), 'Тяговый электродвигатель переменного тока'),
    (10, 3, 11, (20, 2, 381, 141), 'Главная рама тепловоза'),
    (11, 3, 11, (35, 7, 340, 113), 'Кузов капотного типа'),
    (12, 3, 1, (3, 13, 420, 195), 'Кузов закрытого типа'),
    (13, 3, 1, (2, 2, 304, 157), 'Тележка тепловоза'),
]


def safe_output(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError(f'Output must be below workspace: {path}')
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def write_package(parts: dict[str, bytes], path: Path) -> None:
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)


def serialize(root) -> bytes:
    return ET.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)


def extra_paragraph(text: str = '', page_break: bool = False):
    p = ET.Element(f'{{{W}}}p')
    pr = ET.SubElement(p, f'{{{W}}}pPr')
    if page_break:
        ET.SubElement(pr, f'{{{W}}}pageBreakBefore')
    ET.SubElement(pr, f'{{{W}}}spacing', {f'{{{W}}}after': '180'})
    r = ET.SubElement(p, f'{{{W}}}r')
    rp = ET.SubElement(r, f'{{{W}}}rPr')
    ET.SubElement(rp, f'{{{W}}}rFonts', {f'{{{W}}}ascii': 'Times New Roman', f'{{{W}}}hAnsi': 'Times New Roman'})
    ET.SubElement(rp, f'{{{W}}}b')
    ET.SubElement(rp, f'{{{W}}}sz', {f'{{{W}}}val': '28'})
    ET.SubElement(r, f'{{{W}}}t').text = text
    return p


def append_extra(body) -> None:
    section = body.find(f'{{{W}}}sectPr')
    pos = list(body).index(section) if section is not None else len(body)
    body.insert(pos, extra_paragraph('Лабораторная работа №2', page_break=True))
    body.insert(pos + 1, extra_paragraph('Конструкция синхронного генератора переменного тока'))
    body.insert(pos + 2, extra_paragraph('Основные узлы'))


def prepare_documents(parts, output: Path, include_extra: bool):
    cleaned = dict(parts)
    for i in range(1, 14):
        name = f'word/media/image{i}.png'
        original = Image.open(io.BytesIO(parts[name]))
        buff = io.BytesIO()
        Image.new('RGB', original.size, 'white').save(buff, format='PNG')
        cleaned[name] = buff.getvalue()
    master_root = ET.fromstring(cleaned['word/document.xml'])
    if include_extra:
        append_extra(master_root.find(f'{{{W}}}body'))
    master_parts = dict(cleaned)
    master_parts['word/document.xml'] = serialize(master_root)
    master_path = output / 'Печатный шаблон ЛР 1-5.docx'
    write_package(master_parts, master_path)

    source_root = ET.fromstring(cleaned['word/document.xml'])
    source_body = source_root.find(f'{{{W}}}body')
    children = list(source_body)
    starts = []
    for idx, child in enumerate(children):
        text = ''.join(child.xpath('.//w:t/text()', namespaces=NS))
        if text.strip().startswith('Лабораторная работа №'):
            starts.append(idx)
    if len(starts) != 5:
        raise ValueError(f'Expected five laboratory headings, found {starts}')
    end = next(i for i, el in enumerate(children) if el.tag == f'{{{W}}}sectPr')
    lab_dir = output / 'Word по работам'
    lab_dir.mkdir(exist_ok=True)
    for lab, start in enumerate(starts, 1):
        stop = starts[lab] if lab < 5 else end
        selected = copy.deepcopy(children[start:stop])
        while selected and not selected[-1].xpath('.//w:t | .//w:drawing', namespaces=NS):
            selected.pop()
        # A heading at a new document's beginning must not retain a preceding
        # hard break. All other source paragraph geometry remains untouched.
        for br in selected[0].xpath('.//w:br[@w:type="page"]', namespaces=NS):
            br.getparent().remove(br)
        lab_root = copy.deepcopy(source_root)
        body = lab_root.find(f'{{{W}}}body')
        for child in list(body):
            body.remove(child)
        body.extend(selected)
        body.append(copy.deepcopy(children[end]))
        if lab == 2 and include_extra:
            append_extra(body)
        lab_parts = dict(cleaned)
        lab_parts['word/document.xml'] = serialize(lab_root)
        write_package(lab_parts, lab_dir / f'Лабораторная работа {lab}.docx')
    return master_path


class PhotoRegistration:
    def __init__(self, reference: Path):
        self.reference = reference
        self.sift = cv2.SIFT_create(nfeatures=6500, contrastThreshold=.012)
        self.cache = {}

    def align(self, embedded: Image.Image, photo_number: int):
        if photo_number not in self.cache:
            rgb = np.asarray(Image.open(self.reference / f'{photo_number}.jpg').convert('RGB'))
            small = cv2.resize(rgb, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
            kp, des = self.sift.detectAndCompute(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), None)
            self.cache[photo_number] = (rgb, kp, des)
        rgb, source_kp, source_des = self.cache[photo_number]
        target = cv2.resize(np.asarray(embedded.convert('RGB')), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        target_kp, target_des = self.sift.detectAndCompute(cv2.cvtColor(target, cv2.COLOR_RGB2GRAY), None)
        matches = cv2.BFMatcher().knnMatch(target_des, source_des, k=2)
        good = [m for m, n in matches if m.distance < .72 * n.distance]
        if len(good) < 12:
            raise ValueError(f'Cannot register photograph {photo_number}: {len(good)} matches')
        src = np.float32([source_kp[m.trainIdx].pt for m in good])
        dst = np.float32([target_kp[m.queryIdx].pt for m in good])
        h, valid = cv2.findHomography(src, dst, cv2.RANSAC, 2.8)
        if h is None or int(valid.sum()) < 10:
            raise ValueError(f'Unreliable photograph registration: {photo_number}')
        transform = np.diag([4 / 3, 4 / 3, 1]) @ h @ np.diag([.5, .5, 1])
        aligned = cv2.warpPerspective(rgb, transform, (embedded.width * 4, embedded.height * 4), borderValue=(255, 255, 255))
        error = cv2.perspectiveTransform(src.reshape(-1, 1, 2), h).reshape(-1, 2) - dst
        residual = float(np.median(np.linalg.norm(error[valid.ravel().astype(bool)], axis=1))) / 3
        print(f'REGISTRATION photo={photo_number} inliers={int(valid.sum())} residual={residual:.3f}px', flush=True)
        if residual > .8:
            raise ValueError('Image registration error exceeds embedded-image pixel budget')
        return aligned


def pencil_mask(rgb: np.ndarray, roi, figure_id: int) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    values = rgb.astype(np.int16)
    # Correct for warm paper before classifying ink. Raw B > R fails on
    # photographed yellow sheets: blue handwriting can still have B < R.
    paper_rgb = cv2.morphologyEx(rgb, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 45))).astype(np.float32)
    relative = rgb.astype(np.float32) / np.maximum(paper_rgb, 1)
    chromatic_blue = relative[:, :, 2] - np.minimum(relative[:, :, 0], relative[:, :, 1]) > .035
    blue = (((hsv[:, :, 0] >= 90) & (hsv[:, :, 0] <= 175) & (hsv[:, :, 1] >= 30)) |
            ((values[:, :, 2] - values[:, :, 1] > 6) & (values[:, :, 2] - values[:, :, 0] > -2)) |
            chromatic_blue)
    blue = cv2.dilate(blue.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    fine = figure_id in {3, 9}
    gray = cv2.bilateralFilter(gray, 5 if fine else 7, 14 if fine else 22, 2 if fine else 3)
    if not fine:
        gray = cv2.GaussianBlur(gray, (3, 3), .65)
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (35, 35)))
    darkness = background.astype(np.int16) - gray.astype(np.int16)
    ink = (darkness >= 12) & (~blue)
    if fine:
        local_paper = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        ink &= ((local_paper.astype(np.int16)-gray >= 5) | (darkness >= 30))
    allowed = np.zeros_like(gray)
    x0, y0, x1, y1 = [int(x * 4) for x in roi]
    allowed[y0:y1, x0:x1] = 1
    if figure_id == 1:
        allowed[20 * 4:33 * 4, 70 * 4:105 * 4] = 0
    if figure_id == 6:
        # This legend lies beside, not below, the lower turbine symbol.
        allowed[235 * 4:, 210 * 4:] = 0
    ink &= allowed.astype(bool)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    keep = np.zeros(count, dtype=bool)
    for i in range(1, count):
        keep[i] = stats[i, cv2.CC_STAT_AREA] >= 16 and max(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]) >= 8
    return keep[labels].astype(np.uint8) * 255


def nearest_paths(paths):
    if not paths:
        return []
    endpoints = np.array([[p[0], p[-1]] for p in paths], dtype=float)
    active = np.ones(len(paths), dtype=bool)
    ordered = []
    current = np.array([0., 0.])
    for _ in range(len(paths)):
        distances = np.sum((endpoints - current) ** 2, axis=2)
        distances[~active, :] = np.inf
        idx, reverse = np.unravel_index(np.argmin(distances), distances.shape)
        path = paths[idx] if reverse == 0 else list(reversed(paths[idx]))
        ordered.append(path)
        current = np.array(path[-1])
        active[idx] = False
    return ordered


def mask_paths(mask: np.ndarray, rect_mm, figure_id=0, *, technical=False):
    x0, y0, x1, y1 = rect_mm
    sx = (x1 - x0) / mask.shape[1]
    sy = (y1 - y0) / mask.shape[0]
    skel = backend._skeletonize_binary(mask if technical else _deskew_pencil(mask, sx, sy))
    fine = technical or figure_id in {3, 9}
    traces, skel = _pencil_graph_paths(skel, sx, sy, fine=fine, technical=technical)
    paper_paths = [[(x0 + (x + .5) * sx, y0 + (y + .5) * sy) for x, y in trace] for trace in traces]
    if technical:
        # Clean technical references include tiny printed digits. Treat their
        # original centerlines as authoritative: no circle/ellipse fitting,
        # endpoint snapping, cross-gap joining or glyph-shape inference.
        regular = paper_paths
    else:
        paper_paths = _join_pencil_fragments(paper_paths)
        regular = [_regularize_pencil_path(path, fine=fine) for path in paper_paths]
        regular = [path for path in regular if len(path) >= 2 and _path_length(path) >= (.22 if fine else .40)]
        regular = _join_pencil_fragments(regular)
        if figure_id == 10:
            regular = _square_rectilinear_frame(regular)
        regular = _snap_pencil_junctions(regular)
    regular = _neat_pen_paths(regular, technical=technical)
    paths = []
    for points in regular:
        path = [_paper_to_machine(float(x),float(y)) for x,y in points]
        for x, y in path:
            if not (-.001 <= x <= 180.001 and -285.001 <= y <= -4.999):
                raise ValueError(f'Pen point outside calibrated A4: {(x, y)}')
        paths.append(path)
    if not paths:
        raise ValueError('No pencil paths survived separation')
    # This reference checks serialization of the reconstructed geometry. It
    # must not be presented as a percentage of photographic recognition.
    target = np.zeros_like(skel)
    for points in regular:
        pixel = np.rint([[(x-x0)/sx-.5, (y-y0)/sy-.5] for x, y in points]).astype(np.int32)
        cv2.polylines(target, [pixel], False, 255, 1)
    print(f'GEOMETRY components={len(traces)} reconstructed_paths={len(paths)}', flush=True)
    return paths, target


def _path_length(path):
    return float(np.linalg.norm(np.diff(np.asarray(path, dtype=float), axis=0), axis=1).sum())


def _neat_pen_paths(paths, *, technical=False):
    """Neat single-pen drafting, without synthetic movement or overtracing.

    Technical-reference glyphs retain their source topology. Photo geometry
    has already been reconstructed above; neither kind is randomly warped.
    This operation is intentionally incapable of adding waves or new loops.
    """
    result = []
    seen = set()
    for path in paths:
        points = np.asarray(path, dtype=np.float32)
        if len(points) < 2:
            continue
        points = points[np.r_[True,np.linalg.norm(np.diff(points,axis=0),axis=1)>1e-7]]
        if len(points) < 2:
            continue
        closed = np.linalg.norm(points[0]-points[-1]) < 1e-6
        simplified = cv2.approxPolyDP(points.reshape(-1,1,2),.010 if technical else .025,closed).reshape(-1,2)
        if len(simplified) < (3 if closed else 2):
            simplified = points[:-1] if closed else points
        if closed:
            simplified = np.vstack((simplified,simplified[0]))
        if _path_length(simplified) < (.055 if technical else .22):
            continue
        signature = tuple(map(tuple,np.round(simplified,3)))
        key = min(signature,signature[::-1])
        if key in seen:
            continue
        seen.add(key)
        result.append(simplified.tolist())
    return result


def _deskew_pencil(mask, sx, sy):
    skeleton = backend._skeletonize_binary(mask)
    min_length = max(25, round(5 / max(sx, sy)))
    lines = cv2.HoughLinesP(skeleton.astype(np.uint8) * (255 if skeleton.max() <= 1 else 1),
                            1, np.pi / 1800, threshold=max(18, min_length // 2),
                            minLineLength=min_length, maxLineGap=max(2, round(.25 / max(sx, sy))))
    if lines is None:
        return mask
    candidates = []
    for x0, y0, x1, y1 in np.asarray(lines).reshape(-1, 4):
        angle = math.degrees(math.atan2((y1-y0)*sy, (x1-x0)*sx))
        angle = (angle + 90) % 180 - 90
        # Horizontal structural lines, not slanted leaders or hatch lines,
        # determine rotation. Do not shear an isometric construction.
        if abs(angle) <= 3:
            candidates.append((angle, math.hypot((x1-x0)*sx, (y1-y0)*sy)))
    if len(candidates) < 3:
        return mask
    candidates.sort()
    half = sum(weight for _, weight in candidates) / 2
    total = 0
    angle = 0
    for value, weight in candidates:
        total += weight
        if total >= half:
            angle = value
            break
    if abs(angle) < .08:
        return mask
    height, width = mask.shape
    transform = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    rotated = cv2.warpAffine(mask, transform, (width, height), flags=cv2.INTER_NEAREST, borderValue=0)
    # Never crop real strokes in an attempt to level a photograph.
    if np.count_nonzero(rotated) < np.count_nonzero(mask) * .99:
        return mask
    print(f'DESKEW {angle:.3f} degrees', flush=True)
    return rotated


def _pencil_graph_paths(skeleton, sx, sy, *, fine=False, technical=False):
    image = (skeleton > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(image, 8)
    extent = np.hypot(stats[:, cv2.CC_STAT_WIDTH]*sx, stats[:, cv2.CC_STAT_HEIGHT]*sy)
    keep = extent >= (.08 if technical else 1.15 if fine else 2.8)
    keep[0] = False
    # A small, isolated fragment is only retained if it is close enough to
    # a supported stroke to be part of the same construction. In particular,
    # do not outline the scattered specks in the empty area of a scan.
    distance = cv2.distanceTransform((~keep[labels]).astype(np.uint8), cv2.DIST_L2, 5)
    nearby = np.unique(labels[(distance <= (.30 if fine else .25)/max(sx, sy)) & (labels != 0)])
    keep[nearby] |= extent[nearby] >= (.42 if fine else .85)
    image = keep[labels]
    height, width = image.shape
    pixels = set(np.flatnonzero(image).tolist())
    adjacent = {}
    for point in pixels:
        y, x = divmod(point, width)
        neighbors = set()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dx or dy) or not (0 <= x+dx < width and 0 <= y+dy < height):
                    continue
                other = point + dy * width + dx
                if other not in pixels:
                    continue
                # Avoid diagonal triangles around a one-pixel stair step.
                # Those falsely turn smooth lines into hundreds of junctions.
                if dx and dy and (point + dx in pixels or point + dy * width in pixels):
                    continue
                neighbors.add(other)
        adjacent[point] = neighbors

    def step_length(a, b):
        ay, ax = divmod(a, width); by, bx = divmod(b, width)
        return math.hypot((ax-bx)*sx, (ay-by)*sy)

    # Remove only short terminal branches attached to a larger construction;
    # closed loops and ordinary corners are not noise spurs.
    spur_limit = 0.0 if technical else .22 if fine else .40
    for _ in range(3):
        remove = set()
        for start in list(adjacent):
            if len(adjacent[start]) != 1:
                continue
            chain = [start]; previous = None; current = start; length = 0.
            while True:
                next_points = adjacent[current] - ({previous} if previous is not None else set())
                if not next_points:
                    break
                other = next(iter(next_points)); length += step_length(current, other)
                previous, current = current, other
                chain.append(current)
                if len(adjacent[current]) != 2 or length >= spur_limit:
                    break
            if len(adjacent[current]) >= 3 and length < spur_limit:
                remove.update(chain[:-1])
        if not remove:
            break
        for point in remove:
            for other in adjacent[point]:
                adjacent[other].discard(point)
        for point in remove:
            del adjacent[point]
    visited = set()
    paths = []

    def edge(a, b):
        return (min(a, b), max(a, b))

    def follow(start, second):
        chain = [start, second]
        visited.add(edge(start, second))
        previous, current = start, second
        while len(adjacent[current]) == 2:
            other = next(iter(adjacent[current] - {previous}))
            if edge(current, other) in visited:
                break
            visited.add(edge(current, other)); chain.append(other)
            previous, current = current, other
            if current == start:
                break
        return [(p % width, p // width) for p in chain]

    for start, neighbors in adjacent.items():
        if len(neighbors) == 2:
            continue
        for other in neighbors:
            if edge(start, other) not in visited:
                paths.append(follow(start, other))
    for start, neighbors in adjacent.items():
        for other in neighbors:
            if edge(start, other) not in visited:
                paths.append(follow(start, other))
    cleaned = np.zeros_like(skeleton, dtype=np.uint8)
    for point in adjacent:
        cleaned[point // width, point % width] = 255
    return paths, cleaned


def _endpoint_tangent(path, end):
    points = np.asarray(path if end == 0 else list(reversed(path)), dtype=float)
    anchor = points[0]
    for other in points[1:]:
        vector = anchor - other
        length = np.linalg.norm(vector)
        if length >= .45:
            return vector / length
    vector = anchor - points[-1]
    return vector / max(1e-9, np.linalg.norm(vector))


def _join_pencil_fragments(paths, *, max_gap=.45):
    paths = [list(path) for path in paths if len(path) > 1]
    cell_size = max_gap
    for _ in range(6):
        buckets = defaultdict(list)
        candidates = []
        for idx, path in enumerate(paths):
            if np.linalg.norm(np.asarray(path[0])-path[-1]) < 1e-6:
                continue
            for end in (0, 1):
                xy = np.asarray(path[0 if end == 0 else -1], dtype=float)
                key = (math.floor(xy[0] / cell_size), math.floor(xy[1] / cell_size))
                tangent = _endpoint_tangent(path, end)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for other_idx, other_end, other_xy, other_tangent in buckets[(key[0]+dx, key[1]+dy)]:
                            if idx == other_idx:
                                continue
                            delta = other_xy - xy; distance = float(np.linalg.norm(delta))
                            if distance > max_gap or float(tangent @ other_tangent) > -math.cos(math.radians(24)):
                                continue
                            if distance > .10:
                                direction = delta / distance
                                if float(tangent @ direction) < .88 or float(other_tangent @ -direction) < .88:
                                    continue
                            candidates.append((distance, idx, end, other_idx, other_end))
                buckets[key].append((idx, end, xy, tangent))
        consumed = set(); additions = []
        for _, idx, end, other_idx, other_end in sorted(candidates):
            if idx in consumed or other_idx in consumed:
                continue
            a = paths[idx] if end == 1 else list(reversed(paths[idx]))
            b = paths[other_idx] if other_end == 0 else list(reversed(paths[other_idx]))
            if np.linalg.norm(np.asarray(a[-1])-b[0]) <= .10:
                joint = tuple((np.asarray(a[-1])+b[0])/2)
                a = a[:-1] + [joint]; b = b[1:]
            additions.append(a+b); consumed.update((idx, other_idx))
        if not consumed:
            break
        paths = [path for idx, path in enumerate(paths) if idx not in consumed] + additions
    return paths


def _regularize_pencil_path(path, *, fine=False):
    points = np.asarray(path, dtype=np.float32)
    if len(points) < 3:
        return points.tolist()
    length = _path_length(points)
    span = np.linalg.norm(points[-1]-points[0])
    closed = span < .10
    center = points.mean(axis=0)
    _, _, vh = np.linalg.svd(points-center, full_matrices=False)
    axis = vh[0]; normal = np.array([-axis[1], axis[0]])
    distances = np.abs((points-center) @ normal)
    if span > .5 and length < span*1.22 and np.quantile(distances, .95) <= .10 and distances.max() <= .22:
        ends = center + np.outer((points[[0, -1]]-center) @ axis, axis)
        dx, dy = ends[1]-ends[0]
        if abs(dy) <= .24 and abs(dy) <= abs(dx)*.05:
            ends[:, 1] = ends[:, 1].mean()
        elif abs(dx) <= .24 and abs(dx) <= abs(dy)*.05:
            ends[:, 0] = ends[:, 0].mean()
        return ends.tolist()
    if len(points) >= 12 and length > 2:
        # Recover circular arcs without forcing the many isometric ellipses
        # in the references to become circles.
        a = np.column_stack((2*points[:, 0], 2*points[:, 1], np.ones(len(points))))
        rhs = (points**2).sum(axis=1)
        solution = np.linalg.lstsq(a, rhs, rcond=None)[0]
        circle_center = solution[:2]
        radial = np.linalg.norm(points-circle_center, axis=1)
        radius = float(np.median(radial))
        error = np.abs(radial-radius)
        angles = np.unwrap(np.arctan2(points[:, 1]-circle_center[1], points[:, 0]-circle_center[0]))
        sweep = float(angles[-1]-angles[0])
        bbox_span = np.linalg.norm(np.ptp(points, axis=0))
        if .2 < radius < bbox_span*8 and .40 <= abs(sweep) <= math.tau*1.03 and np.quantile(error, .95) <= .09 and error.max() <= .20:
            samples = max(8, min(1000, math.ceil(abs(sweep)*radius/.16)))
            values = np.linspace(angles[0], angles[-1], samples)
            result = np.column_stack((circle_center[0]+radius*np.cos(values), circle_center[1]+radius*np.sin(values)))
            if span > .3:
                result[0] = points[0]; result[-1] = points[-1]
            return result.tolist()
        if span <= .35 and len(points) >= 20:
            ellipse = cv2.fitEllipse(points.reshape(-1, 1, 2))
            (cx, cy), (diam_a, diam_b), angle = ellipse
            aa, bb = diam_a/2, diam_b/2
            if min(aa, bb) > .2 and max(aa, bb) < bbox_span*2:
                radians = math.radians(angle)
                rot = np.array([[math.cos(radians), -math.sin(radians)], [math.sin(radians), math.cos(radians)]])
                local = (points-[cx, cy]) @ rot
                residual = np.abs(np.sqrt((local[:, 0]/aa)**2+(local[:, 1]/bb)**2)-1)*min(aa, bb)
                if np.quantile(residual, .95) < .10 and residual.max() < .22:
                    values = np.linspace(0, math.tau, max(40, math.ceil(math.pi*(aa+bb)/.16)))
                    return (np.column_stack((aa*np.cos(values), bb*np.sin(values))) @ rot.T + [cx, cy]).tolist()
    simplified = cv2.approxPolyDP(points.reshape(-1, 1, 2), .055 if fine else .085, closed).reshape(-1, 2)
    if len(simplified) < 2:
        return []
    # Keep meaningful corners; smooth only shallow turns in curved portions.
    result = [simplified[0].tolist()]
    for idx in range(1, len(simplified)-1):
        previous, current, following = simplified[idx-1:idx+2]
        left, right = current-previous, following-current
        cosine = float(left @ right) / max(1e-9, float(np.linalg.norm(left)*np.linalg.norm(right)))
        if cosine > math.cos(math.radians(38)):
            result.extend(((current*.8+previous*.2).tolist(), (current*.8+following*.2).tolist()))
        else:
            result.append(current.tolist())
    result.append(simplified[-1].tolist())
    if closed and len(simplified) > 2:
        # OpenCV returns the vertices of a polygon without repeating the
        # first vertex; the plotter writer draws consecutive segments only.
        result.append(result[0][:])
    return result


def _square_rectilinear_frame(paths):
    """Fit near-horizontal and near-vertical members, not diagonal leaders."""
    arrays = []
    levels = ([], [])
    closed_flags = []
    for index, path in enumerate(paths):
        closed = np.linalg.norm(np.asarray(path[0])-path[-1]) < 1e-6
        src = np.asarray(path, dtype=np.float32)
        poly = cv2.approxPolyDP(src.reshape(-1, 1, 2), .15, closed).reshape(-1, 2)
        if len(poly) < (3 if closed else 2):
            poly = src[:-1].copy() if closed else src.copy()
        arrays.append(poly)
        closed_flags.append(closed)
        for first in range(len(poly) if closed else len(poly)-1):
            last = (first+1) % len(poly)
            delta = poly[last]-poly[first]
            axis = int(abs(delta[0]) >= abs(delta[1]))
            along = abs(delta[1-axis])
            if along >= 2.0 and abs(delta[axis]) <= min(.58, along*.044):
                levels[axis].append((float((poly[first,axis]+poly[last,axis])/2), float(along), index, first, last))
    for axis, segments in enumerate(levels):
        groups = []
        for segment in sorted(segments):
            if not groups or segment[0]-groups[-1][0][0] > .15:
                groups.append([])
            groups[-1].append(segment)
        for group in groups:
            level = sum(value*weight for value,weight,*_ in group)/sum(item[1] for item in group)
            for _, _, index, first, last in group:
                arrays[index][[first,last],axis] = level
    result = []
    for points, closed in zip(arrays, closed_flags):
        path = points.tolist()
        if closed:
            path.append(path[0][:])
        result.append(path)
    return result


def _snap_pencil_junctions(paths):
    # Join a dangling end only to a crossing stroke that its outward tangent
    # actually points toward. Parallel lines and intended dashed gaps remain.
    arrays = [np.asarray(path, dtype=float) for path in paths]
    a = np.concatenate([p[:-1] for p in arrays])
    delta = np.concatenate([p[1:]-p[:-1] for p in arrays])
    owner = np.repeat(np.arange(len(arrays)), [len(p)-1 for p in arrays])
    lengths = np.linalg.norm(delta, axis=1)
    length_sq = np.maximum(lengths**2, 1e-12)
    units = delta / np.maximum(lengths[:,None], 1e-9)
    out = []
    for idx, p in enumerate(arrays):
        fixed = p.copy()
        if np.linalg.norm(p[0]-p[-1]) >= 1e-6:
            for end in (0, 1):
                pos = 0 if end == 0 else -1
                point = p[pos]
                tangent = _endpoint_tangent(p, end)
                t = np.clip(np.sum((point-a)*delta, axis=1)/length_sq, 0, 1)
                gap = a + t[:,None]*delta - point
                distance = np.linalg.norm(gap, axis=1)
                eligible = ((owner != idx) & (lengths > .32) & (distance <= .30) &
                            (np.abs(units @ tangent) < .65) &
                            ((distance < .075) | ((gap @ tangent) >= .86*distance)))
                if np.any(eligible):
                    best = int(np.argmin(np.where(eligible, distance, np.inf)))
                    fixed[pos] += gap[best]
        out.append(fixed.tolist())
    return out


def write_nc(path: Path, paths):
    pipeline._write_new_gcode(path, nearest_paths(paths), SETTINGS)
    twin = path.with_suffix('.gcode')
    if twin.exists():
        twin.unlink()
    return pipeline.stitch_gcode_polylines.read_draw_polylines(path, z_up=0, z_down=11.9)


def add_paths(page, paths, width=.16):
    shape = page.new_shape()
    for path in paths:
        if len(path) < 2:
            continue
        paper = [_machine_to_paper(x,y) for x,y in path]
        shape.draw_polyline([fitz.Point(x*MM,y*MM) for x,y in paper])
    shape.finish(color=(0, 0, 0), width=width * MM, lineCap=1, lineJoin=1, closePath=False)
    shape.commit()


def save_pdf(doc, path: Path):
    path.write_bytes(doc.tobytes(garbage=4, deflate=True))


def save_png(image: Image.Image, path: Path):
    # PIL's w+b mode conflicts with Windows image-preview handles. Serialize
    # first, then use a write-only handle, as with PDF outputs above.
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    path.write_bytes(buffer.getvalue())


def coverage(paths, skel, rect_mm):
    x0, y0, x1, y1 = rect_mm
    sx = skel.shape[1] / (x1 - x0)
    sy = skel.shape[0] / (y1 - y0)
    raster = np.zeros_like(skel, dtype=np.uint8)
    for path in paths:
        paper = [_machine_to_paper(x,y) for x,y in path]
        pts = np.array([[(x-x0)*sx,(y-y0)*sy] for x,y in paper],dtype=np.int32)
        cv2.polylines(raster, [pts], False, 255, 1)
    radius = max(1, round(.22 * max(sx, sy)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    reconstructed = cv2.dilate(raster, kernel) > 0
    reference = skel > 0
    matched = float(np.count_nonzero(reference & reconstructed) / max(1, np.count_nonzero(reference)))
    allowed = cv2.dilate(reference.astype(np.uint8), kernel) > 0
    extra = float(np.count_nonzero((raster > 0) & ~allowed) / max(1, np.count_nonzero(raster)))
    return matched, extra


def prepare(args):
    output = safe_output(args.output_dir)
    temp = safe_output(args.temp_dir)
    with zipfile.ZipFile(args.source_docx) as z:
        parts = {name: z.read(name) for name in z.namelist()}
    source_pdf_path = next(args.source_render.glob('*.pdf'))
    source_pdf = fitz.open(source_pdf_path)
    placement = {}
    for page_idx, page in enumerate(source_pdf):
        for image in page.get_image_info():
            placement[(image['width'], image['height'])] = (page_idx + 1, [v / MM for v in image['bbox']])
    master_path = prepare_documents(parts, output, args.include_synchronous_generator)
    contract = [
        '# Laboratory hybrid printer and plotter contract',
        f'Reference: {args.source_docx}',
        f'SHA256: {hashlib.sha256(args.source_docx.read_bytes()).hexdigest()}',
        'Reference page count: 22. One A4 portrait section.',
        'Page size: 210.01 x 297 mm. Margins: left 30.004, right 14.993, top and bottom 20.003 mm.',
        'Preserve all source styles, paragraphs, tables, blank response areas, relationships and printed images 14-17.',
        'Editable slots: word/media/image1.png through image13.png. Replace by white PNGs with identical dimensions.',
        'No drawing extent, paragraph spacing, page margin or print scale changes.',
        'Split outputs use the same paragraph ranges, removing only trailing blank paragraphs and a leading hard break.',
        'Plotter-only pencil strokes use paper coordinates and never automatic fit-to-content scaling.',
        'Blue handwriting, including schematic names and numbers, is excluded. Printed graphics stay on printer layer.',
        f'Extra synchronous-generator sheet appended: {args.include_synchronous_generator}.',
    ]
    (temp / 'artifact.md').write_text('\n'.join(contract) + '\n', encoding='utf-8')
    register = PhotoRegistration(args.reference_dir)
    figures = []
    for image_id, lab, photo, roi, title in FIGURES:
        embedded = Image.open(io.BytesIO(parts[f'word/media/image{image_id}.png'])).convert('RGB')
        page_number, rect_mm = placement[embedded.size]
        aligned = register.align(embedded, photo)
        figures.append(dict(id=image_id, lab=lab, page=page_number, title=title, rect_mm=rect_mm, roi=roi, rgb=aligned))
    if args.include_synchronous_generator:
        photo = np.asarray(Image.open(args.reference_dir / '8.jpg').convert('RGB'))
        crop = photo[1415:1970, 200:1520]
        # Keep the same four-pixels-per-embedded-pixel convention as all masks.
        target_width = 155
        target_height = target_width * crop.shape[0] / crop.shape[1]
        figures.append(dict(id=14, lab=2, page=23, title='Синхронный генератор переменного тока',
                            rect_mm=[30, 80, 30 + target_width, 80 + target_height],
                            roi=[1, 1, crop.shape[1] / 4 - 1, crop.shape[0] / 4 - 1], rgb=crop))

    manifest = dict(source=str(args.source_docx), template=str(master_path), page_count=23 if args.include_synchronous_generator else 22,
                    machine='a4_desktop', scale=1.0, paper_mm=[210, 297], paper_registration=PAPER_REGISTRATION,
                    calibrated_paper_bounds_mm=[15, 8.5, 195, 288.5], figures=[], jobs=[])
    grouped = defaultdict(list)
    for figure in figures:
        idx = figure['id']
        folder = output / 'Рисунки' / f'figure_{idx:02d}'
        folder.mkdir(parents=True, exist_ok=True)
        rgb = figure.pop('rgb')
        save_png(Image.fromarray(rgb), folder / 'reference.png')
        mask = pencil_mask(rgb, figure['roi'], idx)
        paths, skel = mask_paths(mask, figure['rect_mm'], idx)
        save_png(Image.fromarray(255 - mask), folder / 'pencil_mask.png')
        restored = write_nc(folder / 'plotter.nc', paths)
        matched, extra = coverage(restored, skel, figure['rect_mm'])
        figure.update(nc=str(folder / 'plotter.nc'), path_count=len(restored), skeleton_coverage=matched, unexpected_draw_ratio=extra)
        print(f'FIGURE {idx:02d} page={figure["page"]} paths={len(restored)} coverage={matched:.4f} extra={extra:.4f}', flush=True)
        if matched < .94 or extra > .015:
            raise ValueError(f'NC reconstruction does not match pencil skeleton for figure {idx}')
        manifest['figures'].append(figure)
        grouped[figure['page']].extend(paths)
    for page_number, paths in sorted(grouped.items()):
        folder = output / 'Страницы для плоттера' / f'page_{page_number:02d}'
        folder.mkdir(parents=True, exist_ok=True)
        restored = write_nc(folder / 'plotter.nc', paths)
        manifest['jobs'].append(dict(page=page_number, nc=str(folder / 'plotter.nc'), figures=[f['id'] for f in figures if f['page'] == page_number], path_count=len(restored)))
    calibration = ROOT / '_plotter_jobs/Nachert_variant11_small/calibration_a4.nc'
    if calibration.exists():
        (output / 'calibration_a4.nc').write_bytes(calibration.read_bytes())
    (output / 'layout.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('TEMPLATE', master_path, flush=True)
    print('NEXT render template, then use --finalize-rendered-pdf', flush=True)


def draw_label(page, text, xy, fontsize=11):
    page.insert_font(fontname='LabText', fontfile=r'C:\Windows\Fonts\arial.ttf')
    page.insert_text(xy, text, fontsize=fontsize, fontname='LabText', color=(0, 0, 0))


def technical_mask(rgb):
    """Keep light antialiased digits as well as blue CAD, not yellow guides.

    A dark-only cutoff broke thin character stems into fragments. This
    threshold is for clean white-background references, not photographs.
    """
    values = np.asarray(rgb).astype(np.int16)
    r,g,b = values[:,:,0],values[:,:,1],values[:,:,2]
    yellow = (np.minimum(r,g)>150)&(np.minimum(r,g)-b>15)&(np.abs(r-g)<45)
    return ((values.min(axis=2)<225)&~yellow).astype(np.uint8)*255


def _legacy_contactor_lines(page):
    lines = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            text = ''.join(span['text'] for span in line['spans']).strip()
            if text:
                lines.append((text,line))
    start = next((i for i,(text,_) in enumerate(lines) if text.startswith('Все узлы контактора')),None)
    if start is None:
        return []
    result = []
    for text,line in lines[start:]:
        result.append(line)
        if text.endswith('деталей.'):
            return result
    raise ValueError('Incomplete legacy contactor paragraph in reference layout')


def clean_legacy_printer_text(args):
    """Remove obsolete figure-103 prose, reserving its exact print space."""
    output = args.output_dir.resolve()
    reference = fitz.open(next(args.source_render.glob('*.pdf')))
    lines = _legacy_contactor_lines(reference[17])
    if len(lines)<2:
        raise ValueError('Cannot measure legacy paragraph without its original lines')
    origins = [line['spans'][0]['origin'][1] for line in lines]
    leading = float(np.median(np.diff(origins)))
    twips = round(leading*len(lines)*20)
    patch = '''
import sys,zipfile
from pathlib import Path
from lxml import etree as ET
w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
height=sys.argv[1]
for argument in sys.argv[2:]:
    path=Path(argument)
    with zipfile.ZipFile(path) as archive:
        parts={name:archive.read(name) for name in archive.namelist()}
    root=ET.fromstring(parts['word/document.xml'])
    count=0
    for paragraph in root.iter(w+'p'):
        text=''.join(node.text or '' for node in paragraph.iter(w+'t')).strip()
        if not text.startswith('Все узлы контактора'):
            continue
        if 'рис. 103' not in text:
            raise ValueError('Refusing to clear an unrelated contactor description')
        properties=paragraph.find(w+'pPr')
        if properties is None:
            properties=ET.Element(w+'pPr');paragraph.insert(0,properties)
        spacing=properties.find(w+'spacing')
        if spacing is None:spacing=ET.SubElement(properties,w+'spacing')
        spacing.set(w+'line',height);spacing.set(w+'lineRule','exact')
        for child in list(paragraph):
            if child is not properties:paragraph.remove(child)
        ET.SubElement(ET.SubElement(paragraph,w+'r'),w+'t').text=''
        count+=1
    if count:
        parts['word/document.xml']=ET.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True)
        staged=path.with_suffix('.docx.tmp')
        with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in parts.items():archive.writestr(name,data)
        staged.replace(path)
    print('OBSOLETE_PARAGRAPHS_REMOVED',path.name,count,flush=True)
'''
    documents=[output/'Печатный шаблон ЛР 1-5.docx',output/'Word по работам'/'Лабораторная работа 4.docx']
    subprocess.run([os.environ.get('CODEX_DOCX_PYTHON',sys.executable),'-c',patch,str(twips),
                    *[str(path) for path in documents]],check=True)
    path=output/'layout.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    data.update(obsolete_description_removed=True,approved=False)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def adopt_technical_references(args):
    output = safe_output(args.output_dir)
    manifest_path = output/'layout.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    source = fitz.open(args.technical_reference_pdf)
    original = fitz.open(next(args.source_render.glob('*.pdf')))
    targets = [
        (14, 15, 3, (654,344), 'Ударно-тяговое устройство'),
        (15, 17, 4, (327,573), 'Кислотная аккумуляторная батарея'),
        (16, 18, 4, (408,462), 'Электромагнитный контактор'),
        (17, 19, 4, (249,264), 'Электропневматический контактор'),
    ]
    additions = []
    for ident, page_number, lab, dimensions, title in targets:
        slot = next(image for image in original[page_number-1].get_image_info()
                    if (image['width'],image['height']) == dimensions)
        image_info = source[page_number-1].get_image_info(xrefs=True)[-1]
        image = Image.open(io.BytesIO(source.extract_image(image_info['xref'])['image'])).convert('RGB')
        rect = [value/MM for value in slot['bbox']]
        # Letterbox in the old slot instead of stretching a newly supplied
        # drawing to the old image's (often quite different) aspect ratio.
        width, height = dimensions[0]*4, dimensions[1]*4
        physical_width, physical_height = rect[2]-rect[0], rect[3]-rect[1]
        scale_mm = min(physical_width/image.width, physical_height/image.height)
        pixel_width = max(1,round(image.width*scale_mm/physical_width*width))
        pixel_height = max(1,round(image.height*scale_mm/physical_height*height))
        resized = image.resize((pixel_width,pixel_height), Image.Resampling.LANCZOS)
        canvas = Image.new('RGB',(width,height),'white')
        canvas.paste(resized,((width-resized.width)//2,(height-resized.height)//2))
        folder = output/'Рисунки'/f'figure_{ident:02d}'
        folder.mkdir(exist_ok=True)
        save_png(canvas,folder/'reference.png')
        additions.append(dict(id=ident,page=page_number,lab=lab,title=title,rect_mm=rect,
                              roi=[0,0,dimensions[0],dimensions[1]],nc=str(folder/'plotter.nc'),
                              kind='technical_reference',reference_pdf=str(args.technical_reference_pdf)))
    # Only replace image payloads. The document XML and all inline extents,
    # page breaks, fonts, print text, and tables remain byte-for-byte intact.
    documents = [output/'Печатный шаблон ЛР 1-5.docx'] + [
        output/'Word по работам'/f'Лабораторная работа {lab}.docx' for lab in (3,4)]
    patch = '''
import io,sys,zipfile
from pathlib import Path
from PIL import Image
for argument in sys.argv[1:]:
    path=Path(argument)
    with zipfile.ZipFile(path) as archive:
        parts={name:archive.read(name) for name in archive.namelist()}
    for ident in range(14,18):
        name=f'word/media/image{ident}.png'
        with Image.open(io.BytesIO(parts[name])) as old:
            buffer=io.BytesIO()
            Image.new('RGB',old.size,'white').save(buffer,format='PNG')
            parts[name]=buffer.getvalue()
    staged=path.with_suffix('.docx.tmp')
    with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in parts.items():
            archive.writestr(name,data)
    staged.replace(path)
    print('PRINT_LAYER_UPDATED',path.name,flush=True)
'''
    subprocess.run([os.environ.get('CODEX_DOCX_PYTHON',sys.executable),'-c',patch,
                    *[str(path) for path in documents]],check=True)
    manifest['figures'] = sorted([f for f in manifest['figures'] if f['id'] < 14] + additions,key=lambda f:f['id'])
    by_page = defaultdict(list)
    for figure in manifest['figures']:
        by_page[figure['page']].append(figure['id'])
    manifest['jobs'] = []
    for page_number, ids in sorted(by_page.items()):
        folder = output/'Страницы для плоттера'/f'page_{page_number:02d}'
        folder.mkdir(exist_ok=True)
        manifest['jobs'].append(dict(page=page_number,figures=ids,nc=str(folder/'plotter.nc')))
    manifest.update(approved=False,technical_reference_pdf=str(args.technical_reference_pdf))
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    clean_legacy_printer_text(args)
    print('ADOPTED four technical references; render printer documents before rebuilding NC',flush=True)


def rebuild_drawings(args):
    """Rebuild cached photo slots in place; never rewrite the printer layer."""
    output = args.output_dir.resolve()
    manifest = json.loads((output / 'layout.json').read_text(encoding='utf-8'))
    if args.technical_only and manifest.get('paper_registration') != PAPER_REGISTRATION:
        raise ValueError('A full rebuild is required before reusing NC with the corrected paper registration')
    if args.drop_extra_sheet:
        manifest['figures'] = [figure for figure in manifest['figures'] if figure['page'] != 23]
        manifest['jobs'] = [job for job in manifest['jobs'] if job['page'] != 23]
        manifest['page_count'] = 22
    grouped = defaultdict(list)
    for figure in manifest['figures']:
        folder = Path(figure['nc']).parent
        technical = figure.get('kind') == 'technical_reference'
        if args.technical_only and not technical:
            grouped[figure['page']].extend(pipeline.stitch_gcode_polylines.read_draw_polylines(
                Path(figure['nc']),z_up=0,z_down=11.9))
            continue
        with Image.open(folder / 'reference.png') as image:
            rgb = np.asarray(image.convert('RGB'))
        mask = technical_mask(rgb) if technical else pencil_mask(rgb, figure['roi'], figure['id'])
        paths, target = mask_paths(mask, figure['rect_mm'], figure['id'], technical=technical)
        restored = write_nc(Path(figure['nc']), paths)
        matched, extra = coverage(restored, target, figure['rect_mm'])
        if matched < .995 or extra > .005:
            raise ValueError(f'Geometry lost during NC serialization: figure {figure["id"]}')
        save_png(Image.fromarray(255-target), folder / 'pencil_mask.png')
        figure.update(path_count=len(restored), skeleton_coverage=matched, unexpected_draw_ratio=extra,
                      reconstruction='pencil_structural_v4',drawing_style='neat_single_pen_v1')
        grouped[figure['page']].extend(paths)
        print(f'REBUILT figure={figure["id"]:02d} page={figure["page"]} paths={len(restored)}', flush=True)
    for job in manifest['jobs']:
        restored = write_nc(Path(job['nc']), grouped[job['page']])
        job['path_count'] = len(restored)
    manifest.update(reconstruction='pencil_structural_v4',drawing_style='neat_single_pen_v1',
                    paper_registration=PAPER_REGISTRATION,approved=False)
    (output / 'layout.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def finalize(args):
    output = args.output_dir.resolve()
    temp = args.temp_dir.resolve()
    data = json.loads((output / 'layout.json').read_text(encoding='utf-8'))
    if data.get('paper_registration') != PAPER_REGISTRATION:
        raise ValueError('Rebuild NC before rendering previews with the corrected paper registration')
    printed = fitz.open(args.finalize_rendered_pdf)
    if len(printed) != data['page_count']:
        raise ValueError(f'Template pagination drift: {len(printed)} != {data["page_count"]}')
    reference = fitz.open(next(args.source_render.glob('*.pdf')))
    for i in range(len(reference)):
        # Printed layer must preserve every original text span and its position.
        def spans(page, exclude_legacy=False):
            obsolete = _legacy_contactor_lines(page) if exclude_legacy else []
            excluded = {tuple(line['bbox']) for line in obsolete}
            return [(s['text'], s['bbox']) for block in page.get_text('dict')['blocks'] if 'lines' in block
                    for line in block['lines'] if tuple(line['bbox']) not in excluded for s in line['spans']]
        old, new = spans(reference[i],exclude_legacy=data.get('obsolete_description_removed',False)), spans(printed[i])
        if len(old) != len(new) or any(a[0] != b[0] or max(abs(x-y) for x, y in zip(a[1], b[1])) > .2 for a, b in zip(old, new)):
            raise ValueError(f'Printer text moved on page {i+1}')
    actual = fitz.open()
    actual.insert_pdf(printed)
    pen_only = fitz.open()
    pen_toc = []
    for job in data['jobs']:
        paths = pipeline.stitch_gcode_polylines.read_draw_polylines(Path(job['nc']), z_up=0, z_down=11.9)
        page_idx = job['page'] - 1
        add_paths(actual[page_idx], paths)
        add_paths(pen_only.new_page(width=210*MM, height=297*MM), paths)
        pen_toc.append([1, f'Лист {job["page"]} общего шаблона', len(pen_only)])
        preview = fitz.open()
        preview.insert_pdf(printed, from_page=page_idx, to_page=page_idx)
        add_paths(preview[0], paths)
        save_pdf(preview, Path(job['nc']).parent / 'plot_preview.pdf')
    save_pdf(actual, output / 'Итог из G-кода.pdf')
    pen_only.set_toc(pen_toc)
    save_pdf(pen_only, output / 'Только траектории плоттера.pdf')
    comparison = fitz.open()
    for figure in data['figures']:
        folder = Path(figure['nc']).parent
        page = comparison.new_page(width=841.89, height=595.28)
        draw_label(page, f'ЛР {figure["lab"]}   Страница {figure["page"]}   Рисунок {figure["id"]}', (24, 28), 12)
        draw_label(page, figure['title'], (24, 50), 14)
        draw_label(page, 'Пример с рукописными записями', (24, 80), 11)
        draw_label(page, 'Траектории пера из готового NC без ручки', (435, 80), 11)
        left, right = fitz.Rect(24, 95, 407, 530), fitz.Rect(435, 95, 818, 530)
        roi = figure['roi']
        with Image.open(folder / 'reference.png') as image:
            # Some original Word image slots use non-square effective pixels.
            # Display the reference in paper millimeters, just like the NC,
            # instead of misleadingly stretching one comparison column.
            x0,y0,x1,y1=figure['rect_mm']
            original_width,original_height=image.size
            physical_size=(max(1,round((x1-x0)*10)),max(1,round((y1-y0)*10)))
            normalized=image.resize(physical_size,Image.Resampling.LANCZOS)
            crop=normalized.crop((round(roi[0]*4/original_width*physical_size[0]),
                                  round(roi[1]*4/original_height*physical_size[1]),
                                  round(roi[2]*4/original_width*physical_size[0]),
                                  round(roi[3]*4/original_height*physical_size[1])))
            buf = io.BytesIO(); crop.save(buf, 'PNG')
        page.insert_image(left, stream=buf.getvalue(), keep_proportion=True)
        paths = pipeline.stitch_gcode_polylines.read_draw_polylines(Path(figure['nc']), z_up=0, z_down=11.9)
        x0, y0, x1, y1 = figure['rect_mm']
        with Image.open(folder / 'reference.png') as image:
            width, height = image.size
        crop_mm = fitz.Rect((x0 + roi[0] * 4 / width * (x1-x0)) * MM,
                           (y0 + roi[1] * 4 / height * (y1-y0)) * MM,
                           (x0 + roi[2] * 4 / width * (x1-x0)) * MM,
                           (y0 + roi[3] * 4 / height * (y1-y0)) * MM)
        isolated = fitz.open(); canvas = isolated.new_page(width=210*MM, height=297*MM)
        add_paths(canvas, paths, width=.16)
        page.show_pdf_page(right, isolated, 0, clip=crop_mm)
        legend = ('Сохранены линии технического чертежа и его печатные обозначения, включая синие линии CAD.'
                  if figure.get('kind') == 'technical_reference' else 'Рукописные подписи и номера исключены; печатный текст остаётся в Word.')
        draw_label(page, legend, (24, 564), 10)
        if figure.get('reconstruction'):
            detail = ('Аккуратная инженерная зарисовка без искусственных волн. Справа реальные линии из NC.'
                      if figure.get('drawing_style') == 'neat_single_pen_v1' else
                      'Геометрия выровнена и очищена. Правая картинка восстановлена только из готового NC.')
        else:
            detail = 'Правая картинка восстановлена из NC; это не оценка точности распознавания фотографии.'
        draw_label(page, detail, (24, 580), 10)
    save_pdf(comparison, output / 'Сравнение рисунков.pdf')
    lines = [
        'ЛАБОРАТОРНЫЕ РАБОТЫ 1-5: ПЕЧАТЬ И ПЛОТТЕР', '',
        '1. Печатный шаблон ЛР 1-5.docx: печатать на A4, масштаб 100%, одна страница на лист.',
        'Не менять поля, шрифт, интервалы, размер бумаги и не включать подгонку под страницу.',
        'Отдельные Word-файлы находятся в папке Word по работам.',
        '2. Только карандашные рисунки идут на маленький плоттер. Ручку и синие номера не рисовать.',
        ('Четыре новые технические схемы удалены из печатного слоя и включены в очередь плоттера.'
         if data.get('technical_reference_pdf') else 'Типографские схемы сохранены в Word и повторно плоттером не обводятся.'),
        '3. NC привязан к бумаге A4 1:1: калибровочные углы расположены на листе',
        'в точках (15;8,5), (195;8,5), (15;288,5), (195;288,5) мм от верхнего левого угла.',
        'Рабочие координаты X=0..180, Y=-285..-5. Не запускать автоподгонку масштаба.',
        'Верх печатного листа соответствует краю поля Y=-285, низ - краю Y=-5. X не отражается.',
        'Перо: вверх 0, рисование 11,9, скорость Z 2500. Рисование 2200, переходы 15000 мм/мин.',
        'Ни один файл автоматически на станок не отправлялся.',
        'Все рисунки: аккуратная инженерная зарисовка одной линией, без искусственных волн и повторной обводки.',
        '4. Итог из G-кода.pdf: печатный шаблон плюс только реальные линии пера из NC.',
        'Сравнение рисунков.pdf: исходные фото и восстановленные траектории для согласования.',
        'Совпадение с фото не означает подтверждение механической точности станка или подачи бумаги.', '',
        'ОЧЕРЕДЬ ПО СТРАНИЦАМ ОБЩЕГО ШАБЛОНА',
    ]
    for idx, job in enumerate(data['jobs'], 1):
        titles = '; '.join(f['title'] for f in data['figures'] if f['id'] in job['figures'])
        lines.append(f'{idx}. Страница {job["page"]}: {titles}. Страницы для плоттера/page_{job["page"]:02d}/plotter.nc')
    if data['page_count'] == 23:
        lines.extend(['', 'Страница 23: дополнительный рисунок синхронного генератора из фото 8.',
                      'В отдельной лабораторной работе 2 это последний, шестой лист.'])
    lines.extend(['', 'Соответствие отдельных Word-файлов общему шаблону:',
                  'ЛР 1: страницы 1-7. ЛР 2: 8-12 и дополнительная 23, если включена.',
                  'ЛР 3: 13-16. ЛР 4: 17-20. ЛР 5: 21-22.'])
    (output / 'Порядок рисования.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    print(f'FINALIZED: {len(printed)} printer pages, {len(data["figures"])} figures, {len(data["jobs"])} page jobs', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-docx', type=Path, required=True)
    parser.add_argument('--reference-dir', type=Path, required=True)
    parser.add_argument('--source-render', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--temp-dir', type=Path, required=True)
    parser.add_argument('--include-synchronous-generator', action='store_true')
    parser.add_argument('--rebuild-drawings', action='store_true', help='Reconstruct cached pencil drawings without changing Word files')
    parser.add_argument('--drop-extra-sheet', action='store_true', help='Exclude the old optional sheet from a cached rebuild')
    parser.add_argument('--technical-reference-pdf', type=Path, help='Adopt four replacement technical drawings and clear their printer slots')
    parser.add_argument('--technical-only', action='store_true', help='Reuse existing photo NC while rebuilding the four technical references')
    parser.add_argument('--clean-printer-text', action='store_true', help='Clear obsolete figure-103 prose without moving print content')
    parser.add_argument('--finalize-rendered-pdf', type=Path)
    args = parser.parse_args()
    if args.clean_printer_text:
        clean_legacy_printer_text(args)
    elif args.technical_reference_pdf:
        adopt_technical_references(args)
    elif args.rebuild_drawings:
        rebuild_drawings(args)
        if args.finalize_rendered_pdf:
            finalize(args)
    elif args.finalize_rendered_pdf:
        finalize(args)
    else:
        prepare(args)


if __name__ == '__main__':
    main()
