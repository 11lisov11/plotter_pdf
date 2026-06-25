from __future__ import annotations

import math
import shutil
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from skimage.morphology import skeletonize

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_faithful_pencil_trace_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)

WORK_W_MM = 180.0
WORK_H_MM = 280.0
DRAW_W_MM = 176.0
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0
TRAVEL_F = 3000
DRAW_F = 1200


def rdp(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    p0 = np.array(points[0], dtype=float)
    p1 = np.array(points[-1], dtype=float)
    v = p1 - p0
    vv = float(np.dot(v, v))
    if vv <= 1e-9:
        dists = [float(np.linalg.norm(np.array(p) - p0)) for p in points]
    else:
        dists = []
        for p in points:
            pp = np.array(p, dtype=float)
            t = max(0.0, min(1.0, float(np.dot(pp - p0, v) / vv)))
            proj = p0 + t * v
            dists.append(float(np.linalg.norm(pp - proj)))
    idx = int(np.argmax(dists))
    if dists[idx] <= eps:
        return [points[0], points[-1]]
    left = rdp(points[: idx + 1], eps)
    right = rdp(points[idx:], eps)
    return left[:-1] + right


def neighbors8(y: int, x: int, h: int, w: int, skel: np.ndarray):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            yy = y + dy
            xx = x + dx
            if 0 <= yy < h and 0 <= xx < w and skel[yy, xx]:
                yield yy, xx


def edge_key(a: tuple[int, int], b: tuple[int, int], w: int) -> tuple[int, int]:
    ia = a[0] * w + a[1]
    ib = b[0] * w + b[1]
    return (ia, ib) if ia <= ib else (ib, ia)


def trace_skeleton(skel: np.ndarray, strength: np.ndarray) -> list[dict]:
    h, w = skel.shape
    kernel = np.ones((3, 3), np.uint8)
    deg = cv2.filter2D(skel.astype(np.uint8), -1, kernel, borderType=cv2.BORDER_CONSTANT) - skel.astype(np.uint8)
    nodes = (skel > 0) & (deg != 2)
    visited: set[tuple[int, int]] = set()
    paths: list[list[tuple[int, int]]] = []

    node_pts = np.argwhere(nodes)
    for y0, x0 in node_pts:
        p0 = (int(y0), int(x0))
        for nb in neighbors8(p0[0], p0[1], h, w, skel):
            k = edge_key(p0, nb, w)
            if k in visited:
                continue
            path = [p0, nb]
            visited.add(k)
            prev = p0
            cur = nb
            guard = 0
            while not nodes[cur[0], cur[1]]:
                cand = []
                for n2 in neighbors8(cur[0], cur[1], h, w, skel):
                    if n2 == prev:
                        continue
                    kk = edge_key(cur, n2, w)
                    if kk not in visited:
                        cand.append(n2)
                if not cand:
                    break
                # Prefer continuing straight through tiny diagonal pixel knots.
                if len(cand) > 1:
                    vy = cur[0] - prev[0]
                    vx = cur[1] - prev[1]
                    cand.sort(key=lambda q: -((q[0] - cur[0]) * vy + (q[1] - cur[1]) * vx))
                nxt = cand[0]
                visited.add(edge_key(cur, nxt, w))
                path.append(nxt)
                prev, cur = cur, nxt
                guard += 1
                if guard > h * w:
                    break
            if len(path) >= 2:
                paths.append(path)

    # Closed loops without endpoints/junctions.
    ys, xs = np.nonzero(skel)
    for y, x in zip(ys, xs):
        p0 = (int(y), int(x))
        unvisited_nbs = [nb for nb in neighbors8(p0[0], p0[1], h, w, skel) if edge_key(p0, nb, w) not in visited]
        for first in unvisited_nbs:
            if edge_key(p0, first, w) in visited:
                continue
            path = [p0, first]
            visited.add(edge_key(p0, first, w))
            prev = p0
            cur = first
            guard = 0
            while True:
                cand = [n2 for n2 in neighbors8(cur[0], cur[1], h, w, skel) if n2 != prev and edge_key(cur, n2, w) not in visited]
                if not cand:
                    break
                nxt = cand[0]
                visited.add(edge_key(cur, nxt, w))
                path.append(nxt)
                prev, cur = cur, nxt
                guard += 1
                if cur == p0 or guard > h * w:
                    break
            if len(path) >= 3:
                paths.append(path)

    out: list[dict] = []
    for path in paths:
        pts_xy = [(float(x), float(y)) for y, x in path]
        length_px = 0.0
        for a, b in zip(pts_xy, pts_xy[1:]):
            length_px += math.hypot(b[0] - a[0], b[1] - a[1])
        if length_px < 7.0:
            continue
        vals = [float(strength[y, x]) for y, x in path]
        mean_strength = float(np.mean(vals)) if vals else 0.0
        max_strength = float(np.max(vals)) if vals else 0.0
        # Keep long pale pencil hatches, reject short paper specks.
        if length_px < 15.0 and mean_strength < 13.0 and max_strength < 28.0:
            continue
        simp = rdp(pts_xy, 0.85)
        if len(simp) < 2:
            continue
        out.append({"pts_px": simp, "length_px": length_px, "strength": mean_strength, "max_strength": max_strength})
    return out


def preprocess(gray: np.ndarray):
    # Normalize slow paper shading, then use coherence to avoid random paper grain.
    den = cv2.fastNlMeansDenoising(gray, None, h=4, templateWindowSize=7, searchWindowSize=21)
    bg = cv2.GaussianBlur(den, (0, 0), sigmaX=25, sigmaY=25)
    norm = cv2.divide(den, bg, scale=236)
    norm = cv2.GaussianBlur(norm, (3, 3), 0)
    local_dark = np.clip(236 - norm.astype(np.int16), 0, 255).astype(np.float32)
    global_dark = np.clip(242 - den.astype(np.int16), 0, 255).astype(np.float32)
    strength = np.maximum(local_dark * 1.65, global_dark * 0.42)

    gx = cv2.Sobel(norm, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(norm, cv2.CV_32F, 0, 1, ksize=3)
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), 2.0)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), 2.0)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), 2.0)
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-3)
    grad = cv2.magnitude(gx, gy)

    strong = strength > 23
    mid = (strength > 14) & (coh > 0.18) & (grad > 3.0)
    faint = (strength > 8.5) & (coh > 0.35) & (grad > 4.0)
    mask = (strong | mid | faint).astype(np.uint8)

    # Make hair/tree strokes continuous, but do not blob-fill tonal areas.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)

    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    clean = np.zeros_like(mask)
    kept = 0
    for i in range(1, num):
        x, y, ww, hh, area = stats[i]
        long_side = max(ww, hh)
        if area >= 9 and long_side >= 5:
            clean[labels == i] = 1
            kept += 1
        elif area >= 5 and long_side >= 9:
            clean[labels == i] = 1
            kept += 1
    return clean.astype(bool), strength, norm, coh, kept


def px_to_mm_paths(paths: list[dict], img_w: int, img_h: int):
    draw_w = DRAW_W_MM
    draw_h = draw_w * img_h / img_w
    if draw_h > WORK_H_MM - 4:
        draw_h = WORK_H_MM - 4
        draw_w = draw_h * img_w / img_h
    x0 = (WORK_W_MM - draw_w) / 2.0
    y0 = (WORK_H_MM - draw_h) / 2.0
    scale = draw_w / img_w
    converted = []
    for p in paths:
        pts = []
        for x, y in p["pts_px"]:
            pts.append((x0 + x * scale, -(y0 + y * scale)))
        length_mm = p["length_px"] * scale
        if length_mm < 1.2:
            continue
        converted.append({**p, "pts_mm": pts, "length_mm": length_mm})
    return converted, draw_w, draw_h


def order_paths(paths: list[dict]) -> list[dict]:
    # Organized boustrophedon ordering: much less chaotic than random nearest jumps.
    def cy(p):
        ys = [pt[1] for pt in p["pts_mm"]]
        return sum(ys) / len(ys)
    rows: dict[int, list[dict]] = defaultdict(list)
    row_h = 8.0
    for p in paths:
        row = int(math.floor((-cy(p)) / row_h))
        rows[row].append(p)
    ordered = []
    for row in sorted(rows):
        group = rows[row]
        reverse_row = row % 2 == 1
        for p in group:
            pts = p["pts_mm"]
            if (pts[0][0] > pts[-1][0]) ^ reverse_row:
                p = {**p, "pts_mm": list(reversed(pts))}
            ordered.append(p)
        ordered[-len(group):] = sorted(ordered[-len(group):], key=lambda p: p["pts_mm"][0][0], reverse=reverse_row)
    return ordered


def write_gcode(paths: list[dict], out_nc: Path):
    lines = [
        "; faithful pencil trace A4",
        "G21",
        "G90",
        f"G0 Z{PEN_UP_Z:.3f}",
        f"F{TRAVEL_F}",
    ]
    draw_len = 0.0
    travel_len = 0.0
    cur = None
    for p in paths:
        pts = p["pts_mm"]
        if len(pts) < 2:
            continue
        start = pts[0]
        if cur is not None:
            travel_len += math.hypot(start[0] - cur[0], start[1] - cur[1])
        lines.append(f"G0 X{start[0]:.3f} Y{start[1]:.3f}")
        lines.append(f"G1 Z{PEN_DOWN_Z:.3f} F{DRAW_F}")
        prev = start
        for x, y in pts[1:]:
            lines.append(f"G1 X{x:.3f} Y{y:.3f}")
            draw_len += math.hypot(x - prev[0], y - prev[1])
            prev = (x, y)
        lines.append(f"G0 Z{PEN_UP_Z:.3f}")
        cur = pts[-1]
    lines.append("M2")
    out_nc.write_text("\n".join(lines) + "\n", encoding="ascii")
    return draw_len, travel_len, len(lines)


def render_png(paths: list[dict], png: Path, pressure_gray: bool = True):
    scale = 5.0
    pad = 60
    w = int(WORK_W_MM * scale + pad * 2)
    h = int(WORK_H_MM * scale + pad * 2)
    im = Image.new("RGB", (w, h), "white")
    dr = ImageDraw.Draw(im)
    # Paper/work area border.
    dr.rectangle([pad, pad, pad + WORK_W_MM * scale, pad + WORK_H_MM * scale], outline=(195, 195, 195), width=1)
    for p in paths:
        pts = []
        for x, y in p["pts_mm"]:
            pts.append((pad + x * scale, pad + (-y) * scale))
        if len(pts) < 2:
            continue
        if pressure_gray:
            s = p.get("strength", 18.0)
            gray = int(np.clip(225 - s * 4.0, 50, 205))
            color = (gray, gray, gray)
        else:
            color = (0, 0, 0)
        dr.line(pts, fill=color, width=1, joint="curve")
    im.save(png)


def png_to_pdf(png: Path, pdf: Path):
    c = canvas.Canvas(str(pdf), pagesize=A4)
    page_w, page_h = A4
    img = Image.open(png)
    iw, ih = img.size
    margin = 18
    scale = min((page_w - 2 * margin) / iw, (page_h - 2 * margin) / ih)
    dw = iw * scale
    dh = ih * scale
    c.drawImage(str(png), (page_w - dw) / 2, (page_h - dh) / 2, dw, dh)
    c.showPage()
    c.save()


def main():
    shutil.copy2(SRC, OUT / "source_input_copy.jpg")
    gray = cv2.imread(str(SRC), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise SystemExit(f"Cannot read {SRC}")
    mask, strength, norm, coh, kept_components = preprocess(gray)
    cv2.imwrite(str(OUT / "debug_normalized.png"), norm)
    cv2.imwrite(str(OUT / "debug_strength.png"), np.clip(strength * 3.0, 0, 255).astype(np.uint8))
    cv2.imwrite(str(OUT / "debug_mask.png"), (mask.astype(np.uint8) * 255))
    skel = skeletonize(mask).astype(np.uint8)
    # Remove tiny skeleton crumbs before graph tracing.
    num, labels, stats, _ = cv2.connectedComponentsWithStats(skel, connectivity=8)
    clean_skel = np.zeros_like(skel)
    for i in range(1, num):
        area = stats[i, cv2.CC_STAT_AREA]
        ww = stats[i, cv2.CC_STAT_WIDTH]
        hh = stats[i, cv2.CC_STAT_HEIGHT]
        if area >= 5 and max(ww, hh) >= 5:
            clean_skel[labels == i] = 1
    cv2.imwrite(str(OUT / "debug_skeleton.png"), clean_skel * 255)

    paths = trace_skeleton(clean_skel.astype(bool), strength)
    paths_mm, draw_w, draw_h = px_to_mm_paths(paths, gray.shape[1], gray.shape[0])
    # Filter over-dense microscopic clutter by length/strength after scaling.
    paths_mm = [p for p in paths_mm if p["length_mm"] >= 1.5 or p["strength"] >= 22.0]
    paths_mm = order_paths(paths_mm)

    nc = OUT / "gemini_faithful_pencil_trace_a4.nc"
    gcode = OUT / "gemini_faithful_pencil_trace_a4.gcode"
    draw_len, travel_len, line_count = write_gcode(paths_mm, nc)
    shutil.copy2(nc, gcode)

    pressure_png = OUT / "gemini_faithful_pencil_trace_preview_pressure_gray.png"
    black_png = OUT / "gemini_faithful_pencil_trace_preview_black_actual.png"
    render_png(paths_mm, pressure_png, True)
    render_png(paths_mm, black_png, False)
    png_to_pdf(pressure_png, OUT / "gemini_faithful_pencil_trace_preview_pressure_gray.pdf")
    png_to_pdf(black_png, OUT / "gemini_faithful_pencil_trace_preview_black_actual.pdf")

    readme = OUT / "README_result.txt"
    readme.write_text(
        "FAITHFUL PENCIL TRACE A4 package\n"
        f"source: {SRC}\n"
        f"output_dir: {OUT}\n"
        f"image_px: {gray.shape[1]} x {gray.shape[0]}\n"
        f"work_area_mm: {WORK_W_MM:.1f} x {WORK_H_MM:.1f}\n"
        f"drawing_size_mm: {draw_w:.2f} x {draw_h:.2f}\n"
        f"mask_components_kept: {kept_components}\n"
        f"paths_total: {len(paths_mm)}\n"
        f"draw_length_m: {draw_len/1000:.2f}\n"
        f"travel_length_m: {travel_len/1000:.2f}\n"
        f"gcode_lines: {line_count}\n"
        f"estimated_time_min_ideal: {(draw_len/1200 + travel_len/3000):.1f}\n"
        "realistic_time_note: likely 2-4 hours depending on pen lifts and GRBL acceleration.\n"
        "algorithm_note: extracts real pencil strokes from the source image after background normalization; removes paper grain using orientation coherence and component filters; skeletonizes to one-pass plotter paths instead of random tonal noise.\n"
        "files:\n"
        "- gemini_faithful_pencil_trace_preview_pressure_gray.png/pdf\n"
        "- gemini_faithful_pencil_trace_preview_black_actual.png/pdf\n"
        "- gemini_faithful_pencil_trace_a4.nc\n"
        "- gemini_faithful_pencil_trace_a4.gcode\n",
        encoding="utf-8",
    )
    print(readme.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
