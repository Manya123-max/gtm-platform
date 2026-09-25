"""
Gmail IMAP Poller Service
Polls Gmail inbox (intotech7@gmail.com) for unread emails and extracts prospect replies for Agent 4 (A4 Inbound Agent).
"""
import imaplib
import email
from typing import List, Dict, Any, Optional, Set
import structlog
import redis

from app.core.config import settings

logger = structlog.get_logger()


def _get_redis():
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        return r
    except Exception:
        return None

def is_msg_processed(msg_id_str: str) -> bool:
    r = _get_redis()
    if r:
        try:
            return bool(r.sismember("gtm:processed_imap_msg_ids", msg_id_str))
        except Exception:
            pass
    return False

def mark_msg_processed(msg_id_str: str):
    r = _get_redis()
    if r:
        try:
            r.sadd("gtm:processed_imap_msg_ids", msg_id_str)
        except Exception:
            pass


class GmailIMAPService:
    def __init__(self):
        self.host = getattr(settings, "SMTP_HOST", "imap.gmail.com")
        if "smtp." in self.host:
            self.host = self.host.replace("smtp.", "imap.")
        self.port = 993
        self.user = getattr(settings, "SMTP_USER", "")
        self.password = getattr(settings, "SMTP_PASSWORD", "")

    def fetch_unread_replies(self, known_emails: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        """
        Connect to Gmail via IMAP SSL, search for recent messages in INBOX,
        parse sender email and text body.

        In TEST MODE (TEST_EMAIL_OVERRIDE configured):
          Only accepts replies from TEST_EMAIL_OVERRIDE.
        In PRODUCTION MODE:
          Only accepts replies if sender is in known_emails (existing GTM contacts).
        All other inbox emails (personal, newsletters, recruitment, etc.) are safely ignored
        and marked as processed in Redis so they are not repeatedly inspected.
        """
        if not self.user or not self.password:
            logger.warning("Gmail IMAP: SMTP_USER or SMTP_PASSWORD not set")
            return []

        messages: List[Dict[str, Any]] = []
        try:
            from datetime import datetime, timedelta
            since_date = (datetime.utcnow() - timedelta(days=3)).strftime("%d-%b-%Y")

            mail = imaplib.IMAP4_SSL(self.host, self.port)
            mail.login(self.user, self.password)
            mail.select("inbox")

            status, search_data = mail.search(None, f'SINCE "{since_date}"')
            if status != "OK" or not search_data or not search_data[0]:
                mail.logout()
                return []

            msg_ids = search_data[0].split()
            # Inspect the last 30 messages
            recent_msg_ids = msg_ids[-30:]
            logger.info("Gmail IMAP: Inspecting recent emails", total_found=len(msg_ids), inspecting=len(recent_msg_ids))

            for msg_id in recent_msg_ids:
                msg_id_str = msg_id.decode()
                if is_msg_processed(msg_id_str):
                    continue

                try:
                    res, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if res != "OK" or not msg_data:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Extract standard RFC 2822 Message-ID header if present
                    raw_msg_id = msg.get("Message-ID", "")
                    clean_msg_id = raw_msg_id.strip("<> \t\r\n") if raw_msg_id else msg_id_str
                    if clean_msg_id and is_msg_processed(clean_msg_id):
                        mark_msg_processed(msg_id_str)
                        continue

                    from_hdr = msg.get("From", "")
                    from_address = ""
                    if "<" in from_hdr and ">" in from_hdr:
                        from_address = from_hdr.split("<")[1].split(">")[0].strip()
                    else:
                        from_address = from_hdr.strip()

                    subject_hdr = msg.get("Subject", "")

                    body_text = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            content_disp = str(part.get("Content-Disposition"))
                            if content_type == "text/plain" and "attachment" not in content_disp:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body_text = payload.decode(errors="ignore")
                                    break
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode(errors="ignore")

                    clean_body = body_text.strip()

                    # Skip self-sent emails from the bot's own address
                    if from_address.lower() == self.user.lower():
                        mark_msg_processed(msg_id_str)
                        if clean_msg_id:
                            mark_msg_processed(clean_msg_id)
                        continue

                    # When TEST_EMAIL_OVERRIDE is configured, only accept emails from the test prospect address
                    test_override = (getattr(settings, "TEST_EMAIL_OVERRIDE", "") or "").strip().lower()
                    if test_override:
                        if from_address.lower() != test_override:
                            mark_msg_processed(msg_id_str)
                            if clean_msg_id:
                                mark_msg_processed(clean_msg_id)
                            logger.info("Gmail IMAP: Skipping non-test sender during test mode", from_address=from_address)
                            continue
                    else:
                        # In PRODUCTION MODE: Only accept emails from existing GTM contacts
                        if known_emails is not None and from_address.lower() not in known_emails:
                            mark_msg_processed(msg_id_str)
                            if clean_msg_id:
                                mark_msg_processed(clean_msg_id)
                            logger.info("Gmail IMAP: Skipping unknown sender not in GTM contacts (production safety)", from_address=from_address)
                            continue

                    # Filter out automated marketing or newsletters if not a real inquiry
                    marketing_domains = [
                        "noreply", "no-reply", "donotreply", "newsletter", "alert@", "notifications@",
                        "beehiiv.com", "substack.com", "magicbricks.com", "instagram.com", "hack2skill.com",
                        "theconqueror.events", "soic.in", "commandingconnection.com", "mail.instagram.com",
                        "internshala.com", "naukri.com", "scaler.com", "tcs.com"
                    ]
                    if any(d in from_address.lower() for d in marketing_domains):
                        mark_msg_processed(msg_id_str)
                        if clean_msg_id:
                            mark_msg_processed(clean_msg_id)
                        logger.info("Gmail IMAP: Skipping automated newsletter sender", from_address=from_address)
                        continue

                    # Valid reply!
                    mark_msg_processed(msg_id_str)
                    if clean_msg_id:
                        mark_msg_processed(clean_msg_id)
                    logger.info("Gmail IMAP: Discovered new client reply", from_address=from_address, subject=subject_hdr, message_id=clean_msg_id)
                    messages.append({
                        "msg_id": msg_id_str,
                        "message_id": clean_msg_id,
                        "from_address": from_address,
                        "subject": subject_hdr,
                        "reply_text": clean_body,
                    })
                except Exception as ex:
                    logger.error("Failed to parse email message", msg_id=msg_id_str, error=str(ex))

            mail.logout()
        except Exception as e:
            logger.error("Gmail IMAP polling failed", error=str(e))

        return messages
