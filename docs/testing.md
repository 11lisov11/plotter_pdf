# Testing

Default test command never opens a real COM port:

```powershell
python -m pytest -q -m "not hardware_required and not word_required and not kompas_required and not build"
python -m coverage run -m pytest -q -m "not hardware_required and not word_required and not kompas_required and not build"
python -m coverage report -m --fail-under=55
```

Markers: `hardware_required`, `word_required`, `kompas_required`, `gui`, `slow`, `build`.
