from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from skimage.morphology import remove_small_objects, skeletonize

SRC = Path(r'C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg')
OUT_DIR = Path(r'C:\plotter_pdf\_plotter_jobs\gemini_grattage_scan_hatch_max_a4_pack')
NAME = 'gemini_grattage_scan_hatch_max_a4'
PAGE_W_MM = 180.0
PAGE_H_MM = 280.0
MARGIN_MM = 4.0
DRAW_FEED = 1400.0
TRAVEL_FEED = 3500.0

OUT_DIR.mkdir(parents=True, exist_ok=True)

img = Image.open(SRC).convert('L')
gray = np.asarray(img, dtype=np.uint8)
h, w = gray.shape

# Keep the original composition, but normalize paper and expose pencil lines.
soft = cv2.GaussianBlur(gray, (0, 0), 18)
line = soft.astype(np.float32) - gray.astype(np.float32)
line[line < 0] = 0
p1, p995 = np.percentile(line, [4, 99.5])
line_norm = np.clip((line - p1) * 255.0 / max(1.0, p995 - p1), 0, 255).astype(np.uint8)
line_norm = cv2.medianBlur(line_norm, 3)
line_norm = cv2.GaussianBlur(line_norm, (0, 0), 0.45)

# Two masks: strong strokes can be shorter, weak pencil texture must be long enough.
strong = line_norm > 34
weak = line_norm > 22
weak = remove_small_objects(weak.astype(bool), min_size=22)
strong = remove_small_objects(strong.astype(bool), min_size=9)
mask = np.logical_or(strong, weak)
# Remove isolated paper grain but do not close aggressively: closing creates artificial blobs.
mask = remove_small_objects(mask, min_size=12)
skel = skeletonize(mask).astype(np.uint8)

# Clear tiny accidental specks on absolute image edge; we add a clean plot border later.
skel[:2, :] = 0
skel[-2:, :] = 0
skel[:, :2] = 0
skel[:, -2:] = 0

coords = set(map(tuple, np.argwhere(skel > 0)))
NEI = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]

def neigh(p):
    y, x = p
    out = []
    for dy, dx in NEI:
        q = (y + dy, x + dx)
        if q in coords:
            out.append(q)
    return out

def edge_key(a, b):
    return (a, b) if a <= b else (b, a)

def pix_len(path):
    total = 0.0
    for (y1,x1),(y2,x2) in zip(path, path[1:]):
        total += math.hypot(x2-x1, y2-y1)
    return total

def rdp(points, eps):
    if len(points) < 3:
        return points
    a = np.array(points[0], dtype=float)
    b = np.array(points[-1], dtype=float)
    ab = b - a
    denom = float(np.dot(ab, ab))
    best_i = -1
    best_d = -1.0
    for i in range(1, len(points)-1):
        p = np.array(points[i], dtype=float)
        if denom <= 1e-9:
            d = float(np.linalg.norm(p-a))
        else:
            t = max(0.0, min(1.0, float(np.dot(p-a, ab) / denom)))
            proj = a + t*ab
            d = float(np.linalg.norm(p-proj))
        if d > best_d:
            best_d = d
            best_i = i
    if best_d > eps:
        left = rdp(points[:best_i+1], eps)
        right = rdp(points[best_i:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]

nodes = {p for p in coords if len(neigh(p)) != 2}
visited = set()
raw_paths = []

for n in list(nodes):
    for nb in neigh(n):
        e = edge_key(n, nb)
        if e in visited:
            continue
        visited.add(e)
        path = [n, nb]
        prev, cur = n, nb
        guard = 0
        while cur not in nodes and guard < 20000:
            ns = [q for q in neigh(cur) if q != prev]
            if not ns:
                break
            nxt = ns[0]
            e2 = edge_key(cur, nxt)
            if e2 in visited:
                break
            visited.add(e2)
            path.append(nxt)
            prev, cur = cur, nxt
            guard += 1
        raw_paths.append(path)

# closed loops or all-degree-2 residues
for p in list(coords):
    for nb in neigh(p):
        e = edge_key(p, nb)
        if e in visited:
            continue
        visited.add(e)
        path = [p, nb]
        prev, cur = p, nb
        guard = 0
        while guard < 20000:
            ns = [q for q in neigh(cur) if q != prev]
            if not ns:
                break
            nxt = ns[0]
            e2 = edge_key(cur, nxt)
            if e2 in visited:
                break
            visited.add(e2)
            path.append(nxt)
            prev, cur = cur, nxt
            guard += 1
        raw_paths.append(path)

# Scale to plotter working area.
scale = min((PAGE_W_MM - 2*MARGIN_MM) / w, (PAGE_H_MM - 2*MARGIN_MM) / h)
img_w_mm = w * scale
img_h_mm = h * scale
x0 = (PAGE_W_MM - img_w_mm) / 2.0
y0 = (PAGE_H_MM - img_h_mm) / 2.0

def to_mm(pt):
    y, x = pt
    return (x0 + x * scale, y0 + y * scale)

def path_mm_len(path_mm):
    return sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(path_mm, path_mm[1:]))

paths = []
for path in raw_paths:
    if len(path) < 2:
        continue
    plen = pix_len(path)
    if plen < 6:
        continue
    vals = [int(line_norm[y, x]) for y, x in path[::max(1, len(path)//18)]]
    mean_dark = float(np.mean(vals)) if vals else 0.0
    ys = [p[0] for p in path]
    xs = [p[1] for p in path]
    cy = (min(ys) + max(ys)) / (2*h)
    cx = (min(xs) + max(xs)) / (2*w)
    # Strong subject/forest strokes may be shorter. Pale sky/field noise must be long.
    min_len = 8.0 if mean_dark > 58 else 13.0 if mean_dark > 39 else 22.0
    if cy < 0.38:
        min_len += 8.0
    if cy > 0.72 and mean_dark < 38:
        min_len += 3.0
    if plen < min_len:
        continue
    # Avoid grain-like blobs: require some extension in at least one direction.
    if max(max(xs)-min(xs), max(ys)-min(ys)) < 5 and mean_dark < 65:
        continue
    simp_pix = rdp([(p[1], p[0]) for p in path], 1.05 if mean_dark < 45 else 0.8)
    simp_yx = [(int(round(y)), int(round(x))) for x,y in simp_pix]
    mm_path = [to_mm(p) for p in simp_yx]
    if len(mm_path) >= 2 and path_mm_len(mm_path) >= 1.2:
        paths.append((mm_path, mean_dark, cy, cx))

# Keep composition clean: cap only weak strokes, always keep dark/long strokes.
scored = []
for mm_path, mean_dark, cy, cx in paths:
    L = path_mm_len(mm_path)
    score = mean_dark * 0.9 + L * 5.5
    if cy < 0.40:
        score -= 18.0
    scored.append((score, mm_path, mean_dark, cy, cx, L))
scored.sort(reverse=True, key=lambda t: t[0])
# Maximum detail without paper-grain soup.
kept = []
sky_count = 0
for score, mm_path, mean_dark, cy, cx, L in scored:
    if cy < 0.40:
        if sky_count >= 430 and mean_dark < 55:
            continue
        sky_count += 1
    kept.append(mm_path)
    if len(kept) >= 5200:
        break

# Coherent scan hatching. This is the key noise fix: dark areas get many parallel strokes,
# light areas get sparse strokes, and strokes are grouped into families instead of random sticks.
density = cv2.GaussianBlur(line_norm.astype(np.float32) / 255.0, (0, 0), 8.0)
rng_scan = np.random.default_rng(777331)

def add_scan_hatch(name, y0r, y1r, threshold, spacing_px, angles_deg, sample_step, min_seg_px, cap, keep_prob=1.0):
    added = 0
    y_min = int(y0r * h)
    y_max = int(y1r * h)
    cx0 = w * 0.5
    cy0 = h * 0.5
    diag = math.hypot(w, h)
    for angle_deg in angles_deg:
        theta = math.radians(angle_deg)
        dx, dy = math.cos(theta), math.sin(theta)
        nx, ny = -dy, dx
        vmin, vmax = -diag * 0.58, diag * 0.58
        umin, umax = -diag * 0.62, diag * 0.62
        v_values = np.arange(vmin, vmax, spacing_px)
        # Deterministic tiny shift prevents mechanical moire but keeps family direction visible.
        v_values = v_values + rng_scan.uniform(-spacing_px*.18, spacing_px*.18, size=len(v_values))
        for v in v_values:
            if added >= cap:
                return added
            pts = []
            active = []
            u_values = np.arange(umin, umax, sample_step)
            for u in u_values:
                x = cx0 + dx*u + nx*v
                y = cy0 + dy*u + ny*v
                if x < 3 or x >= w-3 or y < max(3, y_min) or y >= min(h-3, y_max):
                    pts.append(None)
                    active.append(False)
                    continue
                d0 = float(density[int(y), int(x)])
                # Sparse probability only near threshold, always draw confidently dark masses.
                if d0 >= threshold:
                    p = min(1.0, keep_prob * (0.35 + 5.0*(d0-threshold)))
                    ok = rng_scan.random() <= p
                else:
                    ok = False
                pts.append((x, y, d0))
                active.append(ok)
            i = 0
            while i < len(active):
                while i < len(active) and not active[i]:
                    i += 1
                start = i
                gap = 0
                last_good = i - 1
                while i < len(active):
                    if active[i]:
                        gap = 0
                        last_good = i
                    else:
                        gap += 1
                        if gap > 1:
                            break
                    i += 1
                end = last_good
                if end <= start:
                    continue
                p_start = pts[start]
                p_end = pts[end]
                if p_start is None or p_end is None:
                    continue
                seg_len = math.hypot(p_end[0]-p_start[0], p_end[1]-p_start[1])
                if seg_len < min_seg_px:
                    continue
                # Split very long lines into hand-sized strokes with small gaps.
                chunks = max(1, int(seg_len // 80))
                for ch in range(chunks):
                    if added >= cap:
                        return added
                    a = ch / chunks
                    b = min(1.0, (ch + 0.88) / chunks)
                    x1 = p_start[0] + (p_end[0]-p_start[0])*a
                    y1 = p_start[1] + (p_end[1]-p_start[1])*a
                    x2 = p_start[0] + (p_end[0]-p_start[0])*b
                    y2 = p_start[1] + (p_end[1]-p_start[1])*b
                    mx = (x1+x2)*.5 + rng_scan.normal(0, .6)
                    my = (y1+y2)*.5 + rng_scan.normal(0, .6)
                    mm_path = [to_mm((y1, x1)), to_mm((my, mx)), to_mm((y2, x2))]
                    if path_mm_len(mm_path) >= 1.0:
                        kept.append(mm_path)
                        added += 1
            
    return added

scan_added = {}
scan_added['sky_cloud'] = add_scan_hatch('sky_cloud', .04, .34, .038, 18, [-26, -20, 24], 4, 22, 220, .65)
scan_added['forest_cross'] = add_scan_hatch('forest_cross', .31, .53, .036, 6, [-62, 54], 3, 9, 1750, .95)
scan_added['forest_dark_extra'] = add_scan_hatch('forest_dark_extra', .32, .53, .070, 5, [-42, 68], 3, 8, 800, 1.00)
scan_added['field_slope'] = add_scan_hatch('field_slope', .47, .70, .030, 9, [-14, -10], 4, 24, 560, .70)
scan_added['grass_front'] = add_scan_hatch('grass_front', .66, .99, .030, 8, [-82, 75], 3, 8, 980, .75)
scan_added['subject_shadow'] = add_scan_hatch('subject_shadow', .57, .99, .062, 5, [-55, 43, -72], 3, 8, 1320, 1.00)
print('scan_added:', scan_added)
# Add a clean border matching the illustration frame.
border = [(x0, y0), (x0 + img_w_mm, y0), (x0 + img_w_mm, y0 + img_h_mm), (x0, y0 + img_h_mm), (x0, y0)]
kept.insert(0, border)

# Greedy nearest-end ordering.
remaining = kept[:]
ordered = []
cur = (0.0, 0.0)
while remaining:
    best_i = 0
    best_rev = False
    best_d = 1e18
    for i, p in enumerate(remaining):
        d0 = math.hypot(p[0][0]-cur[0], p[0][1]-cur[1])
        d1 = math.hypot(p[-1][0]-cur[0], p[-1][1]-cur[1])
        if d0 < best_d:
            best_i, best_rev, best_d = i, False, d0
        if d1 < best_d:
            best_i, best_rev, best_d = i, True, d1
    p = remaining.pop(best_i)
    if best_rev:
        p = list(reversed(p))
    ordered.append(p)
    cur = p[-1]

# Write G-code / NC.
def write_gcode(path: Path):
    draw = 0.0
    travel = 0.0
    lines = ['; grattage scan-hatch max A4', 'G21', 'G90', 'G0 Z3.500']
    cur = (0.0, 0.0)
    for p in ordered:
        sx, sy = p[0]
        travel += math.hypot(sx-cur[0], sy-cur[1])
        lines.append(f'G0 X{sx:.3f} Y{-sy:.3f} F{TRAVEL_FEED:.0f}')
        lines.append('G1 Z0.000 F900')
        last = (sx, sy)
        for x, y in p[1:]:
            draw += math.hypot(x-last[0], y-last[1])
            lines.append(f'G1 X{x:.3f} Y{-y:.3f} F{DRAW_FEED:.0f}')
            last = (x, y)
        lines.append('G0 Z3.500')
        cur = last
    lines.append('M2')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return draw, travel, len(lines)

nc = OUT_DIR / f'{NAME}.nc'
gcode = OUT_DIR / f'{NAME}.gcode'
draw_len, travel_len, gcode_lines = write_gcode(nc)
gcode.write_text(nc.read_text(encoding='utf-8'), encoding='utf-8')

# PNG preview.
S = 7
png_w = int(PAGE_W_MM * S)
png_h = int(PAGE_H_MM * S)
preview = Image.new('RGB', (png_w, png_h), 'white')
d = ImageDraw.Draw(preview)
for p in ordered:
    pts = [(x*S, y*S) for x, y in p]
    if len(pts) >= 2:
        d.line(pts, fill=(0,0,0), width=1)
png = OUT_DIR / f'{NAME}_preview_black_actual.png'
preview.save(png)

# PDF preview with exact mm coordinates.
pdf = OUT_DIR / f'{NAME}_preview_black_actual.pdf'
c = canvas.Canvas(str(pdf), pagesize=(PAGE_W_MM*mm, PAGE_H_MM*mm))
c.setStrokeColorRGB(0,0,0)
c.setLineWidth(0.10*mm)
for p in ordered:
    if len(p) < 2:
        continue
    c.setLineWidth(0.10*mm)
    pdf_path = c.beginPath()
    x, y = p[0]
    pdf_path.moveTo(x*mm, (PAGE_H_MM-y)*mm)
    for x, y in p[1:]:
        pdf_path.lineTo(x*mm, (PAGE_H_MM-y)*mm)
    c.drawPath(pdf_path, stroke=1, fill=0)
c.showPage()
c.save()

readme = OUT_DIR / 'README_result.txt'
est_min = draw_len / DRAW_FEED + travel_len / TRAVEL_FEED + len(ordered)*0.18/60.0
readme.write_text(
    f'GRATTAGE SCAN HATCH MAX A4\n'
    f'source: {SRC}\n'
    f'paths_total: {len(ordered)}\n'
    f'draw_length_m: {draw_len/1000:.2f}\n'
    f'travel_length_m: {travel_len/1000:.2f}\n'
    f'estimated_time_min_ideal: {est_min:.1f}\n'
    f'image_fit_mm: {img_w_mm:.1f} x {img_h_mm:.1f}\n'
    f'nc: {nc}\n'
    f'gcode: {gcode}\n'
    f'preview_png: {png}\n'
    f'preview_pdf: {pdf}\n',
    encoding='utf-8'
)
print('GRATTAGE SCAN HATCH MAX A4 package')
print('paths_total:', len(ordered))
print('draw_length_m:', round(draw_len/1000, 2))
print('travel_length_m:', round(travel_len/1000, 2))
print('estimated_time_min_ideal:', round(est_min, 1))
print('image_fit_mm:', round(img_w_mm,1), 'x', round(img_h_mm,1))
print('preview:', png)
print('pdf:', pdf)
print('nc:', nc)


