import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.a6_content import ContentAgent
from app.core.config import settings

@pytest.fixture
def mock_db():
    db = MagicMock(spec=AsyncSession)
    mock_res = MagicMock()
    mock_res.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=mock_res)
    db.commit = AsyncMock()
    return db

@pytest.fixture
def sample_rss_xml():
    return """<rss version="2.0"><channel>
        <title>TechCrunch</title>
        <link>https://techcrunch.com</link>
        <item>
            <title>Salesforce launches new AI Agentforce automation</title>
            <link>https://techcrunch.com/agentforce</link>
            <description>Enterprise CRM AI agents are trending.</description>
            <pubDate>Mon, 17 Aug 2026 12:00:00 GMT</pubDate>
        </item>
    </channel></rss>"""

@pytest.fixture
def sample_gnews_xml():
    return """<rss version="2.0"><channel>
        <title>Google News - CRM automation</title>
        <link>https://news.google.com</link>
        <item>
            <title>How AI Agents change enterprise B2B sales - TechCrunch</title>
            <link>https://news.google.com/articles/123?utm_source=feed</link>
            <description>CRM systems are getting RAG automation.</description>
            <pubDate>Mon, 17 Aug 2026 10:00:00 GMT</pubDate>
            <source url="https://techcrunch.com">TechCrunch</source>
        </item>
    </channel></rss>"""

@pytest.mark.asyncio
@patch("app.core.config.settings.RSS_FEED_URLS", "https://techcrunch.com/feed/")
async def test_rss_parsing_works(mock_db, sample_rss_xml):
    """1. Normal RSS parsing works."""
    agent = ContentAgent(mock_db)
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_rss_xml
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
        signals, fetched, attempted = await agent._check_rss_feeds()
        assert len(signals) == 1
        assert fetched == 1
        assert attempted == 1
        assert signals[0]["source"] == "rss"
        assert signals[0]["title"] == "Salesforce launches new AI Agentforce automation"
        assert "agentforce" in signals[0]["url"]

@pytest.mark.asyncio
@patch("app.core.config.settings.GOOGLE_NEWS_QUERIES", "CRM automation")
async def test_google_news_parsing_works(mock_db, sample_gnews_xml):
    """2. Google News RSS parsing works with a mocked/sample feed."""
    agent = ContentAgent(mock_db)
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_gnews_xml
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
        signals, fetched, attempted = await agent._check_google_news()
        assert len(signals) == 1
        assert fetched == 1
        assert attempted == 1
        assert signals[0]["source"] == "google_news"
        assert signals[0]["title"] == "How AI Agents change enterprise B2B sales - TechCrunch"
        assert signals[0]["source_name"] == "TechCrunch"

@pytest.mark.asyncio
@patch("app.core.config.settings.RSS_FEED_URLS", "https://broken-feed.com/rss")
async def test_rss_failure_does_not_crash(mock_db):
    """3. RSS failures do not crash A6."""
    agent = ContentAgent(mock_db)
    
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=Exception("Connection Timeout"))):
        signals, fetched, attempted = await agent._check_rss_feeds()
        assert len(signals) == 0
        assert fetched == 0
        assert attempted == 1

@pytest.mark.asyncio
@patch("app.core.config.settings.GOOGLE_NEWS_QUERIES", "CRM automation")
async def test_google_news_failure_does_not_crash(mock_db):
    """4. Google News RSS failures do not crash A6."""
    agent = ContentAgent(mock_db)
    
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=Exception("HTTP 503 Service Unavailable"))):
        signals, fetched, attempted = await agent._check_google_news()
        assert len(signals) == 0
        assert fetched == 0
        assert attempted == 1

@pytest.mark.asyncio
@patch("app.core.config.settings.RSS_FEED_URLS", "https://techcrunch.com/feed/")
async def test_source_normalization(mock_db, sample_rss_xml):
    """5. Different sources are normalized into the same structure."""
    agent = ContentAgent(mock_db)
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_rss_xml
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
        signals, _, _ = await agent._check_rss_feeds()
        sig = signals[0]
        # Check required normalized structure fields
        assert "source" in sig
        assert "title" in sig
        assert "topic" in sig
        assert "content" in sig
        assert "description" in sig
        assert "url" in sig
        assert "published_at" in sig
        assert "source_name" in sig
        assert "source_type" in sig

@pytest.mark.asyncio
@patch("app.core.config.settings.A6_RELEVANCE_KEYWORDS", "Salesforce")
async def test_duplicate_url_deduplication(mock_db):
    """6. Duplicate URLs (even with varying query params) are removed."""
    agent = ContentAgent(mock_db)
    
    raw_signals = [
        {"source": "rss", "title": "Salesforce Update", "url": "https://techcrunch.com/salesforce?utm_source=feed&utm_campaign=xyz"},
        {"source": "google_news", "title": "Salesforce News", "url": "https://techcrunch.com/salesforce/"}
    ]

    with patch.object(agent, "_check_rss_feeds", AsyncMock(return_value=([], 0, 0))):
        with patch.object(agent, "_check_google_news", AsyncMock(return_value=([], 0, 0))):
            with patch("app.core.config.settings.NEWS_API_KEY", ""):
                with patch("app.core.config.settings.APIFY_API_TOKEN", ""):
                    # Inject signals raw list before deduplication
                    with patch("app.agents.a6_content.httpx.AsyncClient.get") as mock_get:
                        # Re-implement simple mock for signals aggregation
                        async def mock_gather():
                            return raw_signals
                        agent._check_rss_feeds = AsyncMock(return_value=(raw_signals[:1], 1, 1))
                        agent._check_google_news = AsyncMock(return_value=(raw_signals[1:], 1, 1))
                        
                        deduped = await agent._gather_demand_signals()
                        assert len(deduped) == 1

@pytest.mark.asyncio
@patch("app.core.config.settings.A6_RELEVANCE_KEYWORDS", "Salesforce")
async def test_duplicate_title_deduplication(mock_db):
    """7. Duplicate normalized titles are removed."""
    agent = ContentAgent(mock_db)
    
    raw_signals = [
        {"source": "rss", "title": "Salesforce launches new AI Agentforce!", "url": "https://url1.com"},
        {"source": "google_news", "title": "Salesforce Launches New AI Agentforce.", "url": "https://url2.com"}
    ]

    agent._check_rss_feeds = AsyncMock(return_value=(raw_signals[:1], 1, 1))
    agent._check_google_news = AsyncMock(return_value=(raw_signals[1:], 1, 1))
    
    with patch("app.core.config.settings.NEWS_API_KEY", ""):
        with patch("app.core.config.settings.APIFY_API_TOKEN", ""):
            deduped = await agent._gather_demand_signals()
            assert len(deduped) == 1

@pytest.mark.asyncio
@patch("app.core.config.settings.A6_RELEVANCE_KEYWORDS", "Salesforce,Agentforce")
async def test_relevance_filtering(mock_db):
    """8. Relevance filtering works."""
    agent = ContentAgent(mock_db)
    
    raw_signals = [
        {"source": "rss", "title": "Salesforce releases new CRM code", "url": "https://url1.com"},
        {"source": "rss", "title": "Celebrity gossips on movie premier", "url": "https://url2.com"}
    ]

    agent._check_rss_feeds = AsyncMock(return_value=(raw_signals, 2, 1))
    agent._check_google_news = AsyncMock(return_value=([], 0, 0))
    
    with patch("app.core.config.settings.NEWS_API_KEY", ""):
        with patch("app.core.config.settings.APIFY_API_TOKEN", ""):
            deduped = await agent._gather_demand_signals()
            assert len(deduped) == 1
            assert deduped[0]["title"] == "Salesforce releases new CRM code"

@pytest.mark.asyncio
async def test_a4_a5_insights_flow_and_fallback(mock_db):
    """9. A4/A5 insights still reach content generation and A6 fallback works with zero signals."""
    agent = ContentAgent(mock_db)
    
    conv_insights = [{"source": "A4", "company": "Acme", "text": "Cost is too high"}]
    deal_insights = [{"source": "A5", "company": "Global Corp", "text": "Data security risk"}]
    
    agent.llm.complete = AsyncMock(return_value={"briefs": [{"topic": "Cost & Security in Salesforce Integration"}]})
    
    # Run briefs generation with zero demand signals
    briefs = await agent._generate_content_briefs(
        signals=[],
        icp_segments=["SaaS"],
        conv_insights=conv_insights,
        deal_insights=deal_insights
    )
    
    assert len(briefs) == 1
    # Check that A4 and A5 details were integrated in the call
    called_prompt = agent.llm.complete.call_args[1]["system"]
    assert "Cost is too high" in called_prompt
    assert "Data security risk" in called_prompt
    assert "PRIORITIZATION ORDER" in called_prompt

@pytest.mark.asyncio
async def test_a6_runs_when_all_external_zero(mock_db):
    """10. A6 works when all external sources return zero results."""
    agent = ContentAgent(mock_db)
    
    agent._gather_demand_signals = AsyncMock(return_value=[])
    agent._get_active_icp_segments = AsyncMock(return_value=["SaaS"])
    agent._get_conversation_insights = AsyncMock(return_value=[])
    agent._get_deal_insights = AsyncMock(return_value=[])
    agent._generate_content_briefs = AsyncMock(return_value=[])
    
    result = await agent.run()
    assert result["agent"] == "A6"
    assert result["briefs_created"] == 0

@pytest.mark.asyncio
@patch("app.core.config.settings.NEWS_API_KEY", "test_key")
async def test_existing_newsapi_reddit_not_broken(mock_db):
    """11. Existing NewsAPI/Reddit behavior is preserved and not broken."""
    agent = ContentAgent(mock_db)
    
    mock_news_resp = MagicMock()
    mock_news_resp.status_code = 200
    mock_news_resp.json = MagicMock(return_value={
        "articles": [{"title": "Salesforce CRM News", "description": "AI CRM integration changes B2B sales.", "url": "https://news.com"}]
    })
    
    agent._check_rss_feeds = AsyncMock(return_value=([], 0, 0))
    agent._check_google_news = AsyncMock(return_value=([], 0, 0))
    
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_news_resp)):
        with patch("app.core.config.settings.APIFY_API_TOKEN", ""):
            signals = await agent._gather_demand_signals()
            # NewsAPI returned 1 signal which should be there
            assert len(signals) == 1
            assert signals[0]["source"] == "newsapi"

@pytest.mark.asyncio
@patch("app.core.config.settings.A6_MAX_BRIEFS", 2)
@patch("app.core.config.settings.A6_CONTENT_FORMATS", "linkedin_post,email_sequence")
async def test_briefs_and_formats_limits(mock_db):
    """12. A6_MAX_BRIEFS and A6_CONTENT_FORMATS continue to work."""
    agent = ContentAgent(mock_db)
    
    agent._gather_demand_signals = AsyncMock(return_value=[])
    agent._get_active_icp_segments = MagicMock() # wait, this can be MagicMock/AsyncMock. Let's make sure it does not fail
    agent._get_active_icp_segments = AsyncMock(return_value=["SaaS"])
    agent._get_conversation_insights = AsyncMock(return_value=[])
    agent._get_deal_insights = AsyncMock(return_value=[])
    
    briefs = [
        {"topic": "Topic 1", "icp_segment": "SaaS"},
        {"topic": "Topic 2", "icp_segment": "SaaS"},
        {"topic": "Topic 3", "icp_segment": "SaaS"}
    ]
    agent._generate_content_briefs = AsyncMock(return_value=briefs)
    
    # mock generated content distinct check to prevent duplicates skipping
    mock_distinct = MagicMock()
    mock_distinct.all = MagicMock(return_value=[])
    mock_db.execute = AsyncMock(return_value=mock_distinct)
    
    agent._generate_all_formats = AsyncMock(return_value=([], []))
    agent._save_content = AsyncMock(return_value=(0, 0))
    
    await agent.run()
    # verify that only settings.A6_MAX_BRIEFS (2) are processed
    assert agent._generate_all_formats.call_count == 2
