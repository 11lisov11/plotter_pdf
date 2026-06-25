from __future__ import annotations
import math, re, shutil, hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw
import cv2

SRC=Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
BASE=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_microtone_a4_pack\gemini_tone_error_microtone_a4.nc")
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_weave_refine_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT/'source_input_copy.jpg')
shutil.copy2(BASE, OUT/'base_tone_error_microtone_a4.nc')
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
# Build source target tone with paper/grain removed.
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
# Orientation field for hair/forest tweaks.
g=cv2.GaussianBlur(norm.astype(np.float32),(0,0),1.6)
gx=cv2.Sobel(g,cv2.CV_32F,1,0,ksize=3); gy=cv2.Sobel(g,cv2.CV_32F,0,1,ksize=3)
orient=np.arctan2(gy,gx)+math.pi/2
c2=cv2.GaussianBlur(np.cos(2*orient),(0,0),5.0)
s2=cv2.GaussianBlur(np.sin(2*orient),(0,0),5.0)
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
# Parse base safely.
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
# Render base to current tone + local line density.
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
line_density=cv2.GaussianBlur((line_binary>0).astype(np.float32),(0,0),3.2)
residual=np.clip(target-current,0,1)
residual=cv2.GaussianBlur(residual,(0,0),3.6)
Image.fromarray(np.uint8(255*(1-current))).save(OUT/'base_current_density_debug.png')
Image.fromarray(np.uint8(255*(1-residual))).save(OUT/'weave_residual_debug.png')
Image.fromarray(np.uint8(255*np.clip(line_density*5,0,1))).save(OUT/'line_density_debug.png')
extra=[]
# Wavy clipped line weave: fewer, longer, non-random strokes for missing low-frequency tone.
def add_weave(name, region, angle_deg, spacing, y0f,y1f,x0f,x1f, err_thr, tgt_thr, cap, min_len, bias, keep, phase, split_len):
    theta=math.radians(angle_deg); ux=math.cos(theta); uy=math.sin(theta); nx=-uy; ny=ux
    x0=x0f*W; x1=x1f*W; y0=y0f*H; y1=y1f*H
    corners=[(x0,y0),(x1,y0),(x0,y1),(x1,y1)]
    projs=[x*nx+y*ny for x,y in corners]
    minp,maxp=min(projs)-spacing,max(projs)+spacing
    diag=math.hypot(W,H)
    made=0
    for si in range(int((maxp-minp)/spacing)+1):
        if h01(hash(name),si,17)>keep: continue
        off=minp+si*spacing+phase+(h01(hash(name),si,18)-.5)*spacing*.28
        cx=(x0+x1)/2; cy=(y0+y1)/2; cp=cx*nx+cy*ny
        px=cx+(off-cp)*nx; py=cy+(off-cp)*ny
        cur=[]; segs=[]; gap=0
        wobble_amp=1.4 if region in ('field','sky') else 2.4
        wobble_period=44 if region in ('field','sky') else 30
        for ti,t in enumerate(np.arange(-diag,diag,2.0)):
            wob=math.sin((t+phase)/wobble_period*2*math.pi)*wobble_amp
            wob+= (h01(hash(name),si,int((t+diag)/26),19)-.5)*0.7
            x=px+t*ux+wob*nx; y=py+t*uy+wob*ny
            xi=int(round(x)); yi=int(round(y))
            if xi<0 or xi>=W or yi<0 or yi>=H or xi<x0 or xi>x1 or yi<y0 or yi>y1:
                if cur:
                    gap+=1
                    if gap>2:
                        if len(cur)>=2: segs.append(cur)
                        cur=[]; gap=0
                continue
            e=float(residual[yi,xi]); d=float(target[yi,xi]); c=float(current[yi,xi]); ld=float(line_density[yi,xi])
            ok=e>=err_thr and d>=tgt_thr and c<cap
            # Never create global sky haze.
            if yi/H<.32 and (e<err_thr+.08 or d<tgt_thr+.10): ok=False
            # Protect already dense clusters, except allow a little more in jacket.
            if region!='figure' and ld>.27: ok=False
            if region=='figure' and ld>.40: ok=False
            if ok:
                cur.append((yi,xi,e,d)); gap=0
            elif cur:
                gap+=1
                if gap>2:
                    if len(cur)>=2: segs.append(cur)
                    cur=[]; gap=0
        if cur and len(cur)>=2: segs.append(cur)
        for seg in segs:
            L=sum(math.hypot(seg[i+1][1]-seg[i][1],seg[i+1][0]-seg[i][0]) for i in range(len(seg)-1))
            if L<min_len: continue
            pieces=[]
            if L>split_len*1.35:
                piece_pts=max(4,int(split_len/2.0)); step=max(3,int(piece_pts*.70))
                for st in range(0,len(seg)-2,step):
                    en=min(len(seg),st+piece_pts)
                    if en-st>=2: pieces.append(seg[st:en])
            else:
                pieces=[seg]
            for piece in pieces:
                if len(piece)<2: continue
                tone=float(np.mean([max(e,d*.75) for _,_,e,d in piece]))
                z,shade,feed=press(tone,bias)
                st=max(1,int(len(piece)/9)); sm=piece[::st]
                if sm[-1]!=piece[-1]: sm.append(piece[-1])
                pts=[p2m(y,x) for y,x,_,_ in sm]
                extra.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
                # update caps locally so adjacent weave does not overfill.
                for y,x,_,_ in piece[::max(1,int(len(piece)/5))]:
                    rr=5; ylo=max(0,y-rr); yhi=min(H,y+rr+1); xlo=max(0,x-rr); xhi=min(W,x+rr+1)
                    current[ylo:yhi,xlo:xhi]=np.minimum(1,current[ylo:yhi,xlo:xhi]+0.026)
                    line_density[ylo:yhi,xlo:xhi]=np.minimum(1,line_density[ylo:yhi,xlo:xhi]+0.025)
                made+=1
    return made
counts={}
# Sky: minimal cloud texture.
counts['sky_weave_a']=add_weave('sky_weave_a','sky',24,36,.02,.35,.0,1.0,.16,.31,.28,20,-.14,.35,3,54)
counts['sky_weave_b']=add_weave('sky_weave_b','sky',-24,46,.02,.35,.0,1.0,.24,.44,.30,18,-.10,.25,11,50)
# Forest: residual low-frequency mass.
counts['forest_weave_a']=add_weave('forest_weave_a','forest',64,12,.34,.62,.0,1.0,.075,.16,.62,10,-.04,.72,0,38)
counts['forest_weave_b']=add_weave('forest_weave_b','forest',-56,16,.34,.62,.0,1.0,.15,.33,.70,10,.06,.54,5,34)
counts['forest_weave_c']=add_weave('forest_weave_c','forest',88,15,.34,.62,.0,1.0,.24,.50,.76,8,.12,.38,2,30)
# Field/hill: long soft flow only where underdrawn.
counts['field_weave_a']=add_weave('field_weave_a','field',-11,11,.50,.78,.0,1.0,.09,.16,.50,28,-.10,.52,0,72)
counts['field_weave_b']=add_weave('field_weave_b','field',14,18,.50,.78,.0,1.0,.17,.36,.58,24,-.02,.35,6,58)
# Grass: little, not carpet.
counts['grass_weave_a']=add_weave('grass_weave_a','grass',78,10,.68,.99,.0,1.0,.09,.16,.58,8,-.05,.48,0,24)
counts['grass_weave_b']=add_weave('grass_weave_b','grass',103,14,.68,.99,.0,1.0,.18,.38,.68,8,.08,.34,5,22)
# Figure: conservative dark correction, only residual holes.
counts['figure_weave_a']=add_weave('figure_weave_a','figure',56,9,.60,.99,.24,.66,.16,.30,.68,9,.07,.38,0,30)
counts['figure_weave_b']=add_weave('figure_weave_b','figure',-48,12,.60,.99,.24,.66,.26,.50,.76,8,.16,.28,4,28)
# Hair: flow lines in residual gaps.
counts['hair_weave_a']=add_weave('hair_weave_a','hair',88,9,.52,.80,.38,.76,.10,.18,.52,12,-.04,.42,0,40)
counts['hair_weave_b']=add_weave('hair_weave_b','hair',108,13,.52,.80,.38,.76,.20,.40,.62,10,.06,.30,4,34)
# Compose and reorder.
all_records=[]
for r in base:
    all_records.append({'pts':r['pts'],'z':r['z'],'shade':shade_from_z(r['z']),'feed':r.get('feed',1900),'kind':r['kind'],'tone':r['tone']})
all_records.extend(extra)
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
render(OUT/'gemini_tone_error_weave_refine_preview_pressure_gray.png',True)
render(OUT/'gemini_tone_error_weave_refine_preview_black_actual.png',False,True)
render(OUT/'gemini_tone_error_weave_refine_preview_dark_pressure.png',True,False,True)
SAFE=13.0
lines=['; gemini_tone_error_weave_refine_a4','; microtone base plus residual clipped wavy tonal weave','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
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
(OUT/'gemini_tone_error_weave_refine_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_tone_error_weave_refine_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""TONE ERROR WEAVE REFINE A4 package
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
weave_counts: {counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Weave adds clipped wavy tone lines only in residual under-dark regions, with sky and dense clusters protected.
algorithm_note: starts from tone_error_microtone, renders current tone, computes residual source-current tone, and adds low-frequency wavy line families clipped by residual tone and local line-density caps.
files:
- gemini_tone_error_weave_refine_preview_pressure_gray.png/pdf
- gemini_tone_error_weave_refine_preview_black_actual.png/pdf
- gemini_tone_error_weave_refine_preview_dark_pressure.png/pdf
- gemini_tone_error_weave_refine_a4.nc
- gemini_tone_error_weave_refine_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
