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
    skeletonize=None

SRC=Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_true_strokes_pressure_boost_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT/'source_input_copy.jpg')
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
# Paper normalization and target tone.
denoised=cv2.fastNlMeansDenoising(gray,None,7,7,21)
bg=cv2.GaussianBlur(denoised.astype(np.float32),(0,0),38)
norm=np.clip(denoised.astype(np.float32)/np.maximum(bg,1)*246,0,255).astype(np.uint8)
ink=(255-norm).astype(np.float32)/255.0
ink=cv2.GaussianBlur(ink,(0,0),0.36)
target=np.maximum(cv2.GaussianBlur(ink,(0,0),1.8)*0.82, cv2.GaussianBlur(ink,(0,0),7.5)*1.20)
lo,hi=np.percentile(target,[40,99.55])
target=np.clip((target-lo)/max(1e-6,hi-lo),0,1)
target=np.power(target,0.70)
Image.fromarray(np.uint8(255*(1-target))).save(OUT/'target_density_debug.png')
WORK_W,WORK_H=180.0,280.0
DRAW_W=176.0
scale=DRAW_W/W
DRAW_H=H*scale
if DRAW_H>270:
    DRAW_H=270.0; scale=DRAW_H/H; DRAW_W=W*scale
XOFF=(WORK_W-DRAW_W)/2.0; YTOP=(WORK_H-DRAW_H)/2.0
def p2m(y,x): return XOFF+x*scale, -(YTOP+y*scale)
def press(t,bias=0.0):
    # Wider pressure spread than previous candidates: graphite tone should come from Z, not only extra lines.
    v=max(0,min(1,t+bias))
    if v<.16: return 10.55,225,2400
    if v<.29: return 10.80,190,2250
    if v<.44: return 11.10,138,2050
    if v<.62: return 11.48,74,1700
    return 11.88,22,1400
def h01(*vals):
    data=':'.join(map(str,vals)).encode()
    return int.from_bytes(hashlib.sha1(data).digest()[:4],'big')/0xffffffff
N8=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
def extract(mask):
    sk=skeletonize(mask.astype(bool)) if skeletonize is not None else mask.astype(bool)
    coords=np.argwhere(sk); cs=set((int(y),int(x)) for y,x in coords)
    def nb(p):
        y,x=p; r=[]
        for dy,dx in N8:
            q=(y+dy,x+dx)
            if q in cs: r.append(q)
        return r
    deg={p:len(nb(p)) for p in cs}; visited=set(); out=[]
    def ek(a,b): return (a,b) if a<=b else (b,a)
    def tr(a,b):
        arr=[a,b]; visited.add(ek(a,b)); prev=a; cur=b
        while True:
            ns=[q for q in nb(cur) if q!=prev]
            if deg.get(cur,0)!=2 or not ns: break
            q=ns[0]
            if ek(cur,q) in visited: break
            visited.add(ek(cur,q)); arr.append(q); prev,cur=cur,q
        return arr
    for p,d in list(deg.items()):
        if d!=2:
            for q in nb(p):
                if ek(p,q) not in visited: out.append(tr(p,q))
    for p in list(cs):
        for q in nb(p):
            if ek(p,q) not in visited: out.append(tr(p,q))
    return out,sk
def dpline(pt,a,b):
    py,px=pt; ay,ax=a; by,bx=b
    vx=bx-ax; vy=by-ay; wx=px-ax; wy=py-ay
    c1=vx*wx+vy*wy
    if c1<=0: return math.hypot(px-ax,py-ay)
    c2=vx*vx+vy*vy
    if c2<=c1: return math.hypot(px-bx,py-by)
    t=c1/c2; return math.hypot(px-(ax+t*vx), py-(ay+t*vy))
def rdp(points,eps):
    if len(points)<3: return points
    a=points[0]; b=points[-1]; md=-1; mi=-1
    for i in range(1,len(points)-1):
        d=dpline(points[i],a,b)
        if d>md: md=d; mi=i
    if md>eps: return rdp(points[:mi+1],eps)[:-1]+rdp(points[mi:],eps)
    return [a,b]
def offset_path_pix(path, off):
    if len(path)<2: return path
    arr=[]
    for i,(y,x) in enumerate(path):
        if i==0: y2,x2=path[1]
        elif i==len(path)-1: y2,x2=path[-2]
        else: y2,x2=path[i+1]; yp,xp=path[i-1]; y2=y2-yp+y; x2=x2-xp+x
        dy=y2-y; dx=x2-x
        L=math.hypot(dx,dy) or 1.0
        nx=-dy/L; ny=dx/L
        yy=int(round(y+ny*off)); xx=int(round(x+nx*off))
        if 0<=yy<H and 0<=xx<W: arr.append((yy,xx))
    return arr if len(arr)>=2 else path
paths=[]; occupied=np.zeros((H,W),np.uint8); debug=np.zeros((H,W),np.uint8)
levels=[
    ('deep',.225,4.0,8,.16),
    ('dark',.150,5.0,10,.08),
    ('mid',.096,8.0,18,-.01),
    ('soft',.065,15.0,34,-.10),
    ('faint_long',.045,32.0,70,-.18),
]
level_counts={}; duplicate_counts=Counter()
for li,(name,thr,min_len,min_sky,bias) in enumerate(levels):
    mask=(ink>thr).astype(np.uint8)
    num,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    clean=np.zeros_like(mask)
    for i in range(1,num):
        area=int(stats[i,cv2.CC_STAT_AREA]); w=int(stats[i,cv2.CC_STAT_WIDTH]); h=int(stats[i,cv2.CC_STAT_HEIGHT])
        if area>=4 and max(w,h)>=3: clean[labels==i]=1
    pix,sk=extract(clean)
    occ=cv2.dilate(occupied,np.ones((3,3),np.uint8),iterations=1)
    count=0
    for p in pix:
        if len(p)<3: continue
        arr=np.array(p)
        vals=ink[arr[:,0],arr[:,1]]; dens=target[arr[:,0],arr[:,1]]
        avg=float(vals.mean()); mx=float(vals.max()); davg=float(dens.mean()); dmax=float(dens.max())
        L=sum(math.hypot(p[i+1][1]-p[i][1],p[i+1][0]-p[i][0]) for i in range(len(p)-1))
        ymean=float(arr[:,0].mean())/H; xmean=float(arr[:,1].mean())/W
        need=min_sky if ymean<.34 else min_len
        if L<need: continue
        if name=='faint_long' and (avg<thr*1.23 or L<78): continue
        overlap=float(occ[arr[:,0],arr[:,1]].mean())
        if overlap>.74 and name not in ('deep','dark'): continue
        simp=rdp([(int(y),int(x)) for y,x in p], .82 if name in ('deep','dark') else .98)
        tone=max(davg,dmax*.52,mx*1.65)
        z,shade,feed=press(tone,bias)
        paths.append({'pts':[p2m(y,x) for y,x in simp],'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
        occupied[arr[:,0],arr[:,1]]=1; debug[arr[:,0],arr[:,1]]=max(debug[arr[:,0],arr[:,1]].max() if False else 0, int(255*(li+1)/len(levels)))
        count+=1
        # Close parallel repeats only for truly dark/lower regions. This gives dark close-line density while staying faithful to source path.
        region_allows = ymean>.34 and tone>.46
        figure_region = .58<ymean<.99 and .24<xmean<.68
        forest_region = .34<ymean<.62
        if region_allows and name in ('deep','dark'):
            reps=0
            if tone>.54 and h01(li,count,1)<(.50 if figure_region else .28): reps+=1
            if tone>.70 and h01(li,count,2)<(.24 if figure_region else .12): reps+=1
            for r in range(reps):
                off=(0.85+0.55*r)*(1 if h01(li,count,r,3)>.5 else -1)
                op=offset_path_pix(simp,off)
                if len(op)<2: continue
                z2,shade2,feed2=press(tone,.10+bias)
                paths.append({'pts':[p2m(y,x) for y,x in op],'z':z2,'shade':shade2,'feed':feed2,'kind':name+'_close_repeat','tone':min(1,tone+.10)})
                duplicate_counts[name+'_close_repeat']+=1
    level_counts[name]=count
Image.fromarray(255-debug).save(OUT/'levels_debug.png')
# A very small amount of broad dark correction in jacket only, using close hatch not random noise.
def add_jacket_correction():
    made=0
    for y in range(int(.62*H), int(.99*H), 8):
        for x in range(int(.27*W), int(.63*W), 7):
            d=float(target[y,x])
            if d<.48 or h01(x,y,700)>min(1,(d-.45)*1.25): continue
            angle=[54,-48,8][int(h01(x,y,701)*3)%3]+(h01(x,y,702)-.5)*10
            theta=math.radians(angle)
            length=(10+24*d)*(.85+.35*h01(x,y,703))
            pts=[]; vals=[]
            for t in np.linspace(-.5,.5,6):
                px=x+t*length*math.cos(theta); py=y+t*length*math.sin(theta)
                xi=int(round(px)); yi=int(round(py))
                if 0<=xi<W and 0<=yi<H:
                    vals.append(float(target[yi,xi])); pts.append(p2m(yi,xi))
            if len(pts)>=2 and vals and np.mean(vals)>.42:
                tone=float(np.mean(vals)); z,shade,feed=press(tone,.14)
                paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':'jacket_correction','tone':tone})
                made+=1
    return made
jacket_correction_count=add_jacket_correction()
# Border.
border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
paths.insert(0,{'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5})
# Reorder nearest.
def reorder(paths_in):
    first=paths_in[:1]; rest=paths_in[1:]; out=[]; cur=first[0]['pts'][-1]
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
    return first+out
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
        else: col=(55,55,55)
        d.line(pts,fill=col,width=1)
    im.save(path); im.save(path.with_suffix('.pdf'),'PDF',resolution=dpi)
render(OUT/'gemini_true_strokes_pressure_boost_preview_pressure_gray.png',True)
render(OUT/'gemini_true_strokes_pressure_boost_preview_black_actual.png',False,True)
render(OUT/'gemini_true_strokes_pressure_boost_preview_dark_pressure.png',True,False,True)
SAFE=13.0
lines=['; gemini_true_strokes_pressure_boost_a4','; actual source strokes with boosted Z/close repeats only in dark zones','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
draw=0.0; travel=0.0; last=(0.0,0.0)
for p in paths:
    pts=p['pts']; a=pts[0]
    travel+=math.hypot(a[0]-last[0],a[1]-last[1])
    lines.append(f'; {p["kind"]} tone={p["tone"]:.3f} z={p["z"]:.2f}')
    lines.append(f'G0 Z{SAFE:.2f}')
    lines.append(f'G0 X{a[0]:.3f} Y{a[1]:.3f}')
    lines.append(f'G1 Z{p["z"]:.2f} F900')
    prev=a
    for x,y in pts[1:]:
        draw+=math.hypot(x-prev[0],y-prev[1])
        lines.append(f'G1 X{x:.3f} Y{y:.3f} F{p["feed"]}')
        prev=(x,y)
    lines.append(f'G0 Z{SAFE:.2f}')
    last=pts[-1]
lines += ['G0 X0.000 Y0.000',f'G0 Z{SAFE:.2f}','M2']
(OUT/'gemini_true_strokes_pressure_boost_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_true_strokes_pressure_boost_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""TRUE STROKES PRESSURE BOOST A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
paths: {len(paths)}
kind_counts: {dict(kind_counts)}
level_counts: {level_counts}
close_repeat_counts: {dict(duplicate_counts)}
jacket_correction_count: {jacket_correction_count}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. This candidate relies more on calibrated pencil/soft-pen Z pressure than on synthetic hatching.
algorithm_note: extracts real source pencil strokes at multiple thresholds. Dark real strokes get stronger Z and occasional close parallel repeats; light sky/faint strokes remain sparse to avoid noise.
files:
- gemini_true_strokes_pressure_boost_preview_pressure_gray.png/pdf
- gemini_true_strokes_pressure_boost_preview_black_actual.png/pdf
- gemini_true_strokes_pressure_boost_preview_dark_pressure.png/pdf
- gemini_true_strokes_pressure_boost_a4.nc
- gemini_true_strokes_pressure_boost_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
