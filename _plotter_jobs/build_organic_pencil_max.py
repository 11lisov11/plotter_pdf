from __future__ import annotations
import math, shutil, random
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
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_organic_pencil_max_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT / 'source_input_copy.jpg')
img_bgr = cv2.imread(str(SRC), cv2.IMREAD_COLOR)
if img_bgr is None: raise SystemExit('cannot read source')
gray0 = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
mask_page = gray0 < 252
ys, xs = np.where(mask_page)
x0, x1 = int(xs.min()), int(xs.max()); y0, y1 = int(ys.min()), int(ys.max())
pad=8; x0=max(0,x0-pad); y0=max(0,y0-pad); x1=min(gray0.shape[1]-1,x1+pad); y1=min(gray0.shape[0]-1,y1+pad)
gray = gray0[y0:y1+1, x0:x1+1]
H, W = gray.shape
Image.fromarray(gray).save(OUT/'source_cropped_gray.png')
# Normalize and denoise.
denoised = cv2.fastNlMeansDenoising(gray, None, 8, 7, 21)
bg = cv2.GaussianBlur(denoised.astype(np.float32), (0,0), 36)
norm = np.clip(denoised.astype(np.float32) / np.maximum(bg,1) * 246, 0, 255).astype(np.uint8)
ink = (255 - norm).astype(np.float32) / 255.0
ink = cv2.GaussianBlur(ink, (0,0), 0.45)
d1 = cv2.GaussianBlur(ink, (0,0), 2.2)
d2 = cv2.GaussianBlur(ink, (0,0), 7.5)
density = np.maximum(d1*0.78, d2*1.16)
lo, hi = np.percentile(density, [41, 99.4])
density = np.clip((density-lo)/max(1e-6,hi-lo),0,1)
density = np.power(density,0.70)
Image.fromarray(np.uint8(255*(1-density))).save(OUT/'density_debug.png')

WORK_W, WORK_H = 180.0, 280.0
DRAW_W = 176.0
scale = DRAW_W / W
DRAW_H = H * scale
if DRAW_H > 270:
    DRAW_H = 270.0; scale = DRAW_H/H; DRAW_W = W*scale
XOFF=(WORK_W-DRAW_W)/2; YTOP=(WORK_H-DRAW_H)/2
def p2m(y,x): return XOFF+x*scale, -(YTOP+y*scale)
def level(tone,bias=0.0):
    v=max(0,min(1,tone+bias))
    if v < .18: return 10.62,215,2350
    if v < .32: return 10.86,178,2200
    if v < .48: return 11.10,130,2000
    if v < .66: return 11.38,80,1700
    return 11.72,30,1450

paths=[]
# Real stroke centerlines, used as contours and natural hair/cloud/grass marks.
mask=(ink>.072).astype(np.uint8)
num,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
clean=np.zeros_like(mask)
for i in range(1,num):
    area=int(stats[i,cv2.CC_STAT_AREA]); w=int(stats[i,cv2.CC_STAT_WIDTH]); h=int(stats[i,cv2.CC_STAT_HEIGHT])
    if area>=5 and max(w,h)>=4: clean[labels==i]=1
skel=skeletonize(clean.astype(bool)) if skeletonize is not None else clean.astype(bool)
Image.fromarray(np.uint8(255-skel.astype(np.uint8)*255)).save(OUT/'skeleton_debug.png')
coords=np.argwhere(skel); coord_set=set((int(y),int(x)) for y,x in coords)
N8=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
def nb(p):
    y,x=p; r=[]
    for dy,dx in N8:
        q=(y+dy,x+dx)
        if q in coord_set: r.append(q)
    return r
deg={p:len(nb(p)) for p in coord_set}; visited=set(); pix_paths=[]
def ek(a,b): return (a,b) if a<=b else (b,a)
def trace(a,b):
    path=[a,b]; visited.add(ek(a,b)); prev=a; cur=b
    while True:
        ns=[q for q in nb(cur) if q!=prev]
        if deg.get(cur,0)!=2 or not ns: break
        q=ns[0]
        if ek(cur,q) in visited: break
        visited.add(ek(cur,q)); path.append(q); prev,cur=cur,q
    return path
for p,d in list(deg.items()):
    if d!=2:
        for q in nb(p):
            if ek(p,q) not in visited: pix_paths.append(trace(p,q))
for p in list(coord_set):
    for q in nb(p):
        if ek(p,q) not in visited: pix_paths.append(trace(p,q))
def dl(pt,a,b):
    py,px=pt; ay,ax=a; by,bx=b; vx=bx-ax; vy=by-ay; wx=px-ax; wy=py-ay
    c1=vx*wx+vy*wy
    if c1<=0: return math.hypot(px-ax,py-ay)
    c2=vx*vx+vy*vy
    if c2<=c1: return math.hypot(px-bx,py-by)
    t=c1/c2; return math.hypot(px-(ax+t*vx),py-(ay+t*vy))
def rdp(points,eps):
    if len(points)<3: return points
    a=points[0]; b=points[-1]; md=-1; mi=-1
    for i in range(1,len(points)-1):
        d=dl(points[i],a,b)
        if d>md: md=d; mi=i
    if md>eps: return rdp(points[:mi+1],eps)[:-1]+rdp(points[mi:],eps)
    return [a,b]
for p in pix_paths:
    if len(p)<3: continue
    arr=np.array(p); vals=ink[arr[:,0],arr[:,1]]; dens=density[arr[:,0],arr[:,1]]
    avg=float(vals.mean()); mx=float(vals.max()); davg=float(dens.mean())
    L=sum(math.hypot(p[i+1][1]-p[i][1],p[i+1][0]-p[i][0]) for i in range(len(p)-1))
    ymean=float(arr[:,0].mean())/H
    if L<5: continue
    if avg<.055 and L<24: continue
    if ymean<.34 and avg<.082 and L<36: continue
    simp=rdp([(int(y),int(x)) for y,x in p],.88)
    pts=[p2m(y,x) for y,x in simp]
    z,shade,feed=level(max(davg,mx*2.0))
    paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':'real_trace','tone':davg})

# Deterministic organic pencil strokes. Close in dark zones, sparse in light zones, not a global grid.
def h01(i,j,k=0):
    n=(i*73856093)^(j*19349663)^(k*83492791)
    n=(n ^ (n >> 13))*1274126177
    return ((n ^ (n >> 16)) & 0xffffffff)/0xffffffff

def add_organic(name, y0f,y1f,x0f,x1f, threshold, step_px, angles, len_min,len_max,
                prob_scale=1.0, bias=0.0, min_active=0.55, seed=0):
    made=0
    y0=int(y0f*H); y1=int(y1f*H); x0=int(x0f*W); x1=int(x1f*W)
    sy=max(2,int(step_px)); sx=max(2,int(step_px))
    for gy,y in enumerate(range(y0,y1,sy)):
        for gx,x in enumerate(range(x0,x1,sx)):
            jx=(h01(gx,gy,seed)-.5)*step_px*.9; jy=(h01(gx,gy,seed+1)-.5)*step_px*.9
            cx=int(round(x+jx)); cy=int(round(y+jy))
            if cx<0 or cx>=W or cy<0 or cy>=H: continue
            d=float(density[cy,cx])
            if d<threshold: continue
            p=min(1.0, ((d-threshold)/max(1e-6,1-threshold))**0.50 * prob_scale)
            if h01(gx,gy,seed+2)>p: continue
            ai=int(h01(gx,gy,seed+3)*len(angles))%len(angles)
            angle=angles[ai] + (h01(gx,gy,seed+4)-.5)*20.0
            theta=math.radians(angle); ux=math.cos(theta); uy=math.sin(theta); nx=-uy; ny=ux
            length=(len_min+(len_max-len_min)*(d**.8))*(.75+.55*h01(gx,gy,seed+5))
            # Build a lightly bent pencil stroke with 5 points.
            raw=[]
            samples=[]
            ok_count=0
            for m,t in enumerate(np.linspace(-.5,.5,7)):
                curve=(math.sin((t+.5)*math.pi)*2-1)*(h01(gx,gy,seed+6)-.5)*2.4
                px=cx+t*length*ux+curve*nx
                py=cy+t*length*uy+curve*ny
                xi=int(round(px)); yi=int(round(py))
                if xi<0 or xi>=W or yi<0 or yi>=H:
                    continue
                local=float(density[yi,xi])
                samples.append(local)
                if local>=threshold*.72: ok_count+=1
                raw.append((yi,xi))
            if len(raw)<2 or not samples or ok_count/len(samples)<min_active: continue
            tone=float(np.mean(samples))
            z,shade,feed=level(tone,bias)
            pts=[p2m(y,x) for y,x in raw]
            paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
            made+=1
    return made

organic_counts={}
organic_counts['sky_sparse'] = add_organic('sky_sparse', .02,.36, .00,1.0, .30, 24, [24,-22,12], 14,34, .45, -.12, .60, 10)
organic_counts['forest_mid'] = add_organic('forest_mid', .34,.60, .00,1.0, .18, 8.5, [62,78,-56,44,96], 9,24, .78, -.03, .50, 20)
organic_counts['forest_dark'] = add_organic('forest_dark', .34,.62, .00,1.0, .38, 5.8, [64,-54,86,35], 10,28, 1.00, .08, .52, 30)
organic_counts['field_long'] = add_organic('field_long', .50,.76, .00,1.0, .13, 9.5, [-13,-8,14], 30,78, .65, -.08, .58, 40)
organic_counts['field_dark'] = add_organic('field_dark', .52,.79, .00,1.0, .31, 7.5, [-16,16,-4], 18,54, .75, .02, .55, 50)
organic_counts['grass_light'] = add_organic('grass_light', .68,.98, .00,1.0, .13, 7.0, [70,82,96,58,110], 7,19, .70, -.06, .46, 60)
organic_counts['grass_dark'] = add_organic('grass_dark', .68,.99, .00,1.0, .35, 5.2, [72,96,-58,55,115], 8,22, 1.00, .10, .48, 70)
organic_counts['figure_mid'] = add_organic('figure_mid', .60,.98, .24,.66, .23, 5.6, [54,-42,8,72], 10,28, .95, .04, .48, 80)
organic_counts['figure_deep'] = add_organic('figure_deep', .60,.99, .24,.66, .48, 4.0, [58,-52,4,82], 12,32, 1.00, .18, .46, 90)
organic_counts['hair_flow'] = add_organic('hair_flow', .53,.78, .40,.74, .20, 6.0, [72,86,102,118], 16,42, .85, -.02, .50, 100)

# Border anchors the picture, as in reference.
border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
paths.insert(0,{'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5})

def reorder(paths_in):
    first=paths_in[:1]; rest=paths_in[1:]; ordered=[]; cur=first[0]['pts'][-1]
    while rest:
        bi=0; br=False; bd=1e18; limit=min(len(rest),1700)
        for i in range(limit):
            p=rest[i]; a=p['pts'][0]; b=p['pts'][-1]
            da=math.hypot(a[0]-cur[0],a[1]-cur[1]); db=math.hypot(b[0]-cur[0],b[1]-cur[1])
            if da<bd: bi=i; br=False; bd=da
            if db<bd: bi=i; br=True; bd=db
        p=rest.pop(bi)
        if br: p=dict(p); p['pts']=list(reversed(p['pts']))
        ordered.append(p); cur=p['pts'][-1]
    return first+ordered
paths=reorder(paths)
kind_counts=Counter(p['kind'] for p in paths)

def render(path:Path, pressure=True, black=False, dark=False):
    dpi=230; cw=int(WORK_W/25.4*dpi); ch=int(WORK_H/25.4*dpi)
    im=Image.new('RGB',(cw,ch),(255,255,255) if not dark else (24,24,24)); d=ImageDraw.Draw(im)
    def mm(x,y): return int(round(x/25.4*dpi)), int(round((-y)/25.4*dpi))
    d.rectangle([mm(0,0),mm(WORK_W,-WORK_H)],outline=(238,238,238) if not dark else (66,66,66),width=1)
    for p in paths:
        pts=[mm(x,y) for x,y in p['pts']]
        if len(pts)<2: continue
        if black: col=(0,0,0) if not dark else (235,235,235)
        elif pressure:
            s=int(p['shade']); col=(s,s,s) if not dark else (max(28,255-s),)*3
        else: col=(55,55,55) if not dark else (225,225,225)
        d.line(pts,fill=col,width=1)
    im.save(path); im.save(path.with_suffix('.pdf'),'PDF',resolution=dpi)
render(OUT/'gemini_organic_pencil_max_preview_pressure_gray.png', True)
render(OUT/'gemini_organic_pencil_max_preview_black_actual.png', False, True)
render(OUT/'gemini_organic_pencil_max_preview_dark_pressure.png', True, False, True)

SAFE=13.0; lines=['; gemini_organic_pencil_max_a4','; organic tonal pencil strokes: dark close, light sparse, no regular grid','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
draw=0.0; travel=0.0; last=(0.0,0.0)
for p in paths:
    pts=p['pts']; a=pts[0]; travel+=math.hypot(a[0]-last[0],a[1]-last[1])
    lines.append(f'; {p["kind"]} tone={p["tone"]:.3f} z={p["z"]:.2f}')
    lines.append(f'G0 Z{SAFE:.2f}'); lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}'); lines.append(f'G1 Z{p["z"]:.2f} F900')
    prev=a
    for x,y in pts[1:]:
        draw+=math.hypot(x-prev[0],y-prev[1]); lines.append(f'G1 X{x:.3f} Y{y:.3f} F{p["feed"]}'); prev=(x,y)
    lines.append(f'G0 Z{SAFE:.2f}'); last=pts[-1]
lines += ['G0 X0.000 Y0.000', f'G0 Z{SAFE:.2f}', 'M2']
(OUT/'gemini_organic_pencil_max_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_organic_pencil_max_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""ORGANIC PENCIL MAX A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
paths: {len(paths)}
kind_counts: {dict(kind_counts)}
organic_counts: {organic_counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Closest match requires calibrated Z pressure and pencil/soft pen.
algorithm_note: real source strokes are traced as centerlines; tone is built by local organic strokes, not global grid hatching. Dark zones receive many close strokes; light zones sparse strokes.
files:
- gemini_organic_pencil_max_preview_pressure_gray.png/pdf
- gemini_organic_pencil_max_preview_black_actual.png/pdf
- gemini_organic_pencil_max_preview_dark_pressure.png/pdf
- gemini_organic_pencil_max_a4.nc
- gemini_organic_pencil_max_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
