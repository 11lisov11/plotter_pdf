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

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_lsd_real_strokes_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
WORK_W_MM = 180.0
WORK_H_MM = 280.0
DRAW_W_MM = 176.0
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0
TRAVEL_F = 3000
DRAW_F = 1200


def sample_line(arr, x1, y1, x2, y2, n=16):
    xs = np.linspace(x1, x2, n)
    ys = np.linspace(y1, y2, n)
    h, w = arr.shape
    vals = []
    for x, y in zip(xs, ys):
        ix = int(round(x)); iy = int(round(y))
        if 0 <= ix < w and 0 <= iy < h:
            vals.append(float(arr[iy, ix]))
    return float(np.mean(vals)) if vals else 0.0, float(np.max(vals)) if vals else 0.0


def preprocess(gray):
    den = cv2.fastNlMeansDenoising(gray, None, h=4, templateWindowSize=7, searchWindowSize=21)
    bg = cv2.GaussianBlur(den, (0,0), 25)
    norm = cv2.divide(den, bg, scale=238)
    norm = cv2.GaussianBlur(norm, (3,3), 0)
    local_dark = np.clip(238 - norm.astype(np.int16), 0, 255).astype(np.float32)
    global_dark = np.clip(244 - den.astype(np.int16), 0, 255).astype(np.float32)
    strength = np.maximum(local_dark * 1.7, global_dark * 0.45)
    # Line detector gets a contrast-enhanced dark-on-light image.
    lsd_img = np.clip(255 - strength * 4.5, 0, 255).astype(np.uint8)
    lsd_img = cv2.GaussianBlur(lsd_img, (3,3), 0)
    return den, norm, strength, lsd_img


def detect_lsd(norm, strength, lsd_img):
    detectors = []
    for refine in (cv2.LSD_REFINE_ADV, cv2.LSD_REFINE_STD):
        try:
            detectors.append(cv2.createLineSegmentDetector(refine))
        except Exception:
            pass
    raw = []
    for det in detectors:
        for img, tag in ((lsd_img, 'contrast'), (norm, 'norm')):
            lines = det.detect(img)[0]
            if lines is None:
                continue
            for ln in lines.reshape(-1,4):
                x1,y1,x2,y2 = map(float, ln)
                length = math.hypot(x2-x1, y2-y1)
                if length < 5.0:
                    continue
                mean_s, max_s = sample_line(strength, x1,y1,x2,y2, max(8, int(length/2)))
                # Keep long faint hatches, reject short texture dust.
                if length < 10.0 and mean_s < 9.0 and max_s < 20.0:
                    continue
                if mean_s < 5.5 and length < 22.0:
                    continue
                raw.append((x1,y1,x2,y2,length,mean_s,max_s,tag))
    # Deduplicate almost identical detections from two detector passes.
    buckets = {}
    for seg in raw:
        x1,y1,x2,y2,length,mean_s,max_s,tag = seg
        # canonical endpoint order
        if (x2,y2) < (x1,y1):
            x1,y1,x2,y2 = x2,y2,x1,y1
        key = (round(x1/3), round(y1/3), round(x2/3), round(y2/3))
        prev = buckets.get(key)
        if prev is None or mean_s*length > prev[5]*prev[4]:
            buckets[key] = (x1,y1,x2,y2,length,mean_s,max_s,tag)
    segs = list(buckets.values())
    # Drop obvious tiny residue in very sparse sky; keep cloud hatches if long/coherent.
    h,w = strength.shape
    clean = []
    for x1,y1,x2,y2,length,mean_s,max_s,tag in segs:
        cy = (y1+y2)/2
        if cy < h*0.42 and length < 14 and mean_s < 13:
            continue
        clean.append({'pts_px': [(x1,y1),(x2,y2)], 'length_px': length, 'strength': mean_s, 'max_strength': max_s, 'tag': tag})
    return clean


def add_soft_contours(gray, strength, existing):
    # Add only long organic contours missed by LSD, not filled-cell skeletons.
    den = cv2.fastNlMeansDenoising(gray, None, h=5, templateWindowSize=7, searchWindowSize=21)
    edges = cv2.Canny(den, 70, 150, L2gradient=True)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = list(existing)
    for cnt in contours:
        pts = cnt.reshape(-1,2)
        if len(pts) < 18:
            continue
        # approximate but keep curves.
        approx = cv2.approxPolyDP(pts, epsilon=1.2, closed=False).reshape(-1,2)
        if len(approx) < 3:
            continue
        length = 0.0
        for a,b in zip(approx, approx[1:]):
            length += math.hypot(float(b[0]-a[0]), float(b[1]-a[1]))
        if length < 22 or length > 900:
            continue
        vals=[]
        for x,y in approx[::max(1,len(approx)//24)]:
            vals.append(float(strength[int(y), int(x)]))
        mean_s = float(np.mean(vals)) if vals else 0.0
        if mean_s < 7 and length < 45:
            continue
        # Avoid too many hard outlines in dense jacket: only add pale/medium contour curves.
        out.append({'pts_px': [(float(x),float(y)) for x,y in approx], 'length_px': length, 'strength': mean_s, 'max_strength': max(vals) if vals else mean_s, 'tag': 'contour'})
    return out


def to_mm(paths, img_w, img_h):
    draw_w = DRAW_W_MM
    draw_h = draw_w * img_h / img_w
    if draw_h > WORK_H_MM - 4:
        draw_h = WORK_H_MM - 4
        draw_w = draw_h * img_w / img_h
    x0 = (WORK_W_MM - draw_w)/2
    y0 = (WORK_H_MM - draw_h)/2
    scale = draw_w/img_w
    out=[]
    for p in paths:
        pts=[]
        for x,y in p['pts_px']:
            pts.append((x0+x*scale, -(y0+y*scale)))
        length_mm=p['length_px']*scale
        if length_mm < 1.0:
            continue
        out.append({**p, 'pts_mm': pts, 'length_mm': length_mm})
    return out, draw_w, draw_h


def order_paths(paths):
    rows=defaultdict(list)
    row_h=7.0
    for p in paths:
        cy=sum(pt[1] for pt in p['pts_mm'])/len(p['pts_mm'])
        rows[int((-cy)//row_h)].append(p)
    ordered=[]
    for row in sorted(rows):
        rev=bool(row%2)
        group=[]
        for p in rows[row]:
            pts=p['pts_mm']
            if (pts[0][0] > pts[-1][0]) ^ rev:
                p={**p,'pts_mm':list(reversed(pts))}
            group.append(p)
        group.sort(key=lambda p:p['pts_mm'][0][0], reverse=rev)
        ordered.extend(group)
    return ordered


def write_gcode(paths, out_nc):
    lines=['; LSD real strokes A4','G21','G90',f'G0 Z{PEN_UP_Z:.3f}',f'F{TRAVEL_F}']
    draw=travel=0.0; cur=None
    for p in paths:
        pts=p['pts_mm']
        if len(pts)<2: continue
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
    out_nc.write_text('\n'.join(lines)+'\n', encoding='ascii')
    return draw, travel, len(lines)


def render(paths, png, pressure=True):
    scale=5; pad=60
    im=Image.new('RGB',(int(WORK_W_MM*scale+2*pad), int(WORK_H_MM*scale+2*pad)), 'white')
    dr=ImageDraw.Draw(im)
    dr.rectangle([pad,pad,pad+WORK_W_MM*scale,pad+WORK_H_MM*scale], outline=(195,195,195), width=1)
    for p in paths:
        pts=[(pad+x*scale, pad+(-y)*scale) for x,y in p['pts_mm']]
        if pressure:
            s=p.get('strength',15)
            gray=int(np.clip(218-s*4.2, 45, 205))
            color=(gray,gray,gray)
        else:
            color=(0,0,0)
        dr.line(pts, fill=color, width=1)
    im.save(png)


def png_to_pdf(png,pdf):
    c=canvas.Canvas(str(pdf), pagesize=A4); pw,ph=A4
    img=Image.open(png); iw,ih=img.size; m=18
    sc=min((pw-2*m)/iw,(ph-2*m)/ih); dw=iw*sc; dh=ih*sc
    c.drawImage(str(png),(pw-dw)/2,(ph-dh)/2,dw,dh); c.showPage(); c.save()


def main():
    shutil.copy2(SRC, OUT/'source_input_copy.jpg')
    gray=cv2.imread(str(SRC), cv2.IMREAD_GRAYSCALE)
    den,norm,strength,lsd_img=preprocess(gray)
    cv2.imwrite(str(OUT/'debug_lsd_input.png'), lsd_img)
    cv2.imwrite(str(OUT/'debug_strength.png'), np.clip(strength*3,0,255).astype(np.uint8))
    paths=detect_lsd(norm,strength,lsd_img)
    before=len(paths)
    paths=add_soft_contours(gray,strength,paths)
    contour_added=len(paths)-before
    paths_mm,draw_w,draw_h=to_mm(paths, gray.shape[1], gray.shape[0])
    # Final cull: avoid very tiny black specks.
    paths_mm=[p for p in paths_mm if p['length_mm']>=1.3 or p['strength']>=20]
    paths_mm=order_paths(paths_mm)
    nc=OUT/'gemini_lsd_real_strokes_a4.nc'; gcode=OUT/'gemini_lsd_real_strokes_a4.gcode'
    draw,travel,lines=write_gcode(paths_mm,nc); shutil.copy2(nc,gcode)
    ppng=OUT/'gemini_lsd_real_strokes_preview_pressure_gray.png'; bpng=OUT/'gemini_lsd_real_strokes_preview_black_actual.png'
    render(paths_mm,ppng,True); render(paths_mm,bpng,False)
    png_to_pdf(ppng, OUT/'gemini_lsd_real_strokes_preview_pressure_gray.pdf')
    png_to_pdf(bpng, OUT/'gemini_lsd_real_strokes_preview_black_actual.pdf')
    counts=defaultdict(int)
    for p in paths_mm: counts[p.get('tag','?')]+=1
    text=(
        'LSD REAL STROKES A4 package\n'
        f'source: {SRC}\noutput_dir: {OUT}\n'
        f'image_px: {gray.shape[1]} x {gray.shape[0]}\n'
        f'drawing_size_mm: {draw_w:.2f} x {draw_h:.2f}\n'
        f'paths_total: {len(paths_mm)}\n'
        f'lsd_before_contours: {before}\ncontour_added: {contour_added}\nkind_counts: {dict(counts)}\n'
        f'draw_length_m: {draw/1000:.2f}\ntravel_length_m: {travel/1000:.2f}\ngcode_lines: {lines}\n'
        f'estimated_time_min_ideal: {(draw/DRAW_F+travel/TRAVEL_F):.1f}\n'
        'algorithm_note: detects real pencil line segments from the source with LSD, adds only long organic Canny contours, filters short paper noise, and preserves source hatch directions instead of random dot-like strokes.\n'
        'files:\n- gemini_lsd_real_strokes_preview_pressure_gray.png/pdf\n- gemini_lsd_real_strokes_preview_black_actual.png/pdf\n- gemini_lsd_real_strokes_a4.nc\n- gemini_lsd_real_strokes_a4.gcode\n'
    )
    (OUT/'README_result.txt').write_text(text, encoding='utf-8')
    print(text)

if __name__=='__main__':
    main()
