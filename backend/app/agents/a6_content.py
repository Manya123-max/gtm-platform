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
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.models import (
    BrandAsset, GeneratedContent, FunnelEvent, Contact, ConversationThread, Deal
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
    "linkedin_post": """You are an elite B2B SaaS executive copywriter and thought leader. 
Write a highly professional, engaging LinkedIn post.
Rules:
- Length: 150-250 words.
- Formatting: Use short, punchy paragraphs with double returns. Avoid single-sentence lines (no cringe "broetry"). Use clean bullet points.
- Tone: Consultative, analytical, and authoritative. Start with a direct, data-driven or observation-driven hook.
- Emojis: No emojis, or maximum 1 subtle/professional emoji.
- Hashtags: No hashtags at all.
- Output: Return only the final post content, ready to publish.""",

    "email_sequence": """You are a professional B2B Sales Development Copywriter.
Write a single, high-converting cold outreach email targeting decision-makers.
Rules:
- Formatting: Start with the subject line formatted exactly as: "### Subject: [Subject Line]".
- Template Tags: Use exactly `{first_name}`, `{company}`, and `{sender}` for template variables. Do NOT use bracketed placeholders like "[First Name]", "[Company]", or "[Your Name]".
- Length: Under 150 words.
- Subject line: Under 50 characters, conversational, and lowercase (e.g. "quick question re: {company}'s gtm").
- Tone: Direct, respectful, value-first. Focus on how we can address their specific objections or industry paint points.""",

    "case_study": """You are a professional B2B Case Study writer.
Write a detailed B2B customer success story/case study outline.
Rules:
- Structure: Create clear headings for "### 1. Executive Summary", "### 2. The Challenge", "### 3. The Solution", and "### 4. The Results & ROI".
- Metrics: Use realistic, highly specific performance figures and commercial metrics based on the target ICP.
- Tone: Authoritative, narrative-driven, focusing on before/after transformation. Written for the prospect, not as a vendor sales pitch.""",

    "blog_article": """You are a senior industry editor writing thought leadership pieces.
Write a high-caliber, actionable B2B SaaS blog article.
Rules:
- Length: 600-900 words.
- Structure: Use a compelling intro hook, clear H2/H3 subheadings, bullet points for recommendations, and a strong summary takeaway.
- Tone: Deeply analytical, practical, and specific. Avoid fluffy B2B platitudes ("in today's digital landscape", "revolutionary transformation"). Talk about concrete go-to-market strategies, metrics, and workflows.
- Formatting: Use markdown formatting (bold text, blockquotes) for readability.""",

    "sales_deck_outline": """You are a B2B sales narrative designer.
Write a highly persuasive 8-slide sales deck outline.
Rules:
- Structure: Slide-by-slide sequence (Problem -> Market Context -> Solution -> How it Works -> Proof -> ROI -> Next Steps).
- Slide details: For each slide, write:
  - "Slide Title"
  - "Visual Layout Suggestion" (1-line directive describing the slide's visual layout, chart, or graphic)
  - "Key Talking Points" (2-3 professional, bulleted talking points)
- Tone: Clear, customer-centric, and outcome-oriented.""",
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

        # Step 3: Fetch active prospect insights and generate content briefs
        conv_insights = await self._get_conversation_insights()
        deal_insights = await self._get_deal_insights()
        logger.info("Direct insights fetched", conv_insights=len(conv_insights), deal_insights=len(deal_insights))

        briefs = await self._generate_content_briefs(demand_signals, icp_segments, conv_insights, deal_insights)
        logger.info("Briefs generated", count=len(briefs))

        # Step 4: Generate content for each brief (all active formats)
        generated_count = 0
        skipped_existing = 0
        generation_errors: List[str] = []

        # Query all existing topics to prevent duplicates
        existing_res = await self.db.execute(select(GeneratedContent.topic).distinct())
        existing_topics = [row[0] for row in existing_res.all() if row[0]]

        for brief in briefs[:settings.A6_MAX_BRIEFS]:
            if self._is_duplicate_topic(brief.get("topic"), existing_topics):
                logger.info("Skipping duplicate brief topic", topic=brief.get("topic"))
                active_formats = [f.strip() for f in settings.A6_CONTENT_FORMATS.split(",")] if hasattr(settings, "A6_CONTENT_FORMATS") else CONTENT_FORMATS
                skipped_existing += len(active_formats)
                continue

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
        self,
        signals: List[Dict],
        icp_segments: List[str],
        conv_insights: Optional[List[Dict]] = None,
        deal_insights: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """Use Claude Haiku to cluster signals and generate content briefs."""
        conv_insights = conv_insights or []
        deal_insights = deal_insights or []

        if not signals and not conv_insights and not deal_insights:
            logger.info("No active signals or insights available to generate briefs. Skipping content generation.")
            return []

        signals_text = "\n".join([
            f"- {s['topic']} (source: {s['source']})"
            for s in signals[:30]
        ]) if signals else "No external demand signals available."

        # Format A4 and A5 direct insights
        insights_sections = []
        a4_items = [ins for ins in conv_insights if ins.get("source") == "A4"]
        if a4_items:
            insights_sections.append("Inbound Email Objections/Questions (A4):")
            for item in a4_items:
                insights_sections.append(f"  - Company: {item.get('company')} | Text: {item.get('text')}")
                
        a5_items = [ins for ins in deal_insights if ins.get("source") == "A5"]
        if a5_items:
            if insights_sections:
                insights_sections.append("")
            insights_sections.append("Deal Blockers and Risk Flags (A5):")
            for item in a5_items:
                category_str = f" [{item.get('category')}]" if item.get('category') else ""
                insights_sections.append(f"  - Company: {item.get('company')}{category_str} | Text: {item.get('text')}")
            
        insights_text = "\n".join(insights_sections) if insights_sections else "No direct prospect/deal insights available."
        segments_text = ", ".join(icp_segments)

        prompt = f"""Analyse these inputs to generate 3 content briefs for a B2B SaaS GTM platform:

1. REAL PROSPECT & DEAL INSIGHTS:
These are real objections and pain points from actual prospect conversations and deals.
IMPORTANT: Prioritize topics that address these objections and pain points over the external NewsAPI/Reddit signals, since these are direct signals from active accounts.

{insights_text}

2. EXTERNAL DEMAND SIGNALS (SUPPLEMENTARY CONTEXT):
{signals_text}

ICP segments being targeted: {segments_text}

Return a JSON object with a single key "briefs" containing a list of exactly 3 briefs:
{{
  "briefs": [
    {{
      "topic": "specific topic title addressing prospect needs/objections",
      "icp_segment": "which ICP segment this targets",
      "angle": "unique angle helping overcome the objection or educating the market",
      "key_messages": ["3 key points to make"],
      "proof_points": ["data or examples to include"],
      "competitor_gap": "how this specific angle stands out or differs from standard blog advice"
    }}
  ]
}}"""

        try:
            res = await self.llm.complete(system=prompt, user="Generate the briefs now.")
            briefs = res.get("briefs", [])
            return briefs if isinstance(briefs, list) else []
        except Exception as e:
            logger.error("Brief generation failed", error=str(e))
            return []

    async def _generate_all_formats(self, brief: Dict) -> tuple[List[Dict], List[str]]:
        """
        Generate active formats from settings. Separate Claude Sonnet call per format.
        One call for all formats produces lower quality — this is intentional.
        """
        # Retrieve brand voice examples from PIG (pgvector similarity)
        brand_examples = await self._get_brand_voice_examples(brief["topic"])

        # Parse formats from settings.A6_CONTENT_FORMATS
        active_formats = [f.strip() for f in settings.A6_CONTENT_FORMATS.split(",")] if hasattr(settings, "A6_CONTENT_FORMATS") else CONTENT_FORMATS
        valid_formats = []
        for fmt in active_formats:
            if fmt in FORMAT_SYSTEM_PROMPTS:
                valid_formats.append(fmt)
            else:
                logger.warning("Unsupported content format in settings, skipping", format=fmt)

        if not valid_formats:
            valid_formats = CONTENT_FORMATS

        pieces: List[Dict] = []
        errors: List[str] = []
        tasks = []
        for fmt in valid_formats:
            tasks.append(self._generate_single_format(brief, fmt, brand_examples))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            fmt = valid_formats[i]
            if isinstance(result, str):
                pieces.append({
                    "format": fmt,
                    "content": result,
                    "brief": brief,
                    "icp_segment": brief.get("icp_segment"),
                    "topic": brief.get("topic"),
                })
            else:
                error = f"{fmt}: {result}"
                errors.append(error)
                logger.warning("Format generation failed", format=fmt, error=str(result))

        return pieces, errors

    async def _generate_single_format(
        self, brief: Dict, fmt: str, brand_examples: List[str]
    ) -> str:
        """Single Claude Sonnet call for one content format."""
        brand_context = ""
        if brand_examples:
            brand_context = (
                "\n\nVERIFIED COMPANY EVIDENCE & BRAND ASSETS:\n"
                "The following retrieved brand assets serve as the ONLY source of factual company evidence and proof points. "
                "Use them stylistically as brand voice references, but treat their contents as the absolute limit of factual company claims:\n"
                + "\n---\n".join(brand_examples[:2])
            )

        user_prompt = f"""Create {fmt.replace('_', ' ')} content for this brief:

Topic: {brief['topic']}
Target ICP: {brief.get('icp_segment', 'B2B SaaS companies')}
Unique angle: {brief.get('angle', '')}
Key messages: {', '.join(brief.get('key_messages', []))}
Include: {', '.join(brief.get('proof_points', []))}
Avoid: {brief.get('competitor_gap', '')} (this is what competitors say — say something different)
{brand_context}

CRITICAL INSTRUCTIONS FOR PROOF POINTS & FACTUAL CLAIM CONSTRAINTS:
1. Treat all retrieved assets in the "VERIFIED COMPANY EVIDENCE & BRAND ASSETS" section above as the ONLY source of factual company evidence, customer names, certifications, project outcomes, and metrics.
2. You must NOT invent or hallucinate any metrics, customer names, statistics, project results, certifications, or case-study details. You may only use facts explicitly supported by the retrieved assets.
3. If the retrieved assets do not contain a relevant proof point, do NOT fabricate one; instead, omit the proof point or clearly state that no verified proof point is available.
4. Clearly distinguish 'brand voice reference' from 'verified proof point'. Just because an asset is provided as style/voice reference does not mean it can be treated as verified proof unless it contains explicit factual claims. Do not write generic success stories unless they are supported by these verified assets.

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
        for piece in pieces:
            existing = await self.db.execute(
                select(GeneratedContent.id).where(
                    and_(
                        GeneratedContent.topic == piece.get("topic"),
                        GeneratedContent.content_format == piece["format"],
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

    def _is_duplicate_topic(self, new_topic: Optional[str], existing_topics: List[str], threshold: float = 0.5) -> bool:
        if not new_topic or not existing_topics:
            return False
        
        def get_words(text: str):
            import re
            return set(re.findall(r'\b[a-z]{3,}\b', text.lower()))
            
        new_words = get_words(new_topic)
        if not new_words:
            return False
            
        for existing in existing_topics:
            if not existing:
                continue
            existing_words = get_words(existing)
            if not existing_words:
                continue
            intersection = new_words.intersection(existing_words)
            union = new_words.union(existing_words)
            overlap = len(intersection) / len(union) if union else 0.0
            if overlap >= threshold:
                return True
        return False

    async def _log_funnel_event(self, event_type: str, metadata: Dict):
        event = FunnelEvent(event_type=event_type, agent_id="A6", event_metadata=metadata)
        self.db.add(event)
        await self.db.commit()

    async def _get_conversation_insights(self) -> List[Dict[str, Any]]:
        """
        Query interested/not_interested conversation threads from the last 30 days,
        and use Claude Haiku to extract distinct objections, pain points, or questions.
        """
        cutoff = datetime.utcnow() - timedelta(days=30)
        
        # Query threads joined with Contact
        query = (
            select(
                ConversationThread.content,
                ConversationThread.contact_id,
                Contact.company
            )
            .join(Contact, ConversationThread.contact_id == Contact.id)
            .where(
                and_(
                    ConversationThread.intent.in_(["interested", "not_interested"]),
                    ConversationThread.occurred_at >= cutoff,
                    ConversationThread.content.isnot(None),
                    ConversationThread.content != ""
                )
            )
            .order_by(ConversationThread.occurred_at.desc())
            .limit(20)
        )
        
        result = await self.db.execute(query)
        rows = result.all()
        
        if not rows:
            return []
            
        # Format the threads for the LLM prompt
        threads_data = []
        for i, row in enumerate(rows):
            threads_data.append({
                "index": i,
                "contact_id": row.contact_id,
                "company": row.company or "unknown",
                "text": row.content.strip()
            })
            
        threads_json = json.dumps(threads_data, indent=2)
        
        prompt = f"""You are a B2B sales analysis AI.
Analyze these raw conversation thread replies from prospects. Extract a list of distinct objections, pain points, or questions mentioned.

Raw Threads (tagged with contact_id and company):
{threads_json}

Return ONLY a valid JSON array of objects. Do NOT wrap in markdown or write explanation text.
Format:
[
  {{
    "text": "Extracted objection, pain point, or question (e.g. pricing concern, timeline pressure)",
    "contact_id": "<associated contact_id from raw threads>",
    "company": "<associated company from raw threads>"
  }}
]
"""
        try:
            raw_res = await self.llm.complete_raw(prompt, use_haiku=True)
            cleaned = _clean_json_str(raw_res)
            parsed = json.loads(cleaned)
            
            insights = []
            if isinstance(parsed, list):
                for item in parsed:
                    insights.append({
                        "text": (item.get("text") or "").strip(),
                        "contact_id": item.get("contact_id"),
                        "company": item.get("company", ""),
                        "source": "A4"
                    })
            return insights
        except Exception as e:
            logger.error("A6: Failed to extract conversation insights", error=str(e))
            return []

    async def _get_deal_insights(self) -> List[Dict[str, Any]]:
        """
        Query open deals, extract persisted objections and risk flags,
        and assemble a flat list of deal-related insights with source='A5'.
        """
        query = (
            select(Deal)
            .options(selectinload(Deal.contact))
            .where(Deal.outcome.is_(None))
        )
        result = await self.db.execute(query)
        deals = result.scalars().all()
        
        insights = []
        for deal in deals:
            company_name = "unknown"
            if deal.contact:
                company_name = deal.contact.company or "unknown"
            elif deal.name:
                if " - " in deal.name:
                    company_name = deal.name.split(" - ")[0].strip()
                elif " — " in deal.name:
                    company_name = deal.name.split(" — ")[0].strip()

            # 1. Extract objections (categorized objections from A5 Call Transcripts)
            if deal.objections:
                for obj in deal.objections:
                    if isinstance(obj, dict):
                        insights.append({
                            "text": (obj.get("text") or "").strip(),
                            "category": obj.get("category", "objection"),
                            "deal_id": deal.id,
                            "company": company_name,
                            "source": "A5"
                        })
            
            # 2. Extract risk_flags (A5 Deal Guard alerts)
            if deal.risk_flags:
                for risk in deal.risk_flags:
                    if isinstance(risk, dict):
                        insights.append({
                            "text": (risk.get("description") or "").strip(),
                            "category": risk.get("type", "risk"),
                            "deal_id": deal.id,
                            "company": company_name,
                            "source": "A5"
                        })
                        
        return insights


def _clean_json_str(s: str) -> str:
    """Clean markdown code block wrappers from JSON string if present."""
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1]
    if s.endswith("```"):
        s = s.rsplit("\n", 1)[0]
    return s.strip()
