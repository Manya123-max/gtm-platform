import asyncio
import os
import sys

# Setup python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.agents.a6_content import ContentAgent

async def main():
    # Configure test settings dynamically
    settings.RSS_FEED_URLS = "https://techcrunch.com/feed/,https://hnrss.org/frontpage"
    settings.GOOGLE_NEWS_QUERIES = "Microsoft,Microsoft"
    # Ensure limits are defined
    settings.A6_NEWS_MAX_RESULTS = 5
    settings.A6_REDDIT_MAX_RESULTS = 5
    settings.A6_GOOGLE_NEWS_MAX_RESULTS = 5
    settings.A6_RSS_MAX_RESULTS_PER_FEED = 5
    settings.A6_RELEVANCE_KEYWORDS = "Microsoft, Tech, Software, Windows, Cloud, Salesforce, CRM"

    print("Initializing ContentAgent...")
    async with AsyncSessionLocal() as db:
        agent = ContentAgent(db=db)
        
        print("\n--- Running _gather_demand_signals ---")
        # Run RSS feed check
        print("1. Running RSS check...")
        rss_signals, rss_fetched, rss_attempt = await agent._check_rss_feeds()
        print(f"   Got {len(rss_signals)} RSS signals (fetched: {rss_fetched}, attempted: {rss_attempt}).")
        
        # Run Google News check
        print("2. Running Google News check...")
        gn_signals, gn_fetched, gn_attempt = await agent._check_google_news()
        print(f"   Got {len(gn_signals)} Google News signals (fetched: {gn_fetched}, attempted: {gn_attempt}).")
        
        # Replicate NewsAPI/Apify pre-dedup logic to compute pre-dedup count
        # to show difference between pre-dedup and post-dedup count.
        import httpx
        from datetime import datetime, timedelta
        
        newsapi_signals = []
        news_max = settings.A6_NEWS_MAX_RESULTS
        if settings.NEWS_API_KEY:
            try:
                print("3. Fetching NewsAPI for pre-dedup comparison...")
                pageSize = min(100, news_max)
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        "https://newsapi.org/v2/everything",
                        params={
                            "q": "sales automation OR GTM strategy OR revenue operations",
                            "sortBy": "publishedAt",
                            "language": "en",
                            "pageSize": pageSize,
                            "from": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"),
                        },
                        headers={"X-Api-Key": settings.NEWS_API_KEY},
                    )
                    if resp.status_code == 200:
                        for article in resp.json().get("articles", [])[:news_max]:
                            newsapi_signals.append({
                                "source": "newsapi",
                                "title": article.get("title", ""),
                                "topic": article.get("title", ""),
                                "content": article.get("description", "") or article.get("content", ""),
                                "description": article.get("description", "") or article.get("content", ""),
                                "url": article.get("url", ""),
                            })
            except Exception as e:
                print(f"   NewsAPI fetch failed: {e}")
                
        apify_signals = []
        
        pre_dedup = []
        pre_dedup.extend(newsapi_signals)
        pre_dedup.extend(apify_signals)
        pre_dedup.extend(rss_signals)
        pre_dedup.extend(gn_signals)
        
        pre_dedup_count = len(pre_dedup)
        print(f"\n   Pre-deduplication total count: {pre_dedup_count}")
        
        # Count by source pre-dedup
        source_counts_pre = {}
        for s in pre_dedup:
            src = s.get("source")
            source_counts_pre[src] = source_counts_pre.get(src, 0) + 1
        print("   Pre-dedup counts by source:")
        for src, count in source_counts_pre.items():
            print(f"     - {src}: {count}")
            
        # Run real A6 content agent method (returns post-dedup list)
        print("\n4. Running _gather_demand_signals()...")
        final_signals = await agent._gather_demand_signals()
        post_dedup_count = len(final_signals)
        
        print(f"\n   Post-deduplication total count: {post_dedup_count}")
        
        source_counts_post = {}
        for s in final_signals:
            src = s.get("source")
            source_counts_post[src] = source_counts_post.get(src, 0) + 1
        print("   Post-dedup counts by source:")
        for src, count in source_counts_post.items():
            print(f"     - {src}: {count}")
            
        diff = pre_dedup_count - post_dedup_count
        print(f"\n   Total duplicates/irrelevant removed: {diff}")
        if diff > 0:
            print("   SUCCESS: Deduplication/filtering successfully removed overlapping/irrelevant stories!")
        else:
            print("   Deduplication/filtering ran, but no overlaps or irrelevant items were removed.")

if __name__ == "__main__":
    asyncio.run(main())
