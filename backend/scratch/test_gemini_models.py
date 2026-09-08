import asyncio
import httpx
from app.core.config import settings
from app.services.llm_service import LLMService

async def test_gemini():
    print(f"Testing Gemini Key: {settings.GEMINI_API_KEY[:8]}...{settings.GEMINI_API_KEY[-4:]}")
    
    models_to_test = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-flash-lite-latest",
        "gemini-1.5-pro",
    ]
    
    for model in models_to_test:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": "Reply with 'GEMINI_OK: ' followed by your model name."}]}],
            "generationConfig": {"maxOutputTokens": 100, "temperature": 0.2},
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, headers={"Content-Type": "application/json"}, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    print(f" [SUCCESS] {model} -> {text}")
                else:
                    print(f" [FAIL] {model} -> HTTP {resp.status_code}: {resp.text[:120]}")
        except Exception as e:
            print(f" [ERROR] {model} -> {e}")

if __name__ == "__main__":
    asyncio.run(test_gemini())
