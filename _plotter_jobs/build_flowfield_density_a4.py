from __future__ import annotations
from pathlib import Path
import math, random
from collections import Counter

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from scipy.ndimage import gaussian_filter, map_coordinates, binary_closing
from skimage.morphology import remove_small_objects, skeletonize

SRC=Path(r'C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg')
OUT=Path(r'C:\plotter_pdf\_plotter_jobs\gemini_flowfield_density_a4_pack')
OUT.mkdir(parents=True, exist_ok=True)
random.seed(622026); np.random.seed(622026)
DW,DH,TOP,SAFE=180.0,240.0,20.0,280.0
UP,DOWN,TF,DF=3.5,0.0,3000,1200
PPM=4

img0=Image.open(SRC).convert('L')
W=920; H=round(img0.size[1]*W/img0.size[0])
img=img0.resize((W,H),Image.Resampling.LANCZOS)
w,h=img.size
gray=np.asarray(img,dtype=np.float32)/255.0
bg=gaussian_filter(gray,30)
flat=np.clip(gray/np.maximum(bg,0.58),0,1)
flat=np.clip((flat-0.04)/0.96,0,1)
tone_raw=1-flat
tone=np.clip((gaussian_filter(tone_raw,2.0)-0.016)/0.37,0,1)
tone_dark=gaussian_filter(tone_raw,0.85)

# Structure-tensor direction field: line direction follows local pencil/edge form.
blur=gaussian_filter(flat,1.2)
gx=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3)
gy=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3)
Jxx=gaussian_filter(gx*gx,4.0); Jyy=gaussian_filter(gy*gy,4.0); Jxy=gaussian_filter(gx*gy,4.0)
edge_angle=0.5*np.arctan2(2*Jxy, Jxx-Jyy) + math.pi/2.0
coh=np.sqrt((Jxx-Jyy)**2+4*Jxy*Jxy)/(Jxx+Jyy+1e-6)
coh=np.clip(coh,0,1)

yy,xx=np.mgrid[0:h,0:w]
xn=xx/(w-1); yn=yy/(h-1)
hair=((((xn-.535)/.155)**2+((yn-.640)/.170)**2)<1)|((((xn-.635)/.185)**2+((yn-.660)/.120)**2)<1)
jacket=((((xn-.455)/.170)**2+((yn-.845)/.185)**2)<1)|((((xn-.365)/.110)**2+((yn-.785)/.110)**2)<1)
arm=((((xn-.365)/.105)**2+((yn-.725)/.085)**2)<1)
fig=hair|jacket|arm
sky=yn<.330
forest=(yn>.310)&(yn<.525)&(~fig)
field=(yn>.440)&(yn<.790)&(~fig)
grass=(yn>.635)&(~fig)

paths=[]
def add(kind, pts, min_len=7.0):
    if len(pts)<2: return
    clean=[pts[0]]; length=0.0; last=pts[0]
    for p in pts[1:]:
        d=math.hypot(p[0]-last[0],p[1]-last[1])
        if d>=0.7:
            clean.append(p); length+=d; last=p
    if len(clean)>=2 and length>=min_len:
        paths.append((kind,clean))

def simp(kind, pts, eps=.9, min_len=7.0):
    if len(pts)<2: return
    a=np.array(pts,dtype=np.float32).reshape((-1,1,2))
    ap=cv2.approxPolyDP(a,eps,False).reshape((-1,2))
    add(kind,[(float(x),float(y)) for x,y in ap],min_len)

def in_mask(mask,x,y):
    ix=int(round(x)); iy=int(round(y))
    return 0<=ix<w and 0<=iy<h and bool(mask[iy,ix])

def sample_arr(arr,x,y,default=0.0):
    if x<0 or y<0 or x>=w-1 or y>=h-1: return default
    return float(map_coordinates(arr, [[y],[x]], order=1, mode='nearest')[0])

def mix_line_angle(a,b,weight):
    # line orientation is modulo pi, so mix double-angle vectors.
    z=(1-weight)*complex(math.cos(2*a),math.sin(2*a))+weight*complex(math.cos(2*b),math.sin(2*b))
    return 0.5*math.atan2(z.imag,z.real)

def local_angle(x,y,base,blend):
    ea=sample_arr(edge_angle,x,y,base)
    c=sample_arr(coh,x,y,0.0)
    return mix_line_angle(base,ea,min(0.85,blend*c))

def trace_flow(kind,cx,cy,mask,base,length,step=4.0,blend=.55,jitter=.06,min_len=8.0,offset=0.0):
    a0=local_angle(cx,cy,base,blend)
    px=-math.sin(a0); py=math.cos(a0)
    cx2=cx+px*offset; cy2=cy+py*offset
    if not in_mask(mask,cx2,cy2): return
    rng=random.Random(int(cx2*37+cy2*53+length*11+base*1000)&0xffffffff)
    def walk(sign):
        pts=[]; x=cx2; y=cy2; dist=0.0; last_a=a0
        while dist<length/2:
            if not in_mask(mask,x,y): break
            pts.append((x,y))
            a=local_angle(x,y,base,blend)
            # prevent sudden flips in line field
            if math.cos(a-last_a)<0: a+=math.pi
            a=0.70*a+0.30*last_a + rng.uniform(-jitter,jitter)
            x += sign*math.cos(a)*step
            y += sign*math.sin(a)*step
            dist += step; last_a=a
        return pts
    back=walk(-1); fwd=walk(1)
    pts=list(reversed(back))+fwd[1:]
    simp(kind,pts,.85,min_len)

def flow_seeds(kind,mask,thr,tile,max_groups,base_angles,length_rng,parmax,gap,blend,jitter,gamma,seed,cap):
    rng=random.Random(seed); made=0
    for y0 in range(0,h,tile):
      for x0 in range(0,w,tile):
        if made>=cap: return
        y1=min(h,y0+tile); x1=min(w,x0+tile)
        m=mask[y0:y1,x0:x1]
        if np.count_nonzero(m)<max(9,int(tile*tile*.10)): continue
        vals=tone[y0:y1,x0:x1][m]
        if vals.size==0: continue
        avg=float(vals.mean()); mx=float(vals.max()); val=.62*avg+.38*mx
        if val<thr: continue
        strength=max(0,min(1,(val-thr)/(1-thr)))**gamma
        want=max_groups*strength
        ng=int(want)+(1 if rng.random()<want-int(want) else 0)
        if ng<=0 and mx>thr+.12: ng=1
        if ng<=0: continue
        ys,xs=np.where(m)
        weights=np.maximum(tone[y0:y1,x0:x1][ys,xs],.001); weights=weights/weights.sum()
        for _ in range(ng):
            if made>=cap: return
            idx=int(np.random.choice(np.arange(len(xs)),p=weights))
            cx=x0+float(xs[idx])+rng.uniform(-.10,.10)*tile
            cy=y0+float(ys[idx])+rng.uniform(-.10,.10)*tile
            if not in_mask(mask,cx,cy): continue
            loc=sample_arr(tone,cx,cy,0.0)
            base=math.radians(rng.choice(base_angles)+rng.uniform(-7,7))
            length=rng.uniform(*length_rng)*(0.75+0.70*loc)
            npar=1+min(parmax-1,int((0.20*strength+0.80*loc)*(parmax-1)+.22))
            for k in range(npar):
                off=(k-(npar-1)/2)*gap*rng.uniform(.9,1.1)
                trace_flow(kind,cx,cy,mask,base,length,step=4.2,blend=blend,jitter=jitter,min_len=max(6.5,length_rng[0]*.42),offset=off)
            made+=1

# Dark true contours, but hard-filtered so paper grain does not become strokes.
b=(tone_dark>.165)
b=binary_closing(b,np.ones((2,2),bool))
b=remove_small_objects(b,min_size=38)
sk=skeletonize(b).astype(np.uint8)*255
contours,_=cv2.findContours(sk,cv2.RETR_LIST,cv2.CHAIN_APPROX_NONE)
for c in contours:
    if len(c)<10: continue
    x,y,ww,hh=cv2.boundingRect(c); arc=cv2.arcLength(c,False)
    if arc<22 or ww<3 or hh<3: continue
    local=float(tone[y:min(h,y+hh),x:min(w,x+ww)].mean()); ymid=(y+.5*hh)/h
    if ymid<.33 and (arc<78 or local<.15): continue
    if local<.09 and arc<65: continue
    simp('dark_contour',[(float(p[0][0]),float(p[0][1])) for p in c],1.15,14)

# Flow-field tone strokes by region.
flow_seeds('forest_flow_light',forest,.050,30,2,[-62,58],(12,27),1,2.2,.45,.070,.83,1001,250)
flow_seeds('forest_flow_dark',forest,.150,23,2,[-65,55,84],(10,24),2,2.2,.50,.075,.80,1002,430)
flow_seeds('forest_flow_deep',forest,.285,20,2,[-68,52,86],(8,19),2,2.1,.55,.080,.78,1003,280)
flow_seeds('field_flow_light',field,.045,42,1,[-13,-9],(28,72),1,2.5,.35,.045,.90,2001,115)
flow_seeds('field_flow_mid',field,.150,36,1,[-15,16],(20,48),2,2.4,.38,.045,.92,2002,65)
flow_seeds('grass_flow',grass,.075,28,2,[-82,76,-68],(10,30),2,2.0,.35,.075,.92,3001,230)
flow_seeds('jacket_flow_light',jacket,.060,20,2,[-52,44],(15,34),2,2.4,.30,.050,.88,4001,440)
flow_seeds('jacket_flow_dark',jacket,.225,18,2,[-55,43,-74],(12,30),2,2.8,.32,.055,.82,4002,470)
flow_seeds('hair_shadow_flow',hair,.145,23,1,[-72],(18,40),2,2.2,.42,.035,.84,5001,130)

# Sparse hand-looking sky clusters.
def skycl(cx,cy,rx,ry,ang,cnt,lf,cross=False):
    rng=random.Random(int(cx*13000+cy*17000+cnt*37)); a=math.radians(ang); e=(math.cos(a),math.sin(a)); p=(-math.sin(a),math.cos(a))
    for i in range(cnt):
        band=(i/max(1,cnt-1)-.5)*2
        op=band*ry*h*.7+rng.uniform(-.008,.008)*h; oe=rng.uniform(-.5,.5)*rx*w
        x=cx*w+e[0]*oe+p[0]*op; y=cy*h+e[1]*oe+p[1]*op
        if (((x/w-cx)/rx)**2+((y/h-cy)/ry)**2)>1.08: continue
        length=lf*w*rng.uniform(.55,1.02)
        pts=[]
        for k in range(8):
            t=k/7-.5
            pts.append((x+e[0]*length*t+p[0]*rng.uniform(-1.2,1.2), y+e[1]*length*t+p[1]*rng.uniform(-1.2,1.2)))
        simp('sky_cross' if cross else 'sky',pts,.7,13)
for args in [(0.125,.095,.155,.052,-35,22,.056,False),(0.150,.235,.180,.050,-26,14,.050,False),(0.310,.125,.130,.048,-32,11,.044,False),(0.505,.285,.135,.047,-22,9,.041,False),(0.775,.175,.165,.055,-27,17,.050,False),(0.825,.285,.150,.050,-25,11,.045,False),(0.180,.270,.160,.040,30,5,.037,True),(0.790,.300,.145,.040,28,5,.036,True)]: skycl(*args)

# Semantic hair and jacket folds; keep these deliberately long and readable.
def bez(p0,p1,p2,p3,n=54):
    out=[]
    for i in range(n):
        t=i/(n-1)
        out.append(((1-t)**3*p0[0]+3*(1-t)**2*t*p1[0]+3*(1-t)*t*t*p2[0]+t**3*p3[0],(1-t)**3*p0[1]+3*(1-t)**2*t*p1[1]+3*(1-t)*t*t*p2[1]+t**3*p3[1]))
    return out
def clip_curve(kind,pts,mask,min_len):
    run=[]
    for x,y in pts:
        if in_mask(mask,x,y): run.append((x,y))
        else:
            if run: simp(kind,run,.85,min_len)
            run=[]
    if run: simp(kind,run,.85,min_len)
rng=random.Random(811)
for i in range(96):
    t=i/95
    crown=((.505+.075*(t-.5)+rng.uniform(-.010,.010))*w,(.515+.045*math.sin(t*math.pi)+rng.uniform(-.006,.008))*h)
    if i<40:
        end=((.410+.145*t+rng.uniform(-.012,.012))*w,(.735+.030*math.sin(t*4)+rng.uniform(-.012,.012))*h); c1=((.440+.06*t)*w,(.590+rng.uniform(-.015,.015))*h); c2=((.395+.11*t)*w,(.690+rng.uniform(-.018,.018))*h)
    else:
        tt=(i-40)/55
        end=((.545+.220*tt+rng.uniform(-.013,.013))*w,(.700+.080*math.sin(tt*math.pi)+rng.uniform(-.016,.016))*h); c1=((.545+.075*tt)*w,(.580+rng.uniform(-.016,.016))*h); c2=((.610+.180*tt)*w,(.650+rng.uniform(-.018,.018))*h)
    clip_curve('hair_flow',bez(crown,c1,c2,end,58),hair,16)
for i in range(32):
    t=i/31; x0=(.325+.235*t+rng.uniform(-.008,.008))*w; y0=(.690+.035*math.sin(t*math.pi)+rng.uniform(-.006,.006))*h
    x3=(.350+.195*t+rng.uniform(-.010,.010))*w; y3=(.970+rng.uniform(-.008,.008))*h
    clip_curve('jacket_fold',bez((x0,y0),((x0+x3)/2-.05*w,.780*h),((x0+x3)/2+.03*w,.900*h),(x3,y3),46),jacket,18)

# Clean source-like page border.
m=18; add('outer_border',[(m,m),(w-m,m),(w-m,h-m),(m,h-m),(m,m)],10)

# Convert/order/write/render.
def p2m(p): return (p[0]/w*DW, -(TOP+p[1]/h*DH))
mm=[]
for kind,pts in paths:
    arr=[p2m(p) for p in pts]
    clean=[arr[0]]; length=0
    for p in arr[1:]:
        d=math.hypot(p[0]-clean[-1][0],p[1]-clean[-1][1])
        if d>=.12: clean.append(p); length+=d
    if len(clean)>=2 and length>=.6: mm.append((kind,clean))
rem=mm[:]; ordered=[]; pos=(0,0)
while rem:
    bi=0; br=False; bd=1e9
    for i,(_,pts) in enumerate(rem):
        d0=math.hypot(pts[0][0]-pos[0],pts[0][1]-pos[1]); d1=math.hypot(pts[-1][0]-pos[0],pts[-1][1]-pos[1])
        if d0<bd: bi=i; br=False; bd=d0
        if d1<bd: bi=i; br=True; bd=d1
    kind,pts=rem.pop(bi)
    if br: pts=list(reversed(pts))
    ordered.append((kind,pts)); pos=pts[-1]
name='gemini_flowfield_density_a4'
nc=OUT/f'{name}.nc'; gcode=OUT/f'{name}.gcode'
lines=['; flowfield density A4','G21','G90',f'G0 Z{UP:.3f}',f'F{TF}']
draw=travel=0; last=(0,0)
for kind,pts in ordered:
    st=pts[0]; travel+=math.hypot(st[0]-last[0],st[1]-last[1]); lines += [f'G0 X{st[0]:.3f} Y{st[1]:.3f}', f'G1 Z{DOWN:.3f} F{DF}']; prev=st
    for x,y in pts[1:]: draw+=math.hypot(x-prev[0],y-prev[1]); lines.append(f'G1 X{x:.3f} Y{y:.3f}'); prev=(x,y)
    lines.append(f'G0 Z{UP:.3f}'); last=pts[-1]
lines.append('M2'); text='\n'.join(lines)+'\n'; nc.write_text(text,encoding='ascii'); gcode.write_text(text,encoding='ascii')
def mm2px(p): return (round(p[0]*PPM), round(-p[1]*PPM))
def render(path,gray=False):
    out=Image.new('RGB',(round(DW*PPM),round(SAFE*PPM)),'white'); dr=ImageDraw.Draw(out); dr.rectangle([0,0,out.width-1,out.height-1],outline=(225,225,225))
    for kind,pts in ordered:
        if gray:
            col=(32,32,32) if ('dark' in kind or kind in {'outer_border','hair_flow','jacket_fold','dark_contour'}) else (80,80,80) if ('forest' in kind or 'jacket' in kind or 'hair' in kind) else (132,132,132)
        else: col=(0,0,0)
        dr.line([mm2px(p) for p in pts],fill=col,width=1)
    out.save(path)
black=OUT/f'{name}_preview_black_actual.png'; grayp=OUT/f'{name}_preview_pressure_gray.png'; render(black,False); render(grayp,True)
def make_pdf(png,pdfp):
    c=canvas.Canvas(str(pdfp),pagesize=A4); pw,ph=A4; mar=16; im=Image.open(png); sc=min((pw-2*mar)/im.width,(ph-2*mar)/im.height); c.drawImage(str(png),(pw-im.width*sc)/2,(ph-im.height*sc)/2,im.width*sc,im.height*sc); c.showPage(); c.save()
blackpdf=OUT/f'{name}_preview_black_actual.pdf'; graypdf=OUT/f'{name}_preview_pressure_gray.pdf'; make_pdf(black,blackpdf); make_pdf(grayp,graypdf)
counts=Counter(k for k,_ in ordered)
(OUT/'README_result.txt').write_text('FLOWFIELD DENSITY A4 package\n'+f'source: {SRC}\n'+f'nc: {nc}\n'+f'gcode: {gcode}\n'+f'preview_black_actual_png: {black}\n'+f'preview_black_actual_pdf: {blackpdf}\n'+f'preview_pressure_gray_png: {grayp}\n'+f'preview_pressure_gray_pdf: {graypdf}\n'+f'paths_total: {len(ordered)}\n'+f'kind_counts: {dict(counts)}\n'+f'draw_length_m: {draw/1000:.2f}\n'+f'travel_length_m: {travel/1000:.2f}\n'+f'estimated_time_min_ideal: {(draw/(DF/60)+travel/(TF/60))/60:.1f}\n'+'algorithm_note: structure-tensor flowfield hatching; dark cells get close parallel strokes, light cells sparse flow strokes.\n',encoding='utf-8')
print('FLOWFIELD DENSITY A4 package'); print('paths_total:',len(ordered)); print('kind_counts:',dict(counts)); print('draw_length_m:',round(draw/1000,2)); print('travel_length_m:',round(travel/1000,2)); print('estimated_time_min_ideal:',round((draw/(DF/60)+travel/(TF/60))/60,1)); print('preview:',black); print('pdf:',blackpdf); print('nc:',nc)
