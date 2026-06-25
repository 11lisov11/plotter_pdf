from pathlib import Path
p=Path(r'C:\plotter_pdf\_plotter_jobs\build_density_plus_grassdetail.py')
text=p.read_text(encoding='utf-8')
call='\n    add_grass_blades(paths, dens, reg)\n'
if call not in text:
    needle='    add_long_contours(paths, gray, dens)'
    idx=text.rfind(needle)
    if idx < 0:
        raise SystemExit('main add_long_contours call not found')
    text=text[:idx]+'    add_grass_blades(paths, dens, reg)\n'+text[idx:]
p.write_text(text, encoding='utf-8')
print('call inserted')
