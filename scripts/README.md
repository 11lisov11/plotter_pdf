# Plotter script map

Canonical entry point:

```powershell
python scripts\prepare_plotter_package.py --mode geometry --sheet auto
python scripts\prepare_plotter_package.py --mode graphics --sheet auto --variant "9 вариант"
python scripts\prepare_plotter_package.py --mode copy --sheet a4 drawing.pdf
python scripts\prepare_plotter_package.py --mode photo --sheet a4 фото.jpg --photo-quality normal
python scripts\prepare_plotter_package.py --mode copy --sheet a2 drawing.pdf
```

Modes:

- `geometry` / `1`: начертательная геометрия. Uses `prepare_nachert_packages.py`.
- `graphics` / `2`: компьютерная графика. Uses `prepare_computer_graphics_variants.py`.
- `copy` / `3`: полная копия PDF без правил рамок CG/Начерт. Text is converted to outlines, so letters are hollow/contour-like.
- `photo` / `4`: photo-to-plotter package. Use `--photo-quality fast|normal|detailed`.

Common sheet flag:

- `--sheet auto`: keep source-driven format decisions.
- `--sheet a4`: A4 intent/profile.
- `--sheet a3`: A3 intent/profile.
- `--sheet a2`: A2 intent/profile. The confirmed drawable window is
  `390x580 mm`; full-size placement and clipping are controlled by the
  `a2_corexy` machine profile.

Legacy/internal engines:

- `prepare_nachert_packages.py`: batch builder for `Начерт`.
- `prepare_computer_graphics_variants.py`: batch builder for `Компьютерная графика`.
- `prepare_plotter_ready_new_algorithm.py`: shared clean plotter publishing engine.
- `prepare_photo_plot_package.py`: standalone photo engine.

Use `--plan-only` before long runs:

```powershell
python scripts\prepare_plotter_package.py --mode graphics --sheet auto --variant "9 вариант" --plan-only
```
