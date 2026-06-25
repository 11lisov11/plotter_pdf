from __future__ import annotations

import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(r'C:\plotter_pdf\визитки\premium_v2')
OUT.mkdir(parents=True, exist_ok=True)
random.seed(250625)

# Large 90x50 business-card ratio preview.
W, H = 1800, 1000
PAPER = (255, 253, 247)
BG = (242, 239, 230)
INK = (22, 22, 22)
MUTED = (86, 86, 86)
LIGHT = (166, 166, 166)
PALE = (224, 224, 218)
BLUE = (28, 78, 160)

FONT_HAND = [
    r'C:\Windows\Fonts\segoesc.ttf',
    r'C:\Windows\Fonts\segoepr.ttf',
    r'C:\Windows\Fonts\ariali.ttf',
    r'C:\Windows\Fonts\arial.ttf',
]
FONT_BODY = [
    r'C:\Windows\Fonts\segoeui.ttf',
    r'C:\Windows\Fonts\calibri.ttf',
    r'C:\Windows\Fonts\arial.ttf',
]
FONT_BOLD = [
    r'C:\Windows\Fonts\segoeuib.ttf',
    r'C:\Windows\Fonts\calibrib.ttf',
    r'C:\Windows\Fonts\arialbd.ttf',
]

def load_font(candidates, size):
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()

HAND_HERO = load_font(FONT_HAND, 126)
HAND_SUB = load_font(FONT_HAND, 58)
HAND_SMALL = load_font(FONT_HAND, 34)
BOLD_XL = load_font(FONT_BOLD, 70)
BOLD_L = load_font(FONT_BOLD, 48)
BOLD_M = load_font(FONT_BOLD, 34)
BODY_L = load_font(FONT_BODY, 42)
BODY_M = load_font(FONT_BODY, 32)
BODY_S = load_font(FONT_BODY, 25)
BODY_XS = load_font(FONT_BODY, 19)


def txt_size(draw, text, font):
    box = draw.textbbox((0,0), text, font=font)
    return box[2]-box[0], box[3]-box[1]


def right_text(draw, x, y, text, font, fill=INK):
    w, _ = txt_size(draw, text, font)
    draw.text((x-w, y), text, font=font, fill=fill)


def center_text(draw, box, text, font, fill=INK):
    x0,y0,x1,y1 = box
    w,h = txt_size(draw, text, font)
    draw.text((x0+(x1-x0-w)/2, y0+(y1-y0-h)/2-3), text, font=font, fill=fill)


def line(draw, pts, fill=INK, width=3, jitter=0.0, passes=1):
    for _ in range(passes):
        pp=[]
        for x,y in pts:
            pp.append((x+random.uniform(-jitter,jitter), y+random.uniform(-jitter,jitter)))
        draw.line(pp, fill=fill, width=width, joint='curve')


def poly(draw, pts, outline=INK, width=3, jitter=.0):
    line(draw, pts+[pts[0]], fill=outline, width=width, jitter=jitter)


def hatch(draw, box, angle=-35, spacing=16, fill=LIGHT, width=1, density=.7):
    x0,y0,x1,y1 = box
    diag = int(math.hypot(x1-x0, y1-y0)) + 160
    theta = math.radians(angle)
    dx,dy = math.cos(theta), math.sin(theta)
    nx,ny = -dy, dx
    cx,cy = (x0+x1)/2, (y0+y1)/2
    for k in range(-diag, diag, spacing):
        if random.random() > density:
            continue
        p1 = (cx + nx*k - dx*diag/2, cy + ny*k - dy*diag/2)
        p2 = (cx + nx*k + dx*diag/2, cy + ny*k + dy*diag/2)
        line(draw, [p1,p2], fill=fill, width=width, jitter=.6)


def rounded_card():
    im = Image.new('RGB', (W,H), BG)
    d = ImageDraw.Draw(im)
    # shadow
    d.rounded_rectangle((64,64,W-64,H-64), radius=44, fill=(224,220,210))
    d.rounded_rectangle((50,50,W-82,H-82), radius=38, fill=PAPER, outline=(204,202,193), width=2)
    return im, d


def qr(draw, x, y, s=1.0):
    size = int(150*s)
    draw.rounded_rectangle((x,y,x+size,y+size), radius=10, outline=INK, width=3)
    cell = size/15
    blocks = [
        (1,1,5,5),(10,1,14,5),(1,10,5,14),
        (6,1,7,2),(8,2,9,4),(6,5,8,6),(9,6,11,7),
        (5,8,7,10),(8,9,10,11),(12,8,13,10),(6,12,8,13),
        (9,12,11,14),(13,12,14,14),(5,14,6,15),(11,14,14,15),
    ]
    for a,b,c,d in blocks:
        draw.rectangle((x+a*cell,y+b*cell,x+c*cell,y+d*cell), fill=INK)
    draw.text((x+6, y+size+12), 'сканировать', font=BODY_XS, fill=MUTED)


def draw_extruder_scene(draw, x, y, s=1.0):
    # Main nozzle as hero illustration, more deliberate than previous placeholder.
    # top metal block
    block = [(x+30*s,y+20*s),(x+350*s,y+20*s),(x+350*s,y+150*s),(x+30*s,y+150*s)]
    poly(draw, block, width=4, jitter=.7)
    hatch(draw, (x+45*s,y+34*s,x+335*s,y+136*s), angle=-45, spacing=int(19*s), fill=PALE, density=.65)
    # heat break lines
    for i in range(4):
        yy = y + (48+i*24)*s
        line(draw, [(x+60*s,yy),(x+320*s,yy)], fill=LIGHT, width=1, jitter=.3)
    # nozzle triangle
    nozzle_pts = [(x+105*s,y+150*s),(x+175*s,y+265*s),(x+245*s,y+150*s)]
    poly(draw, nozzle_pts, width=4, jitter=.7)
    hatch(draw, (x+112*s,y+154*s,x+238*s,y+258*s), angle=34, spacing=int(15*s), fill=LIGHT, density=.55)
    # hot filament curve
    pts=[]
    for i in range(80):
        t=i/79
        xx=x+(175+520*t)*s
        yy=y+(280+34*math.sin(t*math.tau*1.15)-18*t)*s
        pts.append((xx,yy))
    line(draw, pts, fill=INK, width=5, jitter=1.2, passes=2)
    # printed layered object
    ox, oy = x+440*s, y+395*s
    for i in range(12):
        yy=oy+i*16*s
        width=(250 - abs(i-6)*14)*s
        x1=ox - width/2
        x2=ox + width/2
        line(draw, [(x1,yy),(x2,yy+random.uniform(-1,1)*s)], fill=INK, width=3, jitter=.8)
    poly(draw, [(ox-136*s,oy-4*s),(ox+136*s,oy-4*s),(ox+116*s,oy+185*s),(ox-116*s,oy+185*s)], width=3, jitter=.65)
    hatch(draw, (ox-130*s,oy,ox+130*s,oy+180*s), angle=-28, spacing=int(18*s), fill=PALE, density=.45)
    # small sparks/idea lines
    for a in [-58,-35,38,62]:
        theta=math.radians(a)
        sx=x+175*s+math.cos(theta)*105*s
        sy=y+265*s+math.sin(theta)*105*s
        ex=x+175*s+math.cos(theta)*155*s
        ey=y+265*s+math.sin(theta)*155*s
        line(draw, [(sx,sy),(ex,ey)], fill=LIGHT, width=2, jitter=.7)


def draw_mini_icon_cube(draw, x, y, s=1.0):
    a=84*s
    p1=[(x,y+46*s),(x+a,y+24*s),(x+a,y+118*s),(x,y+140*s),(x,y+46*s)]
    p2=[(x,y+46*s),(x+36*s,y),(x+120*s,y+22*s),(x+a,y+24*s)]
    p3=[(x+a,y+24*s),(x+120*s,y+22*s),(x+120*s,y+112*s),(x+a,y+118*s)]
    line(draw,p1,width=3,jitter=.45); line(draw,p2,width=3,jitter=.45); line(draw,p3,width=3,jitter=.45)
    hatch(draw,(x,y+22*s,x+120*s,y+140*s),angle=-25,spacing=int(14*s),fill=PALE,density=.50)


def draw_gear(draw, cx, cy, r):
    pts=[]
    for i in range(32):
        a=math.tau*i/32
        rr=r*(1 if i%2==0 else .80)
        pts.append((cx+math.cos(a)*rr, cy+math.sin(a)*rr))
    line(draw, pts+[pts[0]], width=3, jitter=.45)
    draw.ellipse((cx-r*.34,cy-r*.34,cx+r*.34,cy+r*.34), outline=INK, width=3)


def front():
    im,d = rounded_card()
    # left art area
    draw_extruder_scene(d, 135, 155, 1.18)
    # subtle split line
    line(d, [(950,150),(950,820)], fill=PALE, width=2, jitter=.2)
    # text block
    d.text((1020,155), '3D Печать', font=HAND_HERO, fill=INK)
    d.text((1027,282), 'детали • корпуса • прототипы', font=BODY_L, fill=INK)
    line(d, [(1026,348),(1580,348)], fill=INK, width=3, jitter=.2)
    d.text((1028,405), 'Печатаем по эскизу, модели или идее.', font=BODY_M, fill=MUTED)
    d.text((1028,455), 'Подскажем материал и подготовим файл.', font=BODY_M, fill=MUTED)
    # CTA card
    d.rounded_rectangle((1026,535,1438,618), radius=20, outline=INK, width=3)
    center_text(d, (1026,535,1438,618), 'Рассчитать заказ', font=BOLD_M, fill=INK)
    d.rounded_rectangle((1460,535,1618,618), radius=20, outline=PALE, width=2)
    center_text(d, (1460,535,1618,618), 'от 1 шт', font=BODY_S, fill=BLUE)
    # contact row
    d.text((1028,705), '@telegram_shop', font=BOLD_M, fill=BLUE)
    d.text((1028,756), '+7 900 000-00-00', font=BODY_M, fill=INK)
    qr(d, 1480, 676, .78)
    # tagline bottom left
    d.text((135, 835), 'от идеи до готовой детали', font=HAND_SUB, fill=INK)
    return save(im, 'premium_v2_front_large.png')


def back():
    im,d = rounded_card()
    d.text((135,135), 'Что печатаем', font=HAND_HERO, fill=INK)
    d.text((142,260), 'коротко и понятно для клиента', font=BODY_M, fill=MUTED)
    cards=[
        ('01','Прототипы','быстрая проверка формы'),
        ('02','Корпуса','для электроники и DIY'),
        ('03','Детали','крепления и замены'),
    ]
    x0=140
    for i,(n,title,desc) in enumerate(cards):
        x=x0+i*520
        y=390
        d.rounded_rectangle((x,y,x+430,y+285), radius=28, outline=INK, width=3)
        d.text((x+34,y+28), n, font=HAND_SUB, fill=BLUE)
        d.text((x+138,y+44), title, font=BOLD_M, fill=INK)
        d.text((x+138,y+96), desc, font=BODY_XS, fill=MUTED)
        if i==0:
            draw_mini_icon_cube(d,x+130,y+150,1.0)
        elif i==1:
            draw_extruder_scene(d,x+80,y+130,.42)
        else:
            draw_gear(d,x+215,y+208,55)
    line(d, [(140,760),(1660,760)], fill=INK, width=2, jitter=.2)
    d.text((142,805), '@telegram_shop', font=BOLD_M, fill=BLUE)
    d.text((470,805), '+7 900 000-00-00', font=BODY_M, fill=INK)
    d.text((850,805), 'город / доставка / самовывоз', font=BODY_S, fill=MUTED)
    qr(d, 1510, 785, .72)
    return save(im, 'premium_v2_back_large.png')


def save(im, name):
    path=OUT/name
    im.save(path)
    return path

front_path=front()
back_path=back()

# presentation sheet without shrinking text into unreadability
sheet=Image.new('RGB',(2100,1850),BG)
d=ImageDraw.Draw(sheet)
d.text((80,60),'Premium v2: визитка магазина 3D-печати',font=BOLD_XL,fill=INK)
d.text((82,135),'Один сильный визуальный образ, крупный оффер, понятный CTA, QR и контакты. Готово как референс для будущего G-code.',font=BODY_M,fill=MUTED)
for path,y,label in [(front_path,285,'Лицевая сторона'),(back_path,1080,'Обратная сторона')]:
    img=Image.open(path).convert('RGB')
    img.thumbnail((1500,590), Image.Resampling.LANCZOS)
    x=300
    d.text((x,y-64),label,font=BOLD_M,fill=INK)
    d.rounded_rectangle((x-18,y-18,x+img.width+18,y+img.height+18),radius=28,fill=(226,223,214))
    sheet.paste(img,(x,y))
presentation=OUT/'premium_v2_presentation.png'
sheet.save(presentation)

notes=OUT/'premium_v2_notes.md'
notes.write_text('''# Premium v2 визитка для магазина 3D-печати

Это замена слабым UX/UI pro max вариантам.

## Что исправлено

- Нет мелкого мусорного текста.
- Один главный визуальный герой: сопло экструдера и печатаемая деталь.
- Четкая иерархия: `3D Печать` -> что делаем -> CTA -> контакты/QR.
- Контакты и QR не прилеплены случайно, а стоят в отдельном нижнем блоке.
- Рукописный шрифт используется крупно, а не в мелкой каше.
- Иллюстрация стала больше похожа на карандашный технический скетч.
- Есть лицевая и обратная сторона.

## Рекомендация

Для плоттера лучше начинать с лицевой стороны `premium_v2_front_large.png`.

Потом делать G-code слоями:
1. крупные контуры сопла и детали;
2. рукописный заголовок;
3. контакты;
4. QR или его упрощенная плоттерная версия;
5. легкая штриховка, без шумовой каши.
''',encoding='utf-8')

print('created premium v2 files:')
for p in [front_path,back_path,presentation,notes]:
    print(p)

