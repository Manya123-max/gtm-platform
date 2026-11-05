import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def sync_schema():
    from app.core.database import engine, Base
    from sqlalchemy import text
    from app.models import models  # load all models

    async with engine.begin() as conn:
        # Create all tables if missing
        await conn.run_sync(Base.metadata.create_all)
        
        # Specific known alter statements
        queries = [
            # user_inputs
            "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS our_company_name TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS our_services TEXT;",
            "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS target_location VARCHAR(200);",
            "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS target_industries TEXT;",
            "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS target_company_size VARCHAR(50);",
            "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS target_keywords TEXT;",
            "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS target_job_titles TEXT;",
            "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();",

            # signal_events
            "ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS sequence_step INTEGER DEFAULT 0;",
            "ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS next_step_due_at TIMESTAMP WITHOUT TIME ZONE;",
            
            # conversation_threads
            "ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS rejected_by VARCHAR(100);",
            "ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP WITHOUT TIME ZONE;",
            "ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS rejection_reason TEXT;",
            
            # contacts
            "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS user_input_id INTEGER REFERENCES user_inputs(id);",
            "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS win_pattern_score FLOAT;",
            
            # deals
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS objections JSONB;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS deal_health_score FLOAT;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS win_probability FLOAT;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS buying_intent VARCHAR(50);",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS next_best_action TEXT;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS stage_confidence FLOAT;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS budget_confirmed BOOLEAN;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS authority_confirmed BOOLEAN;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS need_confirmed BOOLEAN;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS timeline_confirmed BOOLEAN;",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS outcome VARCHAR(20);",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS lost_reason VARCHAR(300);",
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS stage_entered_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();",
        ]
        
        for q in queries:
            try:
                await conn.execute(text(q))
            except Exception as e:
                print(f"Warning on query '{q}': {e}")
                
    print("Comprehensive schema sync completed successfully!")

if __name__ == "__main__":
    asyncio.run(sync_schema())
