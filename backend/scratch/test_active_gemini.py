import asyncio
import httpx
from app.core.config import settings

async def test_working_models():
    models = [
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.7-flash",
        "gemini-3.1-flash-lite",
        "gemini-pro-latest",
        "gemini-2.5-pro",
    ]
    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={settings.GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": "Say 'OK'"}]}],
            "generationConfig": {"maxOutputTokens": 10},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            print(f"{m}: HTTP {resp.status_code} - {resp.text[:100]}")

if __name__ == "__main__":
    asyncio.run(test_working_models())
