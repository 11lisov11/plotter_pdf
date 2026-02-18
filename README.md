# Plotter Studio

Современное desktop-приложение для GRBL-плоттера (Windows 10/11):
- UI на **PySide6** (русский интерфейс, светлая/тёмная тема),
- workflow: **Подключение -> Калибровка -> Файл -> Рисование -> Сервис**,
- сворачиваемый лог-дровер, статус-бар и аварийная отмена.

## Запуск

### Вариант 1: Python (dev)

```bat
pip install -r requirements.txt
python main.py
```

### Вариант 2: готовый EXE (portable)

После сборки запустите:

```text
dist\PlotterStudio.exe
```

Ничего устанавливать не нужно, админ-права не требуются.

## Сборка portable EXE

### Быстро (bat)

```bat
build_windows.bat
```

### Через PowerShell

```powershell
.\build_windows.ps1
```

Что делает сборка:
1. создаёт `.venv`,
2. ставит зависимости + `pyinstaller`,
3. собирает `PlotterStudio.exe` (`--onefile --noconsole`),
4. кладёт результат в `dist\`,
5. собирает `dist\PlotterStudio-portable.zip`.

## Где хранятся логи и настройки

Приложение использует `QSettings` + JSON snapshot.

- Логи:
  - `%APPDATA%\PlotterStudio\logs\plotter_studio.log`
- Снимок последних настроек:
  - `%APPDATA%\PlotterStudio\last_state.json`

## Горячие клавиши

- `Ctrl+O` — выбрать файл
- `Ctrl+Enter` — старт рисования
- `Ctrl+Shift+Enter` — подготовить и открыть предпросмотр (SVG)
- `Esc` — стоп/отмена текущей операции
- `Ctrl+L` — показать/скрыть лог

## Структура проекта

```text
plotter_studio/
  main.py
  core/
    plotter_controller.py
    serial_worker.py
    protocol.py
    settings.py
  ui/
    main_window.py
    theme.py
    pages/
      connection_page.py
      calibration_page.py
      file_page.py
      manual_page.py
      logs_page.py
    widgets/
      segmented_control.py
      status_pill.py
      toast.py
  assets/
    icon.ico
    icon.png
```

## Что сохранено из функционала

- COM подключение/скан/подключить/отключить,
- выбор инструмента (`pen`/`pencil`),
- калибровка 4 угла + рамка активной зоны,
- предпросмотр траектории перед отправкой (SVG),
- расширенная настройка активной зоны: привязка, смещение XY,
- A3 в 2 прохода по X (выбор прохода 1/2 или 2/2),
- загрузка PDF/SVG/FRW/CDW/DOC/DOCX и отправка на плоттер,
- тест износа карандаша,
- ручные команды Z (вверх/вниз, шаг, feed),
- отпуск моторов,
- кнопка стоп/отмена.

## Тесты

```bat
python -m unittest discover -s tests -p "test_*.py"
```

## Важно

- Новый UI использует существующий backend (`src/plotter_pdf_drawer.py`) через контроллер.
- Для `DOC/DOCX` требуется установленный Microsoft Word (конвертация через COM в PDF).
- Протокол команд плоттера не менялся.
- Legacy-скрипты из `src/` и `scripts/` сохранены для обратной совместимости.
