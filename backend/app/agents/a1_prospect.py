"""A1 - Prospect Intelligence Agent.

Apollo is the only discovery and enrichment provider. The agent discovers
net-new people through Apollo search, enriches them through Apollo bulk match,
scores them, persists contacts, and records funnel events for dashboard
visibility.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Dict, List, Tuple

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Contact, FunnelEvent
from app.services.scoring_service import WinPatternScorer

logger = structlog.get_logger()


class ProspectAgent:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.scorer = WinPatternScorer()

    async def run(self, icp_config: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("A1 starting", config_keys=list(icp_config.keys()))

        raw_contacts, provider_meta = await self._fetch_from_apollo(icp_config)
        logger.info("Apollo prospect fetch complete", count=len(raw_contacts), **provider_meta)

        scored = await self._score_contacts(raw_contacts)
        qualified = [
            contact for contact in scored
            if contact.get("win_pattern_score", 0) >= settings.ICP_SCORE_THRESHOLD
        ]

        save_result = await self._save_contacts(qualified)
        reason = self._reason(raw_contacts, scored, qualified, save_result, provider_meta)

        await self._log_funnel_event(
            "prospect_batch_completed",
            {
                "provider": "apollo",
                "discovery_method": provider_meta.get("method"),
                "provider_page": provider_meta.get("page"),
                "raw_count": len(raw_contacts),
                "scored_count": len(scored),
                "qualified_count": len(qualified),
                "reason": reason,
                **save_result,
            },
        )

        return {
            "agent": "A1",
            "provider": "apollo",
            "discovery_method": provider_meta.get("method"),
            "provider_page": provider_meta.get("page"),
            "raw_count": len(raw_contacts),
            "scored_count": len(scored),
            "qualified_count": len(qualified),
            "reason": reason,
            **save_result,
            "contacts": [c.get("email") for c in qualified[:5]],
        }

    async def _fetch_from_apollo(
        self, icp_config: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not settings.APOLLO_API_KEY:
            return [], {
                "provider": "apollo",
                "method": "people_search_bulk_match",
                "page": None,
                "reason": "missing_apollo_api_key",
            }

        requested_page = icp_config.get("page")
        max_pages = max(1, int(icp_config.get("max_pages", settings.APOLLO_SEARCH_MAX_PAGES)))
        page = int(requested_page) if requested_page else secrets.randbelow(max_pages) + 1
        per_page = min(max(int(icp_config.get("limit", 50)), 1), 100)

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": settings.APOLLO_API_KEY,
        }
        body: Dict[str, Any] = {"page": page, "per_page": per_page}
        if icp_config.get("titles"):
            body["person_titles"] = icp_config["titles"]
        if icp_config.get("geographies"):
            body["person_locations"] = icp_config["geographies"]
        if icp_config.get("employee_ranges"):
            body["organization_num_employees_ranges"] = icp_config["employee_ranges"]
        if icp_config.get("seniorities"):
            body["person_seniorities"] = icp_config["seniorities"]

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                search_resp = await client.post(
                    "https://api.apollo.io/api/v1/mixed_people/api_search",
                    headers=headers,
                    json=body,
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()
                people = search_data.get("people") or search_data.get("contacts") or []
                pagination = search_data.get("pagination") or {}
                total_entries = pagination.get("total_entries") or search_data.get("total_entries", 0)

                if not people:
                    return [], {
                        "provider": "apollo",
                        "method": "people_search_bulk_match",
                        "page": page,
                        "total_entries": total_entries,
                        "reason": "apollo_people_search_empty",
                    }

                enriched_people: List[Dict[str, Any]] = []
                for i in range(0, len(people), 10):
                    details = [{"id": p["id"]} for p in people[i:i + 10] if p.get("id")]
                    if not details:
                        continue
                    match_resp = await client.post(
                        "https://api.apollo.io/api/v1/people/bulk_match",
                        headers=headers,
                        json={
                            "details": details,
                            "reveal_personal_emails": False,
                            "reveal_phone_number": False,
                        },
                    )
                    if match_resp.status_code == 200:
                        enriched_people.extend(match_resp.json().get("matches") or [])
                    else:
                        logger.warning(
                            "Apollo bulk_match failed",
                            status=match_resp.status_code,
                            body=match_resp.text[:250],
                        )

                contacts = [
                    self._parse_apollo_contact(person)
                    for person in enriched_people
                    if person.get("email")
                ]
                return contacts, {
                    "provider": "apollo",
                    "method": "people_search_bulk_match",
                    "page": page,
                    "total_entries": total_entries,
                    "reason": "apollo_contacts_found" if contacts else "apollo_bulk_match_no_emails",
                }
        except httpx.HTTPStatusError as exc:
            logger.error("Apollo fetch failed", status_code=exc.response.status_code)
            return [], {
                "provider": "apollo",
                "method": "people_search_bulk_match",
                "page": page,
                "reason": f"apollo_http_{exc.response.status_code}",
            }
        except Exception as exc:
            logger.exception("Apollo fetch failed", error=str(exc))
            return [], {
                "provider": "apollo",
                "method": "people_search_bulk_match",
                "page": page,
                "reason": "apollo_request_failed",
            }

    @staticmethod
    def _parse_apollo_contact(person: Dict[str, Any]) -> Dict[str, Any]:
        organization = person.get("organization") or {}
        domain = organization.get("primary_domain") or organization.get("website_url") or ""
        domain = domain.replace("https://", "").replace("http://", "").strip("/")

        return {
            "email": (person.get("email") or "").strip().lower(),
            "first_name": person.get("first_name") or "",
            "last_name": person.get("last_name") or "",
            "title": person.get("title") or "",
            "company": organization.get("name") or "",
            "company_domain": domain,
            "linkedin_url": person.get("linkedin_url") or "",
            "company_size": str(organization.get("estimated_num_employees") or ""),
            "employee_count": organization.get("estimated_num_employees"),
            "industry": organization.get("industry") or "",
            "geography": person.get("city") or person.get("country") or "",
            "tech_stack": organization.get("technologies") or [],
            "funding_stage": organization.get("latest_funding_stage") or "",
            "apollo_id": person.get("id") or "",
            "source": "apollo",
            "email_valid": True,
            "email_verified": True,
        }

    async def _score_contacts(self, contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        scored: List[Dict[str, Any]] = []
        for contact in contacts:
            if not contact.get("email"):
                continue
            score, breakdown = self.scorer.score(contact)
            contact["win_pattern_score"] = score
            contact["icp_score_breakdown"] = breakdown
            scored.append(contact)
        return scored

    async def _save_contacts(self, contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        inserted_ids: List[str] = []
        updated_ids: List[str] = []

        for data in contacts:
            email = (data.get("email") or "").strip().lower()
            if not email:
                continue

            result = await self.db.execute(select(Contact).where(Contact.email == email))
            contact = result.scalar_one_or_none()
            if contact:
                contact.icp_score = data.get("win_pattern_score")
                contact.win_pattern_score = data.get("win_pattern_score")
                contact.icp_score_breakdown = data.get("icp_score_breakdown")
                contact.title = data.get("title") or contact.title
                contact.company = data.get("company") or contact.company
                contact.company_domain = data.get("company_domain") or contact.company_domain
                contact.industry = data.get("industry") or contact.industry
                contact.company_size = data.get("company_size") or contact.company_size
                contact.employee_count = data.get("employee_count") or contact.employee_count
                contact.tech_stack = data.get("tech_stack") or contact.tech_stack
                contact.funding_stage = data.get("funding_stage") or contact.funding_stage
                contact.geography = data.get("geography") or contact.geography
                contact.apollo_id = data.get("apollo_id") or contact.apollo_id
                contact.email_valid = data.get("email_valid")
                contact.email_verified = bool(data.get("email_verified"))
                contact.verified_at = datetime.utcnow()
                contact.enriched_at = datetime.utcnow()
                contact.source = "apollo"
                updated_ids.append(str(contact.id))
            else:
                contact = Contact(
                    email=email,
                    first_name=data.get("first_name"),
                    last_name=data.get("last_name"),
                    title=data.get("title"),
                    company=data.get("company"),
                    company_domain=data.get("company_domain"),
                    linkedin_url=data.get("linkedin_url"),
                    company_size=data.get("company_size"),
                    employee_count=data.get("employee_count"),
                    industry=data.get("industry"),
                    funding_stage=data.get("funding_stage"),
                    tech_stack=data.get("tech_stack", []),
                    geography=data.get("geography"),
                    icp_score=data.get("win_pattern_score"),
                    win_pattern_score=data.get("win_pattern_score"),
                    icp_score_breakdown=data.get("icp_score_breakdown"),
                    email_valid=data.get("email_valid"),
                    email_verified=bool(data.get("email_verified")),
                    verified_at=datetime.utcnow(),
                    enriched_at=datetime.utcnow(),
                    source="apollo",
                    apollo_id=data.get("apollo_id"),
                )
                self.db.add(contact)
                await self.db.flush()
                inserted_ids.append(str(contact.id))

        await self.db.commit()
        return {
            "saved_count": len(inserted_ids),
            "updated_count": len(updated_ids),
            "contact_ids": inserted_ids + updated_ids,
            "inserted_contact_ids": inserted_ids,
        }

    @staticmethod
    def _reason(
        raw_contacts: List[Dict[str, Any]],
        scored: List[Dict[str, Any]],
        qualified: List[Dict[str, Any]],
        save_result: Dict[str, Any],
        provider_meta: Dict[str, Any],
    ) -> str:
        if not raw_contacts:
            return provider_meta.get("reason") or "apollo_returned_no_contacts"
        if not scored:
            return "apollo_contacts_missing_email"
        if not qualified:
            return "apollo_contacts_below_icp_threshold"
        if not save_result.get("saved_count") and not save_result.get("updated_count"):
            return "qualified_contacts_found_but_not_persisted"
        return "apollo_contacts_persisted"

    async def _log_funnel_event(self, event_type: str, metadata: Dict[str, Any]) -> None:
        self.db.add(FunnelEvent(event_type=event_type, agent_id="A1", event_metadata=metadata))
        await self.db.commit()