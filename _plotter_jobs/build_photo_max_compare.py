from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas

out = Path(r'C:\plotter_pdf\_plotter_jobs\gemini_photo_max_compare')
out.mkdir(parents=True, exist_ok=True)
items = [
    ('source', Path(r'C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg')),
    ('old tonal strokes', Path(r'C:\plotter_pdf\_plotter_jobs\gemini_tone_error_microtone_a4_pack\gemini_tone_error_microtone_preview_pressure_gray.png')),
    ('new real strokes', Path(r'C:\plotter_pdf\_plotter_jobs\gemini_lsd_real_strokes_a4_pack\gemini_lsd_real_strokes_preview_pressure_gray.png')),
    ('new black pen actual', Path(r'C:\plotter_pdf\_plotter_jobs\gemini_lsd_real_strokes_a4_pack\gemini_lsd_real_strokes_preview_black_actual.png')),
]
thumb_w = 520
label_h = 34
pad = 18
font = ImageFont.load_default()
thumbs = []
for label, path in items:
    im = Image.open(path).convert('RGB')
    scale = thumb_w / im.width
    th = int(im.height * scale)
    im = im.resize((thumb_w, th), Image.Resampling.LANCZOS)
    thumbs.append((label, im))
max_h = max(im.height for _, im in thumbs)
canvas_img = Image.new('RGB', (pad + len(thumbs)*(thumb_w+pad), pad*2 + label_h + max_h), 'white')
dr = ImageDraw.Draw(canvas_img)
for i, (label, im) in enumerate(thumbs):
    x = pad + i*(thumb_w+pad)
    dr.text((x, pad), label, fill=(0,0,0), font=font)
    dr.rectangle([x, pad+label_h, x+thumb_w, pad+label_h+max_h], outline=(210,210,210))
    canvas_img.paste(im, (x, pad+label_h))
png = out/'photo_max_compare.png'
canvas_img.save(png)
pdf = out/'photo_max_compare.pdf'
c = canvas.Canvas(str(pdf), pagesize=landscape(A4))
pw, ph = landscape(A4)
margin = 18
scale = min((pw-2*margin)/canvas_img.width, (ph-2*margin)/canvas_img.height)
dw = canvas_img.width*scale; dh = canvas_img.height*scale
c.drawImage(str(png), (pw-dw)/2, (ph-dh)/2, dw, dh)
c.showPage(); c.save()
print(png)
print(pdf)
