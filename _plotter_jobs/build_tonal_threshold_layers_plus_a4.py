from __future__ import annotations
from pathlib import Path
import math, random
from collections import Counter

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from scipy.ndimage import gaussian_filter, binary_closing, binary_opening
from skimage.morphology import remove_small_objects, skeletonize

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tonal_threshold_layers_plus_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
random.seed(2026062207)
np.random.seed(2026062207)

DW, DH, TOP, SAFE = 180.0, 240.0, 20.0, 280.0
UP, DOWN, TF, DF = 3.5, 0.0, 3000, 1200
PPM = 4

img0 = Image.open(SRC).convert("L")
W = 920
H = round(img0.size[1] * W / img0.size[0])
img = img0.resize((W, H), Image.Resampling.LANCZOS)
w, h = img.size
gray = np.asarray(img, dtype=np.float32) / 255.0
bg = gaussian_filter(gray, 30)
flat = np.clip(gray / np.maximum(bg, 0.58), 0, 1)
flat = np.clip((flat - 0.04) / 0.96, 0, 1)
tone_raw = 1.0 - flat
tone = np.clip((gaussian_filter(tone_raw, 2.1) - 0.016) / 0.37, 0, 1)
tone_dark = gaussian_filter(tone_raw, 0.85)

yy, xx = np.mgrid[0:h, 0:w]
xn = xx / (w - 1)
yn = yy / (h - 1)
hair = ((((xn - .535) / .155) ** 2 + ((yn - .640) / .170) ** 2) < 1) | ((((xn - .635) / .185) ** 2 + ((yn - .660) / .120) ** 2) < 1)
jacket = ((((xn - .455) / .170) ** 2 + ((yn - .845) / .185) ** 2) < 1) | ((((xn - .365) / .110) ** 2 + ((yn - .785) / .110) ** 2) < 1)
arm = ((((xn - .365) / .105) ** 2 + ((yn - .725) / .085) ** 2) < 1)
fig = hair | jacket | arm
sky = yn < .330
forest = (yn > .310) & (yn < .525) & (~fig)
field = (yn > .440) & (yn < .790) & (~fig)
grass = (yn > .635) & (~fig)

paths: list[tuple[str, list[tuple[float, float]]]] = []

def add(kind, pts, min_len=7.0):
    if len(pts) < 2:
        return
    clean = [pts[0]]
    length = 0.0
    last = pts[0]
    for p in pts[1:]:
        d = math.hypot(p[0] - last[0], p[1] - last[1])
        if d >= 0.7:
            clean.append(p)
            length += d
            last = p
    if len(clean) >= 2 and length >= min_len:
        paths.append((kind, clean))

def simp(kind, pts, eps=.9, min_len=7.0):
    if len(pts) < 2:
        return
    a = np.array(pts, dtype=np.float32).reshape((-1, 1, 2))
    ap = cv2.approxPolyDP(a, eps, False).reshape((-1, 2))
    add(kind, [(float(x), float(y)) for x, y in ap], min_len)

def clip_run(kind, pts, mask, min_len=7.0):
    run = []
    for x, y in pts:
        ix, iy = int(round(x)), int(round(y))
        if 0 <= ix < w and 0 <= iy < h and mask[iy, ix]:
            run.append((x, y))
        else:
            if run:
                simp(kind, run, .85, min_len)
            run = []
    if run:
        simp(kind, run, .85, min_len)

def active_mask(mask, thr, close=5, open_=1):
    a = mask & (tone >= thr)
    if close:
        a = binary_closing(a, np.ones((close, close), bool))
    if open_:
        a = binary_opening(a, np.ones((open_, open_), bool))
    a = remove_small_objects(a, min_size=30)
    return a

def broken_hatch(kind, mask, thr, angle_deg, spacing, step, min_run, chunk_rng, keep, jitter, phase=0, close=5, seed=0):
    active = active_mask(mask, thr, close=close)
    rng = random.Random(seed + int(angle_deg * 19) + int(thr * 1000))
    th = math.radians(angle_deg)
    e = np.array([math.cos(th), math.sin(th)], dtype=np.float32)
    p = np.array([-math.sin(th), math.cos(th)], dtype=np.float32)
    center = np.array([w / 2, h / 2], dtype=np.float32)
    diag = math.hypot(w, h)
    us = np.arange(-diag / 2 - 30, diag / 2 + 30, step, dtype=np.float32)
    nlines = int(diag / spacing) + 8
    for i in range(-nlines // 2, nlines // 2 + 1):
        if rng.random() > keep:
            continue
        v = i * spacing + phase
        current = []
        quota = rng.uniform(*chunk_rng)
        drawn = 0.0
        gap = 0.0
        for u in us:
            xy = center + e * u + p * v
            x, y = int(round(float(xy[0]))), int(round(float(xy[1])))
            ok = 0 <= x < w and 0 <= y < h and active[y, x]
            if ok and gap <= 0:
                wob = jitter * (0.65 * math.sin(.031 * u + .47 * i) + .35 * math.sin(.013 * u + phase))
                pt = xy + p * wob
                current.append((float(pt[0]), float(pt[1])))
                drawn += step
                if drawn >= quota:
                    if len(current) * step >= min_run:
                        simp(kind, current, .95, min_run * .70)
                    current = []
                    drawn = 0
                    quota = rng.uniform(*chunk_rng)
                    gap = rng.uniform(step * 1.5, step * 5.0)
            else:
                if len(current) * step >= min_run:
                    simp(kind, current, .95, min_run * .70)
                current = []
                drawn = 0
                if gap > 0:
                    gap -= step
        if len(current) * step >= min_run:
            simp(kind, current, .95, min_run * .70)

# Filtered dark contours only, used as structure anchors.
b = tone_dark > .165
b = binary_closing(b, np.ones((2, 2), bool))
b = remove_small_objects(b, min_size=38)
sk = skeletonize(b).astype(np.uint8) * 255
contours, _ = cv2.findContours(sk, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
for c in contours:
    if len(c) < 10:
        continue
    x, y, ww, hh = cv2.boundingRect(c)
    arc = cv2.arcLength(c, False)
    if arc < 22 or ww < 3 or hh < 3:
        continue
    local = float(tone[y:min(h, y + hh), x:min(w, x + ww)].mean())
    ymid = (y + .5 * hh) / h
    if ymid < .33 and (arc < 78 or local < .15):
        continue
    if local < .09 and arc < 65:
        continue
    simp("dark_contour", [(float(p[0][0]), float(p[0][1])) for p in c], 1.15, 14)

# Tonal threshold layers: dark adds closer/more crossed chunks, light remains sparse.
broken_hatch("sky_light", sky, .070, -28, 30, 6, 34, (24, 62), .42, .8, phase=3, close=7, seed=10)
broken_hatch("sky_cross", sky, .150, 30, 38, 6, 28, (18, 42), .22, .6, phase=9, close=6, seed=11)

broken_hatch("forest_light", forest, .050, -62, 16, 5, 22, (18, 46), .82, .85, phase=2, close=6, seed=20)
broken_hatch("forest_mid", forest, .125, 56, 12, 5, 18, (14, 36), .86, .72, phase=6, close=5, seed=21)
broken_hatch("forest_dark", forest, .220, 86, 8.8, 5, 14, (11, 28), .78, .50, phase=1, close=4, seed=22)
broken_hatch("forest_deep", forest, .290, -70, 7.5, 4, 12, (9, 22), .60, .40, phase=4, close=3, seed=23)

broken_hatch("field_light", field, .052, -13, 15, 6, 42, (42, 100), .68, .55, phase=4, close=8, seed=30)
broken_hatch("field_mid", field, .135, 16, 20, 6, 30, (28, 66), .48, .45, phase=7, close=6, seed=31)

broken_hatch("grass_light", grass, .075, -80, 15, 5, 14, (12, 32), .55, .60, phase=2, close=4, seed=40)
broken_hatch("grass_mid", grass, .150, 75, 14, 5, 12, (10, 27), .44, .50, phase=5, close=4, seed=41)

broken_hatch("jacket_light", jacket, .060, -52, 8.8, 4, 17, (20, 46), .86, .42, phase=0, close=5, seed=50)
broken_hatch("jacket_mid", jacket, .132, 44, 8.6, 4, 16, (18, 42), .84, .40, phase=3, close=5, seed=51)
broken_hatch("jacket_dark", jacket, .235, -74, 7.8, 4, 14, (15, 34), .64, .32, phase=1, close=4, seed=52)

broken_hatch("hair_shadow", hair, .145, -72, 14, 4, 18, (18, 44), .46, .32, phase=2, close=5, seed=60)

# Semantic long hair and jacket folds.
def bez(p0, p1, p2, p3, n=54):
    pts = []
    for i in range(n):
        t = i / (n - 1)
        pts.append(((1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t*t*p2[0] + t**3*p3[0],
                    (1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] + 3*(1-t)*t*t*p2[1] + t**3*p3[1]))
    return pts
rng = random.Random(811)
for i in range(96):
    t = i / 95
    crown = ((.505 + .075 * (t - .5) + rng.uniform(-.010, .010)) * w, (.515 + .045 * math.sin(t * math.pi) + rng.uniform(-.006, .008)) * h)
    if i < 40:
        end = ((.410 + .145 * t + rng.uniform(-.012, .012)) * w, (.735 + .030 * math.sin(t * 4) + rng.uniform(-.012, .012)) * h)
        c1 = ((.440 + .06 * t) * w, (.590 + rng.uniform(-.015, .015)) * h)
        c2 = ((.395 + .11 * t) * w, (.690 + rng.uniform(-.018, .018)) * h)
    else:
        tt = (i - 40) / 55
        end = ((.545 + .220 * tt + rng.uniform(-.013, .013)) * w, (.700 + .080 * math.sin(tt * math.pi) + rng.uniform(-.016, .016)) * h)
        c1 = ((.545 + .075 * tt) * w, (.580 + rng.uniform(-.016, .016)) * h)
        c2 = ((.610 + .180 * tt) * w, (.650 + rng.uniform(-.018, .018)) * h)
    clip_run("hair_flow", bez(crown, c1, c2, end, 58), hair, 16)
for i in range(32):
    t = i / 31
    x0 = (.325 + .235 * t + rng.uniform(-.008, .008)) * w
    y0 = (.690 + .035 * math.sin(t * math.pi) + rng.uniform(-.006, .006)) * h
    x3 = (.350 + .195 * t + rng.uniform(-.010, .010)) * w
    y3 = (.970 + rng.uniform(-.008, .008)) * h
    clip_run("jacket_fold", bez((x0, y0), ((x0+x3)/2 - .05*w, .780*h), ((x0+x3)/2 + .03*w, .900*h), (x3, y3), 46), jacket, 18)

# Hand sky clusters, sparse and deliberate.
def skycl(cx, cy, rx, ry, ang, cnt, lf, cross=False):
    sr = random.Random(int(cx * 13000 + cy * 17000 + cnt * 37))
    a = math.radians(ang); e = (math.cos(a), math.sin(a)); p = (-math.sin(a), math.cos(a))
    for i in range(cnt):
        band = (i / max(1, cnt - 1) - .5) * 2
        op = band * ry * h * .7 + sr.uniform(-.008, .008) * h
        oe = sr.uniform(-.5, .5) * rx * w
        x = cx*w + e[0]*oe + p[0]*op
        y = cy*h + e[1]*oe + p[1]*op
        if (((x/w - cx)/rx)**2 + ((y/h - cy)/ry)**2) > 1.08:
            continue
        ln = lf*w*sr.uniform(.55, 1.02)
        pts = []
        for k in range(8):
            t = k/7 - .5
            pts.append((x + e[0]*ln*t + p[0]*sr.uniform(-1.2, 1.2), y + e[1]*ln*t + p[1]*sr.uniform(-1.2, 1.2)))
        simp("sky_cluster_cross" if cross else "sky_cluster", pts, .7, 13)
for args in [(0.125,.095,.155,.052,-35,20,.054,False),(0.150,.235,.180,.050,-26,13,.048,False),(0.310,.125,.130,.048,-32,10,.043,False),(0.505,.285,.135,.047,-22,8,.040,False),(0.775,.175,.165,.055,-27,16,.048,False),(0.825,.285,.150,.050,-25,10,.044,False),(0.180,.270,.160,.040,30,4,.035,True),(0.790,.300,.145,.040,28,4,.034,True)]:
    skycl(*args)

# Border.
m = 18
add("outer_border", [(m,m),(w-m,m),(w-m,h-m),(m,h-m),(m,m)], 10)

# Convert/order/write/render.
def p2m(p): return (p[0] / w * DW, -(TOP + p[1] / h * DH))
mm = []
for kind, pts in paths:
    arr = [p2m(p) for p in pts]
    clean = [arr[0]]; length = 0.0
    for p in arr[1:]:
        d = math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1])
        if d >= .12:
            clean.append(p); length += d
    if len(clean) >= 2 and length >= .6:
        mm.append((kind, clean))
rem = mm[:]
ordered = []
pos = (0.0, 0.0)
while rem:
    bi = 0; br = False; bd = 1e9
    for i, (_, pts) in enumerate(rem):
        d0 = math.hypot(pts[0][0] - pos[0], pts[0][1] - pos[1])
        d1 = math.hypot(pts[-1][0] - pos[0], pts[-1][1] - pos[1])
        if d0 < bd: bi = i; br = False; bd = d0
        if d1 < bd: bi = i; br = True; bd = d1
    kind, pts = rem.pop(bi)
    if br: pts = list(reversed(pts))
    ordered.append((kind, pts)); pos = pts[-1]

name = "gemini_tonal_threshold_layers_plus_a4"
nc = OUT / f"{name}.nc"
gcode = OUT / f"{name}.gcode"
lines = ["; tonal threshold layers plus A4", "G21", "G90", f"G0 Z{UP:.3f}", f"F{TF}"]
draw = travel = 0.0
last = (0.0, 0.0)
for kind, pts in ordered:
    st = pts[0]
    travel += math.hypot(st[0] - last[0], st[1] - last[1])
    lines += [f"G0 X{st[0]:.3f} Y{st[1]:.3f}", f"G1 Z{DOWN:.3f} F{DF}"]
    prev = st
    for x, y in pts[1:]:
        draw += math.hypot(x - prev[0], y - prev[1])
        lines.append(f"G1 X{x:.3f} Y{y:.3f}")
        prev = (x, y)
    lines.append(f"G0 Z{UP:.3f}")
    last = pts[-1]
lines.append("M2")
text = "\n".join(lines) + "\n"
nc.write_text(text, encoding="ascii")
gcode.write_text(text, encoding="ascii")

def mm2px(p): return (round(p[0] * PPM), round(-p[1] * PPM))
def render(path, gray=False):
    out = Image.new("RGB", (round(DW * PPM), round(SAFE * PPM)), "white")
    dr = ImageDraw.Draw(out)
    dr.rectangle([0, 0, out.width - 1, out.height - 1], outline=(225,225,225))
    for kind, pts in ordered:
        if gray:
            col = (32,32,32) if ("dark" in kind or kind in {"outer_border","hair_flow","jacket_fold","dark_contour"}) else (80,80,80) if ("forest" in kind or "jacket" in kind or "hair" in kind) else (132,132,132)
        else:
            col = (0,0,0)
        dr.line([mm2px(p) for p in pts], fill=col, width=1)
    out.save(path)
black = OUT / f"{name}_preview_black_actual.png"
grayp = OUT / f"{name}_preview_pressure_gray.png"
render(black, False); render(grayp, True)
def make_pdf(png, pdfp):
    c = canvas.Canvas(str(pdfp), pagesize=A4)
    pw, ph = A4; mar = 16
    im = Image.open(png)
    sc = min((pw - 2*mar) / im.width, (ph - 2*mar) / im.height)
    c.drawImage(str(png), (pw - im.width*sc)/2, (ph - im.height*sc)/2, im.width*sc, im.height*sc)
    c.showPage(); c.save()
blackpdf = OUT / f"{name}_preview_black_actual.pdf"
graypdf = OUT / f"{name}_preview_pressure_gray.pdf"
make_pdf(black, blackpdf); make_pdf(grayp, graypdf)
counts = Counter(k for k,_ in ordered)
(OUT / "README_result.txt").write_text(
    "TONAL THRESHOLD LAYERS PLUS A4 package\n" +
    f"source: {SRC}\n" + f"nc: {nc}\n" + f"gcode: {gcode}\n" +
    f"preview_black_actual_png: {black}\n" + f"preview_black_actual_pdf: {blackpdf}\n" +
    f"preview_pressure_gray_png: {grayp}\n" + f"preview_pressure_gray_pdf: {graypdf}\n" +
    f"paths_total: {len(ordered)}\n" + f"kind_counts: {dict(counts)}\n" +
    f"draw_length_m: {draw/1000:.2f}\n" + f"travel_length_m: {travel/1000:.2f}\n" +
    f"estimated_time_min_ideal: {(draw/(DF/60)+travel/(TF/60))/60:.1f}\n" +
    "algorithm_note: plus broken tonal threshold hatch layers; medium/dark layers strengthened while light regions remain sparse.\n",
    encoding="utf-8")
print("TONAL THRESHOLD LAYERS PLUS A4 package")
print("paths_total:", len(ordered))
print("kind_counts:", dict(counts))
print("draw_length_m:", round(draw/1000,2))
print("travel_length_m:", round(travel/1000,2))
print("estimated_time_min_ideal:", round((draw/(DF/60)+travel/(TF/60))/60,1))
print("preview:", black)
print("pdf:", blackpdf)
print("nc:", nc)

