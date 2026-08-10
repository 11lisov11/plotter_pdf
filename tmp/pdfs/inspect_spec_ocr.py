from pathlib import Path
import fitz
import cv2
import numpy as np
from src.plotter_backend import formula_image_ocr as ocr
src = Path(r"C:\plotter_pdf\Компьютерная графика\8 вариант\МЧ00.01.00.00 СП Клапан перепускной_pack\source.pdf")
with fitz.open(src) as doc:
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0), alpha=False, colorspace=fitz.csGRAY)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
result = ocr.ocr_formula_image(image)
print("image", image.shape)
if result is None:
    print("OCR_NONE")
else:
    print("confidence", result.confidence, "variant", result.variant, "lines", len(result.lines))
    for line in result.lines:
        print(f"{line.confidence:.4f}\t{line.bbox_px}\t{line.text}")
