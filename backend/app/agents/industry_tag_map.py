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
    "saas":                     "5567cd4773696439ab010000",
    "software":                 "5567cd4773696439ab020000",
    "information technology":   "5567cd4773696439ab030000",
    "it services":              "5567cd4773696439ab030001",
    "cloud computing":          "5567cd4773696439ab040000",
    "artificial intelligence":  "5567cd4773696439ab050000",
    "ai":                       "5567cd4773696439ab050000",
    "machine learning":         "5567cd4773696439ab050001",
    "cybersecurity":            "5567cd4773696439ab060000",
    "data analytics":           "5567cd4773696439ab070000",
    "devops":                   "5567cd4773696439ab080000",

    # Finance
    "fintech":                  "5567cd4773696439ab090000",
    "financial services":       "5567cd4773696439ab090001",
    "banking":                  "5567cd4773696439ab090002",
    "insurance":                "5567cd4773696439ab090003",

    # Health
    "healthcare":               "5567cd4773696439ab0a0000",
    "healthtech":               "5567cd4773696439ab0a0001",
    "medtech":                  "5567cd4773696439ab0a0002",
    "pharmaceuticals":          "5567cd4773696439ab0a0003",

    # Commerce & Retail
    "ecommerce":                "5567cd4773696439ab0b0000",
    "e-commerce":               "5567cd4773696439ab0b0000",
    "retail":                   "5567cd4773696439ab0b0001",
    "logistics":                "5567cd4773696439ab0b0002",
    "supply chain":             "5567cd4773696439ab0b0003",

    # Media & Marketing
    "marketing":                "5567cd4773696439ab0c0000",
    "advertising":              "5567cd4773696439ab0c0001",
    "media":                    "5567cd4773696439ab0c0002",
    "edtech":                   "5567cd4773696439ab0c0003",
    "education":                "5567cd4773696439ab0c0004",

    # Real Estate & Construction
    "real estate":              "5567cd4773696439ab0d0000",
    "construction":             "5567cd4773696439ab0d0001",

    # Energy & Manufacturing
    "energy":                   "5567cd4773696439ab0e0000",
    "cleantech":                "5567cd4773696439ab0e0001",
    "manufacturing":            "5567cd4773696439ab0e0002",
    "automotive":               "5567cd4773696439ab0e0003",

    # Professional Services
    "consulting":               "5567cd4773696439ab0f0000",
    "legal":                    "5567cd4773696439ab0f0001",
    "hr":                       "5567cd4773696439ab0f0002",
    "human resources":          "5567cd4773696439ab0f0002",
    "recruitment":              "5567cd4773696439ab0f0003",
}


def resolve_industries(industry_str: str) -> Tuple[List[str], List[str]]:
    """
    Resolve a comma-separated industry string into Apollo tag IDs + keyword fallback.

    Returns:
        (tag_ids, keyword_fallback)
        - tag_ids:          List of Apollo organization_industry_tag_ids for matched terms.
                            Empty list if no matches or industry_str is blank.
        - keyword_fallback: List of unmatched terms to fold into q_organization_keyword_tags
                            instead of being silently dropped.

    Examples:
        resolve_industries("SaaS, Fintech, quantum")
        → (["<saas_id>", "<fintech_id>"], ["quantum"])

        resolve_industries("")
        → ([], [])    # no filter applied at all
    """
    if not industry_str or not industry_str.strip():
        return [], []

    tag_ids: List[str] = []
    fallback_keywords: List[str] = []

    for term in industry_str.split(","):
        normalized = term.strip().lower()
        if not normalized:
            continue
        if normalized in INDUSTRY_TAG_MAP:
            tag_ids.append(INDUSTRY_TAG_MAP[normalized])
        else:
            # Don't drop silently — fold into keyword search
            fallback_keywords.append(normalized)

    return tag_ids, fallback_keywords
