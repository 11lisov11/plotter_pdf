from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
OUT=Path(r"C:\plotter_pdf\_plotter_jobs\gemini_soft_refine_compare")
OUT.mkdir(parents=True, exist_ok=True)
items=[
    ("Исходник", Path(r"C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg")),
    ("старый лучший\ntone_error_corrected", Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_corrected_a4_pack\gemini_tone_error_corrected_preview_pressure_gray.png")),
    ("новый мягкий добор\ntone_error_soft_refine", Path(r"C:\plotter_pdf\_plotter_jobs\gemini_tone_error_soft_refine_a4_pack\gemini_tone_error_soft_refine_preview_pressure_gray.png")),
]
canv=[]
for label,p in items:
    im=Image.open(p).convert('RGB')
    w,h=im.size
    target_h=900
    im=im.resize((max(1,int(w*target_h/h)), target_h), Image.Resampling.LANCZOS)
    if im.width>520:
        im=im.resize((520, int(im.height*520/im.width)), Image.Resampling.LANCZOS)
    canvas=Image.new('RGB',(560,990),'white')
    x=(560-im.width)//2; y=76+(890-im.height)//2
    canvas.paste(im,(x,y))
    d=ImageDraw.Draw(canvas)
    try: font=ImageFont.truetype('arial.ttf',22)
    except Exception: font=ImageFont.load_default()
    d.multiline_text((20,18),label,fill=(0,0,0),font=font,spacing=4)
    canv.append(canvas)
compare=Image.new('RGB',(560*len(canv),990),(245,245,245))
for i,im in enumerate(canv):
    compare.paste(im,(i*560,0))
    ImageDraw.Draw(compare).line((i*560,0,i*560,990),fill=(200,200,200),width=1)
compare.save(OUT/'soft_refine_compare.png')
compare.save(OUT/'soft_refine_compare.pdf','PDF',resolution=160)
print(OUT/'soft_refine_compare.png')
print(OUT/'soft_refine_compare.pdf')
