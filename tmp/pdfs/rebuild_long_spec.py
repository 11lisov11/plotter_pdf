from pathlib import Path
from scripts import prepare_plotter_ready_new_algorithm as algorithm
pack = Path(r"C:\plotter_pdf\Компьютерная графика\8 вариант\МЧ00.01.00.00 СП Клапан перепускной_pack")
rows = algorithm._prepare_one_pack(pack, algorithm.Settings(drawing_mode="computer_graphics"))
print(f"rebuilt={len(rows)} ok={all(bool(row.get('ok')) for row in rows)}")
