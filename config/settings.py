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

    UNDERWEAR_LAYERING_PROMPT_TEMPLATE = """第一张图片是内衣产品图（人台图 / 白底图 / 模特图），第二张图片是目标模特穿搭图（低胸、U领、方领、吊带等上衣）。

请将第一张图片中的内衣，以"真实内搭"的方式精准叠穿到第二张模特的衣服内部，只露出自然的蕾丝边缘与罩杯上沿，生成一张超真实模特试穿效果图。

【核心目标】
让画面看起来像模特原本就穿着这件内衣拍摄，呈现自然高级的"内衣叠穿"视觉效果，而不是后期拼贴。

【重点要求】

1. 内衣必须完整保留原始设计
- 保留原内衣全部细节：
  - 蕾丝纹理
  - 花纹刺绣
  - 罩杯结构
  - 钢圈轮廓
  - 面料透明感
  - 缝线与材质
  - 肩带粗细与颜色
- 禁止AI重新设计内衣
- 禁止改变颜色
- 禁止模糊蕾丝细节

2. 模特主体必须完全保留
- 保持原模特：
  - 脸部
  - 发型
  - 身材
  - 姿势
  - 原有服装
  - 光影
- 不允许改变人物长相
- 不允许改变服装版型

3. 真实"内搭"逻辑（非常重要）
- 内衣是"穿在衣服里面"的状态
- 只允许从领口自然露出蕾丝边缘
- 内衣肩带必须隐藏在衣服内部，不允许露出肩带
- 内衣罩杯边缘与衣服领口自然贴合
- 内衣必须符合胸部受力结构
- 必须有真实布料压迫感
- 必须有自然阴影与褶皱
- 不允许悬浮感
- 不允许穿模
- 不允许出现"贴图感"

4. 光影一致
- 内衣光线方向必须与模特照片一致
- 保持相同曝光与色温
- 保持真实摄影质感
- 保持自然景深与高光反射

5. 成片风格
ultra realistic, photorealistic, luxury lingerie layering, hidden bra straps, lace bra under low-cut top, natural fabric interaction, realistic lace texture, cinematic sunlight, premium fashion photography, commercial e-commerce quality, soft shadow, realistic cloth folds, editorial style, high detail, natural cleavage, seamless compositing

【严格禁止】
- 禁止露出肩带
- 禁止修改人物脸部
- 禁止改变身材
- 禁止AI重绘内衣花纹
- 禁止卡通感
- 禁止塑料皮肤
- 禁止低清晰度
- 禁止出现AI拼接痕迹
- 禁止新增不存在的服装结构

最终效果要求：
像真实时尚穿搭摄影，内衣只是作为高级蕾丝内搭自然露出，肩带完全藏在衣服内部，整体干净、真实、高级。{user_prompt}"""

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
