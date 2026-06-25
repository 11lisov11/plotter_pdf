from __future__ import annotations
import math, os, shutil, heapq
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_actual_stroke_trace_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT / "source_input_copy.jpg")

try:
    import cv2
except Exception as e:
    raise SystemExit(f"OpenCV is required for this generator: {e}")
try:
    from skimage.morphology import skeletonize as sk_skeletonize
except Exception:
    sk_skeletonize = None

img_bgr = cv2.imread(str(SRC), cv2.IMREAD_COLOR)
if img_bgr is None:
    raise SystemExit(f"cannot read source: {SRC}")
img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

# Crop to the actual sheet/sketch area: ignore the gray app margins but keep the border.
# We use non-background bbox with padding, then force portrait page ratio from the original.
bg_mask = gray < 252
ys, xs = np.where(bg_mask)
if len(xs):
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    pad = 8
    x0 = max(0, x0-pad); y0=max(0,y0-pad); x1=min(gray.shape[1]-1,x1+pad); y1=min(gray.shape[0]-1,y1+pad)
else:
    x0=y0=0; x1=gray.shape[1]-1; y1=gray.shape[0]-1
crop_rgb = img_rgb[y0:y1+1, x0:x1+1]
crop_gray = gray[y0:y1+1, x0:x1+1]
Image.fromarray(crop_rgb).save(OUT / "source_cropped.png")

# Background normalization: separates pencil from paper tint and JPEG noise.
g = crop_gray.astype(np.float32)
bg = cv2.GaussianBlur(g, (0, 0), 35.0)
norm = g / np.maximum(bg, 1) * 246.0
norm = np.clip(norm, 0, 255).astype(np.uint8)
# Ink darkness, with local contrast enhancement but conservative thresholds.
ink = 255 - norm
ink = cv2.GaussianBlur(ink, (0, 0), 0.45)
# Remove tiny pixel grain while preserving long pencil strokes.
ink_u8 = np.clip(ink,0,255).astype(np.uint8)
# Adaptive mask: keep real graphite lines, not paper texture. The low mask catches faint cloud strokes,
# but later path filters require length/contrast so speckles die.
mask = (ink_u8 >= 12).astype(np.uint8)
# suppress isolated dust, then lightly close broken pencil strokes
num, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
clean = np.zeros_like(mask)
for i in range(1, num):
    area = int(stats[i, cv2.CC_STAT_AREA])
    w = int(stats[i, cv2.CC_STAT_WIDTH]); h = int(stats[i, cv2.CC_STAT_HEIGHT])
    if area >= 5 and max(w,h) >= 4:
        clean[labels == i] = 1
# keep border and long faint lines, but no dense paper freckles
mask = clean.astype(bool)

# Skeletonize to centerlines: this is the key difference from noisy contour tracing.
def zhang_suen(binary: np.ndarray) -> np.ndarray:
    im = binary.astype(np.uint8).copy()
    changed = True
    h,w = im.shape
    while changed:
        changed = False
        for step in (0,1):
            to_del=[]
            P = im
            ys2, xs2 = np.where(P[1:-1,1:-1] == 1)
            ys2 = ys2 + 1; xs2 = xs2 + 1
            for y,x in zip(ys2, xs2):
                p2=P[y-1,x]; p3=P[y-1,x+1]; p4=P[y,x+1]; p5=P[y+1,x+1]
                p6=P[y+1,x]; p7=P[y+1,x-1]; p8=P[y,x-1]; p9=P[y-1,x-1]
                ns = int(p2+p3+p4+p5+p6+p7+p8+p9)
                if ns < 2 or ns > 6:
                    continue
                seq=[p2,p3,p4,p5,p6,p7,p8,p9,p2]
                trans=sum((seq[k]==0 and seq[k+1]==1) for k in range(8))
                if trans != 1:
                    continue
                if step == 0:
                    if p2*p4*p6 != 0 or p4*p6*p8 != 0:
                        continue
                else:
                    if p2*p4*p8 != 0 or p2*p6*p8 != 0:
                        continue
                to_del.append((y,x))
            if to_del:
                for y,x in to_del:
                    im[y,x]=0
                changed=True
    return im.astype(bool)

if sk_skeletonize is not None:
    skel = sk_skeletonize(mask)
else:
    skel = zhang_suen(mask)
Image.fromarray((255 - skel.astype(np.uint8)*255)).save(OUT / "skeleton_debug.png")

H, W = skel.shape
# Build graph of skeleton pixels.
coords = np.argwhere(skel)
coord_set = set((int(y), int(x)) for y,x in coords)
N8 = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
def neigh(p):
    y,x=p
    out=[]
    for dy,dx in N8:
        q=(y+dy,x+dx)
        if q in coord_set:
            out.append(q)
    return out

deg = {p: len(neigh(p)) for p in coord_set}
visited_edges=set()
paths=[]

def edge_key(a,b):
    return (a,b) if a<=b else (b,a)

def trace_from(start, nxt):
    path=[start, nxt]
    visited_edges.add(edge_key(start,nxt))
    prev=start; cur=nxt
    while True:
        ns=[q for q in neigh(cur) if q != prev]
        if deg.get(cur,0) != 2 or not ns:
            break
        q=ns[0]
        ek=edge_key(cur,q)
        if ek in visited_edges:
            break
        visited_edges.add(ek)
        path.append(q)
        prev,cur=cur,q
    return path

# Start from endpoints and junctions to avoid spaghetti paths.
starts=[p for p,d in deg.items() if d != 2]
for p in starts:
    for q in neigh(p):
        if edge_key(p,q) not in visited_edges:
            paths.append(trace_from(p,q))
# Loops left over.
for p in list(coord_set):
    for q in neigh(p):
        if edge_key(p,q) not in visited_edges:
            paths.append(trace_from(p,q))

# RDP simplification and filtering.
def dist_point_line(pt, a, b):
    py,px=pt; ay,ax=a; by,bx=b
    vx=bx-ax; vy=by-ay
    wx=px-ax; wy=py-ay
    c1=vx*wx+vy*wy
    if c1<=0:
        return math.hypot(px-ax, py-ay)
    c2=vx*vx+vy*vy
    if c2<=c1:
        return math.hypot(px-bx, py-by)
    t=c1/c2
    projx=ax+t*vx; projy=ay+t*vy
    return math.hypot(px-projx, py-projy)

def rdp(points, eps):
    if len(points)<3:
        return points
    a=points[0]; b=points[-1]
    maxd=-1; idx=-1
    for i in range(1,len(points)-1):
        d=dist_point_line(points[i],a,b)
        if d>maxd: maxd=d; idx=i
    if maxd>eps:
        return rdp(points[:idx+1],eps)[:-1]+rdp(points[idx:],eps)
    return [a,b]

# Convert pixel length and darkness into keep/drop. Sky/faint strokes must be long; dark details may be shorter.
filtered=[]
for p in paths:
    if len(p) < 3:
        continue
    arr=np.array(p)
    vals=ink_u8[arr[:,0], arr[:,1]].astype(np.float32)
    avg=float(vals.mean())
    mx=float(vals.max())
    length_px=sum(math.hypot(p[i+1][1]-p[i][1], p[i+1][0]-p[i][0]) for i in range(len(p)-1))
    # kill random short dust, keep intentional dark short hatches/grass
    if length_px < 5.5:
        continue
    if avg < 16 and length_px < 18:
        continue
    if avg < 13 and length_px < 35:
        continue
    # top sky: be extra strict to keep airy clouds, not freckles
    y_mean=float(arr[:,0].mean())/H
    if y_mean < 0.33 and avg < 20 and length_px < 28:
        continue
    simp=rdp([(int(y),int(x)) for y,x in p], 0.95)
    if len(simp) >= 2:
        filtered.append((simp, avg, mx, length_px))

# Map to A4 plotter work area. Preserve reference proportions, fill area with margins.
work_w, work_h = 180.0, 280.0
margin=2.0
draw_w=176.0
scale=draw_w / W
draw_h=H * scale
if draw_h > 270.0:
    draw_h=270.0; scale=draw_h/H; draw_w=W*scale
xoff=(work_w-draw_w)/2.0
ytop=(work_h-draw_h)/2.0

def pix_to_mm(y,x):
    return xoff + x*scale, -(ytop + y*scale)

mm_paths=[]
for simp,avg,mx,lpx in filtered:
    pts=[pix_to_mm(y,x) for y,x in simp]
    # clamp and remove tiny moves
    clean_pts=[]
    for x,y in pts:
        if not clean_pts or math.hypot(x-clean_pts[-1][0], y-clean_pts[-1][1]) >= 0.08:
            clean_pts.append((x,y))
    if len(clean_pts)>=2:
        # pressure: faint strokes very light, dark strokes strong. No random opacity in machine, Z carries tone.
        if avg < 18:
            z=10.65; shade=205; feed=2300
        elif avg < 26:
            z=10.90; shade=170; feed=2100
        elif avg < 38:
            z=11.15; shade=130; feed=1900
        elif avg < 58:
            z=11.45; shade=85; feed=1650
        else:
            z=11.75; shade=35; feed=1400
        mm_paths.append({'pts':clean_pts,'avg':avg,'mx':mx,'z':z,'shade':shade,'feed':feed,'len_px':lpx})

# Add one clean picture border from the source page; it anchors composition and reduces visual chaos.
border=[(xoff,-ytop),(xoff+draw_w,-ytop),(xoff+draw_w,-(ytop+draw_h)),(xoff,-(ytop+draw_h)),(xoff,-ytop)]
mm_paths.insert(0, {'pts':border,'avg':40,'mx':80,'z':11.15,'shade':115,'feed':1900,'len_px':0})

# Nearest-neighbor reorder to avoid wasting time, preserving line direction if closer reversed.
def reorder(paths):
    rest=paths[:]
    ordered=[]
    cur=(0.0,0.0)
    while rest:
        best_i=0; best_rev=False; best_d=1e9
        for i,p in enumerate(rest[:1200]):  # bounded scan for speed; enough locality after extraction
            a=p['pts'][0]; b=p['pts'][-1]
            da=math.hypot(a[0]-cur[0], a[1]-cur[1])
            db=math.hypot(b[0]-cur[0], b[1]-cur[1])
            if da<best_d:
                best_i=i; best_rev=False; best_d=da
            if db<best_d:
                best_i=i; best_rev=True; best_d=db
        p=rest.pop(best_i)
        if best_rev:
            p=dict(p); p['pts']=list(reversed(p['pts']))
        ordered.append(p); cur=p['pts'][-1]
    return ordered
mm_paths=reorder(mm_paths)

# Previews.
def render(path, pressure=True, dark_bg=False, black=False):
    dpi=220
    canvas_w=int(work_w/25.4*dpi); canvas_h=int(work_h/25.4*dpi)
    bg=(26,28,30) if dark_bg else (255,255,255)
    im=Image.new('RGB',(canvas_w,canvas_h),bg)
    d=ImageDraw.Draw(im)
    def m2p(x,y):
        return int(round(x/25.4*dpi)), int(round((-y)/25.4*dpi))
    # orange calibration work window
    cal_col=(255,105,35) if not dark_bg else (255,140,70)
    # subtle page border / work frame
    d.rectangle([m2p(0,0),m2p(work_w,-work_h)], outline=(235,235,235) if not dark_bg else (70,70,70), width=1)
    for p in mm_paths:
        pts=[m2p(x,y) for x,y in p['pts']]
        if black:
            col=(0,0,0) if not dark_bg else (230,230,230)
        elif pressure:
            s=int(p['shade'])
            col=(s,s,s) if not dark_bg else (max(30,255-s),max(30,255-s),max(30,255-s))
        else:
            col=(70,70,70) if not dark_bg else (220,220,220)
        if len(pts)>=2:
            d.line(pts, fill=col, width=1)
    im.save(path)
    if str(path).lower().endswith('.png'):
        pdf=Path(path).with_suffix('.pdf')
        im.save(pdf, 'PDF', resolution=dpi)

render(OUT/'gemini_actual_stroke_trace_preview_pressure_gray.png', pressure=True, black=False)
render(OUT/'gemini_actual_stroke_trace_preview_black_actual.png', pressure=False, black=True)
render(OUT/'gemini_actual_stroke_trace_preview_dark_pressure.png', pressure=True, dark_bg=True, black=False)

# G-code.
SAFE_Z=13.00
lines=[]
lines += [
    '; gemini_actual_stroke_trace_a4',
    '; Actual pencil stroke extraction: skeleton centerlines, noise-filtered, variable Z pressure.',
    '; Run pressure calibration before drawing if using pencil/soft pen.',
    'G21', 'G90', f'G0 Z{SAFE_Z:.2f}', 'G0 X0.000 Y0.000'
]
draw_len=0.0; travel_len=0.0; last=(0.0,0.0)
for p in mm_paths:
    pts=p['pts']; z=p['z']; feed=p['feed']
    a=pts[0]
    travel_len += math.hypot(a[0]-last[0], a[1]-last[1])
    lines.append(f'; stroke avg_ink={p["avg"]:.1f} z={z:.2f}')
    lines.append(f'G0 Z{SAFE_Z:.2f}')
    lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}')
    lines.append(f'G1 Z{z:.2f} F900')
    for x,y in pts[1:]:
        draw_len += math.hypot(x-last[0], y-last[1]) if last != (0.0,0.0) else 0
        lines.append(f'G1 X{x:.3f} Y{y:.3f} F{feed}')
        last=(x,y)
    lines.append(f'G0 Z{SAFE_Z:.2f}')
    last=pts[-1]
lines += ['G0 X0.000 Y0.000', f'G0 Z{SAFE_Z:.2f}', 'M2']
(OUT/'gemini_actual_stroke_trace_a4.nc').write_text('\n'.join(lines)+'\n', encoding='utf-8')
(OUT/'gemini_actual_stroke_trace_a4.gcode').write_text('\n'.join(lines)+'\n', encoding='utf-8')

# Better draw length recompute exactly.
draw_len=0.0; travel_len=0.0; last=(0.0,0.0)
for p in mm_paths:
    pts=p['pts']; travel_len += math.hypot(pts[0][0]-last[0], pts[0][1]-last[1])
    for a,b in zip(pts, pts[1:]): draw_len += math.hypot(b[0]-a[0], b[1]-a[1])
    last=pts[-1]

readme=f"""ACTUAL STROKE TRACE A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {work_w:.1f} x {work_h:.1f}
drawing_size_mm: {draw_w:.2f} x {draw_h:.2f}
paths: {len(mm_paths)}
draw_length_m: {draw_len/1000:.2f}
travel_length_m: {travel_len/1000:.2f}
estimated_time_min_ideal: {(draw_len/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours depending on pen-up/down and controller pauses
why_less_noise: extracts real pencil-stroke centerlines from the reference image; filters paper/JPEG grain; tone is carried by Z pressure instead of random black dots.
files:
- gemini_actual_stroke_trace_preview_pressure_gray.png/pdf
- gemini_actual_stroke_trace_preview_black_actual.png/pdf
- gemini_actual_stroke_trace_preview_dark_pressure.png/pdf
- gemini_actual_stroke_trace_a4.nc
- gemini_actual_stroke_trace_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme, encoding='utf-8')
print(readme)
