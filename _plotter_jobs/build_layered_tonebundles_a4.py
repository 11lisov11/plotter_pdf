from __future__ import annotations
from pathlib import Path
import math, random
from collections import Counter

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from scipy.ndimage import gaussian_filter, binary_closing
from skimage.morphology import remove_small_objects, skeletonize

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_layered_tonebundles_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
random.seed(260622)
np.random.seed(260622)

DRAW_W_MM=180.0; DRAW_H_MM=240.0; TOP_MM=20.0; SAFE_H_MM=280.0
PEN_UP_Z=3.5; PEN_DOWN_Z=0.0; TRAVEL_F=3000; DRAW_F=1200; PX_PER_MM=4

img0=Image.open(SRC).convert('L')
w0,h0=img0.size
W=900; H=int(round(h0*W/w0))
img=img0.resize((W,H), Image.Resampling.LANCZOS)
w,h=img.size
gray=np.asarray(img,dtype=np.float32)/255.0
bg=gaussian_filter(gray,sigma=28)
flat=np.clip(gray/np.maximum(bg,0.58),0,1)
flat=np.clip((flat-0.04)/0.96,0,1)
tone_raw=1.0-flat
tone=np.clip((gaussian_filter(tone_raw,sigma=2.1)-0.016)/0.37,0,1)
tone_dark=gaussian_filter(tone_raw,sigma=0.9)
yy,xx=np.mgrid[0:h,0:w]
xn=xx/max(1,w-1); yn=yy/max(1,h-1)
hair_mask=((((xn-0.535)/0.155)**2+((yn-0.640)/0.170)**2)<1.0)|((((xn-0.635)/0.185)**2+((yn-0.660)/0.120)**2)<1.0)
jacket_mask=((((xn-0.455)/0.170)**2+((yn-0.845)/0.185)**2)<1.0)|((((xn-0.365)/0.110)**2+((yn-0.785)/0.110)**2)<1.0)
arm_mask=((((xn-0.365)/0.105)**2+((yn-0.725)/0.085)**2)<1.0)
figure_mask=hair_mask|jacket_mask|arm_mask
sky_mask=yn<0.330
forest_mask=(yn>0.310)&(yn<0.525)&(~figure_mask)
field_mask=(yn>0.440)&(yn<0.790)&(~figure_mask)
grass_mask=(yn>0.635)&(~figure_mask)

paths=[]
def add_path(kind, pts, min_len=7.0):
    if len(pts)<2: return
    clean=[pts[0]]; length=0.0; last=pts[0]
    for p in pts[1:]:
        d=math.hypot(p[0]-last[0],p[1]-last[1])
        if d>=0.7:
            clean.append(p); length+=d; last=p
    if len(clean)>=2 and length>=min_len:
        paths.append((kind,clean))

def simplify_add(kind, pts, eps=0.9, min_len=7.0):
    if len(pts)<2: return
    arr=np.array(pts,dtype=np.float32).reshape((-1,1,2))
    ap=cv2.approxPolyDP(arr,epsilon=eps,closed=False).reshape((-1,2))
    add_path(kind,[(float(x),float(y)) for x,y in ap],min_len)

def clip_add(kind, pts, mask, min_len=7.0):
    run=[]
    for x,y in pts:
        ix,iy=int(round(x)),int(round(y))
        if 0<=ix<w and 0<=iy<h and mask[iy,ix]: run.append((x,y))
        else:
            if run: simplify_add(kind,run,0.85,min_len)
            run=[]
    if run: simplify_add(kind,run,0.85,min_len)

def line_pts(cx,cy,ang,length,off=0.0,wob=0.8,n=6):
    e=(math.cos(ang),math.sin(ang)); p=(-math.sin(ang),math.cos(ang))
    pts=[]
    for i in range(n):
        t=i/(n-1)-0.5
        ww=wob*math.sin((i/(n-1))*math.pi)
        pts.append((cx+e[0]*length*t+p[0]*(off+ww), cy+e[1]*length*t+p[1]*(off+ww)))
    return pts

def tone_bundles(kind, mask, threshold, tile, max_groups, angles, length_rng, parallel_max, parallel_gap, jitter, gamma, seed):
    rng=random.Random(seed)
    for y0 in range(0,h,tile):
        for x0 in range(0,w,tile):
            y1=min(h,y0+tile); x1=min(w,x0+tile)
            m=mask[y0:y1,x0:x1]
            if np.count_nonzero(m)<max(10,int(tile*tile*0.10)): continue
            vals=tone[y0:y1,x0:x1][m]
            if vals.size==0: continue
            avg=float(np.mean(vals)); mx=float(np.max(vals))
            if avg<threshold and mx<threshold+0.05: continue
            strength=max(0.0,min(1.0,((0.65*avg+0.35*mx)-threshold)/max(1e-6,1-threshold)))**gamma
            want=max_groups*strength
            groups=int(want)
            if rng.random()<want-groups: groups+=1
            if groups<=0 and mx>threshold+0.10: groups=1
            if groups<=0: continue
            ys,xs=np.where(m)
            weights=np.maximum(tone[y0:y1,x0:x1][ys,xs],0.001)
            weights=weights/float(weights.sum())
            for _ in range(groups):
                idx=int(np.random.choice(np.arange(len(xs)),p=weights))
                cx=x0+float(xs[idx])+rng.uniform(-0.12,0.12)*tile
                cy=y0+float(ys[idx])+rng.uniform(-0.12,0.12)*tile
                if not (0<=int(cx)<w and 0<=int(cy)<h and mask[int(cy),int(cx)]): continue
                loc=float(tone[int(cy),int(cx)])
                npar=1+int(min(parallel_max-1, math.floor((0.25*strength+0.75*loc)*(parallel_max-1)+0.35)))
                ang=math.radians(rng.choice(angles)+rng.uniform(-jitter,jitter))
                base_len=rng.uniform(*length_rng)*(0.70+0.75*loc)
                for k in range(npar):
                    off=(k-(npar-1)/2.0)*parallel_gap*rng.uniform(0.85,1.15)
                    pts=line_pts(cx,cy,ang,base_len,off=off,wob=rng.uniform(-0.8,0.8),n=6)
                    clip_add(kind,pts,mask,min_len=max(6.5,length_rng[0]*0.42))

# 1. Deliberate dark source contours, filtered hard to avoid paper grain.
binary=(tone_dark>0.160)
binary=binary_closing(binary,structure=np.ones((2,2),dtype=bool))
binary=remove_small_objects(binary,min_size=36)
skel=skeletonize(binary).astype(np.uint8)*255
contours,_=cv2.findContours(skel,cv2.RETR_LIST,cv2.CHAIN_APPROX_NONE)
for cnt in contours:
    if len(cnt)<10: continue
    x,y,ww,hh=cv2.boundingRect(cnt); arc=cv2.arcLength(cnt,False)
    if arc<20 or ww<3 or hh<3: continue
    ymid=(y+0.5*hh)/h
    local=float(np.mean(tone[max(0,y):min(h,y+hh),max(0,x):min(w,x+ww)]))
    if ymid<0.33 and (arc<75 or local<0.14): continue
    if local<0.085 and arc<62: continue
    simplify_add('dark_contour',[(float(p[0][0]),float(p[0][1])) for p in cnt],1.15,14)

# 2. Tonal layer bundles. Dark = close parallel strokes; light = sparse single strokes.
tone_bundles('forest_light_bundle',forest_mask,0.045,28,2,[-62,58],(12,25),1,2.2,10,0.80,101)
tone_bundles('forest_dark_bundle',forest_mask,0.135,20,3,[-65,55,86],(10,24),3,2.0,12,0.75,102)
tone_bundles('forest_deep_bundle',forest_mask,0.250,16,3,[-68,52,88],(8,19),4,1.7,14,0.70,103)
tone_bundles('field_light_bundle',field_mask,0.035,34,2,[-14,-9],(24,62),1,2.4,8,0.85,201)
tone_bundles('field_mid_bundle',field_mask,0.125,28,2,[-15,16],(18,46),2,2.2,8,0.85,202)
tone_bundles('grass_bundle',grass_mask,0.055,22,3,[-82,76,-68],(10,29),2,1.8,13,0.85,301)
tone_bundles('jacket_light_bundle',jacket_mask,0.055,16,3,[-52,44],(15,34),2,1.8,8,0.82,401)
tone_bundles('jacket_dark_bundle',jacket_mask,0.170,13,4,[-55,43,-74],(12,30),4,1.55,9,0.72,402)
tone_bundles('hair_shadow_bundle',hair_mask,0.125,18,2,[-72],(16,34),2,1.8,6,0.80,501)

# 3. Hand-controlled sky clusters. Kept sparse, because light sky must remain light.
def sky_cluster(cx,cy,rx,ry,angle,count,length_frac,cross=False):
    rng=random.Random(int(cx*13000+cy*17000+count*41))
    ang=math.radians(angle); e=(math.cos(ang),math.sin(ang)); p=(-math.sin(ang),math.cos(ang))
    for i in range(count):
        band=(i/max(1,count-1)-0.5)*2
        offp=band*ry*h*0.70+rng.uniform(-0.008,0.008)*h
        offe=rng.uniform(-0.50,0.50)*rx*w
        cxp=cx*w+e[0]*offe+p[0]*offp; cyp=cy*h+e[1]*offe+p[1]*offp
        if (((cxp/w-cx)/rx)**2+((cyp/h-cy)/ry)**2)>1.08: continue
        length=length_frac*w*rng.uniform(0.55,1.02)
        pts=line_pts(cxp,cyp,ang,length,off=0,wob=rng.uniform(-1.4,1.4),n=8)
        simplify_add('sky_cluster_cross' if cross else 'sky_cluster',pts,0.7,13)
for args in [
    (0.125,0.095,0.155,0.052,-35,24,0.058,False),(0.150,0.235,0.180,0.050,-26,16,0.052,False),
    (0.310,0.125,0.130,0.048,-32,13,0.046,False),(0.505,0.285,0.135,0.047,-22,11,0.043,False),
    (0.775,0.175,0.165,0.055,-27,19,0.052,False),(0.825,0.285,0.150,0.050,-25,13,0.047,False),
    (0.180,0.270,0.160,0.040,30,6,0.038,True),(0.790,0.300,0.145,0.040,28,6,0.037,True)]: sky_cluster(*args)

# 4. Semantic long hair strands and jacket folds.
def bezier(p0,p1,p2,p3,n=54):
    pts=[]
    for i in range(n):
        t=i/(n-1)
        pts.append(((1-t)**3*p0[0]+3*(1-t)**2*t*p1[0]+3*(1-t)*t*t*p2[0]+t**3*p3[0],
                    (1-t)**3*p0[1]+3*(1-t)**2*t*p1[1]+3*(1-t)*t*t*p2[1]+t**3*p3[1]))
    return pts
rng=random.Random(811)
for i in range(96):
    t=i/95
    crown=((0.505+0.075*(t-0.5)+rng.uniform(-0.010,0.010))*w,(0.515+0.045*math.sin(t*math.pi)+rng.uniform(-0.006,0.008))*h)
    if i<40:
        end=((0.410+0.145*t+rng.uniform(-0.012,0.012))*w,(0.735+0.030*math.sin(t*4)+rng.uniform(-0.012,0.012))*h)
        c1=((0.440+0.06*t)*w,(0.590+rng.uniform(-0.015,0.015))*h); c2=((0.395+0.11*t)*w,(0.690+rng.uniform(-0.018,0.018))*h)
    else:
        tt=(i-40)/55; end=((0.545+0.220*tt+rng.uniform(-0.013,0.013))*w,(0.700+0.080*math.sin(tt*math.pi)+rng.uniform(-0.016,0.016))*h)
        c1=((0.545+0.075*tt)*w,(0.580+rng.uniform(-0.016,0.016))*h); c2=((0.610+0.180*tt)*w,(0.650+rng.uniform(-0.018,0.018))*h)
    clip_add('hair_flow',bezier(crown,c1,c2,end,58),hair_mask,16)
for i in range(34):
    t=i/33; x0=(0.325+0.235*t+rng.uniform(-0.008,0.008))*w; y0=(0.690+0.035*math.sin(t*math.pi)+rng.uniform(-0.006,0.006))*h
    x3=(0.350+0.195*t+rng.uniform(-0.010,0.010))*w; y3=(0.970+rng.uniform(-0.008,0.008))*h
    clip_add('jacket_fold',bezier((x0,y0),((x0+x3)/2-0.05*w,0.780*h),((x0+x3)/2+0.03*w,0.900*h),(x3,y3),46),jacket_mask,18)

# 5. Border.
m=18; add_path('outer_border',[(m,m),(w-m,m),(w-m,h-m),(m,h-m),(m,m)],10)

# Convert/order/write/render.
def pix_to_mm(p): return (p[0]/w*DRAW_W_MM, -(TOP_MM+p[1]/h*DRAW_H_MM))
mm_paths=[]
for kind,pts in paths:
    mm=[pix_to_mm(p) for p in pts]
    clean=[mm[0]]; length=0.0
    for p in mm[1:]:
        last=clean[-1]; d=math.hypot(p[0]-last[0],p[1]-last[1])
        if d>=0.12: clean.append(p); length+=d
    if len(clean)>=2 and length>=0.60: mm_paths.append((kind,clean))
rem=mm_paths[:]; ordered=[]; pos=(0,0)
while rem:
    bi=0; br=False; bd=1e9
    for i,(_,pts) in enumerate(rem):
        d0=math.hypot(pts[0][0]-pos[0],pts[0][1]-pos[1]); d1=math.hypot(pts[-1][0]-pos[0],pts[-1][1]-pos[1])
        if d0<bd: bi=i; br=False; bd=d0
        if d1<bd: bi=i; br=True; bd=d1
    kind,pts=rem.pop(bi)
    if br: pts=list(reversed(pts))
    ordered.append((kind,pts)); pos=pts[-1]
name='gemini_layered_tonebundles_a4'
nc=OUT/f'{name}.nc'; gcode=OUT/f'{name}.gcode'
lines=['; layered tone bundles A4','G21','G90',f'G0 Z{PEN_UP_Z:.3f}',f'F{TRAVEL_F}']
draw=travel=0.0; last=(0,0)
for kind,pts in ordered:
    st=pts[0]; travel+=math.hypot(st[0]-last[0],st[1]-last[1]); lines.append(f'G0 X{st[0]:.3f} Y{st[1]:.3f}'); lines.append(f'G1 Z{PEN_DOWN_Z:.3f} F{DRAW_F}')
    prev=st
    for x,y in pts[1:]: draw+=math.hypot(x-prev[0],y-prev[1]); lines.append(f'G1 X{x:.3f} Y{y:.3f}'); prev=(x,y)
    lines.append(f'G0 Z{PEN_UP_Z:.3f}'); last=pts[-1]
lines.append('M2'); text='\n'.join(lines)+'\n'; nc.write_text(text,encoding='ascii'); gcode.write_text(text,encoding='ascii')
page_w=int(DRAW_W_MM*PX_PER_MM); page_h=int(SAFE_H_MM*PX_PER_MM)
def mm_to_px(p): return (int(round(p[0]*PX_PER_MM)), int(round((-p[1])*PX_PER_MM)))
def render(path,gray=False):
    im=Image.new('RGB',(page_w,page_h),'white'); dr=ImageDraw.Draw(im); dr.rectangle([0,0,page_w-1,page_h-1],outline=(225,225,225),width=1)
    for kind,pts in ordered:
        pix=[mm_to_px(p) for p in pts]
        if gray:
            col=(32,32,32) if ('dark' in kind or kind in {'outer_border','hair_flow','jacket_fold','dark_contour'}) else (82,82,82) if ('forest' in kind or 'jacket' in kind or 'hair' in kind) else (132,132,132)
        else: col=(0,0,0)
        dr.line(pix,fill=col,width=1)
    im.save(path)
black_png=OUT/f'{name}_preview_black_actual.png'; gray_png=OUT/f'{name}_preview_pressure_gray.png'; render(black_png,False); render(gray_png,True)
def png_to_pdf(png,pdf):
    c=canvas.Canvas(str(pdf),pagesize=A4); pw,ph=A4; mar=16; im=Image.open(png); sc=min((pw-2*mar)/im.width,(ph-2*mar)/im.height); dw=im.width*sc; dh=im.height*sc
    c.drawImage(str(png),(pw-dw)/2,(ph-dh)/2,dw,dh); c.showPage(); c.save()
black_pdf=OUT/f'{name}_preview_black_actual.pdf'; gray_pdf=OUT/f'{name}_preview_pressure_gray.pdf'; png_to_pdf(black_png,black_pdf); png_to_pdf(gray_png,gray_pdf)
counts=Counter(k for k,_ in ordered)
(OUT/'README_result.txt').write_text('LAYERED TONEBUNDLES A4 package\n'+f'source: {SRC}\n'+f'nc: {nc}\n'+f'gcode: {gcode}\n'+f'preview_black_actual_png: {black_png}\n'+f'preview_black_actual_pdf: {black_pdf}\n'+f'preview_pressure_gray_png: {gray_png}\n'+f'preview_pressure_gray_pdf: {gray_pdf}\n'+f'paths_total: {len(ordered)}\n'+f'kind_counts: {dict(counts)}\n'+f'draw_length_m: {draw/1000:.2f}\n'+f'travel_length_m: {travel/1000:.2f}\n'+f'estimated_time_min_ideal: {(draw/(DRAW_F/60)+travel/(TRAVEL_F/60))/60:.1f}\n'+'algorithm_note: tone layers; dark cells receive close parallel mini-bundles, light cells sparse single strokes.\n',encoding='utf-8')
print('LAYERED TONEBUNDLES A4 package')
print('paths_total:',len(ordered)); print('kind_counts:',dict(counts)); print('draw_length_m:',round(draw/1000,2)); print('travel_length_m:',round(travel/1000,2)); print('estimated_time_min_ideal:',round((draw/(DRAW_F/60)+travel/(TRAVEL_F/60))/60,1)); print('preview:',black_png); print('pdf:',black_pdf); print('nc:',nc)
