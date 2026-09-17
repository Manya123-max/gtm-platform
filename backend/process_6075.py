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

    res, data = mail.fetch("6075", "(RFC822)")
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
    print("Fetched reply body from 6075:", body[:200])

    async with AsyncSessionLocal() as db:
        agent = InboundAgent(db)
        result = await agent.handle_reply(payload_data)
        await db.commit()
        print("A4 Processing Result:", result)

if __name__ == "__main__":
    asyncio.run(main())
