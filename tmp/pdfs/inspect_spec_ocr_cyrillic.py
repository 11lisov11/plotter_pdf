from pathlib import Path
import fitz
import numpy as np
from rapidocr import EngineType, LangRec, ModelType, OCRVersion, RapidOCR

engine = RapidOCR(params={
    "Rec.engine_type": EngineType.ONNXRUNTIME,
    "Rec.lang_type": LangRec.CYRILLIC,
    "Rec.model_type": ModelType.MOBILE,
    "Rec.ocr_version": OCRVersion.PPOCRV5,
})
src = Path(r"C:\plotter_pdf\Компьютерная графика\8 вариант\МЧ00.01.00.00 СП Клапан перепускной_pack\source.pdf")
with fitz.open(src) as doc:
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0), alpha=False, colorspace=fitz.csGRAY)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
result = engine(image)
txts = list(result.txts) if result.txts is not None else []
scores = list(result.scores) if result.scores is not None else []
boxes = list(result.boxes) if result.boxes is not None else []
print("lines", len(txts))
for box, text, score in zip(boxes, txts, scores):
    print(f"{float(score):.4f}\t{box.tolist()}\t{text}")
