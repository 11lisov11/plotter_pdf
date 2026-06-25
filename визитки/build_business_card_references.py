from __future__ import annotations

import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(r'C:\plotter_pdf\визитки')
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1600, 1000
CARD_W, CARD_H = 900, 500
random.seed(20260624)

FONT_CANDIDATES = [
    r'C:\Windows\Fonts\segoepr.ttf',
    r'C:\Windows\Fonts\segoesc.ttf',
    r'C:\Windows\Fonts\comic.ttf',
    r'C:\Windows\Fonts\ariali.ttf',
    r'C:\Windows\Fonts\arial.ttf',
]
TEXT_FONT_CANDIDATES = [
    r'C:\Windows\Fonts\arial.ttf',
    r'C:\Windows\Fonts\segoeui.ttf',
    r'C:\Windows\Fonts\calibri.ttf',
]

def font(paths, size):
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()

HAND_BIG = font(FONT_CANDIDATES, 70)
HAND_MED = font(FONT_CANDIDATES, 42)
HAND_SMALL = font(FONT_CANDIDATES, 30)
TEXT = font(TEXT_FONT_CANDIDATES, 28)
TEXT_SMALL = font(TEXT_FONT_CANDIDATES, 22)

INK = (32, 32, 32)
LIGHT = (145, 145, 145)
PALE = (205, 205, 205)
BLUE = (30, 80, 180)
BG = (250, 248, 242)


def jitter_line(draw, pts, fill=INK, width=2, jitter=1.2, passes=1):
    for _ in range(passes):
        jp = []
        for x, y in pts:
            jp.append((x + random.uniform(-jitter, jitter), y + random.uniform(-jitter, jitter)))
        draw.line(jp, fill=fill, width=width, joint='curve')


def hand_rect(draw, box, fill=INK, width=2, jitter=1.0):
    x0, y0, x1, y1 = box
    for _ in range(width):
        jitter_line(draw, [(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)], fill=fill, width=1, jitter=jitter)


def hatch(draw, polygon_box, angle=-35, spacing=12, fill=LIGHT, width=1):
    x0, y0, x1, y1 = polygon_box
    diag = int(math.hypot(x1-x0, y1-y0)) + 80
    theta = math.radians(angle)
    dx, dy = math.cos(theta), math.sin(theta)
    nx, ny = -dy, dx
    cx, cy = (x0+x1)/2, (y0+y1)/2
    for k in range(-diag, diag, spacing):
        p1 = (cx + nx*k - dx*diag/2, cy + ny*k - dy*diag/2)
        p2 = (cx + nx*k + dx*diag/2, cy + ny*k + dy*diag/2)
        if random.random() < 0.92:
            jitter_line(draw, [p1, p2], fill=fill, width=width, jitter=0.7)


def draw_printer(draw, x, y, s=1.0):
    # frame
    hand_rect(draw, (x, y, x+260*s, y+210*s), width=3, jitter=1.4)
    jitter_line(draw, [(x+35*s,y+35*s),(x+225*s,y+35*s)], width=3, jitter=1)
    jitter_line(draw, [(x+65*s,y+35*s),(x+65*s,y+178*s)], width=2, jitter=1)
    jitter_line(draw, [(x+205*s,y+35*s),(x+205*s,y+178*s)], width=2, jitter=1)
    # bed
    jitter_line(draw, [(x+45*s,y+178*s),(x+220*s,y+178*s)], width=3, jitter=1)
    jitter_line(draw, [(x+70*s,y+160*s),(x+190*s,y+160*s)], width=2, jitter=1)
    # carriage + nozzle
    hand_rect(draw, (x+114*s,y+52*s,x+154*s,y+82*s), width=2, jitter=1)
    jitter_line(draw, [(x+134*s,y+82*s),(x+124*s,y+105*s),(x+144*s,y+105*s),(x+134*s,y+82*s)], width=2, jitter=1)
    # printed object
    for i in range(5):
        jitter_line(draw, [(x+95*s,y+(154-i*9)*s),(x+170*s,y+(154-i*9)*s)], width=2, jitter=1.3)
    hand_rect(draw, (x+95*s,y+112*s,x+170*s,y+160*s), width=2, jitter=1.5)
    hatch(draw, (x+94*s,y+112*s,x+171*s,y+160*s), angle=-25, spacing=max(7,int(10*s)), fill=LIGHT)


def draw_nozzle(draw, x, y, s=1.0):
    hand_rect(draw, (x, y, x+170*s, y+90*s), width=3, jitter=1.2)
    jitter_line(draw, [(x+45*s,y+90*s),(x+78*s,y+145*s),(x+112*s,y+145*s),(x+145*s,y+90*s)], width=3, jitter=1.2)
    hatch(draw, (x+8*s,y+8*s,x+162*s,y+85*s), angle=-45, spacing=max(8,int(12*s)), fill=LIGHT)
    # filament layers
    for i in range(8):
        yy = y + (168+i*12)*s
        jitter_line(draw, [(x+30*s, yy),(x+190*s, yy + random.uniform(-2,2)*s)], fill=INK, width=2, jitter=1.2)
    hand_rect(draw, (x+35*s,y+160*s,x+190*s,y+255*s), width=2, jitter=1.2)


def draw_gear(draw, cx, cy, r=58):
    pts = []
    for i in range(24):
        a = math.tau*i/24
        rr = r * (1.0 if i % 2 == 0 else 0.82)
        pts.append((cx+math.cos(a)*rr, cy+math.sin(a)*rr))
    jitter_line(draw, pts+[pts[0]], width=2, jitter=1.4)
    draw.ellipse((cx-r*0.35, cy-r*0.35, cx+r*0.35, cy+r*0.35), outline=INK, width=2)
    hatch(draw, (cx-r, cy-r, cx+r, cy+r), angle=-35, spacing=12, fill=PALE)


def draw_cube(draw, x, y, s=1.0):
    a = 110*s
    pts_front = [(x,y+55*s),(x+a,y+30*s),(x+a,y+140*s),(x,y+165*s),(x,y+55*s)]
    pts_top = [(x,y+55*s),(x+45*s,y),(x+155*s,y+25*s),(x+a,y+30*s)]
    pts_side = [(x+a,y+30*s),(x+155*s,y+25*s),(x+155*s,y+135*s),(x+a,y+140*s)]
    jitter_line(draw, pts_front, width=2, jitter=1.2)
    jitter_line(draw, pts_top, width=2, jitter=1.2)
    jitter_line(draw, pts_side, width=2, jitter=1.2)
    hatch(draw, (x,y+35*s,x+a,y+165*s), angle=-20, spacing=12, fill=PALE)
    hatch(draw, (x+a,y+25*s,x+155*s,y+140*s), angle=42, spacing=10, fill=LIGHT)


def draw_qr_placeholder(draw, x, y, s=1):
    hand_rect(draw, (x,y,x+92*s,y+92*s), width=2, jitter=0.6)
    cells = [
        (0,0,3,3),(6,0,9,3),(0,6,3,9),
        (4,4,5,5),(5,6,6,7),(7,5,8,6),(3,7,4,8),(6,8,7,9),
        (4,1,5,2),(2,4,3,5),(8,4,9,5),(5,2,6,3)
    ]
    cs = 92*s/10
    for a,b,c,d in cells:
        draw.rectangle((x+a*cs,y+b*cs,x+c*cs,y+d*cs), fill=INK)


def card_base(title, subtitle, filename, variant):
    im = Image.new('RGB', (W,H), BG)
    d = ImageDraw.Draw(im)
    d.text((70,48), title, font=HAND_MED, fill=INK)
    d.text((70,92), subtitle, font=TEXT_SMALL, fill=(90,90,90))
    cx, cy = 350, 210
    card = (cx, cy, cx+CARD_W, cy+CARD_H)
    hand_rect(d, card, width=3, jitter=1.2)
    # inner safe margin
    hand_rect(d, (cx+30, cy+30, cx+CARD_W-30, cy+CARD_H-30), fill=PALE, width=1, jitter=1.0)
    if variant == 1:
        d.text((cx+65, cy+55), '3D Print Lab', font=HAND_BIG, fill=INK)
        draw_printer(d, cx+90, cy+165, 1.25)
        d.text((cx+440, cy+190), 'печать деталей', font=HAND_MED, fill=INK)
        d.text((cx+440, cy+245), 'макеты / корпуса / прототипы', font=TEXT, fill=INK)
        jitter_line(d, [(cx+438,cy+290),(cx+780,cy+290)], width=1, jitter=0.8)
        d.text((cx+440, cy+315), '@telegram  +7 900 000-00-00', font=TEXT_SMALL, fill=INK)
        draw_qr_placeholder(d, cx+760, cy+365, 1.0)
    elif variant == 2:
        draw_nozzle(d, cx+80, cy+75, 1.1)
        # filament becomes title curve
        curve = [(cx+280,cy+295),(cx+380,cy+250),(cx+500,cy+230),(cx+650,cy+250),(cx+780,cy+215)]
        jitter_line(d, curve, width=3, jitter=2.0, passes=2)
        d.text((cx+360, cy+120), 'Печатаем идеи', font=HAND_BIG, fill=INK)
        d.text((cx+365, cy+210), '3D-печать на заказ', font=HAND_MED, fill=INK)
        d.text((cx+90, cy+405), 'детали  |  прототипы  |  подарки', font=TEXT, fill=INK)
        draw_qr_placeholder(d, cx+770, cy+375, 0.85)
    elif variant == 3:
        d.text((cx+60, cy+55), 'Мастерская 3D печати', font=HAND_BIG, fill=INK)
        jitter_line(d, [(cx+75,cy+142),(cx+725,cy+142)], width=1, jitter=1)
        draw_cube(d, cx+90, cy+210, 1.0)
        draw_gear(d, cx+370, cy+292, 58)
        draw_printer(d, cx+545, cy+188, .85)
        d.text((cx+80, cy+405), 'от эскиза до готовой детали', font=HAND_MED, fill=INK)
        d.text((cx+565, cy+420), '+7 900 000-00-00', font=TEXT_SMALL, fill=INK)
        draw_qr_placeholder(d, cx+770, cy+370, .85)
    elif variant == 4:
        d.text((cx+70, cy+60), '3D детали', font=HAND_BIG, fill=INK)
        d.text((cx+70, cy+135), 'быстро и аккуратно', font=HAND_MED, fill=INK)
        draw_nozzle(d, cx+580, cy+70, .78)
        draw_cube(d, cx+92, cy+245, .72)
        draw_gear(d, cx+310, cy+315, 45)
        draw_printer(d, cx+455, cy+240, .95)
        # sketchy background lines
        for _ in range(24):
            x = random.randint(cx+55, cx+CARD_W-90)
            y = random.randint(cy+210, cy+CARD_H-72)
            jitter_line(d, [(x,y),(x+random.randint(35,90),y+random.randint(-25,25))], fill=PALE, width=1, jitter=1.1)
        d.text((cx+70, cy+420), '@shop3d  |  phone  |  qr', font=TEXT, fill=INK)
        draw_qr_placeholder(d, cx+765, cy+370, .86)
    im.save(OUT / filename)
    return OUT / filename

refs = []
refs.append(card_base('Референс 01', 'Чертежная мастерская: строго, инженерно, но вручную', 'ref_01_chertyozhnaya_masterskaya.png', 1))
refs.append(card_base('Референс 02', 'Сопло и рукописный заголовок: самый выразительный вариант', 'ref_02_soplo_i_podpis.png', 2))
refs.append(card_base('Референс 03', 'Полка деталей: показывает ассортимент 3D-печати', 'ref_03_polka_detalei.png', 3))
refs.append(card_base('Референс 04', 'Карточка мастера: теплая ручная визитка', 'ref_04_rukopisnaya_kartochka.png', 4))

# contact sheet
thumbs = []
for p in refs:
    img = Image.open(p).convert('RGB')
    img.thumbnail((760, 475), Image.Resampling.LANCZOS)
    thumbs.append((p.name, img.copy()))
sheet = Image.new('RGB', (1680, 1180), BG)
d = ImageDraw.Draw(sheet)
d.text((60, 36), 'Референсы визитки для магазина 3D-печати', font=HAND_MED, fill=INK)
d.text((60, 88), 'Карандашная стилистика, рукописный шрифт, пригодно для последующего G-code', font=TEXT_SMALL, fill=(80,80,80))
positions = [(60,150),(860,150),(60,660),(860,660)]
for (name,img), (x,y) in zip(thumbs, positions):
    sheet.paste(img, (x,y))
    d.rectangle((x,y,x+img.width,y+img.height), outline=(180,180,180), width=2)
    d.text((x, y+img.height+10), name, font=TEXT_SMALL, fill=INK)
sheet_path = OUT / 'references_overview.png'
sheet.save(sheet_path)

# write SVG-ish notes/README
readme = OUT / 'README.md'
readme.write_text('''# Визитки: референсы для магазина 3D-печати

Здесь лежат первые визуальные направления. Это пока НЕ финальный G-code, а референсы для выбора стиля.

## Файлы

1. `ref_01_chertyozhnaya_masterskaya.png` - инженерная визитка с 3D-принтером и рамкой.
2. `ref_02_soplo_i_podpis.png` - сопло экструдера, линия пластика и рукописный заголовок.
3. `ref_03_polka_detalei.png` - полка/набор 3D-деталей: куб, шестеренка, принтер.
4. `ref_04_rukopisnaya_kartochka.png` - более живая карточка мастера.
5. `references_overview.png` - все варианты на одном листе.

## Рекомендация

Для плоттера лучше всего развивать вариант 02 или смесь 02 + 04:
- крупный рукописный заголовок;
- сопло или маленький 3D-принтер;
- карандашная штриховка без шумовой каши;
- QR и контакты снизу справа;
- формат визитки 90x50 мм.

После выбора направления сделаем отдельный чистый G-code под плоттер.
''', encoding='utf-8')

print('created:')
for p in refs + [sheet_path, readme]:
    print(p)
