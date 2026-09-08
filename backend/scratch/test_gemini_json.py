import asyncio
import httpx
from app.core.config import settings

async def test_generation():
    models = ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite", "gemini-flash-latest"]
    prompt = "Return a JSON object with key 'status' equal to 'working' and key 'model' equal to your model name."
    
    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={settings.GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 300,
                "temperature": 0.2,
                "responseMimeType": "application/json"
            },
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload)
                print(f"[{m}] Status: {resp.status_code}")
                if resp.status_code == 200:
                    print(f"[{m}] Response:\n", resp.json()["candidates"][0]["content"]["parts"][0]["text"])
                else:
                    print(f"[{m}] Error:\n", resp.text[:150])
        except Exception as e:
            print(f"[{m}] Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_generation())
