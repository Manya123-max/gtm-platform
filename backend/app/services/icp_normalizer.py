"""
icp_normalizer.py — Centralized ICP Input Normalization Layer.

Transforms heterogeneous frontend/API user inputs into a validated, deterministic
NormalizedICPConfig suitable for Apollo query building and GTM pipeline processing.

Rules enforced:
1. Normalize target job titles and infer appropriate Apollo person_seniorities.
2. Normalize target company geography into organization_locations (company HQ).
3. Normalize company-size ranges into Apollo's discrete organization_num_employees_ranges.
4. Resolve target industries using app.agents.industry_tag_map.resolve_industries.
5. Route unmatched industry terms to q_organization_keyword_tags.
6. Normalize target keywords into a clean list of string tags.
7. Keep our_services strictly isolated for downstream outreach messaging (never in search keywords).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import re

from app.core.config import settings
from app.agents.industry_tag_map import resolve_industries, resolve_industries_and_terms


# Standard discrete employee-count buckets supported by Apollo's search engine
APOLLO_EMPLOYEE_BUCKETS: List[Tuple[str, int, int]] = [
    ("1,10", 1, 10),
    ("11,50", 11, 50),
    ("51,200", 51, 200),
    ("201,500", 201, 500),
    ("501,1000", 501, 1000),
    ("1001,5000", 1001, 5000),
    ("5001,10000", 5001, 10000),
    ("10001,", 10001, 10000000),
]

# Standard Apollo seniority level slugs
VALID_APOLLO_SENIORITIES = {
    "owner",
    "founder",
    "c_suite",
    "partner",
    "vp",
    "head",
    "director",
    "manager",
    "senior",
    "entry",
    "intern",
}

# Common title expansions and synonyms
TITLE_EXPANSIONS: Dict[str, List[str]] = {
    "cro": ["Chief Revenue Officer", "CRO"],
    "chief revenue officer": ["Chief Revenue Officer", "CRO"],
    "cto": ["Chief Technology Officer", "CTO"],
    "chief technology officer": ["Chief Technology Officer", "CTO"],
    "cio": ["Chief Information Officer", "CIO"],
    "chief information officer": ["Chief Information Officer", "CIO"],
    "cfo": ["Chief Financial Officer", "CFO"],
    "chief financial officer": ["Chief Financial Officer", "CFO"],
    "cmo": ["Chief Marketing Officer", "CMO"],
    "chief marketing officer": ["Chief Marketing Officer", "CMO"],
    "cpo": ["Chief Product Officer", "CPO"],
    "chief product officer": ["Chief Product Officer", "CPO"],
    "ceo": ["Chief Executive Officer", "CEO"],
    "chief executive officer": ["Chief Executive Officer", "CEO"],
    "ciso": ["Chief Information Security Officer", "CISO"],
    "chief information security officer": ["Chief Information Security Officer", "CISO"],
    "vp sales": ["VP Sales", "VP of Sales", "Vice President Sales", "Vice President of Sales"],
    "vp of sales": ["VP Sales", "VP of Sales", "Vice President Sales", "Vice President of Sales"],
    "vice president sales": ["VP Sales", "VP of Sales", "Vice President Sales", "Vice President of Sales"],
    "vice president of sales": ["VP Sales", "VP of Sales", "Vice President Sales", "Vice President of Sales"],
    "vp engineering": ["VP Engineering", "VP of Engineering", "Vice President Engineering", "Vice President of Engineering"],
    "vp of engineering": ["VP Engineering", "VP of Engineering", "Vice President Engineering", "Vice President of Engineering"],
    "vice president engineering": ["VP Engineering", "VP of Engineering", "Vice President Engineering", "Vice President of Engineering"],
    "vice president of engineering": ["VP Engineering", "VP of Engineering", "Vice President Engineering", "Vice President of Engineering"],
    "vp marketing": ["VP Marketing", "VP of Marketing", "Vice President Marketing", "Vice President of Marketing"],
    "vp of marketing": ["VP Marketing", "VP of Marketing", "Vice President Marketing", "Vice President of Marketing"],
    "vp product": ["VP Product", "VP of Product", "Vice President Product", "Vice President of Product"],
    "vp of product": ["VP Product", "VP of Product", "Vice President Product", "Vice President of Product"],
    "head of sales": ["Head of Sales", "Head, Sales"],
    "head of engineering": ["Head of Engineering", "Head, Engineering"],
    "head of marketing": ["Head of Marketing", "Head, Marketing"],
    "head of product": ["Head of Product", "Head, Product"],
    "director of sales": ["Director of Sales", "Director, Sales"],
    "director of engineering": ["Director of Engineering", "Director, Engineering"],
    "director of marketing": ["Director of Marketing", "Director, Marketing"],
    "director of product": ["Director of Product", "Director, Product"],
}

# Country aliases to standard Apollo location names
COUNTRY_ALIASES: Dict[str, str] = {
    "us": "United States",
    "usa": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "uae": "United Arab Emirates",
    "u.a.e.": "United Arab Emirates",
    "in": "India",
    "ca": "Canada",
    "au": "Australia",
    "de": "Germany",
    "fr": "France",
    "sg": "Singapore",
}


@dataclass
class NormalizedICPConfig:
    """Normalized search and qualification configuration for Agent 1."""
    titles: List[str] = field(default_factory=list)
    seniorities: List[str] = field(default_factory=list)
    organization_locations: List[str] = field(default_factory=list)
    person_locations: List[str] = field(default_factory=list)
    employee_ranges: List[str] = field(default_factory=list)
    industry_tag_ids: List[str] = field(default_factory=list)
    industry_terms: List[str] = field(default_factory=list)
    technology_keywords: List[str] = field(default_factory=list)
    org_keyword_tags: List[str] = field(default_factory=list)
    technology_keywords_required: bool = False
    include_similar_titles: bool = False
    threshold: float = 70.0
    requested_count: int = 25
    enrich_limit: int = 25
    candidate_pool_size: int = 150
    vendor_services: str = ""
    our_company_name: str = ""
    user_id: Optional[str] = None
    user_input_id: Optional[int] = None

    @property
    def target_industry_tag_ids(self) -> List[str]:
        return self.industry_tag_ids

    @property
    def target_industry_terms(self) -> List[str]:
        return self.industry_terms

    @property
    def target_technology_keywords(self) -> List[str]:
        return self.technology_keywords

    @property
    def target_location(self) -> List[str]:
        return self.organization_locations

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation for workflow payloads."""
        return {
            "titles": self.titles,
            "seniorities": self.seniorities,
            "organization_locations": self.organization_locations,
            "person_locations": self.person_locations,
            "employee_ranges": self.employee_ranges,
            "industry_tag_ids": self.industry_tag_ids,
            "industry_terms": self.industry_terms,
            "technology_keywords": self.technology_keywords,
            "target_industry_tag_ids": self.industry_tag_ids,
            "target_industry_terms": self.industry_terms,
            "target_technology_keywords": self.technology_keywords,
            "target_location": self.organization_locations,
            "org_keyword_tags": self.org_keyword_tags,
            "technology_keywords_required": self.technology_keywords_required,
            "include_similar_titles": self.include_similar_titles,
            "threshold": self.threshold,
            "requested_count": self.requested_count,
            "enrich_limit": self.enrich_limit,
            "candidate_pool_size": self.candidate_pool_size,
            "vendor_services": self.vendor_services,
            "our_company_name": self.our_company_name,
            "user_id": self.user_id,
            "user_input_id": self.user_input_id,
        }



def _split_terms(val: Any) -> List[str]:
    """Helper to split strings by comma or newline, or flatten lists of strings."""
    if not val:
        return []
    if isinstance(val, list):
        out: List[str] = []
        for item in val:
            out.extend(_split_terms(item))
        return out
    if isinstance(val, str):
        tokens = re.split(r"[\r\n,]+", val)
        return [t.strip() for t in tokens if t.strip()]
    return [str(val).strip()]


def _infer_seniorities_from_title(title: str) -> List[str]:
    """Infer Apollo seniority levels from a job title string."""
    t = title.lower().strip()
    inferred: List[str] = []

    if any(k in t for k in ["chief", "cto", "cio", "cpo", "ceo", "cro", "cfo", "cmo", "ciso", "c-level", "c-suite"]):
        inferred.append("c_suite")
    if any(k in t for k in ["vp", "vice president", "v.p."]):
        inferred.append("vp")
    if any(k in t for k in ["head of", "head,", "head -", "head "]):
        inferred.append("head")
    if "director" in t:
        inferred.append("director")
    if any(k in t for k in ["founder", "co-founder"]):
        inferred.append("founder")
    if "owner" in t:
        inferred.append("owner")
    if "partner" in t:
        inferred.append("partner")
    if "manager" in t:
        inferred.append("manager")
    if any(k in t for k in ["senior", "sr.", "sr ", "lead", "principal"]):
        inferred.append("senior")
    if any(k in t for k in ["associate", "junior", "jr.", "entry"]):
        inferred.append("entry")
    if "intern" in t:
        inferred.append("intern")

    return inferred


def _normalize_titles_and_seniorities(
    raw_titles: Any,
    raw_seniorities: Any = None,
) -> Tuple[List[str], List[str]]:
    """
    Normalize target titles and infer appropriate Apollo seniorities.
    Expands common title acronyms while preserving distinct user intent.
    """
    split_titles = _split_terms(raw_titles)
    normalized_titles: List[str] = []
    inferred_seniorities: set[str] = set()

    for item in split_titles:
        cleaned = item.strip()
        if not cleaned:
            continue
        lower = cleaned.lower()

        # Check title expansions
        if lower in TITLE_EXPANSIONS:
            for exp in TITLE_EXPANSIONS[lower]:
                if exp not in normalized_titles:
                    normalized_titles.append(exp)
        else:
            if cleaned not in normalized_titles:
                normalized_titles.append(cleaned)

        # Infer seniority
        for sen in _infer_seniorities_from_title(cleaned):
            inferred_seniorities.add(sen)

    # Process explicit raw_seniorities if provided
    if raw_seniorities:
        for sen in _split_terms(raw_seniorities):
            norm_sen = sen.strip().lower().replace("-", "_").replace(" ", "_")
            if norm_sen in VALID_APOLLO_SENIORITIES:
                inferred_seniorities.add(norm_sen)

    seniority_order = [
        "c_suite", "founder", "owner", "partner", "vp", "head", "director", "manager", "senior", "entry", "intern"
    ]
    sorted_seniorities = [s for s in seniority_order if s in inferred_seniorities]
    for s in inferred_seniorities:
        if s not in sorted_seniorities and s in VALID_APOLLO_SENIORITIES:
            sorted_seniorities.append(s)

    return normalized_titles, sorted_seniorities


def _normalize_locations(raw_loc: Any) -> List[str]:
    """Normalize location strings to standard Apollo country/region names."""
    split_locs = _split_terms(raw_loc)
    normalized: List[str] = []

    for loc in split_locs:
        cleaned = loc.strip()
        if not cleaned:
            continue
        lower = cleaned.lower()
        canonical = COUNTRY_ALIASES.get(lower, cleaned)
        if canonical not in normalized:
            normalized.append(canonical)

    return normalized


def _normalize_employee_ranges(raw_size: Any) -> List[str]:
    """
    Convert a user-entered size range (e.g. '50-500', '51-200', '50-5000', or integer)
    into all overlapping Apollo employee-count bucket strings.
    """
    if not raw_size:
        return ["51,200", "201,500"]

    if isinstance(raw_size, list):
        valid_buckets = {b[0] for b in APOLLO_EMPLOYEE_BUCKETS}
        matched = [str(r).strip() for r in raw_size if str(r).strip() in valid_buckets]
        if matched:
            return matched
        raw_size = ",".join(str(r) for r in raw_size)

    size_str = str(raw_size).strip()
    if not size_str:
        return ["51,200", "201,500"]

    valid_bucket_map = {b[0]: b[0] for b in APOLLO_EMPLOYEE_BUCKETS}
    if size_str in valid_bucket_map:
        return [size_str]

    try:
        parts = re.findall(r"\d+", size_str)
        if len(parts) == 1:
            low = int(parts[0])
            high = low
        elif len(parts) >= 2:
            low = int(parts[0])
            high = int(parts[1])
            if low > high:
                low, high = high, low
        else:
            return ["51,200", "201,500"]

        overlapping = [
            label for label, lo, hi in APOLLO_EMPLOYEE_BUCKETS
            if lo <= high and hi >= low
        ]
        return overlapping if overlapping else ["51,200", "201,500"]
    except Exception:
        return ["51,200", "201,500"]


def _normalize_industries_and_keywords(
    raw_industries: Any,
    raw_keywords: Any,
    raw_tech_keywords: Any = None,
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Resolve target industries against industry_tag_map.py and normalize technology keywords.
    - Verified Apollo industry terms produce organization_industry_tag_ids and industry_terms.
    - Non-industry terms (e.g. Deep Tech, Deep Health, Teleradiology) and explicit keyword
      inputs become technology_keywords and org_keyword_tags.
    
    Returns:
        (industry_tag_ids, industry_terms, technology_keywords, org_keyword_tags)
    """
    industry_str = ""
    if isinstance(raw_industries, list):
        industry_str = ", ".join(str(i) for i in raw_industries if i)
    elif isinstance(raw_industries, str):
        industry_str = raw_industries

    tag_ids, matched_industry_terms, industry_kw_fallback = resolve_industries_and_terms(industry_str)

    kw_list = _split_terms(raw_keywords)
    tech_list = _split_terms(raw_tech_keywords)

    technology_keywords: List[str] = []
    org_keyword_tags: List[str] = []

    # Add explicit technology keywords
    for tk in tech_list:
        clean_tk = tk.strip().lower()
        if clean_tk and clean_tk not in technology_keywords:
            technology_keywords.append(clean_tk)
        if clean_tk and clean_tk not in org_keyword_tags:
            org_keyword_tags.append(clean_tk)

    # Add general keyword tags
    for kw in kw_list:
        clean_kw = kw.strip().lower()
        if clean_kw and clean_kw not in technology_keywords:
            technology_keywords.append(clean_kw)
        if clean_kw and clean_kw not in org_keyword_tags:
            org_keyword_tags.append(clean_kw)

    # Add non-industry fallback terms (e.g. 'deep tech', 'deep health', 'teleradiology')
    for fallback in industry_kw_fallback:
        clean_fb = fallback.strip().lower()
        if clean_fb and clean_fb not in technology_keywords:
            technology_keywords.append(clean_fb)
        if clean_fb and clean_fb not in org_keyword_tags:
            org_keyword_tags.append(clean_fb)

    return tag_ids, matched_industry_terms, technology_keywords, org_keyword_tags


def normalize_icp_input(raw_input: Dict[str, Any]) -> NormalizedICPConfig:
    """
    Main entry point for normalizing any ICP configuration dictionary or form payload.
    """
    raw_titles = (
        raw_input.get("target_job_titles")
        or raw_input.get("titles")
        or raw_input.get("job_titles")
        or raw_input.get("target_titles")
        or raw_input.get("job_title")
        or []
    )
    raw_seniorities = raw_input.get("person_seniorities") or raw_input.get("seniorities")
    titles, seniorities = _normalize_titles_and_seniorities(raw_titles, raw_seniorities)

    raw_org_loc = (
        raw_input.get("organization_locations")
        or raw_input.get("target_location")
        or raw_input.get("geographies")
        or raw_input.get("location")
        or []
    )
    raw_person_loc = raw_input.get("person_locations") or []

    org_locations = _normalize_locations(raw_org_loc)
    person_locations = _normalize_locations(raw_person_loc)

    raw_size = (
        raw_input.get("organization_num_employees_ranges")
        or raw_input.get("target_company_size")
        or raw_input.get("employee_ranges")
        or raw_input.get("company_size")
        or "51-500"
    )
    employee_ranges = _normalize_employee_ranges(raw_size)

    raw_industries = raw_input.get("target_industries") or raw_input.get("industry") or raw_input.get("industries") or ""
    raw_keywords = raw_input.get("target_keywords") or raw_input.get("keywords") or raw_input.get("org_keyword_tags") or ""
    raw_tech_keywords = raw_input.get("target_technology_keywords") or raw_input.get("technology_keywords") or ""

    (
        industry_tag_ids,
        industry_terms,
        technology_keywords,
        org_keyword_tags,
    ) = _normalize_industries_and_keywords(raw_industries, raw_keywords, raw_tech_keywords)

    tech_req = bool(
        raw_input.get("technology_keywords_required")
        or raw_input.get("require_technology_keywords")
        or raw_input.get("strict_keywords")
        or False
    )

    threshold = float(
        raw_input.get("threshold")
        if raw_input.get("threshold") is not None
        else getattr(settings, "ICP_SCORE_THRESHOLD", 70)
    )
    requested_count = int(
        raw_input.get("requested_count")
        or raw_input.get("limit")
        or raw_input.get("enrich_limit")
        or getattr(settings, "APOLLO_ENRICH_LIMIT", 25)
    )
    enrich_limit = int(
        raw_input.get("enrich_limit")
        or getattr(settings, "APOLLO_ENRICH_LIMIT", 25)
    )
    candidate_pool_size = int(
        raw_input.get("candidate_pool_size")
        or getattr(settings, "APOLLO_CANDIDATE_POOL_SIZE", 150)
    )
    include_similar_titles = bool(
        raw_input.get("include_similar_titles", getattr(settings, "APOLLO_INCLUDE_SIMILAR_TITLES", False))
    )

    vendor_services = str(raw_input.get("our_services") or raw_input.get("vendor_services") or "").strip()
    our_company_name = str(raw_input.get("our_company_name") or raw_input.get("company_name") or "").strip()
    user_id = raw_input.get("user_id")
    user_input_id = raw_input.get("user_input_id")

    return NormalizedICPConfig(
        titles=titles,
        seniorities=seniorities,
        organization_locations=org_locations,
        person_locations=person_locations,
        employee_ranges=employee_ranges,
        industry_tag_ids=industry_tag_ids,
        industry_terms=industry_terms,
        technology_keywords=technology_keywords,
        org_keyword_tags=org_keyword_tags,
        technology_keywords_required=tech_req,
        include_similar_titles=include_similar_titles,
        threshold=threshold,
        requested_count=requested_count,
        enrich_limit=enrich_limit,
        candidate_pool_size=candidate_pool_size,
        vendor_services=vendor_services,
        our_company_name=our_company_name,
        user_id=user_id,
        user_input_id=user_input_id,
    )

