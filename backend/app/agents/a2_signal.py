"""
A2 Signal Intelligence Agent.

Uses only the configured sources for this deployment:
- Adzuna for hiring signals
- NewsAPI for funding and expansion news
"""
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Contact, FunnelEvent, SignalConversionRegistry, SignalEvent, SignalType

logger = structlog.get_logger()

DEFAULT_WEIGHTS = {
    SignalType.NEW_HIRE: 0.65,
    SignalType.FUNDING_ROUND: 0.60,
    SignalType.JOB_POSTING: 0.45,
    SignalType.NEWS_EXPANSION: 0.25,
}


class SignalAgent:
    """A2: Detects buying signals through Adzuna and NewsAPI."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._registry_cache: Optional[Dict[SignalType, float]] = None

    async def run(self, contact_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        logger.info("A2 starting")

        weights = await self._load_registry()
        contacts = await self._get_contacts(contact_ids)
        logger.info("Scanning contacts", count=len(contacts))

        all_signals: List[Dict[str, Any]] = []
        for contact in contacts:
            all_signals.extend(await self._detect_signals(contact, weights))

        saved = await self._save_signals(all_signals)
        updated = await self._update_contact_signal_scores(all_signals)

        reason = self._result_reason(contacts, all_signals, saved)
        await self._log_funnel_event("signal_batch_completed", {
            "contacts_scanned": len(contacts),
            "signals_detected": len(all_signals),
            "signals_saved": saved,
            "contacts_updated": updated,
            "reason": reason,
        })

        high_score_signals = [
            signal for signal in all_signals
            if signal.get("confidence", 0) >= settings.SIGNAL_SCORE_THRESHOLD / 100
        ]
        return {
            "agent": "A2",
            "contacts_scanned": len(contacts),
            "signals_detected": len(all_signals),
            "signals_saved": saved,
            "contacts_updated": updated,
            "high_score_signals": len(high_score_signals),
            "contact_signal_pairs": [
                {
                    "contact_id": str(signal["contact_id"]),
                    "signal_type": signal["signal_type"].value,
                    "confidence": signal.get("confidence", 0),
                }
                for signal in high_score_signals
            ],
            "reason": reason,
            "message": reason,
        }

    async def _load_registry(self) -> Dict[SignalType, float]:
        if self._registry_cache:
            return self._registry_cache

        result = await self.db.execute(select(SignalConversionRegistry))
        rows = result.scalars().all()

        weights = dict(DEFAULT_WEIGHTS)
        for row in rows:
            try:
                signal_type = SignalType(row.signal_type)
            except ValueError:
                logger.warning("Unknown signal_type in registry", signal_type=row.signal_type)
                continue
            if signal_type in weights:
                weights[signal_type] = row.conversion_rate

        self._registry_cache = weights
        return weights

    async def _get_contacts(self, contact_ids: Optional[List[str]]) -> List[Contact]:
        if contact_ids:
            result = await self.db.execute(
                select(Contact).where(
                    and_(Contact.id.in_(contact_ids), Contact.do_not_contact.is_(False))
                )
            )
        else:
            result = await self.db.execute(
                select(Contact).where(
                    and_(
                        Contact.do_not_contact.is_(False),
                        Contact.icp_score >= settings.ICP_SCORE_THRESHOLD,
                        Contact.email_valid.is_not(False),
                    )
                ).limit(500)
            )
        return list(result.scalars().all())

    async def _detect_signals(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        tasks = [
            self._check_job_postings(contact, weights),
            self._check_news(contact, weights),
        ]

        signals: List[Dict[str, Any]] = []
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                signals.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Signal detector error", error=str(result))
        return signals

    async def _check_job_postings(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        if not settings.ADZUNA_APP_ID or not settings.ADZUNA_API_KEY or not contact.company:
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://api.adzuna.com/v1/api/jobs/us/search/1",
                    params={
                        "app_id": settings.ADZUNA_APP_ID,
                        "app_key": settings.ADZUNA_API_KEY,
                        "what_or": f'"{contact.company}"',
                        "results_per_page": 10,
                        "sort_by": "date",
                    },
                )
                response.raise_for_status()

            jobs = response.json().get("results", [])
            if not jobs:
                return []

            titles = [job.get("title", "").lower() for job in jobs]
            descriptions = [(job.get("description") or "")[:200].lower() for job in jobs]
            job_text = " ".join(titles + descriptions)

            signals: List[Dict[str, Any]] = []
            if any(term in job_text for term in ["sdr", "bdr", "sales development", "business development rep"]):
                signals.append({
                    "contact_id": contact.id,
                    "signal_type": SignalType.JOB_POSTING,
                    "signal_source": "adzuna",
                    "confidence": weights.get(SignalType.JOB_POSTING, DEFAULT_WEIGHTS[SignalType.JOB_POSTING]),
                    "raw_data": {"job_count": len(jobs), "roles": titles[:5]},
                })

            if any(term in job_text for term in ["vp of sales", "director of sales", "chief revenue", "head of sales"]):
                signals.append({
                    "contact_id": contact.id,
                    "signal_type": SignalType.NEW_HIRE,
                    "signal_source": "adzuna",
                    "confidence": weights.get(SignalType.NEW_HIRE, DEFAULT_WEIGHTS[SignalType.NEW_HIRE]),
                    "raw_data": {
                        "trigger": "leadership_hire",
                        "roles": [title for title in titles if "director" in title or "vp" in title][:5],
                    },
                })

            return signals
        except Exception as exc:
            logger.warning("Adzuna check failed", company=contact.company, error=str(exc))
            return []

    async def _check_news(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        if not settings.NEWS_API_KEY or not contact.company:
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": f'"{contact.company}"',
                        "sortBy": "publishedAt",
                        "language": "en",
                        "pageSize": 5,
                        "from": (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"),
                    },
                    headers={"X-Api-Key": settings.NEWS_API_KEY},
                )
                response.raise_for_status()

            articles = response.json().get("articles", [])
            if not articles:
                return []

            combined_text = " ".join(
                f"{article.get('title', '')} {article.get('description') or ''}".lower()
                for article in articles
            )
            headline = articles[0].get("title")

            signals: List[Dict[str, Any]] = []
            if any(term in combined_text for term in ["funding", "raised", "series a", "series b", "investment", "venture"]):
                signals.append({
                    "contact_id": contact.id,
                    "signal_type": SignalType.FUNDING_ROUND,
                    "signal_source": "newsapi",
                    "confidence": weights.get(SignalType.FUNDING_ROUND, DEFAULT_WEIGHTS[SignalType.FUNDING_ROUND]),
                    "raw_data": {"article_count": len(articles), "headline": headline},
                })

            if any(term in combined_text for term in ["expansion", "new market", "launch", "opens office", "acquires"]):
                signals.append({
                    "contact_id": contact.id,
                    "signal_type": SignalType.NEWS_EXPANSION,
                    "signal_source": "newsapi",
                    "confidence": weights.get(SignalType.NEWS_EXPANSION, DEFAULT_WEIGHTS[SignalType.NEWS_EXPANSION]),
                    "raw_data": {"article_count": len(articles), "headline": headline},
                })

            return signals
        except Exception as exc:
            logger.warning("NewsAPI check failed", company=contact.company, error=str(exc))
            return []

    async def _save_signals(self, signals: List[Dict[str, Any]]) -> int:
        saved = 0
        for signal in signals:
            existing = await self.db.execute(
                select(SignalEvent).where(
                    and_(
                        SignalEvent.contact_id == signal["contact_id"],
                        SignalEvent.signal_type == signal["signal_type"].value,
                        SignalEvent.detected_at >= datetime.utcnow() - timedelta(hours=settings.SIGNAL_DEDUP_HOURS),
                    )
                )
            )
            if existing.scalar_one_or_none():
                continue

            self.db.add(SignalEvent(
                contact_id=signal["contact_id"],
                signal_type=signal["signal_type"].value,
                signal_source=signal["signal_source"],
                confidence=signal["confidence"],
                conversion_weight=signal["confidence"],
                raw_data=signal.get("raw_data"),
            ))
            saved += 1

        await self.db.commit()
        return saved

    async def _update_contact_signal_scores(self, signals: List[Dict[str, Any]]) -> int:
        contact_scores: Dict[Any, float] = {}
        for signal in signals:
            contact_id = signal["contact_id"]
            contact_scores[contact_id] = max(contact_scores.get(contact_id, 0), signal["confidence"])

        updated = 0
        for contact_id, score in contact_scores.items():
            result = await self.db.execute(select(Contact).where(Contact.id == contact_id))
            contact = result.scalar_one_or_none()
            if contact:
                contact.signal_score = score * 100
                contact.latest_signal_at = datetime.utcnow()
                updated += 1

        await self.db.commit()
        return updated

    async def recalibrate_registry(self):
        logger.info("A2 recalibrating signal conversion registry")

        for signal_type in DEFAULT_WEIGHTS:
            total_result = await self.db.execute(
                select(func.count(SignalEvent.id)).where(
                    and_(
                        SignalEvent.signal_type == signal_type.value,
                        SignalEvent.triggered_outreach.is_(True),
                        SignalEvent.detected_at >= datetime.utcnow() - timedelta(days=365),
                    )
                )
            )
            total = total_result.scalar() or 0
            if total < 10:
                continue

            converted = 0
            funnel_events = await self.db.execute(
                select(FunnelEvent).where(
                    and_(
                        FunnelEvent.event_type.in_(["meeting_booked", "deal_closed_won"]),
                        FunnelEvent.timestamp >= datetime.utcnow() - timedelta(days=365),
                    )
                )
            )
            for event in funnel_events.scalars():
                metadata = event.event_metadata or {}
                if metadata.get("signal_type") == signal_type.value:
                    converted += 1

            conversion_rate = converted / total if total else DEFAULT_WEIGHTS[signal_type]
            result = await self.db.execute(
                select(SignalConversionRegistry).where(
                    SignalConversionRegistry.signal_type == signal_type.value
                )
            )
            row = result.scalar_one_or_none()
            if row:
                row.conversion_rate = conversion_rate
                row.sample_size = total
                row.last_calibrated_at = datetime.utcnow()
            else:
                self.db.add(SignalConversionRegistry(
                    signal_type=signal_type.value,
                    conversion_rate=conversion_rate,
                    sample_size=total,
                    last_calibrated_at=datetime.utcnow(),
                ))

        await self.db.commit()
        self._registry_cache = None
        logger.info("Signal registry recalibration complete")

    async def _log_funnel_event(self, event_type: str, metadata: Dict[str, Any]):
        self.db.add(FunnelEvent(event_type=event_type, agent_id="A2", event_metadata=metadata))
        await self.db.commit()

    def _result_reason(self, contacts: List[Contact], signals: List[Dict[str, Any]], saved: int) -> str:
        if not contacts:
            return "No eligible contacts found for signal scanning"
        if not settings.ADZUNA_APP_ID and not settings.NEWS_API_KEY:
            return "A2 skipped external checks because Adzuna and NewsAPI are not configured"
        if not signals:
            return "No qualifying Adzuna or NewsAPI buying signals found"
        if saved == 0:
            return "Signals were detected but all were duplicates inside the dedupe window"
        return f"Saved {saved} new buying signal(s)"
