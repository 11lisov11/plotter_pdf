from __future__ import annotations

from pathlib import Path
import math
import random
from collections import Counter

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from scipy.ndimage import gaussian_filter, binary_opening, binary_closing
from skimage.morphology import remove_small_objects, skeletonize

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_structured_grattage_maxdetail_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
random.seed(70931)
np.random.seed(70931)

DRAW_W_MM = 180.0
DRAW_H_MM = 240.0
TOP_MM = 20.0
SAFE_H_MM = 280.0
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0
TRAVEL_F = 3000
DRAW_F = 1200

img = Image.open(SRC).convert("L")
w0, h0 = img.size
# keep full source, including the fine outer border
work_w = 900
work_h = int(round(h0 * work_w / w0))
img = img.resize((work_w, work_h), Image.Resampling.LANCZOS)
w, h = img.size
gray = np.asarray(img, dtype=np.float32) / 255.0
# Pencil-paper normalization: remove slow paper gradient, keep drawing tone.
bg = gaussian_filter(gray, sigma=22)
flat = np.clip(gray / np.maximum(bg, 0.55), 0, 1)
flat = np.clip((flat - 0.05) / 0.95, 0, 1)
tone_raw = 1.0 - flat
# Smooth density map to avoid salt-and-pepper random noise.
tone = gaussian_filter(tone_raw, sigma=1.8)
tone = np.clip((tone - 0.015) / 0.36, 0, 1)
# A stronger tone map for silhouettes / very dark regions.
tone_strong = gaussian_filter(tone_raw, sigma=1.0)

yy, xx = np.mgrid[0:h, 0:w]
xn = xx / max(1, w - 1)
yn = yy / max(1, h - 1)

# Approximate subject masks. They are intentionally broad and smooth; textural density still comes from image tone.
hair_mask = ((((xn - 0.535) / 0.155) ** 2 + ((yn - 0.640) / 0.170) ** 2) < 1.0) | (
    (((xn - 0.630) / 0.170) ** 2 + ((yn - 0.655) / 0.120) ** 2) < 1.0
)
jacket_mask = ((((xn - 0.455) / 0.165) ** 2 + ((yn - 0.845) / 0.180) ** 2) < 1.0) | (
    (((xn - 0.365) / 0.105) ** 2 + ((yn - 0.785) / 0.105) ** 2) < 1.0
)
arm_mask = ((((xn - 0.365) / 0.105) ** 2 + ((yn - 0.725) / 0.080) ** 2) < 1.0)
figure_mask = hair_mask | jacket_mask | arm_mask
sky_mask = yn < 0.345
forest_mask = (yn > 0.315) & (yn < 0.535) & (~figure_mask)
field_mask = (yn > 0.455) & (yn < 0.815) & (~figure_mask)
grass_mask = (yn > 0.640) & (~figure_mask)

PathPts = list[tuple[float, float]]
paths: list[tuple[str, PathPts]] = []


def add_path(kind: str, pts: PathPts, min_len_px: float = 7.0) -> None:
    if len(pts) < 2:
        return
    length = 0.0
    last = pts[0]
    cleaned = [last]
    for p in pts[1:]:
        if math.hypot(p[0] - last[0], p[1] - last[1]) >= 0.7:
            cleaned.append(p)
            length += math.hypot(p[0] - last[0], p[1] - last[1])
            last = p
    if len(cleaned) >= 2 and length >= min_len_px:
        paths.append((kind, cleaned))


def add_polyline_simplified(kind: str, pts: PathPts, eps: float = 1.1, min_len_px: float = 9.0) -> None:
    if len(pts) < 2:
        return
    arr = np.array(pts, dtype=np.float32).reshape((-1, 1, 2))
    approx = cv2.approxPolyDP(arr, epsilon=eps, closed=False).reshape((-1, 2))
    add_path(kind, [(float(x), float(y)) for x, y in approx], min_len_px=min_len_px)


def hatch_layer(kind: str, mask: np.ndarray, threshold: float, angle_deg: float, spacing: float, step: float,
                min_run: float, jitter: float = 0.0, keep: float = 1.0, phase: float = 0.0) -> None:
    theta = math.radians(angle_deg)
    e = np.array([math.cos(theta), math.sin(theta)], dtype=np.float32)
    p = np.array([-math.sin(theta), math.cos(theta)], dtype=np.float32)
    center = np.array([w / 2.0, h / 2.0], dtype=np.float32)
    diag = math.hypot(w, h)
    line_count = int(diag / spacing) + 4
    u_values = np.arange(-diag / 2 - 20, diag / 2 + 20, step, dtype=np.float32)
    active = mask & (tone >= threshold)
    rng = random.Random(1000 + int(angle_deg * 13) + int(threshold * 1000) + int(spacing * 10))
    for i in range(-line_count // 2, line_count // 2 + 1):
        if rng.random() > keep:
            continue
        v = i * spacing + phase
        raw_pts: PathPts = []
        for ui, uval in enumerate(u_values):
            xy = center + e * uval + p * v
            x = int(round(float(xy[0])))
            y = int(round(float(xy[1])))
            if 0 <= x < w and 0 <= y < h and active[y, x]:
                # soft wobble, shared along the line: makes it pencil-like but not noisy.
                wob = jitter * math.sin(0.045 * uval + 0.9 * i) + 0.35 * jitter * math.sin(0.017 * uval + phase)
                pt = xy + p * wob
                raw_pts.append((float(pt[0]), float(pt[1])))
            else:
                if len(raw_pts) * step >= min_run:
                    add_polyline_simplified(kind, raw_pts, eps=1.0, min_len_px=min_run * 0.75)
                raw_pts = []
        if len(raw_pts) * step >= min_run:
            add_polyline_simplified(kind, raw_pts, eps=1.0, min_len_px=min_run * 0.75)


def bezier(p0, p1, p2, p3, n=42):
    pts = []
    for i in range(n):
        t = i / (n - 1)
        a = (1 - t) ** 3
        b = 3 * (1 - t) ** 2 * t
        c = 3 * (1 - t) * t ** 2
        d = t ** 3
        x = a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0]
        y = a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]
        pts.append((x, y))
    return pts


def clip_by_mask(kind: str, pts: PathPts, mask: np.ndarray, min_len_px: float = 11.0) -> None:
    run: PathPts = []
    for x, y in pts:
        ix, iy = int(round(x)), int(round(y))
        if 0 <= ix < w and 0 <= iy < h and mask[iy, ix]:
            run.append((x, y))
        else:
            if run:
                add_polyline_simplified(kind, run, eps=0.9, min_len_px=min_len_px)
            run = []
    if run:
        add_polyline_simplified(kind, run, eps=0.9, min_len_px=min_len_px)

# 1) Long clean contours from real image, but denoised and component-filtered.
binary = tone_strong > 0.112
binary = binary_closing(binary, structure=np.ones((2, 2), dtype=bool))
binary = remove_small_objects(binary, min_size=18)
skel = skeletonize(binary).astype(np.uint8) * 255
contours, _ = cv2.findContours(skel, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
for cnt in contours:
    if len(cnt) < 8:
        continue
    pts = [(float(p[0][0]), float(p[0][1])) for p in cnt]
    x, y, ww, hh = cv2.boundingRect(cnt)
    arc = cv2.arcLength(cnt, False)
    if arc < 15 or ww < 3 or hh < 3:
        continue
    # Suppress tiny texture crumbs in bright paper/sky; keep longer useful contours.
    local_dark = float(np.mean(tone[max(0, y):min(h, y + hh), max(0, x):min(w, x + ww)]))
    if local_dark < 0.060 and arc < 48:
        continue
    add_polyline_simplified("source_contour", pts, eps=1.15, min_len_px=12.0)


# Extra long light contours for clouds, hillside and hair boundaries. Kept only when long enough, so it does not become sand-noise.
edge_img = np.clip(flat * 255.0, 0, 255).astype(np.uint8)
edges = cv2.Canny(edge_img, 46, 122, apertureSize=3, L2gradient=True)
edges = cv2.dilate(edges, np.ones((2, 2), dtype=np.uint8), iterations=1)
edges = cv2.erode(edges, np.ones((2, 2), dtype=np.uint8), iterations=1)
edge_contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
for cnt in edge_contours:
    if len(cnt) < 14:
        continue
    x, y, ww, hh = cv2.boundingRect(cnt)
    arc = cv2.arcLength(cnt, False)
    if arc < 36 or ww < 5 or hh < 3:
        continue
    local = float(np.mean(tone[max(0, y):min(h, y + hh), max(0, x):min(w, x + ww)]))
    # In sky/field allow only genuinely long contours; in subject allow shorter useful edges.
    ymid = (y + 0.5 * hh) / h
    if local < 0.030 and arc < 95:
        continue
    if ymid < 0.38 and arc < 70:
        continue
    pts = [(float(p[0][0]), float(p[0][1])) for p in cnt]
    add_polyline_simplified("light_contour", pts, eps=1.45, min_len_px=22.0)
# 2) Region hatching: fewer random marks, longer coherent strokes.
# Sky: very sparse, only where the source actually has cloud tone.
hatch_layer("sky_soft", sky_mask, 0.052, -25, spacing=21, step=6, min_run=34, jitter=0.9, keep=0.82, phase=3)
hatch_layer("sky_cross", sky_mask, 0.105, 28, spacing=28, step=6, min_run=30, jitter=0.7, keep=0.62, phase=9)
# Forest: dense dark tree band, but grouped by two consistent diagonal families plus vertical accents.
hatch_layer("forest_main", forest_mask, 0.105, -62, spacing=10, step=5, min_run=22, jitter=1.0, keep=0.96, phase=1)
hatch_layer("forest_cross", forest_mask, 0.165, 58, spacing=11, step=5, min_run=20, jitter=0.9, keep=0.88, phase=5)
hatch_layer("forest_dark", forest_mask, 0.245, 88, spacing=8, step=5, min_run=16, jitter=0.7, keep=0.82, phase=2)
# Field: long slope-following strokes, not random scratch noise.
hatch_layer("field_slope", field_mask, 0.035, -13, spacing=9.5, step=6, min_run=52, jitter=0.8, keep=0.96, phase=4)
hatch_layer("field_cross", field_mask, 0.090, 17, spacing=15, step=6, min_run=38, jitter=0.7, keep=0.70, phase=7)
# Grass lower zone: controlled clumps, only where tone supports it.
hatch_layer("grass_base", grass_mask, 0.052, -82, spacing=10, step=5, min_run=16, jitter=0.9, keep=0.86, phase=2)
hatch_layer("grass_cross", grass_mask, 0.105, 76, spacing=13, step=5, min_run=15, jitter=0.8, keep=0.66, phase=6)
# Jacket: dark areas get very close hatch/crosshatch, preserving the dense body mass.
hatch_layer("jacket_a", jacket_mask, 0.070, -52, spacing=7, step=4, min_run=22, jitter=0.8, keep=1.0, phase=0)
hatch_layer("jacket_b", jacket_mask, 0.135, 44, spacing=7, step=4, min_run=20, jitter=0.75, keep=0.96, phase=3)
hatch_layer("jacket_dark", jacket_mask, 0.230, -72, spacing=5.5, step=4, min_run=16, jitter=0.6, keep=0.9, phase=1)
# Hair shadow under-strokes: fewer than before; long flow lines will define hair.
hatch_layer("hair_shadow_soft", hair_mask, 0.150, -72, spacing=13, step=4, min_run=25, jitter=0.55, keep=0.68, phase=2)

# 3) Hair flow: deliberate long strands following the visible shape.
rng = random.Random(811)
for i in range(86):
    t = i / 85
    crown_x = (0.505 + 0.075 * (t - 0.5) + rng.uniform(-0.010, 0.010)) * w
    crown_y = (0.515 + 0.045 * math.sin(t * math.pi) + rng.uniform(-0.006, 0.008)) * h
    # two fans: left/back and right/long flowing hair
    if i < 36:
        end_x = (0.410 + 0.145 * t + rng.uniform(-0.012, 0.012)) * w
        end_y = (0.735 + 0.030 * math.sin(t * 4.0) + rng.uniform(-0.012, 0.012)) * h
        c1 = ((0.440 + 0.06 * t) * w, (0.590 + rng.uniform(-0.015, 0.015)) * h)
        c2 = ((0.395 + 0.11 * t) * w, (0.690 + rng.uniform(-0.018, 0.018)) * h)
    else:
        tt = (i - 36) / 49
        end_x = (0.545 + 0.220 * tt + rng.uniform(-0.013, 0.013)) * w
        end_y = (0.700 + 0.080 * math.sin(tt * math.pi) + rng.uniform(-0.016, 0.016)) * h
        c1 = ((0.545 + 0.075 * tt) * w, (0.580 + rng.uniform(-0.016, 0.016)) * h)
        c2 = ((0.610 + 0.180 * tt) * w, (0.650 + rng.uniform(-0.018, 0.018)) * h)
    pts = bezier((crown_x, crown_y), c1, c2, (end_x, end_y), n=54)
    clip_by_mask("hair_flow", pts, hair_mask, min_len_px=16)

# Hair dark accent ribbons, close parallel lines around center/back.
for i in range(34):
    t = i / 33
    x0 = (0.475 + 0.105 * t + rng.uniform(-0.006, 0.006)) * w
    y0 = (0.535 + rng.uniform(-0.006, 0.008)) * h
    x3 = (0.460 + 0.145 * t + rng.uniform(-0.008, 0.008)) * w
    y3 = (0.740 + rng.uniform(-0.010, 0.010)) * h
    pts = bezier((x0, y0), ((0.495 + 0.06*t)*w, 0.600*h), ((0.465 + 0.13*t)*w, 0.690*h), (x3, y3), n=46)
    clip_by_mask("hair_dark_strand", pts, hair_mask & (tone > 0.11), min_len_px=15)

# 4) Jacket folds: long folds instead of only crosshatch.
for i in range(30):
    t = i / 29
    x0 = (0.325 + 0.235 * t + rng.uniform(-0.008, 0.008)) * w
    y0 = (0.690 + 0.035 * math.sin(t * math.pi) + rng.uniform(-0.006, 0.006)) * h
    x3 = (0.350 + 0.195 * t + rng.uniform(-0.010, 0.010)) * w
    y3 = (0.970 + rng.uniform(-0.008, 0.008)) * h
    pts = bezier((x0, y0), ((x0 + x3) / 2 - 0.05*w, 0.780*h), ((x0 + x3) / 2 + 0.03*w, 0.900*h), (x3, y3), n=44)
    clip_by_mask("jacket_fold", pts, jacket_mask, min_len_px=18)

# 5) Sparse hand/grass gesture strokes. Deterministic, density-gated, but longer than noise.
for region_name, mask, count, angle_center, length_rng in [
    ("grass_blade", grass_mask & (tone > 0.080), 260, -82, (10, 26)),
    ("forest_leaf", forest_mask & (tone > 0.120), 210, 70, (8, 20)),
]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        continue
    weights = tone[ys, xs]
    weights = weights / max(weights.sum(), 1e-9)
    choice = np.random.choice(np.arange(len(xs)), size=min(count, len(xs)), replace=False, p=weights)
    for idx in choice:
        x = float(xs[idx]); y = float(ys[idx])
        local = float(tone[int(y), int(x)])
        length = random.uniform(*length_rng) * (0.65 + 0.8 * local)
        ang = math.radians(angle_center + random.uniform(-16, 16))
        dx = math.cos(ang) * length * 0.5
        dy = math.sin(ang) * length * 0.5
        pts = [(x - dx, y - dy), (x + dx, y + dy)]
        add_path(region_name, pts, min_len_px=7.0)

# 6) Fixed clean border from the drawing, like the reference page.
margin_px = 18
border = [(margin_px, margin_px), (w - margin_px, margin_px), (w - margin_px, h - margin_px), (margin_px, h - margin_px), (margin_px, margin_px)]
add_path("outer_border", border, min_len_px=10.0)

# Convert to millimeters.
def pix_to_mm(pt: tuple[float, float]) -> tuple[float, float]:
    x, y = pt
    return (x / w * DRAW_W_MM, -(TOP_MM + y / h * DRAW_H_MM))

mm_paths: list[tuple[str, list[tuple[float, float]]]] = []
for kind, pts in paths:
    mm = [pix_to_mm(p) for p in pts]
    # De-duplicate immediate points and discard negligible paths.
    cleaned = [mm[0]]
    length = 0.0
    for p in mm[1:]:
        last = cleaned[-1]
        d = math.hypot(p[0] - last[0], p[1] - last[1])
        if d >= 0.12:
            cleaned.append(p)
            length += d
    if len(cleaned) >= 2 and length >= 0.65:
        mm_paths.append((kind, cleaned))

# Nearest-end ordering to reduce wasted air moves.
remaining = mm_paths[:]
ordered: list[tuple[str, list[tuple[float, float]]]] = []
pos = (0.0, 0.0)
while remaining:
    best_i = 0
    best_rev = False
    best_d = float("inf")
    # Full greedy is fine for a few thousand paths.
    for i, (_, pts) in enumerate(remaining):
        d0 = math.hypot(pts[0][0] - pos[0], pts[0][1] - pos[1])
        d1 = math.hypot(pts[-1][0] - pos[0], pts[-1][1] - pos[1])
        if d0 < best_d:
            best_i, best_rev, best_d = i, False, d0
        if d1 < best_d:
            best_i, best_rev, best_d = i, True, d1
    kind, pts = remaining.pop(best_i)
    if best_rev:
        pts = list(reversed(pts))
    ordered.append((kind, pts))
    pos = pts[-1]

# Save G-code / NC.
name = "gemini_structured_grattage_maxdetail_a4"
nc_path = OUT / f"{name}.nc"
gcode_path = OUT / f"{name}.gcode"
lines = [
    "; structured grattage maxdetail A4 - coherent density hatching",
    "G21",
    "G90",
    f"G0 Z{PEN_UP_Z:.3f}",
    f"F{TRAVEL_F}",
]
draw_len = 0.0
travel_len = 0.0
last_pos = (0.0, 0.0)
for kind, pts in ordered:
    start = pts[0]
    travel_len += math.hypot(start[0] - last_pos[0], start[1] - last_pos[1])
    lines.append(f"G0 X{start[0]:.3f} Y{start[1]:.3f}")
    lines.append(f"G1 Z{PEN_DOWN_Z:.3f} F{DRAW_F}")
    prev = start
    for x, y in pts[1:]:
        draw_len += math.hypot(x - prev[0], y - prev[1])
        lines.append(f"G1 X{x:.3f} Y{y:.3f}")
        prev = (x, y)
    lines.append(f"G0 Z{PEN_UP_Z:.3f}")
    last_pos = pts[-1]
lines.append("M2")
text = "\n".join(lines) + "\n"
nc_path.write_text(text, encoding="ascii")
gcode_path.write_text(text, encoding="ascii")

# Render preview. Black = actual plotter lines. Gray = pressure-like readability preview only.
PX_PER_MM = 4
page_w = int(DRAW_W_MM * PX_PER_MM)
page_h = int(SAFE_H_MM * PX_PER_MM)

def mm_to_preview(p):
    x, y = p
    return (int(round(x * PX_PER_MM)), int(round((-y) * PX_PER_MM)))

def render(path: Path, gray_mode: bool = False) -> None:
    im = Image.new("RGB", (page_w, page_h), "white")
    dr = ImageDraw.Draw(im)
    # light sheet/workspace border
    dr.rectangle([0, 0, page_w - 1, page_h - 1], outline=(225, 225, 225), width=1)
    for kind, pts in ordered:
        pix = [mm_to_preview(p) for p in pts]
        if len(pix) < 2:
            continue
        if gray_mode:
            if kind in ("outer_border", "source_contour", "hair_flow", "hair_dark_strand", "jacket_fold"):
                col = (38, 38, 38)
            elif "dark" in kind or "jacket" in kind:
                col = (62, 62, 62)
            elif "sky" in kind or "field" in kind:
                col = (145, 145, 145)
            else:
                col = (92, 92, 92)
        else:
            col = (0, 0, 0)
        dr.line(pix, fill=col, width=1, joint="curve")
    im.save(path)

black_png = OUT / f"{name}_preview_black_actual.png"
gray_png = OUT / f"{name}_preview_pressure_gray.png"
render(black_png, gray_mode=False)
render(gray_png, gray_mode=True)

# PDF previews embed PNG, stable and easy to open.
def png_to_pdf(png: Path, pdf: Path) -> None:
    c = canvas.Canvas(str(pdf), pagesize=A4)
    pw, ph = A4
    m = 16
    im = Image.open(png)
    sc = min((pw - 2 * m) / im.width, (ph - 2 * m) / im.height)
    dw = im.width * sc
    dh = im.height * sc
    c.drawImage(str(png), (pw - dw) / 2, (ph - dh) / 2, dw, dh)
    c.showPage()
    c.save()

black_pdf = OUT / f"{name}_preview_black_actual.pdf"
gray_pdf = OUT / f"{name}_preview_pressure_gray.pdf"
png_to_pdf(black_png, black_pdf)
png_to_pdf(gray_png, gray_pdf)

counts = Counter(kind for kind, _ in ordered)
readme = OUT / "README_result.txt"
readme.write_text(
    "STRUCTURED GRATTAGE MAXDETAIL A4 package\n"
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
    f"estimated_time_min_ideal: {(draw_len/(1200/60)+travel_len/(3000/60))/60:.1f}\n"
    "algorithm_note: coherent region hatch layers; dark zones get close multi-angle passes, light zones sparse long passes; isolated short noise suppressed.\n",
    encoding="utf-8",
)

print("STRUCTURED GRATTAGE MAXDETAIL A4 package")
print("paths_total:", len(ordered))
print("kind_counts:", dict(counts))
print("draw_length_m:", round(draw_len/1000, 2))
print("travel_length_m:", round(travel_len/1000, 2))
print("estimated_time_min_ideal:", round((draw_len/(1200/60)+travel_len/(3000/60))/60, 1))
print("preview:", black_png)
print("pdf:", black_pdf)
print("nc:", nc_path)

