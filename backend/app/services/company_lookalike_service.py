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
