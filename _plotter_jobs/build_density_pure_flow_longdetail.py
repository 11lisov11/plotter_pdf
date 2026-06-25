from __future__ import annotations

import math
import random
import shutil
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_density_pure_flow_longdetail_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
WORK_W_MM = 180.0
WORK_H_MM = 280.0
DRAW_W_MM = 176.0
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0
TRAVEL_F = 3000
DRAW_F = 1200
RNG = random.Random(91173)


def px_to_mm_func(w: int, h: int):
    draw_w = DRAW_W_MM
    draw_h = draw_w * h / w
    if draw_h > WORK_H_MM - 4:
        draw_h = WORK_H_MM - 4
        draw_w = draw_h * w / h
    x0 = (WORK_W_MM - draw_w) / 2
    y0 = (WORK_H_MM - draw_h) / 2
    sc = draw_w / w
    def conv(x: float, y: float) -> tuple[float, float]:
        return (x0 + x * sc, -(y0 + y * sc))
    return conv, draw_w, draw_h, sc


def preprocess(gray: np.ndarray):
    den = cv2.fastNlMeansDenoising(gray, None, h=4, templateWindowSize=7, searchWindowSize=21)
    bg = cv2.GaussianBlur(den, (0, 0), 27)
    norm = cv2.divide(den, bg, scale=238)
    norm = cv2.GaussianBlur(norm, (5, 5), 0)
    local_dark = np.clip(238 - norm.astype(np.int16), 0, 255).astype(np.float32)
    global_dark = np.clip(245 - den.astype(np.int16), 0, 255).astype(np.float32)
    density = np.maximum(local_dark * 1.50, global_dark * 0.42)
    density = cv2.GaussianBlur(density, (0, 0), 1.2)
    lo, hi = np.percentile(density, [48, 99.3])
    dens = np.clip((density - lo) / max(1.0, hi - lo), 0, 1)
    dens = np.power(dens, 0.82)
    # Preserve very dark jacket/hair but avoid paper dust becoming tone.
    return den, norm, dens.astype(np.float32)


def ellipse_mask(shape, cx, cy, rx, ry, angle=0.0):
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    ca = math.cos(angle); sa = math.sin(angle)
    x = (xx - cx) * ca + (yy - cy) * sa
    y = -(xx - cx) * sa + (yy - cy) * ca
    return (x / rx) ** 2 + (y / ry) ** 2 <= 1.0


def build_regions(dens: np.ndarray):
    h, w = dens.shape
    yy, xx = np.mgrid[0:h, 0:w]
    sky = yy < h * 0.43
    forest = (yy >= h * 0.36) & (yy < h * 0.58)
    field = yy >= h * 0.48
    person = (
        ellipse_mask(dens.shape, w*0.50, h*0.78, w*0.20, h*0.27, angle=-0.08)
        | ellipse_mask(dens.shape, w*0.58, h*0.69, w*0.17, h*0.15, angle=0.12)
        | ellipse_mask(dens.shape, w*0.40, h*0.78, w*0.11, h*0.11, angle=-0.4)
    )
    hair = ellipse_mask(dens.shape, w*0.57, h*0.70, w*0.16, h*0.17, angle=0.12) & (dens > 0.08)
    jacket = ellipse_mask(dens.shape, w*0.45, h*0.86, w*0.18, h*0.18, angle=-0.20) & (dens > 0.12)
    body = person & (yy > h*0.62) & (dens > 0.10)
    grass = (yy > h*0.62) & (~person)
    field_no_person = field & (~person)
    return {
        'sky': sky,
        'forest': forest,
        'field': field_no_person,
        'grass': grass,
        'hair': hair,
        'jacket': jacket,
        'body': body,
        'person': person,
    }


def add_hatches(paths: list[dict], dens: np.ndarray, region: np.ndarray, *, angle_deg: float, spacing: float, threshold: float, min_len: float, max_len: float, step: float = 2.0, jitter: float = 0.45, label: str):
    h, w = dens.shape
    theta = math.radians(angle_deg)
    ux, uy = math.cos(theta), math.sin(theta)
    nx, ny = -uy, ux
    cx, cy = w / 2, h / 2
    corners = [(0,0),(w,0),(0,h),(w,h)]
    svals = [(x-cx)*nx + (y-cy)*ny for x,y in corners]
    tvals = [(x-cx)*ux + (y-cy)*uy for x,y in corners]
    smin, smax = min(svals)-spacing*2, max(svals)+spacing*2
    tmin, tmax = min(tvals)-30, max(tvals)+30
    s = smin + RNG.random() * spacing
    while s <= smax:
        ts = np.arange(tmin, tmax, step)
        xs = cx + ux * ts + nx * s
        ys = cy + uy * ts + ny * s
        valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        ix = np.clip(np.rint(xs).astype(np.int32), 0, w-1)
        iy = np.clip(np.rint(ys).astype(np.int32), 0, h-1)
        d = dens[iy, ix]
        cond = valid & region[iy, ix] & (d > threshold)
        # Bridge tiny holes so the result becomes pencil-like, not dashed sand.
        bridge = cond.copy()
        max_gap = 5
        n = len(bridge)
        i = 0
        while i < n:
            if bridge[i]:
                i += 1; continue
            j = i
            while j < n and not bridge[j]: j += 1
            if i > 0 and j < n and (j - i) <= max_gap:
                bridge[i:j] = True
            i = j
        idxs = np.flatnonzero(bridge)
        if idxs.size:
            # contiguous blocks
            split = np.where(np.diff(idxs) > 1)[0] + 1
            blocks = np.split(idxs, split)
            for b in blocks:
                if b.size < 2:
                    continue
                seg_len = (b[-1] - b[0]) * step
                if seg_len < min_len:
                    continue
                # Split huge tonal fields into hand-like strokes, with small gaps.
                start = int(b[0])
                end = int(b[-1])
                chunk_pts = max(2, int(max_len / step))
                pos = start
                while pos < end:
                    this_end = min(end, pos + chunk_pts + RNG.randint(-3, 5))
                    if (this_end - pos) * step >= min_len:
                        pts = []
                        phase = RNG.random() * math.tau
                        amp = jitter * (0.4 + 0.6 * RNG.random())
                        for k in range(pos, this_end + 1, max(1, int(3.0/step))):
                            if k < 0 or k >= len(xs):
                                continue
                            if not valid[k]:
                                continue
                            x, y = float(xs[k]), float(ys[k])
                            wig = math.sin(k * 0.23 + phase) * amp + RNG.uniform(-0.15, 0.15) * amp
                            pts.append((x + nx * wig, y + ny * wig))
                        if len(pts) >= 2:
                            mean_d = float(np.mean(dens[np.clip(np.rint([p[1] for p in pts]).astype(int),0,h-1), np.clip(np.rint([p[0] for p in pts]).astype(int),0,w-1)]))
                            paths.append({'pts_px': pts, 'strength': mean_d, 'kind': label})
                    pos = this_end + RNG.randint(2, 8)
        s += spacing


def add_lsd_details(paths: list[dict], gray: np.ndarray, dens: np.ndarray, regions: dict):
    den = cv2.fastNlMeansDenoising(gray, None, h=4, templateWindowSize=7, searchWindowSize=21)
    bg = cv2.GaussianBlur(den, (0,0), 25)
    norm = cv2.divide(den, bg, scale=238)
    contrast = np.clip(255 - dens * 255, 0, 255).astype(np.uint8)
    det = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    for img, tag in ((norm, 'detail_norm'), (contrast, 'detail_dark')):
        lines = det.detect(img)[0]
        if lines is None:
            continue
        h,w = dens.shape
        for x1,y1,x2,y2 in lines.reshape(-1,4):
            x1=float(x1);y1=float(y1);x2=float(x2);y2=float(y2)
            length=math.hypot(x2-x1,y2-y1)
            if length < 32:
                continue
            mx=int(np.clip(round((x1+x2)/2),0,w-1)); my=int(np.clip(round((y1+y2)/2),0,h-1))
            d=float(dens[my,mx])
            # Keep source details, but not every paper scratch in the sky.
            if my < h*0.42 and (length < 55 or d < 0.30):
                continue
            keep = False
            if regions['hair'][my,mx] or regions['forest'][my,mx]:
                keep = d > 0.16 or length > 55
            elif regions['field'][my,mx] or regions['grass'][my,mx]:
                keep = d > 0.22 and length > 36
            else:
                keep = d > 0.32 and length > 48
            if keep:
                paths.append({'pts_px': [(x1,y1),(x2,y2)], 'strength': d, 'kind': tag})


def add_contours(paths: list[dict], gray: np.ndarray, dens: np.ndarray):
    den = cv2.fastNlMeansDenoising(gray, None, h=5, templateWindowSize=7, searchWindowSize=21)
    edges = cv2.Canny(den, 80, 160, L2gradient=True)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    h,w = dens.shape
    for cnt in contours:
        pts = cnt.reshape(-1,2)
        if len(pts) < 20:
            continue
        approx = cv2.approxPolyDP(pts, 1.1, closed=False).reshape(-1,2)
        if len(approx) < 3:
            continue
        length=0.0
        for a,b in zip(approx, approx[1:]):
            length += math.hypot(float(b[0]-a[0]), float(b[1]-a[1]))
        if length < 95 or length > 750:
            continue
        vals=[float(dens[int(y),int(x)]) for x,y in approx[::max(1,len(approx)//20)] if 0<=x<w and 0<=y<h]
        md=float(np.mean(vals)) if vals else 0.0
        if md < 0.18 and length < 150:
            continue
        paths.append({'pts_px': [(float(x),float(y)) for x,y in approx], 'strength': md, 'kind': 'contour'})


def convert_order_write(paths: list[dict], w: int, h: int):
    conv, draw_w, draw_h, sc = px_to_mm_func(w, h)
    mm=[]
    for p in paths:
        pts=[conv(x,y) for x,y in p['pts_px']]
        if len(pts)<2:
            continue
        length=sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(pts,pts[1:]))
        if length < 1.0:
            continue
        mm.append({**p, 'pts_mm': pts, 'length_mm': length})
    # Deduplicate nearly same straight segments.
    seen=set(); dedup=[]
    for p in mm:
        pts=p['pts_mm']
        key=(round(pts[0][0]*2),round(pts[0][1]*2),round(pts[-1][0]*2),round(pts[-1][1]*2),p['kind'])
        rkey=(key[2],key[3],key[0],key[1],key[4])
        if key in seen or rkey in seen:
            continue
        seen.add(key); dedup.append(p)
    rows=defaultdict(list)
    for p in dedup:
        cy=sum(y for _,y in p['pts_mm'])/len(p['pts_mm'])
        rows[int((-cy)//7.0)].append(p)
    ordered=[]
    for row in sorted(rows):
        rev=row%2==1
        group=[]
        for p in rows[row]:
            pts=p['pts_mm']
            if (pts[0][0] > pts[-1][0]) ^ rev:
                p={**p, 'pts_mm': list(reversed(pts))}
            group.append(p)
        group.sort(key=lambda p:p['pts_mm'][0][0], reverse=rev)
        ordered.extend(group)
    return ordered, draw_w, draw_h


def write_gcode(paths: list[dict], nc: Path):
    lines=['; density pure flow hatch A4', 'G21', 'G90', f'G0 Z{PEN_UP_Z:.3f}', f'F{TRAVEL_F}']
    draw=travel=0.0; cur=None
    for p in paths:
        pts=p['pts_mm']
        if cur is not None:
            travel += math.hypot(pts[0][0]-cur[0], pts[0][1]-cur[1])
        lines.append(f'G0 X{pts[0][0]:.3f} Y{pts[0][1]:.3f}')
        lines.append(f'G1 Z{PEN_DOWN_Z:.3f} F{DRAW_F}')
        prev=pts[0]
        for x,y in pts[1:]:
            lines.append(f'G1 X{x:.3f} Y{y:.3f}')
            draw += math.hypot(x-prev[0], y-prev[1]); prev=(x,y)
        lines.append(f'G0 Z{PEN_UP_Z:.3f}')
        cur=pts[-1]
    lines.append('M2')
    nc.write_text('\n'.join(lines)+'\n', encoding='ascii')
    return draw, travel, len(lines)


def render(paths: list[dict], png: Path, pressure=True):
    scale=5.0; pad=60
    im=Image.new('RGB',(int(WORK_W_MM*scale+pad*2), int(WORK_H_MM*scale+pad*2)), 'white')
    dr=ImageDraw.Draw(im)
    dr.rectangle([pad,pad,pad+WORK_W_MM*scale,pad+WORK_H_MM*scale], outline=(195,195,195), width=1)
    for p in paths:
        pts=[(pad+x*scale, pad+(-y)*scale) for x,y in p['pts_mm']]
        if len(pts)<2: continue
        if pressure:
            s=float(p.get('strength',0.2))
            gray=int(np.clip(218 - 150*s, 42, 205))
            color=(gray,gray,gray)
        else:
            color=(0,0,0)
        dr.line(pts, fill=color, width=1, joint='curve')
    im.save(png)


def png_to_pdf(png: Path, pdf: Path):
    c=canvas.Canvas(str(pdf), pagesize=A4); pw,ph=A4
    img=Image.open(png); iw,ih=img.size; m=18
    sc=min((pw-2*m)/iw,(ph-2*m)/ih); dw=iw*sc; dh=ih*sc
    c.drawImage(str(png),(pw-dw)/2,(ph-dh)/2,dw,dh); c.showPage(); c.save()


def main():
    shutil.copy2(SRC, OUT/'source_input_copy.jpg')
    gray=cv2.imread(str(SRC), cv2.IMREAD_GRAYSCALE)
    den,norm,dens=preprocess(gray)
    regions=build_regions(dens)
    cv2.imwrite(str(OUT/'debug_density.png'), np.clip(dens*255,0,255).astype(np.uint8))
    paths=[]
    # Sky: few faint directional clusters only where real tone exists.
    add_hatches(paths,dens,regions['sky'],angle_deg=28,spacing=46,threshold=0.30,min_len=22,max_len=85,jitter=0.28,label='sky_sparse')
    add_hatches(paths,dens,regions['sky'],angle_deg=-24,spacing=56,threshold=0.42,min_len=18,max_len=65,jitter=0.26,label='sky_cross_dark')
    # Forest: denser vertical/diagonal bundles, several thresholds.
    add_hatches(paths,dens,regions['forest'],angle_deg=-68,spacing=10,threshold=0.15,min_len=8,max_len=48,jitter=0.55,label='forest_mid_a')
    add_hatches(paths,dens,regions['forest'],angle_deg=-38,spacing=13,threshold=0.22,min_len=7,max_len=42,jitter=0.50,label='forest_mid_b')
    add_hatches(paths,dens,regions['forest'],angle_deg=48,spacing=10,threshold=0.31,min_len=6,max_len=35,jitter=0.45,label='forest_dark_cross')
    add_hatches(paths,dens,regions['forest'],angle_deg=82,spacing=8,threshold=0.38,min_len=7,max_len=44,jitter=0.40,label='forest_deep_vertical')
    # Field/grass: long coherent perspective lines, sparse in light areas.
    add_hatches(paths,dens,regions['field'],angle_deg=12,spacing=17,threshold=0.13,min_len=24,max_len=150,jitter=0.35,label='field_long_light')
    add_hatches(paths,dens,regions['field'],angle_deg=20,spacing=13,threshold=0.22,min_len=18,max_len=115,jitter=0.35,label='field_mid')
    add_hatches(paths,dens,regions['field'],angle_deg=-22,spacing=20,threshold=0.30,min_len=14,max_len=80,jitter=0.30,label='field_cross_dark')
    add_hatches(paths,dens,regions['grass'],angle_deg=-73,spacing=12,threshold=0.16,min_len=5,max_len=24,jitter=0.60,label='grass_a')
    add_hatches(paths,dens,regions['grass'],angle_deg=-48,spacing=14,threshold=0.24,min_len=5,max_len=25,jitter=0.55,label='grass_b')
    add_hatches(paths,dens,regions['grass'],angle_deg=58,spacing=14,threshold=0.32,min_len=5,max_len=22,jitter=0.45,label='grass_dark')
    # Hair and body: source-like directional strands and crosshatch density.
    add_hatches(paths,dens,regions['hair'],angle_deg=83,spacing=7,threshold=0.10,min_len=18,max_len=110,jitter=0.65,label='hair_strands')
    add_hatches(paths,dens,regions['hair'],angle_deg=66,spacing=8,threshold=0.18,min_len=16,max_len=90,jitter=0.55,label='hair_dark')
    add_hatches(paths,dens,regions['jacket'],angle_deg=-54,spacing=5.8,threshold=0.12,min_len=20,max_len=95,jitter=0.30,label='jacket_a')
    add_hatches(paths,dens,regions['jacket'],angle_deg=52,spacing=5.8,threshold=0.18,min_len=20,max_len=95,jitter=0.30,label='jacket_b')
    add_hatches(paths,dens,regions['jacket'],angle_deg=12,spacing=6.5,threshold=0.34,min_len=18,max_len=80,jitter=0.25,label='jacket_deep')
    add_hatches(paths,dens,regions['body'],angle_deg=-38,spacing=8.5,threshold=0.20,min_len=16,max_len=80,jitter=0.28,label='body_mid')
    # Real detected source strokes are used as detail/outline, but filtered so they don't become paper noise.
    add_lsd_details(paths, gray, dens, regions)  # long-only detail, no short fragments
    add_contours(paths, gray, dens)
    ordered, draw_w, draw_h = convert_order_write(paths, gray.shape[1], gray.shape[0])
    nc=OUT/'gemini_density_pure_flow_longdetail_a4.nc'; gcode=OUT/'gemini_density_pure_flow_longdetail_a4.gcode'
    draw,travel,line_count=write_gcode(ordered,nc); shutil.copy2(nc,gcode)
    ppng=OUT/'gemini_density_pure_flow_longdetail_preview_pressure_gray.png'
    bpng=OUT/'gemini_density_pure_flow_longdetail_preview_black_actual.png'
    render(ordered,ppng,True); render(ordered,bpng,False)
    png_to_pdf(ppng,OUT/'gemini_density_pure_flow_longdetail_preview_pressure_gray.pdf')
    png_to_pdf(bpng,OUT/'gemini_density_pure_flow_longdetail_preview_black_actual.pdf')
    counts=defaultdict(int)
    for p in ordered: counts[p['kind']]+=1
    text=(
        'DENSITY PURE FLOW LONG-DETAIL A4 package\n'
        f'source: {SRC}\noutput_dir: {OUT}\n'
        f'image_px: {gray.shape[1]} x {gray.shape[0]}\n'
        f'drawing_size_mm: {draw_w:.2f} x {draw_h:.2f}\n'
        f'paths_total: {len(ordered)}\nkind_counts: {dict(counts)}\n'
        f'draw_length_m: {draw/1000:.2f}\ntravel_length_m: {travel/1000:.2f}\ngcode_lines: {line_count}\n'
        f'estimated_time_min_ideal: {(draw/DRAW_F+travel/TRAVEL_F):.1f}\n'
        'realistic_time_note: likely 2-5 hours depending on pen lifts and acceleration.\n'
        'algorithm_note: region-aware hatch layers plus only long source details. Light zones receive sparse long strokes; dark zones receive multiple closer hatch directions; short LSD fragments are rejected to avoid black-pen noise.\n'
        'files:\n- gemini_density_pure_flow_longdetail_preview_pressure_gray.png/pdf\n- gemini_density_pure_flow_longdetail_preview_black_actual.png/pdf\n- gemini_density_pure_flow_longdetail_a4.nc\n- gemini_density_pure_flow_longdetail_a4.gcode\n'
    )
    (OUT/'README_result.txt').write_text(text,encoding='utf-8')
    print(text)

if __name__=='__main__':
    main()



