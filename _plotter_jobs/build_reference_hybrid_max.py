from __future__ import annotations
import math, shutil
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import cv2
try:
    from skimage.morphology import skeletonize as sk_skeletonize
except Exception:
    sk_skeletonize=None

SRC=Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_reference_hybrid_max_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT/'source_input_copy.jpg')
img_bgr=cv2.imread(str(SRC), cv2.IMREAD_COLOR)
if img_bgr is None: raise SystemExit('cannot read source')
gray=cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
# Crop around actual drawing/page lines.
bg_mask=gray<252
ys,xs=np.where(bg_mask)
x0,x1=int(xs.min()),int(xs.max()); y0,y1=int(ys.min()),int(ys.max())
pad=8; x0=max(0,x0-pad); y0=max(0,y0-pad); x1=min(gray.shape[1]-1,x1+pad); y1=min(gray.shape[0]-1,y1+pad)
gray=gray[y0:y1+1,x0:x1+1]
H,W=gray.shape
Image.fromarray(gray).save(OUT/'source_cropped_gray.png')
# Normalize paper; build ink and density maps.
g=gray.astype(np.float32)
bg=cv2.GaussianBlur(g,(0,0),34)
norm=np.clip(g/np.maximum(bg,1)*246,0,255).astype(np.uint8)
ink=(255-norm).astype(np.float32)
ink=cv2.GaussianBlur(ink,(0,0),0.45)
# Contrast-stretched darkness for pressure mapping.
p10,p995=np.percentile(ink,[10,99.5])
ink_s=np.clip((ink-p10)/max(1,p995-p10),0,1)
density=cv2.GaussianBlur(ink_s,(0,0),5.5)
density=np.clip((density-np.percentile(density,35))/max(1e-5,np.percentile(density,99)-np.percentile(density,35)),0,1)
Image.fromarray(np.uint8(255*(1-density))).save(OUT/'density_debug.png')

# Centerline trace of actual strokes. Hysteresis-ish: darker short lines survive, faint lines need length.
mask=(ink_s>0.105).astype(np.uint8)
num,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
clean=np.zeros_like(mask)
for i in range(1,num):
    area=int(stats[i,cv2.CC_STAT_AREA]); w=int(stats[i,cv2.CC_STAT_WIDTH]); h=int(stats[i,cv2.CC_STAT_HEIGHT])
    if area>=5 and max(w,h)>=4: clean[labels==i]=1
skel=sk_skeletonize(clean.astype(bool)) if sk_skeletonize is not None else clean.astype(bool)
Image.fromarray(np.uint8(255-skel.astype(np.uint8)*255)).save(OUT/'skeleton_debug.png')
coords=np.argwhere(skel); coord_set=set((int(y),int(x)) for y,x in coords)
N8=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
def neigh(p):
    y,x=p; r=[]
    for dy,dx in N8:
        q=(y+dy,x+dx)
        if q in coord_set: r.append(q)
    return r
deg={p:len(neigh(p)) for p in coord_set}
visited=set(); pix_paths=[]
def ek(a,b): return (a,b) if a<=b else (b,a)
def trace(a,b):
    path=[a,b]; visited.add(ek(a,b)); prev=a; cur=b
    while True:
        ns=[q for q in neigh(cur) if q!=prev]
        if deg.get(cur,0)!=2 or not ns: break
        q=ns[0]
        if ek(cur,q) in visited: break
        visited.add(ek(cur,q)); path.append(q); prev,cur=cur,q
    return path
for p,d in list(deg.items()):
    if d!=2:
        for q in neigh(p):
            if ek(p,q) not in visited: pix_paths.append(trace(p,q))
for p in list(coord_set):
    for q in neigh(p):
        if ek(p,q) not in visited: pix_paths.append(trace(p,q))

def dist_point_line(pt,a,b):
    py,px=pt; ay,ax=a; by,bx=b; vx=bx-ax; vy=by-ay; wx=px-ax; wy=py-ay
    c1=vx*wx+vy*wy
    if c1<=0: return math.hypot(px-ax,py-ay)
    c2=vx*vx+vy*vy
    if c2<=c1: return math.hypot(px-bx,py-by)
    t=c1/c2; return math.hypot(px-(ax+t*vx), py-(ay+t*vy))
def rdp(points,eps):
    if len(points)<3: return points
    a=points[0]; b=points[-1]; md=-1; mi=-1
    for i in range(1,len(points)-1):
        d=dist_point_line(points[i],a,b)
        if d>md: md=d; mi=i
    if md>eps: return rdp(points[:mi+1],eps)[:-1]+rdp(points[mi:],eps)
    return [a,b]

work_w,work_h=180.0,280.0; draw_w=176.0; scale=draw_w/W; draw_h=H*scale
if draw_h>270: draw_h=270; scale=draw_h/H; draw_w=W*scale
xoff=(work_w-draw_w)/2; ytop=(work_h-draw_h)/2
def p2m(y,x): return xoff+x*scale, -(ytop+y*scale)

def level_from_dark(v):
    if v<0.18: return 10.65,205,2300
    if v<0.32: return 10.90,165,2100
    if v<0.50: return 11.15,115,1900
    if v<0.70: return 11.45,70,1650
    return 11.75,25,1400

paths=[]
for p in pix_paths:
    if len(p)<3: continue
    arr=np.array(p); vals=ink_s[arr[:,0],arr[:,1]]; avg=float(vals.mean()); mx=float(vals.max())
    l=sum(math.hypot(p[i+1][1]-p[i][1],p[i+1][0]-p[i][0]) for i in range(len(p)-1))
    ymean=float(arr[:,0].mean())/H
    if l<5.5: continue
    if avg<0.16 and l<22: continue
    if ymean<0.35 and avg<0.20 and l<35: continue
    simp=rdp([(int(y),int(x)) for y,x in p],0.9)
    pts=[p2m(y,x) for y,x in simp]
    z,shade,feed=level_from_dark(max(avg,mx*0.55))
    paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':'trace','tone':avg})

# Add controlled tonal hatching from smoothed density map. This replaces random noise with readable pencil tone.
def add_hatch(angle_deg, spacing_px, thresh, z, shade, feed, min_len_px, max_gap_px, region='all'):
    theta=math.radians(angle_deg); ux=math.cos(theta); uy=math.sin(theta); nx=-uy; ny=ux
    corners=[(0,0),(W-1,0),(0,H-1),(W-1,H-1)]
    projs=[x*nx+y*ny for x,y in corners]
    minp,maxp=min(projs)-spacing_px,max(projs)+spacing_px
    steps=int((maxp-minp)/spacing_px)+1
    added=0
    # y-band heuristics keep sky light and give field/hair/body cleaner density.
    for si in range(steps):
        off=minp+si*spacing_px
        # Find long line segment through rectangle by sampling t across diagonal.
        diag=math.hypot(W,H)
        cx=W/2; cy=H/2
        # point on normal near center
        center_proj=cx*nx+cy*ny; px=cx+(off-center_proj)*nx; py=cy+(off-center_proj)*ny
        samples=[]; active=[]; gap=0; current=[]
        for ti in np.linspace(-diag,diag,int(diag/2.2)):
            x=px+ti*ux; y=py+ti*uy
            xi=int(round(x)); yi=int(round(y))
            if xi<0 or xi>=W or yi<0 or yi>=H:
                if current:
                    gap+=1
                    if gap>max_gap_px:
                        if len(current)>=2: samples.append(current)
                        current=[]; gap=0
                continue
            d=float(density[yi,xi])
            yy=yi/H
            ok=d>=thresh
            if region=='lower' and yy<0.38: ok=False
            if region=='dark' and d<thresh: ok=False
            # avoid filling sky with accidental haze unless very strong cloud tone
            if yy<0.32 and d<thresh+0.16: ok=False
            if ok:
                current.append((yi,xi)); gap=0
            elif current:
                gap+=1
                if gap>max_gap_px:
                    if len(current)>=2: samples.append(current)
                    current=[]; gap=0
        if current and len(current)>=2: samples.append(current)
        for seg in samples:
            # decimate and length filter
            if len(seg)<min_len_px: continue
            length=sum(math.hypot(seg[i+1][1]-seg[i][1],seg[i+1][0]-seg[i][0]) for i in range(len(seg)-1))
            if length<min_len_px: continue
            pts=[p2m(y,x) for y,x in seg[::max(1,int(len(seg)/10))]]
            if len(pts)<2: pts=[p2m(*seg[0]),p2m(*seg[-1])]
            paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':'hatch','tone':thresh})
            added+=1
    return added

hatch_counts={}
hatch_counts['mid_terrain']=add_hatch(-12,22,0.28,10.90,175,2100,20,3,'lower')
hatch_counts['forest_dark_a']=add_hatch(55,14,0.43,11.35,82,1700,16,3,'dark')
hatch_counts['forest_dark_b']=add_hatch(-48,18,0.58,11.65,38,1450,14,3,'dark')
hatch_counts['soft_long']=add_hatch(18,30,0.22,10.70,205,2300,35,3,'lower')

# single drawing border
border=[(xoff,-ytop),(xoff+draw_w,-ytop),(xoff+draw_w,-(ytop+draw_h)),(xoff,-(ytop+draw_h)),(xoff,-ytop)]
paths.insert(0,{'pts':border,'z':11.15,'shade':115,'feed':1900,'kind':'border','tone':0.5})

# Order nearest with bounded scan; keep border first.
def reorder(rest):
    first=rest[:1]; arr=rest[1:]; ordered=[]; cur=first[0]['pts'][-1]
    while arr:
        best=0; rev=False; bd=1e9
        limit=min(len(arr),1400)
        for i in range(limit):
            p=arr[i]; a=p['pts'][0]; b=p['pts'][-1]
            da=math.hypot(a[0]-cur[0],a[1]-cur[1]); db=math.hypot(b[0]-cur[0],b[1]-cur[1])
            if da<bd: best=i; rev=False; bd=da
            if db<bd: best=i; rev=True; bd=db
        p=arr.pop(best)
        if rev: p=dict(p); p['pts']=list(reversed(p['pts']))
        ordered.append(p); cur=p['pts'][-1]
    return first+ordered
paths=reorder(paths)

# Render previews
from collections import Counter
kind_counts=Counter(p['kind'] for p in paths)
def render(path, pressure=True, dark=False, black=False):
    dpi=230; cw=int(work_w/25.4*dpi); ch=int(work_h/25.4*dpi)
    im=Image.new('RGB',(cw,ch),(255,255,255) if not dark else (24,24,24)); d=ImageDraw.Draw(im)
    def mm(x,y): return int(round(x/25.4*dpi)), int(round((-y)/25.4*dpi))
    d.rectangle([mm(0,0),mm(work_w,-work_h)],outline=(236,236,236) if not dark else (64,64,64),width=1)
    for p in paths:
        pts=[mm(x,y) for x,y in p['pts']]
        if len(pts)<2: continue
        if black: col=(0,0,0) if not dark else (235,235,235)
        elif pressure:
            s=int(p['shade']); col=(s,s,s) if not dark else (max(30,255-s),)*3
        else: col=(60,60,60)
        d.line(pts,fill=col,width=1)
    im.save(path)
    im.save(Path(path).with_suffix('.pdf'),'PDF',resolution=dpi)
render(OUT/'gemini_reference_hybrid_max_preview_pressure_gray.png',True,False,False)
render(OUT/'gemini_reference_hybrid_max_preview_black_actual.png',False,False,True)
render(OUT/'gemini_reference_hybrid_max_preview_dark_pressure.png',True,True,False)

# G-code
SAFE=13.00; lines=['; gemini_reference_hybrid_max_a4','; real extracted pencil strokes + controlled density hatching; variable Z pressure','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
draw=0; travel=0; last=(0,0)
for p in paths:
    pts=p['pts']; a=pts[0]; travel+=math.hypot(a[0]-last[0],a[1]-last[1])
    lines.append(f'; {p["kind"]} z={p["z"]:.2f}')
    lines.append(f'G0 Z{SAFE:.2f}'); lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}'); lines.append(f'G1 Z{p["z"]:.2f} F900')
    prev=a
    for x,y in pts[1:]:
        draw+=math.hypot(x-prev[0],y-prev[1]); lines.append(f'G1 X{x:.3f} Y{y:.3f} F{p["feed"]}'); prev=(x,y)
    lines.append(f'G0 Z{SAFE:.2f}'); last=pts[-1]
lines += ['G0 X0.000 Y0.000',f'G0 Z{SAFE:.2f}','M2']
(OUT/'gemini_reference_hybrid_max_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_reference_hybrid_max_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""REFERENCE HYBRID MAX A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {work_w:.1f} x {work_h:.1f}
drawing_size_mm: {draw_w:.2f} x {draw_h:.2f}
paths: {len(paths)}
kind_counts: {dict(kind_counts)}
hatch_counts: {hatch_counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. For closest tonal match use pencil/soft pen and run pressure calibration first.
why_less_noise: real source strokes are traced as centerlines; paper grain is filtered; dark tone is added by smooth directional hatch layers, not random pixel noise.
files:
- gemini_reference_hybrid_max_preview_pressure_gray.png/pdf
- gemini_reference_hybrid_max_preview_black_actual.png/pdf
- gemini_reference_hybrid_max_preview_dark_pressure.png/pdf
- gemini_reference_hybrid_max_a4.nc
- gemini_reference_hybrid_max_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
