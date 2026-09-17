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


# â”€â”€ HubSpot Service â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class HubSpotService:
    """HubSpot CRM API â€” free tier, 40K calls/day."""

    BASE = "https://api.hubapi.com"

    @property
    def headers(self):
        return {"Authorization": f"Bearer {settings.HUBSPOT_ACCESS_TOKEN}",
                "Content-Type": "application/json"}

    async def log_activity(self, deal_id: Optional[str], activity_type: str, body: str) -> bool:
        if not settings.HUBSPOT_ACCESS_TOKEN or not deal_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.BASE}/crm/v3/objects/notes",
                    headers=self.headers,
                    json={"properties": {
                        "hs_note_body": body,
                        "hs_timestamp": str(int(__import__("time").time() * 1000)),
                    }},
                )
                resp.raise_for_status()
                note_id = resp.json().get("id")
                if note_id and deal_id:
                    await client.put(
                        f"{self.BASE}/crm/v3/objects/notes/{note_id}/associations/deals/{deal_id}/note_to_deal",
                        headers=self.headers,
                    )
                return True
        except Exception as e:
            logger.error("HubSpot activity log failed", error=str(e))
            return False

    async def sync_deals(self) -> List[Dict]:
        """Pull active deals from HubSpot for A7 pipeline data."""
        if not settings.HUBSPOT_ACCESS_TOKEN:
            return []
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{self.BASE}/crm/v3/objects/deals/search",
                    headers=self.headers,
                    json={
                        "filterGroups": [{"filters": [
                            {"propertyName": "dealstage", "operator": "NEQ", "value": "closedlost"}
                        ]}],
                        "properties": ["dealname", "amount", "dealstage", "closedate", "hubspot_owner_id"],
                        "limit": 100,
                    },
                )
                resp.raise_for_status()
                return resp.json().get("results", [])
        except Exception as e:
            logger.error("HubSpot deal sync failed", error=str(e))
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

    async def get_booking_link(self, contact_email: str, contact_name: str) -> str:
        """
        Generate a pre-filled Cal.com booking link (v2). Falls back to a
        generic cal.com link if the API key is unset or the call fails.
        """
        params = urlencode({"name": contact_name, "email": contact_email})
        base = await self._resolve_booking_base()
        if base:
            return f"{base}?{params}"
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

        import smtplib
        import email.utils
        import re
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

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