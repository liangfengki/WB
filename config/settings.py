import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    ARK_API_KEY = os.getenv("ARK_API_KEY", "")
    ARK_BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    ARK_MODEL = os.getenv("ARK_MODEL", "doubao-seedream-5-0-260128")

    _yunwu_keys_str = os.getenv("YUNWU_API_KEYS", "")
    YUNWU_API_KEYS = [k.strip() for k in _yunwu_keys_str.split(",") if k.strip()]
    
    YUNWU_BASE_URL = os.getenv("YUNWU_BASE_URL", "https://api.yunwu.ai/v1")
    YUNWU_MODEL = os.getenv("YUNWU_MODEL", "gemini-3.1-flash-image-preview")

    OUTPUT_SIZE = int(os.getenv("OUTPUT_SIZE", 1024))
    CONCURRENCY = int(os.getenv("CONCURRENCY", 3))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))
    IMAGES_PER_PRODUCT = int(os.getenv("IMAGES_PER_PRODUCT", 3))

    OCR_LANG = os.getenv("OCR_LANG", "ch_sim")
    ENABLE_TEXT_OVERLAY = os.getenv("ENABLE_TEXT_OVERLAY", "true").lower() == "true"

    ENABLE_COLOR_HARMONIZE = os.getenv("ENABLE_COLOR_HARMONIZE", "true").lower() == "true"
    COLOR_HARMONIZE_STRENGTH = float(os.getenv("COLOR_HARMONIZE_STRENGTH", "0.3"))

    # 在 Vercel 环境中，必须使用 /tmp 目录
    _is_vercel = bool(os.getenv("VERCEL") or os.getenv("AWS_EXECUTION_ENV") or not os.access(".", os.W_OK))
    INPUT_DIR = os.getenv("INPUT_DIR", "/tmp/input" if _is_vercel else "./input")
    OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/tmp/output" if _is_vercel else "./output")
    LOG_DIR = os.getenv("LOG_DIR", "/tmp/logs" if _is_vercel else "./logs")
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/uploads" if _is_vercel else "./uploads")

    SCENE_PRESETS = {
        "简约白底": "纯白色背景，柔和均匀布光，无阴影，电商标准白底图风格，产品居中展示",
        "居家场景": "温馨现代家居客厅场景，自然窗光，木质桌面，绿植点缀，生活化氛围",
        "户外自然": "户外自然场景，阳光明媚，草地或花园背景，清新自然光，生机勃勃",
        "工作室": "专业摄影工作室场景，深灰色背景，聚光灯效果，高端产品展示风格",
        "北欧风格": "北欧简约风格场景，浅木色桌面，白色墙面，柔和自然光，极简美学",
        "节日氛围": "节日装饰场景，暖色调灯光，彩带和装饰物点缀，喜庆温馨氛围",
        "商务办公": "现代商务办公桌面场景，笔记本电脑旁，深色桌面，专业灯光",
        "厨房场景": "现代厨房场景，大理石台面，不锈钢厨具背景，明亮整洁",
    }

    PROMPT_TEMPLATE = """参考图中的产品，在不改变产品本身的前提下，更换适用于该产品的场景背景。
产品必须保持完全不变，保留产品的所有细节、颜色、光影和透视关系。
核心要求：
1. 图中原有的文字内容必须一字不差地保留，绝对不能改变、遗漏或翻译文字内容。
2. 字体的样式（包括字体设计、排版效果、颜色或艺术风格）必须进行改变，不要使用原图的字体样式，将其替换为更具设计感或符合新场景的美观字体。
整体改动要超过原图的60%，确保新背景与原图明显不同。
新背景场景：{background_prompt}
风格：专业电商产品摄影，高清8K，细节丰富，无畸变，适合俄罗斯Wildberries平台展示"""

    REFERENCE_PROMPT_TEMPLATE = """第一张图片是主图（需要换背景的人物/产品图），第二张图片是参考背景图。
请将第一张图片的背景替换为类似第二张图片风格和氛围的背景，同时保持第一张图片中主体（人物/产品）完全不变。
核心要求：
1. 主体（人物/产品）必须保持完全不变，保留所有细节、颜色、光影和透视关系。
2. 背景风格、色调、氛围要与第二张参考背景图一致。
3. 保持第一张主图的原始比例不变，不要裁剪或拉伸主体。
4. 主体与新背景的融合要自然，光影过渡合理。
风格：小红书风格，清新自然，色彩饱满，适合社交媒体展示"""

    UNDERWEAR_LAYERING_PROMPT_TEMPLATE = """第一张图片是内衣产品图（人台图/模特穿着图/白底图），第二张图片是目标模特图（通常为低胸装/U领等服装）。

请将第一张图片中的内衣精确叠穿到第二张图片的模特身上，生成一张模特真实穿着该内衣的效果图。

===== 【核心要求 Core_Requirements】（最高优先级）=====

1. 内衣细节精确保留：
   - 内衣的蕾丝花边、刺绣图案、纹理细节必须与原图完全一致，不得有任何模糊、简化或变形。
   - 内衣的颜色、材质质感（丝绸光泽、棉质哑光、蕾丝通透感等）必须精准还原。
   - 内衣的款式设计（肩带宽度、罩杯形状、钢圈轮廓、搭扣细节）必须与原图保持一致。
   - 内衣上的任何装饰物（蝴蝶结、水钻、吊坠等）必须精确保留。

2. 模特服装完整保留：
   - 模特原有的服装（低胸装/U领等）必须完全保留，不得被移除、替换或遮挡。
   - 模特的面部五官、发型、肤色、体型必须与原图完全一致。
   - 模特的配饰（项链、耳环等）必须保留。

3. 叠穿效果真实自然：
   - 内衣必须看起来是真实穿在模特身上的，有正确的透视关系和身体贴合度。
   - 内衣与外衣的层叠关系要合理——内衣从领口/袖口处自然露出，展现叠穿效果。
   - 内衣的褶皱、阴影必须与模特身体曲线和外衣褶皱相匹配。
   - 光影效果要统一——内衣上的光线方向、强度必须与模特图的光照环境一致。

4. 整体画面质量：
   - 生成图片必须是高清摄影级别，无噪点、无伪影。
   - 色彩过渡自然，内衣与外衣的边界清晰但不生硬。
   - 整体构图保持模特图的原始比例和视角。

===== 【禁止事项 Prohibited】=====
- 禁止移除或替换模特的任何衣物。
- 禁止改变模特的体型、面部特征或姿态。
- 禁止模糊或简化内衣的任何细节。
- 禁止添加原图中不存在的元素。
- 禁止对内衣进行风格化或卡通化处理。{user_prompt}"""

    XHS_MULTI_PROMPT_TEMPLATE = """第一张图片是主图（需要换背景的人物图），第二张图片是参考背景图。
请将第一张图片的背景替换为类似第二张图片风格和氛围的背景，严格遵循以下优先级指令：

===== 【胸型保持 Body_Preserver】（最高优先级） =====
必须保持人物胸部的形状、大小、比例与原图完全一致。
胸部轮廓必须与原图Source_Image保持一致，不得有任何变形或偏移。
胸部饱满度必须与原图Source_Image保持一致，不得增大或缩小。
胸部位置关系必须与原图Source_Image保持一致，不得上移、下移或偏移。
禁止对胸部区域进行任何形变。
禁止对胸部区域进行任何缩放。
禁止对胸部区域进行任何遮挡覆盖。
在任何姿态变化中，胸部区域必须保持原始形态不受影响。

===== 【敏感规避 Content_Moderator】 =====
对敏感部位（胸部、臀部、私密区域）进行合理遮挡处理，使其在生成图片中不直接暴露可见。
通过光影效果对敏感区域进行柔和遮挡。
通过道具（如丝巾、花束、手臂姿态）对敏感区域进行自然遮挡。
通过姿态调整（半身构图、侧面角度、俯拍角度）减少敏感部位的暴露面积。
避免正面全身直拍，优先采用半身构图或侧面角度。
遮挡方式不得与产品展示需求相矛盾，确保产品主体仍然清晰可见。

===== 【背景替换 Background】 =====
将人物背景替换为与第二张参考背景图风格、色调、氛围一致的场景。

===== 【光影匹配 Lighting_Match】（高优先级）=====
在替换背景前，必须先分析第二张参考背景图的整体光照环境：
1. 色温分析：判断参考图是暖色调（偏黄/橙，如夕阳、钨丝灯）还是冷色调（偏蓝，如阴天、日光灯），生成的人物整体色温必须与参考背景一致。
2. 光源方向：判断参考图的主光源方向（顶光、侧光、逆光、漫射光），人物身上的光影方向必须与背景光源匹配。
3. 亮度层次：参考背景的整体亮度（明亮/暗调/中调）必须反映在人物身上——明亮背景时人物不应过暗，暗调背景时人物不应过亮。
4. 色彩氛围：参考图的整体色彩倾向（如偏绿的自然场景、偏暖的室内灯光）必须渗透到人物的肤色和服装反光中，使人物看起来真正处于该环境中。
5. 对比度与饱和度：人物的对比度和饱和度应与参考背景保持一致的风格水准。

保持人物主体的五官、服装款式、配饰完全不变，仅调整光影和色调使之与新背景和谐统一。
保持原始图片比例不变，不要裁剪或拉伸人物主体。
人物与新背景的融合要自然，光影过渡合理，无明显拼接痕迹。
风格：小红书风格，清新自然，色彩饱满，适合社交媒体展示。

===== 【动作微调 Pose_Adjuster】 =====
对人物姿态进行适配新背景的微调，保持人物的面部特征、服装、配饰和整体身体朝向与原图一致。
仅允许调整肢体角度（如手臂、头部倾斜）和身体重心，不得改变人物的站/坐/蹲等基础姿态类型。
{pose_guidance}

{user_prompt}"""


settings = Settings()
