from __future__ import annotations

from pathlib import Path
import math
import random
from collections import Counter

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from scipy.ndimage import gaussian_filter, binary_closing, binary_opening
from skimage.morphology import remove_small_objects, skeletonize

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_pencil_density_coherent_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20260622)
np.random.seed(20260622)

DRAW_W_MM = 180.0
DRAW_H_MM = 240.0
TOP_MM = 20.0
SAFE_H_MM = 280.0
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0
TRAVEL_F = 3000
DRAW_F = 1200
PX_PER_MM = 4

img0 = Image.open(SRC).convert("L")
w0, h0 = img0.size
W = 900
H = int(round(h0 * W / w0))
img = img0.resize((W, H), Image.Resampling.LANCZOS)
w, h = img.size
gray = np.asarray(img, dtype=np.float32) / 255.0

# Normalize paper / camera tone, then build a smooth density map.
bg = gaussian_filter(gray, sigma=28)
flat = np.clip(gray / np.maximum(bg, 0.58), 0, 1)
flat = np.clip((flat - 0.04) / 0.96, 0, 1)
tone_raw = 1.0 - flat
tone = gaussian_filter(tone_raw, sigma=2.4)
tone = np.clip((tone - 0.018) / 0.36, 0, 1)
tone_dark = gaussian_filter(tone_raw, sigma=0.9)

yy, xx = np.mgrid[0:h, 0:w]
xn = xx / max(1, w - 1)
yn = yy / max(1, h - 1)

hair_mask = ((((xn - 0.535) / 0.155) ** 2 + ((yn - 0.640) / 0.170) ** 2) < 1.0) | (
    (((xn - 0.635) / 0.185) ** 2 + ((yn - 0.660) / 0.120) ** 2) < 1.0
)
jacket_mask = ((((xn - 0.455) / 0.170) ** 2 + ((yn - 0.845) / 0.185) ** 2) < 1.0) | (
    (((xn - 0.365) / 0.110) ** 2 + ((yn - 0.785) / 0.110) ** 2) < 1.0
)
arm_mask = ((((xn - 0.365) / 0.105) ** 2 + ((yn - 0.725) / 0.085) ** 2) < 1.0)
figure_mask = hair_mask | jacket_mask | arm_mask
sky_mask = yn < 0.330
forest_mask = (yn > 0.310) & (yn < 0.525) & (~figure_mask)
field_mask = (yn > 0.440) & (yn < 0.790) & (~figure_mask)
grass_mask = (yn > 0.635) & (~figure_mask)

paths: list[tuple[str, list[tuple[float, float]]]] = []

def add_path(kind: str, pts: list[tuple[float, float]], min_len_px: float = 8.0) -> None:
    if len(pts) < 2:
        return
    cleaned = [pts[0]]
    length = 0.0
    last = pts[0]
    for p in pts[1:]:
        d = math.hypot(p[0] - last[0], p[1] - last[1])
        if d >= 0.8:
            cleaned.append(p)
            length += d
            last = p
    if len(cleaned) >= 2 and length >= min_len_px:
        paths.append((kind, cleaned))

def simplify_add(kind: str, pts: list[tuple[float, float]], eps: float = 1.0, min_len_px: float = 8.0) -> None:
    if len(pts) < 2:
        return
    arr = np.array(pts, dtype=np.float32).reshape((-1, 1, 2))
    approx = cv2.approxPolyDP(arr, epsilon=eps, closed=False).reshape((-1, 2))
    add_path(kind, [(float(x), float(y)) for x, y in approx], min_len_px=min_len_px)

def smooth_active(mask: np.ndarray, threshold: float, open_px: int = 1, close_px: int = 4) -> np.ndarray:
    active = mask & (tone >= threshold)
    if close_px > 0:
        active = binary_closing(active, structure=np.ones((close_px, close_px), dtype=bool))
    if open_px > 0:
        active = binary_opening(active, structure=np.ones((open_px, open_px), dtype=bool))
    active = remove_small_objects(active, min_size=28)
    return active

def hatch(kind: str, mask: np.ndarray, threshold: float, angle_deg: float, spacing_px: float, step_px: float,
          min_run_px: float, jitter_px: float = 0.0, keep: float = 1.0, phase_px: float = 0.0,
          open_px: int = 1, close_px: int = 4) -> None:
    active = smooth_active(mask, threshold, open_px=open_px, close_px=close_px)
    theta = math.radians(angle_deg)
    e = np.array([math.cos(theta), math.sin(theta)], dtype=np.float32)
    p = np.array([-math.sin(theta), math.cos(theta)], dtype=np.float32)
    center = np.array([w / 2.0, h / 2.0], dtype=np.float32)
    diag = math.hypot(w, h)
    u_values = np.arange(-diag / 2 - 30, diag / 2 + 30, step_px, dtype=np.float32)
    rng = random.Random(777 + int(angle_deg * 19) + int(threshold * 1000) + int(spacing_px * 23) + int(phase_px * 11))
    line_count = int(diag / spacing_px) + 6
    for i in range(-line_count // 2, line_count // 2 + 1):
        if rng.random() > keep:
            continue
        v = i * spacing_px + phase_px
        run: list[tuple[float, float]] = []
        for u in u_values:
            xy = center + e * u + p * v
            x, y = int(round(float(xy[0]))), int(round(float(xy[1])))
            if 0 <= x < w and 0 <= y < h and active[y, x]:
                wob = jitter_px * (0.70 * math.sin(0.030 * u + 0.57 * i) + 0.30 * math.sin(0.011 * u + phase_px))
                pt = xy + p * wob
                run.append((float(pt[0]), float(pt[1])))
            else:
                if len(run) * step_px >= min_run_px:
                    simplify_add(kind, run, eps=0.95, min_len_px=min_run_px * 0.72)
                run = []
        if len(run) * step_px >= min_run_px:
            simplify_add(kind, run, eps=0.95, min_len_px=min_run_px * 0.72)

def bezier(p0, p1, p2, p3, n=50):
    pts = []
    for i in range(n):
        t = i / (n - 1)
        pts.append((
            (1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t**2*p2[0] + t**3*p3[0],
            (1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] + 3*(1-t)*t**2*p2[1] + t**3*p3[1],
        ))
    return pts

def clip_add(kind: str, pts: list[tuple[float, float]], mask: np.ndarray, min_len_px: float = 12.0) -> None:
    run: list[tuple[float, float]] = []
    for x, y in pts:
        ix, iy = int(round(x)), int(round(y))
        if 0 <= ix < w and 0 <= iy < h and mask[iy, ix]:
            run.append((x, y))
        else:
            if run:
                simplify_add(kind, run, eps=0.85, min_len_px=min_len_px)
            run = []
    if run:
        simplify_add(kind, run, eps=0.85, min_len_px=min_len_px)

# Essential dark contours only. No weak-outline flood in the sky.
binary = tone_dark > 0.155
binary = binary_closing(binary, structure=np.ones((2, 2), dtype=bool))
binary = remove_small_objects(binary, min_size=32)
skel = skeletonize(binary).astype(np.uint8) * 255
contours, _ = cv2.findContours(skel, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
for cnt in contours:
    if len(cnt) < 10:
        continue
    x, y, ww, hh = cv2.boundingRect(cnt)
    arc = cv2.arcLength(cnt, False)
    if arc < 18 or ww < 3 or hh < 3:
        continue
    ymid = (y + 0.5 * hh) / h
    local = float(np.mean(tone[max(0, y):min(h, y + hh), max(0, x):min(w, x + ww)]))
    if ymid < 0.33 and (arc < 70 or local < 0.135):
        continue
    if local < 0.080 and arc < 60:
        continue
    pts = [(float(p[0][0]), float(p[0][1])) for p in cnt]
    simplify_add("dark_contour", pts, eps=1.20, min_len_px=14.0)

# Broad coherent hatching. Spacing controls tone: dark close, light sparse.
hatch("sky_light", sky_mask, 0.065, -25, spacing_px=24, step_px=6, min_run_px=42, jitter_px=0.9, keep=0.66, phase_px=4, open_px=1, close_px=7)
hatch("sky_cross", sky_mask, 0.140, 30, spacing_px=31, step_px=6, min_run_px=34, jitter_px=0.65, keep=0.36, phase_px=10, open_px=1, close_px=6)

hatch("forest_light", forest_mask, 0.012, -63, spacing_px=18, step_px=5, min_run_px=42, jitter_px=0.75, keep=0.76, phase_px=2, open_px=0, close_px=9)
hatch("forest_mid", forest_mask, 0.105, 55, spacing_px=13, step_px=5, min_run_px=28, jitter_px=0.75, keep=0.82, phase_px=6, open_px=1, close_px=6)
hatch("forest_dark", forest_mask, 0.235, 88, spacing_px=8.5, step_px=5, min_run_px=18, jitter_px=0.55, keep=0.70, phase_px=1, open_px=1, close_px=4)

hatch("field_light", field_mask, 0.010, -13, spacing_px=11, step_px=6, min_run_px=86, jitter_px=0.65, keep=0.92, phase_px=3, open_px=0, close_px=11)
hatch("field_mid", field_mask, 0.080, 17, spacing_px=18, step_px=6, min_run_px=48, jitter_px=0.60, keep=0.58, phase_px=7, open_px=1, close_px=8)

hatch("grass_light", grass_mask, 0.018, -80, spacing_px=12, step_px=5, min_run_px=20, jitter_px=0.65, keep=0.76, phase_px=2, open_px=0, close_px=6)
hatch("grass_mid", grass_mask, 0.130, 76, spacing_px=15, step_px=5, min_run_px=16, jitter_px=0.65, keep=0.45, phase_px=6, open_px=1, close_px=4)

hatch("jacket_light", jacket_mask, 0.060, -52, spacing_px=8.2, step_px=4, min_run_px=22, jitter_px=0.65, keep=0.92, phase_px=0, open_px=1, close_px=5)
hatch("jacket_mid", jacket_mask, 0.130, 44, spacing_px=8.0, step_px=4, min_run_px=20, jitter_px=0.55, keep=0.86, phase_px=3, open_px=1, close_px=5)
hatch("jacket_dark", jacket_mask, 0.240, -74, spacing_px=6.8, step_px=4, min_run_px=17, jitter_px=0.45, keep=0.66, phase_px=1, open_px=1, close_px=4)

hatch("hair_shadow", hair_mask, 0.135, -72, spacing_px=14, step_px=4, min_run_px=28, jitter_px=0.45, keep=0.48, phase_px=2, open_px=1, close_px=5)

# Hand-controlled sky groups: keeps the reference-style light cloud texture without Canny trash.
def sky_cluster(cx, cy, rx, ry, angle_deg, count, length_frac, cross=False):
    rng = random.Random(int(cx * 13000 + cy * 17000 + angle_deg * 31 + count))
    theta = math.radians(angle_deg)
    e = np.array([math.cos(theta), math.sin(theta)], dtype=np.float32)
    p = np.array([-math.sin(theta), math.cos(theta)], dtype=np.float32)
    center = np.array([cx * w, cy * h], dtype=np.float32)
    for i in range(count):
        band = (i / max(1, count - 1) - 0.5) * 2.0
        off_p = band * ry * h * 0.70 + rng.uniform(-0.008, 0.008) * h
        off_e = rng.uniform(-0.50, 0.50) * rx * w
        mid = center + e * off_e + p * off_p
        if (((mid[0] / w - cx) / rx) ** 2 + ((mid[1] / h - cy) / ry) ** 2) > 1.1:
            continue
        seg_len = length_frac * w * rng.uniform(0.55, 1.02)
        pts = []
        for k in range(10):
            t = k / 9 - 0.5
            xy = mid + e * (t * seg_len) + p * (rng.uniform(-0.003, 0.003) * h + 0.004*h*math.sin((t+0.5)*math.pi))
            ex = ((xy[0] / w - cx) / rx) ** 2 + ((xy[1] / h - cy) / ry) ** 2
            if 0 <= xy[0] < w and 0 <= xy[1] < h and ex <= 1.18:
                pts.append((float(xy[0]), float(xy[1])))
        simplify_add("sky_cluster_cross" if cross else "sky_cluster", pts, eps=0.75, min_len_px=14.0)

for args in [
    (0.125, 0.095, 0.155, 0.052, -35, 26, 0.060, False),
    (0.150, 0.235, 0.180, 0.050, -26, 18, 0.055, False),
    (0.310, 0.125, 0.130, 0.048, -32, 15, 0.048, False),
    (0.505, 0.285, 0.135, 0.047, -22, 13, 0.045, False),
    (0.775, 0.175, 0.165, 0.055, -27, 21, 0.055, False),
    (0.825, 0.285, 0.150, 0.050, -25, 14, 0.050, False),
    (0.180, 0.270, 0.160, 0.040, 30, 7, 0.040, True),
    (0.790, 0.300, 0.145, 0.040, 28, 7, 0.039, True),
]:
    sky_cluster(*args)

# Hair flow strands and jacket folds are semantic, not random texture.
rng = random.Random(811)
for i in range(92):
    t = i / 91
    crown_x = (0.505 + 0.075 * (t - 0.5) + rng.uniform(-0.010, 0.010)) * w
    crown_y = (0.515 + 0.045 * math.sin(t * math.pi) + rng.uniform(-0.006, 0.008)) * h
    if i < 38:
        end_x = (0.410 + 0.145 * t + rng.uniform(-0.012, 0.012)) * w
        end_y = (0.735 + 0.030 * math.sin(t * 4.0) + rng.uniform(-0.012, 0.012)) * h
        c1 = ((0.440 + 0.06 * t) * w, (0.590 + rng.uniform(-0.015, 0.015)) * h)
        c2 = ((0.395 + 0.11 * t) * w, (0.690 + rng.uniform(-0.018, 0.018)) * h)
    else:
        tt = (i - 38) / 53
        end_x = (0.545 + 0.220 * tt + rng.uniform(-0.013, 0.013)) * w
        end_y = (0.700 + 0.080 * math.sin(tt * math.pi) + rng.uniform(-0.016, 0.016)) * h
        c1 = ((0.545 + 0.075 * tt) * w, (0.580 + rng.uniform(-0.016, 0.016)) * h)
        c2 = ((0.610 + 0.180 * tt) * w, (0.650 + rng.uniform(-0.018, 0.018)) * h)
    clip_add("hair_flow", bezier((crown_x, crown_y), c1, c2, (end_x, end_y), n=56), hair_mask, min_len_px=16)

for i in range(38):
    t = i / 37
    x0 = (0.475 + 0.105 * t + rng.uniform(-0.006, 0.006)) * w
    y0 = (0.535 + rng.uniform(-0.006, 0.008)) * h
    x3 = (0.460 + 0.145 * t + rng.uniform(-0.008, 0.008)) * w
    y3 = (0.740 + rng.uniform(-0.010, 0.010)) * h
    pts = bezier((x0, y0), ((0.495 + 0.06*t)*w, 0.600*h), ((0.465 + 0.13*t)*w, 0.690*h), (x3, y3), n=48)
    clip_add("hair_dark_strand", pts, hair_mask & (tone > 0.10), min_len_px=15)

for i in range(32):
    t = i / 31
    x0 = (0.325 + 0.235 * t + rng.uniform(-0.008, 0.008)) * w
    y0 = (0.690 + 0.035 * math.sin(t * math.pi) + rng.uniform(-0.006, 0.006)) * h
    x3 = (0.350 + 0.195 * t + rng.uniform(-0.010, 0.010)) * w
    y3 = (0.970 + rng.uniform(-0.008, 0.008)) * h
    pts = bezier((x0, y0), ((x0 + x3) / 2 - 0.05*w, 0.780*h), ((x0 + x3) / 2 + 0.03*w, 0.900*h), (x3, y3), n=46)
    clip_add("jacket_fold", pts, jacket_mask, min_len_px=18)

# Sparse grass / leaf accents, weighted by tone but capped so they remain accents.
for region_name, mask, count, angle_center, length_rng in [
    ("grass_blade", grass_mask & (tone > 0.070), 240, -82, (10, 27)),
    ("forest_leaf", forest_mask & (tone > 0.120), 160, 70, (8, 20)),
]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        continue
    weights = tone[ys, xs]
    weights = weights / max(float(weights.sum()), 1e-9)
    choice = np.random.choice(np.arange(len(xs)), size=min(count, len(xs)), replace=False, p=weights)
    for idx in choice:
        x = float(xs[idx]); y = float(ys[idx])
        local = float(tone[int(y), int(x)])
        length = random.uniform(*length_rng) * (0.60 + 0.75 * local)
        ang = math.radians(angle_center + random.uniform(-15, 15))
        dx = math.cos(ang) * length * 0.5
        dy = math.sin(ang) * length * 0.5
        add_path(region_name, [(x - dx, y - dy), (x + dx, y + dy)], min_len_px=7.0)

# Clean border.
margin_px = 18
add_path("outer_border", [(margin_px, margin_px), (w - margin_px, margin_px), (w - margin_px, h - margin_px), (margin_px, h - margin_px), (margin_px, margin_px)], min_len_px=10)

# Convert to machine coordinates.
def pix_to_mm(pt: tuple[float, float]) -> tuple[float, float]:
    x, y = pt
    return (x / w * DRAW_W_MM, -(TOP_MM + y / h * DRAW_H_MM))

mm_paths: list[tuple[str, list[tuple[float, float]]]] = []
for kind, pts in paths:
    mm = [pix_to_mm(p) for p in pts]
    cleaned = [mm[0]]
    length = 0.0
    for p in mm[1:]:
        last = cleaned[-1]
        d = math.hypot(p[0]-last[0], p[1]-last[1])
        if d >= 0.12:
            cleaned.append(p)
            length += d
    if len(cleaned) >= 2 and length >= 0.65:
        mm_paths.append((kind, cleaned))

# Greedy nearest-end ordering.
remaining = mm_paths[:]
ordered: list[tuple[str, list[tuple[float, float]]]] = []
pos = (0.0, 0.0)
while remaining:
    best_i = 0; best_rev = False; best_d = float("inf")
    for i, (_, pts) in enumerate(remaining):
        d0 = math.hypot(pts[0][0]-pos[0], pts[0][1]-pos[1])
        d1 = math.hypot(pts[-1][0]-pos[0], pts[-1][1]-pos[1])
        if d0 < best_d:
            best_i, best_rev, best_d = i, False, d0
        if d1 < best_d:
            best_i, best_rev, best_d = i, True, d1
    kind, pts = remaining.pop(best_i)
    if best_rev:
        pts = list(reversed(pts))
    ordered.append((kind, pts))
    pos = pts[-1]

name = "gemini_pencil_density_coherent_a4"
nc_path = OUT / f"{name}.nc"
gcode_path = OUT / f"{name}.gcode"
lines = ["; pencil density coherent A4", "G21", "G90", f"G0 Z{PEN_UP_Z:.3f}", f"F{TRAVEL_F}"]
draw_len = 0.0; travel_len = 0.0; last = (0.0, 0.0)
for kind, pts in ordered:
    start = pts[0]
    travel_len += math.hypot(start[0]-last[0], start[1]-last[1])
    lines.append(f"G0 X{start[0]:.3f} Y{start[1]:.3f}")
    lines.append(f"G1 Z{PEN_DOWN_Z:.3f} F{DRAW_F}")
    prev = start
    for x, y in pts[1:]:
        draw_len += math.hypot(x-prev[0], y-prev[1])
        lines.append(f"G1 X{x:.3f} Y{y:.3f}")
        prev = (x, y)
    lines.append(f"G0 Z{PEN_UP_Z:.3f}")
    last = pts[-1]
lines.append("M2")
text = "\n".join(lines) + "\n"
nc_path.write_text(text, encoding="ascii")
gcode_path.write_text(text, encoding="ascii")

# Render previews.
page_w = int(DRAW_W_MM * PX_PER_MM); page_h = int(SAFE_H_MM * PX_PER_MM)
def mm_to_px(p):
    return (int(round(p[0] * PX_PER_MM)), int(round((-p[1]) * PX_PER_MM)))

def render(path: Path, gray_mode: bool) -> None:
    im = Image.new("RGB", (page_w, page_h), "white")
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, page_w-1, page_h-1], outline=(225,225,225), width=1)
    for kind, pts in ordered:
        pix = [mm_to_px(p) for p in pts]
        if gray_mode:
            if kind in {"outer_border", "dark_contour", "hair_flow", "hair_dark_strand", "jacket_fold"}:
                col = (32,32,32)
            elif "dark" in kind or "jacket" in kind:
                col = (58,58,58)
            elif "mid" in kind or "forest" in kind:
                col = (86,86,86)
            elif "sky" in kind or "field_light" in kind:
                col = (150,150,150)
            else:
                col = (110,110,110)
        else:
            col = (0,0,0)
        dr.line(pix, fill=col, width=1)
    im.save(path)

black_png = OUT / f"{name}_preview_black_actual.png"
gray_png = OUT / f"{name}_preview_pressure_gray.png"
render(black_png, False)
render(gray_png, True)

def png_to_pdf(png: Path, pdf: Path) -> None:
    c = canvas.Canvas(str(pdf), pagesize=A4)
    pw, ph = A4; m = 16
    im = Image.open(png)
    sc = min((pw-2*m)/im.width, (ph-2*m)/im.height)
    dw = im.width*sc; dh = im.height*sc
    c.drawImage(str(png), (pw-dw)/2, (ph-dh)/2, dw, dh)
    c.showPage(); c.save()

black_pdf = OUT / f"{name}_preview_black_actual.pdf"
gray_pdf = OUT / f"{name}_preview_pressure_gray.pdf"
png_to_pdf(black_png, black_pdf)
png_to_pdf(gray_png, gray_pdf)

counts = Counter(kind for kind, _ in ordered)
readme = OUT / "README_result.txt"
readme.write_text(
    "PENCIL DENSITY COHERENT A4 package\n"
    f"source: {SRC}\n"
    f"nc: {nc_path}\n"
    f"gcode: {gcode_path}\n"
    f"preview_black_actual_png: {black_png}\n"
    f"preview_black_actual_pdf: {black_pdf}\n"
    f"preview_pressure_gray_png: {gray_png}\n"
    f"preview_pressure_gray_pdf: {gray_pdf}\n"
    f"paths_total: {len(ordered)}\n"
    f"kind_counts: {dict(counts)}\n"
    f"draw_length_m: {draw_len/1000:.2f}\n"
    f"travel_length_m: {travel_len/1000:.2f}\n"
    f"estimated_time_min_ideal: {(draw_len/(DRAW_F/60)+travel_len/(TRAVEL_F/60))/60:.1f}\n"
    "algorithm_note: darker areas receive close cross-hatching; light areas receive sparse long grouped strokes; weak edge noise is suppressed.\n",
    encoding="utf-8",
)
print("PENCIL DENSITY COHERENT A4 package")
print("paths_total:", len(ordered))
print("kind_counts:", dict(counts))
print("draw_length_m:", round(draw_len/1000, 2))
print("travel_length_m:", round(travel_len/1000, 2))
print("estimated_time_min_ideal:", round((draw_len/(DRAW_F/60)+travel_len/(TRAVEL_F/60))/60, 1))
print("preview:", black_png)
print("pdf:", black_pdf)
print("nc:", nc_path)

