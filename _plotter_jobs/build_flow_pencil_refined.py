from __future__ import annotations
import math, shutil, hashlib
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
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_flow_pencil_refined_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT / "source_input_copy.jpg")
img_bgr = cv2.imread(str(SRC), cv2.IMREAD_COLOR)
if img_bgr is None:
    raise SystemExit("cannot read source")
gray0 = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
mask_page = gray0 < 252
ys, xs = np.where(mask_page)
x0, x1 = int(xs.min()), int(xs.max())
y0, y1 = int(ys.min()), int(ys.max())
pad = 8
x0=max(0,x0-pad); y0=max(0,y0-pad); x1=min(gray0.shape[1]-1,x1+pad); y1=min(gray0.shape[0]-1,y1+pad)
gray = gray0[y0:y1+1, x0:x1+1]
H, W = gray.shape
Image.fromarray(gray).save(OUT / "source_cropped_gray.png")

# Normalize paper and remove scan grain.
denoised = cv2.fastNlMeansDenoising(gray, None, 8, 7, 21)
bg = cv2.GaussianBlur(denoised.astype(np.float32), (0,0), 36)
norm = np.clip(denoised.astype(np.float32) / np.maximum(bg,1) * 246, 0, 255).astype(np.uint8)
ink = (255 - norm).astype(np.float32) / 255.0
ink = cv2.GaussianBlur(ink, (0,0), 0.45)
# Smooth density = where tone must be built. No raw pixel dust.
density = np.maximum(cv2.GaussianBlur(ink,(0,0),2.4)*0.82, cv2.GaussianBlur(ink,(0,0),8.0)*1.18)
lo, hi = np.percentile(density, [41, 99.4])
density = np.clip((density-lo)/max(1e-6, hi-lo), 0, 1)
density = np.power(density, 0.74)
Image.fromarray(np.uint8(255*(1-density))).save(OUT / "density_debug.png")
# Direction field from real graphite: tangent to strongest gradients, smoothed.
g = cv2.GaussianBlur(norm.astype(np.float32), (0,0), 1.6)
gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
# line direction is perpendicular to gradient
orient = np.arctan2(gy, gx) + math.pi/2
# Smooth orientation using double-angle representation.
c2 = cv2.GaussianBlur(np.cos(2*orient), (0,0), 5.0)
s2 = cv2.GaussianBlur(np.sin(2*orient), (0,0), 5.0)
orient = 0.5*np.arctan2(s2, c2)

WORK_W, WORK_H = 180.0, 280.0
DRAW_W = 176.0
scale = DRAW_W / W
DRAW_H = H * scale
if DRAW_H > 270.0:
    DRAW_H = 270.0
    scale = DRAW_H / H
    DRAW_W = W * scale
XOFF = (WORK_W-DRAW_W)/2.0
YTOP = (WORK_H-DRAW_H)/2.0
def p2m(y: float, x: float) -> tuple[float,float]:
    return XOFF + x*scale, -(YTOP + y*scale)
def press(t: float, bias: float=0.0):
    v = max(0.0, min(1.0, t+bias))
    if v < .18: return 10.62, 215, 2350
    if v < .32: return 10.86, 178, 2200
    if v < .48: return 11.10, 130, 2000
    if v < .66: return 11.38, 82, 1700
    return 11.72, 30, 1450

def h01(*vals: int) -> float:
    s = ':'.join(map(str, vals)).encode()
    return int.from_bytes(hashlib.sha1(s).digest()[:4], 'big') / 0xffffffff

paths: list[dict] = []
# Source centerline trace for real contours and details.
line_mask = (ink > 0.073).astype(np.uint8)
num, labels, stats, _ = cv2.connectedComponentsWithStats(line_mask, 8)
clean = np.zeros_like(line_mask)
for i in range(1, num):
    area = int(stats[i, cv2.CC_STAT_AREA]); w = int(stats[i, cv2.CC_STAT_WIDTH]); h = int(stats[i, cv2.CC_STAT_HEIGHT])
    if area >= 5 and max(w,h) >= 4:
        clean[labels==i] = 1
skel = skeletonize(clean.astype(bool)) if skeletonize is not None else clean.astype(bool)
Image.fromarray(np.uint8(255-skel.astype(np.uint8)*255)).save(OUT / "skeleton_debug.png")
coords = np.argwhere(skel)
coord_set = set((int(y),int(x)) for y,x in coords)
N8=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
def neigh(p):
    y,x=p; out=[]
    for dy,dx in N8:
        q=(y+dy,x+dx)
        if q in coord_set: out.append(q)
    return out
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
def dpline(pt,a,b):
    py,px=pt; ay,ax=a; by,bx=b
    vx=bx-ax; vy=by-ay; wx=px-ax; wy=py-ay
    c1=vx*wx+vy*wy
    if c1<=0: return math.hypot(px-ax,py-ay)
    c2=vx*vx+vy*vy
    if c2<=c1: return math.hypot(px-bx,py-by)
    t=c1/c2
    return math.hypot(px-(ax+t*vx), py-(ay+t*vy))
def rdp(points, eps):
    if len(points)<3: return points
    a=points[0]; b=points[-1]; md=-1; mi=-1
    for i in range(1,len(points)-1):
        d=dpline(points[i],a,b)
        if d>md: md=d; mi=i
    if md>eps: return rdp(points[:mi+1],eps)[:-1]+rdp(points[mi:],eps)
    return [a,b]
for p in pix_paths:
    if len(p)<3: continue
    arr=np.array(p)
    vals=ink[arr[:,0],arr[:,1]]; dens=density[arr[:,0],arr[:,1]]
    avg=float(vals.mean()); mx=float(vals.max()); davg=float(dens.mean())
    L=sum(math.hypot(p[i+1][1]-p[i][1],p[i+1][0]-p[i][0]) for i in range(len(p)-1))
    ymean=float(arr[:,0].mean())/H
    if L<5: continue
    if avg<.055 and L<24: continue
    if ymean<.34 and avg<.082 and L<36: continue
    simp=rdp([(int(y),int(x)) for y,x in p], .88)
    pts=[p2m(y,x) for y,x in simp]
    z,shade,feed=press(max(davg, mx*2.0))
    paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':'real_trace','tone':davg})

# Region-aware deterministic line segments. No random pixel noise, no full-page grid.
def add_parallel_segments(name, angle_deg, spacing, threshold, y0f, y1f, min_len, max_gap, bias=0.0, x0f=0.0, x1f=1.0, keep=1.0, phase=0.0, jitter=1.8):
    theta=math.radians(angle_deg); ux=math.cos(theta); uy=math.sin(theta); nx=-uy; ny=ux
    x0p=x0f*W; x1p=x1f*W; y0p=y0f*H; y1p=y1f*H
    corners=[(x0p,y0p),(x1p,y0p),(x0p,y1p),(x1p,y1p)]
    projs=[x*nx+y*ny for x,y in corners]
    minp,maxp=min(projs)-spacing,max(projs)+spacing
    diag=math.hypot(W,H); count=int((maxp-minp)/spacing)+1
    made=0
    for si in range(count):
        if h01(si, int(angle_deg*10), 123) > keep: continue
        off=minp+si*spacing+phase+(h01(si,77)-0.5)*jitter
        cx=(x0p+x1p)/2; cy=(y0p+y1p)/2
        cproj=cx*nx+cy*ny; px=cx+(off-cproj)*nx; py=cy+(off-cproj)*ny
        cur=[]; gap=0; segs=[]
        for t in np.arange(-diag,diag,2.0):
            x=px+t*ux; y=py+t*uy
            xi=int(round(x)); yi=int(round(y))
            if xi<0 or xi>=W or yi<0 or yi>=H or xi<x0p or xi>x1p or yi<y0p or yi>y1p:
                if cur:
                    gap+=1
                    if gap>max_gap:
                        if len(cur)>=2: segs.append(cur)
                        cur=[]; gap=0
                continue
            d=float(density[yi,xi])
            ok=d>=threshold
            if yi/H < .32 and d < threshold+.14: ok=False
            if ok:
                cur.append((yi,xi,d)); gap=0
            elif cur:
                gap+=1
                if gap>max_gap:
                    if len(cur)>=2: segs.append(cur)
                    cur=[]; gap=0
        if cur and len(cur)>=2: segs.append(cur)
        for seg in segs:
            L=sum(math.hypot(seg[i+1][1]-seg[i][1],seg[i+1][0]-seg[i][0]) for i in range(len(seg)-1))
            if L<min_len: continue
            # split very long segments into pencil-length pieces with small gaps
            max_piece=70 if name.startswith('field') else 42
            pieces=[]
            if L>max_piece*1.4:
                step=max(2,int(max_piece/2))
                for st in range(0,len(seg)-2,step):
                    en=min(len(seg), st+step+int(step*.55))
                    if en-st>=2: pieces.append(seg[st:en])
            else:
                pieces=[seg]
            for piece in pieces:
                if len(piece)<2: continue
                tone=float(np.mean([q[2] for q in piece]))
                z,shade,feed=press(tone,bias)
                sample_step=max(1,int(len(piece)/8))
                sample=piece[::sample_step]
                if sample[-1] != piece[-1]: sample.append(piece[-1])
                pts=[p2m(y,x) for y,x,_ in sample]
                paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
                made+=1
    return made

counts={}
# Sparse sky/cloud hatches.
counts['sky_cloud'] = add_parallel_segments('sky_cloud', 24, 31, .31, .02,.36, 26, 2, -.12, keep=.58, phase=3)
counts['sky_cloud_cross'] = add_parallel_segments('sky_cloud_cross', -25, 38, .43, .02,.36, 22, 2, -.08, keep=.45, phase=11)
# Forest: structured, not random.
counts['forest_slant_a'] = add_parallel_segments('forest_slant_a', 63, 13, .22, .34,.61, 12, 3, -.03, keep=.88)
counts['forest_slant_b'] = add_parallel_segments('forest_slant_b', -57, 16, .35, .34,.61, 10, 3, .04, keep=.72, phase=5)
counts['forest_vertical_dark'] = add_parallel_segments('forest_vertical_dark', 88, 12, .50, .34,.62, 9, 2, .12, keep=.70, phase=3)
# Field: long calm lines.
counts['field_flow_a'] = add_parallel_segments('field_flow_a', -11, 9.5, .15, .50,.77, 34, 5, -.08, keep=.82)
counts['field_flow_b'] = add_parallel_segments('field_flow_b', 14, 16, .34, .50,.78, 26, 3, -.02, keep=.58, phase=6)
# Lower grass: more vertical but with controlled density.
counts['grass_light'] = add_parallel_segments('grass_light', 78, 9, .17, .68,.99, 8, 2, -.05, keep=.70)
counts['grass_dark'] = add_parallel_segments('grass_dark', 103, 12, .34, .68,.99, 8, 2, .06, keep=.66, phase=5)
counts['grass_cross_dark'] = add_parallel_segments('grass_cross_dark', -62, 15, .52, .68,.99, 8, 2, .14, keep=.52, phase=7)
# Figure/jacket: denser but calmer than random organic max.
counts['figure_hatch_a'] = add_parallel_segments('figure_hatch_a', 57, 7.8, .30, .60,.99, 9, 3, .04, .25,.66, keep=.86)
counts['figure_hatch_b'] = add_parallel_segments('figure_hatch_b', -48, 9.2, .43, .60,.99, 9, 2, .13, .25,.66, keep=.72, phase=4)
counts['figure_deep'] = add_parallel_segments('figure_deep', 8, 8, .62, .60,.99, 9, 2, .20, .25,.66, keep=.65, phase=2)
# Hair gets a few flow-field strokes instead of black scribble.
def add_hair_flow():
    made=0
    for y in range(int(.53*H), int(.80*H), 9):
        for x in range(int(.40*W), int(.75*W), 10):
            d=float(density[y,x])
            if d<.20 or h01(x,y,700)>min(1.0,(d-.16)*1.65): continue
            angle=math.degrees(float(orient[y,x]))
            # constrain to hair-like downward curves
            if angle < -20: angle += 180
            if angle > 150: angle -= 180
            angle = max(55, min(125, angle))
            theta=math.radians(angle)
            length=18+38*d
            bend=(h01(x,y,701)-.5)*6
            pts=[]
            for t in np.linspace(-.5,.5,7):
                px=x+t*length*math.cos(theta)+bend*math.sin(t*math.pi)*math.cos(theta+math.pi/2)
                py=y+t*length*math.sin(theta)+bend*math.sin(t*math.pi)*math.sin(theta+math.pi/2)
                xi=int(round(px)); yi=int(round(py))
                if 0<=xi<W and 0<=yi<H:
                    pts.append(p2m(yi,xi))
            if len(pts)>=2:
                z,shade,feed=press(d,-.02)
                paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':'hair_flow','tone':d})
                made+=1
    return made
counts['hair_flow'] = add_hair_flow()

# Border.
border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
paths.insert(0, {'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5})
# Reorder nearest, keep border first.
def reorder(paths_in):
    first=paths_in[:1]; rest=paths_in[1:]; ordered=[]; cur=first[0]['pts'][-1]
    while rest:
        best=0; rev=False; bd=1e18; limit=min(len(rest),1700)
        for i in range(limit):
            p=rest[i]; a=p['pts'][0]; b=p['pts'][-1]
            da=math.hypot(a[0]-cur[0],a[1]-cur[1]); db=math.hypot(b[0]-cur[0],b[1]-cur[1])
            if da<bd: best=i; rev=False; bd=da
            if db<bd: best=i; rev=True; bd=db
        p=rest.pop(best)
        if rev:
            p=dict(p); p['pts']=list(reversed(p['pts']))
        ordered.append(p); cur=p['pts'][-1]
    return first+ordered
paths = reorder(paths)
kind_counts = Counter(p['kind'] for p in paths)

def render(path: Path, pressure=True, black=False, dark=False):
    dpi=230; cw=int(WORK_W/25.4*dpi); ch=int(WORK_H/25.4*dpi)
    im=Image.new('RGB',(cw,ch),(255,255,255) if not dark else (24,24,24)); d=ImageDraw.Draw(im)
    def mm(x,y): return int(round(x/25.4*dpi)), int(round((-y)/25.4*dpi))
    d.rectangle([mm(0,0), mm(WORK_W,-WORK_H)], outline=(238,238,238) if not dark else (66,66,66), width=1)
    for p in paths:
        pts=[mm(x,y) for x,y in p['pts']]
        if len(pts)<2: continue
        if black: col=(0,0,0) if not dark else (235,235,235)
        elif pressure:
            s=int(p['shade']); col=(s,s,s) if not dark else (max(28,255-s),)*3
        else: col=(55,55,55)
        d.line(pts, fill=col, width=1)
    im.save(path); im.save(path.with_suffix('.pdf'), 'PDF', resolution=dpi)
render(OUT/'gemini_flow_pencil_refined_preview_pressure_gray.png', True)
render(OUT/'gemini_flow_pencil_refined_preview_black_actual.png', False, True)
render(OUT/'gemini_flow_pencil_refined_preview_dark_pressure.png', True, False, True)
# NC/GCODE
SAFE=13.0
lines=['; gemini_flow_pencil_refined_a4','; structured flow hatching: dark close lines, light sparse, less random noise','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
draw=0.0; travel=0.0; last=(0.0,0.0)
for p in paths:
    pts=p['pts']; a=pts[0]
    travel += math.hypot(a[0]-last[0], a[1]-last[1])
    lines.append(f'; {p["kind"]} tone={p["tone"]:.3f} z={p["z"]:.2f}')
    lines.append(f'G0 Z{SAFE:.2f}'); lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}'); lines.append(f'G1 Z{p["z"]:.2f} F900')
    prev=a
    for x,y in pts[1:]:
        draw += math.hypot(x-prev[0], y-prev[1])
        lines.append(f'G1 X{x:.3f} Y{y:.3f} F{p["feed"]}')
        prev=(x,y)
    lines.append(f'G0 Z{SAFE:.2f}')
    last=pts[-1]
lines += ['G0 X0.000 Y0.000', f'G0 Z{SAFE:.2f}', 'M2']
(OUT/'gemini_flow_pencil_refined_a4.nc').write_text('\n'.join(lines)+'\n', encoding='utf-8')
(OUT/'gemini_flow_pencil_refined_a4.gcode').write_text('\n'.join(lines)+'\n', encoding='utf-8')
readme=f"""FLOW PENCIL REFINED A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
paths: {len(paths)}
kind_counts: {dict(kind_counts)}
layer_counts: {counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Closest match requires calibrated Z pressure and pencil/soft pen.
algorithm_note: real source strokes are traced; dark tonal areas are filled with structured region-aware hatches rather than random pixel noise. Light sky/cloud areas are intentionally sparse.
files:
- gemini_flow_pencil_refined_preview_pressure_gray.png/pdf
- gemini_flow_pencil_refined_preview_black_actual.png/pdf
- gemini_flow_pencil_refined_preview_dark_pressure.png/pdf
- gemini_flow_pencil_refined_a4.nc
- gemini_flow_pencil_refined_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme, encoding='utf-8')
print(readme)
