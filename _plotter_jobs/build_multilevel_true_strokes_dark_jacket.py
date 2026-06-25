from __future__ import annotations
import math, shutil
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw
import cv2
try:
    from skimage.morphology import skeletonize
except Exception:
    skeletonize=None

SRC=Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_multilevel_true_strokes_dark_jacket_a4_pack")
OUT.mkdir(parents=True,exist_ok=True)
shutil.copy2(SRC,OUT/'source_input_copy.jpg')
img=cv2.imread(str(SRC),cv2.IMREAD_COLOR)
if img is None: raise SystemExit('cannot read source')
gray0=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
mask_page=gray0<252
ys,xs=np.where(mask_page)
x0,x1=int(xs.min()),int(xs.max()); y0,y1=int(ys.min()),int(ys.max())
pad=8; x0=max(0,x0-pad); y0=max(0,y0-pad); x1=min(gray0.shape[1]-1,x1+pad); y1=min(gray0.shape[0]-1,y1+pad)
gray=gray0[y0:y1+1,x0:x1+1]
H,W=gray.shape
Image.fromarray(gray).save(OUT/'source_cropped_gray.png')
# Normalize paper; preserve faint graphite.
denoised=cv2.fastNlMeansDenoising(gray,None,7,7,21)
bg=cv2.GaussianBlur(denoised.astype(np.float32),(0,0),38)
norm=np.clip(denoised.astype(np.float32)/np.maximum(bg,1)*246,0,255).astype(np.uint8)
ink=(255-norm).astype(np.float32)/255.0
ink=cv2.GaussianBlur(ink,(0,0),0.38)
# Smooth density for tone/Z only.
density=np.maximum(cv2.GaussianBlur(ink,(0,0),2.0)*0.78, cv2.GaussianBlur(ink,(0,0),7.5)*1.16)
lo,hi=np.percentile(density,[40,99.5])
density=np.clip((density-lo)/max(1e-6,hi-lo),0,1)
density=np.power(density,.72)
Image.fromarray(np.uint8(255*(1-density))).save(OUT/'density_debug.png')

WORK_W,WORK_H=180.0,280.0
DRAW_W=176.0
scale=DRAW_W/W
DRAW_H=H*scale
if DRAW_H>270:
    DRAW_H=270; scale=DRAW_H/H; DRAW_W=W*scale
XOFF=(WORK_W-DRAW_W)/2; YTOP=(WORK_H-DRAW_H)/2
def p2m(y,x): return XOFF+x*scale, -(YTOP+y*scale)
def press(t,bias=0.0):
    v=max(0,min(1,t+bias))
    if v<.18: return 10.62,215,2350
    if v<.32: return 10.86,178,2200
    if v<.48: return 11.10,130,2000
    if v<.66: return 11.38,82,1700
    return 11.72,30,1450
N8=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
def extract_paths(mask):
    if skeletonize is not None:
        sk=skeletonize(mask.astype(bool))
    else:
        sk=mask.astype(bool)
    coords=np.argwhere(sk); cs=set((int(y),int(x)) for y,x in coords)
    def nb(p):
        y,x=p; r=[]
        for dy,dx in N8:
            q=(y+dy,x+dx)
            if q in cs: r.append(q)
        return r
    deg={p:len(nb(p)) for p in cs}; visited=set(); paths=[]
    def ek(a,b): return (a,b) if a<=b else (b,a)
    def tr(a,b):
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
                if ek(p,q) not in visited: paths.append(tr(p,q))
    for p in list(cs):
        for q in nb(p):
            if ek(p,q) not in visited: paths.append(tr(p,q))
    return paths, sk

def dpline(pt,a,b):
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
        d=dpline(points[i],a,b)
        if d>md: md=d; mi=i
    if md>eps: return rdp(points[:mi+1],eps)[:-1]+rdp(points[mi:],eps)
    return [a,b]

paths=[]; occupied=np.zeros((H,W),np.uint8); debug=np.zeros((H,W),np.uint8)
levels=[
    ('deep',.235,4.0,8,.18),
    ('dark',.155,5.0,10,.10),
    ('mid',.100,8.0,18,.00),
    ('soft',.068,14.0,30,-.08),
    ('faint_long',.046,26.0,58,-.15),
]
level_counts={}
for name,thr,min_len,min_len_sky,bias in levels:
    mask=(ink>thr).astype(np.uint8)
    # remove dust; more permissive for darker thresholds
    num,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    clean=np.zeros_like(mask)
    for i in range(1,num):
        area=int(stats[i,cv2.CC_STAT_AREA]); w=int(stats[i,cv2.CC_STAT_WIDTH]); h=int(stats[i,cv2.CC_STAT_HEIGHT])
        if area>=4 and max(w,h)>=3:
            clean[labels==i]=1
    pix_paths,sk=extract_paths(clean)
    count=0
    occ_dil=cv2.dilate(occupied,np.ones((3,3),np.uint8),iterations=1)
    for p in pix_paths:
        if len(p)<3: continue
        arr=np.array(p)
        vals=ink[arr[:,0],arr[:,1]]; dens=density[arr[:,0],arr[:,1]]
        avg=float(vals.mean()); mx=float(vals.max()); davg=float(dens.mean())
        L=sum(math.hypot(p[i+1][1]-p[i][1],p[i+1][0]-p[i][0]) for i in range(len(p)-1))
        ymean=float(arr[:,0].mean())/H
        need=min_len_sky if ymean<.34 else min_len
        if L<need: continue
        # strict for faint background/sky
        if name=='faint_long' and avg<thr*1.20 and L<70: continue
        overlap=float(occ_dil[arr[:,0],arr[:,1]].mean())
        if overlap>.72 and name!='deep': continue
        simp=rdp([(int(y),int(x)) for y,x in p], .82 if name in ('deep','dark') else 1.0)
        pts=[p2m(y,x) for y,x in simp]
        tone=max(davg, mx*1.75)
        z,shade,feed=press(tone,bias)
        paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
        occupied[arr[:,0],arr[:,1]]=1
        debug[arr[:,0],arr[:,1]]=np.maximum(debug[arr[:,0],arr[:,1]], int(255*(levels.index((name,thr,min_len,min_len_sky,bias))+1)/len(levels)))
        count+=1
    level_counts[name]=count
Image.fromarray(255-debug).save(OUT/'multilevel_debug.png')
# Add only a few controlled dark tonal strokes for jacket/forest so true trace still dominates.
def add_scan(name, angle, spacing, threshold, y0f,y1f,x0f,x1f,min_len,bias,keep):
    theta=math.radians(angle); ux=math.cos(theta); uy=math.sin(theta); nx=-uy; ny=ux
    x0=x0f*W; x1=x1f*W; y0=y0f*H; y1=y1f*H
    projs=[x*nx+y*ny for x,y in [(x0,y0),(x1,y0),(x0,y1),(x1,y1)]]
    minp,maxp=min(projs)-spacing,max(projs)+spacing; diag=math.hypot(W,H); made=0
    for si in range(int((maxp-minp)/spacing)+1):
        # deterministic skip
        hv=int.from_bytes(__import__('hashlib').sha1(f'{name}:{si}'.encode()).digest()[:4],'big')/0xffffffff
        if hv>keep: continue
        off=minp+si*spacing
        cx=(x0+x1)/2; cy=(y0+y1)/2; cp=cx*nx+cy*ny; px=cx+(off-cp)*nx; py=cy+(off-cp)*ny
        cur=[]; gap=0; segs=[]
        for t in np.arange(-diag,diag,2.2):
            x=px+t*ux; y=py+t*uy; xi=int(round(x)); yi=int(round(y))
            if xi<0 or xi>=W or yi<0 or yi>=H or xi<x0 or xi>x1 or yi<y0 or yi>y1:
                if cur:
                    gap+=1
                    if gap>2:
                        if len(cur)>=2: segs.append(cur)
                        cur=[]; gap=0
                continue
            d=float(density[yi,xi]); ok=d>=threshold
            if ok: cur.append((yi,xi,d)); gap=0
            elif cur:
                gap+=1
                if gap>2:
                    if len(cur)>=2: segs.append(cur)
                    cur=[]; gap=0
        if cur and len(cur)>=2: segs.append(cur)
        for seg in segs:
            L=sum(math.hypot(seg[i+1][1]-seg[i][1],seg[i+1][0]-seg[i][0]) for i in range(len(seg)-1))
            if L<min_len: continue
            tone=float(np.mean([q[2] for q in seg])); z,shade,feed=press(tone,bias)
            st=max(1,int(len(seg)/8)); sm=seg[::st]
            if sm[-1]!=seg[-1]: sm.append(seg[-1])
            paths.append({'pts':[p2m(y,x) for y,x,_ in sm],'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
            made+=1
    return made
extra_counts={}
extra_counts['jacket_soft_cross']=add_scan('jacket_soft_cross',54,6.2,.30,.62,.99,.27,.62,8,.08,.82)
extra_counts['jacket_deep_cross']=add_scan('jacket_deep_cross',-48,7.4,.43,.62,.99,.27,.62,8,.16,.70)
extra_counts['jacket_deep_horizontal']=add_scan('jacket_deep_horizontal',8,8.0,.55,.66,.99,.27,.62,10,.20,.56)
extra_counts['forest_deep_marks']=add_scan('forest_deep_marks',76,15,.55,.36,.61,.00,1.0,8,.12,.40)
# Border.
border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
paths.insert(0,{'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5})
# nearest order
def reorder(paths_in):
    first=paths_in[:1]; rest=paths_in[1:]; out=[]; cur=first[0]['pts'][-1]
    while rest:
        bi=0; br=False; bd=1e18; limit=min(len(rest),1800)
        for i in range(limit):
            p=rest[i]; a=p['pts'][0]; b=p['pts'][-1]
            da=math.hypot(a[0]-cur[0],a[1]-cur[1]); db=math.hypot(b[0]-cur[0],b[1]-cur[1])
            if da<bd: bi=i; br=False; bd=da
            if db<bd: bi=i; br=True; bd=db
        p=rest.pop(bi)
        if br: p=dict(p); p['pts']=list(reversed(p['pts']))
        out.append(p); cur=p['pts'][-1]
    return first+out
paths=reorder(paths); kind_counts=Counter(p['kind'] for p in paths)
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
        else: col=(55,55,55)
        d.line(pts,fill=col,width=1)
    im.save(path); im.save(path.with_suffix('.pdf'),'PDF',resolution=dpi)
render(OUT/'gemini_multilevel_true_strokes_dark_jacket_preview_pressure_gray.png',True)
render(OUT/'gemini_multilevel_true_strokes_dark_jacket_preview_black_actual.png',False,True)
render(OUT/'gemini_multilevel_true_strokes_dark_jacket_preview_dark_pressure.png',True,False,True)
SAFE=13.0; lines=['; gemini_multilevel_true_strokes_dark_jacket_a4','; multi-threshold true source strokes + minimal dark hatching','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
draw=0.0; travel=0.0; last=(0.0,0.0)
for p in paths:
    pts=p['pts']; a=pts[0]
    travel+=math.hypot(a[0]-last[0],a[1]-last[1])
    lines.append(f'; {p["kind"]} tone={p["tone"]:.3f} z={p["z"]:.2f}')
    lines.append(f'G0 Z{SAFE:.2f}'); lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}'); lines.append(f'G1 Z{p["z"]:.2f} F900')
    prev=a
    for x,y in pts[1:]:
        draw+=math.hypot(x-prev[0],y-prev[1]); lines.append(f'G1 X{x:.3f} Y{y:.3f} F{p["feed"]}'); prev=(x,y)
    lines.append(f'G0 Z{SAFE:.2f}'); last=pts[-1]
lines += ['G0 X0.000 Y0.000',f'G0 Z{SAFE:.2f}','M2']
(OUT/'gemini_multilevel_true_strokes_dark_jacket_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_multilevel_true_strokes_dark_jacket_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""MULTILEVEL TRUE STROKES DARK JACKET A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
paths: {len(paths)}
kind_counts: {dict(kind_counts)}
level_counts: {level_counts}
extra_counts: {extra_counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Closest match requires calibrated Z pressure and pencil/soft pen.
algorithm_note: extracts actual source pencil strokes in multiple tone levels. Dark zones contribute more stroke levels; faint sky strokes must be long to avoid paper-grain noise.
files:
- gemini_multilevel_true_strokes_dark_jacket_preview_pressure_gray.png/pdf
- gemini_multilevel_true_strokes_dark_jacket_preview_black_actual.png/pdf
- gemini_multilevel_true_strokes_dark_jacket_preview_dark_pressure.png/pdf
- gemini_multilevel_true_strokes_dark_jacket_a4.nc
- gemini_multilevel_true_strokes_dark_jacket_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)


