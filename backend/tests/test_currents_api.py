import os
import asyncio
import httpx

async def test_currents():
    url = "https://api.currentsapi.services/v1/search"
    api_key = os.environ.get("CURRENTS_API_KEY", "")
    
    print("Testing Currents API for keyword 'Galvin'...")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                url,
                params={
                    "keywords": "Galvin",
                    "language": "en",
                },
                headers={
                    "Authorization": api_key,
                }
            )
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                news = data.get("news", [])
                print(f"Number of articles: {len(news)}")
                for idx, art in enumerate(news):
                    print(f"Article {idx}:")
                    print(f"  Title: {art.get('title')}")
                    print(f"  Description: {art.get('description')}")
                    print(f"  URL: {art.get('url')}")
            else:
                print(f"Error body: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_currents())
