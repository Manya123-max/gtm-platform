"""
apollo_query_builder.py — Dedicated Apollo API Search Query Builder.

Converts a NormalizedICPConfig into exact Apollo mixed_people/api_search payloads.
Ensures documented parameter names, correct types, no empty/null filters, and sanitized telemetry.
"""
from __future__ import annotations

from typing import Any, Dict, List, Union
from app.services.icp_normalizer import NormalizedICPConfig, normalize_icp_input


class ApolloQueryBuilder:
    """Builder for constructing validated Apollo search request bodies."""

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
          - q_organization_keyword_tags: List[str]
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

        if norm_cfg.org_keyword_tags:
            payload["q_organization_keyword_tags"] = list(norm_cfg.org_keyword_tags)

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
