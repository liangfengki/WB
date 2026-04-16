import base64
import json
import aiohttp
import itertools
from io import BytesIO
from PIL import Image
from config.settings import settings
from utils.logger import logger

PRODUCT_SCENE_MAP = {
    "厨房用品": {
        "keywords": ["锅", "刀具", "砧板", "餐具", "杯子", "水壶", "厨房", "烹饪", "烘焙", "搅拌器", "量杯", "保鲜盒", "洗碗", "调料", "勺子", "叉子", "碗", "盘子", "案板", "削皮器"],
        "scenes": [
            "现代厨房场景，大理石台面，不锈钢厨具背景，明亮整洁的自然光，专业美食摄影风格",
            "温馨家庭厨房，木质台面，窗边自然光，绿植点缀，生活化氛围",
            "高端厨房展示台，深色大理石背景，聚光灯效果，奢华质感",
        ],
    },
    "家居用品": {
        "keywords": ["枕头", "被子", "毛巾", "地毯", "窗帘", "收纳", "衣架", "挂钩", "垃圾桶", "清洁", "拖把", "扫帚", "洗衣", "晾衣", "香薰", "蜡烛", "花瓶", "装饰", "相框", "时钟"],
        "scenes": [
            "温馨现代家居客厅场景，自然窗光，木质家具，绿植点缀，生活化氛围",
            "北欧简约风格卧室，浅木色家具，白色棉麻床品，柔和自然光",
            "日式极简家居空间，原木色调，白色墙面，禅意氛围",
        ],
    },
    "电子数码": {
        "keywords": ["手机", "耳机", "充电器", "数据线", "音箱", "手表", "平板", "电脑", "键盘", "鼠标", "摄像头", "路由器", "硬盘", "U盘", "电池", "灯泡", "智能", "蓝牙"],
        "scenes": [
            "现代商务办公桌面场景，深色桌面，笔记本电脑旁，专业灯光，科技感",
            "简约白色桌面，极简风格，柔和侧光，苹果产品展示风格",
            "暗色背景，霓虹灯光效果，科技感十足，赛博朋克风格",
        ],
    },
    "服装鞋帽": {
        "keywords": ["T恤", "衬衫", "裤子", "裙子", "外套", "夹克", "毛衣", "帽子", "鞋子", "运动鞋", "靴子", "袜子", "围巾", "手套", "内衣", "睡衣", "泳衣", "瑜伽", "运动服"],
        "scenes": [
            "时尚摄影工作室，浅灰色背景，柔和侧光，高端服装展示风格",
            "城市街头场景，现代建筑背景，自然日光，时尚街拍风格",
            "简约白色背景，柔和均匀布光，电商标准展示风格",
        ],
    },
    "美妆个护": {
        "keywords": ["口红", "粉底", "眼影", "面膜", "洗面奶", "乳液", "香水", "指甲油", "化妆刷", "眉笔", "防晒", "卸妆", "精华", "面霜", "护手霜", "沐浴露", "洗发水", "牙刷", "剃须"],
        "scenes": [
            "高端美妆展示台，大理石台面，玫瑰金装饰，柔和暖光，奢华美妆摄影风格",
            "清新自然场景，花瓣点缀，柔和自然光，清新唯美风格",
            "专业化妆台场景，镜前灯光，化妆品陈列，精致生活氛围",
        ],
    },
    "母婴用品": {
        "keywords": ["奶瓶", "尿布", "婴儿", "玩具", "童车", "安全座椅", "哺乳", "孕妈", "宝宝", "儿童", "积木", "拼图", "绘本", "水杯", "围嘴"],
        "scenes": [
            "温馨婴儿房场景，柔和粉色或蓝色色调，温暖灯光，安全舒适氛围",
            "清新自然草地场景，阳光明媚，户外亲子氛围",
            "简约白色婴儿房，木质家具，柔和自然光，北欧育儿风格",
        ],
    },
    "运动户外": {
        "keywords": ["瑜伽垫", "哑铃", "跳绳", "跑步", "篮球", "足球", "帐篷", "背包", "登山", "骑行", "游泳", "滑雪", "钓鱼", "运动", "健身", "护膝", "水壶", "运动服"],
        "scenes": [
            "户外自然场景，阳光明媚，草地或山景背景，清新自然光，运动活力氛围",
            "现代健身房场景，专业器械背景，动感灯光，运动氛围",
            "户外探险场景，蓝天白云，山川湖泊，冒险精神",
        ],
    },
    "食品饮料": {
        "keywords": ["零食", "坚果", "茶叶", "咖啡", "蜂蜜", "巧克力", "饼干", "果干", "麦片", "饮料", "果汁", "牛奶", "酒", "调味品", "方便面", "罐头", "糖果", "蛋糕"],
        "scenes": [
            "精致美食摄影场景，木质桌面，自然窗光，新鲜食材点缀，专业美食摄影",
            "户外野餐场景，格子餐布，草地背景，阳光明媚，休闲氛围",
            "高端餐厅场景，深色桌布，烛光效果，精致摆盘风格",
        ],
    },
    "宠物用品": {
        "keywords": ["狗粮", "猫粮", "宠物", "猫砂", "牵引绳", "宠物窝", "玩具", "鱼缸", "鸟笼", "仓鼠", "兔子", "宠物衣服", "梳子", "饮水器"],
        "scenes": [
            "温馨家庭场景，宠物友好空间，柔和自然光，温暖舒适氛围",
            "户外草地场景，阳光明媚，自然绿植背景，活泼氛围",
            "现代简约客厅，浅色家具，宠物活动空间，生活化场景",
        ],
    },
    "汽车用品": {
        "keywords": ["车载", "汽车", "座椅", "方向盘", "后视镜", "行车记录仪", "充电器", "香水", "脚垫", "遮阳", "洗车", "轮胎", "维修", "工具"],
        "scenes": [
            "高端汽车内饰场景，真皮座椅，精致仪表盘，专业灯光",
            "户外停车场场景，现代建筑背景，自然日光，商务氛围",
            "专业车库场景，深色背景，聚光灯效果，汽车展示风格",
        ],
    },
    "文具办公": {
        "keywords": ["笔", "本子", "文件夹", "订书机", "剪刀", "胶带", "便签", "计算器", "台灯", "书架", "打印机", "墨水", "颜料", "画笔", "调色", "手工"],
        "scenes": [
            "整洁办公桌面场景，木质桌面，笔记本和咖啡旁，自然窗光，工作效率氛围",
            "创意工作室场景，彩色文具陈列，灵感墙背景，活泼创意氛围",
            "简约白色桌面，极简风格，柔和侧光，专业展示风格",
        ],
    },
    "工具五金": {
        "keywords": ["扳手", "螺丝刀", "锤子", "电钻", "工具箱", "测量", "水平仪", "钳子", "锯", "钉子", "螺丝", "水管", "开关", "灯泡", "电线"],
        "scenes": [
            "专业工作台场景，工具墙背景，工业风格灯光，专业工具展示",
            "现代装修场景，施工现场背景，自然光，实用工具展示",
            "简约深色背景，聚光灯效果，高端工具产品摄影风格",
        ],
    },
}

SCENE_FALLBACK = [
    "专业电商产品摄影场景，柔和均匀布光，简约背景，高清8K，细节丰富",
    "现代生活场景，自然窗光，温馨氛围，产品居中展示，专业摄影",
    "高端产品展示台，深色背景，聚光灯效果，奢华质感，8K高清",
]


class ProductRecognizer:
    def __init__(self, api_keys: list = None, base_url: str = None, model: str = None):
        self.api_keys = api_keys if api_keys is not None else settings.YUNWU_API_KEYS
        if isinstance(self.api_keys, str):
            self.api_keys = [k.strip() for k in self.api_keys.split(",") if k.strip()]
        if not self.api_keys:
            raise ValueError("未提供任何 API Key")
            
        self.key_cycle = itertools.cycle(self.api_keys)
        self.base_url = base_url if base_url else settings.YUNWU_BASE_URL
        # 识别场景下通常使用大语言模型（如 gemini-1.5-pro 等），而非生图模型
        self.model = model if model else settings.YUNWU_MODEL

    async def recognize_product(self, image: Image.Image) -> dict:
        current_key = next(self.key_cycle)
        buffered = BytesIO()
        image.save(buffered, format="JPEG", quality=85)
        img_base64 = base64.b64encode(buffered.getvalue()).decode()

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请仔细分析这张产品图片，识别出这是什么类型的产品。请用以下JSON格式回复（只回复JSON，不要其他内容）：\n{\"product_type\": \"产品大类（如：厨房用品/家居用品/电子数码/服装鞋帽/美妆个护/母婴用品/运动户外/食品饮料/宠物用品/汽车用品/文具办公/工具五金）\", \"product_name\": \"具体产品名称\", \"description\": \"产品外观和特征的简要描述\", \"suitable_scenes\": [\"适合该产品的场景1\", \"适合该产品的场景2\", \"适合该产品的场景3\"]}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
                        }
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {current_key}",
            "Content-Type": "application/json",
        }

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
                        logger.info(f"产品识别结果: {result.get('product_type', '未知')} - {result.get('product_name', '未知')}")
                        return result
                    except json.JSONDecodeError:
                        logger.warning(f"JSON解析失败，原始内容: {content}")
                        return {
                            "product_type": "未知",
                            "product_name": "未知产品",
                            "description": content,
                            "suitable_scenes": [],
                        }
                else:
                    error_text = await response.text()
                    logger.error(f"视觉识别API失败 {response.status}: {error_text}")
                    return {
                        "product_type": "未知",
                        "product_name": "未知产品",
                        "description": f"API调用失败: {response.status}",
                        "suitable_scenes": [],
                    }

    @staticmethod
    def get_scenes_for_product(recognition_result: dict) -> list:
        product_type = recognition_result.get("product_type", "未知")
        product_name = recognition_result.get("product_name", "")
        description = recognition_result.get("description", "")
        ai_scenes = recognition_result.get("suitable_scenes", [])

        matched_scenes = []
        for category, config in PRODUCT_SCENE_MAP.items():
            for keyword in config["keywords"]:
                if keyword in product_type or keyword in product_name or keyword in description:
                    matched_scenes = config["scenes"]
                    break
            if matched_scenes:
                break

        if not matched_scenes:
            for category, config in PRODUCT_SCENE_MAP.items():
                if category in product_type:
                    matched_scenes = config["scenes"]
                    break

        all_scenes = []
        if ai_scenes:
            all_scenes.extend(ai_scenes[:3])
        if matched_scenes:
            for s in matched_scenes:
                if s not in all_scenes:
                    all_scenes.append(s)
        if not all_scenes:
            all_scenes = SCENE_FALLBACK.copy()

        return all_scenes[:3]
