import base64
import json
import aiohttp
import itertools
from io import BytesIO
from PIL import Image
from config.settings import settings
from utils.logger import logger


ANALYSIS_PROMPT = """你是一位专业的小红书内容摄影师和时尚造型顾问。请仔细分析以下人物照片：

请根据人物的穿搭风格、身材特征和整体气质，推荐最佳的拍摄风格、视角和动作。

【风格选项】
- street_style（街拍风格）：都市街头随拍，适合时尚穿搭、运动休闲风格的人物
- cafe_vibes（咖啡厅氛围）：温暖室内，适合文艺、知性、小资风格的人物
- fresh_natural（自然清新）：户外自然光，适合清新、甜美、学生气质的人物
- urban_night（城市夜景）：霓虹灯光，适合酷飒、个性、夜生活风格的人物
- vintage_film（复古胶片）：胶片质感，适合复古、文艺、有腔调的人物
- minimalist（极简风格）：简洁干净，适合气质冷淡、高级感的人物
- fashion_editorial（时尚大片）：杂志封面感，适合精致妆容、高级穿搭的人物
- sweet_cute（甜美可爱）：粉色系柔和，适合甜美、可爱、少女感的人物

【视角选项】
- front（正面）：正对镜头，展示全貌
- side（侧面）：侧面视角，展示身材轮廓
- three_quarter（3/4角度）：微侧身，最显瘦的角度
- back（背影）：背面视角，氛围感强
- overhead（俯拍）：从上往下拍，显脸小
- low_angle（仰拍）：从下往上拍，显腿长

【手部/小动作选项】
- hand_on_hip（手叉腰）：手放腰间，自信气场
- touching_hair（撩头发）：手轻触头发，自然妩媚
- hand_in_pocket（手插口袋）：手放口袋，随性酷感
- holding_object（手拿物品）：手持包/杯子/花束等道具
- chin_rest（托下巴）：手托下巴，沉思文艺
- arm_relaxed（手自然下垂）：双手自然垂放，简约干净

【脸部方向选项】
- face_front（脸朝正面）：正对镜头，直视前方
- face_slight_turn（脸微侧）：脸部微微转向一侧
- face_look_away（看向别处）：目光看向远方/侧面，不看镜头
- face_down_smile（低头微笑）：微微低头，嘴角上扬

请用以下JSON格式回复（只回复JSON，不要其他内容）：
{
    "detected_style": "检测到的人物穿搭风格描述",
    "detected_view": "当前照片的拍摄视角描述",
    "detected_action": "当前照片中人物的动作描述",
    "recommended_style": "风格选项key",
    "recommended_view": "视角选项key",
    "recommended_action": "动作选项key",
    "reasoning": "推荐理由简述（50字以内）"
}"""


class XHSStyleAnalyzer:
    """AI 分析人物照片，推荐最佳 XHS 风格和构图"""

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

    async def analyze(self, source_img: Image.Image) -> dict:
        """分析人物照片，返回推荐的风格和构图"""
        current_key = next(self.key_cycle)
        img_b64 = self._encode_image(source_img)

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ANALYSIS_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {current_key}",
            "Content-Type": "application/json",
        }

        valid_styles = set(settings.XHS_STYLE_PRESETS.keys())
        valid_views = set(settings.XHS_VIEW_PRESETS.keys())
        valid_actions = set(settings.XHS_ACTION_PRESETS.keys())

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

                        if result.get("recommended_style") not in valid_styles:
                            result["recommended_style"] = "fresh_natural"
                        if result.get("recommended_view") not in valid_views:
                            result["recommended_view"] = "front"
                        if result.get("recommended_action") not in valid_actions:
                            result["recommended_action"] = "standing"

                        logger.info(
                            f"XHS风格分析: 风格={result.get('recommended_style', '?')}, "
                            f"视角={result.get('recommended_view', '?')}, "
                            f"动作={result.get('recommended_action', '?')}, "
                            f"理由={result.get('reasoning', '')}"
                        )
                        return result
                    except json.JSONDecodeError:
                        logger.warning(f"XHS风格分析JSON解析失败: {content}")
                        return self._fallback()
                else:
                    error_text = await response.text()
                    logger.error(f"XHS风格分析API失败 {response.status}: {error_text}")
                    return self._fallback()

    @staticmethod
    def _fallback() -> dict:
        return {
            "detected_style": "未知",
            "detected_view": "未知",
            "detected_action": "未知",
            "recommended_style": "fresh_natural",
            "recommended_view": "front",
            "recommended_action": "standing",
            "reasoning": "分析失败，使用默认配置",
        }
