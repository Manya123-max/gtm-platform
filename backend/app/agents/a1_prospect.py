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

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Contact, FunnelEvent, ContactUserInputAssociation
from app.services.scoring_service import WinPatternScorer
from app.services.prospect_summary import generate_selection_summary

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

        from app.services.company_lookalike_service import CompanyLookalikeService

        raw_lookalikes = icp_config.get("company_lookalike") or []
        seed_companies = CompanyLookalikeService.normalize_reference_companies(raw_lookalikes)

        use_apollo = icp_config.get("use_apollo")
        # Step 1: Discover prospects matching standard ICP criteria via live Apollo API
        if use_apollo is False or not settings.APOLLO_API_KEY:
            logger.warning("A1: Live Apollo API discovery unavailable - missing or disabled API key")
            raw_contacts = []
            provider_meta = {
                "provider": "apollo",
                "method": "people_search_bulk_match",
                "page": None,
                "reason": "missing_apollo_api_key",
                "total_entries": 0,
                "raw_search_count": 0,
            }
        else:
            raw_contacts, provider_meta = await self._fetch_from_apollo(icp_config)
            # Live discovery only: never fall back to CSV or seeded offline prospects

        # Step 2: Discover prospects via Company Look-alike if reference companies provided
        if seed_companies:
            logger.info("A1: Running Company Look-alike discovery", seeds=seed_companies)
            lookalike_contacts = []
            lookalike_meta = {}

            if use_apollo is False or not settings.APOLLO_API_KEY:
                logger.warning("A1 Lookalike: Live Apollo API unavailable for lookalikes")
                lookalike_meta = {
                    "provider": "apollo",
                    "method": "lookalike_people_search",
                    "reason": "missing_apollo_api_key",
                    "seed_company_names": seed_companies,
                }
            else:
                lookalike_contacts, lookalike_meta = await self._fetch_lookalikes_from_apollo(icp_config, seed_companies)
                # Live discovery only: never fall back to CSV or seeded offline prospects

            # Step 3: Combine and deduplicate candidates from both discovery paths
            raw_contacts = CompanyLookalikeService.combine_and_deduplicate_prospects(
                icp_prospects=raw_contacts,
                lookalike_prospects=lookalike_contacts,
                seed_company_names=lookalike_meta.get("seed_company_names", seed_companies),
                seed_org_ids=lookalike_meta.get("resolved_org_ids", []),
                seed_domains=lookalike_meta.get("seed_domains", []),
            )
            provider_meta["lookalike_meta"] = lookalike_meta
            if lookalike_contacts and provider_meta.get("method"):
                provider_meta["method"] = f"{provider_meta['method']}_with_lookalikes"

        if icp_config.get("signals"):
            from app.services.apollo_signals_service import ApolloSignalsService
            sig_diag = ApolloSignalsService.classify_signals(icp_config["signals"])
            provider_meta["signals_diagnostics"] = {
                "supported_applied": sig_diag["supported_company_tags"],
                "includes_recent_funding": sig_diag["includes_recent_funding"],
                "unsupported_signals": sig_diag["unsupported_signals"],
            }
            if sig_diag["unsupported_signals"]:
                logger.info(
                    "A1: User selected signals with API/integration limitations",
                    unsupported_count=len(sig_diag["unsupported_signals"]),
                    unsupported_signals=[u["signal"] for u in sig_diag["unsupported_signals"]],
                )

        logger.info(
            "Prospect fetch complete",
            count=len(raw_contacts),
            **provider_meta,
        )

        scored = await self._score_contacts(raw_contacts)
        threshold = icp_config.get("threshold", settings.ICP_SCORE_THRESHOLD)
        qualified = [c for c in scored if c.get("win_pattern_score", 0) >= threshold]
        contacts_to_save = qualified if qualified else scored

        save_result = await self._save_contacts(
            contacts_to_save, icp_config.get("user_input_id"), icp_config.get("user_id")
        )

        # ── Pipeline Step: A1.5 Salesforce Account Verification ──
        # Runs internally after A1 discovers & saves prospects, before A2 signal intelligence
        try:
            from app.agents.a1_5_salesforce_verification import SalesforceVerificationAgent
            sf_agent = SalesforceVerificationAgent(self.db)
            await sf_agent.verify_prospect_accounts(contacts_to_save)
        except Exception as sf_err:
            logger.warning("A1: Post-discovery A1.5 Salesforce verification warning", error=str(sf_err))

        reason = self._reason(raw_contacts, scored, qualified, save_result, provider_meta)
        provider = provider_meta.get("provider", "apollo")

        await self._log_funnel_event(
            "prospect_batch_completed",
            {
                "provider": provider,
                "discovery_method": provider_meta.get("method"),
                "provider_page": provider_meta.get("page"),
                "icp_fingerprint": provider_meta.get("icp_fingerprint"),
                "raw_count": len(raw_contacts),
                "scored_count": len(scored),
                "qualified_count": len(qualified),
                "reason": reason,
                **save_result,
            },
        )

        return {
            "agent": "A1",
            "provider": provider,
            "status": "LIVE" if provider == "apollo" and raw_contacts else ("FALLBACK" if provider == "offline" and raw_contacts else "UNAVAILABLE"),
            "discovery_method": provider_meta.get("method"),
            "provider_page": provider_meta.get("page"),
            "raw_count": len(raw_contacts),
            "scored_count": len(scored),
            "qualified_count": len(qualified),
            "reason": reason,
            "signals_diagnostics": provider_meta.get("signals_diagnostics"),
            **save_result,
            "contacts": [c.get("email") for c in qualified[:5]],
        }

    # ------------------------------------------------------------------
    # Apollo fetch — filter-before-enrich pipeline
    # ------------------------------------------------------------------

    def _compute_icp_fingerprint(self, icp_config: Dict[str, Any]) -> str:
        key_dict = {
            "titles": sorted(icp_config.get("titles") or []),
            "locations": sorted(icp_config.get("organization_locations") or icp_config.get("geographies") or []),
            "ranges": sorted(icp_config.get("employee_ranges") or []),
            "keywords": sorted(icp_config.get("org_keyword_tags") or icp_config.get("keywords") or []),
            "industries": sorted(icp_config.get("industry_tag_ids") or []),
        }
        raw = json.dumps(key_dict, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def _get_highest_page_for_fingerprint(self, fingerprint: str) -> int:
        res = await self.db.execute(
            select(FunnelEvent.event_metadata)
            .where(
                FunnelEvent.event_type == "prospect_batch_completed",
                FunnelEvent.agent_id == "A1",
            )
            .order_by(FunnelEvent.timestamp.desc())
        )
        events = res.scalars().all()
        max_page = 0
        for meta in events:
            if isinstance(meta, dict) and meta.get("icp_fingerprint") == fingerprint:
                page = meta.get("provider_page") or 0
                if page > max_page:
                    max_page = page
        return max_page

    def _is_apollo_result_relevant(self, contact: Dict[str, Any], icp_config: Dict[str, Any]) -> bool:
        target_titles = icp_config.get("titles") or []
        if isinstance(target_titles, str):
            target_titles = [t.strip() for t in target_titles.split(",") if t.strip()]

        contact_title = (contact.get("title") or "").strip().lower()

        # Common job title abbreviation expansions
        ABBR = {
            "vp": "vice president",
            "cro": "chief revenue officer",
            "cto": "chief technology officer",
            "cio": "chief information officer",
            "cdo": "chief digital officer",
            "cmo": "chief marketing officer",
            "cfo": "chief financial officer",
            "coo": "chief operating officer",
            "admin": "administrator",
            "ops": "operations",
            "dir": "director",
            "head": "head",
        }

        STOPWORDS = {"of", "the", "and", "&", "in", "for", "to", "a", "an", "at"}

        def expand_and_tokenize(text: str) -> set:
            words = re.findall(r"[a-zA-Z0-9]+", text.lower())
            tokens = set()
            for w in words:
                if w in STOPWORDS:
                    continue
                tokens.add(w)
                if w in ABBR:
                    tokens.update(ABBR[w].split())
            return tokens

        if target_titles and contact_title:
            c_tokens = expand_and_tokenize(contact_title)
            title_matched = False
            for tt in target_titles:
                tt_lower = tt.strip().lower()
                if tt_lower in contact_title or contact_title in tt_lower:
                    title_matched = True
                    break
                t_tokens = expand_and_tokenize(tt_lower)
                if not t_tokens:
                    continue
                overlap = t_tokens.intersection(c_tokens)
                if len(overlap) >= len(t_tokens) or len(overlap) >= 2 or (len(t_tokens) == 1 and len(overlap) == 1):
                    title_matched = True
                    break
            if not title_matched:
                return False

        # Location check
        raw_loc = icp_config.get("organization_locations") or icp_config.get("geographies") or icp_config.get("target_location")
        if isinstance(raw_loc, list):
            raw_loc = " ".join(raw_loc)
        target_loc = (raw_loc or "").strip().lower()
        contact_geo = (contact.get("geography") or "").strip().lower()

        if target_loc and contact_geo:
            us_indicators = {"united states", "usa", "us", "u.s.", "u.s.a."}
            is_us_target = any(ind in target_loc for ind in us_indicators)

            us_states = {
                "alabama", "al", "alaska", "ak", "arizona", "az", "arkansas", "ar", "california", "ca",
                "colorado", "co", "connecticut", "ct", "delaware", "de", "florida", "fl", "georgia", "ga",
                "hawaii", "hi", "idaho", "id", "illinois", "il", "indiana", "in", "iowa", "ia",
                "kansas", "ks", "kentucky", "ky", "louisiana", "la", "maine", "me", "maryland", "md",
                "massachusetts", "ma", "michigan", "mi", "minnesota", "mn", "mississippi", "ms", "missouri", "mo",
                "montana", "mt", "nebraska", "ne", "nevada", "nv", "new hampshire", "nh", "new jersey", "nj",
                "new mexico", "nm", "new york", "ny", "north carolina", "nc", "north dakota", "nd", "ohio", "oh",
                "oklahoma", "ok", "oregon", "or", "pennsylvania", "pa", "rhode island", "ri", "south carolina", "sc",
                "south dakota", "sd", "tennessee", "tn", "texas", "tx", "utah", "ut", "vermont", "vt",
                "virginia", "va", "washington", "wa", "west virginia", "wv", "wisconsin", "wi", "wyoming", "wy"
            }

            contact_tokens = {t.strip() for t in re.split(r"[,/ ]+", contact_geo) if t.strip()}
            if is_us_target:
                is_us_contact = (
                    any(ind in contact_geo for ind in us_indicators) or
                    bool(contact_tokens.intersection(us_states))
                )
                non_us_countries = {"india", "germany", "france", "uk", "united kingdom", "canada", "brazil", "chile", "poland", "zambia", "australia", "spain", "italy", "china", "japan"}
                has_non_us = bool(contact_tokens.intersection(non_us_countries))
                if has_non_us and not is_us_contact:
                    return False
            else:
                if target_loc not in contact_geo and not any(t in contact_geo for t in target_loc.split() if len(t) > 2):
                    return False

        return True

    @staticmethod
    def _load_csv_candidates() -> List[Dict[str, Any]]:
        """Load candidate prospects from prospects_export.csv."""
        import csv
        import json
        from pathlib import Path

        candidates_paths = [
            Path("/app/prospects_export.csv"),
            Path(__file__).resolve().parent.parent.parent / "prospects_export.csv",
            Path("prospects_export.csv"),
        ]
        csv_file = None
        for p in candidates_paths:
            if p.exists():
                csv_file = p
                break

        csv_candidates = []
        if csv_file:
            with open(csv_file, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = (row.get("email") or "").strip().lower()
                    if not email:
                        continue

                    tech_raw = row.get("tech_stack")
                    tech_list = []
                    if tech_raw:
                        try:
                            tech_list = json.loads(tech_raw) if isinstance(tech_raw, str) else tech_raw
                        except Exception:
                            tech_list = [t.strip() for t in str(tech_raw).split(",") if t.strip()]

                    geo = (row.get("geography") or "").strip()
                    prospect_loc = (row.get("prospect_location") or geo or "").strip() or None

                    csv_candidates.append({
                        "email": email,
                        "first_name": row.get("first_name") or "",
                        "last_name": row.get("last_name") or "",
                        "title": row.get("title") or "",
                        "company": row.get("company") or "",
                        "company_domain": row.get("company_domain") or "",
                        "linkedin_url": row.get("linkedin_url") or "",
                        "company_size": row.get("company_size") or "",
                        "employee_count": int(row["employee_count"]) if row.get("employee_count") and str(row["employee_count"]).isdigit() else None,
                        "industry": row.get("industry") or "",
                        "geography": geo,
                        "prospect_location": prospect_loc,
                        "work_mode": row.get("work_mode") or "Not specified",
                        "location_source": "Offline/Database",
                        "tech_stack": tech_list if isinstance(tech_list, list) else [],
                        "funding_stage": row.get("funding_stage") or "",
                        "apollo_id": row.get("apollo_id") or "",
                        "source": "offline_store",
                        "email_valid": True,
                        "email_verified": True,
                    })
        return csv_candidates

    async def _fetch_offline(
        self, icp_config: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Offline fallback prospect store.
        Loads real prospects from prospects_export.csv without calling Apollo API.
        """
        csv_candidates = self._load_csv_candidates()

        enrich_limit = int(icp_config.get("enrich_limit", getattr(settings, "APOLLO_ENRICH_LIMIT", 10)))
        target_titles = [t.lower() for t in (icp_config.get("titles") or []) if t]

        matched = []
        if target_titles:
            for c in csv_candidates:
                c_title = (c.get("title") or "").lower()
                if any(tt in c_title or c_title in tt for tt in target_titles):
                    matched.append(c)

        candidates = matched if matched else csv_candidates
        selected = candidates[:enrich_limit]

        return selected, {
            "provider": "offline",
            "method": "offline_prospect_store",
            "page": 1,
            "total_entries": len(csv_candidates),
            "raw_search_count": len(csv_candidates),
            "candidates_after_dedup": len(selected),
            "reason": "offline_prospects_loaded",
        }

    async def _fetch_lookalikes_from_offline(
        self, icp_config: Dict[str, Any], seed_companies: List[str]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Discover lookalike prospects from offline candidates based on firmographics."""
        from app.services.company_lookalike_service import CompanyLookalikeService
        csv_candidates = self._load_csv_candidates()
        enrich_limit = int(icp_config.get("enrich_limit", getattr(settings, "APOLLO_ENRICH_LIMIT", 10)))
        lookalikes = CompanyLookalikeService.offline_lookalike_discovery(
            seed_companies=seed_companies,
            icp_config=icp_config,
            csv_candidates=csv_candidates,
            limit=enrich_limit,
        )
        return lookalikes, {
            "provider": "offline",
            "method": "offline_lookalike_store",
            "seed_company_names": seed_companies,
            "resolved_org_ids": [],
            "count": len(lookalikes),
            "reason": "offline_lookalikes_found" if lookalikes else "offline_lookalikes_empty",
        }

    async def _fetch_lookalikes_from_apollo(
        self, icp_config: Dict[str, Any], seed_companies: List[str]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Search Apollo People Search using lookalike_organization_ids.
        Applies compatible ICP filters and strictly excludes seed reference companies.
        """
        if not settings.APOLLO_API_KEY:
            return [], {
                "provider": "apollo",
                "method": "lookalike_people_search",
                "reason": "missing_apollo_api_key",
            }

        from app.services.company_lookalike_service import CompanyLookalikeService

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": settings.APOLLO_API_KEY,
        }
        enrich_limit = int(icp_config.get("enrich_limit", getattr(settings, "APOLLO_ENRICH_LIMIT", 25)))
        all_existing_apollo_ids = await self._get_all_existing_apollo_ids()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # 1. Resolve seed reference companies
                resolution = await CompanyLookalikeService.resolve_reference_companies(
                    client, headers, seed_companies
                )
                resolved_org_ids = resolution.get("resolved_org_ids", [])
                seed_company_names = resolution.get("seed_company_names", [])

                if not resolved_org_ids:
                    logger.warning("A1 Lookalike: No seed companies could be resolved", resolution=resolution)
                    return [], {
                        "provider": "apollo",
                        "method": "lookalike_people_search",
                        "reason": "no_seed_companies_resolved",
                        **resolution,
                    }

                # 2. Build Apollo People Search payload with lookalike_organization_ids
                body = self._build_search_body(icp_config, page=1, per_page=100)
                body["lookalike_organization_ids"] = resolved_org_ids[:5]

                search_resp = await client.post(
                    "https://api.apollo.io/api/v1/mixed_people/api_search",
                    headers=headers,
                    json=body,
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()

                people = search_data.get("people") or search_data.get("contacts") or []
                if not people:
                    return [], {
                        "provider": "apollo",
                        "method": "lookalike_people_search",
                        "reason": "lookalike_search_returned_no_people",
                        **resolution,
                    }

                # 3. Pre-score stubs
                stub_scored: List[Tuple[float, Dict]] = []
                for person in people:
                    stub = self._stub_dict(person)
                    score, _ = self.scorer.score(stub)
                    stub_scored.append((score, person))

                stub_scored.sort(key=lambda x: x[0], reverse=True)
                top_candidates = [p for _, p in stub_scored[:enrich_limit]]

                to_enrich = [
                    p for p in top_candidates
                    if p.get("id") and p["id"] not in all_existing_apollo_ids
                ]

                if not to_enrich:
                    return [], {
                        "provider": "apollo",
                        "method": "lookalike_people_search",
                        "reason": "all_lookalike_candidates_already_in_db",
                        **resolution,
                    }

                # 4. Bulk match top candidates
                enriched_people = await self._bulk_match(client, headers, to_enrich)

                contacts: List[Dict[str, Any]] = []
                for person in enriched_people:
                    if not person.get("email"):
                        continue
                    contact = self._parse_apollo_contact(person)
                    if not self._is_apollo_result_relevant(contact, icp_config):
                        continue

                    contact["source"] = "apollo (lookalike)"
                    contact["discovery_method"] = "lookalike"
                    contact["lookalike_seed_companies"] = list(seed_companies)

                    # Org enrich if needed
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
                            if org_data.get("total_funding_printed"):
                                contact["funding_amount"] = org_data["total_funding_printed"]
                            if org_data.get("latest_funding_round_date"):
                                contact["funding_date"] = org_data["latest_funding_round_date"]

                    if icp_config.get("signals"):
                        contact["matched_signals"] = [s for s in icp_config["signals"] if s]
                        if not contact.get("discovery_method"):
                            contact["discovery_method"] = "signals"

                    contacts.append(contact)

                return contacts, {
                    "provider": "apollo",
                    "method": "lookalike_people_search",
                    "count": len(contacts),
                    "reason": "lookalike_contacts_found" if contacts else "lookalike_bulk_match_no_emails",
                    **resolution,
                }

        except httpx.TimeoutException as exc:
            logger.error("Apollo lookalike fetch timed out", error=str(exc))
            return [], {
                "provider": "apollo",
                "method": "lookalike_people_search",
                "reason": "apollo_timeout",
            }
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            logger.error("Apollo lookalike fetch failed", status_code=status_code)
            reason = "apollo_rate_limited" if status_code == 429 else f"apollo_http_{status_code}"
            return [], {
                "provider": "apollo",
                "method": "lookalike_people_search",
                "reason": reason,
            }
        except Exception as exc:
            logger.exception("Apollo lookalike fetch error", error=str(exc))
            return [], {
                "provider": "apollo",
                "method": "lookalike_people_search",
                "reason": "apollo_lookalike_request_failed",
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

        max_pages = max(1, int(icp_config.get("max_pages", settings.APOLLO_SEARCH_MAX_PAGES)))
        enrich_limit = int(icp_config.get("enrich_limit", getattr(settings, "APOLLO_ENRICH_LIMIT", 25)))
        threshold = icp_config.get("threshold", settings.ICP_SCORE_THRESHOLD)

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": settings.APOLLO_API_KEY,
        }

        # ── Step 1: Page progression using ICP fingerprint ───────────────────
        fingerprint = self._compute_icp_fingerprint(icp_config)
        requested_page = icp_config.get("page")
        if requested_page:
            start_page = int(requested_page)
        else:
            highest_page = await self._get_highest_page_for_fingerprint(fingerprint)
            start_page = (highest_page + 1) if highest_page > 0 else 1

        if start_page > max_pages:
            start_page = 1

        actual_page = start_page
        all_existing_apollo_ids = await self._get_all_existing_apollo_ids()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                body = self._build_search_body(icp_config, page=actual_page, per_page=100)
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
                raw_search_count = len(people)

                # Pre-score stubs
                stub_scored: List[Tuple[float, Dict]] = []
                for person in people:
                    stub = self._stub_dict(person)
                    score, _ = self.scorer.score(stub)
                    stub_scored.append((score, person))

                stub_scored.sort(key=lambda x: x[0], reverse=True)
                top_candidates = [p for _, p in stub_scored[:enrich_limit]]

                # Step 4: Cross-search deduplication against ALL existing apollo_ids in DB
                to_enrich = [
                    p for p in top_candidates
                    if p.get("id") and p["id"] not in all_existing_apollo_ids
                ]

                # Step 4b: Cap page retry at exactly 1 extra attempt
                if not to_enrich and actual_page < max_pages:
                    retry_page = actual_page + 1
                    logger.info("A1: Page yielded no fresh candidates, attempting 1 extra page retry", retry_page=retry_page)
                    body["page"] = retry_page
                    search_resp2 = await client.post(
                        "https://api.apollo.io/api/v1/mixed_people/api_search",
                        headers=headers,
                        json=body,
                    )
                    if search_resp2.status_code == 200:
                        search_data2 = search_resp2.json()
                        people2 = search_data2.get("people") or search_data2.get("contacts") or []
                        if people2:
                            actual_page = retry_page
                            people = people2
                            raw_search_count += len(people2)
                            stub_scored2: List[Tuple[float, Dict]] = []
                            for person in people2:
                                stub = self._stub_dict(person)
                                score, _ = self.scorer.score(stub)
                                stub_scored2.append((score, person))
                            stub_scored2.sort(key=lambda x: x[0], reverse=True)
                            top_candidates = [p for _, p in stub_scored2[:enrich_limit]]
                            to_enrich = [
                                p for p in top_candidates
                                if p.get("id") and p["id"] not in all_existing_apollo_ids
                            ]

                if not to_enrich:
                    return [], {
                        "provider": "apollo",
                        "method": "people_search_bulk_match",
                        "page": actual_page,
                        "icp_fingerprint": fingerprint,
                        "total_entries": total_entries,
                        "raw_search_count": raw_search_count,
                        "candidates_after_dedup": 0,
                        "reason": "all_candidates_already_in_db" if people else "apollo_people_search_empty",
                    }

                # Step 5: Bulk match (pay for enrichment) — top N only
                enriched_people = await self._bulk_match(client, headers, to_enrich)

                if not enriched_people:
                    return [], {
                        "provider": "apollo",
                        "method": "people_search_bulk_match",
                        "page": actual_page,
                        "icp_fingerprint": fingerprint,
                        "total_entries": total_entries,
                        "raw_search_count": raw_search_count,
                        "candidates_after_dedup": len(to_enrich),
                        "reason": "apollo_bulk_match_no_results",
                    }

                # Step 6: Parse + Relevance Filter + conditional org enrich
                contacts: List[Dict[str, Any]] = []
                relevance_filtered_count = 0
                for person in enriched_people:
                    if not person.get("email"):
                        continue
                    contact = self._parse_apollo_contact(person)

                    # Defensive relevance check on title and location
                    if not self._is_apollo_result_relevant(contact, icp_config):
                        relevance_filtered_count += 1
                        logger.info(
                            "A1: Prospect dropped by relevance check",
                            title=contact.get("title"),
                            geo=contact.get("geography"),
                        )
                        continue

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
                            if org_data.get("total_funding_printed"):
                                contact["funding_amount"] = org_data["total_funding_printed"]
                            if org_data.get("latest_funding_round_date"):
                                contact["funding_date"] = org_data["latest_funding_round_date"]

                    if icp_config.get("signals"):
                        contact["matched_signals"] = [s for s in icp_config["signals"] if s]
                        if not contact.get("discovery_method"):
                            contact["discovery_method"] = "signals"

                    contacts.append(contact)

                pre_qualified_count = sum(
                    1 for c in contacts if c.get("win_pattern_score", 0) >= threshold
                )

                return contacts, {
                    "provider": "apollo",
                    "method": "people_search_bulk_match",
                    "page": actual_page,
                    "icp_fingerprint": fingerprint,
                    "total_entries": total_entries,
                    "raw_search_count": raw_search_count,
                    "candidates_after_dedup": len(to_enrich),
                    "enriched_count": len(enriched_people),
                    "relevance_filtered_count": relevance_filtered_count,
                    "pre_qualified_count": pre_qualified_count,
                    "reason": "apollo_contacts_found" if contacts else "apollo_bulk_match_no_emails",
                }

        except httpx.TimeoutException as exc:
            logger.error("Apollo fetch timed out", error=str(exc))
            return [], {
                "provider": "apollo",
                "method": "people_search_bulk_match",
                "page": actual_page,
                "reason": "apollo_timeout",
            }
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            logger.error("Apollo fetch failed", status_code=status_code)
            reason = "apollo_rate_limited" if status_code == 429 else f"apollo_http_{status_code}"
            return [], {
                "provider": "apollo",
                "method": "people_search_bulk_match",
                "page": actual_page,
                "reason": reason,
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
        Build the Apollo mixed_people/api_search request body using ApolloQueryBuilder.
        Maps ICP filters, Company Look-alikes, Signals (OR logic), and Funding stages (OR logic).
        """
        from app.services.apollo_query_builder import ApolloQueryBuilder
        return ApolloQueryBuilder.build_search_payload(icp_config, page=page, per_page=per_page)

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
    # Dedupe — check across all existing contacts in database
    # ------------------------------------------------------------------

    async def _get_all_existing_apollo_ids(self, user_id: Optional[str] = None) -> set:
        """Return all apollo_ids of contacts saved in the database for the user."""
        stmt = select(Contact.apollo_id).where(Contact.apollo_id.isnot(None))
        if user_id:
            stmt = stmt.where(Contact.user_id == user_id)
        result = await self.db.execute(stmt)
        return {row[0] for row in result.all() if row[0]}

    async def _get_all_existing_emails(self, user_id: Optional[str] = None) -> set:
        """Return all emails of contacts saved in the database for the user."""
        stmt = select(Contact.email).where(Contact.email.isnot(None))
        if user_id:
            stmt = stmt.where(Contact.user_id == user_id)
        result = await self.db.execute(stmt)
        return {row[0].strip().lower() for row in result.all() if row[0]}

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

        # Company Location (Firmographic)
        org_city = organization.get("city")
        org_state = organization.get("state")
        org_country = organization.get("country")
        org_loc_parts = [p for p in [org_city, org_state, org_country] if p]
        company_location = ", ".join(org_loc_parts) if org_loc_parts else (organization.get("raw_address") or "")

        # Prospect Location (Individual - no guessing, store actual returned value)
        p_formatted = person.get("formatted_address")
        p_city = person.get("city")
        p_state = person.get("state")
        p_country = person.get("country")
        p_loc_parts = [p for p in [p_city, p_state, p_country] if p]

        if p_formatted and len(p_formatted.split(",")) <= 4 and not any(kw in p_formatted.lower() for kw in ["suite", "avenue", "street", "building", "floor"]):
            prospect_loc = p_formatted
        elif p_loc_parts:
            prospect_loc = ", ".join(p_loc_parts)
        elif p_formatted:
            prospect_loc = p_formatted
        else:
            prospect_loc = None

        # Work Mode (Individual work arrangement: Office / Remote / Hybrid / Not specified)
        work_mode = "Not specified"
        explicit_mode = person.get("work_mode") or person.get("work_arrangement")
        if explicit_mode and str(explicit_mode).strip().lower() in ["remote", "hybrid", "office"]:
            work_mode = str(explicit_mode).strip().capitalize()
        else:
            text = f"{person.get('title') or ''} {person.get('headline') or ''}".lower()
            if re.search(r'\b(remote)\b', text):
                work_mode = "Remote"
            elif re.search(r'\b(hybrid)\b', text):
                work_mode = "Hybrid"
            elif re.search(r'\b(office|on-site|onsite)\b', text):
                work_mode = "Office"

        location_source = "Apollo" if prospect_loc else None

        return {
            "email":             (person.get("email") or "").strip().lower(),
            "first_name":        person.get("first_name") or "",
            "last_name":         person.get("last_name") or "",
            "title":             person.get("title") or "",
            "company":           organization.get("name") or "",
            "company_domain":    domain,
            "linkedin_url":      person.get("linkedin_url") or "",
            "company_size":      str(organization.get("estimated_num_employees") or ""),
            "employee_count":    organization.get("estimated_num_employees"),
            "industry":          organization.get("industry") or "",
            "geography":         company_location,
            "prospect_location": prospect_loc,
            "work_mode":         work_mode,
            "location_source":   location_source,
            "tech_stack":        tech_list,
            "funding_stage":     organization.get("latest_funding_stage") or organization.get("funding_stage") or "",
            "funding_amount":    organization.get("total_funding_printed") or (f"${organization['total_funding']:,}" if organization.get("total_funding") else None),
            "funding_date":      organization.get("latest_funding_round_date"),
            "funding_source":    organization.get("latest_funding_round_source") or "Apollo",
            "apollo_id":         person.get("id") or "",
            "_org_id":           organization.get("id") or "",   # used for conditional org enrich
            "source":            "apollo",
            "email_valid":       True,
            "email_verified":    True,
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
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        inserted_ids: List[str] = []
        all_existing_emails = await self._get_all_existing_emails(user_id=user_id)
        all_existing_apollo_ids = await self._get_all_existing_apollo_ids(user_id=user_id)

        for data in contacts:
            email = (data.get("email") or "").strip().lower()
            apollo_id = data.get("apollo_id")
            if not email:
                continue

            # Strict cross-search deduplication:
            # If a person was already collected in any past search, skip them — do not import again,
            # do not update their user_input_id, and do not link them to this search.
            if email in all_existing_emails or (apollo_id and apollo_id in all_existing_apollo_ids):
                if user_input_id is not None:
                    lookup_q = select(Contact.id).where(or_(Contact.email == email, Contact.apollo_id == apollo_id))
                    if user_id:
                        lookup_q = lookup_q.where(Contact.user_id == user_id)
                    existing_cid = await self.db.scalar(lookup_q.limit(1))
                    if existing_cid:
                        assoc_exists = await self.db.scalar(
                            select(ContactUserInputAssociation.contact_id).where(
                                ContactUserInputAssociation.contact_id == existing_cid,
                                ContactUserInputAssociation.user_input_id == user_input_id,
                            ).limit(1)
                        )
                        if not assoc_exists:
                            self.db.add(ContactUserInputAssociation(contact_id=existing_cid, user_input_id=user_input_id))
                            inserted_ids.append(str(existing_cid))
                logger.info("A1: Cross-search duplicate linked/skipped in _save_contacts", email=email, apollo_id=apollo_id)
                continue

            summary = generate_selection_summary(data)

            from app.services.suppression_service import SuppressionService
            is_suppressed, _ = await SuppressionService.is_email_suppressed(self.db, email)

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
                prospect_location=data.get("prospect_location"),
                work_mode=data.get("work_mode") or "Not specified",
                location_source=data.get("location_source"),
                selection_summary=summary,
                icp_score=data.get("win_pattern_score"),
                win_pattern_score=data.get("win_pattern_score"),
                icp_score_breakdown=data.get("icp_score_breakdown"),
                readiness_score=0.0,
                do_not_contact=is_suppressed,
                email_valid=data.get("email_valid"),
                email_verified=bool(data.get("email_verified")),
                verified_at=datetime.utcnow() if data.get("source") != "offline_store" else None,
                enriched_at=datetime.utcnow() if data.get("source") != "offline_store" else None,
                source=data.get("source", "apollo"),
                apollo_id=apollo_id,
                user_input_id=user_input_id,
                user_id=user_id,
            )
            self.db.add(contact)
            await self.db.flush()
            if user_input_id is not None:
                self.db.add(ContactUserInputAssociation(contact_id=contact.id, user_input_id=user_input_id))
            inserted_ids.append(str(contact.id))
            all_existing_emails.add(email)
            if apollo_id:
                all_existing_apollo_ids.add(apollo_id)

            # Best-effort Salesforce sync (Salesforce is Sole CRM source of truth)
            try:
                from app.services.salesforce_service import SalesforceService
                sf_service = SalesforceService()
                if sf_service.is_configured:
                    sf_id = await sf_service.sync_contact_to_salesforce({
                        "id": contact.id,
                        "email": contact.email,
                        "first_name": contact.first_name,
                        "last_name": contact.last_name,
                        "company": contact.company,
                        "title": contact.title,
                        "company_domain": contact.company_domain,
                        "geography": contact.geography,
                        "prospect_location": contact.prospect_location,
                        "selection_summary": contact.selection_summary,
                        "icp_score": contact.icp_score,
                        "salesforce_contact_id": contact.salesforce_contact_id,
                    })
                    if sf_id:
                        contact.salesforce_contact_id = sf_id
                        logger.info("A1: Synced prospect to Salesforce", email=email, salesforce_id=sf_id)
            except Exception as sf_err:
                logger.warning("A1: Best-effort Salesforce contact sync failed", email=email, error=str(sf_err))

        await self.db.commit()
        return {
            "saved_count": len(inserted_ids),
            "updated_count": 0,
            "contact_ids": inserted_ids,
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