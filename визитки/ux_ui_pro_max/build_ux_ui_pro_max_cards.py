from __future__ import annotations

import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(r'C:\plotter_pdf\визитки\ux_ui_pro_max')
OUT.mkdir(parents=True, exist_ok=True)
random.seed(62024)

CANVAS_W, CANVAS_H = 1800, 1100
CARD_W, CARD_H = 1260, 700  # 90x50 ratio
BG = (246, 244, 238)
CARD = (255, 254, 249)
INK = (24, 24, 24)
MUTED = (92, 92, 92)
LIGHT = (174, 174, 174)
PALE = (226, 226, 226)
BLUE = (34, 86, 168)
GHOST = (238, 237, 232)

FONT_HAND = [
    r'C:\Windows\Fonts\segoepr.ttf',
    r'C:\Windows\Fonts\segoesc.ttf',
    r'C:\Windows\Fonts\comic.ttf',
    r'C:\Windows\Fonts\ariali.ttf',
    r'C:\Windows\Fonts\arial.ttf',
]
FONT_BODY = [
    r'C:\Windows\Fonts\segoeui.ttf',
    r'C:\Windows\Fonts\calibri.ttf',
    r'C:\Windows\Fonts\arial.ttf',
]
FONT_BODY_BOLD = [
    r'C:\Windows\Fonts\segoeuib.ttf',
    r'C:\Windows\Fonts\calibrib.ttf',
    r'C:\Windows\Fonts\arialbd.ttf',
]

def load_font(candidates, size):
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()

HAND_HERO = load_font(FONT_HAND, 104)
HAND_BIG = load_font(FONT_HAND, 78)
HAND_MED = load_font(FONT_HAND, 48)
HAND_SMALL = load_font(FONT_HAND, 31)
BODY_XL = load_font(FONT_BODY_BOLD, 54)
BODY_L = load_font(FONT_BODY_BOLD, 39)
BODY_M = load_font(FONT_BODY, 30)
BODY_S = load_font(FONT_BODY, 23)
BODY_XS = load_font(FONT_BODY, 18)
BODY_TINY = load_font(FONT_BODY, 15)


def tbox(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2]-b[0], b[3]-b[1]


def center_text(draw, box, text, font, fill=INK):
    x0, y0, x1, y1 = box
    w, h = tbox(draw, text, font)
    draw.text((x0 + (x1-x0-w)/2, y0 + (y1-y0-h)/2 - 3), text, font=font, fill=fill)


def right_text(draw, x, y, text, font, fill=INK):
    w, _ = tbox(draw, text, font)
    draw.text((x-w, y), text, font=font, fill=fill)


def line(draw, pts, fill=INK, width=2, jitter=0.0, passes=1):
    for _ in range(passes):
        pp = []
        for x, y in pts:
            pp.append((x + random.uniform(-jitter, jitter), y + random.uniform(-jitter, jitter)))
        draw.line(pp, fill=fill, width=width, joint='curve')


def rect(draw, box, fill=INK, width=2, jitter=0.0, radius=0):
    x0, y0, x1, y1 = box
    if radius:
        draw.rounded_rectangle(box, radius=radius, outline=fill, width=width)
    else:
        for i in range(width):
            line(draw, [(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)], fill=fill, width=1, jitter=jitter)


def hatch(draw, box, angle=-35, spacing=14, fill=LIGHT, width=1, density=.70, clip_margin=0):
    x0, y0, x1, y1 = box
    x0 += clip_margin; y0 += clip_margin; x1 -= clip_margin; y1 -= clip_margin
    diag = int(math.hypot(x1-x0, y1-y0)) + 140
    theta = math.radians(angle)
    dx, dy = math.cos(theta), math.sin(theta)
    nx, ny = -dy, dx
    cx, cy = (x0+x1)/2, (y0+y1)/2
    for k in range(-diag, diag, spacing):
        if random.random() > density:
            continue
        p1 = (cx + nx*k - dx*diag/2, cy + ny*k - dy*diag/2)
        p2 = (cx + nx*k + dx*diag/2, cy + ny*k + dy*diag/2)
        line(draw, [p1, p2], fill=fill, width=width, jitter=.45)


def qr(draw, x, y, s=1.0):
    size = int(122*s)
    rect(draw, (x, y, x+size, y+size), fill=INK, width=2, jitter=.15)
    cell = size / 13
    blocks = [
        (0,0,4,4),(9,0,13,4),(0,9,4,13),
        (5,1,6,2),(7,1,8,3),(5,4,7,5),(8,5,10,6),
        (4,6,5,8),(6,7,8,9),(10,7,11,9),(5,10,7,11),
        (8,10,9,12),(11,10,12,11),(4,12,5,13),(10,12,13,13),
    ]
    for a,b,c,d in blocks:
        draw.rectangle((x+a*cell, y+b*cell, x+c*cell, y+d*cell), fill=INK)
    draw.text((x-2, y+size+8), 'сканировать', font=BODY_TINY, fill=MUTED)


def nozzle(draw, x, y, s=1.0, flow=True):
    rect(draw, (x, y, x+230*s, y+88*s), fill=INK, width=3, jitter=.55)
    hatch(draw, (x+12*s, y+10*s, x+218*s, y+80*s), angle=-42, spacing=max(9, int(15*s)), fill=PALE, density=.62)
    line(draw, [(x+60*s,y+88*s),(x+96*s,y+145*s),(x+134*s,y+145*s),(x+170*s,y+88*s)], fill=INK, width=3, jitter=.55)
    if flow:
        pts = []
        for i in range(48):
            t = i/47
            xx = x + (116 + 430*t)*s
            yy = y + (160 + 18*math.sin(t*math.tau*1.2))*s
            pts.append((xx, yy))
        line(draw, pts, fill=INK, width=3, jitter=1.0, passes=2)


def printer(draw, x, y, s=1.0):
    rect(draw, (x, y, x+280*s, y+220*s), fill=INK, width=3, jitter=.55)
    line(draw, [(x+36*s,y+38*s),(x+244*s,y+38*s)], fill=INK, width=3, jitter=.35)
    line(draw, [(x+62*s,y+38*s),(x+62*s,y+188*s)], fill=INK, width=2, jitter=.35)
    line(draw, [(x+222*s,y+38*s),(x+222*s,y+188*s)], fill=INK, width=2, jitter=.35)
    rect(draw, (x+118*s,y+60*s,x+166*s,y+92*s), fill=INK, width=2, jitter=.35)
    line(draw, [(x+142*s,y+92*s),(x+128*s,y+118*s),(x+156*s,y+118*s),(x+142*s,y+92*s)], fill=INK, width=2, jitter=.45)
    line(draw, [(x+48*s,y+188*s),(x+238*s,y+188*s)], fill=INK, width=3, jitter=.35)
    rect(draw, (x+94*s,y+134*s,x+188*s,y+176*s), fill=INK, width=2, jitter=.45)
    for i in range(5):
        yy = y+(138+i*8)*s
        line(draw, [(x+98*s,yy),(x+184*s,yy)], fill=INK, width=1, jitter=.35)


def mini_parts(draw, x, y, s=1.0):
    # cube
    a = 82*s
    p1 = [(x,y+40*s),(x+a,y+20*s),(x+a,y+112*s),(x,y+132*s),(x,y+40*s)]
    p2 = [(x,y+40*s),(x+34*s,y),(x+116*s,y+22*s),(x+a,y+20*s)]
    p3 = [(x+a,y+20*s),(x+116*s,y+22*s),(x+116*s,y+106*s),(x+a,y+112*s)]
    line(draw, p1, width=2, jitter=.45); line(draw, p2, width=2, jitter=.45); line(draw, p3, width=2, jitter=.45)
    hatch(draw, (x,y+16*s,x+116*s,y+132*s), angle=-25, spacing=max(8,int(13*s)), fill=PALE, density=.45)
    # gear
    cx, cy, r = x+205*s, y+78*s, 42*s
    pts = []
    for i in range(28):
        a0 = math.tau*i/28
        rr = r*(1 if i%2==0 else .80)
        pts.append((cx+math.cos(a0)*rr, cy+math.sin(a0)*rr))
    line(draw, pts+[pts[0]], width=2, jitter=.45)
    draw.ellipse((cx-r*.32, cy-r*.32, cx+r*.32, cy+r*.32), outline=INK, width=2)
    # bracket
    bx, by = x+300*s, y+18*s
    rect(draw, (bx,by,bx+98*s,by+118*s), fill=INK, width=2, jitter=.45)
    draw.ellipse((bx+18*s,by+18*s,bx+42*s,by+42*s), outline=INK, width=2)
    draw.ellipse((bx+58*s,by+76*s,bx+82*s,by+100*s), outline=INK, width=2)


def base(title, subtitle):
    im = Image.new('RGB', (CANVAS_W, CANVAS_H), BG)
    d = ImageDraw.Draw(im)
    d.text((72, 52), title, font=BODY_L, fill=INK)
    d.text((72, 103), subtitle, font=BODY_S, fill=MUTED)
    x0, y0 = 270, 225
    d.rounded_rectangle((x0-14, y0-14, x0+CARD_W+14, y0+CARD_H+14), radius=32, fill=(229,226,218))
    d.rounded_rectangle((x0, y0, x0+CARD_W, y0+CARD_H), radius=28, fill=CARD, outline=(203,203,196), width=2)
    # 12-column rhythm
    left = x0 + 74
    right = x0 + CARD_W - 74
    top = y0 + 64
    bottom = y0 + CARD_H - 64
    return im, d, x0, y0, left, right, top, bottom


def save(im, name):
    path = OUT / name
    im.save(path)
    return path


def card_a():
    im, d, x0, y0, left, right, top, bottom = base('UX/UI PRO MAX A', 'Hero nozzle: самый сильный premium-вариант, чистая иерархия')
    # left hero
    nozzle(d, left, top+74, 1.05)
    hatch(d, (left-30, top+20, left+520, bottom-35), angle=-38, spacing=18, fill=(232,232,228), density=.55)
    # brand block
    d.text((left+610, top+18), '3D Print', font=HAND_HERO, fill=INK)
    d.text((left+615, top+126), 'печать деталей на заказ', font=BODY_L, fill=INK)
    line(d, [(left+615, top+185), (right-30, top+185)], fill=INK, width=2)
    d.text((left+616, top+226), 'Прототипы  •  корпуса  •  макеты', font=BODY_M, fill=MUTED)
    # value chips
    chips = [('от 1 дня', BLUE), ('FDM / PETG / PLA', INK), ('по эскизу', INK)]
    cx = left+616
    for label, color in chips:
        tw, th = tbox(d, label, BODY_S)
        d.rounded_rectangle((cx, top+288, cx+tw+34, top+328), radius=18, outline=PALE, width=2)
        d.text((cx+17, top+296), label, font=BODY_S, fill=color)
        cx += tw + 54
    # contacts block with CTA
    d.text((left+616, bottom-172), 'Напиши в Telegram', font=BODY_L, fill=INK)
    d.text((left+616, bottom-122), '@telegram_shop', font=BODY_M, fill=BLUE)
    d.text((left+616, bottom-82), '+7 900 000-00-00', font=BODY_M, fill=INK)
    qr(d, right-132, bottom-155, .88)
    d.text((left, bottom-18), 'От идеи до готовой детали', font=HAND_SMALL, fill=INK)
    return save(im, 'ux_ui_pro_max_A_hero_nozzle.png')


def card_b():
    im, d, x0, y0, left, right, top, bottom = base('UX/UI PRO MAX B', 'Service grid: максимум понятности для клиента за 3 секунды')
    rect(d, (left, top, right, bottom), fill=INK, width=2, jitter=.15)
    d.text((left+38, top+36), 'Печатаем идеи', font=HAND_BIG, fill=INK)
    d.text((left+42, top+112), '3D-печать, моделирование, мелкие серии', font=BODY_M, fill=MUTED)
    printer(d, left+65, top+235, 1.45)
    # service matrix right
    sx = left + 545
    services = [
        ('01', 'Прототип', 'проверка формы и посадки'),
        ('02', 'Корпус', 'для электроники и DIY'),
        ('03', 'Деталь', 'замена сломанной детали'),
        ('04', 'Подарок', 'миниатюры и декор'),
    ]
    for i, (n, h, desc) in enumerate(services):
        yy = top + 214 + i*88
        d.rounded_rectangle((sx, yy, right-175, yy+63), radius=10, outline=PALE, width=2)
        d.text((sx+24, yy+13), n, font=HAND_SMALL, fill=BLUE)
        d.text((sx+88, yy+10), h, font=BODY_M, fill=INK)
        d.text((sx+88, yy+39), desc, font=BODY_XS, fill=MUTED)
    # footer nav/contact
    line(d, [(left+36, bottom-76), (right-160, bottom-76)], fill=INK, width=1)
    d.text((left+40, bottom-50), '@telegram_shop', font=BODY_S, fill=INK)
    d.text((left+290, bottom-50), '+7 900 000-00-00', font=BODY_S, fill=INK)
    d.text((left+580, bottom-50), 'город / доставка', font=BODY_S, fill=MUTED)
    qr(d, right-135, bottom-124, .76)
    return save(im, 'ux_ui_pro_max_B_service_grid.png')


def card_c():
    im, d, x0, y0, left, right, top, bottom = base('UX/UI PRO MAX C', 'Minimal master: дорогой, спокойный, почти студийный стиль')
    # central composition
    d.text((left+30, top+55), '3D', font=BODY_XL, fill=INK)
    d.text((left+120, top+36), 'мастерская', font=HAND_BIG, fill=INK)
    d.text((left+126, top+116), 'печать деталей, которых нет в магазине', font=BODY_M, fill=MUTED)
    line(d, [(left+30, top+188), (right-310, top+188)], fill=INK, width=2)
    mini_parts(d, left+45, top+270, 1.34)
    # right conversion panel
    panel = (right-275, top+48, right, bottom-44)
    d.rounded_rectangle(panel, radius=18, outline=INK, width=2)
    center_text(d, (panel[0]+20, panel[1]+30, panel[2]-20, panel[1]+95), 'что делаем', BODY_L, fill=INK)
    rows = ['детали', 'макеты', 'корпуса', 'прототипы']
    for i, txt in enumerate(rows):
        yy = panel[1] + 128 + i*52
        d.text((panel[0]+42, yy), f'• {txt}', font=BODY_S, fill=INK)
    line(d, [(panel[0]+36, panel[1]+360), (panel[2]-36, panel[1]+360)], fill=PALE, width=2)
    qr(d, panel[0]+76, panel[1]+390, .86)
    d.text((left+30, bottom-44), '@telegram_shop       +7 900 000-00-00', font=BODY_M, fill=INK)
    return save(im, 'ux_ui_pro_max_C_minimal_master.png')


def card_d():
    im, d, x0, y0, left, right, top, bottom = base('UX/UI PRO MAX D', 'Story split: слева процесс, справа оффер и контакт')
    # split layout
    split = left + 585
    line(d, [(split, top+42), (split, bottom-42)], fill=PALE, width=2)
    # process visual
    d.text((left+28, top+35), 'эскиз', font=HAND_MED, fill=INK)
    line(d, [(left+128, top+74), (left+264, top+74)], fill=LIGHT, width=1)
    d.text((left+310, top+35), 'печать', font=HAND_MED, fill=INK)
    line(d, [(left+430, top+74), (left+540, top+74)], fill=LIGHT, width=1)
    d.text((left+75, top+150), '1', font=HAND_BIG, fill=BLUE)
    mini_parts(d, left+140, top+180, .86)
    d.text((left+75, top+410), '2', font=HAND_BIG, fill=BLUE)
    printer(d, left+140, top+392, .86)
    # offer
    d.text((split+78, top+62), 'От идеи', font=HAND_BIG, fill=INK)
    d.text((split+82, top+138), 'до готовой детали', font=HAND_BIG, fill=INK)
    d.text((split+84, top+236), 'Поможем напечатать прототип, корпус, крепление или подарок.', font=BODY_M, fill=MUTED)
    d.rounded_rectangle((split+84, top+328, right-72, top+395), radius=16, outline=INK, width=2)
    center_text(d, (split+84, top+328, right-72, top+395), 'Заказать расчет', BODY_L, fill=INK)
    d.text((split+84, top+446), '@telegram_shop', font=BODY_M, fill=BLUE)
    d.text((split+84, top+490), '+7 900 000-00-00', font=BODY_M, fill=INK)
    qr(d, right-144, bottom-150, .86)
    return save(im, 'ux_ui_pro_max_D_story_split.png')

refs = [card_a(), card_b(), card_c(), card_d()]

# overview
sheet = Image.new('RGB', (2200, 1700), BG)
d = ImageDraw.Draw(sheet)
d.text((80, 56), 'UX/UI PRO MAX: визитка магазина 3D-печати', font=BODY_XL, fill=INK)
d.text((82, 116), 'Фокус: читаемость 90x50 мм, понятный CTA, QR, сетка, карандашная графика под будущий плоттер', font=BODY_M, fill=MUTED)
positions = [(80, 210), (1130, 210), (80, 930), (1130, 930)]
for p, (x, y) in zip(refs, positions):
    img = Image.open(p).convert('RGB')
    img.thumbnail((960, 620), Image.Resampling.LANCZOS)
    d.rounded_rectangle((x-16, y-16, x+img.width+16, y+img.height+54), radius=24, fill=(230,227,219))
    sheet.paste(img, (x, y))
    d.text((x, y+img.height+16), p.name, font=BODY_S, fill=INK)
overview = OUT / 'ux_ui_pro_max_overview.png'
sheet.save(overview)

# design system / decision doc
md = OUT / 'ux_ui_pro_max_design_system.md'
md.write_text('''# UX/UI PRO MAX для визитки 3D-печати

## Что исправлено по сравнению с первыми референсами

- Один главный смысл на карточку: не россыпь объектов, а hero-композиция.
- Четкая иерархия: бренд -> услуга -> доверие/выгода -> контакт/QR.
- QR всегда в предсказуемой зоне справа снизу или в отдельной панели.
- Контакты не прыгают по макету, а собраны в conversion-блок.
- Рукописный шрифт используется как акцент, а не для всего мелкого текста.
- Мелкий текст оставлен печатным, чтобы после плоттера он не превратился в кашу.
- Штриховка декоративная и направленная, без случайного шума.

## Варианты

1. `ux_ui_pro_max_A_hero_nozzle.png` - лучший премиальный вариант. Главный кандидат для финального G-code.
2. `ux_ui_pro_max_B_service_grid.png` - самый понятный коммерчески: сразу видно услуги.
3. `ux_ui_pro_max_C_minimal_master.png` - спокойный студийный вариант, хорошо для дорогого локального бренда.
4. `ux_ui_pro_max_D_story_split.png` - сильный UX: показывает путь "эскиз -> печать -> заказ".

## Рекомендация

Для плоттера и визитки я бы выбрал A.

Почему:
- сильный силуэт сопла;
- легко читается на 90x50 мм;
- не перегружен мелкими деталями;
- рукописный стиль есть, но контакты остаются читаемыми;
- можно красиво перевести в G-code: контур сопла, линия пластика, легкая штриховка, QR/контакты.

Если цель больше продавать услугу с первого взгляда, выбрать B.
''', encoding='utf-8')

print('created UX/UI pro max references:')
for p in refs + [overview, md]:
    print(p)
