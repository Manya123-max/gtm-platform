import asyncio
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models.models import ConversationThread, Deal, Contact, FunnelEvent, GeneratedContent
from app.core.config import settings

async def check_data():
    print("=== CONFIG / KEYS ===")
    print("GEMINI_API_KEY set:", bool(settings.GEMINI_API_KEY), "length:", len(settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else 0)
    print("GROQ_API_KEY set:", bool(settings.GROQ_API_KEY))
    print("ANTHROPIC_API_KEY set:", bool(settings.ANTHROPIC_API_KEY))
    print("DEEPSEEK_API_KEY set:", bool(settings.DEEPSEEK_API_KEY))
    print("MISTRAL_API_KEY set:", bool(settings.MISTRAL_API_KEY))
    
    async with AsyncSessionLocal() as db:
        print("\n=== CONVERSATION THREADS ===")
        threads = (await db.execute(select(ConversationThread))).scalars().all()
        print("Total conversation threads:", len(threads))
        for t in threads[:10]:
            content_preview = (t.content or "").replace("\n", " ")[:60]
            print(f" - ID: {t.id} | dir: {t.direction} | intent: {t.intent} | event: {t.event_type} | subj: {t.subject} | content: {content_preview}")
            
        print("\n=== DEALS & OBJECTIONS / TRANSCRIPTS ===")
        deals = (await db.execute(select(Deal))).scalars().all()
        print("Total deals:", len(deals))
        for d in deals[:10]:
            print(f" - Deal: {d.name} | Stage: {d.stage} | objections: {d.objections} | risk_flags: {d.risk_flags}")
            
        print("\n=== FUNNEL EVENTS (Transcripts/etc) ===")
        events = (await db.execute(select(FunnelEvent))).scalars().all()
        print("Total funnel events:", len(events))
        transcript_events = [e for e in events if "transcript" in e.event_type.lower()]
        print("Transcript-related events:", len(transcript_events))
        for te in transcript_events[:5]:
            print(f" - Event: {te.event_type} | meta: {te.event_metadata}")
            
        print("\n=== CONTACTS ===")
        contacts = (await db.execute(select(Contact))).scalars().all()
        print("Total contacts:", len(contacts))
        
        print("\n=== GENERATED CONTENT ===")
        contents = (await db.execute(select(GeneratedContent))).scalars().all()
        print("Total generated content pieces:", len(contents))

if __name__ == "__main__":
    asyncio.run(check_data())
