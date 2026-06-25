from pathlib import Path
src = Path(r'C:\plotter_pdf\_plotter_jobs\build_density_fullfield_plus_skyfield.py')
dst = Path(r'C:\plotter_pdf\_plotter_jobs\build_density_plus_figurefolds.py')
text = src.read_text(encoding='utf-8')
repls = {
'gemini_density_fullfield_plus_skyfield_a4_pack':'gemini_density_plus_figurefolds_a4_pack',
'DENSITY FULLFIELD PLUS SKY/FIELD A4 package':'DENSITY PLUS FIGURE FOLDS A4 package',
'density fullfield plus sky field A4':'density plus figure folds A4',
'gemini_density_fullfield_plus_skyfield_a4.nc':'gemini_density_plus_figurefolds_a4.nc',
'gemini_density_fullfield_plus_skyfield_a4.gcode':'gemini_density_plus_figurefolds_a4.gcode',
'gemini_density_fullfield_plus_skyfield_preview_pressure_gray.png':'gemini_density_plus_figurefolds_preview_pressure_gray.png',
'gemini_density_fullfield_plus_skyfield_preview_black_actual.png':'gemini_density_plus_figurefolds_preview_black_actual.png',
'gemini_density_fullfield_plus_skyfield_preview_pressure_gray.pdf':'gemini_density_plus_figurefolds_preview_pressure_gray.pdf',
'gemini_density_fullfield_plus_skyfield_preview_black_actual.pdf':'gemini_density_plus_figurefolds_preview_black_actual.pdf',
"add_layer(paths,dens,reg['jacket'],angle=-54,spacing=5.8,threshold=0.12,min_len=18,max_len=96,label='jacket_l1',jitter=0.24,bridge_px=5)": "add_layer(paths,dens,reg['jacket'],angle=-54,spacing=7.4,threshold=0.17,min_len=18,max_len=96,label='jacket_l1',jitter=0.20,bridge_px=4)",
"add_layer(paths,dens,reg['jacket'],angle=52,spacing=5.8,threshold=0.20,min_len=18,max_len=96,label='jacket_l2',jitter=0.24,bridge_px=4)": "add_layer(paths,dens,reg['jacket'],angle=52,spacing=7.2,threshold=0.25,min_len=18,max_len=96,label='jacket_l2',jitter=0.20,bridge_px=3)",
"add_layer(paths,dens,reg['jacket'],angle=12,spacing=6.5,threshold=0.40,min_len=16,max_len=82,label='jacket_l3',jitter=0.18,bridge_px=3)": "add_layer(paths,dens,reg['jacket'],angle=12,spacing=8.0,threshold=0.47,min_len=16,max_len=82,label='jacket_l3',jitter=0.16,bridge_px=2)",
'tonal staircase with extra sparse sky/cloud and field texture, without dark-area bundling.':'plus_skyfield with lighter jacket mesh and added long figure fold strokes; keeps light areas sparse and avoids dark-area bundling.'
}
for a,b in repls.items():
    text = text.replace(a,b)
fold_func = r'''

def add_figure_folds(paths, dens, reg):
    h, w = dens.shape
    mask = (reg['jacket'] | reg['body']) & (dens > 0.12)

    def add_polyline(points, label, min_len=10.0):
        seg = []
        chunks = []
        for x, y in points:
            ix = int(np.clip(round(x), 0, w-1)); iy = int(np.clip(round(y), 0, h-1))
            if mask[iy, ix]:
                seg.append((float(x), float(y)))
            else:
                if len(seg) >= 4:
                    chunks.append(seg)
                seg = []
        if len(seg) >= 4:
            chunks.append(seg)
        for pts in chunks:
            length = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(pts, pts[1:]))
            if length < min_len:
                continue
            vals=[]
            for x,y in pts[::max(1,len(pts)//12)]:
                ix=int(np.clip(round(x),0,w-1)); iy=int(np.clip(round(y),0,h-1))
                vals.append(float(dens[iy,ix]))
            paths.append({'pts_px': pts, 'strength': float(np.mean(vals)) if vals else 0.3, 'kind': label})

    for i, x0 in enumerate(np.linspace(0.36*w, 0.58*w, 20)):
        phase = RNG.random() * math.tau
        y0 = 0.70*h + RNG.uniform(-8, 12)
        length = RNG.uniform(145, 230)
        pts=[]
        for t in np.linspace(0, 1, 70):
            x = x0 + (t - 0.5) * RNG.uniform(18, 36) + math.sin(t*math.pi*1.5 + phase) * 6
            y = y0 + length*t
            x += (t*t) * ((-1)**i) * RNG.uniform(12, 28)
            pts.append((x,y))
        add_polyline(pts, 'jacket_fold_long', min_len=18)

    for j, y0 in enumerate(np.linspace(0.74*h, 0.89*h, 18)):
        pts=[]
        cx = 0.39*w + RNG.uniform(-8, 8)
        amp = RNG.uniform(22, 42)
        for t in np.linspace(-0.95, 0.95, 60):
            x = cx + amp * math.sin(t*1.2) + RNG.uniform(-0.8,0.8)
            y = y0 + 22 * t + 10 * math.sin(t*2.0 + j*0.3)
            pts.append((x,y))
        add_polyline(pts, 'sleeve_fold_arc', min_len=12)

    for y0 in np.linspace(0.91*h, 0.98*h, 8):
        pts=[]
        for t in np.linspace(0,1,80):
            x = 0.39*w + 0.22*w*t + math.sin(t*math.tau*1.2 + y0*0.01)*5
            y = y0 + math.sin(t*math.tau + y0*0.02)*8
            pts.append((x,y))
        add_polyline(pts, 'jacket_hem_shadow', min_len=18)
'''
text = text.replace('def convert(paths,w,h):', fold_func + '\n\ndef convert(paths,w,h):')
old = "    add_hair_flow(paths,dens,reg)\n    add_layer(paths,dens,reg['hair'],angle=64,spacing=8,threshold=0.22,min_len=16,max_len=90,label='hair_shadow',jitter=0.20,bridge_px=4)\n    add_long_contours(paths, gray, dens)"
new = "    add_hair_flow(paths,dens,reg)\n    add_layer(paths,dens,reg['hair'],angle=64,spacing=8,threshold=0.22,min_len=16,max_len=90,label='hair_shadow',jitter=0.20,bridge_px=4)\n    add_figure_folds(paths, dens, reg)\n    add_long_contours(paths, gray, dens)"
text = text.replace(old, new)
dst.write_text(text, encoding='utf-8')
print(dst)
