import os
from PIL import Image
from config.settings import settings


class ImageProcessor:
    @staticmethod
    def preprocess_image(image_path: str) -> Image.Image:
        img = Image.open(image_path).convert("RGB")

        max_size = settings.OUTPUT_SIZE
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        return img

    @staticmethod
    def save_image(image: Image.Image, output_path: str):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        image.save(output_path, "JPEG", quality=95, optimize=True)
