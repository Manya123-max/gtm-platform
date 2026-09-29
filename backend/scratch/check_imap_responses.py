import asyncio
import os
import sys

from app.services.gmail_imap_service import GmailIMAPService
from app.core.database import AsyncSessionLocal
from app.agents.a4_inbound import InboundAgent
from app.models.models import Contact
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        try:
            service = GmailIMAPService()
            # Clear in-memory deduplication set to test all recent messages
            from app.services import gmail_imap_service
            gmail_imap_service._PROCESSED_MSG_IDS.clear()
            
            messages = service.fetch_unread_replies()
            print(f"Total messages fetched from IMAP: {len(messages)}")
            
            for msg in messages:
                print("=" * 60)
                print(f"Msg ID: {msg.get('msg_id')}")
                print(f"From: {msg.get('from_address')}")
                print(f"Subject: {msg.get('subject')}")
                print(f"Body snippet:\n{msg.get('reply_text', '')}\n")
                
                sender_email = msg.get('from_address', '')
                stmt = select(Contact).where(Contact.email.ilike(sender_email))
                res = await db.execute(stmt)
                contact = res.scalars().first()
                if not contact:
                    test_override = os.getenv("TEST_EMAIL_OVERRIDE")
                    print(f"Contact lookup for '{sender_email}': NONE (TEST_EMAIL_OVERRIDE={test_override})")
                else:
                    print(f"Contact lookup for '{sender_email}': FOUND Contact ID={contact.id}, Name={contact.first_name} {contact.last_name}")
                
                agent = InboundAgent(db)
                payload_data = {
                    "event_type": "reply_received",
                    "from_address": msg.get("from_address"),
                    "reply_text": msg.get("reply_text"),
                    "subject": msg.get("subject")
                }
                result = await agent.handle_reply(payload_data)
                await db.commit()
                print(f"Process result: {result}")
                
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check())
