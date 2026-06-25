from __future__ import annotations
import math, re, shutil, hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw
import cv2

SRC=Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
BASE=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_soft_refine_a4_pack\gemini_tone_error_soft_refine_a4.nc")
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_microtone_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT/'source_input_copy.jpg')
shutil.copy2(BASE, OUT/'base_tone_error_soft_refine_a4.nc')
img=cv2.imread(str(SRC), cv2.IMREAD_COLOR)
if img is None:
    raise SystemExit('cannot read source')
gray0=cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
page=gray0<252
ys,xs=np.where(page)
x0,x1=int(xs.min()),int(xs.max()); y0,y1=int(ys.min()),int(ys.max())
pad=8
x0=max(0,x0-pad); y0=max(0,y0-pad); x1=min(gray0.shape[1]-1,x1+pad); y1=min(gray0.shape[0]-1,y1+pad)
gray=gray0[y0:y1+1,x0:x1+1]
H,W=gray.shape
Image.fromarray(gray).save(OUT/'source_cropped_gray.png')
# Clean tone target.
denoised=cv2.fastNlMeansDenoising(gray,None,7,7,21)
bg=cv2.GaussianBlur(denoised.astype(np.float32),(0,0),38)
norm=np.clip(denoised.astype(np.float32)/np.maximum(bg,1)*246,0,255).astype(np.uint8)
ink=(255-norm).astype(np.float32)/255.0
ink=cv2.GaussianBlur(ink,(0,0),0.38)
target=np.maximum(cv2.GaussianBlur(ink,(0,0),2.0)*0.82, cv2.GaussianBlur(ink,(0,0),8.0)*1.24)
lo,hi=np.percentile(target,[40,99.55])
target=np.clip((target-lo)/max(1e-6,hi-lo),0,1)
target=np.power(target,0.72)
# Orientation field.
g=cv2.GaussianBlur(norm.astype(np.float32),(0,0),1.55)
gx=cv2.Sobel(g,cv2.CV_32F,1,0,ksize=3); gy=cv2.Sobel(g,cv2.CV_32F,0,1,ksize=3)
orient=np.arctan2(gy,gx)+math.pi/2
c2=cv2.GaussianBlur(np.cos(2*orient),(0,0),5.0)
s2=cv2.GaussianBlur(np.sin(2*orient),(0,0),5.0)
orient=0.5*np.arctan2(s2,c2)
Image.fromarray(np.uint8(255*(1-target))).save(OUT/'target_density_debug.png')
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
# Parse base. G0 start only, G1 draw.
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
# Render base density.
coverage=np.zeros((H,W),np.float32)
line_binary=np.zeros((H,W),np.uint8)
for r in base:
    darkness=(255-shade_from_z(r['z']))/255.0
    pts=[]
    for x,y in r['pts']:
        px,py=m2p(x,y)
        if -5<=px<W+5 and -5<=py<H+5:
            pts.append((int(round(px)),int(round(py))))
    if len(pts)<2: continue
    layer=np.zeros((H,W),np.uint8)
    for a,b in zip(pts,pts[1:]):
        cv2.line(layer,a,b,255,1,cv2.LINE_AA)
        cv2.line(line_binary,a,b,255,1,cv2.LINE_AA)
    coverage=1.0-(1.0-coverage)*(1.0-(layer.astype(np.float32)/255.0)*darkness*.72)
current=np.clip(cv2.GaussianBlur(coverage,(0,0),4.0)*1.58,0,1)
line_density=cv2.GaussianBlur((line_binary>0).astype(np.float32),(0,0),3.0)
error=np.clip(target-current,0,1)
error=cv2.GaussianBlur(error,(0,0),2.6)
Image.fromarray(np.uint8(255*(1-current))).save(OUT/'base_current_density_debug.png')
Image.fromarray(np.uint8(255*(1-error))).save(OUT/'microtone_error_debug.png')
Image.fromarray(np.uint8(255*np.clip(line_density*5,0,1))).save(OUT/'base_line_density_debug.png')
extra=[]
# Microtone strokes: short, numerous only in under-darkened zones, density capped.
def region_angle(region,y,x,seed):
    if region=='forest': return [64,-55,86,42,105][int(h01(x,y,seed)*5)%5]+(h01(x,y,seed+1)-.5)*20
    if region=='field': return [-12,-7,12,16][int(h01(x,y,seed)*4)%4]+(h01(x,y,seed+1)-.5)*9
    if region=='grass': return [72,86,102,58,115][int(h01(x,y,seed)*5)%5]+(h01(x,y,seed+1)-.5)*18
    if region=='figure': return [56,-48,8,74][int(h01(x,y,seed)*4)%4]+(h01(x,y,seed+1)-.5)*12
    if region=='hair':
        a=math.degrees(float(orient[y,x]))
        if a<-25: a+=180
        if a>155: a-=180
        return max(55,min(126,a+(h01(x,y,seed+2)-.5)*16))
    return [24,-24,14][int(h01(x,y,seed)*3)%3]+(h01(x,y,seed+1)-.5)*9
def add_micro(name,region,y0f,y1f,x0f,x1f,step,err_thr,tgt_thr,cap,prob,len_min,len_max,bias,seed,min_active=.45):
    made=0
    y0i=int(y0f*H); y1i=int(y1f*H); x0i=int(x0f*W); x1i=int(x1f*W)
    for gy,y0 in enumerate(range(y0i,y1i,max(2,int(step)))):
        for gx,x0 in enumerate(range(x0i,x1i,max(2,int(step)))):
            cx=int(round(x0+(h01(gx,gy,seed)-.5)*step*.95)); cy=int(round(y0+(h01(gx,gy,seed+1)-.5)*step*.95))
            if not (0<=cx<W and 0<=cy<H): continue
            e=float(error[cy,cx]); d=float(target[cy,cx]); ld=float(line_density[cy,cx])
            if e<err_thr or d<tgt_thr or current[cy,cx]>cap: continue
            # Do not put microtone over already dense ink clusters.
            if ld>0.24 and region!='figure': continue
            if ld>0.34 and region=='figure': continue
            p=min(1,((e-err_thr)/max(1e-6,1-err_thr))**.52*prob)
            if h01(gx,gy,seed+2)>p: continue
            angle=region_angle(region,cy,cx,seed+3); th=math.radians(angle)
            length=(len_min+(len_max-len_min)*min(1,(e*.9+d*.55)))*(.82+.36*h01(gx,gy,seed+4))
            bend=(h01(gx,gy,seed+5)-.5)*2.6
            pts=[]; vals=[]
            for t in np.linspace(-.5,.5,5):
                bx=cx+t*length*math.cos(th); by=cy+t*length*math.sin(th)
                px=bx+bend*math.sin((t+.5)*math.pi)*math.cos(th+math.pi/2)
                py=by+bend*math.sin((t+.5)*math.pi)*math.sin(th+math.pi/2)
                xi=int(round(px)); yi=int(round(py))
                if 0<=xi<W and 0<=yi<H:
                    vals.append((float(error[yi,xi]),float(target[yi,xi]),float(current[yi,xi])))
                    pts.append(p2m(yi,xi))
            if len(pts)<2 or not vals: continue
            active=sum(1 for e2,d2,c2 in vals if e2>=err_thr*.55 and d2>=tgt_thr*.72 and c2<cap+.12)/len(vals)
            if active<min_active: continue
            tone=float(np.mean([max(e2,d2*.8) for e2,d2,c2 in vals])); z,shade,feed=press(tone,bias)
            extra.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
            # Update cheap local current/line density so we don't overpack the same area.
            rr=4
            ylo=max(0,cy-rr); yhi=min(H,cy+rr+1); xlo=max(0,cx-rr); xhi=min(W,cx+rr+1)
            current[ylo:yhi,xlo:xhi]=np.minimum(1,current[ylo:yhi,xlo:xhi]+0.035)
            line_density[ylo:yhi,xlo:xhi]=np.minimum(1,line_density[ylo:yhi,xlo:xhi]+0.035)
            made+=1
    return made
counts={}
# Almost no sky; only very visible cloud tone.
counts['sky_microtone']=add_micro('sky_microtone','sky',.02,.35,.0,1.0,25,.16,.30,.28,.30,10,24,-.14,10,.60)
# Forest gets the largest safe refinement; reference has dense tree band.
counts['forest_microtone']=add_micro('forest_microtone','forest',.34,.62,.0,1.0,6,.07,.15,.58,.62,6,18,-.03,20,.45)
counts['forest_dark_microtone']=add_micro('forest_dark_microtone','forest',.34,.62,.0,1.0,5,.13,.32,.66,.54,7,20,.08,30,.43)
# Field and grass: lighter and sparse.
counts['field_microtone']=add_micro('field_microtone','field',.50,.78,.0,1.0,8,.08,.15,.46,.36,12,36,-.10,40,.54)
counts['grass_microtone']=add_micro('grass_microtone','grass',.68,.99,.0,1.0,6,.08,.15,.54,.46,6,18,-.05,50,.42)
counts['grass_dark_microtone']=add_micro('grass_dark_microtone','grass',.68,.99,.0,1.0,5,.15,.35,.64,.38,6,18,.08,60,.40)
# Hair/figure: very conservative to avoid black blob.
counts['hair_microtone']=add_micro('hair_microtone','hair',.52,.80,.38,.76,5,.08,.16,.48,.46,9,28,-.04,70,.48)
counts['figure_microtone']=add_micro('figure_microtone','figure',.60,.99,.24,.66,5,.13,.28,.64,.34,7,20,.08,80,.42)
counts['figure_dark_microtone']=add_micro('figure_dark_microtone','figure',.60,.99,.24,.66,4,.22,.46,.72,.24,8,22,.16,90,.40)
# Compose records.
all_records=[]
for r in base:
    all_records.append({'pts':r['pts'],'z':r['z'],'shade':shade_from_z(r['z']),'feed':r.get('feed',1900),'kind':r['kind'],'tone':r['tone']})
all_records.extend(extra)
# Reorder, preserve border if first.
if all_records and all_records[0]['kind']=='border':
    first=[all_records[0]]; rest=all_records[1:]
else:
    border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
    first=[{'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5}]; rest=all_records
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
render(OUT/'gemini_tone_error_microtone_preview_pressure_gray.png',True)
render(OUT/'gemini_tone_error_microtone_preview_black_actual.png',False,True)
render(OUT/'gemini_tone_error_microtone_preview_dark_pressure.png',True,False,True)
SAFE=13.0
lines=['; gemini_tone_error_microtone_a4','; soft_refine base plus density-capped micro hatching in residual dark areas','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
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
(OUT/'gemini_tone_error_microtone_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_tone_error_microtone_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""TONE ERROR MICROTONE A4 package
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
microtone_counts: {counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Microtone adds density-capped short strokes only where source is darker than base and local line density is still low.
algorithm_note: starts from tone_error_soft_refine, computes residual target-current tone and local line density, then adds short directed strokes under a density cap. Sky and already dense clusters are protected.
files:
- gemini_tone_error_microtone_preview_pressure_gray.png/pdf
- gemini_tone_error_microtone_preview_black_actual.png/pdf
- gemini_tone_error_microtone_preview_dark_pressure.png/pdf
- gemini_tone_error_microtone_a4.nc
- gemini_tone_error_microtone_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
