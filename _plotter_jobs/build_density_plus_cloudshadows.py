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
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_density_plus_cloudshadows_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
WORK_W_MM = 180.0
WORK_H_MM = 280.0
DRAW_W_MM = 176.0
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0
TRAVEL_F = 3000
DRAW_F = 1200
RNG = random.Random(20260622)


def preprocess(gray: np.ndarray):
    den = cv2.fastNlMeansDenoising(gray, None, h=4, templateWindowSize=7, searchWindowSize=21)
    bg = cv2.GaussianBlur(den, (0, 0), 31)
    norm = cv2.divide(den, bg, scale=238)
    norm = cv2.GaussianBlur(norm, (5, 5), 0)
    local = np.clip(238 - norm.astype(np.int16), 0, 255).astype(np.float32)
    global_dark = np.clip(245 - den.astype(np.int16), 0, 255).astype(np.float32)
    dens = np.maximum(local * 1.45, global_dark * 0.38)
    dens = cv2.GaussianBlur(dens, (0, 0), 1.5)
    lo, hi = np.percentile(dens, [50, 99.5])
    dens = np.clip((dens - lo) / max(1.0, hi - lo), 0, 1)
    dens = np.power(dens, 0.78)
    return den, norm, dens.astype(np.float32)


def ellipse_mask(shape, cx, cy, rx, ry, angle=0.0):
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    ca, sa = math.cos(angle), math.sin(angle)
    x = (xx - cx) * ca + (yy - cy) * sa
    y = -(xx - cx) * sa + (yy - cy) * ca
    return (x / rx) ** 2 + (y / ry) ** 2 <= 1.0


def regions(dens: np.ndarray):
    h, w = dens.shape
    yy, xx = np.mgrid[0:h, 0:w]
    person = (
        ellipse_mask(dens.shape, w*0.50, h*0.80, w*0.20, h*0.26, -0.08)
        | ellipse_mask(dens.shape, w*0.58, h*0.69, w*0.17, h*0.15, 0.12)
        | ellipse_mask(dens.shape, w*0.41, h*0.78, w*0.11, h*0.11, -0.35)
    )
    hair = ellipse_mask(dens.shape, w*0.57, h*0.70, w*0.17, h*0.18, 0.12) & (dens > 0.06)
    jacket = ellipse_mask(dens.shape, w*0.45, h*0.86, w*0.18, h*0.18, -0.20) & (dens > 0.10)
    body = person & (dens > 0.09)
    sky = yy < h * 0.43
    forest = (yy >= h * 0.36) & (yy < h * 0.59) & (~person)
    field = (yy >= h * 0.48) & (~person)
    grass = (yy >= h * 0.62) & (~person)
    return dict(sky=sky, forest=forest, field=field, grass=grass, hair=hair, jacket=jacket, body=body, person=person)


def add_layer(paths, dens, mask, *, angle, spacing, threshold, min_len, max_len, label, jitter=0.25, bridge_px=4, step=2.0):
    h, w = dens.shape
    th = math.radians(angle)
    ux, uy = math.cos(th), math.sin(th)
    nx, ny = -uy, ux
    cx, cy = w/2, h/2
    corners = [(0,0),(w,0),(0,h),(w,h)]
    svals = [(x-cx)*nx + (y-cy)*ny for x,y in corners]
    tvals = [(x-cx)*ux + (y-cy)*uy for x,y in corners]
    s = min(svals) - spacing*2 + RNG.random()*spacing
    smax = max(svals) + spacing*2
    tmin, tmax = min(tvals)-40, max(tvals)+40
    while s <= smax:
        ts = np.arange(tmin, tmax, step)
        xs = cx + ux*ts + nx*s
        ys = cy + uy*ts + ny*s
        valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        ix = np.clip(np.rint(xs).astype(int), 0, w-1)
        iy = np.clip(np.rint(ys).astype(int), 0, h-1)
        cond = valid & mask[iy, ix] & (dens[iy, ix] >= threshold)
        if bridge_px > 0:
            i = 0
            while i < len(cond):
                if cond[i]:
                    i += 1
                    continue
                j = i
                while j < len(cond) and not cond[j]:
                    j += 1
                if i > 0 and j < len(cond) and (j-i) <= bridge_px:
                    cond[i:j] = True
                i = j
        idx = np.flatnonzero(cond)
        if idx.size:
            splits = np.where(np.diff(idx) > 1)[0] + 1
            blocks = np.split(idx, splits)
            for b in blocks:
                if b.size < 2:
                    continue
                total_len = (int(b[-1]) - int(b[0])) * step
                if total_len < min_len:
                    continue
                pos = int(b[0])
                end = int(b[-1])
                while pos < end:
                    chunk = max(3, int(max_len/step) + RNG.randint(-4, 4))
                    e = min(end, pos + chunk)
                    if (e - pos) * step >= min_len:
                        pts = []
                        phase = RNG.random() * math.tau
                        stride = max(1, int(3.0/step))
                        for k in range(pos, e+1, stride):
                            if not valid[k]:
                                continue
                            wig = math.sin(k*0.21 + phase) * jitter + RNG.uniform(-0.12, 0.12) * jitter
                            pts.append((float(xs[k] + nx*wig), float(ys[k] + ny*wig)))
                        if len(pts) >= 2:
                            vals = []
                            for x, y in pts[::max(1, len(pts)//10)]:
                                xi = int(np.clip(round(x), 0, w-1)); yi = int(np.clip(round(y), 0, h-1))
                                vals.append(float(dens[yi, xi]))
                            paths.append({'pts_px': pts, 'strength': float(np.mean(vals)) if vals else threshold, 'kind': label})
                    pos = e + RNG.randint(2, 8)
        s += spacing


def add_hair_flow(paths, dens, reg):
    h, w = dens.shape
    # Curved hair strands from crown downward, clipped by hair mask/density.
    starts = np.linspace(0.47*w, 0.69*w, 38)
    for i, sx in enumerate(starts):
        pts = []
        y0 = h*(0.59 + 0.04*RNG.random())
        length = RNG.uniform(155, 245)
        curve = RNG.uniform(-0.28, 0.22)
        phase = RNG.random()*math.tau
        for t in np.linspace(0, 1, 70):
            y = y0 + length*t
            x = sx + (t*t*curve*w*0.18) + math.sin(t*math.tau*1.2 + phase)*5.0*(1-t*0.3)
            xi = int(np.clip(round(x),0,w-1)); yi = int(np.clip(round(y),0,h-1))
            if reg['hair'][yi, xi] and dens[yi, xi] > (0.08 + 0.10*(i%3==0)):
                pts.append((x,y))
            elif pts and len(pts) > 8:
                paths.append({'pts_px': pts, 'strength': 0.35, 'kind': 'hair_flow'})
                pts = []
            else:
                pts = []
        if len(pts) > 8:
            paths.append({'pts_px': pts, 'strength': 0.35, 'kind': 'hair_flow'})


def add_long_contours(paths, gray, dens):
    den = cv2.fastNlMeansDenoising(gray, None, h=5, templateWindowSize=7, searchWindowSize=21)
    edges = cv2.Canny(den, 90, 175, L2gradient=True)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    h, w = dens.shape
    for cnt in contours:
        pts = cnt.reshape(-1,2)
        if len(pts) < 45:
            continue
        approx = cv2.approxPolyDP(pts, 1.25, False).reshape(-1,2)
        if len(approx) < 4:
            continue
        length = sum(math.hypot(float(b[0]-a[0]), float(b[1]-a[1])) for a,b in zip(approx, approx[1:]))
        if length < 120 or length > 760:
            continue
        vals = [float(dens[int(y), int(x)]) for x,y in approx[::max(1,len(approx)//20)] if 0 <= x < w and 0 <= y < h]
        md = float(np.mean(vals)) if vals else 0.0
        if md < 0.16 and length < 190:
            continue
        paths.append({'pts_px': [(float(x),float(y)) for x,y in approx], 'strength': md, 'kind': 'long_contour'})



def add_figure_folds(paths, dens, reg):
    h, w = dens.shape
    mask = (reg['jacket'] | reg['body']) & (dens > 0.12)

    def add_polyline(points, label, min_len=10.0):
        seg = []
        chunks = []
        for x, y in points:
            ix = int(np.clip(round(x), 0, w-1)); iy = int(np.clip(round(y), 0, h-1))
            if mask[iy, ix]:
                seg.append((float(x), float(y)))
            else:
                if len(seg) >= 4:
                    chunks.append(seg)
                seg = []
        if len(seg) >= 4:
            chunks.append(seg)
        for pts in chunks:
            length = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(pts, pts[1:]))
            if length < min_len:
                continue
            vals=[]
            for x,y in pts[::max(1,len(pts)//12)]:
                ix=int(np.clip(round(x),0,w-1)); iy=int(np.clip(round(y),0,h-1))
                vals.append(float(dens[iy,ix]))
            paths.append({'pts_px': pts, 'strength': float(np.mean(vals)) if vals else 0.3, 'kind': label})

    for i, x0 in enumerate(np.linspace(0.36*w, 0.58*w, 20)):
        phase = RNG.random() * math.tau
        y0 = 0.70*h + RNG.uniform(-8, 12)
        length = RNG.uniform(145, 230)
        pts=[]
        for t in np.linspace(0, 1, 70):
            x = x0 + (t - 0.5) * RNG.uniform(18, 36) + math.sin(t*math.pi*1.5 + phase) * 6
            y = y0 + length*t
            x += (t*t) * ((-1)**i) * RNG.uniform(12, 28)
            pts.append((x,y))
        add_polyline(pts, 'jacket_fold_long', min_len=18)

    for j, y0 in enumerate(np.linspace(0.74*h, 0.89*h, 18)):
        pts=[]
        cx = 0.39*w + RNG.uniform(-8, 8)
        amp = RNG.uniform(22, 42)
        for t in np.linspace(-0.95, 0.95, 60):
            x = cx + amp * math.sin(t*1.2) + RNG.uniform(-0.8,0.8)
            y = y0 + 22 * t + 10 * math.sin(t*2.0 + j*0.3)
            pts.append((x,y))
        add_polyline(pts, 'sleeve_fold_arc', min_len=12)

    for y0 in np.linspace(0.91*h, 0.98*h, 8):
        pts=[]
        for t in np.linspace(0,1,80):
            x = 0.39*w + 0.22*w*t + math.sin(t*math.tau*1.2 + y0*0.01)*5
            y = y0 + math.sin(t*math.tau + y0*0.02)*8
            pts.append((x,y))
        add_polyline(pts, 'jacket_hem_shadow', min_len=18)
def convert(paths, w, h):
    draw_w = DRAW_W_MM
    draw_h = draw_w*h/w
    if draw_h > WORK_H_MM-4:
        draw_h = WORK_H_MM-4; draw_w = draw_h*w/h
    x0 = (WORK_W_MM-draw_w)/2; y0 = (WORK_H_MM-draw_h)/2; sc = draw_w/w
    out=[]
    for p in paths:
        pts = [(x0+x*sc, -(y0+y*sc)) for x,y in p['pts_px']]
        if len(pts)<2:
            continue
        length = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(pts, pts[1:]))
        if length < 1.2:
            continue
        out.append({**p, 'pts_mm': pts, 'length_mm': length})
    seen=set(); ded=[]
    for p in out:
        a=p['pts_mm'][0]; b=p['pts_mm'][-1]
        key=(round(a[0]*2), round(a[1]*2), round(b[0]*2), round(b[1]*2), p['kind'])
        rkey=(key[2],key[3],key[0],key[1],key[4])
        if key in seen or rkey in seen:
            continue
        seen.add(key); ded.append(p)
    rows=defaultdict(list)
    for p in ded:
        cy=sum(y for _,y in p['pts_mm'])/len(p['pts_mm'])
        rows[int((-cy)//7.0)].append(p)
    ordered=[]
    for row in sorted(rows):
        rev = row % 2 == 1
        group=[]
        for p in rows[row]:
            pts=p['pts_mm']
            if (pts[0][0] > pts[-1][0]) ^ rev:
                p={**p, 'pts_mm': list(reversed(pts))}
            group.append(p)
        group.sort(key=lambda p:p['pts_mm'][0][0], reverse=rev)
        ordered.extend(group)
    return ordered, draw_w, draw_h


def write_gcode(paths, nc):
    lines=['; density plus cloud shadows A4','G21','G90',f'G0 Z{PEN_UP_Z:.3f}',f'F{TRAVEL_F}']
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


def render(paths, png, pressure=True):
    scale=5.0; pad=60
    im=Image.new('RGB',(int(WORK_W_MM*scale+pad*2), int(WORK_H_MM*scale+pad*2)), 'white')
    dr=ImageDraw.Draw(im)
    dr.rectangle([pad,pad,pad+WORK_W_MM*scale,pad+WORK_H_MM*scale], outline=(195,195,195), width=1)
    for p in paths:
        pts=[(pad+x*scale, pad+(-y)*scale) for x,y in p['pts_mm']]
        if pressure:
            s=float(p.get('strength',0.2)); gray=int(np.clip(220 - 155*s, 44, 205)); color=(gray,gray,gray)
        else:
            color=(0,0,0)
        dr.line(pts, fill=color, width=1, joint='curve')
    im.save(png)


def png_to_pdf(png, pdf):
    c=canvas.Canvas(str(pdf), pagesize=A4); pw,ph=A4
    img=Image.open(png); iw,ih=img.size; m=18
    sc=min((pw-2*m)/iw, (ph-2*m)/ih); dw=iw*sc; dh=ih*sc
    c.drawImage(str(png),(pw-dw)/2,(ph-dh)/2,dw,dh); c.showPage(); c.save()


def main():
    shutil.copy2(SRC, OUT/'source_input_copy.jpg')
    gray=cv2.imread(str(SRC), cv2.IMREAD_GRAYSCALE)
    den,norm,dens=preprocess(gray)
    reg=regions(dens)
    cv2.imwrite(str(OUT/'debug_density.png'), np.clip(dens*255,0,255).astype(np.uint8))
    paths=[]
    # Very light sky: almost empty, only real dark clouds get sparse hatches.
    add_layer(paths,dens,reg['sky'],angle=28,spacing=28,threshold=0.13,min_len=18,max_len=82,label='sky_light',jitter=0.22,bridge_px=3)
    add_layer(paths,dens,reg['sky'],angle=-24,spacing=38,threshold=0.25,min_len=18,max_len=68,label='sky_dark_cross',jitter=0.20,bridge_px=2)
    add_layer(paths,dens,reg['sky'],angle=32,spacing=24,threshold=0.105,min_len=24,max_len=112,label='cloud_soft_shadow',jitter=0.18,bridge_px=4)
    add_layer(paths,dens,reg['sky'],angle=-18,spacing=46,threshold=0.205,min_len=20,max_len=82,label='cloud_soft_cross',jitter=0.16,bridge_px=2)
    # Forest: density staircase, each darker level adds another direction.
    add_layer(paths,dens,reg['forest'],angle=-70,spacing=11,threshold=0.09,min_len=8,max_len=54,label='forest_l1',jitter=0.36,bridge_px=5)
    add_layer(paths,dens,reg['forest'],angle=-40,spacing=10,threshold=0.18,min_len=8,max_len=50,label='forest_l2',jitter=0.32,bridge_px=4)
    add_layer(paths,dens,reg['forest'],angle=45,spacing=9,threshold=0.33,min_len=7,max_len=40,label='forest_l3',jitter=0.28,bridge_px=3)
    add_layer(paths,dens,reg['forest'],angle=82,spacing=8,threshold=0.52,min_len=7,max_len=44,label='forest_l4',jitter=0.25,bridge_px=2)
    # Field/grass: long sparse perspective strokes, then local grass only in darker patches.
    add_layer(paths,dens,reg['field'],angle=12,spacing=12,threshold=0.06,min_len=28,max_len=170,label='field_l1',jitter=0.22,bridge_px=7)
    add_layer(paths,dens,reg['field'],angle=20,spacing=11,threshold=0.16,min_len=18,max_len=130,label='field_l2',jitter=0.20,bridge_px=5)
    add_layer(paths,dens,reg['field'],angle=-22,spacing=21,threshold=0.42,min_len=16,max_len=85,label='field_l3',jitter=0.20,bridge_px=3)
    add_layer(paths,dens,reg['grass'],angle=-72,spacing=11,threshold=0.11,min_len=5,max_len=25,label='grass_l1',jitter=0.46,bridge_px=1)
    add_layer(paths,dens,reg['grass'],angle=58,spacing=13,threshold=0.27,min_len=5,max_len=24,label='grass_l2',jitter=0.36,bridge_px=1)
    # Figure: close, readable crosshatch, no random detector noise.
    add_layer(paths,dens,reg['jacket'],angle=-54,spacing=7.4,threshold=0.17,min_len=18,max_len=96,label='jacket_l1',jitter=0.20,bridge_px=4)
    add_layer(paths,dens,reg['jacket'],angle=52,spacing=7.2,threshold=0.25,min_len=18,max_len=96,label='jacket_l2',jitter=0.20,bridge_px=3)
    add_layer(paths,dens,reg['jacket'],angle=12,spacing=8.0,threshold=0.47,min_len=16,max_len=82,label='jacket_l3',jitter=0.16,bridge_px=2)
    add_layer(paths,dens,reg['body'],angle=-38,spacing=8.5,threshold=0.18,min_len=16,max_len=82,label='body_l1',jitter=0.22,bridge_px=4)
    add_hair_flow(paths,dens,reg)
    add_layer(paths,dens,reg['hair'],angle=64,spacing=8,threshold=0.22,min_len=16,max_len=90,label='hair_shadow',jitter=0.20,bridge_px=4)
    add_figure_folds(paths, dens, reg)
    add_long_contours(paths, gray, dens)
    ordered, draw_w, draw_h = convert(paths, gray.shape[1], gray.shape[0])
    nc=OUT/'gemini_density_plus_cloudshadows_a4.nc'; gcode=OUT/'gemini_density_plus_cloudshadows_a4.gcode'
    draw,travel,line_count=write_gcode(ordered,nc); shutil.copy2(nc,gcode)
    ppng=OUT/'gemini_density_plus_cloudshadows_preview_pressure_gray.png'; bpng=OUT/'gemini_density_plus_cloudshadows_preview_black_actual.png'
    render(ordered,ppng,True); render(ordered,bpng,False)
    png_to_pdf(ppng,OUT/'gemini_density_plus_cloudshadows_preview_pressure_gray.pdf')
    png_to_pdf(bpng,OUT/'gemini_density_plus_cloudshadows_preview_black_actual.pdf')
    counts=defaultdict(int)
    for p in ordered: counts[p['kind']]+=1
    text=(
        'DENSITY PLUS CLOUDSHADOWS A4 package\n'
        f'source: {SRC}\noutput_dir: {OUT}\nimage_px: {gray.shape[1]} x {gray.shape[0]}\n'
        f'drawing_size_mm: {draw_w:.2f} x {draw_h:.2f}\npaths_total: {len(ordered)}\nkind_counts: {dict(counts)}\n'
        f'draw_length_m: {draw/1000:.2f}\ntravel_length_m: {travel/1000:.2f}\ngcode_lines: {line_count}\n'
        f'estimated_time_min_ideal: {(draw/DRAW_F+travel/TRAVEL_F):.1f}\n'
        'algorithm_note: plus_cloudforest with extra sparse cloud-shadow hatch layers in the sky; figure density unchanged and no dark-area bundling. Light areas receive sparse long hatches; each darker threshold adds closer crossing layers. Hair uses curved strands, jacket uses clean close crosshatch, and only long contours are kept.\n'
        'files:\n- gemini_density_plus_cloudshadows_preview_pressure_gray.png/pdf\n- gemini_density_plus_cloudshadows_preview_black_actual.png/pdf\n- gemini_density_plus_cloudshadows_a4.nc\n- gemini_density_plus_cloudshadows_a4.gcode\n'
    )
    (OUT/'README_result.txt').write_text(text,encoding='utf-8')
    print(text)

if __name__ == '__main__':
    main()





