# GRBL Plotter PDF Drawer

Desktop workflow for CH340 GRBL plotter (Windows) to draw PDF/SVG files:
- converts PDF via Inkscape,
- clips to working area,
- adds pen-lift logic,
- sends G-code to GRBL (COM6 by default).

## Что внутри

- `src/plotter_pdf_drawer.py` — GUI/CLI и конвертация PDF/SVG → G-code.
- `src/penlift_postprocess.py` — пост-обработка G-code с управлением пером.
- `src/send_grbl_file.py` — отправка файла в GRBL по COM.
- `config/PLOTTER_CONTROL_RULES.md` — единый регламент настроек станка.
- `config/axis_profile.json` — профиль осей.
- `data/gost_a4_frame.nc`, `data/gost_a4_zone.nc` — эталоны рамки/рабочей зоны.
- `scripts/*.bat` — запускающие утилиты:
  - `scripts/run_plotter_pdf_drawer.bat`
  - `scripts/draw_pdf_now.bat`
  - `scripts/draw_work_area_frame.bat`
  - `scripts/calibrate_corners.bat`
  - `scripts/penlift_postprocess.bat`

## Установка

- Python 3.10+
- Windows + COM-контроллер GRBL
- Inkscape установлен и доступен в PATH, либо установлен по пути:
  `C:\Program Files\Inkscape\bin\inkscape.com`
- Установка зависимостей:

```bat
pip install -r requirements.txt
```

## Быстрый старт

### 1) Быстрая загрузка файла

- Двойной клик `scripts/run_plotter_pdf_drawer.bat` и выберите PDF/SVG.

Или из CMD:

```bat
python src\plotter_pdf_drawer.py C:\path\to\file.pdf
```

### 2) Простой drag&drop

```bat
scripts\draw_pdf_now.bat C:\path\to\file.svg
```

### 3) Только рамка/калибровка

```bat
python src\plotter_pdf_drawer.py --frame
python src\plotter_pdf_drawer.py --calibrate-corners
```

## Команды по умолчанию

- COM: `COM6`
- Baud: `115200`
- Z-up: `0.0`
- Z-down: `11.9` (подбирается под ваш маркер/папочку)
- Рабочая зона: `X 0..180`, `Y -280..0`

Все правила по направлениям, нулю и последовательности команд — в `config/PLOTTER_CONTROL_RULES.md`.

## Безопасная отправка

- После передачи файла в GRBL скрипт снимает удержание моторов (`$1=0`), чтобы они не греялись в холостом режиме.
- Для диагностики перед запуском используйте ручной Connect/алгоритм в UGS или этот же пайплайн приложений.
