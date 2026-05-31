# Plotter PDF CLI

`plotter_pdf` теперь ведётся как консольный проект для подготовки и отправки G-code на GRBL-плоттер под Windows. Десктопная оболочка и portable-build сценарии убраны из активной структуры репозитория. Основной рабочий контур: подготовка PDF/SVG/DOCX в G-code, калибровка, A4/A3 раскладка, A3-переворот второго прохода, превью и отправка в GRBL.

## Что оставлено

- CLI-конвертер и отправка на плоттер.
- Калибровка углами и отрисовка рамки рабочей зоны.
- Sheet-aware режимы `A4`, `A3`, `notebook`, `custom`.
- Логика двухпроходного `A3`, включая:
  - поворот второй части на `180°`;
  - пост-сдвиг второй части на `Y +4.0 мм`;
  - логи о применённом pass transform.
- Handwriting / Method3 pipeline для конспектов и текстовых страниц.
- Диагностика и восстановление Bluetooth SPP / RFCOMM.
- Пакетная подготовка документов из папки `1/`.

## Что убрано

- PySide6 UI и связанные `plotter_studio/ui/*`.
- Контроллер десктопного приложения и `QSettings`.
- Сценарии сборки portable EXE.
- Исторические тестовые output-папки в корне репозитория.

Рабочая папка [`1`](./1) не чистилась автоматически: там лежат ваши реальные пакеты, G-code и PDF-превью.

## Установка

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Минимум по среде:

- Windows 10/11
- Python 3.10+
- GRBL-плоттер по USB или Bluetooth SPP
- Inkscape, если нужен SVG/PDF export pipeline
- Microsoft Word, если нужны `.doc/.docx -> PDF`

## Быстрый старт

Показать доступные параметры:

```powershell
python main.py --help
```

Нарисовать 4 угловые метки калибровки:

```powershell
python main.py --calibrate-corners --com COM6
```

Нарисовать рамку рабочей области:

```powershell
python main.py --frame --com COM6
```

Подготовить G-code без отправки на плоттер:

```powershell
python main.py .\sample.pdf --preview --output .\sample_prepared.nc
```

Сразу отправить файл на плоттер:

```powershell
python main.py .\sample.pdf --com COM6 --sheet-format a4
```

## Структура проекта

```text
main.py
config/
scripts/
src/
  plotter_pdf_drawer.py
  send_grbl_file.py
  release_motors.py
  penlift_postprocess.py
  plotter_backend/
plotter_studio/
  core/
    protocol.py
    serial_worker.py
tests/
```

Ключевые модули:

- [`main.py`](./main.py) — короткая точка входа в CLI.
- [`src/plotter_pdf_drawer.py`](./src/plotter_pdf_drawer.py) — основной конвертер и оркестратор подготовки/рисования.
- [`plotter_studio/core/protocol.py`](./plotter_studio/core/protocol.py) — headless bridge для preview/draw/package сценариев.
- [`plotter_studio/core/serial_worker.py`](./plotter_studio/core/serial_worker.py) — headless worker без Qt, нужен пакетным скриптам.
- [`src/plotter_backend/`](./src/plotter_backend) — геометрия, sheet tiling, GRBL sender, machine helpers.

## Главная команда: `main.py` / `src/plotter_pdf_drawer.py`

Обе команды эквивалентны:

```powershell
python main.py ...
python src\plotter_pdf_drawer.py ...
```

### Что умеет

- Подготовить и отправить `PDF/SVG/FRW/CDW/DOC/DOCX`.
- Построить preview без реальной отправки.
- Выполнить калибровку углами.
- Нарисовать рамку активной рабочей зоны.
- Работать с профилями `A4`, `A3`, `custom`.
- Разбивать лист на pass-grid.
- Выполнять pencil wear test.
- Включать handwriting pipeline для конспектов.

### Основные режимы

- `--calibrate-corners`
  Рисует только 4 угловые метки. Используется перед листом или после смены позиции бумаги.

- `--frame`
  Рисует рамку активной области без подготовки документа.

- `input + --preview`
  Готовит `.nc`, `.svg`, `.pdf`, но не отправляет на плоттер.

- `input` без `--preview`
  Готовит и сразу отправляет G-code на плоттер.

- `--dry-run`
  Готовит только G-code и пишет его в указанный `--output`.

### Важные параметры

- `--com COM6`
  Явный COM-порт. Если не указан, используется автоопределение.

- `--sheet-format a4|a3|work|notebook|custom`
  Выбор листа внутри рабочей области.

- `--sheet-anchor center|lower_left|upper_left|lower_right|upper_right`
  Привязка листа внутри machine workspace.

- `--sheet-offset-x-mm` / `--sheet-offset-y-mm`
  Смещение листа относительно домашней точки.

- `--pass-cols`, `--pass-rows`, `--pass-col`, `--pass-row`
  Явное управление multi-pass раскладкой.

- `--plan-sheet`
  Показывает расчёт pass-plan и текущий pass.

- `--strict-1to1`
  Жёстко сохраняет реальный размер геометрии. Если лист не влезает, часть линий может быть обрезана.

- `--preview --open-preview`
  Готовит preview и открывает результат системным viewer.

- `--tool pen|pencil`
  Режим инструмента.

- `--handwriting`
  Включает handwriting pipeline для текста.

- `--handwriting-font`
  Шрифт для рукописного вывода.

- `--image-contours-mode off|word_only|always`
  Управляет извлечением контуров из растрового содержимого.

## Правила для A3 в 2 прохода

Это ключевая логика, которую важно не ломать:

1. `pass_01` рисуется как первая половина листа.
2. `pass_02` после подготовки автоматически разворачивается на `180°`.
3. После поворота `pass_02` дополнительно сдвигается на `Y +4.0 мм`.
4. Эта логика применяется внутри backend, а не вручную в G-code после генерации.

Актуальные правила описаны также в [`config/PLOTTER_CONTROL_RULES.md`](./config/PLOTTER_CONTROL_RULES.md).

## Консольные скрипты и что они делают

### `scripts\run_plotter_pdf_drawer.bat`

Универсальная Windows-обёртка над `src\plotter_pdf_drawer.py`.

Примеры:

```bat
scripts\run_plotter_pdf_drawer.bat --help
scripts\run_plotter_pdf_drawer.bat --calibrate-corners --com COM6
scripts\run_plotter_pdf_drawer.bat ".\sheet.pdf" --preview
```

### `scripts\calibrate_corners.bat`

Быстрый запуск калибровки 4 углами. Если порт не указан, backend сам ищет доступный COM.

```bat
scripts\calibrate_corners.bat
scripts\calibrate_corners.bat COM6
```

### `scripts\draw_work_area_frame.bat`

Быстрый запуск отрисовки рамки активной зоны.

```bat
scripts\draw_work_area_frame.bat --com COM6
```

### `scripts\draw_pdf_now.bat`

Прямой запуск подготовки/рисования документа через основной CLI.

```bat
scripts\draw_pdf_now.bat ".\task.pdf" --com COM6 --sheet-format a4
```

### `src\send_grbl_file.py`

Низкоуровневая отправка готового `.nc/.gcode` в GRBL. Использовать, если файл уже подготовлен и не нужен повторный preprocessing.

```powershell
python src\send_grbl_file.py COM6 115200 .\job.nc
python src\send_grbl_file.py COM6 115200 .\job.nc --sleep
```

Что делает:

- открывает COM;
- будит контроллер, если нужно;
- стримит G-code по GRBL character-count схеме;
- ждёт `Idle`;
- по желанию отпускает моторы и уводит в `$SLP`.

### `src\release_motors.py`

Отдельно поднимает инструмент и отпускает моторы без запуска нового задания.

```powershell
python src\release_motors.py COM6 115200
python src\release_motors.py COM6 115200 --sleep
```

### `scripts\release_motors.bat`

Windows-обёртка над `src\release_motors.py`.

### `src\penlift_postprocess.py`

Постобработка уже существующего XY G-code: добавляет команды подъёма/опускания пера, задержки и динамику по Z.

Пример:

```powershell
python src\penlift_postprocess.py .\raw.nc --output .\ready.nc --mode z --z-down 15 --z-up 0
```

Когда использовать:

- есть уже готовая геометрия, но нет логики pen-lift;
- нужен быстрый эксперимент с Z-параметрами;
- нужен pencil wear / jitter / short-travel merge.

### `scripts\gcode_to_svg_preview.py`

Строит SVG-превью из готового G-code, показывая только pen-down траектории.

```powershell
python scripts\gcode_to_svg_preview.py .\job.nc -o .\job.svg
```

Полезно для ручной сверки перед отправкой на плоттер.

### `scripts\method3_page_centerline.py`

Готовит single-line centerline SVG/PDF для одной страницы через Method3 pipeline. Нужен в первую очередь для рукописных конспектов и формул.

Что делает:

- при необходимости прогоняет `.doc/.docx` через Word в PDF;
- рендерит страницу в raster;
- прогоняет autotrace centerline;
- чистит и упрощает полилинии;
- сохраняет page-level SVG/PDF preview.

### `scripts\prepare_folder1_packages.py`

Основной пакетный скрипт для подготовки рабочих материалов из папки [`1`](./1). Именно он собирает `*_pack`, page-level PDF preview, `.nc`, `.gcode`, отчёты и summary.

Что делает:

- ищет исходные PDF в `1/`;
- различает техчертежи и TOE-конспекты;
- для техчертежей готовит A4/A3 раскладку;
- для `A3 pass_02` применяет встроенный flip + `Y +4 мм`;
- для TOE формирует рукописный layout по страницам;
- кладёт рядом финальные `.pdf`, `.nc`, `.gcode`, `summary.csv`, `report.json`.

Пример:

```powershell
python scripts\prepare_folder1_packages.py --only "Задача 7"
```

### `scripts\run_pdf_handwriting_acceptance.py`

Quality-gate для handwriting pipeline. Готовит preview страниц и считает метрики по сегментам, дублям и мелким артефактам.

Использовать, если меняете handwriting / Method3 pipeline и хотите увидеть регрессии до реальной отрисовки.

### `scripts\bt_spp_recovery.py`

Диагностика и мягкое восстановление Bluetooth SPP / RFCOMM для `BtWriter`.

Примеры:

```powershell
python scripts\bt_spp_recovery.py --preferred-port COM11
python scripts\bt_spp_recovery.py --preferred-port COM11 --attempt-soft-repair
```

Что показывает:

- живые serial-порты;
- Bluetooth SPP порты;
- ghost SPP порты;
- `RFCOMM Code 10`;
- доступный USB fallback;
- пошаговые recovery recommendations.

Подробная инструкция: [`config/BLUETOOTH_SPP_RECOVERY.md`](./config/BLUETOOTH_SPP_RECOVERY.md)

## Логи и артефакты

Во время preview/draw проект складывает временные артефакты в `_tmp/`:

- `latest_preview.nc`
- `latest_preview_vector.svg`
- `latest_preview_vector.pdf`
- `latest_draw.nc`
- `latest_draw_vector.svg`
- `latest_draw_vector.pdf`

Пакетная подготовка в `1/` создаёт рядом с документом:

- `*_pack\page_01.pdf`
- `*_pack\page_01.nc`
- `*_pack\page_01.gcode`
- `*_pack\logs\*.log.txt`
- `*_pack\report.json`
- `*_pack\summary.csv`

Логи pass-transform особенно важны для `A3 pass_02`: по ним видно, что был применён поворот на `180°` и дополнительный подъём на `4 мм`.

## Bluetooth и COM

Если `COM11`/`COM12` внезапно становятся ghost-портами:

1. Запустите диагностику:

```powershell
python scripts\bt_spp_recovery.py --preferred-port COM11
```

2. Если нужен мягкий repair:

```powershell
python scripts\bt_spp_recovery.py --preferred-port COM11 --attempt-soft-repair
```

3. Если Bluetooth SPP снова умер, но USB жив:
   продолжайте работу через USB COM-порт, пока не восстановите RFCOMM.

## Тесты

Полный прогон:

```powershell
python -m pytest -q
```

Старые hardware/Word/KOMPAS-зависимые тесты по умолчанию исключены через [`pytest.ini`](./pytest.ini).

## Принципы репозитория после очистки

- Основной интерфейс — CLI.
- Preview должен существовать рядом с итоговым G-code.
- Геометрические инварианты вроде `A3 pass_02 rotate 180 + Y+4 mm` фиксируются в backend и в документации.
- Новые автоматизации должны идти через `scripts/` и `src/`, без возврата к отдельному desktop UI.

## TOE Font-First Pipeline

Новый TOE pipeline теперь строится вокруг `font-first` маршрута:

- обычный текст идёт через рукописный векторный шрифт;
- формулы, короткие техобозначения и табличные значения идут печатным шрифтом;
- схемы и line-art стараются сохранять геометрию, а не переводиться в page-wide raster;
- fallback выбирается по профилю страницы и логируется с явной причиной.

Главный скрипт для одного варианта:

```powershell
python scripts\prepare_toe_handwriting_package.py --pdf TOE_Zadachi_1_2_Variant_25.pdf
python scripts\prepare_toe_handwriting_package.py --pdf TOE_Zadachi_1_2_Variant_25.pdf --resume
```

Что он создаёт:

- `*_pack/pages/page_XX.pdf`
- `*_pack/pages/page_XX.svg`
- `*_pack/pages/page_XX.nc`
- `*_pack/pages/page_XX.gcode`
- `*_pack/pages/page_XX_overlay.png`
- `*_pack/logs/page_XX.log.txt`
- `*_pack/report.json`
- `*_pack/summary.csv`
- `*_pack/final_overview.json`

Что теперь видно в логах и отчётах:

- `source_strategy`
- `graph_lineart`
- `selected_variant`
- `selected_reason`
- `fallback_threshold`
- `font_first_preferred`

Additional `selected_reason` values now used by the TOE pipeline:

- `reason=graph_rescue`
- `reason=region_rescue`

Массовая пересборка известных TOE-вариантов:

```powershell
python scripts\prepare_toe_variants.py --all-known --resume
python scripts\prepare_toe_variants.py --variant 4 --variant 25 --variant 26
```

Windows-обёртка:

```bat
scripts\prepare_toe_variants.bat --all-known --resume
```

TOE package audit:

```powershell
python scripts\audit_toe_packages.py --all-known --top-k 6
python scripts\audit_toe_packages.py --variant 11 --variant 25
```

Each `*_pack` now also gets:

- `audit.json`
- `audit.txt`
- `audit_hotspots/page_XX_hotspot.png`

Windows wrapper:

```bat
scripts\audit_toe_packages.bat --all-known --top-k 6
```

TOE package editor / manual overrides:

```powershell
python scripts\toe_package_editor.py --pdf TOE_Zadachi_1_2_Variant_11.pdf show --page 12
python scripts\toe_package_editor.py --pdf TOE_Zadachi_1_2_Variant_11.pdf set --page 12 --variant-label lineart_safe --font-label "Marck Script"
python scripts\toe_package_editor.py --pdf TOE_Zadachi_1_2_Variant_11.pdf rebuild
python scripts\toe_package_editor.py --pdf TOE_Zadachi_1_2_Variant_11.pdf suggest --write page_overrides.suggested.json
scripts\toe_package_editor.bat --pdf TOE_Zadachi_1_2_Variant_11.pdf show --page 12
```

Что делает editor-слой:

- хранит page-level manual overrides в `*_pack/page_overrides.json`;
- позволяет руками зафиксировать `variant_label` и `font_label` для конкретной страницы;
- не требует вручную лезть в `report.json`;
- позволяет точечно пересобрать пакет тем же `prepare_toe_handwriting_package.py`;
- умеет построить черновик suggestions из текущего `report.json`, если в пакете уже есть кандидат, доминирующий над выбранным.
