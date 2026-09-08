import asyncio
import httpx
from app.core.config import settings

async def list_models():
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={settings.GEMINI_API_KEY}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            print(f"Found {len(models)} models:")
            for m in models:
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    print(" -", m.get("name"), "| Display:", m.get("displayName"))
        else:
            print("Response:", resp.text)

if __name__ == "__main__":
    asyncio.run(list_models())
