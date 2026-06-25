from __future__ import annotations
import re, math, shutil, hashlib
from pathlib import Path
from PIL import Image, ImageDraw
from collections import Counter
SRC_DIR=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_organic_pencil_max_a4_pack")
SRC_NC=SRC_DIR/'gemini_organic_pencil_max_a4.nc'
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_balanced_pencil_final_a4_pack")
OUT.mkdir(parents=True,exist_ok=True)
# Copy source/debug images for traceability.
for name in ['source_input_copy.jpg','source_cropped_gray.png','density_debug.png','skeleton_debug.png']:
    p=SRC_DIR/name
    if p.exists(): shutil.copy2(p,OUT/name)
text=SRC_NC.read_text(encoding='utf-8').splitlines()
header=[]; records=[]; cur=None
for line in text:
    if line.startswith('; ') and (' tone=' in line or line.startswith('; border')):
        if cur: records.append(cur)
        kind=line[2:].split()[0]
        tone=0.5; z=11.10
        mt=re.search(r'tone=([0-9.]+)',line); mz=re.search(r'z=([0-9.]+)',line)
        if mt: tone=float(mt.group(1))
        if mz: z=float(mz.group(1))
        cur={'comment':line,'kind':kind,'tone':tone,'z':z,'lines':[line]}
    elif cur:
        cur['lines'].append(line)
    else:
        header.append(line)
if cur: records.append(cur)
# Trim end commands from the last record if they got attached; OK to keep, but final footer will be regenerated.
keep_prob={
    'border':1.0,'real_trace':1.0,'sky_sparse':1.0,
    'forest_mid':0.56,'forest_dark':0.44,
    'field_long':0.82,'field_dark':0.66,
    'grass_light':0.56,'grass_dark':0.42,
    'figure_mid':0.52,'figure_deep':0.40,'hair_flow':0.58,
}
kept=[]
seen=Counter(); kept_counts=Counter()
for idx,r in enumerate(records):
    k=r['kind']; seen[k]+=1
    prob=keep_prob.get(k,0.5)
    if k in ('border','real_trace','sky_sparse'):
        take=True
    else:
        h=hashlib.sha1(f'{k}:{idx}'.encode()).digest()
        val=int.from_bytes(h[:4],'big')/0xffffffff
        # Keep stronger tone strokes slightly more often; this preserves dark close-line requirement.
        effective=min(1.0, prob + max(0.0,r['tone']-0.55)*0.28)
        take=val<=effective
    if take:
        kept.append(r); kept_counts[k]+=1
# Rebuild NC/GCODE.
out_lines=['; gemini_balanced_pencil_final_a4','; filtered from organic max: dark zones still dense, noisy excess removed','G21','G90','G0 Z13.00','G0 X0.000 Y0.000']
for r in kept:
    # remove accidental M2/home lines inside source records, keep stroke commands only
    for ln in r['lines']:
        if ln.startswith('G0 X0.000 Y0.000') or ln == 'M2':
            continue
        out_lines.append(ln)
out_lines += ['G0 X0.000 Y0.000','G0 Z13.00','M2']
(OUT/'gemini_balanced_pencil_final_a4.nc').write_text('\n'.join(out_lines)+'\n',encoding='utf-8')
(OUT/'gemini_balanced_pencil_final_a4.gcode').write_text('\n'.join(out_lines)+'\n',encoding='utf-8')
# Parse strokes for preview/stats.
xy_re=re.compile(r'[GX][01] .*?X(-?[0-9.]+) Y(-?[0-9.]+)')
strokes=[]
for r in kept:
    pts=[]
    for ln in r['lines']:
        m=xy_re.search(ln)
        if m: pts.append((float(m.group(1)),float(m.group(2))))
    if len(pts)>=2:
        strokes.append((r,pts))
def shade_from_z(z,tone):
    if z<10.75: return 215
    if z<11.0: return 178
    if z<11.25: return 130
    if z<11.55: return 80
    return 30
WORK_W,WORK_H=180.0,280.0
def render(path:Path, pressure=True, black=False, dark=False):
    dpi=230; cw=int(WORK_W/25.4*dpi); ch=int(WORK_H/25.4*dpi)
    im=Image.new('RGB',(cw,ch),(255,255,255) if not dark else (24,24,24)); d=ImageDraw.Draw(im)
    def mm(x,y): return int(round(x/25.4*dpi)), int(round((-y)/25.4*dpi))
    d.rectangle([mm(0,0),mm(WORK_W,-WORK_H)],outline=(238,238,238) if not dark else (66,66,66),width=1)
    for r,pts_mm in strokes:
        pts=[mm(x,y) for x,y in pts_mm]
        if black: col=(0,0,0) if not dark else (235,235,235)
        elif pressure:
            s=shade_from_z(r['z'],r['tone']); col=(s,s,s) if not dark else (max(28,255-s),)*3
        else: col=(55,55,55) if not dark else (225,225,225)
        d.line(pts,fill=col,width=1)
    im.save(path); im.save(path.with_suffix('.pdf'),'PDF',resolution=dpi)
render(OUT/'gemini_balanced_pencil_final_preview_pressure_gray.png',True)
render(OUT/'gemini_balanced_pencil_final_preview_black_actual.png',False,True)
render(OUT/'gemini_balanced_pencil_final_preview_dark_pressure.png',True,False,True)
# stats
draw=0.0; travel=0.0; last=(0.0,0.0)
for r,pts in strokes:
    travel += math.hypot(pts[0][0]-last[0],pts[0][1]-last[1])
    for a,b in zip(pts,pts[1:]): draw += math.hypot(b[0]-a[0],b[1]-a[1])
    last=pts[-1]
readme=f"""BALANCED PENCIL FINAL A4 package
source_pack: {SRC_DIR}
output_dir: {OUT}
paths_before: {len(records)}
paths_after: {len(kept)}
counts_before: {dict(seen)}
counts_after: {dict(kept_counts)}
draw_length_m: {draw/1000:.2f}
travel_length_m: {travel/1000:.2f}
estimated_time_min_ideal: {(draw/1000)/0.55:.1f}
realistic_time_note: likely 2-4 hours. Best visual match still requires calibrated Z pressure with pencil/soft pen.
algorithm_note: organic tonal stroke pack was thinned deterministically. Real source strokes kept; noisy dense layers reduced while preserving dark-area close strokes.
files:
- gemini_balanced_pencil_final_preview_pressure_gray.png/pdf
- gemini_balanced_pencil_final_preview_black_actual.png/pdf
- gemini_balanced_pencil_final_preview_dark_pressure.png/pdf
- gemini_balanced_pencil_final_a4.nc
- gemini_balanced_pencil_final_a4.gcode
"""
(OUT/'README_result.txt').write_text(readme,encoding='utf-8')
print(readme)
