import asyncio
import base64
import aiohttp
from io import BytesIO
from PIL import Image

async def test():
    img = Image.new('RGB', (100, 100), color='red')
    buffered = BytesIO()
    img.save(buffered, format="JPEG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()
    
    payload = {
        "model": "gemini-3.1-flash-image-preview",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Turn this into a blue square"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                ]
            }
        ]
    }
    headers = {
        "Authorization": "Bearer YOUR_API_KEY_HERE",
        "Content-Type": "application/json",
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.yunwu.ai/v1/chat/completions", json=payload, headers=headers) as response:
            data = await response.json()
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
                print(f"Success! Content length: {len(content)}")
                print("First 50 chars:", content[:50])
                print("Last 50 chars:", content[-50:])
            else:
                print("Error:", data)

asyncio.run(test())