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
import email.utils
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import hashlib
import httpx
import structlog
from sqlalchemy import and_, or_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.signal_formatter import clean_html_text, format_clean_signal_summary, resolve_signal_article_url, generate_factual_signal_summary
from app.core.config import settings
from app.models.models import (
    Contact, FunnelEvent, SignalConversionRegistry, SignalEvent, SignalType,
    Notification, ContactUserInputAssociation, UserInput
)

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
        self._apify_disabled = False
        self._currents_disabled = False
        self._newsapi_disabled = False

    async def run(self, contact_ids: Optional[List[str]] = None, user_input_id: Optional[int] = None) -> Dict[str, Any]:
        logger.info("A2 starting", user_input_id=user_input_id)

        weights = await self._load_registry()
        contacts = await self._get_contacts(contact_ids, user_input_id=user_input_id)
        logger.info("Scanning contacts", count=len(contacts))

        all_signals: List[Dict[str, Any]] = []
        for contact in contacts:
            all_signals.extend(await self._detect_signals(contact, weights))
            # Paced rate limit delay
            await asyncio.sleep(0.05)

        saved = await self._save_signals(all_signals, user_input_id=user_input_id)
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

    async def _get_contacts(self, contact_ids: Optional[List[str]], user_input_id: Optional[int] = None) -> List[Contact]:
        if contact_ids:
            result = await self.db.execute(
                select(Contact).where(
                    and_(Contact.id.in_(contact_ids), Contact.do_not_contact.is_(False))
                )
            )
        elif user_input_id is not None:
            result = await self.db.execute(
                select(Contact).where(
                    and_(
                        Contact.user_input_id == user_input_id,
                        Contact.do_not_contact.is_(False),
                        or_(Contact.icp_score.is_(None), Contact.icp_score >= 40),
                        Contact.email_valid.is_not(False),
                    )
                ).limit(500)
            )
        else:
            result = await self.db.execute(
                select(Contact).where(
                    and_(
                        Contact.do_not_contact.is_(False),
                        or_(Contact.icp_score.is_(None), Contact.icp_score >= 40),
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
            self._check_google_news_rss(contact, weights),
            self._check_website_tech_stack(contact, weights),
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

            raw_jobs = response.json().get("results", [])
            if not raw_jobs:
                return []

            # Filter jobs strictly to the contact's company
            jobs = []
            for j in raw_jobs:
                job_comp = (j.get("company", {}).get("display_name") or "").strip()
                if not job_comp:
                    continue
                if self._is_company_name_match(job_comp, company, contact.company):
                    jobs.append(j)

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

            first_job = jobs[0] if jobs else {}
            job_created_str = first_job.get("created")
            occurred_at = self._parse_iso(job_created_str)
            if occurred_at == datetime.min:
                occurred_at = None

            signals: List[Dict[str, Any]] = []
            if any(term in job_text for term in ["sdr", "bdr", "sales development", "business development rep", "hiring", "recruiting", "sales", "careers", "we are hiring", "open position"]):
                job_url = resolve_signal_article_url(first_job.get("redirect_url") or first_job.get("url"))
                clean_job_desc = clean_html_text(first_job.get("description"))
                job_data = {
                    "job_count": len(jobs),
                    "roles": titles,
                    "locations": locations,
                    "url": job_url,
                    "headline": clean_html_text(first_job.get("title")),
                    "description": clean_job_desc,
                    "published_at": occurred_at.isoformat() if occurred_at else None,
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
                    "occurred_at": occurred_at,
                    "raw_data": job_data,
                })

            if any(term in job_text for term in ["vp of sales", "director of sales", "chief revenue", "head of sales"]):
                lead_job = next((j for j in jobs if any(t in j.get("title", "").lower() for t in ["director", "vp", "chief", "head"])), first_job)
                lead_created = self._parse_iso(lead_job.get("created"))
                lead_occurred = lead_created if lead_created != datetime.min else occurred_at
                if lead_occurred == datetime.min:
                    lead_occurred = None
                signals.append({
                    "contact_id": contact.id,
                    "signal_type": SignalType.NEW_HIRE,
                    "signal_source": "adzuna",
                    "confidence": weights.get(SignalType.NEW_HIRE, DEFAULT_WEIGHTS[SignalType.NEW_HIRE]),
                    "occurred_at": lead_occurred,
                    "raw_data": {
                        "trigger": "leadership_hire",
                        "roles": [title for title in titles if "director" in title or "vp" in title][:20],
                        "url": lead_job.get("redirect_url"),
                        "headline": lead_job.get("title"),
                        "description": lead_job.get("description"),
                        "published_at": lead_occurred.isoformat(),
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
                    "occurred_at": occurred_at,
                    "raw_data": {
                        "trigger": "geographic_expansion",
                        "locations": expansion_locations,
                        "url": first_job.get("redirect_url"),
                        "headline": f"Geographic expansion detected via hiring in: {', '.join(expansion_locations[:3])}",
                        "description": first_job.get("description"),
                        "published_at": occurred_at.isoformat(),
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
                        fin_dt = self._parse_iso(latest.get("announced_on") or latest.get("first_seen_at"))
                        fin_occurred = fin_dt if fin_dt != datetime.min else datetime.utcnow()
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.FUNDING_ROUND,
                            "signal_source": "predictleads",
                            "confidence": weights.get(SignalType.FUNDING_ROUND, DEFAULT_WEIGHTS[SignalType.FUNDING_ROUND]),
                            "occurred_at": fin_occurred,
                            "raw_data": {
                                "event_count": len(recent),
                                "round_type": latest.get("round_type") or latest.get("category"),
                                "amount": latest.get("amount"),
                                "headline": latest.get("title") or latest.get("headline") or f"Funding round announced: {latest.get('round_type') or 'investment'}",
                                "description": latest.get("description") or latest.get("summary"),
                                "url": latest.get("source_url") or latest.get("url"),
                                "published_at": fin_occurred.isoformat(),
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
                        news_dt = self._parse_iso(latest.get("published_at") or latest.get("first_seen_at"))
                        news_occurred = news_dt if news_dt != datetime.min else datetime.utcnow()
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.NEWS_EXPANSION,
                            "signal_source": "predictleads",
                            "confidence": weights.get(SignalType.NEWS_EXPANSION, DEFAULT_WEIGHTS[SignalType.NEWS_EXPANSION]),
                            "occurred_at": news_occurred,
                            "raw_data": {
                                "event_count": len(recent),
                                "category": latest.get("category"),
                                "headline": latest.get("title") or latest.get("headline"),
                                "description": latest.get("description") or latest.get("summary"),
                                "url": latest.get("source_url") or latest.get("url"),
                                "published_at": news_occurred.isoformat(),
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
                        first_lead = leadership[0].get("attributes", {})
                        lead_dt = self._parse_iso(first_lead.get("first_seen_at") or first_lead.get("first_detected_on"))
                        lead_occurred = lead_dt if lead_dt != datetime.min else datetime.utcnow()
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.NEW_HIRE,
                            "signal_source": "predictleads",
                            "confidence": weights.get(SignalType.NEW_HIRE, DEFAULT_WEIGHTS[SignalType.NEW_HIRE]),
                            "occurred_at": lead_occurred,
                            "raw_data": {
                                "trigger": "leadership_hire",
                                "roles": [j.get("attributes", {}).get("title") for j in leadership][:20],
                                "published_at": lead_occurred.isoformat(),
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
                        first_tech = recent_techs[0].get("attributes", {})
                        tech_dt = self._parse_iso(first_tech.get("first_seen_at") or first_tech.get("announced_on") or first_tech.get("first_detected_on") or first_tech.get("added_on"))
                        tech_occurred = tech_dt if tech_dt != datetime.min else datetime.utcnow()
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.TECH_STACK_CHANGE,
                            "signal_source": "predictleads",
                            "confidence": weights.get(SignalType.TECH_STACK_CHANGE, DEFAULT_WEIGHTS[SignalType.TECH_STACK_CHANGE]),
                            "occurred_at": tech_occurred,
                            "raw_data": {
                                "tech_count": len(recent_techs),
                                "technologies": [t.get("attributes", {}).get("name") for t in recent_techs][:20],
                                "categories": [t.get("attributes", {}).get("category") for t in recent_techs][:20],
                                "published_at": tech_occurred.isoformat(),
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
            v = str(value).strip().replace("Z", "+00:00")
            if " +" in v or " -" in v:
                v = v.replace(" +", "+").replace(" -", "-")
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            try:
                parsed_dt = email.utils.parsedate_to_datetime(str(value))
                if parsed_dt:
                    if parsed_dt.tzinfo is not None:
                        parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    return parsed_dt
            except Exception:
                pass
            return datetime.min

    GENERIC_NOUN_COLLISIONS = {
        "summit", "affinity", "bridge", "target", "scale", "seed", "blend",
        "box", "nest", "wave", "focus", "pilot", "spark", "drift", "bloom",
        "forge", "frontier", "elevate", "compass", "beacon", "peak", "zenith",
        "apex", "cascade", "horizon", "on", "it", "one", "all"
    }

    @classmethod
    def _is_headline_relevant(cls, headline: str, cleaned_company: str, original_company: str) -> bool:
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

        # Whole-word regex match to avoid partial prefix/substring collisions (e.g. 'helio' matching 'helios')
        for cand in [norm_cleaned, norm_original]:
            if not cand or len(cand) < 2:
                continue

            # Short stopwords like "on", "it" should never match as bare words
            if cand in {"on", "it", "in", "at", "as", "is", "or", "and", "the"}:
                pat_corp = r'(?:\b|_)' + re.escape(cand) + r'\s+(?:services|technologies|inc|corp|llc|solutions|group)(?:\b|_)'
                if re.search(pat_corp, norm_headline):
                    return True
                continue

            pat = r'(?:\b|_)' + re.escape(cand) + r'(?:\b|_)'
            matched = False
            if re.search(pat, norm_headline):
                matched = True
            elif "-" in cand:
                pat_sp = r'(?:\b|_)' + re.escape(cand.replace("-", " ")) + r'(?:\b|_)'
                if re.search(pat_sp, norm_headline):
                    matched = True

            if not matched:
                continue

            # Specific false-positive guards for common dictionary words
            if cand == "summit":
                if re.search(r'\b(?:raise|sam|ai|tech|technology|global|annual|climate|energy|ceo|leadership|world|peace|health|youth|media|virtual|national|regional|mayors|defense|security|economic|industry|investor|partner|developer|g7|g20|un|cop)\s+summit\b', norm_headline):
                    continue
                if re.search(r'\bsummit\s+(?:series|conference|meeting|expo|forum|event|festival|rally|talks|dialogue|sierra|park|county|valley|lake|ridge|peak|hotel|resort|mall)\b', norm_headline):
                    continue

            if cand == "affinity":
                if re.search(r'\b(?:brand\s+affinity|affinity\s+groups?|affinity\s+fraud|affinity\s+card|affinity\s+marketing|affinity\s+diagram|affinity\s+bias|natural\s+affinity|chemical\s+affinity|electron\s+affinity)\b', norm_headline):
                    continue

            # For generic single dictionary nouns, guard against common idioms
            if cand in cls.GENERIC_NOUN_COLLISIONS and len(cand.split()) == 1:
                if cand == "target" and re.search(r'\b(?:on\s+target|hit\s+target|sales\s+target|target\s+audience|target\s+market)\b', norm_headline):
                    continue
                if cand == "bridge" and re.search(r'\b(?:bridge\s+the\s+gap|bridge\s+loan|bridge\s+financing|covered\s+bridge|golden\s+gate\s+bridge)\b', norm_headline):
                    continue
                if cand == "scale" and re.search(r'\b(?:at\s+scale|to\s+scale|large\s+scale|small\s+scale|sliding\s+scale)\b', norm_headline):
                    continue

            return True

        return False

    @classmethod
    def _is_company_name_match(cls, job_comp: str, cleaned_company: str, original_company: str) -> bool:
        """Strictly match hiring company name from job board against target prospect company."""
        if not job_comp or not (cleaned_company or original_company):
            return False

        def clean_comp(name: str) -> str:
            name = name.lower()
            name = re.sub(r"\(.*?\)", "", name)
            for d in [" | ", " - ", " — ", " , "]:
                if d in name:
                    name = name.split(d)[0]
            if ", " in name:
                name = name.split(", ")[0]
            name = re.sub(r"[^\w\s]", "", name)
            suffixes = [
                "corporation", "corp", "incorporated", "inc", "limited", "ltd",
                "llc", "association", "assn", "technologies", "technology", "tech",
                "solutions", "services", "systems", "group", "holdings", "worldwide",
                "international", "intl"
            ]
            tokens = [t for t in name.split() if t]
            while tokens and tokens[-1] in suffixes:
                tokens.pop()
            if tokens and tokens[0] == "the":
                tokens.pop(0)
            return " ".join(tokens).strip()

        norm_job = clean_comp(job_comp)
        norm_target_clean = clean_comp(cleaned_company)
        norm_target_orig = clean_comp(original_company)

        # Exact match after suffix stripping
        for cand in [norm_target_clean, norm_target_orig]:
            if not cand:
                continue
            if norm_job == cand:
                return True

        # If target company is a single generic noun (e.g. "summit", "bridge", "target"),
        # do NOT allow substring or multi-word additions (e.g. "the summit sierra" is NOT "summit")
        cand_words = set(norm_target_clean.split())
        if cand_words.intersection(cls.GENERIC_NOUN_COLLISIONS) or len(norm_target_clean.split()) == 1:
            return False

        # For non-generic multi-word names, allow clean prefix/suffix matches
        if norm_target_clean and (norm_job.startswith(norm_target_clean + " ") or norm_target_clean.startswith(norm_job + " ")):
            return True

        return False

    async def _check_currents(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        """Supplementary keyword-matched news via Currents API (higher free-tier
        rate limit than NewsAPI, commercial use allowed). Same matching logic as
        the legacy _check_news so results stay comparable."""
        if self._currents_disabled:
            return []

        company = self._clean_company_name(contact.company)
        if not settings.CURRENTS_API_KEY or not company:
            return []

        try:
            async with httpx.AsyncClient(timeout=10) as client:
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
                if response.status_code in (401, 402, 403, 429):
                    logger.warning("Currents API rate limit or auth error. Disabling Currents for this run.", status=response.status_code)
                    self._currents_disabled = True
                    return []
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
                pub_date_str = a.get("published")
                occurred_at = self._parse_iso(pub_date_str)
                if occurred_at == datetime.min:
                    occurred_at = datetime.utcnow()

                if SignalType.FUNDING_ROUND not in detected_types:
                    if _has_keyword(article_text, ["funding", "raised", "series a", "series b", "series c", "investment", "venture", "round", "ipo", "capital"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.FUNDING_ROUND,
                            "signal_source": "currents",
                            "confidence": weights.get(SignalType.FUNDING_ROUND, DEFAULT_WEIGHTS[SignalType.FUNDING_ROUND]),
                            "occurred_at": occurred_at,
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": a.get("url"),
                                "published_at": occurred_at.isoformat(),
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
                            "occurred_at": occurred_at,
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": a.get("url"),
                                "published_at": occurred_at.isoformat(),
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
                            "occurred_at": occurred_at,
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": a.get("url"),
                                "published_at": occurred_at.isoformat(),
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
                            "occurred_at": occurred_at,
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": a.get("url"),
                                "published_at": occurred_at.isoformat(),
                            },
                        })
                        detected_types.add(SignalType.NEW_HIRE)

            return signals
        except Exception as exc:
            logger.warning("Currents API check failed", company=company, error=str(exc))
            return []

    async def _check_news(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        if self._newsapi_disabled:
            return []

        company = self._clean_company_name(contact.company)
        if not settings.NEWS_API_KEY or not company:
            return []

        try:
            async with httpx.AsyncClient(timeout=10) as client:
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
                if response.status_code in (401, 402, 403, 429):
                    logger.warning("NewsAPI rate limit or auth error. Disabling NewsAPI for this run.", status=response.status_code)
                    self._newsapi_disabled = True
                    return []
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
                pub_date_str = article.get("publishedAt")
                occurred_at = self._parse_iso(pub_date_str)
                if occurred_at == datetime.min:
                    occurred_at = datetime.utcnow()

                if SignalType.FUNDING_ROUND not in detected_types:
                    if _has_keyword(article_text, ["funding", "raised", "series a", "series b", "series c", "investment", "venture", "round", "ipo", "capital"]):
                        signals.append({
                            "contact_id": contact.id,
                            "signal_type": SignalType.FUNDING_ROUND,
                            "signal_source": "newsapi",
                            "confidence": weights.get(SignalType.FUNDING_ROUND, DEFAULT_WEIGHTS[SignalType.FUNDING_ROUND]),
                            "occurred_at": occurred_at,
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": article.get("url"),
                                "published_at": occurred_at.isoformat(),
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
                            "occurred_at": occurred_at,
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": article.get("url"),
                                "published_at": occurred_at.isoformat(),
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
                            "occurred_at": occurred_at,
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": article.get("url"),
                                "published_at": occurred_at.isoformat(),
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
                            "occurred_at": occurred_at,
                            "raw_data": {
                                "article_count": len(articles),
                                "headline": title,
                                "description": description,
                                "url": article.get("url"),
                                "published_at": occurred_at.isoformat(),
                            },
                        })
                        detected_types.add(SignalType.NEW_HIRE)

            return signals
        except Exception as exc:
            logger.warning("NewsAPI check failed", company=company, error=str(exc))
            return []

    async def _check_apify(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        if self._apify_disabled:
            return []

        company = self._clean_company_name(contact.company)
        if not company or not settings.APIFY_API_TOKEN:
            return []

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Trigger Apify Reddit Scraper actor searching for company name
                resp = await client.post(
                    "https://api.apify.com/v2/acts/automation-lab~reddit-scraper/runs",
                    headers={"Authorization": f"Bearer {settings.APIFY_API_TOKEN}"},
                    json={
                        "searchQueries": [company],
                        "searchType": "posts",
                        "maxPosts": 5,
                    },
                    timeout=10,
                )
                if resp.status_code in (401, 402, 403, 429):
                    logger.warning("Apify auth or billing error. Disabling Apify for this run.", status=resp.status_code)
                    self._apify_disabled = True
                    return []
                resp.raise_for_status()
                run_data = resp.json().get("data", {})
                run_id = run_data.get("id")
                
                if not run_id:
                    return []
                
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

    async def _check_google_news_rss(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        """Free, no-API-key Google News RSS scanner for 90-day press releases, funding, and hiring news."""
        company = self._clean_company_name(contact.company)
        if not company:
            return []

        try:
            # Query Google News RSS for company with high-intent keywords over last 90 days
            query = f'"{company}" (funding OR expansion OR hired OR partnership OR launch OR earnings OR "series") when:90d'
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(
                    "https://news.google.com/rss/search",
                    params={
                        "q": query,
                        "hl": "en-US",
                        "gl": "US",
                        "ceid": "US:en",
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )
                if response.status_code != 200:
                    return []

            root = ET.fromstring(response.text)
            items = root.findall(".//item")
            if not items:
                return []

            signals: List[Dict[str, Any]] = []
            detected_types = set()

            for item in items[:15]:
                title_elem = item.find("title")
                title = title_elem.text if title_elem is not None and title_elem.text else ""

                if not self._is_headline_relevant(title, company, contact.company):
                    continue

                desc_elem = item.find("description")
                raw_description = desc_elem.text if desc_elem is not None and desc_elem.text else ""
                link_elem = item.find("link")
                article_url = link_elem.text if link_elem is not None and link_elem.text else ""

                pub_elem = item.find("pubDate")
                pub_str = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else ""
                occurred_at = None
                if pub_str:
                    try:
                        parsed_dt = email.utils.parsedate_to_datetime(pub_str)
                        if parsed_dt:
                            if parsed_dt.tzinfo is not None:
                                parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
                            occurred_at = parsed_dt
                    except Exception:
                        occurred_at = None

                clean_head = clean_html_text(title)
                clean_desc = clean_html_text(raw_description)
                article_text = f"{clean_head} {clean_desc}".lower()

                # Decode real destination article URL from Google News redirect
                resolved_url = resolve_signal_article_url(article_url) or article_url

                def _make_google_signal(sig_type: SignalType, item_occurred_at: Optional[datetime]) -> Dict[str, Any]:
                    factual_summary = generate_factual_signal_summary(
                        signal_type=sig_type.value,
                        headline=clean_head,
                        company=company,
                        raw_description=clean_desc,
                    )
                    return {
                        "contact_id": contact.id,
                        "signal_type": sig_type,
                        "signal_source": "google_news_rss",
                        "confidence": weights.get(sig_type, DEFAULT_WEIGHTS[sig_type]),
                        "summary": factual_summary,
                        "occurred_at": item_occurred_at,
                        "raw_data": {
                            "headline": clean_head,
                            "description": factual_summary,
                            "url": resolved_url,
                            "google_news_url": article_url,
                            "source": "Google News",
                            "published_at": item_occurred_at.isoformat() if item_occurred_at else None,
                        },
                    }

                if SignalType.FUNDING_ROUND not in detected_types:
                    if _has_keyword(article_text, ["funding", "raised", "series a", "series b", "series c", "investment", "venture", "round", "ipo", "capital"]):
                        signals.append(_make_google_signal(SignalType.FUNDING_ROUND, occurred_at))
                        detected_types.add(SignalType.FUNDING_ROUND)

                if SignalType.NEWS_EXPANSION not in detected_types:
                    if _has_keyword(article_text, ["expansion", "new market", "launch", "opens office", "acquires", "acquisition", "partnership", "collaboration", "growth", "unveils new product", "launches new platform"]):
                        signals.append(_make_google_signal(SignalType.NEWS_EXPANSION, occurred_at))
                        detected_types.add(SignalType.NEWS_EXPANSION)

                if SignalType.EARNINGS_CALL not in detected_types:
                    if _has_keyword(article_text, ["earnings call", "quarterly results", "financial report", "q1 results", "q2 results", "q3 results", "q4 results", "net income", "revenue reports", "financial results"]):
                        signals.append(_make_google_signal(SignalType.EARNINGS_CALL, occurred_at))
                        detected_types.add(SignalType.EARNINGS_CALL)

                if SignalType.NEW_HIRE not in detected_types:
                    if _has_keyword(article_text, ["appoints", "joins as", "hires new", "c-level", "chief executive", "cfo", "cto", "vice president", "executive team", "executive appointment", "welcomes new"]):
                        signals.append(_make_google_signal(SignalType.NEW_HIRE, occurred_at))
                        detected_types.add(SignalType.NEW_HIRE)

            return signals
        except Exception as exc:
            logger.warning("Google News RSS check failed", company=company, error=str(exc))
            return []

    ENTERPRISE_SALES_CRM_TOOLS = {
        "Salesforce": ["salesforce.com", "force.com", "pi.pardot.com", "pardot.com"],
        "HubSpot": ["js.hs-scripts.com", "hs-analytics", "hubspot.com"],
        "Marketo": ["marketo.net", "munchkin.marketo.net"],
        "Gong": ["gong.io", "web.gong.io"],
        "6sense": ["6sc.co", "6sense.com"],
        "Demandbase": ["demandbase.com", "tag.demandbase.com"],
        "Apollo.io": ["apollo.io", "assets.apollo.io"],
        "ZoomInfo": ["ws.zoominfo.com"],
        "Drift": ["js.driftt.com"],
        "Intercom": ["widget.intercom.io", "intercomcdn.com"],
    }

    async def _check_website_tech_stack(self, contact: Contact, weights: Dict[SignalType, float]) -> List[Dict[str, Any]]:
        """Direct website HTML fingerprinting for enterprise CRM and sales engagement stack detection."""
        domain = self._get_company_domain(contact)
        if not domain:
            return []

        try:
            target_url = f"https://{domain}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            async with httpx.AsyncClient(timeout=10, follow_redirects=True, verify=False) as client:
                try:
                    response = await client.get(target_url, headers=headers)
                except httpx.RequestError:
                    response = await client.get(f"http://{domain}", headers=headers)

            if response.status_code != 200:
                return []

            html_lower = response.text.lower()
            detected_enterprise = []

            for tech_name, signatures in self.ENTERPRISE_SALES_CRM_TOOLS.items():
                for sig in signatures:
                    if sig.lower() in html_lower:
                        detected_enterprise.append(tech_name)
                        break

            # Strictly require at least one verified enterprise RevOps/CRM tool.
            # Generic utilities (Google Tag Manager, Stripe, Zendesk) alone do not constitute a buying signal.
            if not detected_enterprise:
                return []

            # Calibrate confidence based on depth of enterprise sales stack:
            # 2+ enterprise tools = 0.55; 1 enterprise tool = 0.40
            confidence = 0.55 if len(detected_enterprise) >= 2 else 0.40

            occurred_at = datetime.utcnow()
            primary_techs = ", ".join(detected_enterprise[:4])
            return [{
                "contact_id": contact.id,
                "signal_type": SignalType.TECH_STACK_CHANGE,
                "signal_source": "website_fingerprint",
                "confidence": confidence,
                "occurred_at": occurred_at,
                "raw_data": {
                    "tech_count": len(detected_enterprise),
                    "technologies": detected_enterprise,
                    "headline": f"Enterprise sales tech detected on {domain}: {primary_techs}",
                    "description": f"Website fingerprinting verified {len(detected_enterprise)} enterprise sales/CRM tool(s): {', '.join(detected_enterprise)}.",
                    "url": target_url,
                    "is_company_website": True,
                    "published_at": occurred_at.isoformat(),
                },
            }]
        except Exception as exc:
            logger.debug("Website tech stack fingerprinting skipped or failed", domain=domain, error=str(exc))
            return []

    async def _generate_2_line_signal_summary(self, company_name: str, signals: List[Dict[str, Any]]) -> str:
        """Use LLM to generate a concise 2-sentence summary of detected buying signals."""
        if not signals:
            return ""

        signal_descriptions = []
        for sig in signals:
            sig_type = sig.get("signal_type")
            type_str = sig_type.value if hasattr(sig_type, "value") else str(sig_type)
            raw = sig.get("raw_data") or {}
            headline = raw.get("headline") or raw.get("title") or raw.get("job_title") or raw.get("name") or type_str
            signal_descriptions.append(f"- {type_str}: {headline}")

        signals_text = "\n".join(signal_descriptions[:5])

        system_prompt = (
            "You are a factual B2B Signal Intelligence Analyst. Synthesize detected business signals "
            "into a strictly factual 2-sentence summary (under 45 words total).\n"
            "Rules:\n"
            "1. Write EXACTLY TWO sentences grounded ONLY in the provided signal facts.\n"
            "2. Sentence 1: State what verified events occurred (e.g. specific job openings, expansion reports, or leadership changes) and what company is involved.\n"
            "3. Sentence 2: State the factual business context relevant to commercial or go-to-market operations.\n"
            "4. Strictly avoid speculative conclusions such as 'aggressive market penetration', 'strategic shift', 'ready to invest', 'analyst confidence', or 'buying intent'.\n"
            "5. Do NOT include markdown formatting, bullet points, or dictionary formatting."
        )

        user_prompt = f"Company: {company_name or 'Target Account'}\nSignals Detected:\n{signals_text}"

        try:
            from app.services.llm_service import LLMService
            llm = LLMService()
            res = await llm.complete(system=system_prompt, user=user_prompt, max_tokens=150)
            summary_text = format_clean_signal_summary(res)
            return summary_text.strip()
        except Exception as exc:
            logger.warning("Failed to generate 2-line LLM signal summary", company=company_name, error=str(exc))
            types = list(set(s.get("signal_type").value if hasattr(s.get("signal_type"), "value") else str(s.get("signal_type")) for s in signals))
            clean_types = [t.replace('_', ' ') for t in types[:3]]
            return f"{company_name} has recent activity associated with {', '.join(clean_types)}. These events indicate recent business activity relevant to go-to-market operations."

    @staticmethod
    def _normalize_headline_text(text: Optional[str]) -> str:
        if not text:
            return ""
        # Strip common publication suffixes e.g. " - Yahoo Finance", " | MarketBeat", " - Reuters", " - The Columbus Dispatch"
        t = re.sub(r'\s*[-|–—]\s*([A-Za-z0-9\s.,&]+)$', '', text.strip())
        t = t.lower()
        t = re.sub(r'[^\w\s]', '', t)
        return re.sub(r'\s+', ' ', t).strip()

    @classmethod
    def _signals_overlap(cls, sig1_type: str, sig1_raw: dict, sig2_type: str, sig2_raw: dict, time_delta: timedelta) -> bool:
        u1 = (sig1_raw.get("url") or "").split("?")[0].rstrip("/")
        u2 = (sig2_raw.get("url") or "").split("?")[0].rstrip("/")
        if u1 and u2 and u1 == u2:
            return True

        h1 = sig1_raw.get("headline") or ""
        h2 = sig2_raw.get("headline") or ""
        n1 = cls._normalize_headline_text(h1)
        n2 = cls._normalize_headline_text(h2)

        # Cross-source news article similarity check (Currents vs Google News RSS vs NewsAPI)
        if n1 and n2:
            if n1 == n2 or n1 in n2 or n2 in n1:
                return True
            tok1 = set(w for w in n1.split() if len(w) > 3)
            tok2 = set(w for w in n2.split() if len(w) > 3)
            if tok1 and tok2:
                overlap = len(tok1.intersection(tok2))
                smaller = min(len(tok1), len(tok2))
                if smaller > 0 and (overlap / smaller) >= 0.50:
                    return True

        # Adzuna geographic expansion duplicate check
        if "geographic expansion detected via hiring in" in n1 and "geographic expansion detected via hiring in" in n2:
            return True

        # Specific semantic duplicate checks when signal types match
        if sig1_type == sig2_type:
            # Tech stack change: same technology detected for same contact within 30 days
            if sig1_type == "tech_stack_change" and time_delta.total_seconds() < (30 * 86400):
                tech1 = (sig1_raw.get("tech") or sig1_raw.get("technology") or n1).strip().lower()
                tech2 = (sig2_raw.get("tech") or sig2_raw.get("technology") or n2).strip().lower()
                if tech1 and tech2 and (tech1 == tech2 or tech1 in tech2 or tech2 in tech1):
                    return True

            # If both headlines are identical or substantially similar, it's a duplicate
            if n1 and n2 and (n1 == n2 or n1 in n2 or n2 in n1):
                return True

        return False

    async def _save_signals(self, signals: List[Dict[str, Any]], user_input_id: Optional[int] = None) -> int:
        saved = 0
        processed_in_batch: List[Dict[str, Any]] = []

        for signal in signals:
            sig_type_val = signal["signal_type"].value if hasattr(signal["signal_type"], "value") else str(signal["signal_type"])
            raw_data = signal.get("raw_data") or {}
            headline = raw_data.get("headline") or raw_data.get("title") or ""
            url = raw_data.get("url") or raw_data.get("link") or ""

            # 1. In-batch deduplication across concurrent detectors (e.g. Google RSS vs Currents in same run)
            is_batch_duplicate = False
            for prev_sig in processed_in_batch:
                if prev_sig["contact_id"] == signal["contact_id"]:
                    prev_raw = prev_sig.get("raw_data") or {}
                    prev_type = prev_sig["signal_type"].value if hasattr(prev_sig["signal_type"], "value") else str(prev_sig["signal_type"])
                    if self._signals_overlap(sig_type_val, raw_data, prev_type, prev_raw, timedelta(0)):
                        is_batch_duplicate = True
                        break
            if is_batch_duplicate:
                continue

            # 2. Database cross-source deduplication and cooldown window
            existing_db_sigs = await self.db.execute(
                select(SignalEvent).where(SignalEvent.contact_id == signal["contact_id"])
            )
            existing_rows = existing_db_sigs.scalars().all()

            is_db_duplicate = False
            now = datetime.utcnow()
            for row in existing_rows:
                delta = abs(now - row.detected_at) if row.detected_at else timedelta(days=999)
                row_raw = row.raw_data or {}
                if self._signals_overlap(sig_type_val, raw_data, row.signal_type, row_raw, delta):
                    is_db_duplicate = True
                    break

            if is_db_duplicate:
                continue

            processed_in_batch.append(signal)

            raw_desc = clean_html_text(raw_data.get("description"))
            summary_desc = format_clean_signal_summary(
                signal.get("summary") or raw_desc or headline or f"Detected {sig_type_val} signal via {signal['signal_source']}."
            )

            contact = await self.db.get(Contact, signal["contact_id"])
            contact_user_id = getattr(contact, "user_id", None) if contact else None

            sig_occurred = signal.get("occurred_at")
            sig_event = SignalEvent(
                contact_id=signal["contact_id"],
                user_id=contact_user_id,
                signal_type=sig_type_val,
                signal_source=signal["signal_source"],
                confidence=signal["confidence"],
                conversion_weight=signal["confidence"],
                raw_data=signal.get("raw_data"),
                summary=summary_desc,
                detected_at=sig_occurred if sig_occurred else datetime.utcnow(),
            )
            self.db.add(sig_event)
            await self.db.flush()
            saved += 1

            # Create new_signal notification for the contact's associated session(s)
            try:
                if contact:
                    # Collect all relevant user_input_ids for this contact
                    target_session_ids = set()
                    if user_input_id:
                        target_session_ids.add(user_input_id)
                    if contact.user_input_id:
                        target_session_ids.add(contact.user_input_id)

                    assoc_res = await self.db.execute(
                        select(ContactUserInputAssociation.user_input_id).where(
                            ContactUserInputAssociation.contact_id == contact.id
                        )
                    )
                    for aid in assoc_res.scalars().all():
                        target_session_ids.add(aid)

                    if not target_session_ids:
                        # Fallback to user's latest search session or global latest
                        if contact.user_id:
                            u_latest = await self.db.scalar(
                                select(UserInput.id)
                                .where(UserInput.user_id == contact.user_id)
                                .order_by(UserInput.id.desc())
                                .limit(1)
                            )
                            if u_latest:
                                target_session_ids.add(u_latest)


                    identifier = (url or headline or str(sig_event.id))
                    ref_hash = hashlib.sha256(str(identifier).encode()).hexdigest()[:16]

                    for sess_id in target_session_ids:
                        ref_id = f"signal_{signal['contact_id']}_{sig_type_val}_{sess_id}_{ref_hash}"

                        existing_notif = await self.db.execute(
                            select(Notification.id).where(
                                or_(
                                    Notification.reference_id == ref_id,
                                    Notification.reference_id == f"signal_{signal['contact_id']}_{sig_type_val}_{ref_hash}",
                                )
                            )
                        )
                        if not existing_notif.scalar_one_or_none():
                            c_name = contact.first_name or "Prospect"
                            comp_name = contact.company or "Company"
                            sig_label = sig_type_val.replace("_", " ")
                            notif = Notification(
                                type="new_signal",
                                contact_id=contact.id,
                                user_input_id=sess_id,
                                message=f"New {sig_label} signal for {c_name} at {comp_name}",
                                action_url=f"/contacts/{contact.id}",
                                reference_id=ref_id,
                                expires_at=datetime.utcnow() + timedelta(days=30),
                            )
                            self.db.add(notif)
                            logger.info(
                                "A2: Created new_signal notification",
                                contact_id=contact.id,
                                user_input_id=sess_id,
                                ref_id=ref_id,
                            )
            except Exception as notif_err:
                logger.warning("A2: Failed to create signal notification", error=str(notif_err))

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
                sig_types = sorted(list(set(s["signal_type"].value if hasattr(s["signal_type"], "value") else str(s["signal_type"]) for s in sigs)))
                contact.signal_type = ",".join(sig_types)
                
                # Derive latest_signal_at from actual event dates
                occurred_dates = [
                    s.get("occurred_at")
                    for s in sigs
                    if s.get("occurred_at") and isinstance(s.get("occurred_at"), datetime) and s.get("occurred_at") != datetime.min
                ]
                if occurred_dates:
                    contact.latest_signal_at = max(occurred_dates)
                else:
                    contact.latest_signal_at = None
                
                # Generate 2-line LLM signal summary for the contact
                summary = await self._generate_2_line_signal_summary(contact.company or contact.first_name or "Prospect", sigs)
                if summary:
                    contact.signal_summary = summary

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
        if not signals:
            return "No qualifying buying signals found across configured sources (including Google News RSS and Website Fingerprinting)"
        if saved == 0:
            return "Signals were detected but all were duplicates inside the dedupe window"
        return f"Saved {saved} new buying signal(s)"
