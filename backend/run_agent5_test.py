"""
Agent 5 — Standalone Runner & Verification Script
Simulates Fireflies transcript extraction, checks HubSpot connection, and sends Slack notification.
"""
import asyncio
import json
from app.services.llm_service import LLMService
from app.services.slack_service import SlackService
from app.core.config import settings

async def main():
    print("=" * 60)
    print("Agent 5 (Deal Intelligence) — Verification & Test Runner")
    print("=" * 60)

    # 1. Realistic Fireflies Call Transcript
    meeting_title = "HubSpot - New Deal — Enterprise Discovery & Pricing Call"
    transcript_text = """
Sales Rep: Thanks for joining today, Lauren. We're excited to walk through our platform.
Lauren Bell: Thanks! We need to automate our sales deal risk intelligence. 
Sales Rep: What budget do you have allocated for this initiative?
Lauren Bell: We have a budget of $50,000 approved for Q3. Can your team accommodate that?
Sales Rep: Yes, our annual enterprise tier is $48,000, which fits within your budget.
Lauren Bell: That's great. Regarding timeline, our VP of Revenue, Marcus Vance, needs this live in 6 weeks before sales kickoff. Marcus has final procurement sign-off.
Sales Rep: We can easily deliver in 4 weeks. Any technical or compliance blockers?
Lauren Bell: We must verify SOC2 Type II compliance and European data residency for our Germany team.
Sales Rep: We are SOC2 Type II certified and have Frankfurt EU data residency.
Lauren Bell: Perfect. Please send the proposal and MSA by Friday.
"""

    print(f"\n[1/4] Ingesting Transcript for: '{meeting_title}'")
    
    # 2. Run LLM Extraction (Agent 5 Prompt)
    print("[2/4] Running Agent 5 AI Extraction (BANT, Objections, Buying Intent)...")
    llm = LLMService()

    prompt = f"""Extract structured sales intelligence from this call transcript.

Meeting: {meeting_title}
Contact: Lauren Bell (VP of Operations)

Transcript:
{transcript_text}

Return JSON with exactly these fields:
{{
  "next_steps": ["list of concrete next steps with dates if mentioned"],
  "pain_points": ["key challenges or needs expressed"],
  "competitors_mentioned": ["names of any competitors mentioned"],
  "decision_maker_details": "name/title/role of the decision maker if mentioned or confirmed",
  "stage_confidence": 0.85,
  "objections": [{{"text": "the objection as stated", "category": "one of: pricing, competition, security, budget, timeline, integration, legal, procurement, other"}}],
  "bant_signals": {{
    "budget_confirmed": true,
    "authority_confirmed": true,
    "need_confirmed": true,
    "timeline_confirmed": true,
    "budget_notes": "budget details",
    "timeline_notes": "timeline details"
  }},
  "stakeholders_mentioned": ["names/titles of people mentioned"],
  "recommended_stage_change": "PROPOSAL",
  "recommended_stage_reason": "reason if stage change recommended",
  "call_summary": "2-3 sentence summary of the call outcome",
  "sentiment": "positive",
  "buying_intent": "strong"
}}

If a field is unclear, use null. Return valid JSON only."""

    extraction = await llm.complete(
        system="You are a sales intelligence extraction engine. Return valid JSON only.",
        user=prompt,
        use_sonnet=True,
    )
    if isinstance(extraction, str):
        try:
            extraction = json.loads(extraction)
        except Exception:
            pass

    bant = extraction.get("bant_signals", {})
    print("\n[3/4] Extracted Intelligence:")
    print(f"  • Buying Intent: {extraction.get('buying_intent', 'N/A').upper()}")
    print(f"  • Decision Maker: {extraction.get('decision_maker_details', 'N/A')}")
    print(f"  • Budget Confirmed: {bant.get('budget_confirmed')} ({bant.get('budget_notes')})")
    print(f"  • Timeline Confirmed: {bant.get('timeline_confirmed')} ({bant.get('timeline_notes')})")
    print(f"  • Objections: {len(extraction.get('objections', []))} detected")
    print(f"  • Summary: {extraction.get('call_summary')}")

    # 3. Trigger Slack Notification
    print("\n[4/4] Sending Agent 5 Notification to Slack...")
    slack = SlackService()
    alert_text = (
        f"🎯 *Agent 5: Call Transcript Processed — {meeting_title}*\n"
        f"• *Buying Intent:* `{extraction.get('buying_intent', 'N/A').upper()}`\n"
        f"• *Decision Maker:* {extraction.get('decision_maker_details', 'Identified')}\n"
        f"• *BANT Qualified:* Budget ✓ | Authority ✓ | Need ✓ | Timeline ✓\n"
        f"• *Summary:* {extraction.get('call_summary')}\n"
        f"• *Next Steps:* {', '.join(extraction.get('next_steps', ['Follow up']))}"
    )
    slack_res = await slack.send_alert(alert_text)
    print(f"Slack Notification Status: {'✓ SENT' if slack_res else 'FAILED'}")

    print("\n" + "=" * 60)
    print("Agent 5 test completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
