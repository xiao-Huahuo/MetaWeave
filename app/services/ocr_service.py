from io import BytesIO
from typing import Optional, Iterable

import numpy as np
from PIL import Image

from app.core.logger import global_logger as logger


class OCRService:
    _ocr_instance = None

    @classmethod
    def _get_ocr(cls):
        if cls._ocr_instance is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except Exception as e:
                logger.error(f"缺少 rapidocr_onnxruntime, 无法进行 OCR: {e}")
                return None
            cls._ocr_instance = RapidOCR()
        return cls._ocr_instance

    @classmethod
    def recognize_image_path(cls, image_path: str) -> Optional[str]:
        try:
            image = Image.open(image_path).convert("RGB")
            return cls._run_ocr(image)
        except Exception as e:
            logger.error(f"OCR 读取图片失败 {image_path}: {e}")
            return None

    @classmethod
    def recognize_image_bytes(cls, image_bytes: bytes) -> Optional[str]:
        try:
            image = Image.open(BytesIO(image_bytes)).convert("RGB")
            return cls._run_ocr(image)
        except Exception as e:
            logger.error(f"OCR 读取图片字节失败: {e}")
            return None

    @classmethod
    def _run_ocr(cls, image: Image.Image) -> Optional[str]:
        ocr = cls._get_ocr()
        if not ocr:
            return None

        try:
            img_array = np.array(image)
            result, _ = ocr(img_array)
        except Exception as e:
            logger.error(f"OCR 执行失败: {e}")
            return None

        return cls._parse_ocr_result(result)

    @staticmethod
    def _parse_ocr_result(result: Iterable) -> Optional[str]:
        if not result:
            return None

        texts = []
        for item in result:
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    text_tuple = item[1]
                    if isinstance(text_tuple, (list, tuple)) and text_tuple:
                        text = text_tuple[0]
                        if text:
                            texts.append(str(text))
            except Exception:
                continue

        text = "\n".join(texts).strip()
        return text if text else None
