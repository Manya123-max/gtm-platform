"""
Database Backfill & Signal Recalibration Script:
1. Removes false-positive signals:
   - Website fingerprint signals with only generic utilities (Google Tag Manager, etc.) and no enterprise CRM/sales tools.
   - Generic noun / conference collisions (SAM Summit Series, RAISE Summit, Brand Affinity, Affinity Groups, mall jobs).
2. Recalibrates legitimate website fingerprint confidence:
   - 0.55 for 2+ enterprise sales tools (e.g. HubSpot + Apollo.io).
   - 0.40 for 1 enterprise sales tool (e.g. HubSpot).
3. Recomputes Contact signal fields (signal_score, signal_type, latest_signal_at) based strictly on remaining legitimate signals.
"""
import asyncio
from datetime import datetime
from sqlalchemy import select, delete
from app.core.database import AsyncSessionLocal
from app.models.models import Contact, SignalEvent
from app.agents.a2_signal import SignalAgent, SignalType


async def main(dry_run: bool = False):
    print(f"--- Starting Signal Recalibration (dry_run={dry_run}) ---")
    async with AsyncSessionLocal() as db:
        # 1. Inspect website_fingerprint signals
        wf_res = await db.execute(select(SignalEvent).where(SignalEvent.signal_source == "website_fingerprint"))
        wf_events = wf_res.scalars().all()
        
        deleted_ids = set()
        deleted_count = 0
        recalibrated_count = 0
        
        for e in wf_events:
            raw = e.raw_data or {}
            techs = raw.get("technologies") or []
            enterprise = [t for t in techs if t in SignalAgent.ENTERPRISE_SALES_CRM_TOOLS]
            
            if not enterprise:
                print(f"DELETING false-positive website fingerprint {e.id} (techs={techs})")
                deleted_ids.add(e.id)
                deleted_count += 1
            else:
                new_conf = 0.55 if len(enterprise) >= 2 else 0.40
                if e.confidence != new_conf:
                    print(f"RECALIBRATING {e.id}: {e.confidence} -> {new_conf} (enterprise={enterprise})")
                    e.confidence = new_conf
                    e.conversion_weight = new_conf
                    raw["technologies"] = enterprise
                    raw["tech_count"] = len(enterprise)
                    e.raw_data = raw
                    recalibrated_count += 1

        # 2. Inspect headline-based and job-based signals for false positives
        all_sig_res = await db.execute(select(SignalEvent))
        all_signals = all_sig_res.scalars().all()
        
        for e in all_signals:
            if e.id in deleted_ids or e.signal_source == "website_fingerprint":
                continue
                
            c = await db.get(Contact, e.contact_id)
            if not c:
                continue
                
            raw = e.raw_data or {}
            headline = raw.get("headline") or ""
            
            should_delete = False
            reason = ""
            
            # Check Adzuna job postings
            if e.signal_source == "adzuna":
                # Check if company was Summit and job was mall / street address
                if (c.company or "").lower() == "summit":
                    if "summit sierra" in headline.lower() or "summit dr" in headline.lower() or "summit st" in headline.lower():
                        should_delete = True
                        reason = f"Adzuna mall/address collision for Summit: {headline}"
                elif (c.company or "").lower() in ["on", "on services"]:
                    if "radiologic" in headline.lower() or "technologist" in headline.lower():
                        should_delete = True
                        reason = f"Adzuna unrelated medical tech job for ON Services: {headline}"
                elif "seasonal sales associate" in headline.lower() and "affinity" in (c.company or "").lower():
                    should_delete = True
                    reason = f"Adzuna retail job for Affinity: {headline}"

            # Check news headlines
            if e.signal_source in ["google_news_rss", "currents", "newsapi"]:
                agent = SignalAgent(db)
                clean_comp = agent._clean_company_name(c.company)
                if not SignalAgent._is_headline_relevant(headline, clean_comp, c.company):
                    should_delete = True
                    reason = f"Headline irrelevant / generic collision for {c.company}: {headline}"

            if should_delete:
                print(f"DELETING false-positive signal {e.id} ({reason})")
                deleted_ids.add(e.id)
                deleted_count += 1

        if not dry_run and deleted_ids:
            from sqlalchemy import text
            id_list = list(deleted_ids)
            await db.execute(
                text("UPDATE outreach_drafts SET signal_id = NULL WHERE signal_id::text = ANY(:s_ids)"),
                {"s_ids": id_list}
            )
            await db.execute(
                text("UPDATE outreach_log SET signal_id = NULL WHERE signal_id::text = ANY(:s_ids)"),
                {"s_ids": id_list}
            )
            for d_id in deleted_ids:
                d_sig = await db.get(SignalEvent, d_id)
                if d_sig:
                    await db.delete(d_sig)
            await db.flush()

        # 3. Recompute contact signal fields
        contacts_res = await db.execute(select(Contact))
        contacts = contacts_res.scalars().all()
        
        contacts_updated = 0
        for c in contacts:
            c_sigs_res = await db.execute(
                select(SignalEvent).where(SignalEvent.contact_id == c.id)
            )
            c_sigs = [s for s in c_sigs_res.scalars().all() if s.id not in deleted_ids]
            
            old_score = c.signal_score
            old_type = c.signal_type
            old_latest = c.latest_signal_at
            
            if not c_sigs:
                c.signal_score = None
                c.signal_type = None
                c.latest_signal_at = None
                c.signal_summary = None
            else:
                best_sig = max(c_sigs, key=lambda s: s.confidence)
                c.signal_score = round(best_sig.confidence * 100, 1)
                sig_types = sorted(list(set(s.signal_type for s in c_sigs)))
                c.signal_type = ",".join(sig_types)
                c.latest_signal_at = max(s.detected_at for s in c_sigs if s.detected_at)
                
            if c.signal_score != old_score or c.signal_type != old_type or c.latest_signal_at != old_latest:
                print(f"UPDATED Contact {c.company} ({c.first_name} {c.last_name}): "
                      f"score: {old_score} -> {c.signal_score}, "
                      f"type: {old_type} -> {c.signal_type}, "
                      f"latest_at: {old_latest} -> {c.latest_signal_at}")
                contacts_updated += 1

        if not dry_run:
            await db.commit()
            print("Database transaction COMMITTED successfully.")
        else:
            await db.rollback()
            print("Dry run complete (no changes committed).")

        print(f"Summary: deleted={deleted_count}, recalibrated={recalibrated_count}, contacts_updated={contacts_updated}")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    asyncio.run(main(dry_run=dry))
