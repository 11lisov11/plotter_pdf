from __future__ import annotations
import math, shutil
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw
import cv2
try:
    from skimage.morphology import skeletonize
except Exception:
    skeletonize = None

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tonal_hatch_max_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT / "source_input_copy.jpg")

img_bgr = cv2.imread(str(SRC), cv2.IMREAD_COLOR)
if img_bgr is None:
    raise SystemExit(f"cannot read {SRC}")
gray0 = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
# Crop to white drawing page/content, excluding outside viewer margins.
mask_page = gray0 < 252
ys, xs = np.where(mask_page)
x0, x1 = int(xs.min()), int(xs.max())
y0, y1 = int(ys.min()), int(ys.max())
pad = 8
x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
x1 = min(gray0.shape[1]-1, x1 + pad); y1 = min(gray0.shape[0]-1, y1 + pad)
gray = gray0[y0:y1+1, x0:x1+1]
H, W = gray.shape
Image.fromarray(gray).save(OUT / "source_cropped_gray.png")

# Paper/scan normalization. We intentionally remove paper grain before turning tone into strokes.
denoised = cv2.fastNlMeansDenoising(gray, None, 8, 7, 21)
bg = cv2.GaussianBlur(denoised.astype(np.float32), (0, 0), 36)
norm = np.clip(denoised.astype(np.float32) / np.maximum(bg, 1) * 246, 0, 255).astype(np.uint8)
ink = (255 - norm).astype(np.float32) / 255.0
ink = cv2.GaussianBlur(ink, (0, 0), 0.45)
# Density field controls hatching. It is deliberately smooth: tones, not pixels.
d1 = cv2.GaussianBlur(ink, (0, 0), 2.2)
d2 = cv2.GaussianBlur(ink, (0, 0), 7.0)
density = np.maximum(d1 * 0.72, d2 * 1.18)
lo = np.percentile(density, 42)
hi = np.percentile(density, 99.4)
density = np.clip((density - lo) / max(1e-6, hi - lo), 0, 1)
# gamma < 1 lifts mid-tone graphite, but keep empty sky sparse by later band rules.
density = np.power(density, 0.72)
Image.fromarray(np.uint8(255 * (1 - density))).save(OUT / "density_debug.png")

# A4 working area in the real plotter window.
WORK_W, WORK_H = 180.0, 280.0
DRAW_W = 176.0
scale = DRAW_W / W
DRAW_H = H * scale
if DRAW_H > 270.0:
    DRAW_H = 270.0
    scale = DRAW_H / H
    DRAW_W = W * scale
XOFF = (WORK_W - DRAW_W) / 2.0
YTOP = (WORK_H - DRAW_H) / 2.0

def pix_to_mm(y: float, x: float) -> tuple[float, float]:
    return XOFF + x * scale, -(YTOP + y * scale)

def pressure_level(tone: float, layer_bias: float = 0.0):
    v = max(0.0, min(1.0, tone + layer_bias))
    if v < 0.18: return 10.62, 215, 2350
    if v < 0.32: return 10.86, 180, 2200
    if v < 0.48: return 11.10, 132, 2000
    if v < 0.66: return 11.38, 82, 1700
    return 11.72, 32, 1450

paths: list[dict] = []

# 1) Real source stroke centerlines: contours/details from the actual drawing, not synthetic noise.
line_mask = (ink > 0.070).astype(np.uint8)
num, labels, stats, _ = cv2.connectedComponentsWithStats(line_mask, 8)
clean = np.zeros_like(line_mask)
for i in range(1, num):
    area = int(stats[i, cv2.CC_STAT_AREA])
    w = int(stats[i, cv2.CC_STAT_WIDTH]); h = int(stats[i, cv2.CC_STAT_HEIGHT])
    if area >= 5 and max(w, h) >= 4:
        clean[labels == i] = 1
if skeletonize is not None:
    skel = skeletonize(clean.astype(bool))
else:
    skel = clean.astype(bool)
Image.fromarray(np.uint8(255 - skel.astype(np.uint8) * 255)).save(OUT / "skeleton_debug.png")
coords = np.argwhere(skel)
coord_set = set((int(y), int(x)) for y, x in coords)
N8 = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
def neighbours(p):
    y, x = p
    out = []
    for dy, dx in N8:
        q = (y+dy, x+dx)
        if q in coord_set:
            out.append(q)
    return out
deg = {p: len(neighbours(p)) for p in coord_set}
visited = set()
def edge_key(a, b): return (a, b) if a <= b else (b, a)
def trace_path(a, b):
    path = [a, b]
    visited.add(edge_key(a, b))
    prev, cur = a, b
    while True:
        ns = [q for q in neighbours(cur) if q != prev]
        if deg.get(cur, 0) != 2 or not ns:
            break
        q = ns[0]
        if edge_key(cur, q) in visited:
            break
        visited.add(edge_key(cur, q))
        path.append(q)
        prev, cur = cur, q
    return path
pix_paths = []
for p, d in list(deg.items()):
    if d != 2:
        for q in neighbours(p):
            if edge_key(p, q) not in visited:
                pix_paths.append(trace_path(p, q))
for p in list(coord_set):
    for q in neighbours(p):
        if edge_key(p, q) not in visited:
            pix_paths.append(trace_path(p, q))

def point_line_dist(pt, a, b):
    py, px = pt; ay, ax = a; by, bx = b
    vx = bx - ax; vy = by - ay; wx = px - ax; wy = py - ay
    c1 = vx*wx + vy*wy
    if c1 <= 0: return math.hypot(px-ax, py-ay)
    c2 = vx*vx + vy*vy
    if c2 <= c1: return math.hypot(px-bx, py-by)
    t = c1 / c2
    return math.hypot(px-(ax+t*vx), py-(ay+t*vy))
def rdp(points, eps):
    if len(points) < 3:
        return points
    a = points[0]; b = points[-1]
    best_d = -1.0; best_i = -1
    for i in range(1, len(points)-1):
        d = point_line_dist(points[i], a, b)
        if d > best_d:
            best_d = d; best_i = i
    if best_d > eps:
        return rdp(points[:best_i+1], eps)[:-1] + rdp(points[best_i:], eps)
    return [a, b]

for p in pix_paths:
    if len(p) < 3:
        continue
    arr = np.array(p)
    vals = ink[arr[:,0], arr[:,1]]
    dens_vals = density[arr[:,0], arr[:,1]]
    avg = float(vals.mean()); mx = float(vals.max()); d_avg = float(dens_vals.mean())
    length_px = sum(math.hypot(p[i+1][1]-p[i][1], p[i+1][0]-p[i][0]) for i in range(len(p)-1))
    ymean = float(arr[:,0].mean()) / H
    # keep intentional fine lines; kill paper dust/scan freckles
    if length_px < 5.0: continue
    if avg < 0.055 and length_px < 23: continue
    if ymean < 0.34 and avg < 0.080 and length_px < 34: continue
    simp = rdp([(int(y), int(x)) for y, x in p], 0.88)
    pts = [pix_to_mm(y, x) for y, x in simp]
    z, shade, feed = pressure_level(max(d_avg, mx * 2.0))
    paths.append({'pts': pts, 'z': z, 'shade': shade, 'feed': feed, 'kind': 'real_trace', 'tone': d_avg})

# 2) Controlled tonal hatching. These are smooth field/forest/body masses, never pixel dust.
def add_hatch_layer(name: str, angle_deg: float, spacing_px: float, threshold: float, y0f: float, y1f: float,
                    min_len_px: float, bridge_gap_px: int, layer_bias: float = 0.0,
                    x0f: float = 0.0, x1f: float = 1.0, phase: float = 0.0,
                    require_local_max: float = 0.0):
    theta = math.radians(angle_deg)
    ux, uy = math.cos(theta), math.sin(theta)
    nx, ny = -uy, ux
    corners = [(x0f*W, y0f*H), (x1f*W, y0f*H), (x0f*W, y1f*H), (x1f*W, y1f*H)]
    projs = [x*nx + y*ny for x, y in corners]
    minp, maxp = min(projs)-spacing_px, max(projs)+spacing_px
    diag = math.hypot(W, H)
    count = int((maxp-minp)/spacing_px) + 1
    made = 0
    sample_step = 2.0
    for si in range(count):
        off = minp + si * spacing_px + phase
        cx, cy = (x0f+x1f)*W/2, (y0f+y1f)*H/2
        center_proj = cx*nx + cy*ny
        px = cx + (off-center_proj)*nx
        py = cy + (off-center_proj)*ny
        current = []
        gap = 0
        segs = []
        # deterministic slight broken pencil feel: skip microscopic holes only, not noisy dashes.
        for t in np.arange(-diag, diag, sample_step):
            x = px + t*ux; y = py + t*uy
            xi = int(round(x)); yi = int(round(y))
            if xi < 0 or xi >= W or yi < 0 or yi >= H or xi < x0f*W or xi > x1f*W or yi < y0f*H or yi > y1f*H:
                if current:
                    gap += 1
                    if gap > bridge_gap_px:
                        if len(current) >= 2: segs.append(current)
                        current = []; gap = 0
                continue
            d = float(density[yi, xi])
            ok = d >= threshold
            # Sky must stay airy. Only cloud/strong pencil tone can hatch there.
            if yi/H < 0.30 and d < threshold + 0.12:
                ok = False
            if require_local_max and float(ink[yi, xi]) < require_local_max:
                ok = False
            if ok:
                current.append((yi, xi, d)); gap = 0
            elif current:
                gap += 1
                if gap > bridge_gap_px:
                    if len(current) >= 2: segs.append(current)
                    current = []; gap = 0
        if current and len(current) >= 2:
            segs.append(current)
        for seg in segs:
            length = 0.0
            for a, b in zip(seg, seg[1:]):
                length += math.hypot(b[1]-a[1], b[0]-a[0])
            if length < min_len_px:
                continue
            tone = float(np.mean([s[2] for s in seg]))
            z, shade, feed = pressure_level(tone, layer_bias)
            # Keep hatches as calm, deliberate pencil strokes with a few intermediate points.
            step = max(1, int(len(seg) / 11))
            sample = seg[::step]
            if sample[-1] != seg[-1]:
                sample.append(seg[-1])
            pts = [pix_to_mm(y, x) for y, x, _ in sample]
            paths.append({'pts': pts, 'z': z, 'shade': shade, 'feed': feed, 'kind': name, 'tone': tone})
            made += 1
    return made

hatch_counts = {}
# Sky/clouds: very sparse, only soft tonal indication.
hatch_counts['sky_soft_1'] = add_hatch_layer('sky_soft_1', 25, 28, 0.30, 0.02, 0.35, 28, 3, -0.10)
hatch_counts['sky_soft_2'] = add_hatch_layer('sky_soft_2', -25, 34, 0.42, 0.02, 0.35, 22, 2, -0.05, phase=9)
# Forest band: dense but structured cross-hatching.
hatch_counts['forest_a'] = add_hatch_layer('forest_a', 63, 11, 0.19, 0.34, 0.58, 12, 4, -0.02)
hatch_counts['forest_b'] = add_hatch_layer('forest_b', -57, 13, 0.30, 0.34, 0.58, 10, 3, 0.03, phase=4)
hatch_counts['forest_c_dark'] = add_hatch_layer('forest_c_dark', 88, 10, 0.46, 0.34, 0.60, 8, 2, 0.10, phase=2)
# Field/hill: long directional strokes, not random dots.
hatch_counts['field_long_1'] = add_hatch_layer('field_long_1', -13, 8.5, 0.135, 0.52, 0.74, 30, 5, -0.08)
hatch_counts['field_long_2'] = add_hatch_layer('field_long_2', 14, 15, 0.28, 0.52, 0.76, 24, 3, -0.02, phase=5)
# Lower grass: many short vertical/diagonal deliberate marks, sparse where light.
hatch_counts['grass_a'] = add_hatch_layer('grass_a', 78, 8, 0.14, 0.68, 0.98, 10, 2, -0.05)
hatch_counts['grass_b'] = add_hatch_layer('grass_b', 102, 11, 0.25, 0.68, 0.98, 9, 2, 0.03, phase=4)
hatch_counts['grass_dark_cross'] = add_hatch_layer('grass_dark_cross', -62, 13, 0.42, 0.66, 0.98, 8, 2, 0.12, phase=6)
# Figure/jacket/hair dark mass: tight crosshatch only where density is high.
hatch_counts['figure_dark_a'] = add_hatch_layer('figure_dark_a', 58, 7, 0.28, 0.61, 0.98, 9, 3, 0.04, x0f=0.25, x1f=0.64)
hatch_counts['figure_dark_b'] = add_hatch_layer('figure_dark_b', -48, 8, 0.39, 0.61, 0.98, 8, 2, 0.12, x0f=0.25, x1f=0.64, phase=3)
hatch_counts['figure_deep'] = add_hatch_layer('figure_deep', 8, 6.5, 0.58, 0.61, 0.98, 8, 2, 0.20, x0f=0.25, x1f=0.64, phase=2)

# One composition border.
border = [(XOFF, -YTOP), (XOFF+DRAW_W, -YTOP), (XOFF+DRAW_W, -(YTOP+DRAW_H)), (XOFF, -(YTOP+DRAW_H)), (XOFF, -YTOP)]
paths.insert(0, {'pts': border, 'z': 11.10, 'shade': 120, 'feed': 1900, 'kind': 'border', 'tone': 0.5})

# Nearest-neighbor order, bounded but enough for local path efficiency.
def reorder(paths_in):
    first = paths_in[:1]
    rest = paths_in[1:]
    ordered = []
    cur = first[0]['pts'][-1]
    while rest:
        best_i = 0; best_rev = False; best_d = 1e18
        limit = min(len(rest), 1600)
        for i in range(limit):
            p = rest[i]; a = p['pts'][0]; b = p['pts'][-1]
            da = math.hypot(a[0]-cur[0], a[1]-cur[1])
            db = math.hypot(b[0]-cur[0], b[1]-cur[1])
            if da < best_d:
                best_i = i; best_rev = False; best_d = da
            if db < best_d:
                best_i = i; best_rev = True; best_d = db
        p = rest.pop(best_i)
        if best_rev:
            p = dict(p); p['pts'] = list(reversed(p['pts']))
        ordered.append(p); cur = p['pts'][-1]
    return first + ordered
paths = reorder(paths)
kind_counts = Counter(p['kind'] for p in paths)

def render(path: Path, *, pressure: bool, black: bool = False, dark_bg: bool = False):
    dpi = 230
    cw = int(WORK_W / 25.4 * dpi); ch = int(WORK_H / 25.4 * dpi)
    bgc = (255,255,255) if not dark_bg else (24,24,24)
    im = Image.new('RGB', (cw, ch), bgc)
    d = ImageDraw.Draw(im)
    def mm(x,y): return int(round(x / 25.4 * dpi)), int(round((-y) / 25.4 * dpi))
    d.rectangle([mm(0,0), mm(WORK_W, -WORK_H)], outline=(238,238,238) if not dark_bg else (66,66,66), width=1)
    for p in paths:
        pts = [mm(x,y) for x,y in p['pts']]
        if len(pts) < 2: continue
        if black:
            col = (0,0,0) if not dark_bg else (235,235,235)
        elif pressure:
            s = int(p['shade'])
            col = (s,s,s) if not dark_bg else (max(28,255-s),)*3
        else:
            col = (55,55,55) if not dark_bg else (225,225,225)
        d.line(pts, fill=col, width=1)
    im.save(path)
    im.save(path.with_suffix('.pdf'), 'PDF', resolution=dpi)

render(OUT / 'gemini_tonal_hatch_max_preview_pressure_gray.png', pressure=True)
render(OUT / 'gemini_tonal_hatch_max_preview_black_actual.png', pressure=False, black=True)
render(OUT / 'gemini_tonal_hatch_max_preview_dark_pressure.png', pressure=True, dark_bg=True)

# G-code
SAFE_Z = 13.00
lines = [
    '; gemini_tonal_hatch_max_a4',
    '; tonal layer hatching: dark areas dense/close, light areas sparse; variable Z pressure',
    'G21', 'G90', f'G0 Z{SAFE_Z:.2f}', 'G0 X0.000 Y0.000'
]
draw_len = 0.0; travel_len = 0.0; last = (0.0, 0.0)
for p in paths:
    pts = p['pts']; a = pts[0]
    travel_len += math.hypot(a[0]-last[0], a[1]-last[1])
    lines.append(f'; {p["kind"]} tone={p["tone"]:.3f} z={p["z"]:.2f}')
    lines.append(f'G0 Z{SAFE_Z:.2f}')
    lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}')
    lines.append(f'G1 Z{p["z"]:.2f} F900')
    prev = a
    for x,y in pts[1:]:
        draw_len += math.hypot(x-prev[0], y-prev[1])
        lines.append(f'G1 X{x:.3f} Y{y:.3f} F{p["feed"]}')
        prev = (x,y)
    lines.append(f'G0 Z{SAFE_Z:.2f}')
    last = pts[-1]
lines += ['G0 X0.000 Y0.000', f'G0 Z{SAFE_Z:.2f}', 'M2']
(OUT / 'gemini_tonal_hatch_max_a4.nc').write_text('\n'.join(lines) + '\n', encoding='utf-8')
(OUT / 'gemini_tonal_hatch_max_a4.gcode').write_text('\n'.join(lines) + '\n', encoding='utf-8')

readme = f"""TONAL HATCH MAX A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
paths: {len(paths)}
kind_counts: {dict(kind_counts)}
hatch_counts: {hatch_counts}
draw_length_m: {draw_len/1000:.2f}
travel_length_m: {travel_len/1000:.2f}
estimated_time_min_ideal: {(draw_len/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Closest to reference requires pencil/soft pen and calibrated Z pressure.
algorithm_note: actual source pencil strokes are traced as centerlines; tonal masses are filled by deterministic hatching layers. Dark zones get multiple close layers; light zones stay sparse.
files:
- gemini_tonal_hatch_max_preview_pressure_gray.png/pdf
- gemini_tonal_hatch_max_preview_black_actual.png/pdf
- gemini_tonal_hatch_max_preview_dark_pressure.png/pdf
- gemini_tonal_hatch_max_a4.nc
- gemini_tonal_hatch_max_a4.gcode
"""
(OUT / 'README_result.txt').write_text(readme, encoding='utf-8')
print(readme)
