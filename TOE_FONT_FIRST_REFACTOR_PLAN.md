# TOE Font-First Refactor Plan

## Goal

Перевести TOE pipeline с page-level `raster_safe` и ad-hoc fallback-ов на устойчивую схему:

- обычный текст извлекается из PDF/SVG как текст и рисуется рукописным векторным шрифтом;
- формулы и короткие техобозначения рисуются печатным векторным шрифтом;
- схемы, графы, таблицы и line-art идут отдельным геометрическим маршрутом;
- raster fallback остаётся только для image-only контента, а не для всего текста страницы.

Ключевой принцип: **сначала шрифт и текстовая семантика, потом трассировка картинок**, а не наоборот.

## Почему это нужно

Текущие проблемы:

- текстовый контент слишком часто уходит в `raster_safe`, после чего страница становится зависимой от DPI, threshold и contour-mode;
- таблицы, графы и схемные подписи деградируют при full-page raster rewrite;
- правки page-level получаются хрупкими: одно улучшение таблицы может испортить общий стиль страницы;
- логика выбора варианта размазана между `prepare_toe_handwriting_package.py`, `prepare_folder1_packages.py` и `plotter_pdf_drawer.py`;
- профили шрифтов и routing policy сейчас зашиты строками и локальными эвристиками в нескольких местах.

## Целевое состояние

### 1. Content routing

Каждый кусок страницы должен попасть ровно в один из маршрутов:

- `body_text_handwriting`
  Обычный текст, абзацы, подписи, пояснения, заголовки.

- `print_formula_text`
  Формулы, обозначения вида `R1`, `I2`, `Uab`, короткие техподписи, табличные параметры, служебные строки `Рисунок 1.1`, `Таблица 1.1`.

- `vector_line_art`
  Векторные линии, таблицы, рамки, сетки, оси, стрелки, геометрия схем.

- `image_line_art_trace`
  Картинки, в которых реально нет текстовых узлов, но есть line-art/схема/граф.

- `image_formula_trace`
  Image-only формульные полосы, которые невозможно взять как текст.

- `last_resort_raster`
  Только для страниц или областей, где нет другого надёжного маршрута.

### 2. Font profiles

В проекте должны жить централизованные handwriting-профили:

- `Marck Script`: основной TOE default;
- `Neucha`: более ровный резерв;
- `Bad Script`: резервный живой почерк;
- `Caveat`: дополнительный мягкий резерв.

Печатные профили:

- `Times New Roman`: базовый formula/tech print route;
- `Cambria`: fallback для формул;
- `Arial`: последний системный fallback.

### 3. Selection policy

Пакетный генератор должен выбирать вариант в таком порядке:

1. `font-first vector text`
2. `font-first vector text + image trace`
3. `font-first vector text + formula trace`
4. `local region fallback`
5. `page-level raster fallback`

Page-level fallback не должен быть нормой для text-heavy страниц.

## Инварианты, которые нельзя ломать

- не трогать sheet geometry, A3 flip, calibration, GRBL sender;
- не ломать текущие `preview -> svg/pdf/nc/gcode` артефакты;
- не ломать root-level package layout;
- не терять текущий CLI workflow;
- не возвращать page-wide handwriting там, где текст уже можно взять как vector text;
- не пропускать формулы и таблицы ради общей similarity.

## Этапы

### Phase 0. Freeze and Audit

Цель:

- зафиксировать существующие проблемы и подготовить точку безопасного входа.

Задачи:

- собрать все точки, где сейчас задаются handwriting fonts, formula fonts и route flags;
- разделить политику TOE и общие backend-настройки;
- собрать перечень content classes, которые уже умеем распознавать.

Definition of done:

- создан отдельный policy-модуль;
- все жёстко зашитые строки вроде `Marck Script`, `Times New Roman`, `autotrace3` начинают жить централизованно.

### Phase 1. Centralize TOE policy

Цель:

- вынести font profiles и routing defaults из скриптов в backend policy layer.

Задачи:

- создать `src/plotter_backend/toe_font_policy.py`;
- хранить там handwriting-профили, formula font policy, known variant defaults;
- перевязать `prepare_toe_handwriting_package.py`;
- перевязать `prepare_folder1_packages.py`;
- добавить модульные тесты.

Definition of done:

- пакетные скрипты используют policy-модуль, а не локальные списки шрифтов и magic strings.

### Phase 2. Build content-class router

Цель:

- перестать принимать решения только по page-level similarity.

Задачи:

- ввести выделение классов: body, short tech token, formula, table cell, caption, figure label;
- добавить route decision helper, работающий от текста, размера шрифта, окружения и SVG tag context;
- отделить служебные строки `Рисунок`, `Таблица`, `Схема`, `Вариант` от body handwriting.

Definition of done:

- route выбирается не в одном `if` внутри rewrite, а отдельным helper с тестами.

### Phase 3. Table-aware rendering

Цель:

- таблицы должны рисоваться как таблицы, а не как page-level handwriting block.

Задачи:

- отделить table grid от table text;
- table grid всегда брать из vector geometry;
- table text всегда вести через print-font route, если исходный PDF даёт text spans;
- page-level raster fallback для таблиц использовать только если table text реально отсутствует.

Definition of done:

- `page_01` у TOE-variant-ов рисуется печатно в таблице и не ломает остальную страницу.

### Phase 4. Formula-first route

Цель:

- формулы перестают зависеть от handwriting route.

Задачи:

- ввести отдельный formula render route;
- формулы из text spans рисовать печатным font-first vector route;
- image-only formulas вести отдельно через formula trace, не смешивая с графами;
- добавить отдельные acceptance checks для formula-heavy страниц.

Definition of done:

- page-level formula loss становится исключением, а не нормой.

### Phase 5. Diagram and graph route

Цель:

- схемы и графы не должны ломаться из-за text rewrite.

Задачи:

- выделить graph/diagram content profile;
- сохранить line-art geometry как primary route;
- labels на схемах вести через print route или controlled handwriting route в зависимости от размера;
- для node circles, axes, thin connectors держать отдельные thresholds.

Definition of done:

- мелкие графовые подписи и узлы читаются без page-wide raster fallback.

### Phase 6. Region-level fallback

Цель:

- заменить page-wide fallback локальным fallback по областям.

Задачи:

- научиться строить region boxes для formula/table/diagram areas;
- применять fallback только к нужному фрагменту страницы;
- собирать финальную страницу из нескольких маршрутов.

Definition of done:

- исправление таблицы или формулы не ухудшает body text страницы.

### Phase 7. Candidate selection rewrite

Цель:

- selector должен выбирать лучший page assembly, а не лучший page raster.

Задачи:

- сравнивать кандидаты по content-class metrics;
- отдельно штрафовать потери таблиц, формул и схем;
- снизить влияние только общей `layout_similarity`;
- хранить в `report.json` content-aware reason of selection.

Definition of done:

- отчёт говорит не только "selected raster_safe", а почему выбран маршрут по контенту.

### Phase 8. Package validation and migration

Цель:

- прогнать уже существующие variant packs через новый pipeline.

Задачи:

- 4, 11, 14, 25, 26 проверить заново;
- сравнить старые и новые пакеты по отдельным страницам;
- обновить README и эксплуатационные документы;
- подготовить стабильный CLI entry для repackage.

Definition of done:

- можно взять новый variant PDF и прогнать его без ручной page-level починки.

## Acceptance criteria

### Functional

- body text в TOE рисуется рукописным vector font route;
- формулы и короткие техобозначения рисуются печатно;
- таблицы имеют печатный текст и отдельную сетку;
- схемы и графы не теряют thin geometry;
- fallback по возможности region-level, а не page-level.

### Engineering

- policy централизована;
- ключевые route decisions покрыты тестами;
- нет размножения hardcoded font rules по скриптам;
- все старые non-TOE сценарии остаются зелёными.

### Operational

- итоговый CLI остаётся прежним;
- пакеты продолжают содержать `pdf/svg/nc/gcode/overlay`;
- summary/report продолжают строиться.

## Test strategy

Автотесты:

- policy-модуль;
- table/figure/formula route helpers;
- candidate selection;
- package wiring;
- regression tests на известных weak pages.

Ручная проверка:

- `Variant 11 page_01`
- `Variant 14 page_01`
- `Variant 25 page_01`
- `Variant 26 page_01`
- formula-heavy pages
- graph-heavy pages

## Risk management

Главные риски:

- переусложнить page assembly;
- испортить уже рабочий direct-vector text route;
- начать смешивать print/handwriting так, что страница станет визуально рваной.

Снижение риска:

- делать маленькие этапы;
- хранить routing policy отдельно;
- не трогать geometry pipeline;
- проверять через targeted rebuilds и `pytest` после каждого этапа.

## Immediate execution order

Текущий рабочий порядок:

1. Phase 1: centralize TOE policy
2. Phase 2: extract content-class router
3. Phase 3: table-aware rendering
4. Phase 4: formula-first route

## Current status

- `[completed practical pass]` Phase 1: centralize TOE policy
- `[completed practical pass]` Phase 2: content-class router
- `[completed practical pass]` Phase 3: table-aware rendering
- `[completed practical pass]` Phase 4: formula-first route
- `[completed practical pass]` Phase 5: diagram and graph route
- `[completed practical pass]` Phase 6: region-level fallback
- `[completed practical pass]` Phase 7: candidate selection rewrite
- `[completed practical pass]` Phase 8: package validation and migration

## Progress Update 2026-03-30

Completed:

- Phase 1 foundation: centralized TOE font policy in backend module.
- Phase 2 foundation: content-class router for body / formula / table / caption / short tech text.
- Phase 3 practical pass: page_01 table-aware routing and text-rich font-first protection against unnecessary page-wide fallback.
- Phase 4 practical pass: formula/tech strings routed to print-font path in package rebuilds.
- Phase 5 practical pass: graph/diagram pages now expose `graph_lineart` source strategy and can switch to `graph_safe`.
- Phase 6 practical pass: local `region_safe` rescue can replace only weak regions instead of degrading the whole page.
- Phase 7 practical pass: candidate reports now store content-aware selection reasons.
- Phase 8 practical pass: variants `4`, `11`, `14`, `25`, `26` rebuilt with the current font-first pipeline.

Observed live package hits:

- `Variant 4 page_07` and `page_16` selected `region_safe`
- `Variant 11 page_08` selected `region_safe`
- `Variant 14 page_08` selected `region_safe`
- graph-heavy pages now report `source_strategy=graph_lineart` in page logs and reports

Operational status:

- Stable single-variant entry: `scripts/prepare_toe_handwriting_package.py`
- Stable multi-variant entry: `scripts/prepare_toe_variants.py` and `scripts/prepare_toe_variants.bat`
- Reports/logs now expose `source_strategy`, `selected_reason`, `fallback_threshold`, `font_first_preferred`
- Reports/logs can now emit `graph_lineart`, `reason=graph_rescue`, and `reason=region_rescue`
- Stable audit entry: `scripts/audit_toe_packages.py`, which writes `audit.json` and `audit.txt` into each TOE package
- Audit hotspot crops are now emitted into `audit_hotspots/page_XX_hotspot.png`
