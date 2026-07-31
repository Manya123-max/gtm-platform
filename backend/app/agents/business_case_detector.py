from typing import Dict, Any, Optional
import structlog
from app.services.llm_service import LLMService

logger = structlog.get_logger()

class BusinessCaseDetector:
    """
    Classifies B2B GTM opportunities into predefined business cases using contact and signal details.
    """

    BUSINESS_CASES = [
        "Recruitment Partnership",
        "AI Consulting",
        "Product Demo",
        "AI Automation",
        "RAG Development",
        "Digital Transformation",
        "Managed Services",
        "General Sales Outreach"
    ]

    def __init__(self, llm: LLMService = None):
        self.llm = llm or LLMService()

    async def detect(
        self,
        industry: Optional[str],
        title: Optional[str],
        signal_type: str,
        signal_data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Classifies the opportunity based on contact context and signal triggers.
        Returns:
            business_case (string)
            confidence (number 0.0-1.0)
            reason (string explanation)
        """
        system_prompt = f"""You are a B2B GTM Business Case Detector.
Your job is to analyze a prospect's firmographic context and their trigger signals to classify the sales opportunity into exactly one of these business cases:

Allowed Business Cases:
{chr(10).join(f'- {bc}' for bc in self.BUSINESS_CASES)}

Prospect Context:
- Industry: {industry or 'N/A'}
- Job Title: {title or 'N/A'}

Trigger Signal:
- Type: {signal_type}
- Signal Data: {signal_data or {}}

Evaluate which business case is the most fitting match for this opportunity.
Return a structured JSON object with exactly three fields:
- business_case (string): Must be EXACTLY one of the allowed business cases listed above.
- confidence (number): A confidence score between 0.0 and 1.0 representing your classification confidence.
- reason (string): A short, professional explanation of why this business case applies.
"""
        user_prompt = f"""Classify opportunity:
Industry: {industry or 'N/A'}
Title: {title or 'N/A'}
Signal Type: {signal_type}
Signal Data: {signal_data or {}}"""

        try:
            result = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                use_sonnet=False,  # Haiku is fast and cost-efficient
                response_format={
                    "business_case": "string",
                    "confidence": "number",
                    "reason": "string"
                }
            )
            val = result.get("business_case", "General Sales Outreach")
            if val not in self.BUSINESS_CASES:
                val = "General Sales Outreach"

            return {
                "business_case": val,
                "confidence": float(result.get("confidence", 0.5)),
                "reason": str(result.get("reason", "Fallback classification."))
            }
        except Exception as e:
            logger.error("BusinessCaseDetector detection failed, falling back", error=str(e))
            return {
                "business_case": "General Sales Outreach",
                "confidence": 0.5,
                "reason": f"Detector exception: {str(e)}"
            }
