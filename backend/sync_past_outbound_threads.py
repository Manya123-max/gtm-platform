import asyncio
from datetime import datetime
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import ConversationThread, OutreachLog, Contact

async def sync():
    async with AsyncSessionLocal() as db:
        print("--- Syncing past approved replies into ConversationThread ---")
        res = await db.execute(
            select(ConversationThread).where(
                ConversationThread.approved_at.isnot(None),
                ConversationThread.draft_content.isnot(None)
            )
        )
        approved_inbounds = res.scalars().all()
        created_replies = 0

        for thread in approved_inbounds:
            # Check if an outbound reply already exists right after this approved inbound
            existing_outbound = await db.execute(
                select(ConversationThread).where(
                    ConversationThread.contact_id == thread.contact_id,
                    ConversationThread.direction == "outbound",
                    ConversationThread.event_type == "reply_sent",
                    ConversationThread.content == thread.draft_content
                )
            )
            if not existing_outbound.scalars().first():
                outbound = ConversationThread(
                    contact_id=thread.contact_id,
                    event_type="reply_sent",
                    direction="outbound",
                    channel="email",
                    content=thread.draft_content,
                    approved_by=thread.approved_by,
                    approved_at=thread.approved_at,
                    sent_at=thread.sent_at or thread.approved_at,
                    occurred_at=thread.approved_at or datetime.utcnow(),
                    readiness_score_after=thread.readiness_score_after
                )
                db.add(outbound)
                created_replies += 1

        print(f"Created {created_replies} missing outbound reply events in ConversationThread.")

        print("--- Syncing past OutreachLog emails into ConversationThread ---")
        logs_res = await db.execute(select(OutreachLog))
        outreach_logs = logs_res.scalars().all()
        created_outreach = 0

        for log in outreach_logs:
            body_text = f"Subject: {log.subject}\n\n{log.body_preview or ''}"
            existing_thread = await db.execute(
                select(ConversationThread).where(
                    ConversationThread.contact_id == log.contact_id,
                    ConversationThread.direction == "outbound",
                    ConversationThread.event_type == "email_sent",
                    ConversationThread.occurred_at == log.sent_at
                )
            )
            if not existing_thread.scalars().first():
                outreach_thread = ConversationThread(
                    contact_id=log.contact_id,
                    event_type="email_sent",
                    direction="outbound",
                    channel=log.channel or "email",
                    content=body_text,
                    occurred_at=log.sent_at or datetime.utcnow(),
                    sent_at=log.sent_at or datetime.utcnow(),
                )
                db.add(outreach_thread)
                created_outreach += 1

        await db.commit()
        print(f"Created {created_outreach} missing outreach email events in ConversationThread.")

if __name__ == "__main__":
    asyncio.run(sync())
