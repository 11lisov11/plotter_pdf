from __future__ import annotations

import math
import random
import shutil
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_adaptive_orientation_streamlines_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
WORK_W_MM = 180.0
WORK_H_MM = 280.0
DRAW_W_MM = 176.0
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0
TRAVEL_F = 3000
DRAW_F = 1200
RNG = random.Random(22062026)


def preprocess(gray: np.ndarray):
    den = cv2.fastNlMeansDenoising(gray, None, h=4, templateWindowSize=7, searchWindowSize=21)
    bg = cv2.GaussianBlur(den, (0,0), 31)
    norm = cv2.divide(den, bg, scale=238)
    norm = cv2.GaussianBlur(norm, (5,5), 0)
    local = np.clip(238 - norm.astype(np.int16), 0, 255).astype(np.float32)
    global_dark = np.clip(245 - den.astype(np.int16), 0, 255).astype(np.float32)
    dens = np.maximum(local * 1.45, global_dark * 0.38)
    dens = cv2.GaussianBlur(dens, (0,0), 1.5)
    lo, hi = np.percentile(dens, [50, 99.5])
    dens = np.clip((dens - lo) / max(1.0, hi - lo), 0, 1)
    dens = np.power(dens, 0.78).astype(np.float32)

    gx = cv2.Sobel(norm, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(norm, cv2.CV_32F, 0, 1, ksize=3)
    jxx = cv2.GaussianBlur(gx*gx, (0,0), 3.0)
    jyy = cv2.GaussianBlur(gy*gy, (0,0), 3.0)
    jxy = cv2.GaussianBlur(gx*gy, (0,0), 3.0)
    grad_angle = 0.5 * np.arctan2(2*jxy, jxx - jyy + 1e-6)
    tangent = grad_angle + math.pi/2
    coherence = np.sqrt((jxx-jyy)**2 + 4*jxy*jxy) / (jxx + jyy + 1e-3)
    return den, norm, dens, tangent.astype(np.float32), coherence.astype(np.float32)


def ellipse_mask(shape, cx, cy, rx, ry, angle=0.0):
    h,w = shape
    yy, xx = np.mgrid[0:h,0:w]
    ca, sa = math.cos(angle), math.sin(angle)
    x = (xx-cx)*ca + (yy-cy)*sa
    y = -(xx-cx)*sa + (yy-cy)*ca
    return (x/rx)**2 + (y/ry)**2 <= 1.0


def build_regions(shape):
    h,w = shape
    yy,xx=np.mgrid[0:h,0:w]
    person = (ellipse_mask(shape,w*0.50,h*0.80,w*0.20,h*0.26,-0.08)
              | ellipse_mask(shape,w*0.58,h*0.69,w*0.17,h*0.15,0.12)
              | ellipse_mask(shape,w*0.41,h*0.78,w*0.11,h*0.11,-0.35))
    hair = ellipse_mask(shape,w*0.57,h*0.70,w*0.17,h*0.18,0.12)
    jacket = ellipse_mask(shape,w*0.45,h*0.86,w*0.18,h*0.18,-0.20)
    sky = yy < h*0.43
    forest = (yy >= h*0.36) & (yy < h*0.59) & (~person)
    field = (yy >= h*0.48) & (~person)
    grass = (yy >= h*0.62) & (~person)
    return dict(person=person,hair=hair,jacket=jacket,sky=sky,forest=forest,field=field,grass=grass)


def fallback_angle(x, y, reg):
    iy = int(y); ix = int(x)
    if reg['hair'][iy, ix]:
        return math.radians(82)
    if reg['jacket'][iy, ix]:
        return math.radians(-52)
    if reg['forest'][iy, ix]:
        return math.radians(-67)
    if reg['grass'][iy, ix]:
        return math.radians(-68)
    if reg['field'][iy, ix]:
        return math.radians(14)
    if reg['sky'][iy, ix]:
        return math.radians(25)
    return math.radians(12)


def angle_at(x, y, tangent, coh, reg):
    h,w = tangent.shape
    ix = int(np.clip(round(x),0,w-1)); iy = int(np.clip(round(y),0,h-1))
    a = float(tangent[iy, ix])
    if float(coh[iy, ix]) < 0.16:
        a = fallback_angle(ix, iy, reg)
    else:
        fb = fallback_angle(ix, iy, reg)
        # Blend local orientation with region direction so noisy microtexture doesn't spin.
        z = 0.72*complex(math.cos(a), math.sin(a)) + 0.28*complex(math.cos(fb), math.sin(fb))
        a = math.atan2(z.imag, z.real)
    return a


def trace_one(seed, dens, tangent, coh, reg, thr, max_len, step=2.3):
    h,w = dens.shape
    def walk(direction):
        x,y = seed
        pts=[]
        travelled=0.0
        prev_a = None
        for _ in range(int(max_len/step)+2):
            ix=int(np.clip(round(x),0,w-1)); iy=int(np.clip(round(y),0,h-1))
            if not (0 <= x < w and 0 <= y < h): break
            if dens[iy,ix] < thr*0.72: break
            a = angle_at(x,y,tangent,coh,reg)
            if prev_a is not None:
                # Keep orientation continuous; flip tangent if needed.
                da = math.atan2(math.sin(a-prev_a), math.cos(a-prev_a))
                if abs(da) > math.pi/2:
                    a += math.pi
                z = 0.75*complex(math.cos(a), math.sin(a)) + 0.25*complex(math.cos(prev_a), math.sin(prev_a))
                a = math.atan2(z.imag,z.real)
            prev_a = a
            wig = math.sin(travelled*0.18 + (seed[0]+seed[1])*0.01) * 0.18
            x += math.cos(a)*step*direction + math.cos(a+math.pi/2)*wig
            y += math.sin(a)*step*direction + math.sin(a+math.pi/2)*wig
            travelled += step
            pts.append((x,y))
        return pts
    back = walk(-1)
    fwd = walk(1)
    pts = list(reversed(back)) + [seed] + fwd
    # Remove tight duplicate wiggle points.
    clean=[]
    for p in pts:
        if not clean or math.hypot(p[0]-clean[-1][0], p[1]-clean[-1][1]) >= 1.2:
            clean.append(p)
    return clean


def mark_visited(vis, pts, radius):
    h,w = vis.shape
    r=max(1,int(radius))
    for x,y in pts[::2]:
        ix=int(round(x)); iy=int(round(y))
        if 0<=ix<w and 0<=iy<h:
            cv2.circle(vis,(ix,iy),r,1,-1)


def visited_at(vis,x,y):
    h,w=vis.shape
    ix=int(np.clip(round(x),0,w-1)); iy=int(np.clip(round(y),0,h-1))
    return bool(vis[iy,ix])


def generate_streamlines(dens,tangent,coh,reg):
    h,w=dens.shape
    paths=[]
    configs=[
        dict(name='light_stream',thr=0.14,grid=34,max_len=135,min_len=32,visit=8),
        dict(name='mid_stream',thr=0.26,grid=25,max_len=115,min_len=26,visit=7),
        dict(name='dark_stream',thr=0.42,grid=18,max_len=88,min_len=18,visit=5),
        dict(name='deep_stream',thr=0.60,grid=13,max_len=66,min_len=14,visit=4),
    ]
    for cfg in configs:
        vis=np.zeros((h,w),np.uint8)
        offset_x=RNG.uniform(0,cfg['grid']); offset_y=RNG.uniform(0,cfg['grid'])
        ys=np.arange(offset_y,h,cfg['grid'])
        xs=np.arange(offset_x,w,cfg['grid'])
        for y in ys:
            for x in xs:
                jx=x+RNG.uniform(-cfg['grid']*0.30,cfg['grid']*0.30)
                jy=y+RNG.uniform(-cfg['grid']*0.30,cfg['grid']*0.30)
                if not (0<=jx<w and 0<=jy<h): continue
                ix=int(np.clip(round(jx),0,w-1)); iy=int(np.clip(round(jy),0,h-1))
                if dens[iy,ix] < cfg['thr']: continue
                # Keep sky extra sparse.
                if reg['sky'][iy,ix] and cfg['name'] not in ('light_stream','mid_stream'):
                    continue
                if visited_at(vis,jx,jy): continue
                pts=trace_one((jx,jy),dens,tangent,coh,reg,cfg['thr'],cfg['max_len'])
                length=sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(pts,pts[1:]))
                if length < cfg['min_len']:
                    continue
                vals=[]
                for px,py in pts[::max(1,len(pts)//12)]:
                    ii=int(np.clip(round(px),0,w-1)); jj=int(np.clip(round(py),0,h-1))
                    vals.append(float(dens[jj,ii]))
                paths.append({'pts_px':pts,'strength':float(np.mean(vals)) if vals else cfg['thr'],'kind':cfg['name']})
                mark_visited(vis,pts,cfg['visit'])
    return paths


def add_hair_flow(paths,dens,reg):
    h,w=dens.shape
    for sx in np.linspace(0.47*w,0.69*w,34):
        pts=[]; y0=h*(0.59+0.04*RNG.random()); length=RNG.uniform(155,235); curve=RNG.uniform(-0.28,0.22); phase=RNG.random()*math.tau
        for t in np.linspace(0,1,68):
            y=y0+length*t; x=sx+(t*t*curve*w*0.18)+math.sin(t*math.tau*1.2+phase)*5.0*(1-t*0.3)
            ix=int(np.clip(round(x),0,w-1)); iy=int(np.clip(round(y),0,h-1))
            if reg['hair'][iy,ix] and dens[iy,ix]>0.08:
                pts.append((x,y))
            elif len(pts)>8:
                paths.append({'pts_px':pts,'strength':0.36,'kind':'hair_flow'}); pts=[]
            else:
                pts=[]
        if len(pts)>8: paths.append({'pts_px':pts,'strength':0.36,'kind':'hair_flow'})


def add_long_contours(paths,gray,dens):
    den=cv2.fastNlMeansDenoising(gray,None,h=5,templateWindowSize=7,searchWindowSize=21)
    edges=cv2.Canny(den,90,175,L2gradient=True)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_NONE)
    h,w=dens.shape
    for cnt in contours:
        pts=cnt.reshape(-1,2)
        if len(pts)<45: continue
        approx=cv2.approxPolyDP(pts,1.25,False).reshape(-1,2)
        if len(approx)<4: continue
        length=sum(math.hypot(float(b[0]-a[0]),float(b[1]-a[1])) for a,b in zip(approx,approx[1:]))
        if length<140 or length>760: continue
        vals=[float(dens[int(y),int(x)]) for x,y in approx[::max(1,len(approx)//20)] if 0<=x<w and 0<=y<h]
        md=float(np.mean(vals)) if vals else 0.0
        if md<0.17 and length<210: continue
        paths.append({'pts_px':[(float(x),float(y)) for x,y in approx],'strength':md,'kind':'long_contour'})


def convert(paths,w,h):
    draw_w=DRAW_W_MM; draw_h=draw_w*h/w
    if draw_h>WORK_H_MM-4:
        draw_h=WORK_H_MM-4; draw_w=draw_h*w/h
    x0=(WORK_W_MM-draw_w)/2; y0=(WORK_H_MM-draw_h)/2; sc=draw_w/w
    out=[]
    for p in paths:
        pts=[(x0+x*sc,-(y0+y*sc)) for x,y in p['pts_px']]
        if len(pts)<2: continue
        length=sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(pts,pts[1:]))
        if length<1.4: continue
        out.append({**p,'pts_mm':pts,'length_mm':length})
    rows=defaultdict(list)
    for p in out:
        cy=sum(y for _,y in p['pts_mm'])/len(p['pts_mm'])
        rows[int((-cy)//7.0)].append(p)
    ordered=[]
    for row in sorted(rows):
        rev=row%2==1; group=[]
        for p in rows[row]:
            pts=p['pts_mm']
            if (pts[0][0]>pts[-1][0]) ^ rev:
                p={**p,'pts_mm':list(reversed(pts))}
            group.append(p)
        group.sort(key=lambda p:p['pts_mm'][0][0],reverse=rev)
        ordered.extend(group)
    return ordered,draw_w,draw_h


def write_gcode(paths,nc):
    lines=['; adaptive orientation streamlines A4','G21','G90',f'G0 Z{PEN_UP_Z:.3f}',f'F{TRAVEL_F}']
    draw=travel=0.0; cur=None
    for p in paths:
        pts=p['pts_mm']
        if cur is not None: travel+=math.hypot(pts[0][0]-cur[0],pts[0][1]-cur[1])
        lines.append(f'G0 X{pts[0][0]:.3f} Y{pts[0][1]:.3f}')
        lines.append(f'G1 Z{PEN_DOWN_Z:.3f} F{DRAW_F}')
        prev=pts[0]
        for x,y in pts[1:]:
            lines.append(f'G1 X{x:.3f} Y{y:.3f}')
            draw+=math.hypot(x-prev[0],y-prev[1]); prev=(x,y)
        lines.append(f'G0 Z{PEN_UP_Z:.3f}')
        cur=pts[-1]
    lines.append('M2')
    nc.write_text('\n'.join(lines)+'\n',encoding='ascii')
    return draw,travel,len(lines)


def render(paths,png,pressure=True):
    scale=5; pad=60
    im=Image.new('RGB',(int(WORK_W_MM*scale+2*pad),int(WORK_H_MM*scale+2*pad)),'white')
    dr=ImageDraw.Draw(im)
    dr.rectangle([pad,pad,pad+WORK_W_MM*scale,pad+WORK_H_MM*scale],outline=(195,195,195),width=1)
    for p in paths:
        pts=[(pad+x*scale,pad+(-y)*scale) for x,y in p['pts_mm']]
        if pressure:
            s=float(p.get('strength',0.2)); gray=int(np.clip(222-155*s,44,206)); color=(gray,gray,gray)
        else:
            color=(0,0,0)
        dr.line(pts,fill=color,width=1,joint='curve')
    im.save(png)


def png_to_pdf(png,pdf):
    c=canvas.Canvas(str(pdf),pagesize=A4); pw,ph=A4
    img=Image.open(png); iw,ih=img.size; m=18
    sc=min((pw-2*m)/iw,(ph-2*m)/ih); dw=iw*sc; dh=ih*sc
    c.drawImage(str(png),(pw-dw)/2,(ph-dh)/2,dw,dh); c.showPage(); c.save()


def main():
    shutil.copy2(SRC,OUT/'source_input_copy.jpg')
    gray=cv2.imread(str(SRC),cv2.IMREAD_GRAYSCALE)
    den,norm,dens,tangent,coh=preprocess(gray)
    reg=build_regions(dens.shape)
    cv2.imwrite(str(OUT/'debug_density.png'),np.clip(dens*255,0,255).astype(np.uint8))
    cv2.imwrite(str(OUT/'debug_coherence.png'),np.clip(coh*255,0,255).astype(np.uint8))
    paths=generate_streamlines(dens,tangent,coh,reg)
    add_hair_flow(paths,dens,reg)
    add_long_contours(paths,gray,dens)
    ordered,draw_w,draw_h=convert(paths,gray.shape[1],gray.shape[0])
    nc=OUT/'gemini_adaptive_orientation_streamlines_a4.nc'; gcode=OUT/'gemini_adaptive_orientation_streamlines_a4.gcode'
    draw,travel,line_count=write_gcode(ordered,nc); shutil.copy2(nc,gcode)
    ppng=OUT/'gemini_adaptive_orientation_streamlines_preview_pressure_gray.png'; bpng=OUT/'gemini_adaptive_orientation_streamlines_preview_black_actual.png'
    render(ordered,ppng,True); render(ordered,bpng,False)
    png_to_pdf(ppng,OUT/'gemini_adaptive_orientation_streamlines_preview_pressure_gray.pdf')
    png_to_pdf(bpng,OUT/'gemini_adaptive_orientation_streamlines_preview_black_actual.pdf')
    counts=defaultdict(int)
    for p in ordered: counts[p['kind']]+=1
    text=(
        'ADAPTIVE ORIENTATION STREAMLINES A4 package\n'
        f'source: {SRC}\noutput_dir: {OUT}\nimage_px: {gray.shape[1]} x {gray.shape[0]}\n'
        f'drawing_size_mm: {draw_w:.2f} x {draw_h:.2f}\npaths_total: {len(ordered)}\nkind_counts: {dict(counts)}\n'
        f'draw_length_m: {draw/1000:.2f}\ntravel_length_m: {travel/1000:.2f}\ngcode_lines: {line_count}\n'
        f'estimated_time_min_ideal: {(draw/DRAW_F+travel/TRAVEL_F):.1f}\n'
        'algorithm_note: local structure-tensor orientation streamlines. Darker source tone spawns denser streamline layers; light zones remain sparse. Region fallback angles prevent random curl where local orientation is weak.\n'
        'files:\n- gemini_adaptive_orientation_streamlines_preview_pressure_gray.png/pdf\n- gemini_adaptive_orientation_streamlines_preview_black_actual.png/pdf\n- gemini_adaptive_orientation_streamlines_a4.nc\n- gemini_adaptive_orientation_streamlines_a4.gcode\n'
    )
    (OUT/'README_result.txt').write_text(text,encoding='utf-8')
    print(text)

if __name__=='__main__':
    main()

