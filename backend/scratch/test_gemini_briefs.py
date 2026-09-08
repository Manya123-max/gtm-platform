import asyncio
import json
import httpx
from app.core.config import settings

GEMINI_MODELS = ["gemini-3.7-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-flash-latest"]

async def call_gemini_with_fallback(system: str, user: str, max_tokens: int = 2500, force_json: bool = False) -> str:
    combined = f"{system}\n\n{user}" if system else user
    payload = {
        "contents": [{"parts": [{"text": combined}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.3,
        }
    }
    if force_json:
        payload["generationConfig"]["responseMimeType"] = "application/json"
        
    last_err = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0] and "parts" in candidates[0]["content"]:
                            text = candidates[0]["content"]["parts"][0].get("text", "").strip()
                            if text:
                                return text
                    elif resp.status_code in (429, 503):
                        await asyncio.sleep(1)
                        continue
                    else:
                        break
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.5)
    raise RuntimeError(f"All Gemini models failed. Last error: {last_err}")

async def test_a6_brief_clustering():
    insights_text = """
Inbound Email Objections/Questions (A4):
  - Company: GrowthOps | Text: We're feeling growing pains scaling outbound. What does your platform do exactly?
  - Company: ScalePath | Text: Evaluating outbound stack right now. Send me a one-pager?
  - Company: DataBridge | Text: Switched from HubSpot to Salesforce and in the middle of migration chaos.

Deal Blockers and Risk Flags (A5):
  - Company: Acme Corp [security] | Text: Our only concern is around HIPAA and SOC2 Type II compliance
  - Company: CloudZone [security] | Text: We need European data residency guarantee for our Frankfurt operations
  - Company: CloudZone [security] | Text: Our security team requires SOC2 Type II audit report before contracting
"""
    prompt = f"""Analyse these inputs to generate 3 content briefs for a B2B SaaS GTM platform:

1. REAL PROSPECT & DEAL INSIGHTS:
These are real objections and pain points from actual prospect conversations and deals.
IMPORTANT: Prioritize topics that address these objections and pain points over external signals, since these are direct signals from active accounts.

{insights_text}

ICP segments being targeted: SaaS, B2B Technology, Healthcare Tech, FinTech

Return a JSON object with a single key "briefs" containing a list of exactly 3 briefs:
{{
  "briefs": [
    {{
      "topic": "specific topic title addressing prospect needs/objections",
      "icp_segment": "which ICP segment this targets",
      "angle": "unique angle helping overcome the objection or educating the market",
      "key_messages": ["3 key points to make"],
      "proof_points": ["data or examples to include"],
      "competitor_gap": "how this specific angle stands out or differs from standard blog advice"
    }}
  ]
}}"""

    print("Generating 3 briefs using Gemini with fallback...")
    raw = await call_gemini_with_fallback(prompt, "Generate the briefs now.", force_json=True)
    print("Gemini Output:")
    print(raw)
    parsed = json.loads(raw)
    print(f"\nParsed {len(parsed.get('briefs', []))} briefs successfully!")

if __name__ == "__main__":
    asyncio.run(test_a6_brief_clustering())
