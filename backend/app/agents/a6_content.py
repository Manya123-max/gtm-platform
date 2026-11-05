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
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.models import (
    BrandAsset, GeneratedContent, FunnelEvent, Contact, ConversationThread,
    Deal, SignalEvent, OutreachDraft, OutreachLog, UserInput
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
    1. Gather demand signals (external) + Account Buying Signals (A2)
    2. Identify active ICP segments & target titles from prospects (A1) + UserInput
    3. Fetch inbound conversation objections (A4), deal transcript objections & risks (A5), and outreach themes (A3)
    4. Generate 3 unique content briefs taking all upstream pipeline context into account
    5. Generate 5 formats per brief via dedicated LLM calls
    6. Tag by ICP segment and persist with embeddings for brand voice retrieval
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMService()
        self.embedder = EmbeddingService()

    async def run(self, icp_segments: Optional[List[str]] = None) -> Dict[str, Any]:
        logger.info("A6 starting")

        # Step 1: Gather external demand signals
        demand_signals = await self._gather_demand_signals()

        # Step 2: Identify active ICP segments from prospect data (A1) and user intake
        if not icp_segments:
            icp_segments = await self._get_active_icp_segments()

        # Step 3: Fetch intelligence from all upstream agents (A2, A3, A4, A5, UserInput)
        conv_insights = await self._get_conversation_insights()
        deal_insights = await self._get_deal_insights()
        buying_signals = await self._get_buying_signals()
        outreach_insights = await self._get_outreach_insights()
        user_context = await self._get_user_input_context()

        # Query all existing topics to pass to the LLM so it generates fresh, distinct topics
        existing_res = await self.db.execute(select(GeneratedContent.topic).distinct())
        existing_topics = [row[0] for row in existing_res.all() if row[0]]

        logger.info(
            "Pipeline insights fetched",
            conv_insights=len(conv_insights),
            deal_insights=len(deal_insights),
            buying_signals=len(buying_signals),
            outreach_insights=len(outreach_insights),
            icp_segments=len(icp_segments),
        )

        briefs = await self._generate_content_briefs(
            signals=demand_signals,
            icp_segments=icp_segments,
            conv_insights=conv_insights,
            deal_insights=deal_insights,
            buying_signals=buying_signals,
            outreach_insights=outreach_insights,
            user_context=user_context,
            existing_topics=existing_topics,
        )
        logger.info("Briefs generated", count=len(briefs))

        # Step 4: Generate content for each brief (all active formats)
        generated_count = 0
        skipped_existing = 0
        generation_errors: List[str] = []

        for brief in briefs[:settings.A6_MAX_BRIEFS]:
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
        Collect demand signals from public sources (NewsAPI, Currents).
        """
        signals = []

        # Competitor blog RSS monitoring via NewsAPI
        if settings.NEWS_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(
                        "https://newsapi.org/v2/everything",
                        params={
                            "q": "sales automation OR GTM strategy OR revenue operations",
                            "sortBy": "publishedAt",
                            "language": "en",
                            "pageSize": 10,
                            "from": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"),
                        },
                        headers={"X-Api-Key": settings.NEWS_API_KEY},
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

        return signals

    async def _get_active_icp_segments(self) -> List[str]:
        """Pull industry segments from active contacts (A1) and UserInput."""
        result = await self.db.execute(
            select(Contact.industry)
            .where(
                and_(
                    Contact.industry.isnot(None),
                    Contact.industry != "",
                    Contact.do_not_contact == False,
                )
            )
            .distinct()
            .limit(10)
        )
        industries = [row[0].strip() for row in result.all() if row[0] and row[0].strip()]
        
        # Also check UserInput for target_industries
        ui_res = await self.db.execute(select(UserInput.target_industries).order_by(desc(UserInput.id)).limit(1))
        ui_inds = ui_res.scalar_one_or_none()
        if ui_inds:
            for ind in ui_inds.split(","):
                val = ind.strip()
                if val and val not in industries:
                    industries.append(val)
                    
        return industries or ["SaaS", "B2B Technology"]

    async def _get_buying_signals(self) -> List[Dict[str, Any]]:
        """Query recent account buying signals detected by A2."""
        result = await self.db.execute(
            select(SignalEvent, Contact.company)
            .outerjoin(Contact, SignalEvent.contact_id == Contact.id)
            .order_by(desc(SignalEvent.detected_at))
            .limit(20)
        )
        signals = []
        for sig, company in result.all():
            sig_type = sig.signal_type.value if hasattr(sig.signal_type, 'value') else sig.signal_type
            raw_summary = ""
            if isinstance(sig.raw_data, dict):
                if sig.raw_data.get("trigger"):
                    raw_summary = f"{sig.raw_data.get('trigger')} in {', '.join(sig.raw_data.get('locations', [])[:3])}"
                elif sig.raw_data.get("roles"):
                    raw_summary = f"Hiring for: {', '.join(sig.raw_data.get('roles', [])[:3])}"
            signals.append({
                "company": company or "Target Account",
                "signal_type": sig_type,
                "signal_source": sig.signal_source,
                "confidence": sig.confidence,
                "summary": raw_summary,
                "source": "A2"
            })
        return signals

    async def _get_outreach_insights(self) -> List[Dict[str, Any]]:
        """Query active outreach drafts and matched services from A3."""
        result = await self.db.execute(
            select(OutreachDraft, Contact.company)
            .outerjoin(Contact, OutreachDraft.contact_id == Contact.id)
            .order_by(desc(OutreachDraft.created_at))
            .limit(15)
        )
        outreach_items = []
        for draft, company in result.all():
            outreach_items.append({
                "company": company or "Target Account",
                "business_case": draft.business_case,
                "matched_services": draft.matched_services or [],
                "subject": draft.subject,
                "source": "A3"
            })
        return outreach_items

    async def _get_user_input_context(self) -> Dict[str, Any]:
        """Fetch vendor offering and onboarding context from UserInput."""
        result = await self.db.execute(select(UserInput).order_by(desc(UserInput.id)).limit(1))
        ui = result.scalar_one_or_none()
        if ui:
            return {
                "our_company_name": ui.our_company_name or "",
                "our_services": ui.our_services or "",
                "target_location": ui.target_location or "",
                "target_keywords": ui.target_keywords or "",
                "target_job_titles": ui.target_job_titles or ""
            }
        return {}

    async def _generate_content_briefs(
        self,
        signals: List[Dict],
        icp_segments: List[str],
        conv_insights: Optional[List[Dict]] = None,
        deal_insights: Optional[List[Dict]] = None,
        buying_signals: Optional[List[Dict]] = None,
        outreach_insights: Optional[List[Dict]] = None,
        user_context: Optional[Dict] = None,
        existing_topics: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Synthesize intelligence from A1-A5 into 3 high-impact content briefs."""
        conv_insights = conv_insights or []
        deal_insights = deal_insights or []
        buying_signals = buying_signals or []
        outreach_insights = outreach_insights or []
        user_context = user_context or {}
        existing_topics = existing_topics or []

        # Format A4 conversation insights (received prospect emails & objections)
        a4_items = [ins for ins in conv_insights if ins.get("source") == "A4"]
        a4_text = "\n".join([
            f"  - Company: {item.get('company')} | Concern/Topic: {item.get('text')}"
            for item in a4_items
        ]) if a4_items else "  No recent inbound email objections recorded."

        # Format A5 deal insights (Fireflies call transcript objections & deal blockers)
        a5_items = [ins for ins in deal_insights if ins.get("source") == "A5"]
        a5_text = "\n".join([
            f"  - Company: {item.get('company')} [{item.get('category', 'objection')}] | Objection/Risk: {item.get('text')}"
            for item in a5_items
        ]) if a5_items else "  No open deal objections recorded."

        # Format A2 account buying signals
        a2_text = "\n".join([
            f"  - Company: {s.get('company')} | Signal: {s.get('signal_type')} ({s.get('summary') or s.get('signal_source')})"
            for s in buying_signals[:10]
        ]) if buying_signals else "  No recent buying signals recorded."

        # Format A3 outreach business cases & matched services
        a3_text = "\n".join([
            f"  - Company: {o.get('company')} | Pitch Case: {o.get('business_case')} | Services: {', '.join(o.get('matched_services', []))}"
            for o in outreach_insights[:10]
        ]) if outreach_insights else "  No recent outreach drafts recorded."

        vendor_info = ""
        if user_context.get("our_services"):
            vendor_info = f"""
VENDOR & OFFERING CONTEXT:
- Company Name: {user_context.get('our_company_name') or 'Our GTM Platform'}
- Core Services: {user_context.get('our_services')}
- Target Keywords: {user_context.get('target_keywords') or 'N/A'}
- Target Job Titles: {user_context.get('target_job_titles') or 'Decision Makers'}
"""

        avoid_topics_text = ""
        if existing_topics:
            avoid_topics_text = f"""
PREVIOUSLY GENERATED TOPICS (CRITICAL: DO NOT REPEAT THESE TOPICS; GENERATE NEW, FRESH ANGLES):
{chr(10).join([f'- {t}' for t in existing_topics[:15]])}
"""

        segments_text = ", ".join(icp_segments)

        prompt = f"""You are an elite B2B Content Strategy & Demand Generation AI.
Synthesize these REAL live pipeline signals and intelligence gathered across all sales agents (A1-A5) to generate 3 actionable, highly differentiated content briefs.

1. PROSPECT INBOUND OBJECTIONS & INQUIRIES (Agent 4 - Inbound Email Memory):
{a4_text}

2. DEAL INTELLIGENCE & CALL TRANSCRIPT OBJECTIONS (Agent 5 - Deal Guard & Call Transcripts):
{a5_text}

3. ACCOUNT BUYING SIGNALS (Agent 2 - Trigger Events):
{a2_text}

4. OUTREACH THEMES & MATCHED SERVICES (Agent 3 - Multi-Channel Sequences):
{a3_text}
{vendor_info}
TARGET ICP SEGMENTS:
{segments_text}
{avoid_topics_text}

RULES:
- Ground each topic directly in the real pain points, call transcript objections (e.g. compliance, HIPAA/SOC2, data residency, CRM migrations, tech stack consolidation), or buying signals above.
- Ensure the 3 briefs cover DIFFERENT angles or target different ICP segments.
- Do NOT generate generic or repetitive marketing fluff.

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
            res = await self.llm.complete(system=prompt, user="Generate the 3 briefs now.", max_tokens=4000)
            if isinstance(res, list):
                return res
            briefs = res.get("briefs", [])
            if not briefs and "topic" in res:
                briefs = [res]
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

        for fmt in valid_formats:
            try:
                result = await self._generate_single_format(brief, fmt, brand_examples)
                if isinstance(result, str) and result.strip():
                    pieces.append({
                        "format": fmt,
                        "content": result.strip(),
                        "brief": brief,
                        "icp_segment": brief.get("icp_segment"),
                        "topic": brief.get("topic"),
                    })
                await asyncio.sleep(0.2)
            except Exception as exc:
                error = f"{fmt}: {exc}"
                errors.append(error)
                logger.warning("Format generation failed", format=fmt, error=str(exc))

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
        Uses deterministic hash-based token projection embeddings (0 dependencies, non-neural).
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
                select(GeneratedContent).where(
                    and_(
                        GeneratedContent.topic == piece.get("topic"),
                        GeneratedContent.content_format == piece["format"],
                    )
                ).limit(1)
            )
            existing_row = existing.scalar_one_or_none()
            if existing_row:
                existing_row.title = f"{brief['topic']} — {piece['format'].replace('_', ' ').title()}"
                existing_row.content = piece["content"]
                existing_row.brief = brief
                existing_row.icp_segment = piece.get("icp_segment")
                saved += 1
            else:
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
        Query inbound/interested/not_interested conversation threads,
        and use LLM to extract distinct objections, pain points, or questions.
        """
        cutoff = datetime.utcnow() - timedelta(days=90)
        
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
                    or_(
                        ConversationThread.intent.in_(["interested", "not_interested", "objection", "pricing"]),
                        ConversationThread.direction == "inbound",
                        ConversationThread.event_type.in_(["reply_received", "inbound_email"]),
                    ),
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
        
        # Fallback if no recent rows in 90 days: get latest available inbound threads without cutoff filter
        if len(rows) < 3:
            fallback_query = (
                select(
                    ConversationThread.content,
                    ConversationThread.contact_id,
                    Contact.company
                )
                .join(Contact, ConversationThread.contact_id == Contact.id)
                .where(
                    and_(
                        or_(
                            ConversationThread.intent.isnot(None),
                            ConversationThread.direction == "inbound",
                            ConversationThread.event_type.in_(["reply_received", "inbound_email"])
                        ),
                        ConversationThread.content.isnot(None),
                        ConversationThread.content != ""
                    )
                )
                .order_by(ConversationThread.occurred_at.desc())
                .limit(20)
            )
            fallback_res = await self.db.execute(fallback_query)
            fallback_rows = fallback_res.all()
            if fallback_rows:
                rows = fallback_rows
            
        if not rows:
            return []
            
        # Format the threads for the LLM prompt
        threads_data = []
        for i, row in enumerate(rows):
            threads_data.append({
                "index": i,
                "contact_id": row.contact_id,
                "company": row.company or "unknown",
                "text": row.content.strip()[:500]
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
            raw_res = await self.llm.complete_raw(prompt)
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
            elif isinstance(parsed, dict) and "insights" in parsed:
                for item in parsed["insights"]:
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
        Query deals, extract persisted objections and risk flags (including from call transcripts),
        and assemble a flat list of deal-related insights with source='A5'.
        """
        query = (
            select(Deal)
            .options(selectinload(Deal.contact))
            .where(Deal.outcome.is_(None))
        )
        result = await self.db.execute(query)
        deals = result.scalars().all()
        if not deals:
            fallback_res = await self.db.execute(select(Deal).options(selectinload(Deal.contact)))
            deals = fallback_res.scalars().all()
        
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
