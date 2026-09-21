"""
Prospect Interest & Engagement Detection Engine
Calculates explainable 0-100 Interest Scores, lifecycle statuses, sub-score breakdowns,
and AI-generated executive conversation summaries.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional

try:
    from app.services.llm_service import LLMService
except Exception:
    class LLMService:
        async def generate_response(self, *args, **kwargs):
            return "Prospect requested follow-up meeting."

try:
    import structlog
    logger = structlog.get_logger()
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class InterestStatus:
    HIGH_INTEREST = "HIGH_INTEREST"  # Score 80-100
    WARM_ENGAGED = "WARM_ENGAGED"    # Score 50-79
    PASSIVE = "PASSIVE"              # Score 25-49
    INACTIVE = "INACTIVE"            # Score 1-24
    REJECTED = "REJECTED"            # Score 0 (Explicit refusal / DNC)


# Intent weight dictionary (max 35 pts)
INTENT_WEIGHTS = {
    "meeting_request": 35,
    "interested": 30,
    "pricing": 25,
    "technical_question": 25,
    "referral": 20,
    "unknown": 5,
    "not_interested": 0,
    "unsubscribe": 0,
}


class InterestScorer:
    """
    Explainable 0-100 Prospect Interest Scorer.
    
    Sub-scores:
    1. Intent & Sentiment (max 35 pts)
    2. Recency of Response (max 25 pts)
    3. Communication Frequency (max 20 pts)
    4. Response Rate (max 20 pts)
    5. Inactivity Decay (penalty up to -40 pts)
    """

    def __init__(self):
        self.llm = LLMService()

    def score(
        self,
        contact_dict: Dict[str, Any],
        conversation_threads: List[Dict[str, Any]],
        outreach_logs: List[Dict[str, Any]],
    ) -> Tuple[float, str, Dict[str, Any]]:
        """
        Calculates interest score, status, and breakdown dict.
        """
        # 1. Check for explicit rejection / DNC flag
        do_not_contact = contact_dict.get("do_not_contact", False)
        inbound_threads = [
            t for t in conversation_threads if t.get("direction") == "inbound"
        ]
        
        # Sort inbound threads by date descending
        inbound_threads.sort(
            key=lambda x: x.get("occurred_at") or datetime.min, reverse=True
        )
        
        latest_intent = inbound_threads[0].get("intent") if inbound_threads else None

        if do_not_contact or latest_intent in ["unsubscribe", "not_interested"]:
            breakdown = {
                "intent_score": 0,
                "recency_score": 0,
                "frequency_score": 0,
                "response_rate_score": 0,
                "inactivity_decay": 0,
                "rejection_override": True,
                "latest_intent": latest_intent or "explicit_dnc",
                "explanation": "Prospect explicitly unsubscribed or expressed zero interest (DNC).",
            }
            return 0.0, InterestStatus.REJECTED, breakdown

        now = datetime.now()

        # ── 1. Intent & Sentiment Score (max 35 pts) ──────────────────────────
        intent_score = 0
        if latest_intent:
            intent_score = INTENT_WEIGHTS.get(latest_intent, 5)

        # ── 2. Recency Score (max 25 pts) ────────────────────────────────────
        recency_score = 0
        last_response_at = contact_dict.get("last_response_at")
        if not last_response_at and inbound_threads:
            last_response_at = inbound_threads[0].get("occurred_at")

        if last_response_at:
            if isinstance(last_response_at, str):
                try:
                    last_response_at = datetime.fromisoformat(last_response_at.replace("Z", "+00:00"))
                except Exception:
                    last_response_at = None

        if last_response_at:
            if hasattr(last_response_at, "tzinfo") and last_response_at.tzinfo is not None:
                last_response_at = last_response_at.replace(tzinfo=None)
            
            days_since_response = (now - last_response_at).total_seconds() / 86400.0

            if days_since_response <= 1.0:
                recency_score = 25
            elif days_since_response <= 3.0:
                recency_score = 20
            elif days_since_response <= 7.0:
                recency_score = 15
            elif days_since_response <= 14.0:
                recency_score = 10
            elif days_since_response <= 30.0:
                recency_score = 5
            else:
                recency_score = 0

        # ── 3. Communication Frequency Score (max 20 pts) ────────────────────
        frequency_score = 0
        # Count inbound replies in last 30 days
        recent_replies_30d = 0
        for t in inbound_threads:
            t_date = t.get("occurred_at")
            if t_date:
                if isinstance(t_date, str):
                    try:
                        t_date = datetime.fromisoformat(t_date.replace("Z", "+00:00"))
                    except Exception:
                        continue
                if hasattr(t_date, "tzinfo") and t_date.tzinfo is not None:
                    t_date = t_date.replace(tzinfo=None)
                if (now - t_date).total_seconds() <= 30 * 86400:
                    recent_replies_30d += 1

        if recent_replies_30d >= 3:
            frequency_score = 20
        elif recent_replies_30d == 2:
            frequency_score = 14
        elif recent_replies_30d == 1:
            frequency_score = 8
        else:
            frequency_score = 0

        # ── 4. Response Rate Score (max 20 pts) ──────────────────────────────
        outreach_count = contact_dict.get("outreach_count") or len(outreach_logs) or 1
        response_count = contact_dict.get("response_count") or len(inbound_threads)
        
        ratio = response_count / max(1, outreach_count)
        response_rate_score = min(20, round(ratio * 20))

        # ── 5. Inactivity Decay Penalty (up to -40 pts) ──────────────────────
        inactivity_decay = 0
        last_activity_at = last_response_at or contact_dict.get("last_outreach_at")
        if not last_activity_at and outreach_logs:
            last_activity_at = outreach_logs[0].get("sent_at")

        if last_activity_at:
            if isinstance(last_activity_at, str):
                try:
                    last_activity_at = datetime.fromisoformat(last_activity_at.replace("Z", "+00:00"))
                except Exception:
                    last_activity_at = None

        if last_activity_at:
            if hasattr(last_activity_at, "tzinfo") and last_activity_at.tzinfo is not None:
                last_activity_at = last_activity_at.replace(tzinfo=None)
            
            idle_days = (now - last_activity_at).total_seconds() / 86400.0
            
            if idle_days >= 30:
                inactivity_decay = -30
            elif idle_days >= 14:
                inactivity_decay = -15
            elif idle_days >= 7:
                inactivity_decay = -5
            else:
                inactivity_decay = 0

        # Sum raw score
        raw_score = intent_score + recency_score + frequency_score + response_rate_score + inactivity_decay
        score = max(0.0, min(100.0, float(raw_score)))

        # Determine status
        if score >= 80.0:
            status = InterestStatus.HIGH_INTEREST
        elif score >= 50.0:
            status = InterestStatus.WARM_ENGAGED
        elif score >= 25.0:
            status = InterestStatus.PASSIVE
        else:
            status = InterestStatus.INACTIVE

        explanation = (
            f"Intent ({intent_score}/35), Recency ({recency_score}/25), "
            f"Frequency ({frequency_score}/20), Response Rate ({response_rate_score}/20), "
            f"Decay ({inactivity_decay})."
        )

        breakdown = {
            "intent_score": intent_score,
            "recency_score": recency_score,
            "frequency_score": frequency_score,
            "response_rate_score": response_rate_score,
            "inactivity_decay": inactivity_decay,
            "rejection_override": False,
            "latest_intent": latest_intent or "none",
            "recent_replies_30d": recent_replies_30d,
            "explanation": explanation,
        }

        return score, status, breakdown

    async def generate_conversation_summary(
        self, contact_dict: Dict[str, Any], conversation_threads: List[Dict[str, Any]]
    ) -> str:
        """
        Uses Claude LLM to generate a concise 2-sentence executive summary
        of the prospect's engagement history, interests, and next steps.
        """
        if not conversation_threads:
            return "No prior conversation history recorded for this prospect."

        # Format thread context
        thread_lines = []
        for t in conversation_threads[-6:]:  # Last 6 messages
            sender = "Prospect" if t.get("direction") == "inbound" else "Sales Team"
            content = t.get("content") or ""
            intent = t.get("intent") or "N/A"
            thread_lines.append(f"{sender} (Intent: {intent}): {content[:250]}")

        prompt = (
            f"Prospect: {contact_dict.get('first_name', '')} {contact_dict.get('last_name', '')} "
            f"at {contact_dict.get('company', 'Unknown')}.\n"
            f"Title: {contact_dict.get('title', 'N/A')}\n\n"
            f"Conversation Log:\n" + "\n".join(thread_lines) + "\n\n"
            "Summarize this prospect's engagement status, key interest/objection, and recommended next action in 2 concise sentences."
        )

        try:
            summary = await self.llm.generate_response(
                system_prompt="You are a senior GTM sales strategist. Provide clear, objective executive summaries.",
                user_prompt=prompt,
                max_tokens=150,
                temperature=0.3,
            )
            return summary.strip()
        except Exception as e:
            logger.warning("Failed to generate AI conversation summary", error=str(e))
            return f"Prospect has {len(conversation_threads)} messages logged. Latest intent: {conversation_threads[-1].get('intent', 'unknown')}."
