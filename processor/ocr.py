from PIL import Image, ImageDraw, ImageFont
from config.settings import settings
from utils.logger import logger

class OCRProcessor:
    def __init__(self):
        self.reader = None
        self.text_data = []

    def _ensure_reader(self):
        if self.reader is None:
            try:
                import easyocr
                import os
                model_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
                os.makedirs(model_dir, exist_ok=True)
                self.reader = easyocr.Reader([settings.OCR_LANG], gpu=False, model_storage_directory=model_dir)
            except ImportError:
                logger.warning("未安装 easyocr，OCR 功能被禁用。如果部署在 Vercel 这是正常现象。")
                self.reader = "DISABLED"

    def extract_text(self, image: Image.Image):
        if not settings.ENABLE_TEXT_OVERLAY:
            logger.info("未开启文字保留，跳过 OCR 提取")
            self.text_data = []
            return self.text_data

        self._ensure_reader()
        if self.reader == "DISABLED":
            self.text_data = []
            return self.text_data

        import numpy as np
        img_np = np.array(image)
        results = self.reader.readtext(img_np)

        self.text_data = []
        for bbox, text, confidence in results:
            if confidence > 0.5:
                x_min = int(min(point[0] for point in bbox))
                y_min = int(min(point[1] for point in bbox))
                x_max = int(max(point[0] for point in bbox))
                y_max = int(max(point[1] for point in bbox))

                self.text_data.append(
                    {
                        "text": text,
                        "x": x_min,
                        "y": y_min,
                        "width": x_max - x_min,
                        "height": y_max - y_min,
                        "confidence": confidence,
                    }
                )

        logger.info(f"识别到 {len(self.text_data)} 个文字区域")
        return self.text_data

    def overlay_text(self, image: Image.Image) -> Image.Image:
        if not settings.ENABLE_TEXT_OVERLAY or not self.text_data:
            return image

        draw = ImageDraw.Draw(image)

        for text_info in self.text_data:
            try:
                font_size = max(12, int(text_info["height"] * 0.8))
                font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", font_size)
            except Exception:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/STHeiti Light.ttc", font_size)
                except Exception:
                    font = ImageFont.load_default()

            draw.rectangle(
                [
                    text_info["x"],
                    text_info["y"],
                    text_info["x"] + text_info["width"],
                    text_info["y"] + text_info["height"],
                ],
                fill="white",
            )

            draw.text(
                (text_info["x"], text_info["y"]),
                text_info["text"],
                font=font,
                fill="black",
            )

        logger.info(f"已叠加 {len(self.text_data)} 个文字")
        return image
