from __future__ import annotations
import math, re, shutil, hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw
import cv2

SRC=Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
BASE=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_corrected_a4_pack\gemini_tone_error_corrected_a4.nc")
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_soft_refine_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT/'source_input_copy.jpg')
shutil.copy2(BASE, OUT/'base_tone_error_corrected_a4.nc')
img=cv2.imread(str(SRC), cv2.IMREAD_COLOR)
if img is None: raise SystemExit('cannot read source')
gray0=cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
page=gray0<252
ys,xs=np.where(page)
x0,x1=int(xs.min()),int(xs.max()); y0,y1=int(ys.min()),int(ys.max())
pad=8
x0=max(0,x0-pad); y0=max(0,y0-pad); x1=min(gray0.shape[1]-1,x1+pad); y1=min(gray0.shape[0]-1,y1+pad)
gray=gray0[y0:y1+1,x0:x1+1]
H,W=gray.shape
Image.fromarray(gray).save(OUT/'source_cropped_gray.png')
# Target tone from source, paper-grain suppressed.
denoised=cv2.fastNlMeansDenoising(gray,None,7,7,21)
bg=cv2.GaussianBlur(denoised.astype(np.float32),(0,0),38)
norm=np.clip(denoised.astype(np.float32)/np.maximum(bg,1)*246,0,255).astype(np.uint8)
ink=(255-norm).astype(np.float32)/255.0
ink=cv2.GaussianBlur(ink,(0,0),0.38)
target=np.maximum(cv2.GaussianBlur(ink,(0,0),2.0)*0.82, cv2.GaussianBlur(ink,(0,0),8.0)*1.24)
lo,hi=np.percentile(target,[40,99.55])
target=np.clip((target-lo)/max(1e-6,hi-lo),0,1)
target=np.power(target,0.72)
Image.fromarray(np.uint8(255*(1-target))).save(OUT/'target_density_debug.png')
# Orientation for soft strokes.
g=cv2.GaussianBlur(norm.astype(np.float32),(0,0),1.6)
gx=cv2.Sobel(g,cv2.CV_32F,1,0,ksize=3); gy=cv2.Sobel(g,cv2.CV_32F,0,1,ksize=3)
orient=np.arctan2(gy,gx)+math.pi/2
c2=cv2.GaussianBlur(np.cos(2*orient),(0,0),5.5)
s2=cv2.GaussianBlur(np.sin(2*orient),(0,0),5.5)
orient=0.5*np.arctan2(s2,c2)
WORK_W,WORK_H=180.0,280.0
DRAW_W=176.0
scale=DRAW_W/W
DRAW_H=H*scale
if DRAW_H>270:
    DRAW_H=270.0; scale=DRAW_H/H; DRAW_W=W*scale
XOFF=(WORK_W-DRAW_W)/2.0; YTOP=(WORK_H-DRAW_H)/2.0
def p2m(y,x): return XOFF+x*scale, -(YTOP+y*scale)
def m2p(x,y): return (x-XOFF)/scale, ((-y)-YTOP)/scale
def press(t,bias=0.0):
    v=max(0,min(1,t+bias))
    if v<.18: return 10.62,215,2350
    if v<.32: return 10.86,178,2200
    if v<.48: return 11.10,130,2000
    if v<.66: return 11.38,82,1700
    return 11.72,30,1450
def shade_from_z(z):
    if z<10.75: return 215
    if z<11.0: return 178
    if z<11.25: return 130
    if z<11.55: return 82
    return 30
def h01(*vals):
    data=':'.join(map(str,vals)).encode()
    return int.from_bytes(hashlib.sha1(data).digest()[:4],'big')/0xffffffff
# Parse base NC safely: G0 only start point, G1 are drawing moves.
base=[]; cur=None
for line in BASE.read_text(encoding='utf-8').splitlines():
    if line.startswith('; ') and ' z=' in line:
        if cur and len(cur['pts'])>=2: base.append(cur)
        mt=re.search(r'tone=([0-9.]+)',line); mz=re.search(r'z=([0-9.]+)',line)
        cur={'kind':line[2:].split()[0], 'tone':float(mt.group(1)) if mt else .5, 'z':float(mz.group(1)) if mz else 11.1, 'feed':1900, 'pts':[]}
    elif cur:
        m0=re.search(r'G0 X(-?[0-9.]+) Y(-?[0-9.]+)',line)
        if m0 and not cur['pts']:
            cur['pts'].append((float(m0.group(1)),float(m0.group(2))))
            continue
        m1=re.search(r'G1 X(-?[0-9.]+) Y(-?[0-9.]+).*?(?:F([0-9]+))?',line)
        if m1:
            cur['pts'].append((float(m1.group(1)),float(m1.group(2))))
            if m1.group(3): cur['feed']=int(m1.group(3))
if cur and len(cur['pts'])>=2: base.append(cur)
# Render base to tone map.
coverage=np.zeros((H,W),np.float32)
for r in base:
    darkness=(255-shade_from_z(r['z']))/255.0
    pts=[]
    for x,y in r['pts']:
        px,py=m2p(x,y)
        if -5<=px<W+5 and -5<=py<H+5:
            pts.append((int(round(px)),int(round(py))))
    if len(pts)<2: continue
    layer=np.zeros((H,W),np.uint8)
    for a,b in zip(pts,pts[1:]): cv2.line(layer,a,b,255,1,cv2.LINE_AA)
    coverage=1.0-(1.0-coverage)*(1.0-(layer.astype(np.float32)/255.0)*darkness*.72)
current=np.clip(cv2.GaussianBlur(coverage,(0,0),4.0)*1.58,0,1)
error=np.clip(target-current,0,1)
error=cv2.GaussianBlur(error,(0,0),3.2)
Image.fromarray(np.uint8(255*(1-current))).save(OUT/'base_current_density_debug.png')
Image.fromarray(np.uint8(255*(1-error))).save(OUT/'soft_refine_error_debug.png')
extra=[]
def angle_for(region,y,x,seed):
    if region=='sky': return [24,-24,14][int(h01(x,y,seed)*3)%3]+(h01(x,y,seed+1)-.5)*9
    if region=='forest': return [64,-55,86,44,103][int(h01(x,y,seed)*5)%5]+(h01(x,y,seed+1)-.5)*16
    if region=='field': return [-12,-7,12,16][int(h01(x,y,seed)*4)%4]+(h01(x,y,seed+1)-.5)*8
    if region=='grass': return [72,86,102,58,115][int(h01(x,y,seed)*5)%5]+(h01(x,y,seed+1)-.5)*16
    if region=='hair':
        a=math.degrees(float(orient[y,x]))
        if a<-25: a+=180
        if a>155: a-=180
        return max(55,min(126,a+(h01(x,y,seed+2)-.5)*15))
    return [56,-48,8,76][int(h01(x,y,seed)*4)%4]+(h01(x,y,seed+1)-.5)*10
def add_soft(name,region,y0f,y1f,x0f,x1f,step,err_thr,tgt_thr,prob,len_min,len_max,bias,seed,min_active=.50):
    made=0
    y0i=int(y0f*H); y1i=int(y1f*H); x0i=int(x0f*W); x1i=int(x1f*W)
    for gy,y0 in enumerate(range(y0i,y1i,max(2,int(step)))):
        for gx,x0 in enumerate(range(x0i,x1i,max(2,int(step)))):
            cx=int(round(x0+(h01(gx,gy,seed)-.5)*step*.9)); cy=int(round(y0+(h01(gx,gy,seed+1)-.5)*step*.9))
            if not (0<=cx<W and 0<=cy<H): continue
            e=float(error[cy,cx]); d=float(target[cy,cx])
            if e<err_thr or d<tgt_thr: continue
            take=min(1,((e-err_thr)/max(1e-6,1-err_thr))**.55*prob)
            if h01(gx,gy,seed+2)>take: continue
            ang=angle_for(region,cy,cx,seed+3); th=math.radians(ang)
            length=(len_min+(len_max-len_min)*min(1,(e*.8+d*.7)))*(.82+.38*h01(gx,gy,seed+4))
            bend=(h01(gx,gy,seed+5)-.5)*3.4
            pts=[]; vals=[]
            for t in np.linspace(-.5,.5,6):
                bx=cx+t*length*math.cos(th); by=cy+t*length*math.sin(th)
                px=bx+bend*math.sin((t+.5)*math.pi)*math.cos(th+math.pi/2)
                py=by+bend*math.sin((t+.5)*math.pi)*math.sin(th+math.pi/2)
                xi=int(round(px)); yi=int(round(py))
                if 0<=xi<W and 0<=yi<H:
                    vals.append((float(error[yi,xi]),float(target[yi,xi]))); pts.append(p2m(yi,xi))
            if len(pts)<2 or not vals: continue
            active=sum(1 for e2,d2 in vals if e2>=err_thr*.55 and d2>=tgt_thr*.70)/len(vals)
            if active<min_active: continue
            tone=float(np.mean([max(e2,d2) for e2,d2 in vals])); z,shade,feed=press(tone,bias)
            extra.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
            made+=1
    return made
counts={}
# Soft sky only in cloud patches; no global haze.
counts['sky_soft_refine']=add_soft('sky_soft_refine','sky',.02,.35,.0,1.0,24,.12,.23,.42,16,38,-.14,10,.62)
# Forest/trees: more tone but not grid.
counts['forest_soft_refine']=add_soft('forest_soft_refine','forest',.34,.62,.0,1.0,9,.08,.16,.54,10,28,-.04,20,.50)
counts['forest_dark_refine']=add_soft('forest_dark_refine','forest',.34,.62,.0,1.0,7,.16,.34,.52,10,30,.08,30,.48)
# Field/grass: sparse directional corrections.
counts['field_soft_refine']=add_soft('field_soft_refine','field',.50,.78,.0,1.0,10,.08,.14,.42,24,70,-.10,40,.58)
counts['grass_soft_refine']=add_soft('grass_soft_refine','grass',.68,.99,.0,1.0,8,.08,.15,.42,8,22,-.06,50,.46)
counts['grass_dark_refine']=add_soft('grass_dark_refine','grass',.68,.99,.0,1.0,6,.16,.36,.44,8,24,.10,60,.46)
# Hair gets flow strokes; jacket only modestly boosted, because base already dark.
counts['hair_soft_refine']=add_soft('hair_soft_refine','hair',.52,.80,.38,.76,6,.09,.16,.58,14,42,-.04,70,.50)
counts['figure_soft_refine']=add_soft('figure_soft_refine','figure',.60,.99,.24,.66,7,.12,.24,.42,10,30,.06,80,.48)
counts['figure_dark_refine']=add_soft('figure_dark_refine','figure',.60,.99,.24,.66,6,.22,.45,.34,12,32,.16,90,.45)
all_records=[]
for r in base:
    all_records.append({'pts':r['pts'],'z':r['z'],'shade':shade_from_z(r['z']),'feed':r.get('feed',1900),'kind':r['kind'],'tone':r['tone']})
all_records.extend(extra)
# Reorder with border first if present.
first=[]; rest=all_records
if rest and rest[0]['kind']=='border': first=[rest[0]]; rest=rest[1:]
else:
    border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
    first=[{'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5}]
def reorder(rest):
    out=[]; cur=first[0]['pts'][-1]
    while rest:
        bi=0; br=False; bd=1e18; limit=min(len(rest),1900)
        for i in range(limit):
            p=rest[i]; a=p['pts'][0]; b=p['pts'][-1]
            da=math.hypot(a[0]-cur[0],a[1]-cur[1]); db=math.hypot(b[0]-cur[0],b[1]-cur[1])
            if da<bd: bi=i; br=False; bd=da
            if db<bd: bi=i; br=True; bd=db
        p=rest.pop(bi)
        if br: p=dict(p); p['pts']=list(reversed(p['pts']))
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
        d.line(pts,fill=col,width=1)
    im.save(path); im.save(path.with_suffix('.pdf'),'PDF',resolution=dpi)
render(OUT/'gemini_tone_error_soft_refine_preview_pressure_gray.png',True)
render(OUT/'gemini_tone_error_soft_refine_preview_black_actual.png',False,True)
render(OUT/'gemini_tone_error_soft_refine_preview_dark_pressure.png',True,False,True)
SAFE=13.0
lines=['; gemini_tone_error_soft_refine_a4','; tone_error_corrected plus protected soft refine strokes','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
draw=0.0; travel=0.0; last=(0.0,0.0)
for r in ordered:
    pts=r['pts']; a=pts[0]
    travel+=math.hypot(a[0]-last[0],a[1]-last[1])
    lines.append(f'; {r["kind"]} tone={r["tone"]:.3f} z={r["z"]:.2f}')
    lines.append(f'G0 Z{SAFE:.2f}'); lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}'); lines.append(f'G1 Z{r["z"]:.2f} F900')
    prev=a
    for x,y in pts[1:]:
        draw+=math.hypot(x-prev[0],y-prev[1]); lines.append(f'G1 X{x:.3f} Y{y:.3f} F{r["feed"]}'); prev=(x,y)
    lines.append(f'G0 Z{SAFE:.2f}'); last=pts[-1]
lines += ['G0 X0.000 Y0.000',f'G0 Z{SAFE:.2f}','M2']
(OUT/'gemini_tone_error_soft_refine_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_tone_error_soft_refine_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""TONE ERROR SOFT REFINE A4 package
source: {SRC}
base_nc: {BASE}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
base_paths: {len(base)}
extra_paths: {len(extra)}
paths_total: {len(ordered)}
kind_counts: {dict(kind_counts)}
soft_refine_counts: {counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Soft refine adds strokes only where base is lighter than denoised source tone; sky/light zones are protected by thresholds.
algorithm_note: starts from tone_error_corrected, renders it to a tone map, computes residual tone error, and adds limited direction-aware soft strokes in under-darkened regions.
files:
- gemini_tone_error_soft_refine_preview_pressure_gray.png/pdf
- gemini_tone_error_soft_refine_preview_black_actual.png/pdf
- gemini_tone_error_soft_refine_preview_dark_pressure.png/pdf
- gemini_tone_error_soft_refine_a4.nc
- gemini_tone_error_soft_refine_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
