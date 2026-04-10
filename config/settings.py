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


settings = Settings()
