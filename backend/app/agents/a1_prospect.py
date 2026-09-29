"""A1 - Prospect Intelligence Agent.

Apollo is the discovery and enrichment provider. The iterative replenishment pipeline:
  1. Normalizes ICP configuration (titles, seniorities, size ranges, locations, industry tags).
  2. Builds validated Apollo search payloads using ApolloQueryBuilder.
  3. Iterates sequentially across Apollo pages (Page 1 → Page 2 → ... up to max pages):
     a. Performs fast in-memory deduplication (IDs and composite keys).
     b. Executes pre-qualification gate on search stubs (rejecting clear mismatches without external calls).
     c. Excludes candidates enriched in PostgreSQL within the last 7 days.
     d. Pre-scores eligible stubs with WinPatternScorer to rank the strongest prospects first.
     e. Selects only the needed subset of pre-qualified candidates for enrichment.
     f. Bulk-matches selected candidates in batches of 10.
     g. Conditionally enriches org firmographics if missing.
     h. Computes final authoritative ICP score with WinPatternScorer and applies threshold.
     i. Accumulates qualifying prospects until requested count (default 25) is reached.
  4. Stops immediately when requested count is reached, Apollo is exhausted, or max pages reached.
  5. Never injects fallback database contacts on failed or empty searches.
  6. Persists final qualifying prospects with user_id and user_input_id for strict multi-user isolation.
  7. Emits rich structured telemetry to FunnelEvent (zero secrets).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Set

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Contact, FunnelEvent
from app.services.scoring_service import WinPatternScorer
from app.services.icp_normalizer import (
    NormalizedICPConfig,
    normalize_icp_input,
    APOLLO_EMPLOYEE_BUCKETS,
    _infer_seniorities_from_title,
)
from app.services.apollo_query_builder import ApolloQueryBuilder
from app.agents.industry_tag_map import get_industry_synonyms, INDUSTRY_TAG_MAP

logger = structlog.get_logger()



class ProspectAgent:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.scorer = WinPatternScorer()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, icp_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the A1 prospecting pipeline with normalized input and smart replenishment.
        """
        norm_cfg = normalize_icp_input(icp_config)
        requested_count = int(
            norm_cfg.requested_count
            or norm_cfg.enrich_limit
            or getattr(settings, "APOLLO_ENRICH_LIMIT", 25)
        )

        logger.info(
            "A1 starting prospecting run",
            requested_count=requested_count,
            titles=norm_cfg.titles,
            seniorities=norm_cfg.seniorities,
            organization_locations=norm_cfg.organization_locations,
            employee_ranges=norm_cfg.employee_ranges,
            industry_tag_ids=norm_cfg.industry_tag_ids,
            org_keyword_tags=norm_cfg.org_keyword_tags,
            threshold=norm_cfg.threshold,
        )

        final_prospects, telemetry = await self._fetch_and_enrich_replenishment(
            norm_cfg, requested_count
        )

        logger.info(
            "Apollo replenishment pipeline complete",
            qualified_count=len(final_prospects),
            **{k: v for k, v in telemetry.items() if k != "search_request"},
        )

        save_result = await self._save_contacts(
            final_prospects,
            user_input_id=norm_cfg.user_input_id,
            user_id=norm_cfg.user_id,
        )

        telemetry["saved_count"] = save_result.get("saved_count", 0)
        telemetry["updated_count"] = save_result.get("updated_count", 0)
        telemetry["final_qualified_count"] = len(final_prospects)

        reason = self._reason(final_prospects, save_result, telemetry)
        telemetry["reason"] = reason

        await self._log_funnel_event(
            "prospect_batch_completed",
            {
                "provider": "apollo",
                "telemetry": telemetry,
                **save_result,
            },
        )

        return {
            "agent": "A1",
            "provider": "apollo",
            "discovery_method": "prequalified_replenishment_bulk_match",
            "requested_count": requested_count,
            "raw_count": telemetry.get("raw_candidates", 0),
            "prequalified_count": telemetry.get("prequalified_candidates", 0),
            "enriched_count": telemetry.get("enriched_count", 0),
            "qualified_count": len(final_prospects),
            "final_count": len(final_prospects),
            "saved_count": save_result.get("saved_count", 0),
            "reason": reason,
            "telemetry": telemetry,
            **save_result,
            "contacts": [c.get("email") for c in final_prospects[:5]],
        }

    # ------------------------------------------------------------------
    # Apollo replenishment & selective enrichment loop
    # ------------------------------------------------------------------

    async def _fetch_and_enrich_replenishment(
        self, norm_cfg: NormalizedICPConfig, requested_count: int
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        telemetry: Dict[str, Any] = {
            "requested_count": requested_count,
            "search_request": {},
            "pages_requested": 0,
            "raw_candidates": 0,
            "duplicate_candidates": 0,
            "recently_enriched_excluded": 0,
            "prequalification_rejected": 0,
            "industry_rejected": 0,
            "technology_rejected": 0,
            "location_rejected": 0,
            "company_size_rejected": 0,
            "title_rejected": 0,
            "prequalified_candidates": 0,
            "candidates_selected_for_enrichment": 0,
            "enrichment_batches": 0,
            "enriched_count": 0,
            "final_threshold_passed": 0,
            "final_qualified_count": 0,
            "remaining_needed": requested_count,
            "exhaustion_reason": None,
        }

        if not settings.APOLLO_API_KEY:
            telemetry["exhaustion_reason"] = "missing_apollo_api_key"
            return [], telemetry

        max_pages = max(
            1,
            int(
                getattr(
                    settings,
                    "APOLLO_MAX_SEARCH_PAGES",
                    getattr(settings, "APOLLO_SEARCH_MAX_PAGES", 10),
                )
            ),
        )
        per_page = int(getattr(settings, "APOLLO_SEARCH_PER_PAGE", 100))

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": settings.APOLLO_API_KEY,
        }

        base_search_body = ApolloQueryBuilder.build_search_payload(norm_cfg, page=1, per_page=per_page)
        telemetry["search_request"] = ApolloQueryBuilder.to_sanitized_dict(base_search_body)

        final_qualified: List[Dict[str, Any]] = []
        seen_apollo_ids: Set[str] = set()
        seen_composite_keys: Set[Tuple[str, str, str]] = set()
        enriched_apollo_ids: Set[str] = set()

        current_page = 1

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                while len(final_qualified) < requested_count and current_page <= max_pages:
                    search_body = ApolloQueryBuilder.build_search_payload(
                        norm_cfg, page=current_page, per_page=per_page
                    )
                    telemetry["pages_requested"] += 1

                    search_resp = await client.post(
                        "https://api.apollo.io/api/v1/mixed_people/api_search",
                        headers=headers,
                        json=search_body,
                    )
                    if search_resp.status_code != 200:
                        logger.error(
                            "Apollo search HTTP error",
                            status_code=search_resp.status_code,
                            body=search_resp.text[:300],
                        )
                        telemetry["exhaustion_reason"] = f"apollo_http_{search_resp.status_code}"
                        break

                    search_data = search_resp.json()
                    pagination = search_data.get("pagination") or {}
                    total_entries = pagination.get("total_entries") or search_data.get("total_entries", 0)
                    people = search_data.get("people") or search_data.get("contacts") or []

                    if not people:
                        telemetry["exhaustion_reason"] = "apollo_exhausted"
                        break

                    # 1. Filter stubs on current page
                    page_prequalified_stubs: List[Dict[str, Any]] = []
                    for person in people:
                        telemetry["raw_candidates"] += 1
                        pid = person.get("id") or ""
                        first_name = (person.get("first_name") or "").strip().lower()
                        last_name = (person.get("last_name") or "").strip().lower()
                        org_name = ((person.get("organization") or {}).get("name") or "").strip().lower()
                        # In-memory deduplication across pages & within page
                        composite_key = (first_name, last_name, org_name) if (first_name or last_name) and org_name else None
                        if pid and pid in seen_apollo_ids:
                            telemetry["duplicate_candidates"] += 1
                            continue
                        if composite_key and composite_key in seen_composite_keys:
                            telemetry["duplicate_candidates"] += 1
                            continue

                        # Pre-qualification gate
                        is_prequal, reject_reason = self._check_prequalification(person, norm_cfg)
                        if not is_prequal:
                            telemetry["prequalification_rejected"] += 1
                            if reject_reason and reject_reason in telemetry:
                                telemetry[reject_reason] += 1
                            continue

                        if pid:
                            seen_apollo_ids.add(pid)
                        if composite_key:
                            seen_composite_keys.add(composite_key)

                        telemetry["prequalified_candidates"] += 1
                        page_prequalified_stubs.append(person)


                    # 2. Exclude stubs enriched in DB within the last 7 days or already enriched in this run
                    stubs_to_check = [p["id"] for p in page_prequalified_stubs if p.get("id")]
                    recently_enriched = await self._get_recently_enriched_apollo_ids(stubs_to_check)
                    fresh_stubs = [
                        p
                        for p in page_prequalified_stubs
                        if p.get("id") not in recently_enriched
                        and p.get("id") not in enriched_apollo_ids
                    ]
                    telemetry["recently_enriched_excluded"] += (
                        len(page_prequalified_stubs) - len(fresh_stubs)
                    )

                    # 3. If no fresh pre-qualified stubs on this page, advance page and replenish
                    if not fresh_stubs:
                        if total_entries and (current_page * per_page) >= total_entries:
                            telemetry["exhaustion_reason"] = "apollo_exhausted"
                            break
                        if len(people) < per_page and not total_entries:
                            telemetry["exhaustion_reason"] = "apollo_exhausted"
                            break
                        current_page += 1
                        continue

                    # 4. Pre-score fresh stubs to rank strongest candidates first
                    stub_scored: List[Tuple[float, Dict]] = []
                    for p in fresh_stubs:
                        stub = self._stub_dict(p)
                        score, _ = self.scorer.score(stub)
                        stub_scored.append((score, p))

                    stub_scored.sort(key=lambda x: x[0], reverse=True)

                    # Select candidates needed up to remaining_needed (or batch limit)
                    remaining_needed = requested_count - len(final_qualified)
                    batch_select_limit = min(len(stub_scored), max(remaining_needed, 10))
                    selected_stubs = [p for _, p in stub_scored[:batch_select_limit]]
                    telemetry["candidates_selected_for_enrichment"] += len(selected_stubs)

                    for s in selected_stubs:
                        if s.get("id"):
                            enriched_apollo_ids.add(s["id"])

                    # 5. Bulk Match in batches of 10
                    enriched_people = await self._bulk_match(client, headers, selected_stubs)
                    telemetry["enriched_count"] += len(enriched_people)
                    telemetry["enrichment_batches"] += (len(selected_stubs) + 9) // 10

                    # 6. Parse, conditionally org-enrich, and final score
                    for person in enriched_people:
                        if not person.get("email"):
                            continue
                        contact = self._parse_apollo_contact(person)

                        # Conditional Org enrich when firmographics are missing
                        if (
                            not contact.get("funding_stage")
                            and not contact.get("industry")
                            and not contact.get("tech_stack")
                            and contact.get("_org_id")
                        ):
                            org_data = await self._enrich_org(client, headers, contact["_org_id"])
                            if org_data:
                                contact["funding_stage"] = org_data.get("latest_funding_stage") or ""
                                contact["industry"] = org_data.get("industry") or ""
                                contact["tech_stack"] = org_data.get("technologies") or []

                        score, breakdown = self.scorer.score(contact)
                        contact["win_pattern_score"] = score
                        contact["icp_score"] = score
                        contact["icp_score_breakdown"] = breakdown

                        if score >= norm_cfg.threshold:
                            final_qualified.append(contact)
                            telemetry["final_threshold_passed"] += 1

                    telemetry["final_qualified_count"] = len(final_qualified)
                    telemetry["remaining_needed"] = max(0, requested_count - len(final_qualified))

                    # 7. Check if we reached the requested count
                    if len(final_qualified) >= requested_count:
                        break

                    # 8. Check if pagination is exhausted
                    if total_entries and (current_page * per_page) >= total_entries:
                        telemetry["exhaustion_reason"] = "apollo_exhausted"
                        break
                    if len(people) < per_page and not total_entries:
                        telemetry["exhaustion_reason"] = "apollo_exhausted"
                        break

                    current_page += 1

                # If loop completed without hitting target or setting reason
                if len(final_qualified) < requested_count and not telemetry.get("exhaustion_reason"):
                    if current_page > max_pages:
                        telemetry["exhaustion_reason"] = "max_pages_reached"
                    else:
                        telemetry["exhaustion_reason"] = (
                            "apollo_exhausted"
                            if telemetry["raw_candidates"] > 0
                            else "apollo_people_search_empty"
                        )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Apollo HTTP error",
                status_code=exc.response.status_code,
                body=exc.response.text[:300],
            )
            telemetry["exhaustion_reason"] = f"apollo_http_{exc.response.status_code}"
        except Exception as exc:
            logger.exception("Apollo fetch failed", error=str(exc))
            telemetry["exhaustion_reason"] = "apollo_request_failed"

        # Sort final qualified prospects descending by score and slice to requested_count
        final_qualified.sort(key=lambda c: c.get("win_pattern_score", 0), reverse=True)
        return final_qualified[:requested_count], telemetry

    # ------------------------------------------------------------------
    # Pre-Qualification Gate (Search-time stub integrity & ICP check)
    # ------------------------------------------------------------------

    @classmethod
    def _matches_target_industry(cls, person: Dict[str, Any], norm_cfg: NormalizedICPConfig) -> bool:
        """
        Deterministic industry qualification check using organization-level data.
        Returns True if candidate satisfies the target industry requirement, False otherwise.
        """
        # If no target industries or tags are requested, industry check passes
        if not norm_cfg.industry_terms and not norm_cfg.industry_tag_ids:
            return True

        org = person.get("organization") or {}
        stub_industry = (org.get("industry") or "").strip().lower()

        # Build list of target industry terms
        target_terms = [t.strip().lower() for t in norm_cfg.industry_terms if t.strip()]

        if stub_industry:
            # 1. Exact or word-boundary match against target terms
            for t_term in target_terms:
                if t_term == stub_industry:
                    return True
                if re.search(rf"\b{re.escape(t_term)}\b", stub_industry) or re.search(rf"\b{re.escape(stub_industry)}\b", t_term):
                    return True

            # 2. Tag ID match
            if norm_cfg.industry_tag_ids:
                stub_tag_id = INDUSTRY_TAG_MAP.get(stub_industry)
                if stub_tag_id and stub_tag_id in norm_cfg.industry_tag_ids:
                    return True

            # 3. Synonym matching for target industry terms using regex word-boundaries
            for t_term in target_terms:
                synonyms = get_industry_synonyms(t_term)
                for syn in synonyms:
                    if len(syn) <= 2:
                        # Short abbreviations (e.g. 'ai', 'it') must match whole words only
                        if re.search(rf"\b{re.escape(syn)}\b", stub_industry):
                            return True
                    else:
                        if syn in stub_industry or re.search(rf"\b{re.escape(syn)}\b", stub_industry):
                            return True

            # If industry was explicitly provided in stub and matched none of the above -> HARD REJECTION
            return False

        # If Apollo provides NO industry, check alternative organization-level evidence
        org_name = (org.get("name") or "").lower()
        org_keywords = org.get("keywords") or []
        if isinstance(org_keywords, list):
            org_kw_str = " ".join(str(k) for k in org_keywords).lower()
        else:
            org_kw_str = str(org_keywords).lower()
        org_desc = (org.get("short_description") or org.get("description") or org.get("headline") or "").lower()
        org_domain = (org.get("primary_domain") or org.get("website_url") or "").lower()

        combined_org_text = f"{org_name} {org_kw_str} {org_desc} {org_domain}"

        for t_term in target_terms:
            if re.search(rf"\b{re.escape(t_term)}\b", combined_org_text):
                return True
            synonyms = get_industry_synonyms(t_term)
            for syn in synonyms:
                if len(syn) >= 3 and re.search(rf"\b{re.escape(syn)}\b", combined_org_text):
                    return True

        # No industry provided and no supporting org evidence -> REJECT (insufficient evidence)
        return False


    @classmethod
    def _matches_target_technology(cls, person: Dict[str, Any], norm_cfg: NormalizedICPConfig) -> bool:
        """
        Deterministic technology / category qualification check using organization-level data.
        Never uses person job title as company-level evidence.
        """
        if not norm_cfg.technology_keywords:
            return True

        org = person.get("organization") or {}
        org_name = (org.get("name") or "").lower()
        org_keywords = org.get("keywords") or []
        if isinstance(org_keywords, list):
            org_kw_str = " ".join(str(k) for k in org_keywords).lower()
        else:
            org_kw_str = str(org_keywords).lower()
        org_tech = " ".join(str(t) for t in org.get("technologies") or []).lower()
        org_desc = (org.get("short_description") or org.get("description") or org.get("headline") or "").lower()
        org_domain = (org.get("primary_domain") or org.get("website_url") or "").lower()
        org_industry = (org.get("industry") or "").lower()

        combined_org_evidence = f"{org_name} {org_kw_str} {org_tech} {org_desc} {org_domain} {org_industry}"

        matched = False
        for tk in norm_cfg.technology_keywords:
            clean_tk = tk.strip().lower()
            if not clean_tk:
                continue
            if clean_tk in combined_org_evidence:
                matched = True
                break
            tk_words = [w for w in re.findall(r"\b\w+\b", clean_tk) if len(w) > 2]
            if tk_words and all(w in combined_org_evidence for w in tk_words):
                matched = True
                break

        if norm_cfg.technology_keywords_required:
            return matched

        return True

    @classmethod
    def _check_prequalification(
        cls, person: Dict[str, Any], norm_cfg: NormalizedICPConfig
    ) -> Tuple[bool, Optional[str]]:
        """
        Lightweight check using ONLY information available in the search response stub.
        Returns (is_qualified, rejection_reason).
        """
        title = (person.get("title") or "").strip()
        first_name = (person.get("first_name") or "").strip()
        last_name = (person.get("last_name") or "").strip()
        org = person.get("organization") or {}
        org_name = (org.get("name") or "").strip()
        org_domain = (org.get("primary_domain") or "").strip()

        # Hard Rule 1: Must have a title or name
        if not title and not (first_name or last_name):
            return False, "title_rejected"

        # Hard Rule 2: Must have an organization
        if not org_name and not org_domain:
            return False, "company_size_rejected"

        title_lower = title.lower()

        # Hard Rule 3: Reject explicit negative / non-decision-maker roles if targeting leadership
        negative_keywords = ["intern", "student", "assistant to", "retired", "apprentice", "volunteer"]
        for neg in negative_keywords:
            if neg in title_lower and not any(neg in t.lower() for t in norm_cfg.titles):
                return False, "title_rejected"

        # Rule 4: Title & Seniority compatibility
        if norm_cfg.titles or norm_cfg.seniorities:
            title_matched = False
            if norm_cfg.titles:
                for target_t in norm_cfg.titles:
                    target_lower = target_t.lower()
                    if target_lower in title_lower or title_lower in target_lower:
                        title_matched = True
                        break
                    # Token overlap (e.g. "vp", "sales")
                    target_tokens = set(re.findall(r"\b\w+\b", target_lower))
                    title_tokens = set(re.findall(r"\b\w+\b", title_lower))
                    if target_tokens and target_tokens.issubset(title_tokens):
                        title_matched = True
                        break

            seniority_matched = False
            if norm_cfg.seniorities:
                inferred_sens = _infer_seniorities_from_title(title)
                stub_sen = (person.get("seniority") or "").strip().lower()
                if any(s in norm_cfg.seniorities for s in inferred_sens) or (
                    stub_sen in norm_cfg.seniorities
                ):
                    seniority_matched = True

            # Must pass at least title or seniority match
            if not title_matched and not seniority_matched:
                return False, "title_rejected"

        # Rule 5: Organization location compatibility (only if known in stub)
        if norm_cfg.organization_locations:
            stub_locs = [
                org.get("country"),
                org.get("state"),
                org.get("city"),
                org.get("raw_address"),
                person.get("country"),
                person.get("state"),
                person.get("city"),
            ]
            loc_strings = [str(l).strip().lower() for l in stub_locs if l and str(l).strip()]
            if loc_strings:
                matched_loc = False
                for target_loc in norm_cfg.organization_locations:
                    t_loc = target_loc.lower()
                    for l_str in loc_strings:
                        if t_loc in l_str or l_str in t_loc:
                            matched_loc = True
                            break
                        if t_loc in ["united states", "usa", "us"] and l_str in [
                            "united states",
                            "usa",
                            "us",
                            "u.s.",
                            "u.s.a.",
                        ]:
                            matched_loc = True
                            break
                    if matched_loc:
                        break
                if not matched_loc:
                    return False, "location_rejected"

        # Rule 6: Employee count / company size compatibility (only if known in stub)
        if norm_cfg.employee_ranges:
            emp_count = org.get("estimated_num_employees")
            if emp_count is not None and isinstance(emp_count, (int, float)) and emp_count > 0:
                bounds: List[Tuple[int, int]] = []
                for label, lo, hi in APOLLO_EMPLOYEE_BUCKETS:
                    if label in norm_cfg.employee_ranges:
                        bounds.append((lo, hi))
                if bounds:
                    min_emp = min(b[0] for b in bounds)
                    max_emp = max(b[1] for b in bounds)
                    if emp_count < min_emp * 0.7 or emp_count > max_emp * 1.4:
                        return False, "company_size_rejected"

        # Rule 7: Hard Industry qualification check
        if not cls._matches_target_industry(person, norm_cfg):
            return False, "industry_rejected"

        # Rule 8: Technology / Category keywords check
        if not cls._matches_target_technology(person, norm_cfg):
            return False, "technology_rejected"

        return True, None

    @classmethod
    def _is_prequalified(cls, person: Dict[str, Any], norm_cfg: NormalizedICPConfig) -> bool:
        """
        Lightweight check using ONLY information available in the search response stub.
        Never calls external APIs. Does not over-reject missing optional fields.
        """
        is_prequal, _ = cls._check_prequalification(person, norm_cfg)
        return is_prequal


    # ------------------------------------------------------------------
    # Pre-score stub dictionary
    # ------------------------------------------------------------------

    @staticmethod
    def _stub_dict(person: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a scorable dict from an Apollo search stub.
        """
        org = person.get("organization") or {}
        return {
            "title": person.get("title") or "",
            "company_size": str(org.get("estimated_num_employees") or ""),
            "employee_count": org.get("estimated_num_employees"),
            "industry": org.get("industry") or "",
            "tech_stack": org.get("technologies") or [],
            "funding_stage": org.get("latest_funding_stage") or "",
            "apollo_id": person.get("id") or "",
        }

    # ------------------------------------------------------------------
    # Bulk match helper (Batches of 10)
    # ------------------------------------------------------------------

    async def _bulk_match(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, Any],
        people: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Call Apollo bulk_match in batches of 10 and return all enriched matches."""
        enriched: List[Dict[str, Any]] = []
        for i in range(0, len(people), 10):
            batch = people[i : i + 10]
            details = [{"id": p["id"]} for p in batch if p.get("id")]
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
    # Conditional org enrichment
    # ------------------------------------------------------------------

    async def _enrich_org(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, Any],
        org_id: str,
    ) -> Dict[str, Any]:
        """
        Call organizations/enrich to fill missing firmographic fields.
        Fired only when funding_stage + industry + tech_stack are blank.
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
    # Dedupe against recently enriched contacts in DB
    # ------------------------------------------------------------------

    async def _get_recently_enriched_apollo_ids(
        self, apollo_ids: List[str]
    ) -> Set[str]:
        """Return apollo_ids of contacts enriched within the last 7 days."""
        if not apollo_ids:
            return set()
        cutoff = datetime.utcnow() - timedelta(days=7)
        result = await self.db.execute(
            select(Contact.apollo_id)
            .where(Contact.apollo_id.in_(apollo_ids))
            .where(Contact.enriched_at >= cutoff)
        )
        return {row[0] for row in result.all() if row[0]}

    # ------------------------------------------------------------------
    # Parse Apollo response into Contact dictionary
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

        # Parse technologies from current_technologies
        techs = organization.get("current_technologies") or []
        tech_list = []
        if isinstance(techs, list):
            for t in techs:
                if isinstance(t, dict) and t.get("name"):
                    tech_list.append(t["name"])
                elif isinstance(t, str):
                    tech_list.append(t)

        if not tech_list and organization.get("technology_names"):
            tech_list = organization.get("technology_names") or []

        if not tech_list and organization.get("technologies"):
            tech_list = organization.get("technologies") or []

        email_status = (person.get("email_status") or "").lower()
        is_valid_email = email_status in ("verified", "valid", "guessed", "extrapolated") or bool(
            person.get("email")
        )

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
            "geography": person.get("city") or person.get("country") or organization.get("country") or "",
            "tech_stack": tech_list,
            "funding_stage": organization.get("latest_funding_stage")
            or organization.get("funding_stage")
            or "",
            "apollo_id": person.get("id") or "",
            "_org_id": organization.get("id") or "",
            "source": "apollo",
            "email_valid": is_valid_email,
            "email_verified": email_status in ("verified", "valid"),
        }

    # ------------------------------------------------------------------
    # Save contacts with multi-user isolation
    # ------------------------------------------------------------------

    async def _save_contacts(
        self,
        contacts: List[Dict[str, Any]],
        user_input_id: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        inserted_ids: List[str] = []
        updated_ids: List[str] = []

        now = datetime.utcnow()

        for data in contacts:
            email = (data.get("email") or "").strip().lower()
            if not email:
                continue

            if user_id:
                result = await self.db.execute(
                    select(Contact).where(
                        Contact.email == email,
                        Contact.user_id == user_id,
                    )
                )
            else:
                result = await self.db.execute(
                    select(Contact).where(Contact.email == email)
                )
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
                contact.verified_at = now
                contact.enriched_at = now
                contact.source = "apollo"
                if user_input_id is not None:
                    contact.user_input_id = user_input_id
                if user_id is not None:
                    contact.user_id = user_id
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
                    verified_at=now,
                    enriched_at=now,
                    source="apollo",
                    apollo_id=data.get("apollo_id"),
                    user_input_id=user_input_id,
                    user_id=user_id,
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
        final_prospects: List[Dict[str, Any]],
        save_result: Dict[str, Any],
        telemetry: Dict[str, Any],
    ) -> str:
        if not final_prospects:
            return (
                telemetry.get("exhaustion_reason")
                or telemetry.get("reason")
                or "no_qualified_prospects_found"
            )
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