import os
import asyncio
from typing import List, Tuple
from config.settings import settings
from utils.logger import logger
from processor.image import ImageProcessor
from processor.ocr import OCRProcessor
from processor.product_recognizer import ProductRecognizer
from api.seedream import SeedreamAPI


def _build_opacity_section(opacity: int) -> str:
    """根据透明度百分比生成提示词段落，精确描述面料物理行为"""
    if opacity <= 5:
        return """===== 【外衣透明度：完全不透明 0%】 =====
外衣为厚实不透光面料（如牛仔、厚棉、羊毛、灯芯绒等），完全遮挡内衣。
- 外衣面料下不可看到任何内衣轮廓、颜色或纹理
- 内衣仅能从领口、袖口等开口处自然露出边缘
- 外衣颜色必须保持原图色彩，不受内衣颜色影响"""
    elif opacity <= 20:
        return f"""===== 【外衣透明度：微透 {opacity}%】 =====
外衣为普通厚度面料（如标准棉T恤、针织衫），仅在紧贴皮肤处有极微弱的轮廓暗示。
- 仅在内衣罩杯最凸起处，外衣面料因贴合而有极轻微的起伏轮廓
- 不可看到内衣的颜色、花纹或蕾丝纹理
- 外衣颜色必须100%保持原图，不受内衣颜色任何影响
- 效果类似于穿着普通T恤时隐约看到的轮廓线"""
    elif opacity <= 40:
        return f"""===== 【外衣透明度：隐约透 {opacity}%】 =====
外衣为略薄面料（如薄棉、轻薄针织、雪纺内衬），内衣轮廓隐约可见但颜色不明。
- 内衣的整体轮廓和罩杯形状可隐约辨认
- 内衣的颜色只能以极淡的阴影形式暗示，不可呈现真实颜色
- 内衣的蕾丝花纹不可见
- 外衣颜色以原图为主，内衣颜色不得向外衣扩散或渗透"""
    elif opacity <= 60:
        return f"""===== 【外衣透明度：半透明 {opacity}%】 =====
外衣为半透明面料（如薄雪纺、欧根纱、薄纱），内衣的轮廓和颜色朦胧可见。
- 内衣的轮廓清晰可辨，罩杯形状和肩带走向可见
- 内衣颜色以柔和、朦胧的方式透出，比实际颜色淡约50%
- 内衣蕾丝花纹以极模糊的纹理暗示形式可见
- 外衣自身的颜色和质感为主体，内衣只是底层朦胧影像
- 严禁内衣颜色向外衣区域扩散或染色"""
    elif opacity <= 80:
        return f"""===== 【外衣透明度：高度透明 {opacity}%】 =====
外衣为透明薄纱/网纱面料，内衣的花纹、颜色、结构清晰可见。
- 内衣的颜色、花纹、蕾丝细节清晰透过外衣可见
- 外衣仅保留薄纱质感、光泽和轻微的折射效果
- 外衣在褶皱处和边缘处透明度略低
- 内衣颜色应保持原色，但通过外衣纱层观察时带有轻微的纱层色调
- 外衣纱层与内衣之间有真实的层叠距离感"""
    else:
        return f"""===== 【外衣透明度：极度透明 {opacity}%】 =====
外衣极度透明近乎隐形（如极薄蝉翼纱、透明硬纱），内衣几乎完全展示。
- 内衣的颜色、纹理、结构完整可见，接近裸眼效果
- 外衣仅在边缘、褶皱、接缝处有轻微的面料存在感
- 外衣面料的微弱光泽和轻微折射为画面增添层次感
- 内衣颜色必须忠实还原，不受外衣色调影响"""


class BatchProcessor:
    def __init__(
        self,
        background_prompt: str,
        input_path: str = None,
        output_path: str = None,
        images_per_product: int = None,
        api_keys: list = None,
        progress_callback=None,
        auto_recognize: bool = False,
        ref_bg_path: str = None,
        ref_bg_files: list = None,
        xhs_multi_mode: bool = False,
        underwear_layering_mode: bool = False,
        underwear_files: list = None,
        model_files: list = None,
        generations_per_source: int = 1,
        user_prompt: str = "",
        enable_color_harmonize: bool = True,
        layering_style: str = "lace_full",
        material: str = "lace",
        opacity: int = 30,
        auto_mode: bool = False,
        xhs_style: str = "",
        xhs_view: str = "",
        xhs_action: str = "",
    ):
        self.background_prompt = background_prompt
        self.api = SeedreamAPI(api_keys=api_keys)
        self.ocr = OCRProcessor()
        self.recognizer = ProductRecognizer(api_keys=api_keys)
        self.failed_files = []
        self.input_path = input_path if input_path is not None else settings.INPUT_DIR
        self.output_path = output_path if output_path is not None else settings.OUTPUT_DIR
        self.images_per_product = images_per_product or settings.IMAGES_PER_PRODUCT
        self.progress_callback = progress_callback
        self.total_tasks = 0
        self.completed_tasks = 0
        self.auto_recognize = auto_recognize
        self.recognition_results = {}
        self.ref_bg_path = ref_bg_path
        self.ref_bg_files = ref_bg_files
        self.xhs_multi_mode = xhs_multi_mode
        self.underwear_layering_mode = underwear_layering_mode
        self.underwear_files = underwear_files or []
        self.model_files = model_files or []
        self.generations_per_source = generations_per_source
        self.user_prompt = user_prompt
        self.enable_color_harmonize = enable_color_harmonize
        self.layering_style = layering_style
        self.material = material
        self.opacity = opacity
        self.auto_mode = auto_mode
        self.xhs_style = xhs_style
        self.xhs_view = xhs_view
        self.xhs_action = xhs_action
        self._xhs_analysis_cache = {}
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

    async def _process_xhs_multi(self) -> List[Tuple[bool, str, list]]:
        """XHS 多图模式处理流程"""
        from engine.pairing import PairingEngine, PairingResult
        from engine.prompt_builder import PromptBuilder

        source_files = self.get_image_files()
        if not source_files:
            logger.warning("没有找到待处理的人物图")
            return []

        ref_files = self.ref_bg_files or []
        if not ref_files:
            logger.error("参考背景图列表为空，无法进行 XHS 多图模式处理")
            return []

        engine = PairingEngine(
            source_files=source_files,
            reference_files=ref_files,
            generations_per_source=self.generations_per_source,
        )
        pairings = engine.generate_pairings()
        self.total_tasks = len(pairings)
        self.completed_tasks = 0

        logger.info(f"XHS 多图模式: {len(source_files)} 张人物图 × {self.generations_per_source} 次生成 = {self.total_tasks} 个任务")

        # 并发处理所有配对
        tasks = [self._process_single_pairing(p) for p in pairings]
        results = []
        for future in asyncio.as_completed(tasks):
            result = await future
            results.append(result)

        success_count = sum(1 for r in results if r[0])
        logger.info(f"XHS 多图模式处理完成: 成功 {success_count}/{len(results)}")

        if self.failed_files:
            logger.info(f"失败文件: {', '.join(self.failed_files)}")

        return results

    async def _process_single_pairing(self, pairing) -> Tuple[bool, str, list]:
        """处理单个配对任务"""
        async with self.semaphore:
            from engine.prompt_builder import PromptBuilder

            output_filename = pairing.output_filename
            try:
                logger.info(f"开始处理配对: {pairing.source_filename} + {pairing.reference_filename} -> {output_filename}")
                self._report_progress(pairing.source_filename, "processing", f"配对处理: {pairing.reference_filename}")

                # 加载源图和参考图
                source_img = ImageProcessor.preprocess_image(pairing.source_path)
                ref_img = ImageProcessor.preprocess_image(pairing.reference_path)

                # 自动模式：AI 分析源图推荐最佳风格+构图（带缓存）
                if self.auto_mode and self.xhs_multi_mode:
                    cache_key = pairing.source_path
                    if cache_key in self._xhs_analysis_cache:
                        analysis = self._xhs_analysis_cache[cache_key]
                    else:
                        from processor.xhs_analyzer import XHSStyleAnalyzer
                        analyzer = XHSStyleAnalyzer(api_keys=self.api.api_keys if hasattr(self.api, 'api_keys') else None)
                        analysis = await analyzer.analyze(source_img)
                        self._xhs_analysis_cache[cache_key] = analysis
                    style_key = analysis.get("recommended_style", "fresh_natural")
                    view_key = analysis.get("recommended_view", "front")
                    action_key = analysis.get("recommended_action", "standing")
                    self._report_progress(
                        pairing.source_filename, "processing",
                        f"AI分析完成: {analysis.get('reasoning', '')}"
                    )
                else:
                    style_key = self.xhs_style
                    view_key = self.xhs_view
                    action_key = self.xhs_action

                # 构建提示词
                prompt = PromptBuilder.build_xhs_multi_prompt(
                    user_prompt=self.user_prompt,
                    scene_keywords=[],
                    style_key=style_key,
                    view_key=view_key,
                    action_key=action_key,
                )

                # 调用 API: Source_Image 作为第一张图, Reference_Image 作为第二张图
                generated_images = await self.api.generate_image(
                    source_img, prompt, ref_bg_image=ref_img
                )

                # 保存输出
                output_file_path = os.path.join(self.output_path, output_filename)
                ImageProcessor.save_image(generated_images[0], output_file_path)

                self.completed_tasks += 1
                logger.info(f"配对处理完成: {output_filename}")
                self._report_progress(pairing.source_filename, "completed", f"生成: {output_filename}")
                return (True, pairing.source_filename, [output_filename])

            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                self.completed_tasks += 1
                logger.error(f"配对处理失败 {pairing.source_filename} + {pairing.reference_filename}: {str(e)}\n{error_details}")
                self.failed_files.append(output_filename)
                self._report_progress(pairing.source_filename, "failed", str(e))
                return (False, pairing.source_filename, [])

    async def _process_underwear_layering(self) -> List[Tuple[bool, str, list]]:
        """内衣叠穿模式处理流程：将内衣图叠穿到模特图上"""
        if not self.underwear_files:
            logger.error("内衣图列表为空，无法进行内衣叠穿模式处理")
            return []

        if not self.model_files:
            logger.error("模特图列表为空，无法进行内衣叠穿模式处理")
            return []

        # 构建配对：每张内衣图 × 每张模特图 × 生成数量
        pairings = []
        for uw_idx, uw_path in enumerate(self.underwear_files):
            uw_name = os.path.splitext(os.path.basename(uw_path))[0]
            for md_idx, md_path in enumerate(self.model_files):
                md_name = os.path.splitext(os.path.basename(md_path))[0]
                for gen_idx in range(self.generations_per_source):
                    if self.generations_per_source == 1:
                        output_filename = f"{uw_name}_on_{md_name}.jpg"
                    else:
                        output_filename = f"{uw_name}_on_{md_name}_{gen_idx + 1}.jpg"
                    pairings.append({
                        "underwear_path": uw_path,
                        "underwear_filename": os.path.basename(uw_path),
                        "model_path": md_path,
                        "model_filename": os.path.basename(md_path),
                        "output_filename": output_filename,
                    })

        self.total_tasks = len(pairings)
        self.completed_tasks = 0

        logger.info(f"内衣叠穿模式: {len(self.underwear_files)} 张内衣图 × {len(self.model_files)} 张模特图 × {self.generations_per_source} 次生成 = {self.total_tasks} 个任务")

        # 并发处理所有配对
        tasks = [self._process_single_underwear_pairing(p) for p in pairings]
        results = []
        for future in asyncio.as_completed(tasks):
            result = await future
            results.append(result)

        success_count = sum(1 for r in results if r[0])
        logger.info(f"内衣叠穿模式处理完成: 成功 {success_count}/{len(results)}")

        if self.failed_files:
            logger.info(f"失败文件: {', '.join(self.failed_files)}")

        return results

    async def _process_single_underwear_pairing(self, pairing: dict) -> Tuple[bool, str, list]:
        """处理单个内衣叠穿配对任务"""
        async with self.semaphore:
            output_filename = pairing["output_filename"]
            try:
                logger.info(f"开始内衣叠穿: {pairing['underwear_filename']} + {pairing['model_filename']} -> {output_filename}")
                self._report_progress(
                    pairing["underwear_filename"], "processing",
                    f"叠穿处理: {pairing['model_filename']}"
                )

                # 加载内衣图和模特图
                underwear_img = ImageProcessor.preprocess_image(pairing["underwear_path"])
                model_img = ImageProcessor.preprocess_image(pairing["model_path"])

                # 自动模式：AI 分析并选择最佳配置
                if self.auto_mode:
                    from processor.underwear_analyzer import UnderwearAnalyzer
                    analyzer = UnderwearAnalyzer(api_keys=self.api.api_keys if hasattr(self.api, 'api_keys') else None)
                    analysis = await analyzer.analyze_pair(underwear_img, model_img)
                    style_key = analysis.get("recommended_style", "lace_full")
                    material_key = analysis.get("recommended_material", "lace")
                    opacity_val = analysis.get("recommended_opacity", 30)
                    self._report_progress(
                        pairing["underwear_filename"], "processing",
                        f"AI分析完成: {analysis.get('reasoning', '')}"
                    )
                else:
                    style_key = self.layering_style
                    material_key = self.material
                    opacity_val = self.opacity

                # 构建提示词
                preset = settings.LAYERING_STYLE_PRESETS.get(style_key, settings.LAYERING_STYLE_PRESETS["lace_full"])
                style_section = preset["prompt_section"]
                material_preset = settings.LAYERING_MATERIAL_PRESETS.get(material_key, settings.LAYERING_MATERIAL_PRESETS["lace"])
                material_section = material_preset["prompt_section"]
                opacity_section = _build_opacity_section(opacity_val)
                prompt = settings.UNDERWEAR_LAYERING_PROMPT_TEMPLATE.format(
                    user_prompt=self.user_prompt,
                    style_section=style_section,
                    material_section=material_section,
                    opacity_section=opacity_section,
                )

                # 调用 API: 内衣图作为 reference_image, 模特图作为 ref_bg_image
                color_isolation_system = (
                    "You are a professional fashion photography compositor. "
                    "CRITICAL RULE: Maintain strict color isolation between layers. "
                    "The underwear's colors must NEVER bleed, transfer, or contaminate the outer clothing. "
                    "The outer clothing must retain 100% of its original colors from the model photo. "
                    "Any color bleeding or contamination is a critical failure. "
                    "Focus on realistic fabric layering with zero color transfer between garments."
                )
                generated_images = await self.api.generate_image(
                    underwear_img, prompt, ref_bg_image=model_img,
                    system_message=color_isolation_system
                )

                # 保存输出
                output_file_path = os.path.join(self.output_path, output_filename)
                ImageProcessor.save_image(generated_images[0], output_file_path)

                self.completed_tasks += 1
                logger.info(f"内衣叠穿完成: {output_filename}")
                self._report_progress(pairing["underwear_filename"], "completed", f"生成: {output_filename}")
                return (True, pairing["underwear_filename"], [output_filename])

            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                self.completed_tasks += 1
                logger.error(f"内衣叠穿失败 {pairing['underwear_filename']} + {pairing['model_filename']}: {str(e)}\n{error_details}")
                self.failed_files.append(output_filename)
                self._report_progress(pairing["underwear_filename"], "failed", str(e))
                return (False, pairing["underwear_filename"], [])

    async def process_all(self):
        os.makedirs(self.output_path, exist_ok=True)

        # 内衣叠穿模式分发
        if self.underwear_layering_mode:
            return await self._process_underwear_layering()

        # XHS 多图模式分发
        if self.xhs_multi_mode:
            return await self._process_xhs_multi()

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