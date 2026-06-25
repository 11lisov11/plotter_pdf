from __future__ import annotations
import math, re, shutil, hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw
import cv2

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
BASE_DIR = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_multilevel_true_strokes_dark_jacket_a4_pack")
BASE_NC = BASE_DIR / "gemini_multilevel_true_strokes_dark_jacket_a4.nc"
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_corrected_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
for p in [SRC, BASE_NC]:
    shutil.copy2(p, OUT / p.name)

img = cv2.imread(str(SRC), cv2.IMREAD_COLOR)
if img is None:
    raise SystemExit("cannot read source")
gray0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
mask_page = gray0 < 252
ys, xs = np.where(mask_page)
x0, x1 = int(xs.min()), int(xs.max())
y0, y1 = int(ys.min()), int(ys.max())
pad = 8
x0=max(0,x0-pad); y0=max(0,y0-pad); x1=min(gray0.shape[1]-1,x1+pad); y1=min(gray0.shape[0]-1,y1+pad)
gray = gray0[y0:y1+1, x0:x1+1]
H, W = gray.shape
Image.fromarray(gray).save(OUT / "source_cropped_gray.png")
# Target tone map: paper grain removed, source graphite tone retained.
denoised = cv2.fastNlMeansDenoising(gray, None, 7, 7, 21)
bg = cv2.GaussianBlur(denoised.astype(np.float32), (0,0), 38)
norm = np.clip(denoised.astype(np.float32) / np.maximum(bg,1) * 246, 0, 255).astype(np.uint8)
ink = (255 - norm).astype(np.float32) / 255.0
ink = cv2.GaussianBlur(ink, (0,0), 0.38)
target = np.maximum(cv2.GaussianBlur(ink,(0,0),2.0)*0.80, cv2.GaussianBlur(ink,(0,0),8.0)*1.22)
lo, hi = np.percentile(target, [40, 99.55])
target = np.clip((target-lo)/max(1e-6,hi-lo),0,1)
target = np.power(target,0.72)
Image.fromarray(np.uint8(255*(1-target))).save(OUT / "target_density_debug.png")
# Orientation field.
g = cv2.GaussianBlur(norm.astype(np.float32), (0,0), 1.6)
gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
orient = np.arctan2(gy,gx) + math.pi/2
c2 = cv2.GaussianBlur(np.cos(2*orient),(0,0),5.0)
s2 = cv2.GaussianBlur(np.sin(2*orient),(0,0),5.0)
orient = 0.5*np.arctan2(s2,c2)

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
def p2m(y,x): return XOFF + x*scale, -(YTOP + y*scale)
def m2p(x,y): return (x-XOFF)/scale, ((-y)-YTOP)/scale
def press(t,bias=0.0):
    v=max(0,min(1,t+bias))
    if v<.18: return 10.62,215,2350
    if v<.32: return 10.86,178,2200
    if v<.48: return 11.10,130,2000
    if v<.66: return 11.38,82,1700
    return 11.72,30,1450

def shade_from_z(z):
    if z < 10.75: return 215
    if z < 11.0: return 178
    if z < 11.25: return 130
    if z < 11.55: return 82
    return 30

def h01(*vals):
    s=':'.join(map(str,vals)).encode()
    return int.from_bytes(hashlib.sha1(s).digest()[:4],'big')/0xffffffff

# Parse base NC into stroke records.
records=[]; current=None; pen_started=False
for line in BASE_NC.read_text(encoding='utf-8').splitlines():
    if line.startswith('; ') and ' z=' in line:
        if current and len(current['pts'])>=2:
            records.append(current)
        parts=line[2:].split()
        kind=parts[0]
        mt=re.search(r'tone=([0-9.]+)',line); mz=re.search(r'z=([0-9.]+)',line)
        current={'kind':kind,'tone':float(mt.group(1)) if mt else .5,'z':float(mz.group(1)) if mz else 11.1,'pts':[],'feed':1900}
        pen_started=False
    elif current:
        mf=re.search(r'F([0-9]+)',line)
        if mf and line.startswith('G1 X'):
            current['feed']=int(mf.group(1))
        m=re.search(r'G0 X(-?[0-9.]+) Y(-?[0-9.]+)',line)
        if m and not current['pts']:
            current['pts'].append((float(m.group(1)), float(m.group(2))))
            continue
        m=re.search(r'G1 X(-?[0-9.]+) Y(-?[0-9.]+)',line)
        if m:
            current['pts'].append((float(m.group(1)), float(m.group(2))))
if current and len(current['pts'])>=2:
    records.append(current)
# Render base density/coverage in pixel space. Tone uses local density of line distribution.
coverage = np.zeros((H,W), np.float32)
for r in records:
    darkness = (255 - shade_from_z(r['z']))/255.0
    pts=[]
    for x,y in r['pts']:
        px,py=m2p(x,y)
        if -5 <= px < W+5 and -5 <= py < H+5:
            pts.append((int(round(px)), int(round(py))))
    if len(pts)<2: continue
    layer=np.zeros((H,W),np.uint8)
    for a,b in zip(pts,pts[1:]):
        cv2.line(layer,a,b,255,1,cv2.LINE_AA)
    coverage = 1.0 - (1.0-coverage)*(1.0-(layer.astype(np.float32)/255.0)*darkness*0.72)
current_tone = cv2.GaussianBlur(coverage,(0,0),4.2)
# Scale current tone to comparable range; preview line density naturally lower than source image.
current_tone = np.clip(current_tone*1.65,0,1)
error = np.clip(target - current_tone, 0, 1)
# Protect sky/light paper, smooth error so we add masses not noise.
error = cv2.GaussianBlur(error,(0,0),3.0)
Image.fromarray(np.uint8(255*(1-current_tone))).save(OUT / "base_render_density_debug.png")
Image.fromarray(np.uint8(255*(1-error))).save(OUT / "tone_error_debug.png")

extra=[]
# Region-aware tone correction. Add calm close strokes only where missing darkness is real.
def add_error_strokes(name,y0f,y1f,x0f,x1f,step,thr,angles,length_min,length_max,bias,prob_mul,seed,orient_weight=0.0):
    made=0
    y0i=int(y0f*H); y1i=int(y1f*H); x0i=int(x0f*W); x1i=int(x1f*W)
    for gy,y in enumerate(range(y0i,y1i,max(2,int(step)))):
        for gx,x in enumerate(range(x0i,x1i,max(2,int(step)))):
            jx=(h01(gx,gy,seed)-.5)*step*.92; jy=(h01(gx,gy,seed+1)-.5)*step*.92
            cx=int(round(x+jx)); cy=int(round(y+jy))
            if cx<0 or cx>=W or cy<0 or cy>=H: continue
            e=float(error[cy,cx]); d=float(target[cy,cx])
            if e<thr or d<thr*.78: continue
            p=min(1.0, ((e-thr)/max(1e-6,1-thr))**0.55 * prob_mul)
            if h01(gx,gy,seed+2)>p: continue
            if orient_weight>0 and h01(gx,gy,seed+3)<orient_weight:
                angle=math.degrees(float(orient[cy,cx]))
                if angle < -25: angle += 180
                if angle > 155: angle -= 180
            else:
                angle=angles[int(h01(gx,gy,seed+4)*len(angles))%len(angles)]
            angle += (h01(gx,gy,seed+5)-.5)*15
            theta=math.radians(angle)
            length=(length_min+(length_max-length_min)*min(1,(e*1.4+d*.7)))*(.78+.48*h01(gx,gy,seed+6))
            curve=(h01(gx,gy,seed+7)-.5)*3.2
            pts=[]; samples=[]
            for t in np.linspace(-.5,.5,6):
                bx=cx+t*length*math.cos(theta)
                by=cy+t*length*math.sin(theta)
                bend=curve*math.sin((t+.5)*math.pi)
                px=bx+bend*math.cos(theta+math.pi/2)
                py=by+bend*math.sin(theta+math.pi/2)
                xi=int(round(px)); yi=int(round(py))
                if 0<=xi<W and 0<=yi<H:
                    samples.append((float(error[yi,xi]), float(target[yi,xi])))
                    pts.append(p2m(yi,xi))
            if len(pts)<2: continue
            mean_e=float(np.mean([s[0] for s in samples])); mean_d=float(np.mean([s[1] for s in samples]))
            if mean_e<thr*.72 or mean_d<thr*.72: continue
            z,shade,feed=press(max(mean_d,mean_e),bias)
            extra.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':max(mean_d,mean_e)})
            made+=1
    return made
counts={}
# Sky almost untouched: only substantial missing cloud tone.
counts['sky_error_soft']=add_error_strokes('sky_error_soft',.02,.35,.00,1.0,22,.36,[24,-22],14,34,-.13,.36,10,.25)
# Forest receives close local strokes; dark tree band in reference needs mass, but avoid carpet noise.
counts['forest_error_mid']=add_error_strokes('forest_error_mid',.34,.62,.00,1.0,8.5,.20,[63,-55,86],10,28,-.02,.72,20,.20)
counts['forest_error_dark']=add_error_strokes('forest_error_dark',.34,.62,.00,1.0,6.5,.34,[70,-50,90],10,30,.09,.70,30,.30)
# Field/grass: directional sparse corrections.
counts['field_error_flow']=add_error_strokes('field_error_flow',.50,.77,.00,1.0,9.0,.18,[-12,-6,14],26,70,-.08,.58,40,.12)
counts['grass_error']=add_error_strokes('grass_error',.68,.99,.00,1.0,7.0,.19,[75,96,110,62],8,22,-.03,.62,50,.16)
# Figure/jacket and hair: most important dark correction.
counts['figure_error_mid']=add_error_strokes('figure_error_mid',.60,.99,.24,.66,5.2,.20,[56,-46,8,72],10,30,.06,.92,60,.15)
counts['figure_error_dark']=add_error_strokes('figure_error_dark',.60,.99,.24,.66,4.2,.34,[58,-50,6,82],12,34,.18,.92,70,.12)
counts['hair_error_flow']=add_error_strokes('hair_error_flow',.52,.80,.39,.75,5.8,.18,[78,92,108,118],14,42,-.03,.76,80,.70)

# Combine and reorder. Keep base border first if present.
all_records=[]
for r in records:
    all_records.append({'pts':r['pts'],'z':r['z'],'shade':shade_from_z(r['z']),'feed':r.get('feed',1900),'kind':r['kind'],'tone':r['tone']})
all_records.extend(extra)
# Remove obvious zero-length records.
all_records=[r for r in all_records if len(r['pts'])>=2]
# Nearest reorder, keep first border-like record if possible.
first=[]; rest=all_records
if rest and rest[0]['kind']=='border':
    first=[rest[0]]; rest=rest[1:]
else:
    border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
    first=[{'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5}]

def reorder(rest):
    out=[]; cur=first[0]['pts'][-1]
    while rest:
        bi=0; br=False; bd=1e18; limit=min(len(rest),1800)
        for i in range(limit):
            p=rest[i]; a=p['pts'][0]; b=p['pts'][-1]
            da=math.hypot(a[0]-cur[0],a[1]-cur[1]); db=math.hypot(b[0]-cur[0],b[1]-cur[1])
            if da<bd: bi=i; br=False; bd=da
            if db<bd: bi=i; br=True; bd=db
        p=rest.pop(bi)
        if br:
            p=dict(p); p['pts']=list(reversed(p['pts']))
        out.append(p); cur=p['pts'][-1]
    return out
ordered=first+reorder(rest[:])
kind_counts=Counter(r['kind'] for r in ordered)

def render(path:Path, pressure=True, black=False, dark=False):
    dpi=230; cw=int(WORK_W/25.4*dpi); ch=int(WORK_H/25.4*dpi)
    im=Image.new('RGB',(cw,ch),(255,255,255) if not dark else (24,24,24)); d=ImageDraw.Draw(im)
    def mm(x,y): return int(round(x/25.4*dpi)), int(round((-y)/25.4*dpi))
    d.rectangle([mm(0,0),mm(WORK_W,-WORK_H)],outline=(238,238,238) if not dark else (66,66,66),width=1)
    for r in ordered:
        pts=[mm(x,y) for x,y in r['pts']]
        if len(pts)<2: continue
        if black: col=(0,0,0) if not dark else (235,235,235)
        elif pressure:
            s=int(r['shade']); col=(s,s,s) if not dark else (max(28,255-s),)*3
        else: col=(55,55,55)
        d.line(pts, fill=col, width=1)
    im.save(path); im.save(path.with_suffix('.pdf'),'PDF',resolution=dpi)
render(OUT/'gemini_tone_error_corrected_preview_pressure_gray.png',True)
render(OUT/'gemini_tone_error_corrected_preview_black_actual.png',False,True)
render(OUT/'gemini_tone_error_corrected_preview_dark_pressure.png',True,False,True)
# G-code
SAFE=13.0
lines=['; gemini_tone_error_corrected_a4','; base true strokes plus tone-error corrections: dark gaps get close lines, light areas protected','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
draw=0.0; travel=0.0; last=(0.0,0.0)
for r in ordered:
    pts=r['pts']; a=pts[0]
    travel+=math.hypot(a[0]-last[0],a[1]-last[1])
    lines.append(f'; {r["kind"]} tone={r["tone"]:.3f} z={r["z"]:.2f}')
    lines.append(f'G0 Z{SAFE:.2f}'); lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}'); lines.append(f'G1 Z{r["z"]:.2f} F900')
    prev=a
    for x,y in pts[1:]:
        draw+=math.hypot(x-prev[0],y-prev[1])
        lines.append(f'G1 X{x:.3f} Y{y:.3f} F{r["feed"]}')
        prev=(x,y)
    lines.append(f'G0 Z{SAFE:.2f}')
    last=pts[-1]
lines += ['G0 X0.000 Y0.000', f'G0 Z{SAFE:.2f}', 'M2']
(OUT/'gemini_tone_error_corrected_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_tone_error_corrected_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""TONE ERROR CORRECTED A4 package
source: {SRC}
base_nc: {BASE_NC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
base_paths: {len(records)}
extra_paths: {len(extra)}
paths_total: {len(ordered)}
kind_counts: {dict(kind_counts)}
correction_counts: {counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Closest match requires calibrated Z pressure and pencil/soft pen.
algorithm_note: renders base G-code back to a tone map, compares it to the denoised source tone, then adds deterministic local strokes only where target is darker than current. Sky/light zones are threshold-protected.
files:
- gemini_tone_error_corrected_preview_pressure_gray.png/pdf
- gemini_tone_error_corrected_preview_black_actual.png/pdf
- gemini_tone_error_corrected_preview_dark_pressure.png/pdf
- gemini_tone_error_corrected_a4.nc
- gemini_tone_error_corrected_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)

