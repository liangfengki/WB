"""XHS 多图模式提示词构建器模块。

根据场景关键词检测和用户自定义提示词，构建完整的 XHS 多图模式提示词。
"""

from typing import List, Tuple

from config.settings import settings


# 室外关键词
OUTDOOR_KEYWORDS = ["户外", "公园", "街道", "海边", "草地", "花园", "森林", "山", "湖"]
# 室内关键词
INDOOR_KEYWORDS = ["室内", "客厅", "办公室", "咖啡厅", "卧室", "书房", "餐厅", "商场"]

# 姿态引导文本
_POSE_GUIDANCE_OUTDOOR = "自然放松的肢体状态，微微舒展的手臂，身体重心略微后倾，展现轻松惬意的氛围。"
_POSE_GUIDANCE_INDOOR = "收敛得体的肢体姿态，自然下垂或轻放的手臂，身体重心居中，展现优雅端庄的气质。"
_POSE_GUIDANCE_NEUTRAL = "保持自然舒适的肢体姿态，与背景氛围协调一致。"


class PromptBuilder:
    """XHS 多图模式提示词构建器"""

    @staticmethod
    def build_xhs_multi_prompt(user_prompt: str = "", scene_keywords: List[str] = None, style_key: str = "", view_key: str = "", action_key: str = "") -> str:
        """
        构建完整的 XHS 多图模式提示词。

        Args:
            user_prompt: 用户自定义补充提示词（最多 500 字符）
            scene_keywords: 场景关键词列表，用于判断室内/室外
            style_key: 风格预设 key（可选）
            view_key: 视角预设 key（可选）
            action_key: 动作预设 key（可选）

        Returns:
            完整提示词字符串
        """
        # 检测场景类型
        scene_type = PromptBuilder.detect_scene_type(scene_keywords or [])

        # 根据场景类型选择姿态引导
        if scene_type == "outdoor":
            pose_guidance = _POSE_GUIDANCE_OUTDOOR
        elif scene_type == "indoor":
            pose_guidance = _POSE_GUIDANCE_INDOOR
        else:
            pose_guidance = _POSE_GUIDANCE_NEUTRAL

        # 风格预设
        if style_key and style_key in settings.XHS_STYLE_PRESETS:
            style_section = settings.XHS_STYLE_PRESETS[style_key]["prompt_section"]
        else:
            style_section = ""

        # 视角预设
        if view_key and view_key in settings.XHS_VIEW_PRESETS:
            view_section = settings.XHS_VIEW_PRESETS[view_key]["prompt_section"]
        else:
            view_section = ""

        # 动作预设
        if action_key and action_key in settings.XHS_ACTION_PRESETS:
            action_section = settings.XHS_ACTION_PRESETS[action_key]["prompt_section"]
        else:
            action_section = ""

        # 截断用户提示词
        truncated_prompt, _ = PromptBuilder.truncate_user_prompt(user_prompt)

        # 填充模板
        prompt = settings.XHS_MULTI_PROMPT_TEMPLATE.format(
            pose_guidance=pose_guidance,
            style_section=style_section,
            view_section=view_section,
            action_section=action_section,
            user_prompt=truncated_prompt,
        )

        return prompt

    @staticmethod
    def detect_scene_type(keywords: List[str]) -> str:
        """
        检测场景类型。

        Args:
            keywords: 场景关键词列表

        Returns:
            'outdoor' 如果包含室外关键词，
            'indoor' 如果包含室内关键词，
            'neutral' 其他情况
        """
        if not keywords:
            return "neutral"

        for keyword in keywords:
            if keyword in OUTDOOR_KEYWORDS:
                return "outdoor"

        for keyword in keywords:
            if keyword in INDOOR_KEYWORDS:
                return "indoor"

        return "neutral"

    @staticmethod
    def truncate_user_prompt(prompt: str, max_length: int = 500) -> Tuple[str, bool]:
        """
        截断用户提示词。

        Args:
            prompt: 用户输入的提示词
            max_length: 最大允许长度，默认 500

        Returns:
            (截断后的提示词, 是否被截断)
        """
        if len(prompt) <= max_length:
            return (prompt, False)
        return (prompt[:max_length], True)
