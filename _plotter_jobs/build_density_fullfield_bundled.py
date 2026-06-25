from __future__ import annotations

import math
import shutil
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SRC = Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")
BASE = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_density_tone_levels_fullfield_a4_pack\gemini_density_tone_levels_fullfield_a4.nc")
OUT = Path(r"C:\plotter_pdf\_plotter_jobs\gemini_density_fullfield_bundled_a4_pack")
OUT.mkdir(parents=True, exist_ok=True)
WORK_W_MM = 180.0
WORK_H_MM = 280.0
DRAW_W_MM = 176.0
DRAW_F = 1200
TRAVEL_F = 3000
PEN_UP_Z = 3.5
PEN_DOWN_Z = 0.0


def preprocess_density(gray: np.ndarray) -> np.ndarray:
    den = cv2.fastNlMeansDenoising(gray, None, h=4, templateWindowSize=7, searchWindowSize=21)
    bg = cv2.GaussianBlur(den, (0, 0), 31)
    norm = cv2.divide(den, bg, scale=238)
    norm = cv2.GaussianBlur(norm, (5, 5), 0)
    local = np.clip(238 - norm.astype(np.int16), 0, 255).astype(np.float32)
    global_dark = np.clip(245 - den.astype(np.int16), 0, 255).astype(np.float32)
    dens = np.maximum(local * 1.45, global_dark * 0.38)
    dens = cv2.GaussianBlur(dens, (0, 0), 1.5)
    lo, hi = np.percentile(dens, [50, 99.5])
    dens = np.clip((dens - lo) / max(1.0, hi - lo), 0, 1)
    return np.power(dens, 0.78).astype(np.float32)


def parse_nc(path: Path):
    paths = []
    cur = []
    pen = False
    last_xy = None
    for raw in path.read_text(encoding='ascii', errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith(';'):
            continue
        parts = line.split()
        cmd = parts[0]
        vals = {}
        for p in parts[1:]:
            if len(p) >= 2 and p[0] in 'XYZF':
                try:
                    vals[p[0]] = float(p[1:])
                except ValueError:
                    pass
        if 'Z' in vals:
            if vals['Z'] <= 0.1:
                pen = True
                if last_xy is not None:
                    cur = [last_xy]
            else:
                if pen and len(cur) >= 2:
                    paths.append(cur)
                cur = []
                pen = False
        if 'X' in vals or 'Y' in vals:
            x = vals.get('X', last_xy[0] if last_xy else 0.0)
            y = vals.get('Y', last_xy[1] if last_xy else 0.0)
            last_xy = (x, y)
            if pen:
                cur.append(last_xy)
    if pen and len(cur) >= 2:
        paths.append(cur)
    return paths


def mm_mapping(img_w: int, img_h: int):
    draw_w = DRAW_W_MM
    draw_h = draw_w * img_h / img_w
    if draw_h > WORK_H_MM - 4:
        draw_h = WORK_H_MM - 4
        draw_w = draw_h * img_w / img_h
    x0 = (WORK_W_MM - draw_w) / 2
    y0 = (WORK_H_MM - draw_h) / 2
    sc = draw_w / img_w
    def mm_to_px(xmm: float, ymm: float):
        x = (xmm - x0) / sc
        y = ((-ymm) - y0) / sc
        return x, y
    return mm_to_px, draw_w, draw_h


def path_len(path):
    return sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(path, path[1:]))


def path_density(path, dens, mm_to_px):
    h, w = dens.shape
    vals = []
    for a, b in zip(path, path[1:]):
        seg = math.hypot(b[0]-a[0], b[1]-a[1])
        n = max(2, int(seg / 1.5))
        for i in range(n):
            t = i / max(1, n-1)
            x = a[0] + (b[0]-a[0]) * t
            y = a[1] + (b[1]-a[1]) * t
            px, py = mm_to_px(x, y)
            ix = int(np.clip(round(px), 0, w-1))
            iy = int(np.clip(round(py), 0, h-1))
            vals.append(float(dens[iy, ix]))
    return float(np.mean(vals)) if vals else 0.0, float(np.max(vals)) if vals else 0.0


def offset_path(path, offset):
    if len(path) < 2:
        return path
    out = []
    n = len(path)
    for i, p in enumerate(path):
        if i == 0:
            dx = path[1][0] - p[0]; dy = path[1][1] - p[1]
        elif i == n-1:
            dx = p[0] - path[i-1][0]; dy = p[1] - path[i-1][1]
        else:
            dx = path[i+1][0] - path[i-1][0]; dy = path[i+1][1] - path[i-1][1]
        ln = math.hypot(dx, dy)
        if ln < 1e-6:
            out.append(p); continue
        nx, ny = -dy/ln, dx/ln
        out.append((p[0] + nx * offset, p[1] + ny * offset))
    return out


def in_bounds(path):
    for x, y in path:
        if x < -1.0 or x > WORK_W_MM + 1.0 or y > 1.0 or y < -WORK_H_MM - 1.0:
            return False
    return True


def build(paths, dens, mm_to_px):
    enhanced = []
    counts = defaultdict(int)
    for path in paths:
        length = path_len(path)
        mean_d, max_d = path_density(path, dens, mm_to_px)
        enhanced.append({'pts': path, 'strength': mean_d, 'kind': 'base'})
        counts['base'] += 1
        # No bundling for tiny specks. Only meaningful strokes get neighbours.
        if length < 4.0:
            continue
        # More neighbours only where both the path and source tone are dark.
        offsets = []
        if mean_d >= 0.62 or max_d >= 0.86:
            offsets = [-0.38, 0.38]
        if mean_d >= 0.74 and length >= 8.0:
            offsets = [-0.62, 0.62]
        if mean_d >= 0.84 and length >= 10.0:
            offsets = [-0.86, 0.86]
        # Keep very long field/sky lines from becoming bands: require stronger mean.
        if length > 70 and mean_d < 0.78:
            offsets = []
        for off in offsets:
            op = offset_path(path, off)
            if in_bounds(op):
                enhanced.append({'pts': op, 'strength': min(1.0, mean_d + 0.08), 'kind': f'bundle_{off:+.2f}'})
                counts[f'bundle_{off:+.2f}'] += 1
    return enhanced, counts


def order_paths(items):
    rows = defaultdict(list)
    for item in items:
        cy = sum(y for _, y in item['pts']) / len(item['pts'])
        rows[int((-cy)//7.0)].append(item)
    ordered = []
    for row in sorted(rows):
        rev = row % 2 == 1
        group = []
        for item in rows[row]:
            pts = item['pts']
            if (pts[0][0] > pts[-1][0]) ^ rev:
                item = {**item, 'pts': list(reversed(pts))}
            group.append(item)
        group.sort(key=lambda it: it['pts'][0][0], reverse=rev)
        ordered.extend(group)
    return ordered


def write_gcode(items, nc: Path):
    lines = ['; density fullfield bundled A4', 'G21', 'G90', f'G0 Z{PEN_UP_Z:.3f}', f'F{TRAVEL_F}']
    draw = travel = 0.0
    cur = None
    for item in items:
        pts = item['pts']
        if len(pts) < 2:
            continue
        if cur is not None:
            travel += math.hypot(pts[0][0]-cur[0], pts[0][1]-cur[1])
        lines.append(f'G0 X{pts[0][0]:.3f} Y{pts[0][1]:.3f}')
        lines.append(f'G1 Z{PEN_DOWN_Z:.3f} F{DRAW_F}')
        prev = pts[0]
        for x, y in pts[1:]:
            lines.append(f'G1 X{x:.3f} Y{y:.3f}')
            draw += math.hypot(x-prev[0], y-prev[1])
            prev = (x, y)
        lines.append(f'G0 Z{PEN_UP_Z:.3f}')
        cur = pts[-1]
    lines.append('M2')
    nc.write_text('\n'.join(lines)+'\n', encoding='ascii')
    return draw, travel, len(lines)


def render(items, png: Path, pressure=True):
    scale = 5.0; pad = 60
    im = Image.new('RGB', (int(WORK_W_MM*scale + 2*pad), int(WORK_H_MM*scale + 2*pad)), 'white')
    dr = ImageDraw.Draw(im)
    dr.rectangle([pad, pad, pad+WORK_W_MM*scale, pad+WORK_H_MM*scale], outline=(195,195,195), width=1)
    for item in items:
        pts = [(pad+x*scale, pad+(-y)*scale) for x, y in item['pts']]
        if pressure:
            s = float(item.get('strength', 0.25))
            gray = int(np.clip(222 - 155*s, 42, 206))
            color = (gray, gray, gray)
        else:
            color = (0,0,0)
        dr.line(pts, fill=color, width=1, joint='curve')
    im.save(png)


def png_to_pdf(png: Path, pdf: Path):
    c = canvas.Canvas(str(pdf), pagesize=A4)
    pw, ph = A4
    img = Image.open(png); iw, ih = img.size
    m = 18
    sc = min((pw-2*m)/iw, (ph-2*m)/ih)
    dw, dh = iw*sc, ih*sc
    c.drawImage(str(png), (pw-dw)/2, (ph-dh)/2, dw, dh)
    c.showPage(); c.save()


def main():
    shutil.copy2(SRC, OUT/'source_input_copy.jpg')
    shutil.copy2(BASE, OUT/'base_fullfield_a4.nc')
    gray = cv2.imread(str(SRC), cv2.IMREAD_GRAYSCALE)
    dens = preprocess_density(gray)
    cv2.imwrite(str(OUT/'debug_density.png'), np.clip(dens*255, 0, 255).astype(np.uint8))
    mm_to_px, draw_w, draw_h = mm_mapping(gray.shape[1], gray.shape[0])
    base_paths = parse_nc(BASE)
    enhanced, counts = build(base_paths, dens, mm_to_px)
    ordered = order_paths(enhanced)
    nc = OUT/'gemini_density_fullfield_bundled_a4.nc'
    gcode = OUT/'gemini_density_fullfield_bundled_a4.gcode'
    draw, travel, lines = write_gcode(ordered, nc)
    shutil.copy2(nc, gcode)
    ppng = OUT/'gemini_density_fullfield_bundled_preview_pressure_gray.png'
    bpng = OUT/'gemini_density_fullfield_bundled_preview_black_actual.png'
    render(ordered, ppng, True)
    render(ordered, bpng, False)
    png_to_pdf(ppng, OUT/'gemini_density_fullfield_bundled_preview_pressure_gray.pdf')
    png_to_pdf(bpng, OUT/'gemini_density_fullfield_bundled_preview_black_actual.pdf')
    text = (
        'DENSITY FULLFIELD BUNDLED A4 package\n'
        f'source: {SRC}\nbase_nc: {BASE}\noutput_dir: {OUT}\n'
        f'image_px: {gray.shape[1]} x {gray.shape[0]}\n'
        f'drawing_size_mm: {draw_w:.2f} x {draw_h:.2f}\n'
        f'base_paths: {len(base_paths)}\npaths_total: {len(ordered)}\nkind_counts: {dict(counts)}\n'
        f'draw_length_m: {draw/1000:.2f}\ntravel_length_m: {travel/1000:.2f}\ngcode_lines: {lines}\n'
        f'estimated_time_min_ideal: {(draw/DRAW_F + travel/TRAVEL_F):.1f}\n'
        'algorithm_note: starts from tone_levels_fullfield and adds close parallel neighbour strokes only on dark source-toned paths. Light areas remain sparse; dark areas gain tighter line bundles without random short noise.\n'
        'files:\n- gemini_density_fullfield_bundled_preview_pressure_gray.png/pdf\n- gemini_density_fullfield_bundled_preview_black_actual.png/pdf\n- gemini_density_fullfield_bundled_a4.nc\n- gemini_density_fullfield_bundled_a4.gcode\n'
    )
    (OUT/'README_result.txt').write_text(text, encoding='utf-8')
    print(text)

if __name__ == '__main__':
    main()
