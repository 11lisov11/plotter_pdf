from pathlib import Path
import math, random
from collections import Counter
import cv2, numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from scipy.ndimage import gaussian_filter, binary_closing
from skimage.morphology import remove_small_objects, skeletonize

SRC=Path(r'C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg')
OUT=Path(r'C:\plotter_pdf\_plotter_jobs\gemini_hybrid_best_density_a4_pack'); OUT.mkdir(parents=True,exist_ok=True)
random.seed(62026); np.random.seed(62026)
DW,DH,TOP,SAFE=180.0,240.0,20.0,280.0; UP,DOWN,TF,DF=3.5,0.0,3000,1200; PPM=4
im0=Image.open(SRC).convert('L'); W=900; H=round(im0.size[1]*W/im0.size[0]); im=im0.resize((W,H),Image.Resampling.LANCZOS); w,h=im.size
gray=np.asarray(im,dtype=np.float32)/255.0; bg=gaussian_filter(gray,28); flat=np.clip(gray/np.maximum(bg,0.58),0,1); flat=np.clip((flat-0.04)/0.96,0,1)
tone_raw=1-flat; tone=np.clip((gaussian_filter(tone_raw,2.0)-0.016)/0.37,0,1); tone_dark=gaussian_filter(tone_raw,0.9)
yy,xx=np.mgrid[0:h,0:w]; xn=xx/(w-1); yn=yy/(h-1)
hair=((((xn-.535)/.155)**2+((yn-.640)/.170)**2)<1)|((((xn-.635)/.185)**2+((yn-.660)/.120)**2)<1)
jacket=((((xn-.455)/.170)**2+((yn-.845)/.185)**2)<1)|((((xn-.365)/.110)**2+((yn-.785)/.110)**2)<1)
arm=((((xn-.365)/.105)**2+((yn-.725)/.085)**2)<1); fig=hair|jacket|arm
sky=yn<.330; forest=(yn>.310)&(yn<.525)&(~fig); field=(yn>.440)&(yn<.790)&(~fig); grass=(yn>.635)&(~fig)
paths=[]
def add(kind,pts,min_len=7):
    if len(pts)<2:return
    clean=[pts[0]]; length=0; last=pts[0]
    for p in pts[1:]:
        d=math.hypot(p[0]-last[0],p[1]-last[1])
        if d>=.7: clean.append(p); length+=d; last=p
    if len(clean)>=2 and length>=min_len: paths.append((kind,clean))
def simp(kind,pts,eps=.9,min_len=7):
    if len(pts)<2:return
    a=np.array(pts,dtype=np.float32).reshape((-1,1,2)); ap=cv2.approxPolyDP(a,eps,False).reshape((-1,2)); add(kind,[(float(x),float(y)) for x,y in ap],min_len)
def clip(kind,pts,mask,min_len=7):
    run=[]
    for x,y in pts:
        ix,iy=round(x),round(y)
        if 0<=ix<w and 0<=iy<h and mask[iy,ix]: run.append((x,y))
        else:
            if run:simp(kind,run,.85,min_len)
            run=[]
    if run:simp(kind,run,.85,min_len)
def line(cx,cy,ang,l,off=0,wob=.5,n=6):
    e=(math.cos(ang),math.sin(ang)); p=(-math.sin(ang),math.cos(ang)); pts=[]
    for i in range(n):
        t=i/(n-1)-.5; ww=wob*math.sin(i/(n-1)*math.pi); pts.append((cx+e[0]*l*t+p[0]*(off+ww),cy+e[1]*l*t+p[1]*(off+ww)))
    return pts
def bundles(kind,mask,thr,tile,maxg,angles,lens,parmax,gap,jit,gamma,seed,cap=999):
    rng=random.Random(seed); made=0
    for y0 in range(0,h,tile):
      for x0 in range(0,w,tile):
        y1=min(h,y0+tile); x1=min(w,x0+tile); m=mask[y0:y1,x0:x1]
        if np.count_nonzero(m)<max(9,int(tile*tile*.10)):continue
        vals=tone[y0:y1,x0:x1][m]
        if vals.size==0:continue
        avg=float(vals.mean()); mx=float(vals.max()); val=.65*avg+.35*mx
        if val<thr:continue
        strength=max(0,min(1,(val-thr)/(1-thr)))**gamma; want=maxg*strength; ng=int(want)+(1 if rng.random()<want-int(want) else 0)
        if ng<=0 and mx>thr+.12:ng=1
        if ng<=0:continue
        ys,xs=np.where(m); weights=np.maximum(tone[y0:y1,x0:x1][ys,xs],.001); weights=weights/weights.sum()
        for _ in range(ng):
            if made>=cap:return
            idx=int(np.random.choice(np.arange(len(xs)),p=weights)); cx=x0+float(xs[idx])+rng.uniform(-.10,.10)*tile; cy=y0+float(ys[idx])+rng.uniform(-.10,.10)*tile
            if not(0<=int(cx)<w and 0<=int(cy)<h and mask[int(cy),int(cx)]):continue
            loc=float(tone[int(cy),int(cx)]); npar=1+min(parmax-1,int((.20*strength+.80*loc)*(parmax-1)+.25)); ang=math.radians(rng.choice(angles)+rng.uniform(-jit,jit)); ln=rng.uniform(*lens)*(.70+.70*loc)
            for k in range(npar): clip(kind,line(cx,cy,ang,ln,(k-(npar-1)/2)*gap*rng.uniform(.9,1.1),rng.uniform(-.55,.55)),mask,max(6.5,lens[0]*.42))
            made+=1
# filtered real contours
b=(tone_dark>.165); b=binary_closing(b,np.ones((2,2),bool)); b=remove_small_objects(b,min_size=38); sk=skeletonize(b).astype(np.uint8)*255
contours,_=cv2.findContours(sk,cv2.RETR_LIST,cv2.CHAIN_APPROX_NONE)
for c in contours:
    if len(c)<10:continue
    x,y,ww,hh=cv2.boundingRect(c); arc=cv2.arcLength(c,False)
    if arc<22 or ww<3 or hh<3:continue
    local=float(tone[y:min(h,y+hh),x:min(w,x+ww)].mean()); ymid=(y+.5*hh)/h
    if ymid<.33 and (arc<78 or local<.15):continue
    if local<.09 and arc<65:continue
    simp('dark_contour',[(float(p[0][0]),float(p[0][1])) for p in c],1.15,14)
# capped tonal groups
bundles('forest_light',forest,.045,30,2,[-62,58],(12,26),1,2.2,10,.82,11,280)
bundles('forest_dark',forest,.145,22,2,[-65,55,86],(10,23),2,2.1,12,.78,12,520)
bundles('forest_deep',forest,.285,20,2,[-68,52,88],(8,18),2,2.1,14,.78,13,320)
bundles('field_light',field,.050,40,1,[-14,-9],(24,62),1,2.5,7,.90,21,150)
bundles('field_mid',field,.145,34,1,[-15,16],(18,44),2,2.4,7,.92,22,95)
bundles('grass',grass,.070,25,2,[-82,76,-68],(10,29),2,2.0,12,.90,31,310)
bundles('jacket_light',jacket,.062,19,2,[-52,44],(15,34),2,2.3,8,.88,41,480)
bundles('jacket_dark',jacket,.215,18,2,[-55,43,-74],(12,30),2,2.7,9,.82,42,560)
bundles('hair_shadow',hair,.145,22,1,[-72],(18,38),2,2.2,5,.84,51,150)
# hybrid field/grass flow: sparse hand-like slope marks to replace part of random texture
rng_hybrid=random.Random(4419)
def hybrid_flow(kind, ybase, count, slope, length_rng, amp, mask):
    for i in range(count):
        x0=rng_hybrid.uniform(0.05*w,0.95*w)
        y0=(ybase+rng_hybrid.uniform(-0.014,0.014))*h + slope*(x0-w*0.5)
        a=math.atan(slope)+rng_hybrid.uniform(-0.040,0.040)
        ln=rng_hybrid.uniform(*length_rng)
        pts=[]
        for k in range(14):
            t=k/13-.5
            bend=math.sin((t+.5)*math.pi)*rng_hybrid.uniform(-amp,amp)
            pts.append((x0+math.cos(a)*ln*t-math.sin(a)*bend, y0+math.sin(a)*ln*t+math.cos(a)*bend))
        clip(kind,pts,mask,16)
hybrid_flow('field_flow_soft',0.535,16,-0.12,(58,128),2.4,field)
hybrid_flow('field_flow_soft',0.615,11,-0.10,(46,100),2.7,field)
hybrid_flow('grass_flow_soft',0.725,13,-0.08,(40,90),3.0,grass)
# a few curved foreground grass gestures, not too many
for i in range(78):
    cx=rng_hybrid.uniform(0.03*w,0.97*w); cy=rng_hybrid.uniform(0.710*h,0.965*h)
    ix=int(min(w-1,max(0,cx))); iy=int(min(h-1,max(0,cy)))
    if not grass[iy,ix]:
        continue
    a=math.radians(rng_hybrid.choice([-82,-70,72,82])+rng_hybrid.uniform(-7,7)); ln=rng_hybrid.uniform(13,31)
    pts=[]
    for k in range(6):
        t=k/5-.5; bend=math.sin((t+.5)*math.pi)*rng_hybrid.uniform(-2.1,2.1)
        pts.append((cx+math.cos(a)*ln*t-math.sin(a)*bend, cy+math.sin(a)*ln*t+math.cos(a)*bend))
    clip('grass_gesture',pts,grass,7)
# sky clusters
def skycl(cx,cy,rx,ry,ang,cnt,lf,cross=False):
    rng=random.Random(int(cx*13000+cy*17000+cnt*37)); a=math.radians(ang); e=(math.cos(a),math.sin(a)); p=(-math.sin(a),math.cos(a))
    for i in range(cnt):
        band=(i/max(1,cnt-1)-.5)*2; op=band*ry*h*.7+rng.uniform(-.008,.008)*h; oe=rng.uniform(-.5,.5)*rx*w; x=cx*w+e[0]*oe+p[0]*op; y=cy*h+e[1]*oe+p[1]*op
        if (((x/w-cx)/rx)**2+((y/h-cy)/ry)**2)>1.08:continue
        simp('sky_cross' if cross else 'sky',line(x,y,a,lf*w*rng.uniform(.55,1.02),0,rng.uniform(-1.2,1.2),8),.7,13)
for args in [(0.125,.095,.155,.052,-35,23,.057,False),(0.150,.235,.180,.050,-26,15,.051,False),(0.310,.125,.130,.048,-32,12,.045,False),(0.505,.285,.135,.047,-22,10,.042,False),(0.775,.175,.165,.055,-27,18,.051,False),(0.825,.285,.150,.050,-25,12,.046,False),(0.180,.270,.160,.040,30,5,.037,True),(0.790,.300,.145,.040,28,5,.036,True)]:skycl(*args)
# curves
def bez(p0,p1,p2,p3,n=54):
    return [((1-t)**3*p0[0]+3*(1-t)**2*t*p1[0]+3*(1-t)*t*t*p2[0]+t**3*p3[0],(1-t)**3*p0[1]+3*(1-t)**2*t*p1[1]+3*(1-t)*t*t*p2[1]+t**3*p3[1]) for t in [i/(n-1) for i in range(n)]]
rng=random.Random(811)
for i in range(94):
    t=i/93; crown=((.505+.075*(t-.5)+rng.uniform(-.010,.010))*w,(.515+.045*math.sin(t*math.pi)+rng.uniform(-.006,.008))*h)
    if i<39:
        end=((.410+.145*t+rng.uniform(-.012,.012))*w,(.735+.030*math.sin(t*4)+rng.uniform(-.012,.012))*h); c1=((.440+.06*t)*w,(.590+rng.uniform(-.015,.015))*h); c2=((.395+.11*t)*w,(.690+rng.uniform(-.018,.018))*h)
    else:
        tt=(i-39)/54; end=((.545+.220*tt+rng.uniform(-.013,.013))*w,(.700+.080*math.sin(tt*math.pi)+rng.uniform(-.016,.016))*h); c1=((.545+.075*tt)*w,(.580+rng.uniform(-.016,.016))*h); c2=((.610+.180*tt)*w,(.650+rng.uniform(-.018,.018))*h)
    clip('hair_flow',bez(crown,c1,c2,end,58),hair,16)
for i in range(32):
    t=i/31; x0=(.325+.235*t+rng.uniform(-.008,.008))*w; y0=(.690+.035*math.sin(t*math.pi)+rng.uniform(-.006,.006))*h; x3=(.350+.195*t+rng.uniform(-.010,.010))*w; y3=(.970+rng.uniform(-.008,.008))*h
    clip('jacket_fold',bez((x0,y0),((x0+x3)/2-.05*w,.780*h),((x0+x3)/2+.03*w,.900*h),(x3,y3),46),jacket,18)
# border
m=18; add('outer_border',[(m,m),(w-m,m),(w-m,h-m),(m,h-m),(m,m)],10)
def p2m(p):return(p[0]/w*DW,-(TOP+p[1]/h*DH))
mm=[]
for kind,pts in paths:
    arr=[p2m(p) for p in pts]; clean=[arr[0]]; length=0
    for p in arr[1:]:
        d=math.hypot(p[0]-clean[-1][0],p[1]-clean[-1][1])
        if d>=.12:clean.append(p); length+=d
    if len(clean)>=2 and length>=.6:mm.append((kind,clean))
rem=mm[:]; ordered=[]; pos=(0,0)
while rem:
    bi=0;br=False;bd=1e9
    for i,(_,pts) in enumerate(rem):
        d0=math.hypot(pts[0][0]-pos[0],pts[0][1]-pos[1]); d1=math.hypot(pts[-1][0]-pos[0],pts[-1][1]-pos[1])
        if d0<bd:bi=i;br=False;bd=d0
        if d1<bd:bi=i;br=True;bd=d1
    kind,pts=rem.pop(bi)
    if br:pts=list(reversed(pts))
    ordered.append((kind,pts)); pos=pts[-1]
name='gemini_hybrid_best_density_a4'; nc=OUT/f'{name}.nc'; gcode=OUT/f'{name}.gcode'
lines=['; hybrid best density A4','G21','G90',f'G0 Z{UP:.3f}',f'F{TF}']; draw=travel=0; last=(0,0)
for kind,pts in ordered:
    st=pts[0]; travel+=math.hypot(st[0]-last[0],st[1]-last[1]); lines += [f'G0 X{st[0]:.3f} Y{st[1]:.3f}',f'G1 Z{DOWN:.3f} F{DF}']; prev=st
    for x,y in pts[1:]:draw+=math.hypot(x-prev[0],y-prev[1]); lines.append(f'G1 X{x:.3f} Y{y:.3f}'); prev=(x,y)
    lines.append(f'G0 Z{UP:.3f}'); last=pts[-1]
lines.append('M2'); nc.write_text('\n'.join(lines)+'\n',encoding='ascii'); gcode.write_text('\n'.join(lines)+'\n',encoding='ascii')
def mm2px(p):return(round(p[0]*PPM),round(-p[1]*PPM))
def render(path,gray=False):
    out=Image.new('RGB',(round(DW*PPM),round(SAFE*PPM)),'white'); dr=ImageDraw.Draw(out); dr.rectangle([0,0,out.width-1,out.height-1],outline=(225,225,225))
    for kind,pts in ordered:
        col=(0,0,0) if not gray else ((32,32,32) if ('dark' in kind or kind in {'outer_border','hair_flow','jacket_fold','dark_contour'}) else (82,82,82) if ('forest' in kind or 'jacket' in kind or 'hair' in kind) else (132,132,132))
        dr.line([mm2px(p) for p in pts],fill=col,width=1)
    out.save(path)
black=OUT/f'{name}_preview_black_actual.png'; grayp=OUT/f'{name}_preview_pressure_gray.png'; render(black,False); render(grayp,True)
def pdf(png,pdfp):
    c=canvas.Canvas(str(pdfp),pagesize=A4); pw,ph=A4; mar=16; im=Image.open(png); sc=min((pw-2*mar)/im.width,(ph-2*mar)/im.height); c.drawImage(str(png),(pw-im.width*sc)/2,(ph-im.height*sc)/2,im.width*sc,im.height*sc); c.showPage(); c.save()
blackpdf=OUT/f'{name}_preview_black_actual.pdf'; graypdf=OUT/f'{name}_preview_pressure_gray.pdf'; pdf(black,blackpdf); pdf(grayp,graypdf)
counts=Counter(k for k,_ in ordered)
(OUT/'README_result.txt').write_text('LAYERED CAP A4 package\n'+f'source: {SRC}\n'+f'nc: {nc}\n'+f'gcode: {gcode}\n'+f'preview_black_actual_png: {black}\n'+f'preview_black_actual_pdf: {blackpdf}\n'+f'preview_pressure_gray_png: {grayp}\n'+f'preview_pressure_gray_pdf: {graypdf}\n'+f'paths_total: {len(ordered)}\n'+f'kind_counts: {dict(counts)}\n'+f'draw_length_m: {draw/1000:.2f}\n'+f'travel_length_m: {travel/1000:.2f}\n'+f'estimated_time_min_ideal: {(draw/(DF/60)+travel/(TF/60))/60:.1f}\n'+'algorithm_note: hybrid best density; keeps layered_cap dark mass while reducing random light-field/grass noise and adding sparse hand-like flow marks.\n',encoding='utf-8')
print('HYBRID BEST DENSITY A4 package'); print('paths_total:',len(ordered)); print('kind_counts:',dict(counts)); print('draw_length_m:',round(draw/1000,2)); print('travel_length_m:',round(travel/1000,2)); print('estimated_time_min_ideal:',round((draw/(DF/60)+travel/(TF/60))/60,1)); print('preview:',black); print('pdf:',blackpdf); print('nc:',nc)

