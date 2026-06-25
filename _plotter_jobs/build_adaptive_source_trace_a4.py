from __future__ import annotations
from pathlib import Path
import math
from collections import Counter

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from scipy.ndimage import gaussian_filter, binary_closing, binary_opening
from skimage.filters import threshold_sauvola
from skimage.morphology import remove_small_objects, skeletonize

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_adaptive_source_trace_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
DRAW_W_MM = 180.0
DRAW_H_MM = 240.0
TOP_MM = 20.0
SAFE_H_MM = 280.0
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0
TRAVEL_F = 3000
DRAW_F = 1200
PX_PER_MM = 4

img0 = Image.open(SRC).convert('L')
w0,h0=img0.size
W=1000
H=int(round(h0*W/w0))
img=img0.resize((W,H), Image.Resampling.LANCZOS)
w,h=img.size
gray=np.asarray(img,dtype=np.float32)/255.0
bg=gaussian_filter(gray,sigma=32)
flat=np.clip(gray/np.maximum(bg,0.58),0,1)
# local contrast enhancement for pencil strokes, but keep paper grain suppressed.
blur=gaussian_filter(flat,sigma=1.0)
tone=np.clip(1.0-blur,0,1)
# Sauvola finds local pencil lines in both faint and dark zones.
thr=threshold_sauvola(blur, window_size=45, k=0.16, r=0.5)
ink=(blur < (thr - 0.006)) | (tone > 0.145)
# Avoid converting blank paper texture to paths.
ink &= tone > 0.030
ink=binary_closing(ink, structure=np.ones((2,2),dtype=bool))
ink=binary_opening(ink, structure=np.ones((1,1),dtype=bool))
ink=remove_small_objects(ink, min_size=22)
# Drop almost-isolated paper specks via connected component geometry before skeleton.
num, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
keep=np.zeros_like(ink,dtype=bool)
for lab in range(1,num):
    x,y,ww,hh,area=stats[lab]
    if area < 20:
        continue
    diag=math.hypot(ww,hh)
    elong=max(ww,hh)/max(1,min(ww,hh))
    # keep long/fairly dark strokes; reject tiny round paper grains.
    local=float(np.mean(tone[y:y+hh,x:x+ww][labels[y:y+hh,x:x+ww]==lab]))
    if diag < 7 and local < 0.12:
        continue
    if area < 42 and elong < 1.8 and local < 0.16:
        continue
    keep[labels==lab]=True
skel=skeletonize(keep).astype(np.uint8)*255
contours,_=cv2.findContours(skel, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
paths=[]

def add_path(kind, pts, min_len_px=10.0):
    if len(pts)<2: return
    arr=np.array(pts,dtype=np.float32).reshape((-1,1,2))
    approx=cv2.approxPolyDP(arr, epsilon=1.0, closed=False).reshape((-1,2))
    clean=[(float(approx[0][0]),float(approx[0][1]))]
    length=0.0
    last=clean[-1]
    for x,y in approx[1:]:
        p=(float(x),float(y)); d=math.hypot(p[0]-last[0],p[1]-last[1])
        if d>=0.9:
            clean.append(p); length+=d; last=p
    if len(clean)>=2 and length>=min_len_px:
        paths.append((kind,clean))

for cnt in contours:
    if len(cnt)<6: continue
    x,y,ww,hh=cv2.boundingRect(cnt)
    arc=cv2.arcLength(cnt, False)
    if arc<12 or ww<2 or hh<2: continue
    local=float(np.mean(tone[max(0,y):min(h,y+hh), max(0,x):min(w,x+ww)]))
    ymid=(y+0.5*hh)/h
    # In very bright sky, keep only longer deliberate strokes.
    if ymid<0.33 and (arc<38 or local<0.065):
        continue
    if local<0.045 and arc<30:
        continue
    pts=[(float(p[0][0]),float(p[0][1])) for p in cnt]
    add_path('source_stroke', pts, min_len_px=10.0)

# Add page border from source style.
margin=20
paths.append(('outer_border',[(margin,margin),(w-margin,margin),(w-margin,h-margin),(margin,h-margin),(margin,margin)]))

def pix_to_mm(p):
    x,y=p
    return (x/w*DRAW_W_MM, -(TOP_MM+y/h*DRAW_H_MM))
mm_paths=[]
for kind,pts in paths:
    mm=[pix_to_mm(p) for p in pts]
    clean=[mm[0]]; length=0.0
    for p in mm[1:]:
        last=clean[-1]; d=math.hypot(p[0]-last[0],p[1]-last[1])
        if d>=0.10:
            clean.append(p); length+=d
    if len(clean)>=2 and length>=0.50:
        mm_paths.append((kind,clean))
# greedy nearest order
rem=mm_paths[:]; ordered=[]; pos=(0.0,0.0)
while rem:
    bi=0;br=False;bd=1e9
    for i,(_,pts) in enumerate(rem):
        d0=math.hypot(pts[0][0]-pos[0],pts[0][1]-pos[1])
        d1=math.hypot(pts[-1][0]-pos[0],pts[-1][1]-pos[1])
        if d0<bd: bi=i;br=False;bd=d0
        if d1<bd: bi=i;br=True;bd=d1
    kind,pts=rem.pop(bi)
    if br: pts=list(reversed(pts))
    ordered.append((kind,pts)); pos=pts[-1]
name='gemini_adaptive_source_trace_a4'
nc=OUT/f'{name}.nc'; gcode=OUT/f'{name}.gcode'
lines=['; adaptive source trace A4','G21','G90',f'G0 Z{PEN_UP_Z:.3f}',f'F{TRAVEL_F}']
draw=0.0; travel=0.0; last=(0,0)
for kind,pts in ordered:
    st=pts[0]; travel+=math.hypot(st[0]-last[0],st[1]-last[1])
    lines.append(f'G0 X{st[0]:.3f} Y{st[1]:.3f}')
    lines.append(f'G1 Z{PEN_DOWN_Z:.3f} F{DRAW_F}')
    prev=st
    for x,y in pts[1:]:
        draw+=math.hypot(x-prev[0],y-prev[1]); lines.append(f'G1 X{x:.3f} Y{y:.3f}'); prev=(x,y)
    lines.append(f'G0 Z{PEN_UP_Z:.3f}'); last=pts[-1]
lines.append('M2')
text='\n'.join(lines)+'\n'
nc.write_text(text,encoding='ascii'); gcode.write_text(text,encoding='ascii')
# render
page_w=int(DRAW_W_MM*PX_PER_MM); page_h=int(SAFE_H_MM*PX_PER_MM)
def mm_to_px(p): return (int(round(p[0]*PX_PER_MM)), int(round((-p[1])*PX_PER_MM)))
def render(path, gray_mode=False):
    im=Image.new('RGB',(page_w,page_h),'white'); dr=ImageDraw.Draw(im)
    dr.rectangle([0,0,page_w-1,page_h-1], outline=(225,225,225), width=1)
    for kind,pts in ordered:
        pix=[mm_to_px(p) for p in pts]
        col=(0,0,0) if not gray_mode else ((32,32,32) if kind=='outer_border' else (70,70,70))
        dr.line(pix, fill=col, width=1)
    im.save(path)
black_png=OUT/f'{name}_preview_black_actual.png'; gray_png=OUT/f'{name}_preview_pressure_gray.png'
render(black_png,False); render(gray_png,True)
def png_to_pdf(png,pdf):
    c=canvas.Canvas(str(pdf), pagesize=A4); pw,ph=A4; m=16
    im=Image.open(png); sc=min((pw-2*m)/im.width,(ph-2*m)/im.height); dw=im.width*sc; dh=im.height*sc
    c.drawImage(str(png),(pw-dw)/2,(ph-dh)/2,dw,dh); c.showPage(); c.save()
black_pdf=OUT/f'{name}_preview_black_actual.pdf'; gray_pdf=OUT/f'{name}_preview_pressure_gray.pdf'
png_to_pdf(black_png,black_pdf); png_to_pdf(gray_png,gray_pdf)
counts=Counter(k for k,_ in ordered)
(OUT/'README_result.txt').write_text(
    'ADAPTIVE SOURCE TRACE A4 package\n'
    f'source: {SRC}\n'
    f'nc: {nc}\n'
    f'gcode: {gcode}\n'
    f'preview_black_actual_png: {black_png}\n'
    f'preview_black_actual_pdf: {black_pdf}\n'
    f'preview_pressure_gray_png: {gray_png}\n'
    f'preview_pressure_gray_pdf: {gray_pdf}\n'
    f'paths_total: {len(ordered)}\n'
    f'kind_counts: {dict(counts)}\n'
    f'draw_length_m: {draw/1000:.2f}\n'
    f'travel_length_m: {travel/1000:.2f}\n'
    f'estimated_time_min_ideal: {(draw/(DRAW_F/60)+travel/(TRAVEL_F/60))/60:.1f}\n'
    'algorithm_note: adaptive local threshold extracts actual pencil strokes from source, then skeletonizes and filters paper grain.\n',
    encoding='utf-8')
print('ADAPTIVE SOURCE TRACE A4 package')
print('paths_total:', len(ordered))
print('kind_counts:', dict(counts))
print('draw_length_m:', round(draw/1000,2))
print('travel_length_m:', round(travel/1000,2))
print('estimated_time_min_ideal:', round((draw/(DRAW_F/60)+travel/(TRAVEL_F/60))/60,1))
print('preview:', black_png)
print('pdf:', black_pdf)
print('nc:', nc)
