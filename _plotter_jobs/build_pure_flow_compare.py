from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas
out=Path(r'C:\plotter_pdf\_plotter_jobs\gemini_pure_flow_compare')
out.mkdir(parents=True,exist_ok=True)
items=[
 ('source',Path(r'C:\Users\USER\Downloads\f3370dc25e274d3fa82ef06fc8258ba5_gemini-3.1-flash-image-preview.jpg')),
 ('clean density gray',Path(r'C:\plotter_pdf\_plotter_jobs\gemini_density_guided_clean_a4_pack\gemini_density_guided_clean_preview_pressure_gray.png')),
 ('clean density black',Path(r'C:\plotter_pdf\_plotter_jobs\gemini_density_guided_clean_a4_pack\gemini_density_guided_clean_preview_black_actual.png')),
 ('pure flow no-LSD gray',Path(r'C:\plotter_pdf\_plotter_jobs\gemini_density_pure_flow_nolsd_a4_pack\gemini_density_pure_flow_nolsd_preview_pressure_gray.png')),
 ('pure flow no-LSD black',Path(r'C:\plotter_pdf\_plotter_jobs\gemini_density_pure_flow_nolsd_a4_pack\gemini_density_pure_flow_nolsd_preview_black_actual.png')),
]
thumb_w=430; pad=16; label_h=32; font=ImageFont.load_default(); thumbs=[]
for label,path in items:
 im=Image.open(path).convert('RGB'); sc=thumb_w/im.width
 im=im.resize((thumb_w,int(im.height*sc)),Image.Resampling.LANCZOS); thumbs.append((label,im))
max_h=max(im.height for _,im in thumbs)
img=Image.new('RGB',(pad+len(thumbs)*(thumb_w+pad),pad*2+label_h+max_h),'white')
dr=ImageDraw.Draw(img)
for i,(label,im) in enumerate(thumbs):
 x=pad+i*(thumb_w+pad); dr.text((x,pad),label,fill=(0,0,0),font=font)
 dr.rectangle([x,pad+label_h,x+thumb_w,pad+label_h+max_h],outline=(210,210,210)); img.paste(im,(x,pad+label_h))
png=out/'pure_flow_compare.png'; pdf=out/'pure_flow_compare.pdf'; img.save(png)
c=canvas.Canvas(str(pdf),pagesize=landscape(A4)); pw,ph=landscape(A4); m=12
sc=min((pw-2*m)/img.width,(ph-2*m)/img.height); dw=img.width*sc; dh=img.height*sc
c.drawImage(str(png),(pw-dw)/2,(ph-dh)/2,dw,dh); c.showPage(); c.save()
print(png); print(pdf)
