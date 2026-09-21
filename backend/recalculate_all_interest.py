"""
Utility script to recalculate Interest Scores and AI Summaries for all contacts.
Can be executed as a background job or standalone script.
"""

import asyncio
from datetime import datetime
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import Contact, ConversationThread, OutreachLog
from app.services.interest_scoring_service import InterestScorer, InterestStatus


async def recalculate_all():
    async with AsyncSessionLocal() as db:
        scorer = InterestScorer()
        result = await db.execute(select(Contact))
        contacts = result.scalars().all()
        print(f"Recalculating interest scores for {len(contacts)} contacts...")

        updated_count = 0
        for contact in contacts:
            # Fetch threads
            t_res = await db.execute(
                select(ConversationThread)
                .where(ConversationThread.contact_id == contact.id)
                .order_by(ConversationThread.occurred_at.asc())
            )
            threads = t_res.scalars().all()
            thread_dicts = [
                {
                    "direction": t.direction,
                    "content": t.content,
                    "intent": t.intent,
                    "occurred_at": t.occurred_at,
                }
                for t in threads
            ]

            # Fetch outreach logs
            o_res = await db.execute(
                select(OutreachLog)
                .where(OutreachLog.contact_id == contact.id)
                .order_by(OutreachLog.sent_at.asc())
            )
            outreaches = o_res.scalars().all()
            outreach_dicts = [{"sent_at": o.sent_at} for o in outreaches]

            # Set response_count & outreach_count if missing
            inbound_count = len([t for t in thread_dicts if t["direction"] == "inbound"])
            contact.response_count = inbound_count
            contact.outreach_count = len(outreach_dicts) or contact.outreach_count or 1

            contact_dict = {
                "do_not_contact": contact.do_not_contact,
                "last_response_at": contact.last_response_at,
                "last_outreach_at": contact.last_outreach_at,
                "response_count": contact.response_count,
                "outreach_count": contact.outreach_count,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "company": contact.company,
                "title": contact.title,
            }

            score, status, breakdown = scorer.score(contact_dict, thread_dicts, outreach_dicts)
            
            contact.interest_score = score
            contact.interest_status = status
            contact.interest_score_breakdown = breakdown
            contact.interest_updated_at = datetime.utcnow()

            if status == InterestStatus.REJECTED:
                contact.do_not_contact = True

            if not contact.conversation_summary and thread_dicts:
                summary = await scorer.generate_conversation_summary(contact_dict, thread_dicts)
                contact.conversation_summary = summary

            updated_count += 1

        await db.commit()
        print(f"Successfully updated interest scores for {updated_count} contacts.")


if __name__ == "__main__":
    asyncio.run(recalculate_all())
