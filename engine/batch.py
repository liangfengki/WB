import os
import asyncio
from typing import List
from config.settings import settings
from utils.logger import logger
from processor.image import ImageProcessor
from processor.ocr import OCRProcessor
from processor.product_recognizer import ProductRecognizer
from api.seedream import SeedreamAPI


class BatchProcessor:
    def __init__(
        self,
        background_prompt: str,
        input_path: str = None,
        output_path: str = None,
        images_per_product: int = None,
        api_keys: list = None,
        base_url: str = None,
        model: str = None,
        progress_callback=None,
        auto_recognize: bool = False,
    ):
        self.background_prompt = background_prompt
        self.api = SeedreamAPI(api_keys=api_keys, base_url=base_url, model=model)
        self.ocr = OCRProcessor()
        self.recognizer = ProductRecognizer(api_keys=api_keys, base_url=base_url, model=model)
        self.failed_files = []
        self.input_path = input_path if input_path is not None else settings.INPUT_DIR
        self.output_path = output_path if output_path is not None else settings.OUTPUT_DIR
        self.images_per_product = images_per_product or settings.IMAGES_PER_PRODUCT
        self.progress_callback = progress_callback
        self.total_tasks = 0
        self.completed_tasks = 0
        self.auto_recognize = auto_recognize
        self.recognition_results = {}
        self._semaphore = None

    @property
    def semaphore(self):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.CONCURRENCY)
        return self._semaphore

    def get_image_files(self) -> List[str]:
        files = []
        if not os.path.exists(self.input_path):
            return files
        for filename in sorted(os.listdir(self.input_path)):
            if filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                files.append(os.path.join(self.input_path, filename))
        return files

    def _report_progress(self, filename: str, status: str, detail: str = ""):
        if self.progress_callback:
            self.progress_callback(filename, status, self.completed_tasks, self.total_tasks, detail)

    async def process_single_image(self, image_path: str):
        async with self.semaphore:
            return await self._process_single_image(image_path)

    async def _process_single_image(self, image_path: str):
        filename = os.path.basename(image_path)
        name_without_ext = os.path.splitext(filename)[0]

        try:
            logger.info(f"开始处理: {filename}")
            self._report_progress(filename, "processing", "预处理图片")

            img = ImageProcessor.preprocess_image(image_path)

            scenes = []
            if self.auto_recognize:
                self._report_progress(filename, "processing", "AI识别产品类型...")
                recognition = await self.recognizer.recognize_product(img)
                self.recognition_results[filename] = recognition
                product_type = recognition.get("product_type", "未知")
                product_name = recognition.get("product_name", "未知产品")
                logger.info(f"识别结果: {product_type} - {product_name}")
                self._report_progress(filename, "processing", f"识别为: {product_type} - {product_name}")
                scenes = ProductRecognizer.get_scenes_for_product(recognition)

            if not scenes and self.background_prompt:
                scenes = [self.background_prompt]

            if not scenes:
                scenes = ["专业电商产品摄影场景，柔和均匀布光，简约背景，高清8K"]

            try:
                self.ocr.extract_text(img)
            except Exception as e:
                logger.warning(f"OCR文本提取失败 (可能无法保留文字): {e}")

            saved_paths = []
            for scene_idx, scene_prompt in enumerate(scenes[:self.images_per_product]):
                full_prompt = settings.PROMPT_TEMPLATE.format(background_prompt=scene_prompt)

                self._report_progress(
                    filename,
                    "processing",
                    f"生成场景{scene_idx + 1}/{min(len(scenes), self.images_per_product)}: {scene_prompt[:30]}..."
                )

                generated_images = await self.api.generate_image(img, full_prompt)

                for gen_idx, gen_img in enumerate(generated_images):
                    final_img = self.ocr.overlay_text(gen_img)

                    if self.images_per_product == 1 and len(scenes) == 1:
                        output_filename = f"{name_without_ext}_new.jpg"
                    else:
                        output_filename = f"{name_without_ext}_scene{scene_idx + 1}.jpg"

                    output_file_path = os.path.join(self.output_path, output_filename)
                    ImageProcessor.save_image(final_img, output_file_path)
                    saved_paths.append(output_filename)

            self.completed_tasks += 1
            logger.info(f"处理完成: {filename} -> {', '.join(saved_paths)}")
            self._report_progress(filename, "completed", f"生成{len(saved_paths)}张图")
            return True, filename, saved_paths

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self.completed_tasks += 1
            logger.error(f"处理失败 {filename}: {str(e)}\n{error_details}")
            self.failed_files.append(filename)
            self._report_progress(filename, "failed", str(e))
            return False, filename, []

    async def process_all(self):
        os.makedirs(self.output_path, exist_ok=True)

        image_files = self.get_image_files()
        logger.info(f"发现 {len(image_files)} 张待处理图片")

        if not image_files:
            logger.warning("没有找到待处理图片")
            return []

        self.total_tasks = len(image_files)
        self.completed_tasks = 0

        tasks = [self.process_single_image(path) for path in image_files]
        results = []

        for future in asyncio.as_completed(tasks):
            result = await future
            results.append(result)

        success_count = sum(1 for r in results if r[0])
        logger.info(f"批量处理完成: 成功 {success_count}/{len(results)}")

        if self.failed_files:
            logger.info(f"失败文件: {', '.join(self.failed_files)}")

        return results