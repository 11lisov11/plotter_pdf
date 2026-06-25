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
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_adaptive_tonal_lines_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SRC, OUT/'source_input_copy.jpg')
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
# Normalize paper. Use smooth target tone; paper/JPEG grain should not become strokes.
denoised=cv2.fastNlMeansDenoising(gray,None,7,7,21)
bg=cv2.GaussianBlur(denoised.astype(np.float32),(0,0),38)
norm=np.clip(denoised.astype(np.float32)/np.maximum(bg,1)*246,0,255).astype(np.uint8)
ink=(255-norm).astype(np.float32)/255.0
ink=cv2.GaussianBlur(ink,(0,0),0.40)
detail=cv2.GaussianBlur(ink,(0,0),1.6)
mass=cv2.GaussianBlur(ink,(0,0),8.5)
target=np.maximum(detail*0.76, mass*1.28)
lo,hi=np.percentile(target,[40,99.55])
target=np.clip((target-lo)/max(1e-6,hi-lo),0,1)
target=np.power(target,0.74)
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
    v=max(0,min(1,t+bias))
    if v<.18: return 10.62,215,2350
    if v<.32: return 10.86,178,2200
    if v<.48: return 11.10,130,2000
    if v<.66: return 11.38,82,1700
    return 11.72,30,1450
def h01(*vals):
    data=':'.join(map(str,vals)).encode()
    return int.from_bytes(hashlib.sha1(data).digest()[:4],'big')/0xffffffff
paths=[]
# Add real contour/stroke skeleton, but slightly stricter than previous so it does not dominate with noise.
def extract(mask):
    sk=skeletonize(mask.astype(bool)) if skeletonize is not None else mask.astype(bool)
    coords=np.argwhere(sk); cs=set((int(y),int(x)) for y,x in coords)
    N8=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
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
mask=(ink>.082).astype(np.uint8)
num,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
clean=np.zeros_like(mask)
for i in range(1,num):
    area=int(stats[i,cv2.CC_STAT_AREA]); w=int(stats[i,cv2.CC_STAT_WIDTH]); h=int(stats[i,cv2.CC_STAT_HEIGHT])
    if area>=5 and max(w,h)>=4: clean[labels==i]=1
pix,sk=extract(clean)
Image.fromarray(np.uint8(255-sk.astype(np.uint8)*255)).save(OUT/'contour_skeleton_debug.png')
contour_count=0
for p in pix:
    if len(p)<3: continue
    arr=np.array(p); dens=target[arr[:,0],arr[:,1]]; vals=ink[arr[:,0],arr[:,1]]
    davg=float(dens.mean()); avg=float(vals.mean()); mx=float(vals.max())
    L=sum(math.hypot(p[i+1][1]-p[i][1],p[i+1][0]-p[i][0]) for i in range(len(p)-1))
    ymean=float(arr[:,0].mean())/H
    if L<5: continue
    if ymean<.34 and L<34 and avg<.11: continue
    if avg<.07 and L<22: continue
    simp=rdp([(int(y),int(x)) for y,x in p],.92)
    pts=[p2m(y,x) for y,x in simp]
    z,shade,feed=press(max(davg,mx*1.55),-.03)
    paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':'source_contour','tone':max(davg,mx*1.55)})
    contour_count+=1
# Adaptive clipped hatch layers. Each layer is a tone threshold; dark areas receive several layers.
def add_layer(name,angle,spacing,thr,y0f,y1f,x0f,x1f,min_len,bias,keep=1.0,phase=0.0,wobble=1.6,split_len=64):
    theta=math.radians(angle); ux=math.cos(theta); uy=math.sin(theta); nx=-uy; ny=ux
    x0=x0f*W; x1=x1f*W; y0=y0f*H; y1=y1f*H
    corners=[(x0,y0),(x1,y0),(x0,y1),(x1,y1)]
    projs=[x*nx+y*ny for x,y in corners]
    minp,maxp=min(projs)-spacing,max(projs)+spacing
    diag=math.hypot(W,H); count=int((maxp-minp)/spacing)+1; made=0
    for si in range(count):
        if h01(hash(name),si,1)>keep: continue
        off=minp+si*spacing+phase+(h01(hash(name),si,2)-.5)*wobble
        cx=(x0+x1)/2; cy=(y0+y1)/2; cp=cx*nx+cy*ny; px=cx+(off-cp)*nx; py=cy+(off-cp)*ny
        cur=[]; segs=[]; gap=0
        for t in np.arange(-diag,diag,1.9):
            x=px+t*ux; y=py+t*uy
            # small deterministic pencil wobble along the normal, not enough to look noisy
            ww=(h01(hash(name),si,int((t+diag)/19),3)-.5)*1.15
            x+=ww*nx; y+=ww*ny
            xi=int(round(x)); yi=int(round(y))
            if xi<0 or xi>=W or yi<0 or yi>=H or xi<x0 or xi>x1 or yi<y0 or yi>y1:
                if cur:
                    gap+=1
                    if gap>2:
                        if len(cur)>=2: segs.append(cur)
                        cur=[]; gap=0
                continue
            d=float(target[yi,xi])
            ok=d>=thr
            # hard sky protection: only substantial cloud mass may be hatched.
            if yi/H<.32 and d<thr+.14: ok=False
            if ok:
                cur.append((yi,xi,d)); gap=0
            elif cur:
                gap+=1
                if gap>2:
                    if len(cur)>=2: segs.append(cur)
                    cur=[]; gap=0
        if cur and len(cur)>=2: segs.append(cur)
        for seg in segs:
            L=sum(math.hypot(seg[i+1][1]-seg[i][1],seg[i+1][0]-seg[i][0]) for i in range(len(seg)-1))
            if L<min_len: continue
            # split long lines into pencil strokes with small spaces so it does not look mechanically ruled
            pieces=[]
            if L>split_len*1.35:
                piece_pts=max(3,int(split_len/1.9))
                step=max(2,int(piece_pts*.72))
                for st in range(0,len(seg)-2,step):
                    en=min(len(seg),st+piece_pts)
                    if en-st>=2: pieces.append(seg[st:en])
            else:
                pieces=[seg]
            for piece in pieces:
                if len(piece)<2: continue
                tone=float(np.mean([q[2] for q in piece]))
                z,shade,feed=press(tone,bias)
                st=max(1,int(len(piece)/8)); sample=piece[::st]
                if sample[-1]!=piece[-1]: sample.append(piece[-1])
                pts=[p2m(y,x) for y,x,_ in sample]
                paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':tone})
                made+=1
    return made
counts={}
# Sky/clouds: very sparse hatch like reference.
counts['sky_soft_a']=add_layer('sky_soft_a',24,30,.34,.02,.35,.0,1.0,22,-.14,.50,3,1.2,60)
counts['sky_soft_b']=add_layer('sky_soft_b',-24,38,.48,.02,.35,.0,1.0,18,-.10,.38,9,1.0,55)
# Forest: tonal mass with diagonal/vertical hatch, light pressure.
counts['forest_a']=add_layer('forest_a',64,12,.19,.34,.62,.0,1.0,10,-.06,.86,0,1.6,42)
counts['forest_b']=add_layer('forest_b',-56,15,.33,.34,.62,.0,1.0,9,.03,.68,5,1.6,38)
counts['forest_c']=add_layer('forest_c',88,13,.50,.34,.62,.0,1.0,8,.10,.54,2,1.2,34)
# Hills/field: long flowing strokes.
counts['field_a']=add_layer('field_a',-11,8.5,.15,.50,.77,.0,1.0,30,-.10,.82,0,1.1,78)
counts['field_b']=add_layer('field_b',14,15,.34,.50,.78,.0,1.0,24,-.02,.52,5,1.0,60)
# Grass foreground: sparse where light, close where dark.
counts['grass_a']=add_layer('grass_a',78,8.5,.17,.68,.99,.0,1.0,8,-.06,.72,0,1.5,26)
counts['grass_b']=add_layer('grass_b',103,12,.36,.68,.99,.0,1.0,8,.08,.56,5,1.5,24)
counts['grass_c']=add_layer('grass_c',-62,16,.55,.68,.99,.0,1.0,8,.15,.42,7,1.3,22)
# Figure: controlled dense hatch, not black mass.
counts['figure_a']=add_layer('figure_a',56,7.2,.27,.60,.99,.24,.66,9,.05,.74,0,1.4,34)
counts['figure_b']=add_layer('figure_b',-48,9.0,.45,.60,.99,.24,.66,8,.15,.58,4,1.2,32)
counts['figure_c']=add_layer('figure_c',8,9.0,.61,.62,.99,.24,.66,8,.20,.42,2,1.0,30)
# Hair direction, kept separate and not too dense.
counts['hair_a']=add_layer('hair_a',88,7.5,.23,.52,.80,.38,.76,12,-.04,.60,0,1.3,42)
counts['hair_b']=add_layer('hair_b',108,10,.39,.52,.80,.38,.76,10,.06,.45,4,1.2,36)
# Border.
border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
paths.insert(0,{'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5})
# Reorder nearest, keep border first.
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
        if br:
            p=dict(p); p['pts']=list(reversed(p['pts']))
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
render(OUT/'gemini_adaptive_tonal_lines_preview_pressure_gray.png',True)
render(OUT/'gemini_adaptive_tonal_lines_preview_black_actual.png',False,True)
render(OUT/'gemini_adaptive_tonal_lines_preview_dark_pressure.png',True,False,True)
SAFE=13.0
lines=['; gemini_adaptive_tonal_lines_a4','; adaptive clipped tonal hatch: dark close lines, light sparse, no G0 drawing','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
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
(OUT/'gemini_adaptive_tonal_lines_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_adaptive_tonal_lines_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""ADAPTIVE TONAL LINES A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
paths: {len(paths)}
source_contour_paths: {contour_count}
kind_counts: {dict(kind_counts)}
layer_counts: {counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Closest match requires calibrated Z pressure and pencil/soft pen.
algorithm_note: uses clipped tonal hatch layers. Dark zones receive multiple close line families; light regions and sky are protected by high thresholds. Source contour strokes are overlaid for real detail.
files:
- gemini_adaptive_tonal_lines_preview_pressure_gray.png/pdf
- gemini_adaptive_tonal_lines_preview_black_actual.png/pdf
- gemini_adaptive_tonal_lines_preview_dark_pressure.png/pdf
- gemini_adaptive_tonal_lines_a4.nc
- gemini_adaptive_tonal_lines_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
