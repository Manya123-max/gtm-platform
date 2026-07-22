"""
A6 — Content Intelligence Agent
Starts from documented audience demand — forum questions, competitor gaps, own engagement.
Content tagged by ICP segment and fed directly into A3 outreach sequences.
Five separate Claude API calls — one per format for quality.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio
import httpx
import json
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.config import settings
from app.models.models import (
    BrandAsset, GeneratedContent, FunnelEvent, Contact
)
from app.services.llm_service import LLMService
from app.services.embedding_service import EmbeddingService

logger = structlog.get_logger()

CONTENT_FORMATS = [
    "linkedin_post",
    "email_sequence",
    "case_study",
    "blog_article",
    "sales_deck_outline",
]

FORMAT_SYSTEM_PROMPTS = {
    "linkedin_post": """You write LinkedIn posts for B2B SaaS audiences.
Rules: 150-300 words. Hook in first line. No hashtags unless < 3. Conversational tone. Data point or insight in every post. End with a question or observation, not a call to action.""",

    "email_sequence": """You write B2B email nurture sequences (3 emails).
Rules: Each email under 200 words. Subject lines under 50 chars. Value-first structure. Progressive commitment — each email asks for something slightly bigger.""",

    "case_study": """You write B2B case study outlines.
Rules: Use the Problem → Solution → Result → Proof structure. Quantify results where possible. Focus on the before/after transformation. Written for the prospect, not the vendor.""",

    "blog_article": """You write B2B SaaS blog articles.
Rules: 600-900 words. SEO-aware but not keyword-stuffed. Practical and specific. Structure: Hook → Problem framing → Analysis → Specific recommendations → Takeaway.""",

    "sales_deck_outline": """You write B2B sales deck slide outlines.
Rules: 8-12 slides maximum. Each slide gets: title, 1-line subtext, 2-3 bullet points. Sequence: Problem → Market context → Solution → How it works → Proof → ROI → Next steps.""",
}


class ContentAgent:
    """
    A6: Demand-driven content generation.

    Flow:
    1. Scrape ICP forums and competitor blogs for demand signals (Apify)
    2. Cluster topics by embedding similarity
    3. Identify gaps vs competitor content
    4. Generate content brief per topic
    5. Generate 5 formats per brief (separate Claude call each)
    6. Tag by ICP segment for use in A3 sequences
    7. Store with embeddings for brand voice retrieval
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMService()
        self.embedder = EmbeddingService()

    async def run(self, icp_segments: Optional[List[str]] = None) -> Dict[str, Any]:
        logger.info("A6 starting")

        # Step 1: Gather demand signals
        demand_signals = await self._gather_demand_signals()
        logger.info("Demand signals gathered", count=len(demand_signals))

        # Step 2: Identify active ICP segments from prospect data
        if not icp_segments:
            icp_segments = await self._get_active_icp_segments()

        # Step 3: Generate content briefs
        briefs = await self._generate_content_briefs(demand_signals, icp_segments)
        logger.info("Briefs generated", count=len(briefs))

        # Step 4: Generate content for each brief (all 5 formats)
        generated_count = 0
        skipped_existing = 0
        generation_errors: List[str] = []
        for brief in briefs[:3]:
            pieces, errors = await self._generate_all_formats(brief)
            generation_errors.extend(errors)
            saved, skipped = await self._save_content(pieces, brief)
            generated_count += saved
            skipped_existing += skipped

        await self._log_funnel_event("content_batch_completed", {
            "briefs": len(briefs),
            "pieces_generated": generated_count,
        })

        return {
            "agent": "A6",
            "briefs_created": len(briefs),
            "content_pieces_generated": generated_count,
            "content_pieces_skipped_existing": skipped_existing,
            "generation_errors": generation_errors,
            "reason": (
                "Content generated"
                if generated_count else
                "Existing recent content skipped"
                if skipped_existing else
                "No content generated; see generation_errors"
            ),
        }

    async def _gather_demand_signals(self) -> List[Dict]:
        """
        Collect demand signals from public sources.
        Apify free $5/mo credit for public web scraping.
        NewsAPI for competitor content monitoring.
        No LinkedIn scraping.
        """
        signals = []

        # Competitor blog RSS monitoring via NewsAPI
        if settings.NEWS_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        "https://newsapi.org/v2/everything",
                        params={
                            "q": "sales automation OR GTM strategy OR revenue operations",
                            "sortBy": "publishedAt",
                            "language": "en",
                            "pageSize": 20,
                            "from": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"),
                        },
                        headers={"X-Api-Key": settings.NEWS_API_KEY},
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        for article in resp.json().get("articles", []):
                            signals.append({
                                "source": "competitor_news",
                                "topic": article.get("title", ""),
                                "description": article.get("description", ""),
                                "url": article.get("url", ""),
                            })
            except Exception as e:
                logger.warning("NewsAPI content scan failed", error=str(e))

        # Apify public forum scraping (G2 reviews, Reddit — not LinkedIn)
        if settings.APIFY_API_TOKEN:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    # Trigger Apify web scraper actor
                    resp = await client.post(
                        f"https://api.apify.com/v2/acts/apify~web-scraper/runs",
                        headers={"Authorization": f"Bearer {settings.APIFY_API_TOKEN}"},
                        json={
                            "startUrls": [
                                {"url": "https://www.reddit.com/r/sales/top/?t=week"},
                                {"url": "https://www.reddit.com/r/Entrepreneur/top/?t=week"},
                            ],
                            "pageFunction": """
                                async function pageFunction(context) {
                                    return Array.from(document.querySelectorAll('h3')).slice(0,10).map(h => ({
                                        title: h.textContent.trim()
                                    }));
                                }
                            """,
                            "maxPagesPerCrawl": 2,
                        },
                        timeout=15,
                    )
                    if resp.status_code in (200, 201):
                        run_id = resp.json().get("data", {}).get("id")
                        if run_id:
                            # Poll for results (simplified — production would use webhooks)
                            await asyncio.sleep(15)
                            result_resp = await client.get(
                                f"https://api.apify.com/v2/acts/apify~web-scraper/runs/{run_id}/dataset/items",
                                headers={"Authorization": f"Bearer {settings.APIFY_API_TOKEN}"},
                            )
                            if result_resp.status_code == 200:
                                for item in result_resp.json()[:20]:
                                    if item.get("title"):
                                        signals.append({
                                            "source": "reddit",
                                            "topic": item["title"],
                                            "description": "",
                                        })
            except Exception as e:
                logger.warning("Apify scraping failed", error=str(e))

        logger.info("Demand signals", count=len(signals))
        return signals

    async def _get_active_icp_segments(self) -> List[str]:
        """Pull industry segments from active contacts being worked."""
        result = await self.db.execute(
            select(Contact.industry)
            .where(
                and_(
                    Contact.industry.isnot(None),
                    Contact.icp_score >= settings.ICP_SCORE_THRESHOLD,
                    Contact.do_not_contact == False,
                )
            )
            .distinct()
            .limit(5)
        )
        industries = [row[0] for row in result.all() if row[0]]
        return industries or ["SaaS", "B2B Technology"]

    async def _generate_content_briefs(
        self, signals: List[Dict], icp_segments: List[str]
    ) -> List[Dict]:
        """Use Claude Haiku to cluster signals and generate content briefs."""
        if not signals:
            return self._default_briefs(icp_segments)

        signals_text = "\n".join([
            f"- {s['topic']} (source: {s['source']})"
            for s in signals[:30]
        ])
        segments_text = ", ".join(icp_segments)

        prompt = f"""Analyse these content demand signals from ICP forums and competitor content.
Generate 3 content briefs for a B2B SaaS GTM platform.

ICP segments being targeted: {segments_text}

Demand signals:
{signals_text}

Return JSON array of exactly 3 briefs:
[
  {{
    "topic": "specific topic title",
    "icp_segment": "which ICP segment this targets",
    "angle": "unique angle not covered by competitors",
    "key_messages": ["3 key points to make"],
    "proof_points": ["data or examples to include"],
    "competitor_gap": "what competitors have not said about this"
  }}
]"""

        try:
            result = await self.llm.complete_raw(prompt, use_haiku=True)
            briefs = json.loads(result)
            return briefs if isinstance(briefs, list) else self._default_briefs(icp_segments)
        except Exception as e:
            logger.error("Brief generation failed", error=str(e))
            return self._default_briefs(icp_segments)

    def _default_briefs(self, icp_segments: List[str]) -> List[Dict]:
        segment = icp_segments[0] if icp_segments else "B2B SaaS"
        return [
            {
                "topic": f"How {segment} companies are using AI to scale GTM without scaling headcount",
                "icp_segment": segment,
                "angle": "Practical implementation, not vendor pitch",
                "key_messages": ["Agents handle volume", "Humans handle judgment", "Data compounds over time"],
                "proof_points": [],
                "competitor_gap": "Most content focuses on tools, not on how agents share context",
            }
        ]

    async def _generate_all_formats(self, brief: Dict) -> tuple[List[Dict], List[str]]:
        """
        Generate all 5 formats. Separate Claude Sonnet call per format.
        One call for all formats produces lower quality — this is intentional.
        """
        # Retrieve brand voice examples from PIG (pgvector similarity)
        brand_examples = await self._get_brand_voice_examples(brief["topic"])

        pieces: List[Dict] = []
        errors: List[str] = []
        tasks = []
        for fmt in CONTENT_FORMATS:
            tasks.append(self._generate_single_format(brief, fmt, brand_examples))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, str):
                pieces.append({
                    "format": CONTENT_FORMATS[i],
                    "content": result,
                    "brief": brief,
                    "icp_segment": brief.get("icp_segment"),
                    "topic": brief.get("topic"),
                })
            else:
                error = f"{CONTENT_FORMATS[i]}: {result}"
                errors.append(error)
                logger.warning("Format generation failed", format=CONTENT_FORMATS[i], error=str(result))

        return pieces, errors

    async def _generate_single_format(
        self, brief: Dict, fmt: str, brand_examples: List[str]
    ) -> str:
        """Single Claude Sonnet call for one content format."""
        brand_context = ""
        if brand_examples:
            brand_context = "\n\nBrand voice reference examples (match this style):\n" + \
                            "\n---\n".join(brand_examples[:2])

        user_prompt = f"""Create {fmt.replace('_', ' ')} content for this brief:

Topic: {brief['topic']}
Target ICP: {brief.get('icp_segment', 'B2B SaaS companies')}
Unique angle: {brief.get('angle', '')}
Key messages: {', '.join(brief.get('key_messages', []))}
Include: {', '.join(brief.get('proof_points', []))}
Avoid: {brief.get('competitor_gap', '')} (this is what competitors say — say something different)
{brand_context}

Return only the content, no meta-commentary."""

        return await self.llm.complete_raw(
            FORMAT_SYSTEM_PROMPTS[fmt] + "\n\nReturn only the content itself, no labels or headers.",
            user_prompt=user_prompt,
            use_sonnet=True,
        )

    async def _get_brand_voice_examples(self, topic: str) -> List[str]:
        """
        Retrieve 2 most similar brand assets using pgvector cosine similarity.
        OpenAI text-embedding-3-small: $0.02/M tokens — negligible cost.
        """
        try:
            embedding = await self.embedder.embed(topic)
            result = await self.db.execute(
                select(BrandAsset.content)
                .where(BrandAsset.embedding.isnot(None))
                .order_by(BrandAsset.embedding.cosine_distance(embedding))
                .limit(2)
            )
            return [row[0] for row in result.all()]
        except Exception:
            return []

    async def _save_content(self, pieces: List[Dict], brief: Dict) -> tuple[int, int]:
        saved = 0
        skipped = 0
        cutoff = datetime.utcnow() - timedelta(hours=settings.CONTENT_DEDUP_HOURS)
        for piece in pieces:
            if settings.CONTENT_DEDUP_HOURS > 0:
                existing = await self.db.execute(
                    select(GeneratedContent.id).where(
                        and_(
                            GeneratedContent.topic == piece.get("topic"),
                            GeneratedContent.content_format == piece["format"],
                            GeneratedContent.created_at >= cutoff,
                        )
                    ).limit(1)
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue
            self.db.add(GeneratedContent(
                title=f"{brief['topic']} — {piece['format'].replace('_', ' ').title()}",
                content_format=piece["format"],
                icp_segment=piece.get("icp_segment"),
                topic=piece.get("topic"),
                content=piece["content"],
                brief=brief,
            ))
            saved += 1
        await self.db.commit()
        return saved, skipped

    async def _log_funnel_event(self, event_type: str, metadata: Dict):
        event = FunnelEvent(event_type=event_type, agent_id="A6", event_metadata=metadata)
        self.db.add(event)
        await self.db.commit()
