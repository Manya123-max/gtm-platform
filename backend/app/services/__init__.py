"""
Service layer â€” external integrations.
Each service is a thin wrapper around one external API.
"""
import httpx
import structlog
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode
from app.core.config import settings

logger = structlog.get_logger()


# â”€â”€ Slack Service â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SlackService:
    """Slack Bolt-compatible message sender for approvals and alerts."""

    async def send_approval_request(
        self, contact, reply_text: str, draft_response: str,
        intent: str, readiness_score: float,
        should_include_calendar: bool, thread_event_id: str,
    ) -> Optional[str]:
        if not settings.SLACK_BOT_TOKEN:
            return None

        score_emoji = "ðŸ”¥" if readiness_score >= 70 else "âš¡" if readiness_score >= 40 else "ðŸ’¬"

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"{score_emoji} *Reply from {contact.email}* | Score: {readiness_score:.0f}/100 | Intent: `{intent}`"}},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"*Their reply:*\n```{reply_text[:500]}```"}},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"*AI draft response:*\n```{draft_response[:500]}```"}},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": f"Contact: {contact.company or 'unknown'} | {'ðŸ“… Calendar link will be included' if should_include_calendar else 'No calendar link'}"}
            ]},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "✓ Approve & Send"},
                 "style": "primary", "action_id": "approve_reply",
                 "value": thread_event_id},
                {"type": "button", "text": {"type": "plain_text", "text": "✏️ Edit Response"},
                 "action_id": "edit_reply",
                 "value": thread_event_id},
                {"type": "button", "text": {"type": "plain_text", "text": "✗ Reject"},
                 "style": "danger", "action_id": "reject_reply",
                 "value": thread_event_id},
            ]},
        ]

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                    json={"channel": settings.SLACK_APPROVAL_CHANNEL, "blocks": blocks},
                )
                data = resp.json()
                return data.get("ts") if data.get("ok") else None
        except Exception as e:
            logger.error("Slack approval send failed", error=str(e))
            return None

    async def send_draft_approval_card(self, contact, draft) -> Optional[str]:
        if not settings.SLACK_BOT_TOKEN:
            return None

        first_name = getattr(contact, "first_name", "") or ""
        last_name = getattr(contact, "last_name", "") or ""
        company = getattr(contact, "company", "") or "Unknown"
        title = getattr(contact, "title", "") or "N/A"
        email = getattr(contact, "email", "") or ""

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"🔥 *Outreach Draft for {first_name} {last_name}* ({company})\n*Email:* `{email}` | *Title:* `{title}`"}},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"*Business Case:* {draft.business_case}\n*Subject:* `{draft.subject}`"}},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"*Draft Preview:*\n```{draft.body[:500]}```"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "✓ Approve & Send"},
                 "style": "primary", "action_id": "approve_draft",
                 "value": str(draft.id)},
                {"type": "button", "text": {"type": "plain_text", "text": "✗ Reject"},
                 "style": "danger", "action_id": "reject_draft",
                 "value": str(draft.id)},
            ]},
        ]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                    json={
                        "channel": settings.SLACK_APPROVAL_CHANNEL,
                        "text": f"Outreach Draft for {first_name} {last_name} ({company})",
                        "blocks": blocks,
                    },
                )
                data = resp.json()
                if data.get("ok"):
                    logger.info("Slack draft approval card sent", draft_id=str(draft.id), ts=data.get("ts"))
                    return data.get("ts")
                else:
                    logger.error("Slack API rejected draft approval card", error=data.get("error"), response=data)
                    return None
        except Exception as e:
            logger.error("Slack draft approval send failed", error=str(e))
            return None

    async def open_edit_modal(
        self, trigger_id: str, thread_event_id: str, current_draft: str
    ) -> bool:
        if not settings.SLACK_BOT_TOKEN:
            return False

        view = {
            "type": "modal",
            "callback_id": "edit_reply_modal",
            "private_metadata": thread_event_id,
            "title": {"type": "plain_text", "text": "Edit AI Response"},
            "submit": {"type": "plain_text", "text": "Save & Send"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "draft_input_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "draft_text_input",
                        "multiline": True,
                        "initial_value": (current_draft or "")[:2000],
                    },
                    "label": {"type": "plain_text", "text": "Draft Response Text"},
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://slack.com/api/views.open",
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                    json={"trigger_id": trigger_id, "view": view},
                )
                data = resp.json()
                return data.get("ok", False)
        except Exception as e:
            logger.error("Slack modal open failed", error=str(e))
            return False

    async def update_to_approved(self, ts: str, approved_by: str) -> bool:
        if not settings.SLACK_BOT_TOKEN or not ts:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.update",
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                    json={
                        "channel": settings.SLACK_APPROVAL_CHANNEL,
                        "ts": ts,
                        "text": f"✓ Approved by {approved_by}",
                        "blocks": [
                            {"type": "section", "text": {"type": "mrkdwn", "text": f"✓ *Approved and sent by {approved_by}*"}}
                        ]
                    },
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error("Slack message update approved failed", error=str(e))
            return False

    async def update_to_rejected(self, ts: str, rejected_by: str) -> bool:
        if not settings.SLACK_BOT_TOKEN or not ts:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.update",
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                    json={
                        "channel": settings.SLACK_APPROVAL_CHANNEL,
                        "ts": ts,
                        "text": f"✗ Rejected by {rejected_by}",
                        "blocks": [
                            {"type": "section", "text": {"type": "mrkdwn", "text": f"✗ *Rejected by {rejected_by}*"}}
                        ]
                    },
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error("Slack message update rejected failed", error=str(e))
            return False

    async def send_daily_digest(self, pending_actions: list) -> bool:
        if not settings.SLACK_BOT_TOKEN or not pending_actions:
            return False

        lines = [f"*📋 Daily Deal Actions — {len(pending_actions)} pending*\n"]
        for action in pending_actions[:10]:
            severity_emoji = "🔴" if "high" in str(action.reason or "").lower() else "🟡"
            action_name = str(action.action_type or "Action").replace('_', ' ').title()
            lines.append(f"{severity_emoji} *{action_name}*")
            if action.reason:
                lines.append(f"   {action.reason}")
            if action.recommended_value:
                lines.append(f"   → {action.recommended_value}\n")

        channel = settings.SLACK_ALERTS_CHANNEL or settings.SLACK_APPROVAL_CHANNEL
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                    json={
                        "channel": channel,
                        "text": "\n".join(lines),
                    },
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.error("Slack daily digest rejected", error=data.get("error"), channel=channel)
                return data.get("ok", False)
        except Exception as e:
            logger.error("Slack digest failed", error=str(e))
            return False

    async def send_alert(self, message: str) -> bool:
        if not settings.SLACK_BOT_TOKEN:
            return False
        channel = settings.SLACK_ALERTS_CHANNEL or settings.SLACK_APPROVAL_CHANNEL
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                    json={"channel": channel, "text": message},
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.error("Slack alert rejected", error=data.get("error"), channel=channel)
                return data.get("ok", False)
        except Exception as e:
            logger.error("Slack alert failed", error=str(e))
            return False


# ── Ntfy Service ────────────────────────────────────────────────────────

class NtfyService:
    """Plain push notification via ntfy.sh — default approval channel."""

    async def send_approval_alert(
        self, contact, reply_text: str, draft_response: str,
        intent: str, readiness_score: float, thread_event_id: str,
    ) -> bool:
        if not settings.NTFY_APPROVAL_TOPIC:
            return False
        message = (
            f"Reply from {contact.email} ({contact.company or 'unknown'})\n"
            f"Score: {readiness_score:.0f}/100 | Intent: {intent}\n\n"
            f"Their reply: {reply_text[:300]}\n\n"
            f"Draft: {draft_response[:300]}\n\n"
            f"thread_event_id: {thread_event_id}"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{settings.NTFY_BASE_URL}/{settings.NTFY_APPROVAL_TOPIC}",
                    content=message.encode("utf-8"),
                    headers={"Title": "GTM reply needs approval", "Priority": "high"},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error("Ntfy approval alert failed", error=str(e))
            return False

    async def send_alert(self, message: str) -> bool:
        if not settings.NTFY_ALERTS_TOPIC:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{settings.NTFY_BASE_URL}/{settings.NTFY_ALERTS_TOPIC}",
                    content=message.encode("utf-8"),
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error("Ntfy alert failed", error=str(e))
            return False


# ── Salesforce Service (Sole CRM Source of Truth) ───────────────────────────
from app.services.salesforce_service import SalesforceService, SALESFORCE_STAGE_MAP


class HubSpotService:
    """
    Deprecated: HubSpot has been retired in favor of Salesforce CRM.
    This class is maintained solely for backward compatibility.
    """
    def __init__(self):
        pass

    async def log_activity(self, *args, **kwargs) -> bool:
        logger.warning("HubSpotService.log_activity called but HubSpot is deprecated. Use SalesforceService.")
        return False

    async def sync_deals(self) -> list:
        logger.warning("HubSpotService.sync_deals called but HubSpot is deprecated. Use SalesforceService.")
        return []


# â”€â”€ Cal.com Service â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class CalService:
    """Cal.com API (v2) — free tier. Generate booking links for qualified prospects."""

    def __init__(self):
        # Cached "https://cal.com/{username}/{event-slug}" after first resolution.
        self._booking_base: Optional[str] = None

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.CAL_COM_API_KEY}",
            "cal-api-version": settings.CAL_COM_API_VERSION,
        }

    @staticmethod
    def _pick_event_slug(event_types: List[Dict]) -> Optional[str]:
        if not event_types:
            return None
        # Honour a pinned slug if it exists in the account.
        if settings.CAL_COM_EVENT_SLUG:
            for et in event_types:
                if et.get("slug") == settings.CAL_COM_EVENT_SLUG:
                    return settings.CAL_COM_EVENT_SLUG
        # Otherwise pick the shortest meeting (fastest to book).
        shortest = min(event_types, key=lambda e: e.get("lengthInMinutes") or 9999)
        return shortest.get("slug")

    async def _resolve_booking_base(self) -> Optional[str]:
        """Resolve and cache https://cal.com/{username}/{event-slug} via the v2 API."""
        if self._booking_base:
            return self._booking_base
        if settings.CAL_COM_EVENT_SLUG and settings.CAL_COM_EVENT_SLUG.startswith("http"):
            self._booking_base = settings.CAL_COM_EVENT_SLUG
            return self._booking_base
        if not settings.CAL_COM_API_KEY:
            return None

        base = settings.CAL_COM_BASE_URL.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                me = await client.get(f"{base}/me", headers=self._headers)
                me.raise_for_status()
                username = (me.json().get("data") or {}).get("username")
                if not username:
                    return None

                et = await client.get(f"{base}/event-types", headers=self._headers)
                et.raise_for_status()
                slug = self._pick_event_slug(et.json().get("data") or [])
                if not slug:
                    return None

            self._booking_base = f"https://cal.com/{username}/{slug}"
            return self._booking_base
        except Exception as e:
            logger.warning("Cal.com booking base resolution failed", error=str(e))
            return None

    def resolve_user_booking_url(self, user: Optional[Any] = None) -> Optional[str]:
        """
        Explicitly resolve a sales rep's verified Cal.com booking URL:
        1. Explicit booking URL if configured on user record: user.cal_com_booking_url
        2. Explicit Cal.com username on user record: user.cal_com_username + event_slug
        3. Explicit event slug if structured with username/event or full URL
        4. Centralized Admin User Mapping: settings.CAL_COM_USER_MAPPINGS
        5. Confirmed production identity mapping (shree.lakshmi@forcecloudlabs.com -> shree-lakshmi-iaqqsz/15min)
        CRITICAL: Never silently guess or derive username from email prefix (email.split('@')[0]).
        If unmapped, returns None to indicate 'Mapping Required'.
        """
        if not user:
            return None

        # 1. Explicit booking URL on user record
        custom_url = getattr(user, "cal_com_booking_url", None)
        if custom_url and isinstance(custom_url, str) and custom_url.strip():
            url = custom_url.strip()
            # Guard against legacy erroneous URL
            if "shreelakshmipp" not in url:
                return url

        # 2. Explicit Cal.com username on user record
        cal_username = getattr(user, "cal_com_username", None)
        if cal_username and isinstance(cal_username, str) and cal_username.strip():
            u = cal_username.strip()
            slug = getattr(user, "cal_com_event_slug", None) or getattr(settings, "CAL_COM_DEFAULT_EVENT_SLUG", None) or "15min"
            org = getattr(settings, "CAL_COM_ORG_SLUG", None)
            if org and isinstance(org, str) and org.strip():
                return f"https://cal.com/{org.strip().strip('/')}/{u}/{str(slug).strip().lstrip('/')}"
            return f"https://cal.com/{u}/{str(slug).strip().lstrip('/')}"

        # 3. Explicit event slug (if structured with username/slug or full URL)
        custom_slug = getattr(user, "cal_com_event_slug", None)
        if custom_slug and isinstance(custom_slug, str) and custom_slug.strip():
            slug = custom_slug.strip()
            if "shreelakshmipp" not in slug:
                if slug.startswith("http"):
                    return slug
                if "/" in slug:
                    return f"https://cal.com/{slug.lstrip('/')}"

        # 4. Centralized Admin User Mapping (configured by company admin)
        email = getattr(user, "email", None)
        if email and isinstance(email, str) and "@" in email:
            clean_email = email.strip().lower()
            user_mappings = getattr(settings, "CAL_COM_USER_MAPPINGS", None)
            if user_mappings:
                import json
                try:
                    mapping_dict = json.loads(user_mappings) if isinstance(user_mappings, str) else user_mappings
                    if isinstance(mapping_dict, dict) and clean_email in mapping_dict:
                        mapped_val = mapping_dict[clean_email]
                        if isinstance(mapped_val, dict):
                            if mapped_val.get("booking_url"):
                                b_url = str(mapped_val["booking_url"]).strip()
                                if "shreelakshmipp" not in b_url:
                                    return b_url
                            m_user = mapped_val.get("username")
                            m_slug = mapped_val.get("event_slug") or getattr(settings, "CAL_COM_DEFAULT_EVENT_SLUG", None) or "15min"
                            if m_user and "shreelakshmipp" not in str(m_user):
                                return f"https://cal.com/{str(m_user).strip()}/{str(m_slug).strip().lstrip('/')}"
                        elif isinstance(mapped_val, str) and "shreelakshmipp" not in mapped_val:
                            val = mapped_val.strip()
                            return val if val.startswith("http") else f"https://cal.com/{val.lstrip('/')}"
                except Exception as map_err:
                    logger.warning("CalService: Failed to parse CAL_COM_USER_MAPPINGS", error=str(map_err))

            # 5. Confirmed production company user mapping
            if clean_email == "shree.lakshmi@forcecloudlabs.com":
                return "https://cal.com/shree-lakshmi-iaqqsz/15min"

        # Explicitly NO guessing (do NOT derive username from email prefix)
        return None

    async def get_booking_link(
        self,
        contact_email: str,
        contact_name: str,
        user: Optional[Any] = None,
        user_booking_url: Optional[str] = None,
    ) -> str:
        """
        Generate a pre-filled Cal.com booking link (v2).
        If user has a specific booking URL or event slug configured, uses that rep's calendar.
        Falls back to a generic cal.com link if the API key is unset or the call fails.
        """
        params = urlencode({"name": contact_name, "email": contact_email})

        # 1. Per-sales-rep explicit booking URL
        target_url = user_booking_url or (getattr(user, "cal_com_booking_url", None) if user else None)
        if target_url and isinstance(target_url, str):
            base_url = target_url.rstrip("/")
            sep = "&" if "?" in base_url else "?"
            return f"{base_url}{sep}{params}"

        # 2. Per-sales-rep event slug (e.g. "https://cal.com/rep/15min" or "rep/15min")
        event_slug = getattr(user, "cal_com_event_slug", None) if user else None
        if event_slug and isinstance(event_slug, str):
            slug = event_slug.strip()
            if slug.startswith("http"):
                base_url = slug.rstrip("/")
            else:
                base_url = f"https://cal.com/{slug.lstrip('/')}"
            sep = "&" if "?" in base_url else "?"
            return f"{base_url}{sep}{params}"

        # 3. Automated organization / user booking profile resolution
        if user:
            auto_url = self.resolve_user_booking_url(user)
            if auto_url and isinstance(auto_url, str):
                base_url = auto_url.rstrip("/")
                sep = "&" if "?" in base_url else "?"
                return f"{base_url}{sep}{params}"

        # 3. Global company-level Cal.com account resolution
        base = await self._resolve_booking_base()
        if base:
            sep = "&" if "?" in base else "?"
            return f"{base}{sep}{params}"
        return f"https://cal.com/book?{params}"


# â”€â”€ Resend Service â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ResendService:
    """Resend API â€” 100 emails/day free. Used for weekly digest reports."""

    async def send(self, subject: str, html: str, to: Optional[List[str]] = None) -> bool:
        if not settings.RESEND_API_KEY:
            logger.info("Resend not configured â€” digest not sent")
            return False

        recipients = to or [settings.RESEND_FROM_EMAIL]
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}",
                             "Content-Type": "application/json"},
                    json={"from": settings.RESEND_FROM_EMAIL, "to": recipients,
                          "subject": subject, "html": html},
                )
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("Resend send failed", error=str(e))
            return False

    async def send_email(
        self, to: str, subject: str, html: str,
        reply_to: Optional[str] = None,
    ) -> Optional[str]:
        """
        Send a single transactional email and return the Resend message id
        (or None on failure). Used by A3 outreach and A4 replies — the
        send-only Resend key works for this.
        """
        if not settings.RESEND_API_KEY or not to:
            logger.info("Resend not configured — email not sent", to=to)
            return None

        target_email = getattr(settings, "TEST_EMAIL_OVERRIDE", None) or to

        body = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [target_email],
            "subject": subject,
            "html": html,
        }
        if reply_to:
            body["reply_to"] = reply_to
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}",
                             "Content-Type": "application/json"},
                    json=body,
                )
                resp.raise_for_status()
                return resp.json().get("id")
        except Exception as e:
            logger.error("Resend send_email failed", to=to, error=str(e))
            return None


# ── SMTP / Gmail Service ──────────────────────────────────────────────────

class SMTPService:
    """Standard SMTP / Gmail email sender."""

    async def send_email(
        self, to: str, subject: str, html: str, reply_to: Optional[str] = None
    ) -> Optional[str]:
        user = getattr(settings, "SMTP_USER", "")
        password = getattr(settings, "SMTP_PASSWORD", "")
        if not user or not password:
            logger.info("SMTP not configured (missing SMTP_USER / SMTP_PASSWORD)")
            return None

        import os
        import smtplib
        import email.utils
        import re
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        # Safety gate: Never dispatch real emails in test environments or when sending is disabled
        is_test_env = bool(
            os.environ.get("PYTEST_CURRENT_TEST")
            or getattr(settings, "AGENT3_TEST_MODE", False)
            or getattr(settings, "DRY_RUN_OUTREACH", False)
            or not getattr(settings, "ENABLE_EMAIL_SENDING", False)
        )
        if is_test_env:
            logger.info(
                "SMTPService: Live email sending suppressed (Safe/Test mode active)",
                to=to,
                subject=subject,
                enable_email_sending=getattr(settings, "ENABLE_EMAIL_SENDING", False),
            )
            return "mock_smtp_msg_ok"

        target_email = getattr(settings, "TEST_EMAIL_OVERRIDE", None) or to
        host = getattr(settings, "SMTP_HOST", "smtp.gmail.com")
        port = int(getattr(settings, "SMTP_PORT", 587))
        raw_from = getattr(settings, "SMTP_FROM_EMAIL", None) or user
        from_header = f"ForceCloud Labs GTM <{raw_from}>" if "<" not in raw_from else raw_from

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = target_email
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid()
        if reply_to:
            msg["Reply-To"] = reply_to

        # Attach plain text and HTML for maximum inbox deliverability
        plain_text = re.sub(r"<[^>]+>", "", html).strip() or "Please view this email in an HTML-compatible client."
        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            recipients = [target_email]
            if user.lower() not in [r.lower() for r in recipients]:
                recipients.append(user)

            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(user, password)
                server.sendmail(raw_from, recipients, msg.as_string())
            
            # Append message to Gmail [Gmail]/Sent Mail folder so it appears in Gmail UI Sent Mails
            try:
                import imaplib
                import time
                mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
                mail.login(user, password)
                mail.append('"[Gmail]/Sent Mail"', "\\Seen", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
                mail.logout()
                logger.info("Appended sent email to Gmail Sent Mail folder", to=target_email)
            except Exception as imap_ex:
                logger.warning("Could not append email to Gmail Sent Mail folder", error=str(imap_ex))

            logger.info("Email sent via SMTP", to=target_email)
            return "smtp_msg_ok"
        except Exception as e:
            logger.error("SMTP send_email failed", to=target_email, error=str(e))
            return None


# ── Embedding Service ─────────────────────────────────────────────────────

class EmbeddingService:
    """
    Hash-based embeddings — zero dependencies, zero disk cost.
    sentence-transformers REMOVED (it installs PyTorch = ~2GB disk).
    Provides cosine similarity for brand voice retrieval in A6.
    Accuracy is lower than neural embeddings but fully functional.
    """
    import hashlib as _hashlib
    import math as _math
    import re as _re

    def _tokenize(self, text: str):
        import re
        return re.findall(r'\b[a-z]{3,}\b', text.lower())

    def _hash_embed(self, text: str, dims: int = 384):
        import hashlib, math
        tokens = self._tokenize(text[:2000])
        vec = [0.0] * dims
        for token in tokens:
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            pos = h % dims
            weight = 1.0 / math.log(len(token) + 2)
            vec[pos] += weight
        magnitude = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / magnitude for x in vec]

    async def embed(self, text: str):
        return self._hash_embed(text)

    async def embed_batch(self, texts: list):
        return [self._hash_embed(t) for t in texts]

    def cosine_similarity(self, a: list, b: list) -> float:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a)) or 1.0
        mag_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (mag_a * mag_b)


from app.services.gmail_imap_service import GmailIMAPService
from app.services.salesforce_service import SalesforceSyncService
from app.services.token_encryption import encrypt_token, decrypt_token
from app.services.google_oauth_service import GoogleOAuthService
