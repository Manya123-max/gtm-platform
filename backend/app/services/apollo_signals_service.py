"""
apollo_signals_service.py — Apollo Signals Registry, Classification, and Validation Service.

Defines the authoritative taxonomy for all 14 Apollo Signals across four signal groups:
1. Company momentum (Target Object: Companies)
2. Company intent (Target Object: People)
3. Persona (Target Object: People)
4. Engagement (Target Object: People)

Enforces strict API isolation rules:
- Persona signals MUST NOT be represented as company-level signals.
- Engagement signals MUST NOT be represented as company-level events.
- High buying intent MUST NOT be approximated with generic keywords.
- Only verified, supported company-level momentum signals may be queried via cold prospect search.
- Unsupported or integration-dependent signals are surfaced via structured diagnostics, never silently faked.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import structlog

logger = structlog.get_logger(__name__)


# Authoritative registry of all 14 Apollo Signals visible in Apollo interface
APOLLO_SIGNALS_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ── Group: Company momentum (Target Object: Companies) ──────────────────
    "Award or recognition": {
        "id": "award_or_recognition",
        "name": "Award or recognition",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company recently won an industry award, featured in rankings (e.g. Inc 5000), or earned notable public recognition.",
        "event_type": "Public recognition / Milestone",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "partially_supported",
        "supported_via_keyword_tags": True,
        "api_endpoint": "mixed_people/api_search",
        "api_parameter": "q_organization_keyword_tags",
        "limitations": "Matched via organization event/keyword tags. Structured press-release event stream requires Apollo News API subscription.",
    },
    "Cutting costs": {
        "id": "cutting_costs",
        "name": "Cutting costs",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company announces cost restructuring, hiring slowdowns, budget cuts, or facility consolidation.",
        "event_type": "Cost management / Restructuring",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "unsupported_in_cold_search",
        "supported_via_keyword_tags": False,
        "api_endpoint": None,
        "api_parameter": None,
        "limitations": "Requires Apollo Company Event Stream/Webhooks. Cannot be reliably queried via cold search API without custom news monitoring.",
    },
    "Merger or acquisition": {
        "id": "merger_or_acquisition",
        "name": "Merger or acquisition",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company acquired another firm or was acquired/merged, indicating systems consolidation and organizational integration needs.",
        "event_type": "M&A transaction",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "partially_supported",
        "supported_via_keyword_tags": True,
        "api_endpoint": "mixed_people/api_search",
        "api_parameter": "q_organization_keyword_tags / organization_latest_funding_stage_cd",
        "limitations": "Supported via funding stage code 'merger_or_acquisition' and news tags. Real-time M&A alerts require Apollo Events API.",
    },
    "New client signed": {
        "id": "new_client_signed",
        "name": "New client signed",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company publicly announced winning a major new commercial customer or multi-year client contract.",
        "event_type": "Commercial customer win",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "unsupported_in_cold_search",
        "supported_via_keyword_tags": False,
        "api_endpoint": None,
        "api_parameter": None,
        "limitations": "Requires Apollo News/Events Feed. Standard Apollo people search API does not expose a discrete customer-win parameter.",
    },
    "New partnership": {
        "id": "new_partnership",
        "name": "New partnership",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company established a strategic alliance, technology co-development pact, or channel reseller agreement.",
        "event_type": "Strategic partnership / Alliance",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "partially_supported",
        "supported_via_keyword_tags": True,
        "api_endpoint": "mixed_people/api_search",
        "api_parameter": "q_organization_keyword_tags",
        "limitations": "Filtered via organization news keyword tags. Proprietary closed-loop partner verification requires Apollo News stream.",
    },
    "New product or service": {
        "id": "new_product_or_service",
        "name": "New product or service",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company announced or launched a new software product line, enterprise feature set, or service capability.",
        "event_type": "Product / Service launch",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "partially_supported",
        "supported_via_keyword_tags": True,
        "api_endpoint": "mixed_people/api_search",
        "api_parameter": "q_organization_keyword_tags",
        "limitations": "Filtered via organization news keyword tags. Structured launch telemetry requires Apollo Events API.",
    },
    "Office expansion": {
        "id": "office_expansion",
        "name": "Office expansion",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company opened new regional headquarters, international branches, or expanded physical operating facilities.",
        "event_type": "Geographic / Facility expansion",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "partially_supported",
        "supported_via_keyword_tags": True,
        "api_endpoint": "mixed_people/api_search",
        "api_parameter": "q_organization_keyword_tags",
        "limitations": "Filtered via organization news keyword tags. Physical facility lease records require Apollo Real Estate / Events stream.",
    },
    "Rapid growth": {
        "id": "rapid_growth",
        "name": "Rapid growth",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company exhibits rapid headcount acceleration or exceptional business scaling (>20% YoY growth).",
        "event_type": "Headcount / Organization growth",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "partially_supported",
        "supported_via_keyword_tags": True,
        "api_endpoint": "mixed_people/api_search",
        "api_parameter": "q_organization_keyword_tags",
        "limitations": "Filtered via organization growth tags. Continuous percentage-based growth tracking requires Apollo Growth Insights.",
    },
    "Recent funding": {
        "id": "recent_funding",
        "name": "Recent funding",
        "group": "Company momentum",
        "target_object": "Companies",
        "business_meaning": "Company recently raised a venture capital, seed, debt, or private equity round, providing fresh capital for software initiatives.",
        "event_type": "Capital raise / Funding round",
        "is_company_level": True,
        "is_person_level": False,
        "support_status": "supported",
        "supported_via_keyword_tags": False,
        "api_endpoint": "mixed_people/api_search",
        "api_parameter": "organization_latest_funding_stage_cd",
        "limitations": "Fully supported using Apollo's structured organization_latest_funding_stage_cd parameter.",
    },

    # ── Group: Company intent (Target Object: People) ───────────────────────
    "High buying intent": {
        "id": "high_buying_intent",
        "name": "High buying intent",
        "group": "Company intent",
        "target_object": "People",
        "business_meaning": "Prospects working at organizations exhibiting surging digital research activity on relevant B2B topic clusters (Bombora Intent).",
        "event_type": "Third-party digital research surge",
        "is_company_level": False,
        "is_person_level": True,
        "support_status": "requires_intent_subscription",
        "supported_via_keyword_tags": False,
        "api_endpoint": "mixed_people/api_search (with Bombora Intent Add-on)",
        "api_parameter": "intent_topic_ids",
        "limitations": "Requires Apollo Custom/Enterprise plan with Bombora Intent Add-on and specific intent taxonomy topic IDs. Must NOT be approximated via generic keyword tags.",
    },

    # ── Group: Persona (Target Object: People) ──────────────────────────────
    "Former champion changed jobs": {
        "id": "former_champion_changed_jobs",
        "name": "Former champion changed jobs",
        "group": "Persona",
        "target_object": "People",
        "business_meaning": "A contact or champion from a previously closed-won deal or evaluation in your CRM has moved to a new company.",
        "event_type": "Career transition / CRM relationship match",
        "is_company_level": False,
        "is_person_level": True,
        "support_status": "requires_crm_integration",
        "supported_via_keyword_tags": False,
        "api_endpoint": "Apollo Plays / CRM Integration API",
        "api_parameter": None,
        "limitations": "Requires synced Salesforce/HubSpot CRM customer contact history. Cannot be queried in public cold prospect discovery.",
    },
    "New role": {
        "id": "new_role",
        "name": "New role",
        "group": "Persona",
        "target_object": "People",
        "business_meaning": "Individual recently started in a new job role or company within the last 30–90 days (prime vendor evaluation window).",
        "event_type": "Individual career movement",
        "is_company_level": False,
        "is_person_level": True,
        "support_status": "requires_persona_job_change_api",
        "supported_via_keyword_tags": False,
        "api_endpoint": "Apollo Job Change API / Plays",
        "api_parameter": None,
        "limitations": "Person-level signal. Not supported on standard search without specific employment start-date parameters. Must NOT be represented as a company-level signal.",
    },
    "Recently promoted": {
        "id": "recently_promoted",
        "name": "Recently promoted",
        "group": "Persona",
        "target_object": "People",
        "business_meaning": "Individual was promoted internally within their organization in the last 3–6 months.",
        "event_type": "Internal career advancement",
        "is_company_level": False,
        "is_person_level": True,
        "support_status": "requires_persona_job_change_api",
        "supported_via_keyword_tags": False,
        "api_endpoint": "Apollo Job Change API / Plays",
        "api_parameter": None,
        "limitations": "Person-level signal. Requires Apollo Plays or promotion tracking. Must NOT be represented as a company-level signal.",
    },

    # ── Group: Engagement (Target Object: People) ───────────────────────────
    "Opened 2+ emails in past week": {
        "id": "opened_2_plus_emails_in_past_week",
        "name": "Opened 2+ emails in past week",
        "group": "Engagement",
        "target_object": "People",
        "business_meaning": "Prospect has actively opened 2 or more outbound sales emails in the past 7 days (outbound sequence engagement).",
        "event_type": "Outbound email sequence engagement",
        "is_company_level": False,
        "is_person_level": True,
        "support_status": "requires_sequence_history",
        "supported_via_keyword_tags": False,
        "api_endpoint": "Apollo Sequences / Mailbox Activity",
        "api_parameter": None,
        "limitations": "First-party sequence engagement metric. Strictly impossible for cold, undiscovered prospects who have never been contacted.",
    },
}


class ApolloSignalsService:
    """Service for classifying, validating, and mapping Apollo signals to API queries."""

    @classmethod
    def get_signal_info(cls, signal_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve signal metadata by exact name (case-insensitive fallback)."""
        clean_name = signal_name.strip()
        if clean_name in APOLLO_SIGNALS_REGISTRY:
            return APOLLO_SIGNALS_REGISTRY[clean_name]

        # Case-insensitive lookup
        lower_name = clean_name.lower()
        for k, v in APOLLO_SIGNALS_REGISTRY.items():
            if k.lower() == lower_name:
                return v
        return None

    @classmethod
    def classify_signals(
        cls, signals: List[str]
    ) -> Dict[str, Any]:
        """
        Classify a list of user-requested signals into supported query parameters
        and structured diagnostic limitations.

        Returns:
            {
                "supported_company_tags": List[str],  # Safe company momentum tags for q_organization_keyword_tags
                "includes_recent_funding": bool,      # Whether 'Recent funding' was selected
                "unsupported_signals": List[Dict],    # Persona, Engagement, and Intent signals with explanations
                "all_classified": List[Dict],         # Full metadata for each signal
            }
        """
        supported_company_tags: List[str] = []
        includes_recent_funding = False
        unsupported_signals: List[Dict[str, Any]] = []
        all_classified: List[Dict[str, Any]] = []

        for sig in signals:
            clean_sig = str(sig).strip()
            if not clean_sig:
                continue

            info = cls.get_signal_info(clean_sig)
            if not info:
                # Custom or unrecognized signal: treat conservatively
                diag = {
                    "signal": clean_sig,
                    "group": "Custom",
                    "target_object": "Unknown",
                    "support_status": "unrecognized",
                    "reason": f"Signal '{clean_sig}' is not part of the standard 14 Apollo signals.",
                }
                unsupported_signals.append(diag)
                all_classified.append(diag)
                continue

            all_classified.append(info)

            # Check special cases
            if info["name"] == "Recent funding":
                includes_recent_funding = True
                continue

            # Strict isolation rules:
            if info["group"] == "Persona":
                # Must NEVER be mapped to company-level keyword tags
                unsupported_signals.append({
                    "signal": info["name"],
                    "group": info["group"],
                    "target_object": info["target_object"],
                    "support_status": info["support_status"],
                    "reason": (
                        f"'{info['name']}' is a person-level career signal requiring CRM integration or Apollo Plays. "
                        "It cannot be represented as a company-level filter in cold prospect discovery."
                    ),
                })
            elif info["group"] == "Engagement":
                # Must NEVER be mapped to company-level keyword tags
                unsupported_signals.append({
                    "signal": info["name"],
                    "group": info["group"],
                    "target_object": info["target_object"],
                    "support_status": info["support_status"],
                    "reason": (
                        f"'{info['name']}' is a first-party sequence engagement metric. "
                        "It strictly cannot filter cold, never-contacted prospects."
                    ),
                })
            elif info["group"] == "Company intent":
                # High buying intent requires Bombora Intent Add-on
                unsupported_signals.append({
                    "signal": info["name"],
                    "group": info["group"],
                    "target_object": info["target_object"],
                    "support_status": info["support_status"],
                    "reason": (
                        f"'{info['name']}' requires an Apollo Custom/Enterprise plan with the Bombora Intent Add-on. "
                        "It cannot be approximated via generic keyword tags."
                    ),
                })
            elif info.get("supported_via_keyword_tags"):
                # Company momentum signals that can legitimately search company news tags
                if info["name"] not in supported_company_tags:
                    supported_company_tags.append(info["name"])
            else:
                # Other unsupported company momentum signals (e.g. Cutting costs, New client signed)
                unsupported_signals.append({
                    "signal": info["name"],
                    "group": info["group"],
                    "target_object": info["target_object"],
                    "support_status": info["support_status"],
                    "reason": info.get("limitations", "Not supported in cold discovery API search."),
                })

        return {
            "supported_company_tags": supported_company_tags,
            "includes_recent_funding": includes_recent_funding,
            "unsupported_signals": unsupported_signals,
            "all_classified": all_classified,
        }

