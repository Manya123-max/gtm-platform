import sys
sys.path.append('/app')
import asyncio
import os

from app.services.gmail_imap_service import GmailIMAPService
from app.db.session import SessionLocal
from app.services.inbound_service import inbound_service
from app.models.contact import Contact

async def check():
    db = SessionLocal()
    try:
        service = GmailIMAPService()
        # Reset processed set for testing
        from app.services import gmail_imap_service
        gmail_imap_service._PROCESSED_MSG_IDS.clear()
        
        messages = service.fetch_unread_replies()
        print(f"Total messages fetched from IMAP: {len(messages)}")
        
        for msg in messages:
            print("=" * 60)
            print(f"Msg ID: {msg.get('msg_id')}")
            print(f"From: {msg.get('from_address')}")
            print(f"Subject: {msg.get('subject')}")
            print(f"Body snippet: {msg.get('reply_text', '')[:100]}...")
            
            sender_email = msg.get('from_address', '')
            contact = db.query(Contact).filter(Contact.email.ilike(sender_email)).first()
            if not contact:
                test_override = os.getenv("TEST_EMAIL_OVERRIDE")
                print(f"Contact lookup for '{sender_email}': NONE (TEST_EMAIL_OVERRIDE={test_override})")
            else:
                print(f"Contact lookup for '{sender_email}': FOUND Contact ID={contact.id}, Name={contact.first_name} {contact.last_name}")
            
            # Process email
            res = await inbound_service.process_inbound_reply(
                db=db, 
                from_address=msg.get('from_address'),
                subject=msg.get('subject'),
                reply_text=msg.get('reply_text'),
                raw_email_data=msg
            )
            print(f"Process result: {res}")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(check())
