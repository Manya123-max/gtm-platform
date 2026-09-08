"""
A2 Signal Intelligence Agent.

Sources for this deployment:
- Adzuna              hiring signals (job board search)
- PredictLeads        structured hiring / funding / news-event signals (primary;
                       replaces most of NewsAPI's job with categorized data instead
                       of keyword matching)
- Currents API        supplementary keyword-matched news, higher free-tier rate
                       limit than NewsAPI and commercial-use friendly
- NewsAPI             legacy source, kept only as an optional extra if a key is
                       still configured (low free-tier rate limit — see PredictLeads
                       / Currents above for the replacements)
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
import structlog
from sqlalchemy import and_, or_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Contact, FunnelEvent, SignalConversionRegistry, SignalEvent, SignalType

logger = structlog.get_logger()

DEFAULT_WEIGHTS = {
    SignalType.NEW_HIRE: 0.65,
    SignalType.FUNDING_ROUND: 0.60,
    SignalType.JOB_POSTING: 0.60,
    SignalType.NEWS_EXPANSION: 0.25,
    SignalType.TECH_STACK_CHANGE: 0.50,
    SignalType.EARNINGS_CALL: 0.45,
    SignalType.COMPETITOR_REVIEW: 0.55,
    SignalType.SOCIAL_ENGAGEMENT: 0.40,
}


def _has_keyword(text: str, keywords: List[str]) -> bool:
    text_lower = text.lower()
    for kw in keywords:
        pattern = r'\b' + re.escape(kw.lower()) + r'\b'
        if re.search(pattern, text_lower):
            return True
    return False


class SignalAgent:
    """A2: Detects buying signals through Adzuna, PredictLeads, Currents API, and (optionally) NewsAPI."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._registry_cache: Optional[Dict[SignalType, float]] = None
        self._predictleads_disabled = False

    async def run(self, contact_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        logger.info("A2 starting")

        weights = await self._load_registry()
        contacts = await self._get_contacts(contact_ids)
        logger.info("Scanning contacts", count=len(contacts))

        all_signals: List[Dict[str, Any]] = []
        for contact in contacts:
            all_signals.extend(await self._detect_signals(contact, weights))
            # Rate limit delay to prevent Adzuna/Currents/NewsAPI 503 gateway timeouts
            await asyncio.sleep(0.5)

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
            self._check_predictleads(contact, weights),
            self._check_currents(contact, weights),
            self._check_news(contact, weights),
            self._check_apify(contact, weights),
        ]

        signals: List[Dict[str, Any]] = []
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                signals.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Signal detector error", error=str(result))
        return signals

    def _get_company_domain(self, contact: Contact) -> str:
        """Resolve a bare domain for domain-keyed APIs (PredictLeads)."""
        if contact.company_domain:
            return contact.company_domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
        email = contact.email or ""
        parts = email.split("@")
        return parts[1].lower() if len(parts) > 1 else ""

    def _clean_company_name(self, name: Optional[str]) -> str:
        if not name:
            return ""
        import re
        # Remove parenthetical details e.g., Proximus Media House (PMH) -> Proximus Media House
        name = re.sub(r"\(.*?\)", "", name)
        # Remove suffixes after common delimiters with surrounding spaces or specific characters, but NOT raw hyphens inside words
        for delimiter in [" | ", " - ", " — ", " , "]:
            if delimiter in name:
                name = name.split(delimiter)[0]
        
        if ", " in name:
            name = name.split(", ")[0]
            
        suffixes = [
            "corporation", "corp.", "corp", 
            "incorporated", "inc.", "inc", 
            "limited", "ltd.", "ltd", 
            "llc", "l.l.c.", 
            "association", "assn.",
            "worldwide", "holdings", "group",
            "technologies", "technology", "tech",
            "services", "systems", "solutions",
            "mena", "europe", "international", "intl."
        ]
        
        name_lower = name.lower().strip()
        # Clean multiple suffixes iteratively
        cleaned = True
        while cleaned:
            cleaned = False
            for suffix in suffixes:
                # Check both space and hyphen prefixes
                for sep in [" ", "-"]:
                    full_suffix = sep + suffix
                    if name_lower.endswith(full_suffix):
                        remaining_len = len(name_lower) - len(full_suffix)
                        if remaining_len >= 3:
                            name = name[:remaining_len].strip()
                            name_lower = name.lower().strip()
                            cleaned = True
                            break
                if cleaned:
                    break
                        
        return name.strip()

    def _get_adzuna_country_code(self, contact: Contact) -> str:
        # Check email domain extension
        email = contact.email or ""
        parts = email.split("@")
        if len(parts) > 1:
            domain = parts[1].lower()
            tld = domain.split(".")[-1]
            
            # Map top-level domains to Adzuna country codes
            tld_map = {
                "us": "us", "uk": "gb", "gb": "gb", "co.uk": "gb",
                "ca": "ca", "au": "au", "nz": "nz", "za": "za",
                "in": "in", "de": "de", "fr": "fr", "it": "it",
                "nl": "nl", "at": "at", "pl": "pl", "ru": "ru",
                "sg": "sg", "br": "br", "mx": "mx", "be": "be",
                "ch": "ch", "es": "es", "se": "se"
            }
            if tld in tld_map:
                return tld_map[tld]

        # Check geography string
        geo = (contact.geography or "").lower()
        geo_map = {
            "india": "in", "united kingdom": "gb", "uk": "gb",
            "germany": "de", "france": "fr", "italy": "it",
            "brazil": "br", "canada": "ca", "australia": "au",
            "poland": "pl", "belgium": "be", "spain": "es",
            "south africa": "za", "new zealand": "nz", "switzerland": "ch",
            "netherlands": "nl", "austria": "at", "singapore": "sg",
            "mexico": "mx", "russia": "ru", "sweden": "se"
        }
        for country, code in geo_map.items():
            if country in geo:
                return code

        return "us"  # default fallback

    async def _check_job_postings(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        company = self._clean_company_name(contact.company)
        if not settings.ADZUNA_APP_ID or not settings.ADZUNA_API_KEY or not company:
            return []

        country_code = self._get_adzuna_country_code(contact)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/1",
                    params={
                        "app_id": settings.ADZUNA_APP_ID,
                        "app_key": settings.ADZUNA_API_KEY,
                        "what_or": f'"{company}"',
                        "results_per_page": 20,
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

            locations = sorted(list(set(
                job.get("location", {}).get("display_name")
                for job in jobs
                if job.get("location", {}) and job.get("location", {}).get("display_name")
            )))

            salaries_max = [job.get("salary_max") for job in jobs if job.get("salary_max")]
            salaries_min = [job.get("salary_min") for job in jobs if job.get("salary_min")]
            max_salary = max(salaries_max) if salaries_max else None
            min_salary = min(salaries_min) if salaries_min else None

            signals: List[Dict[str, Any]] = []
            if any(term in job_text for term in ["sdr", "bdr", "sales development", "business development rep", "hiring", "recruiting", "sales", "careers", "we are hiring", "open position"]):
                job_data = {
                    "job_count": len(jobs),
                    "roles": titles,
                    "locations": locations
                }
                if max_salary is not None:
                    job_data["max_salary"] = max_salary
                if min_salary is not None:
                    job_data["min_salary"] = min_salary

                signals.append({
                    "contact_id": contact.id,
                    "signal_type": SignalType.JOB_POSTING,
                    "signal_source": "adzuna",
                    "confidence": weights.get(SignalType.JOB_POSTING, DEFAULT_WEIGHTS[SignalType.JOB_POSTING]),
                    "raw_data": job_data,
                })

            if any(term in job_text for term in ["vp of sales", "director of sales", "chief revenue", "head of sales"]):
                signals.append({
                    "contact_id": contact.id,
                    "signal_type": SignalType.NEW_HIRE,
                    "signal_source": "adzuna",
                    "confidence": weights.get(SignalType.NEW_HIRE, DEFAULT_WEIGHTS[SignalType.NEW_HIRE]),
                    "raw_data": {
                        "trigger": "leadership_hire",
                        "roles": [title for title in titles if "director" in title or "vp" in title][:20],
                    },
                })

            # Check for geographic expansion based on hiring locations
            contact_geo = (contact.geography or "").strip().lower()
            expansion_locations = []
            if contact_geo:
                for loc in locations:
                    if contact_geo not in loc.lower():
                        expansion_locations.append(loc)
            if expansion_locations:
                signals.append({
                    "contact_id": contact.id,
                    "signal_type": SignalType.NEWS_EXPANSION,
                    "signal_source": "adzuna",
                    "confidence": weights.get(SignalType.NEWS_EXPANSION, DEFAULT_WEIGHTS[SignalType.NEWS_EXPANSION]),
                    "raw_data": {
                        "trigger": "geographic_expansion",
                        "locations": expansion_locations,
                    }
                })

            return signals
        except Exception as exc:
            logger.warning("Adzuna check failed", company=company, error=str(exc))
            return []

    # PredictLeads news_event categories that indicate expansion-style activity.
    # NOTE: verify this list against docs.predictleads.com > News Events Dataset >
    # Categories for your account's schema version before relying on it in prod.
    _PREDICTLEADS_EXPANSION_CATEGORIES = {
        "expansion", "new_office", "partnership", "product_launch",
        "acquisition", "merger", "new_market",
    }

    async def _check_predictleads(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        if self._predictleads_disabled:
            return []

        domain = self._get_company_domain(contact)
        if not settings.PREDICTLEADS_API_KEY or not settings.PREDICTLEADS_API_TOKEN or not domain:
            return []

        headers = {
            "X-Api-Key": settings.PREDICTLEADS_API_KEY,
            "X-Api-Token": settings.PREDICTLEADS_API_TOKEN,
        }
        signals: List[Dict[str, Any]] = []
        cutoff = datetime.utcnow() - timedelta(days=90)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Financing events → FUNDING_ROUND
                fin_resp = await client.get(
                    f"https://predictleads.com/api/v3/companies/{domain}/financing_events",
                    headers=headers,
                )
                if fin_resp.status_code in (401, 402, 403):
                    logger.warning("PredictLeads authentication or billing error. Disabling PredictLeads for this run.", status=fin_resp.status_code, domain=domain)
                    self._predictleads_disabled = True
                    return []

                if fin_resp.status_code == 200:
                    events = fin_resp.json().get("data", [])
                    recent = [
                        e for e in events
                        if self._parse_iso(e.get("attributes", {}).get("announced_on")
                                            or e.get("attributes", {}).get("first_seen_at")) >= cutoff
                    ]
                    if recent:
                        latest = recent[0].get("attributes", {})
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.FUNDING_ROUND,
                            "signal_source": "predictleads",
                            "confidence": weights.get(SignalType.FUNDING_ROUND, DEFAULT_WEIGHTS[SignalType.FUNDING_ROUND]),
                            "raw_data": {
                                "event_count": len(recent),
                                "round_type": latest.get("round_type") or latest.get("category"),
                                "amount": latest.get("amount"),
                            },
                        })
                elif fin_resp.status_code not in (404,):
                    logger.warning("PredictLeads financing_events non-200", domain=domain, status=fin_resp.status_code)

                # News events → NEWS_EXPANSION (structured category match, no keyword guessing)
                news_resp = await client.get(
                    f"https://predictleads.com/api/v3/companies/{domain}/news_events",
                    headers=headers,
                )
                if news_resp.status_code == 200:
                    events = news_resp.json().get("data", [])
                    recent = [
                        e for e in events
                        if self._parse_iso(e.get("attributes", {}).get("published_at")
                                            or e.get("attributes", {}).get("first_seen_at")) >= cutoff
                        and (e.get("attributes", {}).get("category") in self._PREDICTLEADS_EXPANSION_CATEGORIES)
                    ]
                    if recent:
                        latest = recent[0].get("attributes", {})
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.NEWS_EXPANSION,
                            "signal_source": "predictleads",
                            "confidence": weights.get(SignalType.NEWS_EXPANSION, DEFAULT_WEIGHTS[SignalType.NEWS_EXPANSION]),
                            "raw_data": {
                                "event_count": len(recent),
                                "category": latest.get("category"),
                                "headline": latest.get("title") or latest.get("headline"),
                            },
                        })
                elif news_resp.status_code not in (404,):
                    logger.warning("PredictLeads news_events non-200", domain=domain, status=news_resp.status_code)

                # Job openings → NEW_HIRE (leadership roles), complements Adzuna where
                # its country coverage is thin, since PredictLeads scrapes career pages directly
                jobs_resp = await client.get(
                    f"https://predictleads.com/api/v3/companies/{domain}/job_openings",
                    headers=headers,
                    params={"page[size]": 25},
                )
                if jobs_resp.status_code == 200:
                    jobs = jobs_resp.json().get("data", [])
                    leadership = [
                        j for j in jobs
                        if j.get("attributes", {}).get("seniority") in {"c_level", "vice_president", "head", "director"}
                    ]
                    if leadership:
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.NEW_HIRE,
                            "signal_source": "predictleads",
                            "confidence": weights.get(SignalType.NEW_HIRE, DEFAULT_WEIGHTS[SignalType.NEW_HIRE]),
                            "raw_data": {
                                "trigger": "leadership_hire",
                                "roles": [j.get("attributes", {}).get("title") for j in leadership][:20],
                            },
                        })
                elif jobs_resp.status_code not in (404,):
                    logger.warning("PredictLeads job_openings non-200", domain=domain, status=jobs_resp.status_code)

                # Technologies Used → TECH_STACK_CHANGE
                tech_resp = await client.get(
                    f"https://predictleads.com/api/v3/companies/{domain}/technologies",
                    headers=headers,
                )
                if tech_resp.status_code == 200:
                    techs = tech_resp.json().get("data", [])
                    recent_techs = [
                        t for t in techs
                        if self._parse_iso(t.get("attributes", {}).get("first_seen_at") 
                                           or t.get("attributes", {}).get("announced_on")
                                           or t.get("attributes", {}).get("first_detected_on")
                                           or t.get("attributes", {}).get("added_on")) >= cutoff
                    ]
                    if recent_techs:
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.TECH_STACK_CHANGE,
                            "signal_source": "predictleads",
                            "confidence": weights.get(SignalType.TECH_STACK_CHANGE, DEFAULT_WEIGHTS[SignalType.TECH_STACK_CHANGE]),
                            "raw_data": {
                                "tech_count": len(recent_techs),
                                "technologies": [t.get("attributes", {}).get("name") for t in recent_techs][:20],
                                "categories": [t.get("attributes", {}).get("category") for t in recent_techs][:20],
                            },
                        })
                elif tech_resp.status_code not in (404,):
                    logger.warning("PredictLeads technologies non-200", domain=domain, status=tech_resp.status_code)

            return signals
        except Exception as exc:
            logger.warning("PredictLeads check failed", domain=domain, error=str(exc))
            return []

    @staticmethod
    def _parse_iso(value: Optional[str]) -> datetime:
        if not value:
            return datetime.min
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return datetime.min

    @staticmethod
    def _is_headline_relevant(headline: str, cleaned_company: str, original_company: str) -> bool:
        if not headline:
            return False
            
        def normalize(t: str) -> str:
            t = t.lower()
            t = re.sub(r"[^\w\s\-]", "", t)
            t = re.sub(r"\s+", " ", t)
            return t.strip()

        norm_headline = normalize(headline)
        norm_cleaned = normalize(cleaned_company)
        norm_original = normalize(original_company)

        # Check if either normalized cleaned name or original name exists as a substring/word in headline
        if norm_cleaned in norm_headline or norm_original in norm_headline:
            return True
            
        # Check hyphen/space variations
        if "-" in norm_cleaned:
            space_cleaned = norm_cleaned.replace("-", " ")
            if space_cleaned in norm_headline:
                return True
            no_space_cleaned = norm_cleaned.replace("-", "")
            if no_space_cleaned in norm_headline:
                return True

        if "-" in norm_original:
            space_original = norm_original.replace("-", " ")
            if space_original in norm_headline:
                return True
            no_space_original = norm_original.replace("-", "")
            if no_space_original in norm_headline:
                return True

        return False

    async def _check_currents(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        """Supplementary keyword-matched news via Currents API (higher free-tier
        rate limit than NewsAPI, commercial use allowed). Same matching logic as
        the legacy _check_news so results stay comparable."""
        company = self._clean_company_name(contact.company)
        if not settings.CURRENTS_API_KEY or not company:
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://api.currentsapi.services/v1/search",
                    params={
                        "keywords": company,
                        "language": "en",
                        "start_date": (datetime.utcnow() - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    headers={
                        "Authorization": settings.CURRENTS_API_KEY,
                    },
                )
                response.raise_for_status()

            articles = response.json().get("news", [])
            if not articles:
                return []

            signals: List[Dict[str, Any]] = []
            detected_types = set()

            for a in articles:
                title = a.get("title", "")
                if not self._is_headline_relevant(title, company, contact.company):
                    continue
                description = a.get("description") or ""
                article_text = f"{title} {description}".lower()

                if SignalType.FUNDING_ROUND not in detected_types:
                    if _has_keyword(article_text, ["funding", "raised", "series a", "series b", "series c", "investment", "venture", "round", "ipo", "capital"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.FUNDING_ROUND,
                            "signal_source": "currents",
                            "confidence": weights.get(SignalType.FUNDING_ROUND, DEFAULT_WEIGHTS[SignalType.FUNDING_ROUND]),
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": a.get("url")
                            },
                        })
                        detected_types.add(SignalType.FUNDING_ROUND)

                if SignalType.NEWS_EXPANSION not in detected_types:
                    if _has_keyword(article_text, ["expansion", "new market", "launch", "opens office", "acquires", "acquisition", "partnership", "collaboration", "growth", "unveils new product", "launches new platform"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.NEWS_EXPANSION,
                            "signal_source": "currents",
                            "confidence": weights.get(SignalType.NEWS_EXPANSION, DEFAULT_WEIGHTS[SignalType.NEWS_EXPANSION]),
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": a.get("url")
                            },
                        })
                        detected_types.add(SignalType.NEWS_EXPANSION)

                if SignalType.EARNINGS_CALL not in detected_types:
                    if _has_keyword(article_text, ["earnings call", "quarterly results", "financial report", "q1 results", "q2 results", "q3 results", "q4 results", "net income", "revenue reports", "financial results"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.EARNINGS_CALL,
                            "signal_source": "currents",
                            "confidence": weights.get(SignalType.EARNINGS_CALL, DEFAULT_WEIGHTS[SignalType.EARNINGS_CALL]),
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": a.get("url")
                            },
                        })
                        detected_types.add(SignalType.EARNINGS_CALL)

                if SignalType.NEW_HIRE not in detected_types:
                    if _has_keyword(article_text, ["appoints", "joins as", "hires new", "c-level", "chief executive", "cfo", "cto", "vice president", "executive team", "executive appointment", "welcomes new"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.NEW_HIRE,
                            "signal_source": "currents",
                            "confidence": weights.get(SignalType.NEW_HIRE, DEFAULT_WEIGHTS[SignalType.NEW_HIRE]),
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": a.get("url")
                            },
                        })
                        detected_types.add(SignalType.NEW_HIRE)

            return signals
        except Exception as exc:
            logger.warning("Currents API check failed", company=company, error=str(exc))
            return []

    async def _check_news(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        company = self._clean_company_name(contact.company)
        if not settings.NEWS_API_KEY or not company:
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": f'"{company}"',
                        "sortBy": "publishedAt",
                        "language": "en",
                        "pageSize": 15,
                        "from": (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"),
                    },
                    headers={"X-Api-Key": settings.NEWS_API_KEY},
                )
                response.raise_for_status()

            articles = response.json().get("articles", [])
            if not articles:
                return []

            signals: List[Dict[str, Any]] = []
            detected_types = set()

            for article in articles:
                title = article.get("title", "")
                if not self._is_headline_relevant(title, company, contact.company):
                    continue
                description = article.get("description") or ""
                article_text = f"{title} {description}".lower()

                if SignalType.FUNDING_ROUND not in detected_types:
                    if _has_keyword(article_text, ["funding", "raised", "series a", "series b", "series c", "investment", "venture", "round", "ipo", "capital"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.FUNDING_ROUND,
                            "signal_source": "newsapi",
                            "confidence": weights.get(SignalType.FUNDING_ROUND, DEFAULT_WEIGHTS[SignalType.FUNDING_ROUND]),
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": article.get("url")
                            },
                        })
                        detected_types.add(SignalType.FUNDING_ROUND)

                if SignalType.NEWS_EXPANSION not in detected_types:
                    if _has_keyword(article_text, ["expansion", "new market", "launch", "opens office", "acquires", "acquisition", "partnership", "collaboration", "growth", "unveils new product", "launches new platform"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.NEWS_EXPANSION,
                            "signal_source": "newsapi",
                            "confidence": weights.get(SignalType.NEWS_EXPANSION, DEFAULT_WEIGHTS[SignalType.NEWS_EXPANSION]),
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": article.get("url")
                            },
                        })
                        detected_types.add(SignalType.NEWS_EXPANSION)

                if SignalType.EARNINGS_CALL not in detected_types:
                    if _has_keyword(article_text, ["earnings call", "quarterly results", "financial report", "q1 results", "q2 results", "q3 results", "q4 results", "net income", "revenue reports", "financial results"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.EARNINGS_CALL,
                            "signal_source": "newsapi",
                            "confidence": weights.get(SignalType.EARNINGS_CALL, DEFAULT_WEIGHTS[SignalType.EARNINGS_CALL]),
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": article.get("url")
                            },
                        })
                        detected_types.add(SignalType.EARNINGS_CALL)

                if SignalType.NEW_HIRE not in detected_types:
                    if _has_keyword(article_text, ["appoints", "joins as", "hires new", "c-level", "chief executive", "cfo", "cto", "vice president", "executive team", "executive appointment", "welcomes new"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.NEW_HIRE,
                            "signal_source": "newsapi",
                            "confidence": weights.get(SignalType.NEW_HIRE, DEFAULT_WEIGHTS[SignalType.NEW_HIRE]),
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": article.get("url")
                            },
                        })
                        detected_types.add(SignalType.NEW_HIRE)

            return signals
        except Exception as exc:
            logger.warning("NewsAPI check failed", company=company, error=str(exc))
            return []

    async def _check_apify(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        company = self._clean_company_name(contact.company)
        if not company or not settings.APIFY_API_TOKEN:
            return []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Trigger Apify Reddit Scraper actor searching for company name
                resp = await client.post(
                    "https://api.apify.com/v2/acts/automation-lab~reddit-scraper/runs",
                    headers={"Authorization": f"Bearer {settings.APIFY_API_TOKEN}"},
                    json={
                        "searchQueries": [company],
                        "searchType": "posts",
                        "maxPosts": 5,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                run_data = resp.json().get("data", {})
                run_id = run_data.get("id")
                
                if not run_id:
                    return []
                    
                # Poll for scraper run (simple sleep)
                await asyncio.sleep(15)
                
                result_resp = await client.get(
                    f"https://api.apify.com/v2/acts/automation-lab~reddit-scraper/runs/{run_id}/dataset/items",
                    headers={"Authorization": f"Bearer {settings.APIFY_API_TOKEN}"},
                )
                
                if result_resp.status_code == 200:
                    items = result_resp.json()
                    if items:
                        headline = items[0].get("title", f"Social discussions about {company}")
                        return [{
                            "contact_id": contact.id,
                            "signal_type": SignalType.SOCIAL_ENGAGEMENT,
                            "signal_source": "apify_reddit",
                            "confidence": weights.get(SignalType.SOCIAL_ENGAGEMENT, DEFAULT_WEIGHTS[SignalType.SOCIAL_ENGAGEMENT]),
                            "raw_data": {
                                "mention_count": len(items),
                                "headline": headline,
                                "urls": [item.get("url") for item in items if item.get("url")][:5]
                             }
                        }]
            return []
        except Exception as exc:
            logger.warning("Apify check failed", company=company, error=str(exc))
            return []

    async def _save_signals(self, signals: List[Dict[str, Any]]) -> int:
        saved = 0
        for signal in signals:
            # 1. Time-based rolling window deduplication (same type within 24h)
            existing_time = await self.db.execute(
                select(SignalEvent).where(
                    and_(
                        SignalEvent.contact_id == signal["contact_id"],
                        SignalEvent.signal_type == signal["signal_type"].value,
                        SignalEvent.detected_at >= datetime.utcnow() - timedelta(hours=settings.SIGNAL_DEDUP_HOURS),
                    )
                )
            )
            if existing_time.scalar_one_or_none():
                continue

            # 2. Article-based deduplication (same headline or url regardless of time window)
            raw_data = signal.get("raw_data") or {}
            headline = raw_data.get("headline")
            url = raw_data.get("url")
            
            if headline or url:
                clauses = []
                if headline:
                    clauses.append(SignalEvent.raw_data["headline"].astext == headline)
                if url:
                    clauses.append(SignalEvent.raw_data["url"].astext == url)
                
                existing_article = await self.db.execute(
                    select(SignalEvent).where(
                        and_(
                            SignalEvent.contact_id == signal["contact_id"],
                            or_(*clauses)
                        )
                    )
                )
                if existing_article.scalar_one_or_none():
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
        contact_signals: Dict[Any, List[Dict[str, Any]]] = {}
        for signal in signals:
            contact_id = signal["contact_id"]
            if contact_id not in contact_signals:
                contact_signals[contact_id] = []
            contact_signals[contact_id].append(signal)

        updated = 0
        for contact_id, sigs in contact_signals.items():
            result = await self.db.execute(select(Contact).where(Contact.id == contact_id))
            contact = result.scalar_one_or_none()
            if contact:
                best_sig = max(sigs, key=lambda s: s["confidence"])
                contact.signal_score = best_sig["confidence"] * 100
                
                # Combine unique signal types as comma-separated
                sig_types = sorted(list(set(s["signal_type"].value for s in sigs)))
                contact.signal_type = ",".join(sig_types)
                
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
        any_source_configured = any([
            settings.ADZUNA_APP_ID,
            settings.PREDICTLEADS_API_KEY,
            settings.CURRENTS_API_KEY,
            settings.NEWS_API_KEY,
        ])
        if not any_source_configured:
            return "A2 skipped external checks because no signal source (Adzuna / PredictLeads / Currents / NewsAPI) is configured"
        if not signals:
            return "No qualifying buying signals found across configured sources"
        if saved == 0:
            return "Signals were detected but all were duplicates inside the dedupe window"
        return f"Saved {saved} new buying signal(s)"
