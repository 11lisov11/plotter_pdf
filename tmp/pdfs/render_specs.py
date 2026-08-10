import fitz
items = [
    (r"C:\plotter_pdf\Компьютерная графика\8 вариант\Спецификация_pack\plot_preview.pdf", r"C:\plotter_pdf\tmp\pdfs\spec_short.png"),
    (r"C:\plotter_pdf\Компьютерная графика\8 вариант\МЧ00.01.00.00 СП Клапан перепускной_pack\plot_preview.pdf", r"C:\plotter_pdf\tmp\pdfs\spec_long.png"),
]
for src, dst in items:
    doc = fitz.open(src)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
    pix.save(dst)
    print(dst, page.rect, pix.width, pix.height)
