import asyncio
import imaplib
import email
import structlog
from app.core.database import AsyncSessionLocal
from app.agents.a4_inbound import InboundAgent

logger = structlog.get_logger()

async def main():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login("intotech7@gmail.com", "wmmgiqboigfkxvkt")
    mail.select("inbox")

    for msg_id in ["6077", "6078"]:
        res, data = mail.fetch(msg_id, "(RFC822)")
        if not data or not data[0]:
            continue
        msg = email.message_from_bytes(data[0][1])

        body = ""
        if msg.is_multipart():
            for p in msg.walk():
                if p.get_content_type() == "text/plain":
                    payload = p.get_payload(decode=True)
                    if payload:
                        body = payload.decode(errors="ignore")
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(errors="ignore")

        payload_data = {
            "event_type": "reply_received",
            "from_address": "suriya.krishnan@forcecloudlabs.com",
            "reply_text": body.strip(),
            "subject": msg.get("Subject", "")
        }
        print(f"\n--- Processing Msg {msg_id} (Subject: {msg.get('Subject')}) ---")
        print("Reply snippet:", body.strip()[:150])

        async with AsyncSessionLocal() as db:
            agent = InboundAgent(db)
            result = await agent.handle_reply(payload_data)
            await db.commit()
            print(f"Result for Msg {msg_id}:", result)

if __name__ == "__main__":
    asyncio.run(main())
