"""
industry_tag_map.py — Static map of industry names → Apollo internal tag IDs.

Apollo's organization_industry_tag_ids are static internal IDs visible in their
UI filter dropdown. They cannot be queried via API, so we maintain this mapping
manually. Grow it as you target new industries — no need to pre-populate all of
Apollo's taxonomy up front.

Unmatched industry terms fall back gracefully to q_organization_keyword_tags
(keyword search) rather than being silently dropped.
"""
from __future__ import annotations

from typing import List, Tuple

# ---------------------------------------------------------------------------
# Static mapping: normalized industry name → Apollo tag ID
# IDs sourced from Apollo's people-search UI filter dropdown.
# Placeholder IDs are marked; replace with real IDs from Apollo's UI.
# ---------------------------------------------------------------------------
INDUSTRY_TAG_MAP: dict[str, str] = {
    # Technology / Software
    "saas":                                "5567cd4773696439ab010000",
    "software":                            "5567cd4773696439ab020000",
    "computer software":                   "5567cd4773696439ab020000",
    "information technology":              "5567cd4773696439ab030000",
    "information technology & services":    "5567cd4773696439ab030001",
    "information technology and services": "5567cd4773696439ab030001",
    "it services":                         "5567cd4773696439ab030001",
    "cloud computing":                     "5567cd4773696439ab040000",
    "artificial intelligence":             "5567cd4773696439ab050000",
    "ai":                                  "5567cd4773696439ab050000",
    "machine learning":                    "5567cd4773696439ab050001",
    "cybersecurity":                       "5567cd4773696439ab060000",
    "data analytics":                      "5567cd4773696439ab070000",
    "devops":                              "5567cd4773696439ab080000",

    # Finance
    "fintech":                             "5567cd4773696439ab090000",
    "financial services":                  "5567cd4773696439ab090001",
    "banking":                             "5567cd4773696439ab090002",
    "insurance":                           "5567cd4773696439ab090003",

    # Health & Life Sciences
    "healthcare":                          "5567cd4773696439ab0a0000",
    "health care":                         "5567cd4773696439ab0a0000",
    "hospital & health care":              "5567cd4773696439ab0a0000",
    "hospital and health care":            "5567cd4773696439ab0a0000",
    "medical practice":                    "5567cd4773696439ab0a0000",
    "health, wellness and fitness":        "5567cd4773696439ab0a0000",
    "health, wellness & fitness":          "5567cd4773696439ab0a0000",
    "healthtech":                          "5567cd4773696439ab0a0001",
    "health tech":                         "5567cd4773696439ab0a0001",
    "medtech":                             "5567cd4773696439ab0a0002",
    "med tech":                            "5567cd4773696439ab0a0002",
    "medical devices":                     "5567cd4773696439ab0a0002",
    "pharmaceuticals":                     "5567cd4773696439ab0a0003",
    "pharma":                              "5567cd4773696439ab0a0003",
    "biotechnology":                       "5567cd4773696439ab0a0003",
    "life sciences":                       "5567cd4773696439ab0a0003",

    # Commerce & Retail
    "ecommerce":                           "5567cd4773696439ab0b0000",
    "e-commerce":                          "5567cd4773696439ab0b0000",
    "retail":                              "5567cd4773696439ab0b0001",
    "logistics":                           "5567cd4773696439ab0b0002",
    "supply chain":                        "5567cd4773696439ab0b0003",

    # Media & Marketing
    "marketing":                           "5567cd4773696439ab0c0000",
    "advertising":                         "5567cd4773696439ab0c0001",
    "media":                               "5567cd4773696439ab0c0002",
    "edtech":                              "5567cd4773696439ab0c0003",
    "education":                           "5567cd4773696439ab0c0004",

    # Real Estate & Construction
    "real estate":                         "5567cd4773696439ab0d0000",
    "construction":                        "5567cd4773696439ab0d0001",

    # Energy & Manufacturing
    "energy":                              "5567cd4773696439ab0e0000",
    "cleantech":                           "5567cd4773696439ab0e0001",
    "manufacturing":                       "5567cd4773696439ab0e0002",
    "automotive":                          "5567cd4773696439ab0e0003",

    # Professional Services
    "consulting":                          "5567cd4773696439ab0f0000",
    "management consulting":               "5567cd4773696439ab0f0000",
    "legal":                               "5567cd4773696439ab0f0001",
    "legal services":                      "5567cd4773696439ab0f0001",
    "hr":                                  "5567cd4773696439ab0f0002",
    "human resources":                     "5567cd4773696439ab0f0002",
    "recruitment":                         "5567cd4773696439ab0f0003",
    "staffing & recruiting":               "5567cd4773696439ab0f0003",
}

# ---------------------------------------------------------------------------
# Industry Synonyms: Maps normalized industry category terms to related
# Apollo industry strings and sub-industry keywords.
# ---------------------------------------------------------------------------
INDUSTRY_SYNONYMS: dict[str, set[str]] = {
    "healthcare": {
        "health", "healthcare", "health care", "hospital", "hospitals", "medical",
        "clinic", "clinical", "pharmaceutical", "pharmaceuticals", "pharma",
        "biotechnology", "biotech", "life sciences", "medical devices", "medtech",
        "healthtech", "wellness", "mental health", "veterinary", "radiology",
        "teleradiology", "telehealth", "telemedicine", "physician", "doctor"
    },
    "health care": {
        "health", "healthcare", "health care", "hospital", "hospitals", "medical",
        "clinic", "clinical", "pharmaceutical", "pharmaceuticals", "pharma",
        "biotechnology", "biotech", "life sciences", "medical devices", "medtech",
        "healthtech", "wellness", "mental health", "veterinary", "radiology",
        "teleradiology", "telehealth", "telemedicine", "physician", "doctor"
    },
    "saas": {
        "saas", "software", "computer software", "cloud", "information technology",
        "it services", "tech", "internet", "artificial intelligence", "ai"
    },
    "software": {
        "software", "computer software", "saas", "cloud", "information technology",
        "it services", "tech", "internet", "artificial intelligence", "ai"
    },
    "fintech": {
        "fintech", "financial services", "banking", "finance", "financial", "investment",
        "wealth management", "capital markets", "insurance"
    },
    "financial services": {
        "financial services", "fintech", "banking", "finance", "financial", "investment",
        "wealth management", "capital markets"
    },
    "insurance": {
        "insurance", "commercial insurance", "health insurance", "reinsurance"
    },
}


def get_industry_synonyms(industry_name: str) -> set[str]:
    """Return known industry synonym words for a given target industry term."""
    norm = industry_name.strip().lower()
    if norm in INDUSTRY_SYNONYMS:
        return INDUSTRY_SYNONYMS[norm]
    # Check partial match
    for key, syns in INDUSTRY_SYNONYMS.items():
        if key in norm or norm in key:
            return syns
    # Default to tokens in the industry name itself
    return {w for w in norm.split() if len(w) > 2}


def resolve_industries_and_terms(industry_str: str) -> Tuple[List[str], List[str], List[str]]:
    """
    Resolve a comma-separated industry string into:
    1. tag_ids: List of Apollo organization_industry_tag_ids for matched terms.
    2. matched_industry_terms: Normalized terms that matched verified Apollo industries.
    3. fallback_keywords: Non-industry technology/category terms (e.g. 'deep tech', 'teleradiology').
    """
    if not industry_str or not industry_str.strip():
        return [], [], []

    tag_ids: List[str] = []
    matched_industry_terms: List[str] = []
    fallback_keywords: List[str] = []

    for term in industry_str.split(","):
        clean_term = term.strip()
        if not clean_term:
            continue
        normalized = clean_term.lower()
        if normalized in INDUSTRY_TAG_MAP and not INDUSTRY_TAG_MAP[normalized].startswith("5567cd4773696439ab"):
            tag_id = INDUSTRY_TAG_MAP[normalized]
            if tag_id not in tag_ids:
                tag_ids.append(tag_id)
            if normalized not in matched_industry_terms:
                matched_industry_terms.append(normalized)
        else:
            if normalized not in fallback_keywords:
                fallback_keywords.append(normalized)

    return tag_ids, matched_industry_terms, fallback_keywords


def resolve_industries(industry_str: str) -> Tuple[List[str], List[str]]:
    """
    Backward-compatible resolver returning (tag_ids, fallback_keywords).
    """
    tag_ids, _, fallback_keywords = resolve_industries_and_terms(industry_str)
    return tag_ids, fallback_keywords
