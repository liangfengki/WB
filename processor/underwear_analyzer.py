import base64
import json
import aiohttp
import itertools
from io import BytesIO
from PIL import Image
from config.settings import settings
from utils.logger import logger


ANALYSIS_PROMPT = """你是一位专业的时尚穿搭顾问和内衣搭配专家。请仔细分析以下两张图片：

第一张图：内衣产品图
第二张图：模特穿搭图

请根据两张图的实际内容，推荐最佳的内衣叠穿效果配置。

【分析要求】
1. 分析内衣：识别内衣的类型（文胸/运动内衣/无痕内衣/三角杯/抹胸等）、材质（蕾丝/光面缎面/棉质/运动面料/刺绣等）、颜色（精确描述主色和辅色）、设计特点
2. 分析模特图：识别领口类型（深V/浅V/圆领/方领/高领/衬衫领/吊带等）、面料厚薄（薄纱/棉质/丝绸/厚实等）、颜色（精确描述外衣颜色）
3. 特别注意：分析内衣颜色与外衣颜色的对比度和协调性，判断是否容易出现颜色偏移问题
4. 根据分析结果推荐最佳叠穿配置

【叠穿风格选项】
- lace_full（大面积展示）：适合大领口/V领，内衣大面积从领口露出。适合内衣颜色与外衣颜色对比明显的搭配
- lace_peek（微露边缘）：适合小领口/高领/衬衫，只微微露出一丝内衣边缘。颜色偏移风险最低
- see_through（透视薄纱）：适合模特图面料较薄的情况，内衣透过薄纱若隐若现。需要注意颜色隔离
- half_dressed（半脱半穿）：外衣从一侧肩膀滑落，内衣半遮半掩
- strap_slipped（肩带滑落）：内衣肩带从一侧滑落，性感慵懒风
- subtle_hint（若隐若现）：适合略薄但不透明的面料，内衣在下方隐约透出

【材质选项】
- lace（蕾丝/镂空/网纱）
- smooth（光面/缎面/丝滑）
- cotton（棉质/日常舒适）
- sports（运动/无痕/背心式）
- embroidered（刺绣/提花/浮雕）

【透明度】0-100的整数，根据模特图面料厚薄判断：
- 厚实面料（牛仔/厚棉/羊毛） → 0-10
- 普通面料（标准棉T恤/针织） → 10-25
- 略薄面料（薄棉/轻薄针织） → 25-45
- 半透明面料（薄雪纺/欧根纱） → 45-70
- 透明面料（薄纱/网纱） → 70-90
- 极度透明（蝉翼纱/透明硬纱） → 90-100

请用以下JSON格式回复（只回复JSON，不要其他内容）：
{
    "underwear_type": "内衣类型描述",
    "underwear_color": "内衣主色描述",
    "underwear_material": "材质选项key",
    "model_neckline": "领口类型描述",
    "model_fabric": "面料描述",
    "model_color": "外衣颜色描述",
    "color_risk": "low/medium/high - 颜色偏移风险评估",
    "recommended_style": "叠穿风格选项key",
    "recommended_material": "材质选项key",
    "recommended_opacity": 数字,
    "reasoning": "选择理由简述（50字以内）"
}"""


class UnderwearAnalyzer:
    """AI 分析内衣图+模特图，推荐最佳叠穿配置"""

    def __init__(self, api_keys: list = None):
        self.api_keys = api_keys if api_keys is not None else settings.YUNWU_API_KEYS
        if isinstance(self.api_keys, str):
            self.api_keys = [k.strip() for k in self.api_keys.split(",") if k.strip()]
        if not self.api_keys:
            raise ValueError("未提供任何 API Key")

        self.key_cycle = itertools.cycle(self.api_keys)
        self.base_url = settings.YUNWU_BASE_URL
        self.model = settings.YUNWU_MODEL

    def _encode_image(self, image: Image.Image) -> str:
        buffered = BytesIO()
        image.save(buffered, format="JPEG", quality=85)
        return base64.b64encode(buffered.getvalue()).decode()

    async def analyze_pair(self, underwear_img: Image.Image, model_img: Image.Image) -> dict:
        """分析内衣图+模特图，返回最佳叠穿配置"""
        current_key = next(self.key_cycle)

        underwear_b64 = self._encode_image(underwear_img)
        model_b64 = self._encode_image(model_img)

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ANALYSIS_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{underwear_b64}"}},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{model_b64}"}},
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {current_key}",
            "Content-Type": "application/json",
        }

        # 合法的选项值
        valid_styles = {"lace_full", "lace_peek", "see_through", "half_dressed", "strap_slipped", "subtle_hint"}
        valid_materials = {"lace", "smooth", "cotton", "sports", "embroidered"}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    try:
                        json_str = content
                        if "```json" in content:
                            json_str = content.split("```json")[1].split("```")[0].strip()
                        elif "```" in content:
                            json_str = content.split("```")[1].split("```")[0].strip()
                        result = json.loads(json_str)

                        # 校验并修正返回值
                        if result.get("recommended_style") not in valid_styles:
                            result["recommended_style"] = "lace_full"
                        if result.get("recommended_material") not in valid_materials:
                            result["recommended_material"] = "lace"
                        try:
                            result["recommended_opacity"] = max(0, min(100, int(result.get("recommended_opacity", 30))))
                        except (ValueError, TypeError):
                            result["recommended_opacity"] = 30

                        logger.info(
                            f"内衣分析结果: 内衣={result.get('underwear_type', '?')}, "
                            f"材质={result.get('recommended_material', '?')}, "
                            f"风格={result.get('recommended_style', '?')}, "
                            f"透明度={result.get('recommended_opacity', '?')}, "
                            f"理由={result.get('reasoning', '')}"
                        )
                        return result
                    except json.JSONDecodeError:
                        logger.warning(f"内衣分析JSON解析失败: {content}")
                        return self._fallback()
                else:
                    error_text = await response.text()
                    logger.error(f"内衣分析API失败 {response.status}: {error_text}")
                    return self._fallback()

    @staticmethod
    def _fallback() -> dict:
        """分析失败时的默认值"""
        return {
            "underwear_type": "未知",
            "underwear_material": "lace",
            "model_neckline": "未知",
            "model_fabric": "未知",
            "recommended_style": "lace_full",
            "recommended_material": "lace",
            "recommended_opacity": 30,
            "reasoning": "分析失败，使用默认配置",
        }
