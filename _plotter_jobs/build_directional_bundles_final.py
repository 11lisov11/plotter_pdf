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
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_directional_bundles_final_a4_pack")
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
gray=gray0[y0:y1+1, x0:x1+1]
H,W=gray.shape
Image.fromarray(gray).save(OUT/'source_cropped_gray.png')
# Normalize paper and build target tone.
denoised=cv2.fastNlMeansDenoising(gray,None,7,7,21)
bg=cv2.GaussianBlur(denoised.astype(np.float32),(0,0),38)
norm=np.clip(denoised.astype(np.float32)/np.maximum(bg,1)*246,0,255).astype(np.uint8)
ink=(255-norm).astype(np.float32)/255.0
ink=cv2.GaussianBlur(ink,(0,0),0.38)
small=cv2.GaussianBlur(ink,(0,0),2.0)
large=cv2.GaussianBlur(ink,(0,0),8.0)
target=np.maximum(small*0.82, large*1.24)
lo,hi=np.percentile(target,[40,99.55])
target=np.clip((target-lo)/max(1e-6,hi-lo),0,1)
target=np.power(target,0.72)
Image.fromarray(np.uint8(255*(1-target))).save(OUT/'target_density_debug.png')
# Structure tensor / orientation. Use denoised normalized image.
g=cv2.GaussianBlur(norm.astype(np.float32),(0,0),1.5)
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
# Base: real source strokes, but only once. This preserves real pencil contours.
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
    deg={p:len(nb(p)) for p in cs}; visited=set(); pix=[]
    def ek(a,b): return (a,b) if a<=b else (b,a)
    def tr(a,b):
        out=[a,b]; visited.add(ek(a,b)); prev=a; cur=b
        while True:
            ns=[q for q in nb(cur) if q!=prev]
            if deg.get(cur,0)!=2 or not ns: break
            q=ns[0]
            if ek(cur,q) in visited: break
            visited.add(ek(cur,q)); out.append(q); prev,cur=cur,q
        return out
    for p,d in list(deg.items()):
        if d!=2:
            for q in nb(p):
                if ek(p,q) not in visited: pix.append(tr(p,q))
    for p in list(cs):
        for q in nb(p):
            if ek(p,q) not in visited: pix.append(tr(p,q))
    return pix,sk
def dpline(pt,a,b):
    py,px=pt; ay,ax=a; by,bx=b
    vx=bx-ax; vy=by-ay; wx=px-ax; wy=py-ay
    c1=vx*wx+vy*wy
    if c1<=0: return math.hypot(px-ax,py-ay)
    c2=vx*vx+vy*vy
    if c2<=c1: return math.hypot(px-bx,py-by)
    t=c1/c2
    return math.hypot(px-(ax+t*vx), py-(ay+t*vy))
def rdp(points,eps):
    if len(points)<3: return points
    a=points[0]; b=points[-1]; md=-1; mi=-1
    for i in range(1,len(points)-1):
        d=dpline(points[i],a,b)
        if d>md: md=d; mi=i
    if md>eps: return rdp(points[:mi+1],eps)[:-1]+rdp(points[mi:],eps)
    return [a,b]
base_mask=(ink>.070).astype(np.uint8)
num,labels,stats,_=cv2.connectedComponentsWithStats(base_mask,8)
clean=np.zeros_like(base_mask)
for i in range(1,num):
    area=int(stats[i,cv2.CC_STAT_AREA]); w=int(stats[i,cv2.CC_STAT_WIDTH]); h=int(stats[i,cv2.CC_STAT_HEIGHT])
    if area>=5 and max(w,h)>=4:
        clean[labels==i]=1
pix,sk=extract(clean)
Image.fromarray(np.uint8(255-sk.astype(np.uint8)*255)).save(OUT/'base_skeleton_debug.png')
base_count=0
for p in pix:
    if len(p)<3: continue
    arr=np.array(p)
    vals=ink[arr[:,0],arr[:,1]]; dens=target[arr[:,0],arr[:,1]]
    avg=float(vals.mean()); mx=float(vals.max()); davg=float(dens.mean())
    L=sum(math.hypot(p[i+1][1]-p[i][1],p[i+1][0]-p[i][0]) for i in range(len(p)-1))
    ymean=float(arr[:,0].mean())/H
    if L<5: continue
    if avg<.055 and L<24: continue
    if ymean<.34 and avg<.082 and L<36: continue
    simp=rdp([(int(y),int(x)) for y,x in p], .92)
    pts=[p2m(y,x) for y,x in simp]
    z,shade,feed=press(max(davg,mx*1.75),-.02)
    paths.append({'pts':pts,'z':z,'shade':shade,'feed':feed,'kind':'real_trace','tone':max(davg,mx*1.75)})
    base_count+=1
# Directional bundles: integrate local orientation but in controlled regions.
def region_angle(region,y,x,seed):
    yy=y/H; xx=x/W
    if region=='sky':
        base=[24,-24,12][int(h01(x,y,seed)*3)%3]
        return base+(h01(x,y,seed+1)-.5)*10
    if region=='forest':
        base=[70,-55,88,45,102][int(h01(x,y,seed)*5)%5]
        return base+(h01(x,y,seed+1)-.5)*16
    if region=='field':
        base=[-12,-7,12,16][int(h01(x,y,seed)*4)%4]
        return base+(h01(x,y,seed+1)-.5)*8
    if region=='grass':
        base=[72,86,102,58,115][int(h01(x,y,seed)*5)%5]
        return base+(h01(x,y,seed+1)-.5)*18
    if region=='hair':
        a=math.degrees(float(orient[y,x]))
        if a<-25: a+=180
        if a>155: a-=180
        return max(56,min(126,a+(h01(x,y,seed+2)-.5)*18))
    if region=='figure':
        base=[55,-48,8,75][int(h01(x,y,seed)*4)%4]
        return base+(h01(x,y,seed+1)-.5)*12
    return math.degrees(float(orient[y,x]))
def add_bundle(name,region,y0f,y1f,x0f,x1f,step,thr,prob,len_min,len_max,bias,seed,min_active=.52):
    made=0
    y0i=int(y0f*H); y1i=int(y1f*H); x0i=int(x0f*W); x1i=int(x1f*W)
    sy=max(2,int(step)); sx=max(2,int(step))
    for gy,y0 in enumerate(range(y0i,y1i,sy)):
        for gx,x0 in enumerate(range(x0i,x1i,sx)):
            cx=int(round(x0+(h01(gx,gy,seed)-.5)*step*.9))
            cy=int(round(y0+(h01(gx,gy,seed+1)-.5)*step*.9))
            if cx<0 or cx>=W or cy<0 or cy>=H: continue
            d=float(target[cy,cx])
            if d<thr: continue
            take=min(1.0, ((d-thr)/max(1e-6,1-thr))**0.55*prob)
            if h01(gx,gy,seed+2)>take: continue
            angle=region_angle(region,cy,cx,seed+3)
            theta=math.radians(angle)
            length=(len_min+(len_max-len_min)*(d**.82))*(.82+.42*h01(gx,gy,seed+4))
            bend=(h01(gx,gy,seed+5)-.5)*4.5
            pts=[]; samples=[]
            # two close companion lines in dark areas imitate pencil bundles, not random fill.
            companions=1 + (1 if d>.55 and h01(gx,gy,seed+6)<.45 else 0)
            for c in range(companions):
                offset=(c-.5*(companions-1))*(1.8+2.8*d)
                sub=[]; sub_samples=[]
                nx=math.cos(theta+math.pi/2); ny=math.sin(theta+math.pi/2)
                for t in np.linspace(-.5,.5,7):
                    curve=bend*math.sin((t+.5)*math.pi)
                    px=cx+t*length*math.cos(theta)+(offset+curve)*nx
                    py=cy+t*length*math.sin(theta)+(offset+curve)*ny
                    xi=int(round(px)); yi=int(round(py))
                    if 0<=xi<W and 0<=yi<H:
                        sub_samples.append(float(target[yi,xi])); sub.append(p2m(yi,xi))
                if len(sub)>=2 and sub_samples and sum(v>=thr*.70 for v in sub_samples)/len(sub_samples)>=min_active:
                    tone=float(np.mean(sub_samples))
                    z,shade,feed=press(max(d,tone),bias)
                    paths.append({'pts':sub,'z':z,'shade':shade,'feed':feed,'kind':name,'tone':max(d,tone)})
                    made+=1
    return made
counts={}
counts['sky_cloud_bundles']=add_bundle('sky_cloud_bundles','sky',.02,.35,.0,1.0,23,.34,.35,15,36,-.14,10,.60)
counts['forest_mid_bundles']=add_bundle('forest_mid_bundles','forest',.34,.62,.0,1.0,9.0,.18,.68,10,28,-.04,20,.50)
counts['forest_dark_bundles']=add_bundle('forest_dark_bundles','forest',.34,.62,.0,1.0,6.0,.34,.72,10,30,.10,30,.48)
counts['field_flow_bundles']=add_bundle('field_flow_bundles','field',.50,.78,.0,1.0,8.5,.15,.55,28,76,-.09,40,.58)
counts['field_dark_bundles']=add_bundle('field_dark_bundles','field',.50,.78,.0,1.0,7.2,.34,.50,18,52,.03,45,.54)
counts['grass_light_bundles']=add_bundle('grass_light_bundles','grass',.68,.99,.0,1.0,7.0,.15,.55,8,22,-.06,50,.46)
counts['grass_dark_bundles']=add_bundle('grass_dark_bundles','grass',.68,.99,.0,1.0,5.2,.34,.70,8,24,.10,60,.45)
counts['figure_mid_bundles']=add_bundle('figure_mid_bundles','figure',.60,.99,.24,.66,5.6,.21,.82,10,30,.06,70,.46)
counts['figure_dark_bundles']=add_bundle('figure_dark_bundles','figure',.60,.99,.24,.66,4.3,.38,.86,12,34,.18,80,.44)
counts['hair_flow_bundles']=add_bundle('hair_flow_bundles','hair',.52,.80,.38,.76,5.5,.18,.78,15,46,-.03,90,.48)
# Border.
border=[(XOFF,-YTOP),(XOFF+DRAW_W,-YTOP),(XOFF+DRAW_W,-(YTOP+DRAW_H)),(XOFF,-(YTOP+DRAW_H)),(XOFF,-YTOP)]
paths.insert(0,{'pts':border,'z':11.10,'shade':120,'feed':1900,'kind':'border','tone':.5})
# Reorder nearest, border first.
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
render(OUT/'gemini_directional_bundles_final_preview_pressure_gray.png',True)
render(OUT/'gemini_directional_bundles_final_preview_black_actual.png',False,True)
render(OUT/'gemini_directional_bundles_final_preview_dark_pressure.png',True,False,True)
SAFE=13.0
lines=['; gemini_directional_bundles_final_a4','; real trace plus directional tone bundles: dark close lines, light sparse, no G0 drawing','G21','G90',f'G0 Z{SAFE:.2f}','G0 X0.000 Y0.000']
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
(OUT/'gemini_directional_bundles_final_a4.nc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'gemini_directional_bundles_final_a4.gcode').write_text('\n'.join(lines)+'\n',encoding='utf-8')
readme=f"""DIRECTIONAL BUNDLES FINAL A4 package
source: {SRC}
output_dir: {OUT}
image_px_after_crop: {W} x {H}
work_area_mm: {WORK_W:.1f} x {WORK_H:.1f}
drawing_size_mm: {DRAW_W:.2f} x {DRAW_H:.2f}
paths: {len(paths)}
base_real_trace_paths: {base_count}
kind_counts: {dict(kind_counts)}
bundle_counts: {counts}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Closest match requires calibrated Z pressure and pencil/soft pen.
algorithm_note: preserves real extracted source strokes, then adds region-aware directional bundles. Dark zones receive close companion strokes; light sky/cloud regions are sparse and threshold-protected.
files:
- gemini_directional_bundles_final_preview_pressure_gray.png/pdf
- gemini_directional_bundles_final_preview_black_actual.png/pdf
- gemini_directional_bundles_final_preview_dark_pressure.png/pdf
- gemini_directional_bundles_final_a4.nc
- gemini_directional_bundles_final_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
