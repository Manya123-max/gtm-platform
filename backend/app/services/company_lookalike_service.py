"""
company_lookalike_service.py — Company Look-alike Discovery and Resolution Service.

Implements company look-alike intelligence for GTM prospect discovery:
1. Normalizes and validates user-entered reference companies (enforces max 5 seed limit).
2. Resolves company names to Apollo organization records using Apollo Organization Search
   (POST https://api.apollo.io/api/v1/organizations/search) with caching and match-confidence checks.
3. Safely handles ambiguous company names, low-confidence matches, and missing companies.
4. Builds Apollo People Search payloads utilizing lookalike_organization_ids alongside compatible ICP filters.
5. Strictly excludes seed reference companies from lookalike discovery results.
6. Combines and deduplicates prospects discovered via ICP search and look-alike search.
7. Provides offline similarity fallback using firmographic attributes when Apollo API is offline.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Apollo supports a maximum of 5 seed companies for lookalike discovery
MAX_SEED_COMPANIES = 5

# Common legal and corporate suffixes stripped during normalization
CORP_SUFFIX_PATTERN = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c\.|corp|corporation|co|company|ltd|limited|pvt|plc|gmbh|sa|holding|holdings|group|technologies|technology|tech|solutions|international|global)\b",
    re.IGNORECASE,
)

# In-memory resolution cache (query_name_lower -> resolution_dict)
_ORGANIZATION_RESOLUTION_CACHE: Dict[str, Dict[str, Any]] = {}


def clean_company_name(name: str) -> str:
    """Normalize company name by removing punctuation, corporate suffixes, and excess whitespace."""
    if not name:
        return ""
    text = name.strip().lower()
    # Remove domain protocols/slashes if user typed a url
    text = re.sub(r"^https?://(www\.)?", "", text)
    text = text.split("/")[0]
    # Remove common corporate suffixes
    cleaned = CORP_SUFFIX_PATTERN.sub("", text)
    # Remove punctuation
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else text.strip()


class CompanyLookalikeService:
    """Service for resolving seed companies, querying lookalikes, and merging results."""

    STANDALONE_CORP_SUFFIXES = {
        "inc", "inc.", "incorporated", "llc", "l.l.c.", "corp", "corp.",
        "corporation", "co", "co.", "company", "ltd", "ltd.", "limited",
        "pvt", "plc", "gmbh", "sa"
    }

    @classmethod
    def normalize_reference_companies(
        cls,
        raw_companies: Union[str, List[str]],
        max_seeds: int = MAX_SEED_COMPANIES
    ) -> List[str]:
        """
        Normalize and validate reference company names.
        Trims whitespace, merges comma-separated legal suffixes (e.g. RadNet, Inc.),
        removes duplicates case-insensitively, and enforces the max seed limit.
        """
        if not raw_companies:
            return []

        if isinstance(raw_companies, str):
            raw_tokens = re.split(r"[\r\n,]+", raw_companies)
        elif isinstance(raw_companies, list):
            raw_tokens = []
            for item in raw_companies:
                if isinstance(item, str):
                    raw_tokens.extend(re.split(r"[\r\n,]+", item))
                elif item:
                    raw_tokens.append(str(item))
        else:
            raw_tokens = [str(raw_companies)]

        # Merge standalone corporate suffixes caused by comma separation (e.g. ['RadNet', 'Inc.'])
        merged_tokens: List[str] = []
        for t in raw_tokens:
            cleaned = t.strip()
            if not cleaned:
                continue
            if cleaned.lower() in cls.STANDALONE_CORP_SUFFIXES and merged_tokens:
                merged_tokens[-1] = f"{merged_tokens[-1]}, {cleaned}"
            else:
                merged_tokens.append(cleaned)

        seen: Set[str] = set()
        normalized: List[str] = []
        for cleaned in merged_tokens:
            lower = cleaned.lower()
            if lower not in seen:
                seen.add(lower)
                normalized.append(cleaned)
            if len(normalized) >= max_seeds:
                break

        return normalized

    @classmethod
    def compute_match_confidence(
        cls, query: str, candidate_org: Dict[str, Any]
    ) -> float:
        """
        Compute match confidence score between query and candidate organization [0.0 - 1.0].
        Considers exact name, cleaned name, domain match, and token overlap.
        """
        query_raw = query.strip().lower()
        query_clean = clean_company_name(query)

        org_name = (candidate_org.get("name") or "").strip().lower()
        org_clean = clean_company_name(org_name)
        domain = (
            candidate_org.get("primary_domain")
            or candidate_org.get("website_url")
            or ""
        ).strip().lower()
        domain_clean = re.sub(r"^https?://(www\.)?", "", domain).split("/")[0]
        domain_name = domain_clean.split(".")[0] if "." in domain_clean else domain_clean

        # 1. Exact raw match
        if query_raw == org_name:
            return 1.0

        # 2. Exact cleaned name match
        if query_clean and query_clean == org_clean:
            return 0.98

        # 3. Exact domain root match
        if query_clean and query_clean == domain_name:
            return 0.95

        # 4. Domain contains or equals query
        if query_raw and domain_clean and (query_raw == domain_clean or f"{query_raw}." in domain_clean):
            return 0.92

        # 5. Token set match
        q_tokens = set(query_clean.split())
        org_tokens = set(org_clean.split())
        if q_tokens and org_tokens:
            intersection = q_tokens.intersection(org_tokens)
            if intersection == q_tokens:
                # Query is a complete subset of org name
                return 0.85
            ratio = len(intersection) / max(len(q_tokens), len(org_tokens))
            if ratio >= 0.6:
                return round(0.5 + (0.4 * ratio), 2)

        # 6. Prefix match
        if query_clean and org_clean.startswith(query_clean):
            return 0.80

        return 0.20

    @classmethod
    async def resolve_company_name(
        cls,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        company_name: str,
    ) -> Dict[str, Any]:
        """
        Resolve a single company name to an Apollo organization record using Organization Search.
        Includes match-confidence check and caching.
        """
        cache_key = company_name.strip().lower()
        if cache_key in _ORGANIZATION_RESOLUTION_CACHE:
            return _ORGANIZATION_RESOLUTION_CACHE[cache_key]

        payload = {
            "q_organization_name": company_name.strip(),
            "page": 1,
            "per_page": 5,
        }

        try:
            # Apollo Organization Search endpoint
            resp = await client.post(
                "https://api.apollo.io/api/v1/organizations/search",
                headers=headers,
                json=payload,
            )
            if resp.status_code == 404:
                # Some Apollo plans expose mixed_companies/search
                resp = await client.post(
                    "https://api.apollo.io/api/v1/mixed_companies/search",
                    headers=headers,
                    json=payload,
                )

            if resp.status_code == 429:
                logger.warning("Apollo org search rate limited (429)", company=company_name)
                return {
                    "status": "error",
                    "reason": "rate_limited",
                    "query": company_name,
                }

            if resp.status_code != 200:
                logger.warning(
                    "Apollo org search failed",
                    status=resp.status_code,
                    company=company_name,
                )
                return {
                    "status": "error",
                    "reason": f"http_{resp.status_code}",
                    "query": company_name,
                }

            data = resp.json()
            organizations = data.get("organizations") or data.get("accounts") or []

            if not organizations:
                result = {
                    "status": "not_found",
                    "query": company_name,
                    "reason": "no_organizations_returned",
                }
                _ORGANIZATION_RESOLUTION_CACHE[cache_key] = result
                return result

            # Score each returned candidate
            scored_candidates = []
            for org in organizations:
                conf = cls.compute_match_confidence(company_name, org)
                scored_candidates.append((conf, org))

            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            top_score, top_org = scored_candidates[0]

            # Ambiguity check: if top score is marginal or multiple close competitors exist
            if len(scored_candidates) > 1:
                second_score, second_org = scored_candidates[1]
                # If not an exact match (>= 0.95) and close to 2nd candidate, or top score is low, mark ambiguous
                if (top_score < 0.95 and (top_score - second_score) < 0.15) or top_score < 0.70:
                    result = {
                        "status": "ambiguous",
                        "query": company_name,
                        "confidence": top_score,
                        "candidates": [
                            {
                                "name": o.get("name"),
                                "domain": o.get("primary_domain") or o.get("website_url"),
                                "score": s,
                            }
                            for s, o in scored_candidates[:3]
                        ],
                        "reason": "multiple_close_matches",
                    }
                    _ORGANIZATION_RESOLUTION_CACHE[cache_key] = result
                    return result

            # Minimum acceptable confidence threshold
            if top_score < 0.70:
                result = {
                    "status": "ambiguous",
                    "query": company_name,
                    "confidence": top_score,
                    "candidates": [
                        {
                            "name": top_org.get("name"),
                            "domain": top_org.get("primary_domain") or top_org.get("website_url"),
                            "score": top_score,
                        }
                    ],
                    "reason": "low_confidence_match",
                }
                _ORGANIZATION_RESOLUTION_CACHE[cache_key] = result
                return result

            # Successfully resolved
            result = {
                "status": "resolved",
                "organization_id": top_org.get("id"),
                "name": top_org.get("name") or company_name,
                "domain": top_org.get("primary_domain") or top_org.get("website_url") or "",
                "industry": top_org.get("industry") or "",
                "employee_count": top_org.get("estimated_num_employees"),
                "confidence": top_score,
                "raw_org": top_org,
            }
            _ORGANIZATION_RESOLUTION_CACHE[cache_key] = result
            return result

        except httpx.TimeoutException:
            logger.warning("Apollo org search timeout", company=company_name)
            return {"status": "error", "reason": "timeout", "query": company_name}
        except Exception as exc:
            logger.exception("Apollo org search unexpected error", company=company_name, error=str(exc))
            return {"status": "error", "reason": "request_failed", "query": company_name}

    @classmethod
    async def resolve_reference_companies(
        cls,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        reference_companies: List[str],
    ) -> Dict[str, Any]:
        """
        Resolve a list of reference companies to their Apollo organization IDs.
        Separates successfully resolved companies, ambiguous queries, and not-found entries.
        """
        resolved_org_ids: List[str] = []
        resolved_companies: List[Dict[str, Any]] = []
        seed_company_names: List[str] = []
        seed_domains: List[str] = []
        ambiguous_companies: List[Dict[str, Any]] = []
        not_found_companies: List[str] = []
        errors: List[Dict[str, Any]] = []

        for name in reference_companies:
            res = await cls.resolve_company_name(client, headers, name)
            status = res.get("status")
            if status == "resolved":
                org_id = res.get("organization_id")
                if org_id and org_id not in resolved_org_ids:
                    resolved_org_ids.append(org_id)
                resolved_companies.append(res)
                seed_company_names.append(res.get("name", name).strip().lower())
                domain = res.get("domain") or ""
                clean_dom = re.sub(r"^https?://(www\.)?", "", domain).split("/")[0].strip().lower()
                if clean_dom:
                    seed_domains.append(clean_dom)
            elif status == "ambiguous":
                ambiguous_companies.append(res)
                seed_company_names.append(name.strip().lower())
            elif status == "not_found":
                not_found_companies.append(name)
                seed_company_names.append(name.strip().lower())
            else:
                errors.append(res)
                seed_company_names.append(name.strip().lower())

        return {
            "resolved_org_ids": resolved_org_ids[:MAX_SEED_COMPANIES],
            "resolved_companies": resolved_companies,
            "seed_company_names": list(set(seed_company_names)),
            "seed_domains": list(set(seed_domains)),
            "ambiguous_companies": ambiguous_companies,
            "not_found_companies": not_found_companies,
            "errors": errors,
        }

    @classmethod
    async def discover_similar_organizations(
        cls,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        seed_companies: List[str],
        icp_config: Dict[str, Any],
        target_count: int = 15,
    ) -> Dict[str, Any]:
        """
        Stage 1: Discover similar organizations (lookalikes) for the provided seed companies.
        1. Resolves seed reference companies to Apollo organization records.
        2. Discovers direct peers and competitors using LLM Market Intelligence + Apollo Org Search.
        3. Excludes the seed reference companies themselves.
        4. Resolves and validates discovered peer companies against Apollo's organization database.
        5. Returns structured list of verified lookalike organizations and their organization_ids.
        """
        resolution = await cls.resolve_reference_companies(client, headers, seed_companies)
        seed_company_names = resolution.get("seed_company_names", [s.strip().lower() for s in seed_companies if s])
        seed_domains = resolution.get("seed_domains", [])

        clean_seeds = {clean_company_name(s) for s in seed_companies if s}
        raw_seeds_lower = {s.strip().lower() for s in seed_companies if s}
        domains_set = {d.strip().lower() for d in seed_domains if d}

        candidate_peers: List[Dict[str, Any]] = []

        # ── Track 1: LLM Market Intelligence Competitor Discovery ──
        try:
            from app.services.llm_service import LLMService
            llm = LLMService()
            system_prompt = (
                "You are an expert B2B market researcher and competitor intelligence system. "
                "Given reference/seed company names and target market criteria, identify 10 to 15 real, active "
                "direct competitors and lookalike companies in the exact same industry and business domain. "
                "Output ONLY a valid JSON array of objects with keys 'name' and 'domain' (e.g. [{\"name\": \"Dynatrace\", \"domain\": \"dynatrace.com\"}]). "
                "Strictly exclude the seed companies themselves. Do NOT include markdown code blocks or explanations."
            )
            user_prompt = f"Seed Companies: {', '.join(seed_companies)}\n"
            if icp_config.get("target_industries"):
                user_prompt += f"Target Industry: {icp_config.get('target_industries')}\n"
            if icp_config.get("target_company_size"):
                user_prompt += f"Target Company Size: {icp_config.get('target_company_size')}\n"
            if icp_config.get("target_location"):
                user_prompt += f"Target Location: {icp_config.get('target_location')}\n"
            if icp_config.get("target_keywords"):
                user_prompt += f"Target Keywords: {icp_config.get('target_keywords')}\n"

            llm_resp = await llm.complete(system=system_prompt, user=user_prompt, max_tokens=600)
            clean_resp = re.sub(r"^```(?:json)?\s*", "", llm_resp.strip())
            clean_resp = re.sub(r"\s*```$", "", clean_resp.strip())
            parsed = json.loads(clean_resp)
            if isinstance(parsed, list):
                for p in parsed:
                    if isinstance(p, dict) and p.get("name"):
                        candidate_peers.append({
                            "name": p["name"].strip(),
                            "domain": (p.get("domain") or "").strip().lower(),
                            "source": "market_intelligence",
                        })
        except Exception as llm_err:
            logger.info("CompanyLookalikeService: LLM competitor discovery skipped or fallback", error=str(llm_err))

        # ── Track 2: Apollo Organization Search ──
        try:
            org_search_payload: Dict[str, Any] = {"page": 1, "per_page": 20}
            if icp_config.get("organization_locations"):
                org_search_payload["organization_locations"] = icp_config["organization_locations"]
            if icp_config.get("employee_ranges"):
                org_search_payload["organization_num_employees_ranges"] = icp_config["employee_ranges"]
            if icp_config.get("industry_tag_ids"):
                org_search_payload["organization_industry_tag_ids"] = icp_config["industry_tag_ids"]
            if icp_config.get("org_keyword_tags"):
                org_search_payload["q_organization_keyword_tags"] = icp_config["org_keyword_tags"][:5]

            org_resp = await client.post(
                "https://api.apollo.io/api/v1/organizations/search",
                headers=headers,
                json=org_search_payload,
            )
            if org_resp.status_code == 200:
                org_data = org_resp.json()
                apollo_orgs = org_data.get("organizations") or []
                for a_org in apollo_orgs:
                    o_name = a_org.get("name")
                    o_dom = a_org.get("primary_domain") or a_org.get("website_url") or ""
                    if o_name:
                        candidate_peers.append({
                            "name": o_name.strip(),
                            "domain": o_dom.strip().lower(),
                            "source": "apollo_org_search",
                            "apollo_org": a_org,
                        })
        except Exception as apollo_org_err:
            logger.info("CompanyLookalikeService: Apollo org search skipped", error=str(apollo_org_err))

        # ── Deduplicate and Exclude Seed Companies ──
        seen_names: Set[str] = set()
        seen_domains: Set[str] = set()
        filtered_candidates: List[Dict[str, Any]] = []

        for cand in candidate_peers:
            c_name = cand["name"].strip()
            c_clean = clean_company_name(c_name)
            c_lower = c_name.lower()
            c_dom = cand.get("domain", "").lower()
            clean_dom = re.sub(r"^https?://(www\.)?", "", c_dom).split("/")[0]

            # Rule: Strictly exclude seed companies
            if c_lower in raw_seeds_lower or c_clean in clean_seeds:
                continue
            if clean_dom and (clean_dom in domains_set or any(s in clean_dom for s in raw_seeds_lower if len(s) > 3)):
                continue

            if c_clean in seen_names:
                continue
            seen_names.add(c_clean)
            if clean_dom:
                if clean_dom in seen_domains:
                    continue
                seen_domains.add(clean_dom)

            filtered_candidates.append(cand)

        # ── Resolve Each Candidate to Verified Apollo Org ID ──
        discovered_organizations: List[Dict[str, Any]] = []
        for cand in filtered_candidates:
            if len(discovered_organizations) >= target_count:
                break

            # If candidate was already an Apollo org from Track 2
            if cand.get("apollo_org") and cand["apollo_org"].get("id"):
                a_org = cand["apollo_org"]
                discovered_organizations.append({
                    "organization_id": a_org["id"],
                    "name": a_org.get("name") or cand["name"],
                    "domain": a_org.get("primary_domain") or cand.get("domain") or "",
                    "industry": a_org.get("industry") or "",
                    "employee_count": a_org.get("estimated_num_employees"),
                    "matched_seeds": list(seed_companies),
                    "source": cand.get("source", "lookalike_expansion"),
                })
                continue

            # Otherwise resolve by name
            res = await cls.resolve_company_name(client, headers, cand["name"])
            if res.get("status") == "resolved" and res.get("organization_id"):
                org_name = res.get("name") or cand["name"]
                # Exclude if resolved to a seed company
                if org_name.lower() in raw_seeds_lower or clean_company_name(org_name) in clean_seeds:
                    continue
                discovered_organizations.append({
                    "organization_id": res["organization_id"],
                    "name": org_name,
                    "domain": res.get("domain") or cand.get("domain") or "",
                    "industry": res.get("industry") or "",
                    "employee_count": res.get("employee_count"),
                    "matched_seeds": list(seed_companies),
                    "source": cand.get("source", "lookalike_expansion"),
                })

        org_ids = [org["organization_id"] for org in discovered_organizations if org.get("organization_id")]

        logger.info(
            "CompanyLookalikeService: Stage 1 discovery complete",
            seeds=seed_companies,
            discovered_count=len(discovered_organizations),
            discovered_org_names=[o["name"] for o in discovered_organizations],
        )

        return {
            "seed_companies": seed_companies,
            "seed_resolution": resolution,
            "discovered_organizations": discovered_organizations,
            "organization_ids": org_ids,
            "count": len(discovered_organizations),
        }

    @classmethod
    def offline_discover_similar_organizations(
        cls,
        seed_companies: List[str],
        icp_config: Dict[str, Any],
        csv_candidates: Optional[List[Dict[str, Any]]] = None,
        target_count: int = 15,
    ) -> Dict[str, Any]:
        """
        Stage 1 Offline: Identifies similar organizations from local prospect store.
        """
        if csv_candidates is None:
            from app.agents.a1_prospect import ProspectAgent
            csv_candidates = ProspectAgent._load_csv_candidates()

        clean_seeds = {clean_company_name(s) for s in seed_companies if s}
        raw_seeds_lower = {s.strip().lower() for s in seed_companies if s}

        target_industries = [
            i.lower().strip() for i in (icp_config.get("industry_terms") or []) if i
        ]

        seen_companies: Set[str] = set()
        discovered_orgs: List[Dict[str, Any]] = []

        for row in csv_candidates:
            comp = (row.get("company") or "").strip()
            if not comp:
                continue
            clean_comp = clean_company_name(comp)
            comp_lower = comp.lower()
            comp_dom = (row.get("company_domain") or "").strip().lower()

            if comp_lower in raw_seeds_lower or clean_comp in clean_seeds:
                continue
            if any(s in comp_dom for s in raw_seeds_lower if len(s) > 3):
                continue
            if clean_comp in seen_companies:
                continue

            ind = (row.get("industry") or "").lower()
            if target_industries and not any(ti in ind or ind in ti for ti in target_industries):
                continue

            seen_companies.add(clean_comp)
            discovered_orgs.append({
                "organization_id": row.get("apollo_id") or f"org_{clean_comp}",
                "name": comp,
                "domain": comp_dom,
                "industry": row.get("industry") or "",
                "employee_count": row.get("employee_count"),
                "matched_seeds": list(seed_companies),
                "source": "offline_store",
            })
            if len(discovered_orgs) >= target_count:
                break

        return {
            "seed_companies": seed_companies,
            "discovered_organizations": discovered_orgs,
            "organization_ids": [o["organization_id"] for o in discovered_orgs],
            "count": len(discovered_orgs),
        }

    @staticmethod
    def build_lookalike_search_body(
        base_body: Dict[str, Any],
        lookalike_org_ids: List[str],
    ) -> Dict[str, Any]:
        """
        Augments Apollo People Search request body with lookalike_organization_ids.
        Maintains target titles, locations, employee ranges, seniorities, etc.
        """
        body = dict(base_body)
        body["lookalike_organization_ids"] = list(lookalike_org_ids)[:MAX_SEED_COMPANIES]
        return body

    @classmethod
    def offline_lookalike_discovery(
        cls,
        seed_companies: List[str],
        icp_config: Dict[str, Any],
        csv_candidates: List[Dict[str, Any]],
        limit: int = 15,
    ) -> List[Dict[str, Any]]:
        """
        Offline fallback prospect look-alike matching.
        Identifies prospects in prospects_export.csv whose companies resemble the seed companies
        based on firmographic attributes (industry, employee scale, tech stack) while strictly
        excluding the seed companies themselves.
        """
        if not seed_companies or not csv_candidates:
            return []

        clean_seeds = {clean_company_name(s) for s in seed_companies if s}
        raw_seeds_lower = {s.strip().lower() for s in seed_companies if s}

        # Determine target industry and size preferences from ICP
        target_industries = [
            i.lower().strip() for i in (icp_config.get("industry_terms") or []) if i
        ]
        target_titles = [
            t.lower().strip() for t in (icp_config.get("titles") or []) if t
        ]

        matched: List[Dict[str, Any]] = []

        for candidate in csv_candidates:
            comp_name = (candidate.get("company") or "").strip()
            comp_clean = clean_company_name(comp_name)
            comp_lower = comp_name.lower()
            comp_domain = (candidate.get("company_domain") or "").strip().lower()

            # Rule 7: Strictly exclude the reference seed companies themselves
            if comp_lower in raw_seeds_lower or comp_clean in clean_seeds:
                continue
            if any(s in comp_domain for s in raw_seeds_lower if len(s) > 3):
                continue

            # Title matching check
            c_title = (candidate.get("title") or "").lower()
            if target_titles and not any(tt in c_title or c_title in tt for tt in target_titles):
                continue

            # Firmographic similarity score
            sim_score = 0
            reasons = []

            c_ind = (candidate.get("industry") or "").lower()
            if target_industries and any(ti in c_ind or c_ind in ti for ti in target_industries):
                sim_score += 40
                reasons.append(f"Industry alignment ({candidate.get('industry')})")
            elif c_ind:
                sim_score += 20

            c_size = candidate.get("employee_count")
            if c_size and c_size >= 50:
                sim_score += 25
                reasons.append(f"Enterprise scale ({c_size} employees)")

            if candidate.get("tech_stack"):
                sim_score += 20
                reasons.append("Modern technology adoption")

            if sim_score >= 40:
                item = dict(candidate)
                item["source"] = "offline_lookalike"
                item["discovery_method"] = "lookalike"
                item["lookalike_seed_companies"] = list(seed_companies)
                item["similarity_rationale"] = "; ".join(reasons) if reasons else "Firmographic similarity"
                matched.append(item)

        return matched[:limit]

    @classmethod
    def combine_and_deduplicate_prospects(
        cls,
        icp_prospects: List[Dict[str, Any]],
        lookalike_prospects: List[Dict[str, Any]],
        seed_company_names: List[str],
        seed_org_ids: Optional[List[str]] = None,
        seed_domains: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Merge and deduplicate prospect results from standard ICP search and Look-alike search:
        - Strictly excludes prospects at seed reference companies.
        - Deduplicates using Apollo ID (primary) or Email (secondary).
        - If a prospect appears in both paths, merges metadata, records both discovery sources,
          and preserves the highest win_pattern_score.
        """
        clean_seeds = {clean_company_name(s) for s in (seed_company_names or []) if s}
        raw_seeds_lower = {s.strip().lower() for s in (seed_company_names or []) if s}
        org_ids_set = set(seed_org_ids or [])
        domains_set = {d.strip().lower() for d in (seed_domains or []) if d}

        def is_seed_company(c: Dict[str, Any]) -> bool:
            """Check if contact belongs to a seed company."""
            org_id = c.get("_org_id") or c.get("organization_id")
            if org_id and org_id in org_ids_set:
                return True
            comp = (c.get("company") or "").strip().lower()
            if comp in raw_seeds_lower or clean_company_name(comp) in clean_seeds:
                return True
            dom = (c.get("company_domain") or "").strip().lower()
            clean_dom = re.sub(r"^https?://(www\.)?", "", dom).split("/")[0]
            if clean_dom in domains_set or any(s in clean_dom for s in raw_seeds_lower if len(s) > 3):
                return True
            return False

        merged_by_key: Dict[str, Dict[str, Any]] = {}

        # 1. Process standard ICP prospects
        for c in icp_prospects:
            key = (c.get("apollo_id") or c.get("email") or "").strip().lower()
            if not key:
                continue
            item = dict(c)
            item["discovery_sources"] = ["icp_search"]
            item["source"] = item.get("source") or "apollo"
            merged_by_key[key] = item

        # 2. Process lookalike prospects
        for c in lookalike_prospects:
            key = (c.get("apollo_id") or c.get("email") or "").strip().lower()
            if not key:
                continue
            # Rule 7: Exclude seed companies from lookalike discoveries
            if is_seed_company(c):
                logger.info(
                    "A1 Lookalike: Excluded candidate working at seed company",
                    company=c.get("company"),
                    email=c.get("email"),
                    apollo_id=c.get("apollo_id"),
                )
                continue

            key = (c.get("apollo_id") or c.get("email") or "").strip().lower()

            if key in merged_by_key:
                # Candidate found in both paths: merge metadata
                existing = merged_by_key[key]
                if "lookalike" not in existing.get("discovery_sources", []):
                    existing["discovery_sources"].append("lookalike")
                existing["source"] = "apollo (icp + lookalike)"
                existing["lookalike_seed_companies"] = list(seed_company_names)
                if c.get("similarity_rationale"):
                    existing["similarity_rationale"] = c.get("similarity_rationale")

                # Keep higher win_pattern_score if present
                if c.get("win_pattern_score", 0) > existing.get("win_pattern_score", 0):
                    existing["win_pattern_score"] = c.get("win_pattern_score")
                    existing["icp_score_breakdown"] = c.get("icp_score_breakdown")

                # Merge firmographics if existing was blank
                for field in ("industry", "funding_stage", "company_size", "employee_count"):
                    if not existing.get(field) and c.get(field):
                        existing[field] = c.get(field)
                if not existing.get("tech_stack") and c.get("tech_stack"):
                    existing["tech_stack"] = c.get("tech_stack")
            else:
                item = dict(c)
                item["discovery_sources"] = ["lookalike"]
                item["source"] = item.get("source") or "apollo (lookalike)"
                item["lookalike_seed_companies"] = list(seed_company_names)
                merged_by_key[key] = item

        return list(merged_by_key.values())
