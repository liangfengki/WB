import asyncio
import base64
import aiohttp
import re
import itertools
from io import BytesIO
from PIL import Image
from config.settings import settings
from utils.logger import logger


class SeedreamAPI:
    def __init__(self, api_keys: list = None, base_url: str = None, model: str = None):
        self.api_keys = api_keys if api_keys is not None else settings.YUNWU_API_KEYS
        if isinstance(self.api_keys, str):
            self.api_keys = [k.strip() for k in self.api_keys.split(",") if k.strip()]
        if not self.api_keys:
            raise ValueError("未提供任何 API Key")
            
        self.key_cycle = itertools.cycle(self.api_keys)
        self.base_url = base_url if base_url else settings.YUNWU_BASE_URL
        self.model = model if model else settings.YUNWU_MODEL
        self._semaphore = None

    @property
    def semaphore(self):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.CONCURRENCY)
        return self._semaphore

    async def generate_image(
        self, reference_image: Image.Image, prompt: str, n: int = 1
    ) -> list:
        async with self.semaphore:
            last_exception = None
            
            for attempt in range(settings.MAX_RETRIES):
                current_key = next(self.key_cycle)
                try:
                    buffered = BytesIO()
                    reference_image.save(buffered, format="JPEG", quality=90)
                    img_base64 = base64.b64encode(buffered.getvalue()).decode()

                    payload = {
                        "model": self.model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                                ]
                            }
                        ]
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
                            timeout=aiohttp.ClientTimeout(total=120),
                        ) as response:
                            if response.status == 200:
                                data = await response.json()
                                if "choices" in data and len(data["choices"]) > 0:
                                    content = data["choices"][0]["message"]["content"]
                                    
                                    # Gemini-3.1-flash-image-preview returns base64 string in markdown format like ![image](data:image/jpeg;base64,/9j/...)
                                    match = re.search(r'base64,([A-Za-z0-9+/=]+)', content)
                                    if match:
                                        b64_data = match.group(1)
                                        img_bytes = base64.b64decode(b64_data)
                                        result_img = Image.open(BytesIO(img_bytes))
                                        return [result_img]
                                    else:
                                        logger.error(f"返回内容未包含base64图片数据: {content[:200]}")
                                        raise Exception("API未返回有效的base64图片数据")
                                else:
                                    raise Exception("API返回数据格式错误，未找到choices")
                            else:
                                error_text = await response.text()
                                logger.error(f"API请求失败 {response.status}: {error_text}")
                                if attempt < settings.MAX_RETRIES - 1:
                                    await asyncio.sleep(2 ** attempt)
                                else:
                                    last_exception = Exception(f"API请求失败 {response.status}: {error_text}")

                except asyncio.TimeoutError:
                    logger.error(f"第 {attempt + 1} 次请求超时")
                    last_exception = Exception("API请求超时")
                    if attempt < settings.MAX_RETRIES - 1:
                        await asyncio.sleep(2 ** attempt)
                except Exception as e:
                    logger.error(f"第 {attempt + 1} 次请求失败: {str(e)}")
                    last_exception = e
                    if attempt < settings.MAX_RETRIES - 1:
                        await asyncio.sleep(2 ** attempt)

            raise Exception(f"达到最大重试次数，API请求失败: {str(last_exception)}")

    async def generate_multiple(
        self, reference_image: Image.Image, prompt: str, count: int = 3
    ) -> list:
        tasks = []
        for i in range(count):
            tasks.append(self.generate_image(reference_image, prompt))

        results = []
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        for result in completed:
            if isinstance(result, Exception):
                logger.error(f"生成图片失败: {str(result)}")
            elif isinstance(result, list):
                results.extend(result)
            elif isinstance(result, Image.Image):
                results.append(result)

        return results
