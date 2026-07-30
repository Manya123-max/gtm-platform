from typing import Dict, Any, List, Optional
import structlog
from app.services.llm_service import LLMService

logger = structlog.get_logger()

class ServiceMatcher:
    """
    Compares our services with detected company needs, hiring information, and buying signals.
    """

    def __init__(self, llm: LLMService = None):
        self.llm = llm or LLMService()

    async def match(
        self,
        our_services: str,
        industry: Optional[str],
        title: Optional[str],
        hiring_info: Optional[Dict[str, Any]],
        buying_signal: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Compare services, hiring info, and signals.
        Returns:
            matched_services (list of strings)
            match_score (number between 0 and 100)
            reason (string explanation)
        """
        system_prompt = f"""You are a Service Matching Engine for a B2B GTM platform.
Your job is to compare a vendor's services with a prospect company's context, hiring information, and buying signals to evaluate product-market alignment.

We sell these services: {our_services}.

Prospect Context:
- Industry: {industry or 'N/A'}
- Job Title of Target: {title or 'N/A'}

Hiring Information:
- Active Roles/Searches: {hiring_info or 'None detected'}

Buying Signals:
- Signals details: {buying_signal or 'None detected'}

You must evaluate how well our services align with their business needs, hiring patterns, and trigger signals.
Return a structured JSON object with exactly three fields:
- matched_services (array of strings): Sub-list of our services that are highly relevant to this prospect.
- match_score (number from 0 to 100): An alignment score (0 = no match, 100 = perfect alignment).
- reason (string): A brief, analytical explanation of why these services were matched or why the score is low.
"""
        user_prompt = f"""Evaluate alignment for:
Industry: {industry or 'N/A'}
Title: {title or 'N/A'}
Hiring: {hiring_info or 'N/A'}
Signal: {buying_signal or 'N/A'}"""

        try:
            result = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                use_sonnet=False,  # Use Haiku for cost efficiency
                response_format={
                    "matched_services": ["string"],
                    "match_score": "number",
                    "reason": "string"
                }
            )
            return {
                "matched_services": list(result.get("matched_services", [])),
                "match_score": float(result.get("match_score", 50)),
                "reason": str(result.get("reason", ""))
            }
        except Exception as e:
            logger.error("ServiceMatcher match failed, falling back to general values", error=str(e))
            return {
                "matched_services": ["CRM consulting"],
                "match_score": 50.0,
                "reason": f"ServiceMatcher encountered an error during evaluation: {str(e)}"
            }
