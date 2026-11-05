"""
Account & Prospect Tiering Service
Prioritizes prospects and accounts into Tier 1, Tier 2, and Tier 3 based on:
1. ICP fit score (A1)
2. Verified buying signal score and signal type (A2)
3. Signal recency using actual event dates (within 30 days)
4. Coherent event qualification: Signal score, signal type, source, and recency
   must originate from the same relevant event.
5. Account-level aggregation: Multiple contacts belonging to the same company
   share the same account tier classification consistently.
"""
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()

# ── Configurable Tiering Thresholds ──────────────────────────────────────────
TIER_1_MIN_ICP: float = 70.0            # Strong ICP fit
TIER_1_MIN_SIGNAL_SCORE: float = 55.0   # Verified buying intent score threshold (covers 58 funding, 61 new hire, 64 earnings)
TIER_1_MOMENTUM_MIN_ICP: float = 65.0   # Good ICP fit eligible for momentum Tier 1
TIER_1_MOMENTUM_MIN_SIGNAL: float = 64.0 # Exceptionally strong signal required for ICP 65-69
TIER_2_MIN_ICP: float = 65.0            # Good ICP fit awaiting signals
TIER_2_MID_ICP: float = 50.0            # Moderate/Promising ICP fit
TIER_2_MIN_SIGNAL_SCORE: float = 40.0   # Moderate/meaningful buying signal
TIER_2_OPPORTUNISTIC_MIN_ICP: float = 40.0 # Fringe ICP fit eligible with verified active buying events
RECENCY_WINDOW_DAYS: int = 30           # Active buying window (30 days)

# Verified Active Buying Intent Signal Types
# These represent verifiable commercial triggers rather than passive infrastructure.
ACTIVE_BUYING_INTENT_TYPES: Set[str] = {
    "funding_round",
    "new_hire",
    "earnings_call",
}

# Signal types that can be meaningful recent signals (e.g. for ICP 50-64 or supporting)
MEANINGFUL_SIGNAL_TYPES: Set[str] = {
    "funding_round",
    "new_hire",
    "earnings_call",
    "job_posting",
    "competitor_review",
    "news_expansion",
    "tech_stack_change",
}

# Sources representing passive infrastructure detection rather than active buying intent
PASSIVE_SOURCES: Set[str] = {
    "website_fingerprint",
}


class AccountTierInfo:
    def __init__(
        self,
        company: str,
        tier: int,
        tier_label: str,
        reason: str,
        account_icp_score: float,
        account_signal_score: float,
        signal_types: List[str],
        signal_count: int,
        latest_signal_at: Optional[datetime],
        is_recent: bool,
        qualifying_signal_type: Optional[str] = None,
        qualifying_signal_score: Optional[float] = None,
        qualifying_event_at: Optional[datetime] = None,
    ):
        self.company = company
        self.tier = tier
        self.tier_label = tier_label
        self.reason = reason
        self.account_icp_score = account_icp_score
        self.account_signal_score = account_signal_score
        self.signal_types = signal_types
        self.signal_count = signal_count
        self.latest_signal_at = latest_signal_at
        self.is_recent = is_recent
        self.qualifying_signal_type = qualifying_signal_type
        self.qualifying_signal_score = qualifying_signal_score
        self.qualifying_event_at = qualifying_event_at


class AccountTierService:
    """
    Evaluates and assigns account tiers consistently across all contacts
    belonging to the same company based on ICP fit and verified market signals.
    """

    @classmethod
    def _extract_events(cls, contacts: List[Any], now: datetime) -> List[Dict[str, Any]]:
        """
        Extracts coherent individual signal events across contacts.
        Ensures signal score, signal type, source, and recency belong to the same event.
        Guards against cross-event contamination, duplicate signals, and passive tech.
        """
        events: List[Dict[str, Any]] = []
        seen_event_ids: Set[str] = set()

        for c in contacts:
            # 1. If SQLAlchemy contact has eager-loaded signals relationship
            c_signals = getattr(c, "signals", None)
            if c_signals and isinstance(c_signals, list):
                for s in c_signals:
                    sig_id = getattr(s, "id", None)
                    if sig_id and sig_id in seen_event_ids:
                        continue
                    if sig_id:
                        seen_event_ids.add(sig_id)

                    s_type = str(getattr(s, "signal_type", "") or "")
                    s_src = str(getattr(s, "signal_source", "") or "")
                    conf = getattr(s, "confidence", 0.0) or 0.0
                    score = round(conf * 100, 1)
                    s_dt = getattr(s, "detected_at", None)
                    raw = getattr(s, "raw_data", None) or {}
                    headline = raw.get("headline") or raw.get("title") or getattr(s, "summary", "") or ""

                    days_ago = (now - s_dt).days if s_dt else 999
                    is_recent = 0 <= days_ago <= RECENCY_WINDOW_DAYS
                    is_passive = s_src in PASSIVE_SOURCES or (
                        s_type == "tech_stack_change" and s_src not in ("google_news_rss", "newsapi", "currents")
                    )

                    events.append({
                        "id": sig_id,
                        "type": s_type,
                        "source": s_src,
                        "score": score,
                        "occurred_at": s_dt,
                        "days_ago": days_ago,
                        "is_recent": is_recent,
                        "is_passive": is_passive,
                        "headline": headline,
                    })
            else:
                # 2. Fallback to contact's own coupled signal fields (e.g. for unit test stubs)
                sig_type_str = getattr(c, "signal_type", None)
                sig_score = getattr(c, "signal_score", None)
                sig_at = getattr(c, "latest_signal_at", None)
                sig_src = str(getattr(c, "signal_source", None) or getattr(c, "source", None) or "")
                summary = getattr(c, "signal_summary", "") or ""

                if sig_type_str and sig_score is not None:
                    types = [t.strip() for t in str(sig_type_str).split(",") if t.strip()]
                    contact_id = getattr(c, "id", str(id(c)))
                    dedup_key = f"{contact_id}_{sig_type_str}_{sig_score}_{sig_at}"
                    if dedup_key in seen_event_ids:
                        continue
                    seen_event_ids.add(dedup_key)

                    days_ago = (now - sig_at).days if sig_at else 999
                    is_recent = 0 <= days_ago <= RECENCY_WINDOW_DAYS
                    is_passive = sig_src in PASSIVE_SOURCES

                    # Treat each unique signal type from this contact as a coupled candidate
                    for t in types:
                        t_passive = is_passive or (t == "tech_stack_change" and sig_src in PASSIVE_SOURCES)
                        events.append({
                            "id": None,
                            "type": t,
                            "source": sig_src,
                            "score": float(sig_score),
                            "occurred_at": sig_at,
                            "days_ago": days_ago,
                            "is_recent": is_recent,
                            "is_passive": t_passive,
                            "headline": summary,
                        })

        # Sort events by score descending, then recency ascending
        events.sort(key=lambda x: (x["score"], -x["days_ago"]), reverse=True)
        return events

    @classmethod
    def classify_company(
        cls,
        company_name: str,
        contacts: List[Any],
        now: Optional[datetime] = None,
    ) -> AccountTierInfo:
        if now is None:
            now = datetime.utcnow()

        # 1. Aggregate company-level ICP fit across all associated contacts
        icp_scores = [c.icp_score for c in contacts if getattr(c, "icp_score", None) is not None]
        max_icp = max(icp_scores) if icp_scores else 0.0

        # 2. Extract coherent events across contacts
        events = cls._extract_events(contacts, now=now)

        # 3. Collect company-level signal summaries
        all_types = sorted(list(set(e["type"] for e in events if e.get("type"))))
        max_signal = max([e["score"] for e in events] or [0.0])
        latest_sig = max([e["occurred_at"] for e in events if e.get("occurred_at")] or [None])
        is_recent = any(e["is_recent"] for e in events)

        # Filter events for tier qualification:
        # A) Active buying intent events:
        #    - funding_round, new_hire, earnings_call
        #    - score >= 55.0 (covers calibrated 58 funding, 61 new hire, 64 earnings call)
        #    - recent (occurred within 30 days)
        #    - NOT passive tech presence (website_fingerprint)
        recent_active_buying_events = [
            e for e in events
            if e["is_recent"] and not e["is_passive"] and e["type"] in ACTIVE_BUYING_INTENT_TYPES and e["score"] >= TIER_1_MIN_SIGNAL_SCORE
        ]

        # B) Meaningful recent events (e.g. for ICP 50-64):
        #    - score >= 40.0, recent (within 30 days), non-passive
        #    - funding_round, new_hire, earnings_call, job_posting, competitor_review
        recent_meaningful_events = [
            e for e in events
            if e["is_recent"] and not e["is_passive"] and e["type"] in MEANINGFUL_SIGNAL_TYPES and e["score"] >= TIER_2_MIN_SIGNAL_SCORE
        ]

        # C) Verified active buying events for ICP 40-49 (such as funding or relevant hiring):
        #    - funding_round, new_hire, job_posting with score >= 40.0, recent, non-passive
        recent_hiring_funding_events = [
            e for e in events
            if e["is_recent"] and not e["is_passive"] and e["type"] in {"funding_round", "new_hire", "job_posting"} and e["score"] >= TIER_2_MIN_SIGNAL_SCORE
        ]

        # ── 4. Apply Classification Rules ────────────────────────────────────

        # Tier 1 — High priority:
        # - ICP >= 70 with recent, verified buying intent
        # - OR ICP 65–69 with exceptionally strong verified signals (score >= 64 or multiple active buying events)
        if max_icp >= TIER_1_MIN_ICP and recent_active_buying_events:
            top_e = recent_active_buying_events[0]
            sig_type_disp = top_e["type"].replace("_", " ")
            reason = (
                f"Strong ICP fit ({max_icp:.0f}) with recent verified buying intent: "
                f"{sig_type_disp} (score {top_e['score']:.0f}, detected {top_e['days_ago']}d ago)."
            )
            return AccountTierInfo(
                company=company_name,
                tier=1,
                tier_label="Tier 1",
                reason=reason,
                account_icp_score=max_icp,
                account_signal_score=top_e["score"],
                signal_types=all_types,
                signal_count=len(all_types),
                latest_signal_at=top_e["occurred_at"],
                is_recent=True,
                qualifying_signal_type=top_e["type"],
                qualifying_signal_score=top_e["score"],
                qualifying_event_at=top_e["occurred_at"],
            )

        if TIER_1_MOMENTUM_MIN_ICP <= max_icp < TIER_1_MIN_ICP and (
            any(e["score"] >= TIER_1_MOMENTUM_MIN_SIGNAL and e["is_recent"] and not e["is_passive"] and e["type"] in ACTIVE_BUYING_INTENT_TYPES for e in events)
            or len(recent_active_buying_events) >= 2
        ):
            top_e = recent_active_buying_events[0]
            sig_type_disp = top_e["type"].replace("_", " ")
            reason = (
                f"High Momentum: Good ICP fit ({max_icp:.0f}) elevated by exceptionally strong verified signals: "
                f"{sig_type_disp} (score {top_e['score']:.0f}, detected {top_e['days_ago']}d ago)."
            )
            return AccountTierInfo(
                company=company_name,
                tier=1,
                tier_label="Tier 1 (Momentum)",
                reason=reason,
                account_icp_score=max_icp,
                account_signal_score=top_e["score"],
                signal_types=all_types,
                signal_count=len(all_types),
                latest_signal_at=top_e["occurred_at"],
                is_recent=True,
                qualifying_signal_type=top_e["type"],
                qualifying_signal_score=top_e["score"],
                qualifying_event_at=top_e["occurred_at"],
            )

        # Tier 2 — Medium priority:
        # - ICP >= 65 awaiting signals (or with passive/supporting/stale signals)
        # - ICP 50–64 with meaningful recent signals
        # - ICP 40–49 with verified active buying events such as funding or relevant hiring
        if max_icp >= TIER_2_MIN_ICP:
            if events:
                top_e = events[0]
                if all(not e["is_recent"] for e in events):
                    stale_sig = events[0]
                    reason = f"Strong ICP fit ({max_icp:.0f}); signals are older than 30d ({stale_sig['days_ago']}d ago); awaiting fresh buying triggers."
                elif all(e["is_passive"] for e in events):
                    reason = f"Strong ICP fit ({max_icp:.0f}) with installed tech stack presence; awaiting active buying intent triggers."
                else:
                    reason = f"Strong ICP fit ({max_icp:.0f}) with supporting market signals; awaiting high-intent buying signals."

                return AccountTierInfo(
                    company=company_name,
                    tier=2,
                    tier_label="Tier 2",
                    reason=reason,
                    account_icp_score=max_icp,
                    account_signal_score=top_e["score"],
                    signal_types=all_types,
                    signal_count=len(all_types),
                    latest_signal_at=top_e["occurred_at"],
                    is_recent=is_recent,
                    qualifying_signal_type=top_e["type"],
                    qualifying_signal_score=top_e["score"],
                    qualifying_event_at=top_e["occurred_at"],
                )
            else:
                reason = f"Strong ICP fit ({max_icp:.0f}); awaiting recent buying signals for outreach."
                return AccountTierInfo(
                    company=company_name,
                    tier=2,
                    tier_label="Tier 2",
                    reason=reason,
                    account_icp_score=max_icp,
                    account_signal_score=0.0,
                    signal_types=[],
                    signal_count=0,
                    latest_signal_at=None,
                    is_recent=False,
                    qualifying_signal_type=None,
                    qualifying_signal_score=None,
                    qualifying_event_at=None,
                )

        if TIER_2_MID_ICP <= max_icp < TIER_2_MIN_ICP and recent_meaningful_events:
            top_e = recent_meaningful_events[0]
            sig_type_disp = top_e["type"].replace("_", " ")
            reason = (
                f"Promising ICP fit ({max_icp:.0f}) with meaningful recent market signals: "
                f"{sig_type_disp} (score {top_e['score']:.0f}, detected {top_e['days_ago']}d ago)."
            )
            return AccountTierInfo(
                company=company_name,
                tier=2,
                tier_label="Tier 2",
                reason=reason,
                account_icp_score=max_icp,
                account_signal_score=top_e["score"],
                signal_types=all_types,
                signal_count=len(all_types),
                latest_signal_at=top_e["occurred_at"],
                is_recent=True,
                qualifying_signal_type=top_e["type"],
                qualifying_signal_score=top_e["score"],
                qualifying_event_at=top_e["occurred_at"],
            )

        if TIER_2_OPPORTUNISTIC_MIN_ICP <= max_icp < TIER_2_MID_ICP and recent_hiring_funding_events:
            top_e = recent_hiring_funding_events[0]
            sig_type_disp = top_e["type"].replace("_", " ")
            reason = (
                f"Opportunistic Discovery: Fringe ICP fit ({max_icp:.0f}) elevated by verified active buying event: "
                f"{sig_type_disp} (score {top_e['score']:.0f}, detected {top_e['days_ago']}d ago)."
            )
            return AccountTierInfo(
                company=company_name,
                tier=2,
                tier_label="Tier 2 (Opportunistic)",
                reason=reason,
                account_icp_score=max_icp,
                account_signal_score=top_e["score"],
                signal_types=all_types,
                signal_count=len(all_types),
                latest_signal_at=top_e["occurred_at"],
                is_recent=True,
                qualifying_signal_type=top_e["type"],
                qualifying_signal_score=top_e["score"],
                qualifying_event_at=top_e["occurred_at"],
            )

        # Tier 3 — Lower priority:
        # All remaining accounts without sufficient fit or reliable buying evidence
        if max_icp < TIER_2_OPPORTUNISTIC_MIN_ICP:
            reason = f"Insufficient ICP fit ({max_icp:.0f}); does not meet qualification profile."
        elif TIER_2_OPPORTUNISTIC_MIN_ICP <= max_icp < TIER_2_MID_ICP:
            reason = f"Fringe ICP fit ({max_icp:.0f}) without verified funding or hiring events; monitor for active triggers."
        elif TIER_2_MID_ICP <= max_icp < TIER_2_MIN_ICP:
            reason = f"Moderate fit ({max_icp:.0f}) without meaningful recent buying signals; monitor for new triggers."
        else:
            reason = f"Unclassified account profile (ICP {max_icp:.0f}); awaiting qualification."

        top_e = events[0] if events else None
        return AccountTierInfo(
            company=company_name,
            tier=3,
            tier_label="Tier 3",
            reason=reason,
            account_icp_score=max_icp,
            account_signal_score=top_e["score"] if top_e else 0.0,
            signal_types=all_types,
            signal_count=len(all_types),
            latest_signal_at=top_e["occurred_at"] if top_e else None,
            is_recent=is_recent,
            qualifying_signal_type=top_e["type"] if top_e else None,
            qualifying_signal_score=top_e["score"] if top_e else None,
            qualifying_event_at=top_e["occurred_at"] if top_e else None,
        )

    @classmethod
    def annotate_contacts(cls, contacts: List[Any], now: Optional[datetime] = None) -> List[Any]:
        """
        Groups contacts by company, computes account tier, and annotates
        tier properties on each contact object.
        """
        if not contacts:
            return contacts

        if now is None:
            now = datetime.utcnow()

        # Group contacts by normalized company name
        company_groups: Dict[str, List[Any]] = {}
        for c in contacts:
            comp_key = (getattr(c, "company", "") or "Unknown").strip().lower()
            if comp_key not in company_groups:
                company_groups[comp_key] = []
            company_groups[comp_key].append(c)

        # Classify each company once
        tier_map: Dict[str, AccountTierInfo] = {}
        for comp_key, comp_contacts in company_groups.items():
            display_comp = comp_contacts[0].company if comp_contacts[0].company else comp_key
            tier_map[comp_key] = cls.classify_company(display_comp, comp_contacts, now=now)

        # Assign tier attributes to all contacts
        for c in contacts:
            comp_key = (getattr(c, "company", "") or "Unknown").strip().lower()
            info = tier_map[comp_key]
            c.tier = info.tier
            c.tier_label = info.tier_label
            c.tier_reason = info.reason
            c.signal_count = info.signal_count
            c.account_icp_score = info.account_icp_score
            c.account_signal_score = info.account_signal_score

            # Synchronize coherent primary qualifying signal across score, badge, and date
            c.primary_signal_type = info.qualifying_signal_type
            c.primary_signal_score = info.qualifying_signal_score
            c.primary_signal_at = info.qualifying_event_at

            if info.qualifying_signal_type:
                # Ensure primary qualifying signal is the first type in comma-separated list
                existing_types = [t.strip() for t in str(getattr(c, "signal_type", "") or "").split(",") if t.strip()]
                ordered_types = [info.qualifying_signal_type] + [t for t in existing_types if t != info.qualifying_signal_type]
                c.signal_type = ",".join(ordered_types) if ordered_types else info.qualifying_signal_type
                c.signal_score = info.qualifying_signal_score
                c.latest_signal_at = info.qualifying_event_at
            elif not info.signal_types:
                c.signal_type = None
                c.signal_score = None
                c.latest_signal_at = None

        return contacts

    @classmethod
    def compute_summary(cls, contacts: List[Any], now: Optional[datetime] = None) -> Dict[str, int]:
        """
        Calculates exact count of contacts in All, Tier 1, Tier 2, and Tier 3.
        """
        annotated = cls.annotate_contacts(contacts, now=now)
        t1 = sum(1 for c in annotated if getattr(c, "tier", None) == 1)
        t2 = sum(1 for c in annotated if getattr(c, "tier", None) == 2)
        t3 = sum(1 for c in annotated if getattr(c, "tier", None) == 3)
        return {
            "all": len(annotated),
            "tier_1": t1,
            "tier_2": t2,
            "tier_3": t3,
        }
