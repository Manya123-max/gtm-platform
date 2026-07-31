import httpx
import asyncio
from datetime import datetime, timedelta, timezone

async def main():
    api_key = "hDDeUGise1BKSW8XZaVSaHXIUryPrfmzjM0SNxIbN9VvkwQh"
    company_1 = "Yodlee"
    company_2 = "Google"
    url = "https://api.currentsapi.services/v1/search"
    
    # Test 1: 6 days ago in RFC 3339 format, Authorization header, Yodlee
    start_date_6d = (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params_1 = {
        "keywords": company_1,
        "language": "en",
        "start_date": start_date_6d,
    }
    headers = {
        "Authorization": api_key
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r1 = await client.get(url, params=params_1, headers=headers)
        print("TEST 1 (6 days ago, RFC 3339 header, Yodlee):")
        print(f"Status: {r1.status_code}")
        print(r1.text[:300])

    # Test 2: 6 days ago in RFC 3339 format, Authorization header, Google
    params_2 = {
        "keywords": company_2,
        "language": "en",
        "start_date": start_date_6d,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r2 = await client.get(url, params=params_2, headers=headers)
        print("\nTEST 2 (6 days ago, RFC 3339 header, Google):")
        print(f"Status: {r2.status_code}")
        print(r2.text[:300])

if __name__ == "__main__":
    asyncio.run(main())
