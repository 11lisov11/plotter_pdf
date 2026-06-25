from __future__ import annotations

import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(r'C:\plotter_pdf\визитки')
OUT.mkdir(parents=True, exist_ok=True)
random.seed(240626)

# Canvas is large for visual reference; design itself keeps 90x50 proportions.
W, H = 1800, 1100
CARD_W, CARD_H = 1260, 700
BG = (248, 246, 239)
PAPER = (255, 254, 249)
INK = (28, 28, 28)
MID = (105, 105, 105)
LIGHT = (178, 178, 178)
PALE = (222, 222, 222)
ACCENT = (39, 93, 160)

FONT_HAND = [
    r'C:\Windows\Fonts\segoepr.ttf',
    r'C:\Windows\Fonts\segoesc.ttf',
    r'C:\Windows\Fonts\comic.ttf',
    r'C:\Windows\Fonts\ariali.ttf',
    r'C:\Windows\Fonts\arial.ttf',
]
FONT_TEXT = [
    r'C:\Windows\Fonts\segoeui.ttf',
    r'C:\Windows\Fonts\calibri.ttf',
    r'C:\Windows\Fonts\arial.ttf',
]

def load_font(paths, size):
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()

HAND_XL = load_font(FONT_HAND, 96)
HAND_L = load_font(FONT_HAND, 66)
HAND_M = load_font(FONT_HAND, 43)
HAND_S = load_font(FONT_HAND, 30)
TEXT_L = load_font(FONT_TEXT, 42)
TEXT_M = load_font(FONT_TEXT, 31)
TEXT_S = load_font(FONT_TEXT, 24)
TEXT_XS = load_font(FONT_TEXT, 19)


def text_size(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2]-b[0], b[3]-b[1]


def text_center(draw, box, text, font, fill=INK):
    x0, y0, x1, y1 = box
    tw, th = text_size(draw, text, font)
    draw.text((x0 + (x1-x0-tw)/2, y0 + (y1-y0-th)/2 - 3), text, font=font, fill=fill)


def text_right(draw, x_right, y, text, font, fill=INK):
    tw, _ = text_size(draw, text, font)
    draw.text((x_right - tw, y), text, font=font, fill=fill)


def jitter_line(draw, pts, fill=INK, width=2, jitter=0.9, passes=1):
    for _ in range(passes):
        jp = []
        for x, y in pts:
            jp.append((x + random.uniform(-jitter, jitter), y + random.uniform(-jitter, jitter)))
        draw.line(jp, fill=fill, width=width, joint='curve')


def hand_rect(draw, box, fill=INK, width=2, jitter=0.8):
    x0, y0, x1, y1 = box
    for _ in range(width):
        jitter_line(draw, [(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)], fill=fill, width=1, jitter=jitter)


def clean_line(draw, p1, p2, fill=INK, width=2):
    jitter_line(draw, [p1, p2], fill=fill, width=width, jitter=0.5)


def hatch_box(draw, box, angle=-35, spacing=14, fill=LIGHT, width=1, density=0.78):
    x0, y0, x1, y1 = box
    diag = int(math.hypot(x1-x0, y1-y0)) + 120
    theta = math.radians(angle)
    dx, dy = math.cos(theta), math.sin(theta)
    nx, ny = -dy, dx
    cx, cy = (x0+x1)/2, (y0+y1)/2
    for k in range(-diag, diag, spacing):
        if random.random() > density:
            continue
        p1 = (cx + nx*k - dx*diag/2, cy + ny*k - dy*diag/2)
        p2 = (cx + nx*k + dx*diag/2, cy + ny*k + dy*diag/2)
        jitter_line(draw, [p1, p2], fill=fill, width=width, jitter=0.6)


def qr(draw, x, y, s=1.0):
    size = int(112*s)
    hand_rect(draw, (x, y, x+size, y+size), width=2, jitter=0.4)
    cell = size / 11
    blocks = [
        (0,0,3,3),(8,0,11,3),(0,8,3,11),
        (4,1,5,2),(6,1,7,2),(5,3,6,4),(7,4,9,5),
        (3,5,4,6),(5,5,7,7),(9,6,10,7),(4,8,6,9),
        (7,8,8,10),(9,9,10,10),(3,10,4,11),
    ]
    for a,b,c,d in blocks:
        draw.rectangle((x+a*cell, y+b*cell, x+c*cell, y+d*cell), fill=INK)
    draw.text((x-2, y+size+7), 'QR / контакты', font=TEXT_XS, fill=MID)


def draw_printer_icon(draw, x, y, s=1.0):
    # compact isometric sketch, ordered enough for a business card
    hand_rect(draw, (x, y, x+255*s, y+205*s), width=3, jitter=0.9)
    clean_line(draw, (x+34*s,y+38*s), (x+221*s,y+38*s), width=3)
    clean_line(draw, (x+60*s,y+38*s), (x+60*s,y+172*s), width=2)
    clean_line(draw, (x+205*s,y+38*s), (x+205*s,y+172*s), width=2)
    hand_rect(draw, (x+108*s,y+58*s,x+155*s,y+88*s), width=2, jitter=0.8)
    jitter_line(draw, [(x+131*s,y+88*s),(x+118*s,y+112*s),(x+145*s,y+112*s),(x+131*s,y+88*s)], width=2, jitter=0.8)
    clean_line(draw, (x+45*s,y+176*s), (x+220*s,y+176*s), width=3)
    # product on bed
    hand_rect(draw, (x+88*s,y+125*s,x+175*s,y+165*s), width=2, jitter=0.8)
    for i in range(5):
        yy = y+(128+i*8)*s
        jitter_line(draw, [(x+91*s,yy),(x+172*s,yy)], width=1, jitter=0.55)
    hatch_box(draw, (x+88*s,y+124*s,x+175*s,y+166*s), angle=-28, spacing=int(10*s), fill=LIGHT, density=.55)


def draw_nozzle_logo(draw, x, y, s=1.0):
    hand_rect(draw, (x, y, x+210*s, y+86*s), width=3, jitter=0.75)
    hatch_box(draw, (x+12*s,y+10*s,x+198*s,y+80*s), angle=-42, spacing=int(15*s), fill=PALE, density=.62)
    jitter_line(draw, [(x+55*s,y+86*s),(x+88*s,y+138*s),(x+124*s,y+138*s),(x+156*s,y+86*s)], width=3, jitter=0.75)
    # flowing filament
    pts = []
    for i in range(36):
        t = i/35
        xx = x + (105 + 365*t)*s
        yy = y + (150 + 22*math.sin(t*math.tau*1.25))*s
        pts.append((xx, yy))
    jitter_line(draw, pts, width=3, jitter=1.3, passes=2)


def draw_parts_cluster(draw, x, y, s=1.0):
    # cube
    a = 95*s
    pts1 = [(x,y+48*s),(x+a,y+25*s),(x+a,y+125*s),(x,y+148*s),(x,y+48*s)]
    pts2 = [(x,y+48*s),(x+38*s,y),(x+133*s,y+24*s),(x+a,y+25*s)]
    pts3 = [(x+a,y+25*s),(x+133*s,y+24*s),(x+133*s,y+118*s),(x+a,y+125*s)]
    jitter_line(draw, pts1, width=2, jitter=.8)
    jitter_line(draw, pts2, width=2, jitter=.8)
    jitter_line(draw, pts3, width=2, jitter=.8)
    hatch_box(draw, (x,y+25*s,x+133*s,y+148*s), angle=-24, spacing=int(12*s), fill=PALE, density=.50)
    # gear
    cx, cy, r = x+225*s, y+88*s, 52*s
    pts = []
    for i in range(28):
        ang = math.tau*i/28
        rr = r*(1 if i%2==0 else .80)
        pts.append((cx+math.cos(ang)*rr, cy+math.sin(ang)*rr))
    jitter_line(draw, pts+[pts[0]], width=2, jitter=.9)
    draw.ellipse((cx-r*.34, cy-r*.34, cx+r*.34, cy+r*.34), outline=INK, width=2)
    # bracket
    bx, by = x+330*s, y+25*s
    hand_rect(draw, (bx,by,bx+115*s,by+132*s), width=2, jitter=.8)
    draw.ellipse((bx+24*s,by+22*s,bx+50*s,by+48*s), outline=INK, width=2)
    draw.ellipse((bx+70*s,by+86*s,bx+96*s,by+112*s), outline=INK, width=2)
    hatch_box(draw, (bx,by,bx+115*s,by+132*s), angle=35, spacing=int(13*s), fill=PALE, density=.45)


def card_canvas(label, subtitle):
    im = Image.new('RGB', (W,H), BG)
    d = ImageDraw.Draw(im)
    d.text((70, 52), label, font=HAND_M, fill=INK)
    d.text((70, 94), subtitle, font=TEXT_S, fill=MID)
    x0, y0 = 270, 210
    d.rounded_rectangle((x0-8, y0-8, x0+CARD_W+8, y0+CARD_H+8), radius=26, fill=(235,232,224))
    d.rounded_rectangle((x0, y0, x0+CARD_W, y0+CARD_H), radius=24, fill=PAPER, outline=(200,200,200), width=2)
    return im, d, x0, y0


def draw_layout_grid(draw, x0, y0, subtle=True):
    if not subtle:
        return
    # very light guide rhythm, visible as design order, not as construction noise
    for x in [x0+70, x0+CARD_W-70, x0+CARD_W-230]:
        clean_line(draw, (x, y0+70), (x, y0+CARD_H-70), fill=(232,232,232), width=1)
    for y in [y0+82, y0+CARD_H-90]:
        clean_line(draw, (x0+70, y), (x0+CARD_W-70, y), fill=(232,232,232), width=1)


def card_01():
    im, d, x0, y0 = card_canvas('Дизайн 01', 'Премиальная чистая визитка: сопло + подпись + строгие контакты')
    draw_layout_grid(d, x0, y0)
    d.text((x0+78, y0+76), '3D Print', font=HAND_XL, fill=INK)
    d.text((x0+86, y0+168), 'мастерская печати на заказ', font=TEXT_M, fill=MID)
    clean_line(d, (x0+82, y0+222), (x0+535, y0+222), fill=INK, width=2)
    draw_nozzle_logo(d, x0+78, y0+280, .92)
    d.text((x0+690, y0+102), 'Детали', font=HAND_L, fill=INK)
    d.text((x0+692, y0+174), 'прототипы / корпуса / макеты', font=TEXT_M, fill=INK)
    d.text((x0+692, y0+226), 'FDM  •  PETG  •  PLA  •  TPU', font=TEXT_S, fill=MID)
    clean_line(d, (x0+690, y0+286), (x0+1090, y0+286), fill=PALE, width=2)
    d.text((x0+692, y0+328), '@telegram_shop', font=TEXT_M, fill=INK)
    d.text((x0+692, y0+374), '+7 900 000-00-00', font=TEXT_M, fill=INK)
    d.text((x0+692, y0+420), 'город / доставка', font=TEXT_S, fill=MID)
    qr(d, x0+1060, y0+500, .86)
    d.text((x0+76, y0+610), 'От идеи до готовой детали', font=HAND_M, fill=INK)
    return save(im, 'designer_ref_01_premium_nozzle.png')


def card_02():
    im, d, x0, y0 = card_canvas('Дизайн 02', 'Инженерная карточка: сетка, принтер и аккуратный блок услуг')
    draw_layout_grid(d, x0, y0)
    hand_rect(d, (x0+58, y0+58, x0+CARD_W-58, y0+CARD_H-58), fill=INK, width=2, jitter=.55)
    d.text((x0+90, y0+82), 'Печатаем идеи', font=HAND_L, fill=INK)
    d.text((x0+94, y0+150), '3D-печать  •  моделирование  •  малые серии', font=TEXT_S, fill=MID)
    draw_printer_icon(d, x0+95, y0+255, 1.38)
    # service cards
    boxes = [
        ('01', 'прототипы', 'быстрая проверка формы'),
        ('02', 'корпуса', 'под электронику и DIY'),
        ('03', 'детали', 'замена и кастом'),
    ]
    bx, by = x0+560, y0+235
    for i,(num,title,desc) in enumerate(boxes):
        yy = by+i*112
        hand_rect(d, (bx, yy, bx+470, yy+78), fill=PALE, width=1, jitter=.45)
        d.text((bx+24, yy+16), num, font=HAND_M, fill=ACCENT)
        d.text((bx+94, yy+14), title, font=TEXT_M, fill=INK)
        d.text((bx+94, yy+48), desc, font=TEXT_XS, fill=MID)
    clean_line(d, (x0+90, y0+585), (x0+1030, y0+585), fill=INK, width=1)
    d.text((x0+90, y0+610), '@telegram_shop', font=TEXT_S, fill=INK)
    d.text((x0+350, y0+610), '+7 900 000-00-00', font=TEXT_S, fill=INK)
    qr(d, x0+1084, y0+535, .72)
    return save(im, 'designer_ref_02_engineering_grid.png')


def card_03():
    im, d, x0, y0 = card_canvas('Дизайн 03', 'Более тёплый бренд: ручная подпись, детали как маленькая витрина')
    draw_layout_grid(d, x0, y0)
    d.text((x0+80, y0+80), 'Твоя 3D мастерская', font=HAND_L, fill=INK)
    d.text((x0+84, y0+148), 'деталь, которую нельзя купить, можно напечатать', font=TEXT_S, fill=MID)
    clean_line(d, (x0+80, y0+198), (x0+780, y0+198), fill=PALE, width=2)
    draw_parts_cluster(d, x0+94, y0+275, 1.35)
    # right panel
    hand_rect(d, (x0+870, y0+88, x0+1165, y0+612), fill=INK, width=2, jitter=.6)
    text_center(d, (x0+890,y0+108,x0+1145,y0+178), '3D PRINT', TEXT_L, fill=INK)
    clean_line(d, (x0+910,y0+192),(x0+1125,y0+192), fill=PALE, width=2)
    labels = ['моделирование', 'печать', 'постобработка', 'консультация']
    for i, lab in enumerate(labels):
        yy = y0+238+i*55
        d.text((x0+915, yy), f'• {lab}', font=TEXT_S, fill=INK)
    qr(d, x0+958, y0+440, .95)
    d.text((x0+86, y0+610), '+7 900 000-00-00     @telegram_shop', font=TEXT_M, fill=INK)
    return save(im, 'designer_ref_03_warm_workshop.png')


def card_04():
    im, d, x0, y0 = card_canvas('Дизайн 04', 'Мини-плакат: сильная композиция, минимум текста, красиво для плоттера')
    draw_layout_grid(d, x0, y0)
    # big diagonal visual area
    jitter_line(d, [(x0+65,y0+545),(x0+510,y0+92),(x0+1180,y0+92)], fill=PALE, width=2, jitter=1.2)
    draw_nozzle_logo(d, x0+94, y0+118, 1.15)
    d.text((x0+645, y0+118), 'PRINT', font=HAND_XL, fill=INK)
    d.text((x0+650, y0+218), '3D на заказ', font=HAND_L, fill=INK)
    clean_line(d, (x0+650, y0+298), (x0+1110, y0+298), fill=INK, width=2)
    d.text((x0+650, y0+340), 'детали / макеты / корпуса', font=TEXT_M, fill=INK)
    d.text((x0+650, y0+390), 'быстро. аккуратно. по эскизу.', font=TEXT_S, fill=MID)
    # small sketch cloud
    for _ in range(28):
        xx = random.randint(x0+98, x0+570)
        yy = random.randint(y0+382, y0+590)
        jitter_line(d, [(xx, yy), (xx+random.randint(28,90), yy+random.randint(-24,18))], fill=LIGHT, width=1, jitter=.9)
    d.text((x0+84, y0+618), '@telegram_shop', font=TEXT_M, fill=INK)
    d.text((x0+365, y0+618), '+7 900 000-00-00', font=TEXT_M, fill=INK)
    qr(d, x0+1084, y0+532, .76)
    return save(im, 'designer_ref_04_poster_style.png')


def save(im, name):
    path = OUT / name
    im.save(path)
    return path

refs = [card_01(), card_02(), card_03(), card_04()]

# Overview sheet
sheet = Image.new('RGB', (1900, 1420), BG)
d = ImageDraw.Draw(sheet)
d.text((70, 46), 'Дизайнерские референсы визитки 3D-печати', font=HAND_L, fill=INK)
d.text((74, 118), 'Упорядоченная сетка, рукописный характер, карандашная графика, подготовка под будущий G-code', font=TEXT_S, fill=MID)
positions = [(70,190),(985,190),(70,800),(985,800)]
for p, (x,y) in zip(refs, positions):
    img = Image.open(p).convert('RGB')
    img.thumbnail((840, 520), Image.Resampling.LANCZOS)
    d.rounded_rectangle((x-10,y-10,x+img.width+10,y+img.height+10), radius=18, fill=(232,229,220))
    sheet.paste(img, (x,y))
    d.text((x, y+img.height+14), p.name, font=TEXT_S, fill=INK)
overview = OUT / 'designer_references_overview.png'
sheet.save(overview)

# Simple selector sheet: what to choose next.
notes = OUT / 'README_designer.md'
notes.write_text('''# Дизайнерские варианты визитки

Эта версия упорядочена под будущий плоттер: одинаковые поля, ясный главный объект, отдельный блок контактов, QR-зона и меньше случайного визуального шума.

## Варианты

1. `designer_ref_01_premium_nozzle.png` - самый премиальный: сопло, крупный рукописный заголовок, строгий правый блок контактов.
2. `designer_ref_02_engineering_grid.png` - инженерный: рамка, принтер, услуги в карточках.
3. `designer_ref_03_warm_workshop.png` - тёплая мастерская: детали как витрина, справа контактная панель.
4. `designer_ref_04_poster_style.png` - мини-плакат: крупный PRINT, сильная диагональ, минимум текста.

## Моя рекомендация

Для финального G-code лучше всего брать `designer_ref_01_premium_nozzle.png`:
- самый чистый силуэт;
- хорошо читается в формате 90x50 мм;
- не перегружен мелкими деталями;
- легко перевести в плоттерные линии и штриховку.

Если хочется более инженерно и понятно клиенту, брать `designer_ref_02_engineering_grid.png`.
''', encoding='utf-8')

print('created designer references:')
for p in refs + [overview, notes]:
    print(p)
