"""
apollo_query_builder.py — Dedicated Apollo API Search Query Builder.

Converts a NormalizedICPConfig into exact Apollo mixed_people/api_search payloads.
Ensures documented parameter names, correct types, no empty/null filters, and sanitized telemetry.
"""
from __future__ import annotations

from typing import Any, Dict, List, Union
from app.services.icp_normalizer import NormalizedICPConfig, normalize_icp_input


# Mapping from human-friendly funding stage labels to standard Apollo codes
APOLLO_FUNDING_STAGE_MAP: Dict[str, str] = {
    "seed": "seed",
    "angel": "angel",
    "venture (round not specified)": "venture",
    "venture": "venture",
    "series a": "series_a",
    "series b": "series_b",
    "series c": "series_c",
    "series d": "series_d",
    "series e": "series_e",
    "series f": "series_f",
    "debt financing": "debt_financing",
    "equity crowdfunding": "equity_crowdfunding",
    "convertible note": "convertible_note",
    "private equity": "private_equity",
    "merger / acquisition": "merger_or_acquisition",
    "merger/acquisition": "merger_or_acquisition",
    "merger": "merger_or_acquisition",
    "acquisition": "merger_or_acquisition",
    "other": "other",
}


class ApolloQueryBuilder:
    """Builder for constructing validated Apollo search request bodies."""

    @staticmethod
    def map_funding_stages(stages: List[str]) -> List[str]:
        """Convert friendly funding stage labels to normalized Apollo codes."""
        mapped = []
        for s in stages:
            clean = str(s).strip().lower()
            code = APOLLO_FUNDING_STAGE_MAP.get(clean, clean.replace(" ", "_"))
            if code and code not in mapped:
                mapped.append(code)
        return mapped

    @staticmethod
    def build_search_payload(
        config: Union[NormalizedICPConfig, Dict[str, Any]],
        page: int = 1,
        per_page: int = 100,
    ) -> Dict[str, Any]:
        """
        Build the Apollo mixed_people/api_search request payload.

        Documented Apollo parameter mapping:
          - person_titles: List[str]
          - person_seniorities: List[str]
          - organization_locations: List[str]
          - person_locations: List[str]
          - organization_num_employees_ranges: List[str]
          - organization_industry_tag_ids: List[str]
          - q_organization_keyword_tags: List[str] (supports signals + keywords with OR semantics)
          - organization_latest_funding_stage_cd: List[str] (funding stages with OR semantics)
          - lookalike_organization_ids: List[str]
          - include_similar_titles: bool (default: False)
          - page: int
          - per_page: int
        """
        norm_cfg: NormalizedICPConfig
        if isinstance(config, NormalizedICPConfig):
            norm_cfg = config
        elif isinstance(config, dict):
            norm_cfg = normalize_icp_input(config)
        else:
            raise TypeError(f"Expected NormalizedICPConfig or dict, got {type(config)}")

        payload: Dict[str, Any] = {
            "page": max(1, int(page)),
            "per_page": min(100, max(1, int(per_page))),
        }

        # Person-level filters
        if norm_cfg.titles:
            payload["person_titles"] = list(norm_cfg.titles)

        if norm_cfg.seniorities:
            payload["person_seniorities"] = list(norm_cfg.seniorities)

        if norm_cfg.include_similar_titles:
            payload["include_similar_titles"] = True

        if norm_cfg.person_locations:
            payload["person_locations"] = list(norm_cfg.person_locations)

        # Organization-level filters
        if norm_cfg.organization_locations:
            payload["organization_locations"] = list(norm_cfg.organization_locations)

        if norm_cfg.employee_ranges:
            payload["organization_num_employees_ranges"] = list(norm_cfg.employee_ranges)

        if norm_cfg.industry_tag_ids:
            payload["organization_industry_tag_ids"] = list(norm_cfg.industry_tag_ids)

        # Keyword & Signals tags (OR logic within keyword tags in Apollo)
        combined_tags: List[str] = []
        if norm_cfg.org_keyword_tags:
            for tag in norm_cfg.org_keyword_tags:
                if tag and tag not in combined_tags:
                    combined_tags.append(tag)

        # Process Signals using strict signal classification
        signals_classification = None
        if norm_cfg.signals:
            from app.services.apollo_signals_service import ApolloSignalsService
            signals_classification = ApolloSignalsService.classify_signals(norm_cfg.signals)

            # Strict rule: Apply ONLY verified company-level momentum tags to organization keyword tags.
            # Persona, Engagement, and Intent signals MUST NOT be added to company keyword tags.
            for sig_tag in signals_classification["supported_company_tags"]:
                if sig_tag and sig_tag not in combined_tags:
                    combined_tags.append(sig_tag)

        if combined_tags:
            payload["q_organization_keyword_tags"] = combined_tags

        # Funding stages filter (OR logic within stages in Apollo)
        funding_stages_list = list(norm_cfg.funding_stages or [])
        if signals_classification and signals_classification.get("includes_recent_funding"):
            # If 'Recent funding' signal is selected and no specific stage is given,
            # query all major venture and equity funding stages
            if not funding_stages_list:
                funding_stages_list = [
                    "seed", "angel", "series_a", "series_b", "series_c",
                    "series_d", "series_e", "series_f", "venture", "private_equity"
                ]

        if funding_stages_list:
            mapped_stages = ApolloQueryBuilder.map_funding_stages(funding_stages_list)
            if mapped_stages:
                payload["organization_latest_funding_stage_cd"] = mapped_stages

        if norm_cfg.lookalike_organization_ids:
            payload["lookalike_organization_ids"] = list(norm_cfg.lookalike_organization_ids)[:5]

        return payload

    @staticmethod
    def to_sanitized_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a sanitized copy of search payload safe for telemetry and logging.
        Redacts any potential sensitive tokens or keys.
        """
        sanitized = dict(payload)
        # Remove any unexpected secrets
        for secret_key in ("api_key", "X-Api-Key", "token", "password", "secret"):
            sanitized.pop(secret_key, None)
        return sanitized
