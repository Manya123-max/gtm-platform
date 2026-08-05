"""A1 - Prospect Intelligence Agent.

Apollo is the only discovery and enrichment provider. The agent:
  1. Searches Apollo with the correct ICP filters (no vendor company restriction)
  2. Pre-scores stubs before paying for enrichment (filter-first)
  3. Dedupes against recently enriched contacts
  4. Bulk-matches only the pre-qualified, deduped subset
  5. Conditionally enriches org data when firmographic fields are blank
  6. Final-scores, thresholds, and persists contacts
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Contact, FunnelEvent
from app.services.scoring_service import WinPatternScorer

logger = structlog.get_logger()

# Pages with fewer total entries than this are searched sequentially from page 1
# to avoid landing on an empty page. Large result sets use random sampling for variety.
_RANDOM_PAGE_THRESHOLD = 200


class ProspectAgent:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.scorer = WinPatternScorer()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, icp_config: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("A1 starting", config_keys=list(icp_config.keys()))

        raw_contacts, provider_meta = await self._fetch_from_apollo(icp_config)
        logger.info(
            "Apollo prospect fetch complete",
            count=len(raw_contacts),
            **provider_meta,
        )

        scored = await self._score_contacts(raw_contacts)
        threshold = icp_config.get("threshold", settings.ICP_SCORE_THRESHOLD)
        qualified = [c for c in scored if c.get("win_pattern_score", 0) >= threshold]

        save_result = await self._save_contacts(
            qualified, icp_config.get("user_input_id")
        )
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

    # ------------------------------------------------------------------
    # Apollo fetch — filter-before-enrich pipeline
    # ------------------------------------------------------------------

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

        max_pages = max(1, int(icp_config.get("max_pages", settings.APOLLO_SEARCH_MAX_PAGES)))
<<<<<<< HEAD
        enrich_limit = int(icp_config.get("enrich_limit", getattr(settings, "APOLLO_ENRICH_LIMIT", 10)))
=======
<<<<<<< HEAD
        enrich_limit = int(icp_config.get("enrich_limit", 10))
=======
        enrich_limit = int(icp_config.get("enrich_limit", settings.APOLLO_ENRICH_LIMIT))
>>>>>>> ff7acc4bfc6042ccd78b59eab1a8fd0685da42d9
>>>>>>> b0cbbe053f65f9a430794591dff5cac7654c316c
        threshold = icp_config.get("threshold", settings.ICP_SCORE_THRESHOLD)

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": settings.APOLLO_API_KEY,
        }

        # ── Step 1: Initial search (page 1) to learn total_entries ──────────
        body = self._build_search_body(icp_config, page=1, per_page=100)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                search_resp = await client.post(
                    "https://api.apollo.io/api/v1/mixed_people/api_search",
                    headers=headers,
                    json=body,
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()

                pagination = search_data.get("pagination") or {}
                total_entries = pagination.get("total_entries") or search_data.get("total_entries", 0)
                people = search_data.get("people") or search_data.get("contacts") or []

                # ── Step 2: Decide page strategy based on total_entries ──────
                requested_page = icp_config.get("page")
                if requested_page:
                    actual_page = int(requested_page)
                elif total_entries < _RANDOM_PAGE_THRESHOLD:
                    # Small result set — use page 1 (already fetched)
                    actual_page = 1
                else:
                    # Large result set — re-fetch on a random page for variety
                    actual_page = secrets.randbelow(max_pages) + 1
                    if actual_page > 1:
                        body["page"] = actual_page
                        search_resp2 = await client.post(
                            "https://api.apollo.io/api/v1/mixed_people/api_search",
                            headers=headers,
                            json=body,
                        )
                        search_resp2.raise_for_status()
                        people = (
                            search_resp2.json().get("people")
                            or search_resp2.json().get("contacts")
                            or []
                        )

                if not people:
                    return [], {
                        "provider": "apollo",
                        "method": "people_search_bulk_match",
                        "page": actual_page,
                        "total_entries": total_entries,
                        "reason": "apollo_people_search_empty",
                    }

                # ── Step 3: Pre-score stubs (no enrichment yet) ──────────────
                stub_scored: List[Tuple[float, Dict]] = []
                for person in people:
                    stub = self._stub_dict(person)
                    score, _ = self.scorer.score(stub)
                    stub_scored.append((score, person))

                stub_scored.sort(key=lambda x: x[0], reverse=True)
                top_candidates = [p for _, p in stub_scored[:enrich_limit]]
                pre_qualified_count = sum(
                    1 for s, _ in stub_scored[:enrich_limit] if s >= threshold
                )

                logger.info(
                    "A1 pre-score complete",
                    total_stubs=len(people),
                    pre_qualified=pre_qualified_count,
                    to_enrich=len(top_candidates),
                )

                # ── Step 4: Dedupe against recently enriched contacts ─────────
                apollo_ids = [p["id"] for p in top_candidates if p.get("id")]
                recently_enriched = await self._get_recently_enriched_apollo_ids(apollo_ids)
                to_enrich = [
                    p for p in top_candidates
                    if p.get("id") not in recently_enriched
                ]

                logger.info(
                    "A1 dedupe complete",
                    already_enriched=len(recently_enriched),
                    to_enrich=len(to_enrich),
                )

                if not to_enrich:
                    return [], {
                        "provider": "apollo",
                        "method": "people_search_bulk_match",
                        "page": actual_page,
                        "total_entries": total_entries,
                        "reason": "all_candidates_recently_enriched",
                    }

                # ── Step 5: Bulk match (pay for enrichment) — top N only ─────
                enriched_people = await self._bulk_match(client, headers, to_enrich)

                if not enriched_people:
                    return [], {
                        "provider": "apollo",
                        "method": "people_search_bulk_match",
                        "page": actual_page,
                        "total_entries": total_entries,
                        "reason": "apollo_bulk_match_no_results",
                    }

                # ── Step 6: Parse + conditional org enrich ───────────────────
                contacts: List[Dict[str, Any]] = []
                for person in enriched_people:
                    if not person.get("email"):
                        continue
                    contact = self._parse_apollo_contact(person)

                    # Org enrich: fire only when key firmographic fields are blank
                    if (
                        not contact.get("funding_stage")
                        and not contact.get("industry")
                        and not contact.get("tech_stack")
                        and contact.get("_org_id")
                    ):
                        org_data = await self._enrich_org(client, headers, contact["_org_id"])
                        if org_data:
                            contact["funding_stage"] = org_data.get("latest_funding_stage") or ""
                            contact["industry"]      = org_data.get("industry") or ""
                            contact["tech_stack"]    = org_data.get("technologies") or []

                    contacts.append(contact)

                return contacts, {
                    "provider": "apollo",
                    "method": "people_search_bulk_match",
                    "page": actual_page,
                    "total_entries": total_entries,
                    "pre_qualified_count": pre_qualified_count,
                    "deduped_count": len(recently_enriched),
                    "enriched_count": len(enriched_people),
                    "reason": "apollo_contacts_found" if contacts else "apollo_bulk_match_no_emails",
                }

        except httpx.HTTPStatusError as exc:
            logger.error("Apollo fetch failed", status_code=exc.response.status_code)
            return [], {
                "provider": "apollo",
                "method": "people_search_bulk_match",
                "page": None,
                "reason": f"apollo_http_{exc.response.status_code}",
            }
        except Exception as exc:
            logger.exception("Apollo fetch failed", error=str(exc))
            return [], {
                "provider": "apollo",
                "method": "people_search_bulk_match",
                "page": None,
                "reason": "apollo_request_failed",
            }

    # ------------------------------------------------------------------
    # Apollo search body builder — correct param names
    # ------------------------------------------------------------------

    @staticmethod
    def _build_search_body(
        icp_config: Dict[str, Any],
        page: int = 1,
        per_page: int = 100,
    ) -> Dict[str, Any]:
        """
        Build the Apollo mixed_people/api_search request body.

        Param mapping (confirmed correct Apollo field names):
          person_titles                    ← icp_config["titles"]
          organization_locations           ← icp_config["organization_locations"]  (org HQ, not person location)
          organization_num_employees_ranges← icp_config["employee_ranges"]
          person_seniorities               ← icp_config["seniorities"]  (optional plumbing)
          organization_industry_tag_ids    ← icp_config["industry_tag_ids"]  (static map IDs)
          q_organization_keyword_tags      ← icp_config["org_keyword_tags"]  (array — keywords + unmatched industry terms)

        Intentionally absent:
          q_organization_name  ← REMOVED (was the bug: restricted results to vendor's own company)
          q_keywords           ← REPLACED by q_organization_keyword_tags (more targeted)
        """
        body: Dict[str, Any] = {"page": page, "per_page": per_page}

        if icp_config.get("titles"):
            body["person_titles"] = icp_config["titles"]

        if icp_config.get("organization_locations"):
            # organization_locations = where the company is headquartered
            body["organization_locations"] = icp_config["organization_locations"]

        if icp_config.get("employee_ranges"):
            body["organization_num_employees_ranges"] = icp_config["employee_ranges"]

        if icp_config.get("seniorities"):
            # Plumbing exists for future use; intake form doesn't populate this yet
            body["person_seniorities"] = icp_config["seniorities"]

        if icp_config.get("industry_tag_ids"):
            # Resolved static tag IDs from industry_tag_map.py
            body["organization_industry_tag_ids"] = icp_config["industry_tag_ids"]

        if icp_config.get("org_keyword_tags"):
            # Array of keyword terms — covers user keywords + unmatched industry fallback
            body["q_organization_keyword_tags"] = icp_config["org_keyword_tags"]

        return body

    # ------------------------------------------------------------------
    # Pre-score stubs (before enrichment)
    # ------------------------------------------------------------------

    @staticmethod
    def _stub_dict(person: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a scorable dict from an Apollo search stub.
        Org data (industry, employee count, technologies) is available in stubs
        without paying for bulk_match enrichment.
        """
        org = person.get("organization") or {}
        return {
            "title":          person.get("title") or "",
            "company_size":   str(org.get("estimated_num_employees") or ""),
            "employee_count": org.get("estimated_num_employees"),
            "industry":       org.get("industry") or "",
            "tech_stack":     org.get("technologies") or [],
            "funding_stage":  org.get("latest_funding_stage") or "",
            "apollo_id":      person.get("id") or "",
        }

    # ------------------------------------------------------------------
    # Bulk match helper
    # ------------------------------------------------------------------

    async def _bulk_match(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, Any],
        people: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Call Apollo bulk_match in batches of 10 and return all enriched results."""
        enriched: List[Dict[str, Any]] = []
        for i in range(0, len(people), 10):
            details = [{"id": p["id"]} for p in people[i : i + 10] if p.get("id")]
            if not details:
                continue
            try:
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
                    enriched.extend(match_resp.json().get("matches") or [])
                else:
                    logger.warning(
                        "Apollo bulk_match failed",
                        status=match_resp.status_code,
                        body=match_resp.text[:250],
                    )
            except Exception as exc:
                logger.warning("Apollo bulk_match exception", error=str(exc))
        return enriched

    # ------------------------------------------------------------------
    # Conditional org enrichment — fix blank firmographic scoring bug
    # ------------------------------------------------------------------

    async def _enrich_org(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, Any],
        org_id: str,
    ) -> Dict[str, Any]:
        """
        Call organizations/enrich to fill missing firmographic fields.
        Fired ONLY when funding_stage + industry + tech_stack are all blank,
        so we don't spend a credit on every contact.
        """
        try:
            resp = await client.post(
                "https://api.apollo.io/api/v1/organizations/enrich",
                headers=headers,
                json={"organization_id": org_id},
            )
            if resp.status_code == 200:
                return resp.json().get("organization") or {}
        except Exception as exc:
            logger.warning("Apollo org enrich failed", org_id=org_id, error=str(exc))
        return {}

    # ------------------------------------------------------------------
    # Dedupe — skip recently enriched contacts
    # ------------------------------------------------------------------

    async def _get_recently_enriched_apollo_ids(
        self, apollo_ids: List[str]
    ) -> set:
        """Return apollo_ids of contacts enriched within the last 7 days."""
        if not apollo_ids:
            return set()
        cutoff = datetime.utcnow() - timedelta(days=7)
        result = await self.db.execute(
            select(Contact.apollo_id)
            .where(Contact.apollo_id.in_(apollo_ids))
            .where(Contact.enriched_at >= cutoff)
        )
        return {row[0] for row in result.all()}

    # ------------------------------------------------------------------
    # Parse Apollo response into contact dict
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_apollo_contact(person: Dict[str, Any]) -> Dict[str, Any]:
        organization = person.get("organization") or {}
        domain = (
            organization.get("primary_domain")
            or organization.get("website_url")
            or ""
        )
        domain = domain.replace("https://", "").replace("http://", "").strip("/")

        # Parse technologies from Apollo's "current_technologies" array of dicts
        techs = organization.get("current_technologies") or []
        tech_list = []
        if isinstance(techs, list):
            for t in techs:
                if isinstance(t, dict) and t.get("name"):
                    tech_list.append(t["name"])
                elif isinstance(t, str):
                    tech_list.append(t)
        
        # Fallback to "technology_names" string array
        if not tech_list and organization.get("technology_names"):
            tech_list = organization.get("technology_names") or []
        
        # Fallback to "technologies" string array
        if not tech_list and organization.get("technologies"):
            tech_list = organization.get("technologies") or []

        return {
            "email":          (person.get("email") or "").strip().lower(),
            "first_name":     person.get("first_name") or "",
            "last_name":      person.get("last_name") or "",
            "title":          person.get("title") or "",
            "company":        organization.get("name") or "",
            "company_domain": domain,
            "linkedin_url":   person.get("linkedin_url") or "",
            "company_size":   str(organization.get("estimated_num_employees") or ""),
            "employee_count": organization.get("estimated_num_employees"),
            "industry":       organization.get("industry") or "",
            "geography":      person.get("city") or person.get("country") or "",
            "tech_stack":     tech_list,
            "funding_stage":  organization.get("latest_funding_stage") or organization.get("funding_stage") or "",
            "apollo_id":      person.get("id") or "",
            "_org_id":        organization.get("id") or "",   # used for conditional org enrich
            "source":         "apollo",
            "email_valid":    True,
            "email_verified": True,
        }

    # ------------------------------------------------------------------
    # Score contacts
    # ------------------------------------------------------------------

    async def _score_contacts(
        self, contacts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        scored: List[Dict[str, Any]] = []
        for contact in contacts:
            if not contact.get("email"):
                continue
            score, breakdown = self.scorer.score(contact)
            contact["win_pattern_score"] = score
            contact["icp_score_breakdown"] = breakdown
            scored.append(contact)
        return scored

    # ------------------------------------------------------------------
    # Save contacts
    # ------------------------------------------------------------------
    async def _save_contacts(
        self,
        contacts: List[Dict[str, Any]],
        user_input_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        inserted_ids: List[str] = []
        updated_ids: List[str] = []

        for data in contacts:
            email = (data.get("email") or "").strip().lower()
            if not email:
                continue

            result = await self.db.execute(
                select(Contact).where(Contact.email == email)
            )
            contact = result.scalar_one_or_none()

            if contact:
                contact.icp_score             = data.get("win_pattern_score")
                contact.win_pattern_score      = data.get("win_pattern_score")
                contact.icp_score_breakdown    = data.get("icp_score_breakdown")
                contact.title                  = data.get("title") or contact.title
                contact.company                = data.get("company") or contact.company
                contact.company_domain         = data.get("company_domain") or contact.company_domain
                contact.industry               = data.get("industry") or contact.industry
                contact.company_size           = data.get("company_size") or contact.company_size
                contact.employee_count         = data.get("employee_count") or contact.employee_count
                contact.tech_stack             = data.get("tech_stack") or contact.tech_stack
                contact.funding_stage          = data.get("funding_stage") or contact.funding_stage
                contact.geography              = data.get("geography") or contact.geography
                contact.apollo_id              = data.get("apollo_id") or contact.apollo_id
                contact.email_valid            = data.get("email_valid")
                contact.email_verified         = bool(data.get("email_verified"))
                contact.verified_at            = datetime.utcnow()
                contact.enriched_at            = datetime.utcnow()
                contact.source                 = "apollo"
                if user_input_id is not None:
                    contact.user_input_id = user_input_id
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
                    user_input_id=user_input_id,
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

    # ------------------------------------------------------------------
    # Reason string
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Funnel event logging
    # ------------------------------------------------------------------

    async def _log_funnel_event(
        self, event_type: str, metadata: Dict[str, Any]
    ) -> None:
        self.db.add(
            FunnelEvent(event_type=event_type, agent_id="A1", event_metadata=metadata)
        )
        await self.db.commit()