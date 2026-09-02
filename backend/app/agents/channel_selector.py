from typing import Dict, Any, List, Optional
import structlog
from app.services.llm_service import LLMService

logger = structlog.get_logger()

class ChannelSelector:
    """
    Selects the primary and secondary outreach channels based on available contact info,
    job titles, and signal details.
    """

    CHANNELS = ["Email", "LinkedIn", "Phone", "Outlook"]

    def __init__(self, llm: LLMService = None):
        self.llm = llm or LLMService()

    async def select_channels(
        self,
        email: Optional[str],
        email_valid: Optional[bool],
        linkedin_url: Optional[str],
        title: Optional[str],
        signal_type: str
    ) -> Dict[str, Any]:
        """
        Evaluate and select channels.
        Returns:
            primary_channel (string)
            secondary_channel (string)
            available_channels (list of strings)
            reason (string explanation)
        """
        available = []
        if email and email_valid is not False:
            available.append("Email")
            available.append("Outlook")
        if linkedin_url:
            available.append("LinkedIn")
        
        # Phone is always a possible fallback option
        available.append("Phone")

        system_prompt = f"""You are a Channel Selection Engine for a B2B GTM platform.
Your job is to select the primary and secondary communication channels for outreach, based on the target contact's details and active channels.

Allowed Channels: {self.CHANNELS}
Available Channels for this Contact: {available}

Prospect Context:
- Job Title: {title or 'N/A'}
- Trigger Signal Type: {signal_type}

Analyze the job title and signal. For example:
- VPs and C-suite Executives often respond better to highly tailored Email or Outlook.
- Sales, marketing, and recruiting roles are highly active on LinkedIn.
- High urgency signals might benefit from Phone or direct Email.

Return a structured JSON object with exactly three fields:
- primary_channel (string): The best channel to use. Must be one of the Available Channels list.
- secondary_channel (string): The second best channel to use. Must be one of the Available Channels list (or "None" if only one is available).
- reason (string): A short, professional explanation of why this channel combination was chosen.
"""
        user_prompt = f"""Select channels:
Job Title: {title or 'N/A'}
Signal Type: {signal_type}
Available: {available}"""

        try:
            result = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                use_sonnet=False,  # Haiku is fast and cost-efficient
                response_format={
                    "primary_channel": "string",
                    "secondary_channel": "string",
                    "reason": "string"
                }
            )
            prim = result.get("primary_channel", "Email")
            sec = result.get("secondary_channel", "LinkedIn")
            
            # Bound checking
            if prim not in available:
                prim = available[0] if available else "Email"
            if sec not in available and sec != "None":
                sec = available[1] if len(available) > 1 else "None"

            return {
                "primary_channel": prim,
                "secondary_channel": sec,
                "available_channels": available,
                "reason": str(result.get("reason", "Fallback selection logic."))
            }
        except Exception as e:
            logger.error("ChannelSelector failed, falling back", error=str(e))
            return {
                "primary_channel": "Email",
                "secondary_channel": "LinkedIn",
                "available_channels": available,
                "reason": f"Channel selector exception: {str(e)}"
            }
