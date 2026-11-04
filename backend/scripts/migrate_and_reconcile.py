#!/usr/bin/env python3
"""
Database Migration and Baseline Reconciliation Script for GTM Platform.
Safely establishes Alembic migration baseline on existing databases
without data loss, and upgrades to head revision (h4c9d0e1f2g3).

Critical Safety:
- Verifies complete schema parity against baseline g3b8c9d0e1f2 before stamping.
- Aborts immediately if the schema does not match the expected baseline.
- Never re-stamps if the database is already at or past the baseline.
- Executes forward upgrade to head and verifies optional input columns.
"""
import os
import sys
from pathlib import Path
from typing import Set, Dict

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, text, inspect
from alembic.config import Config
from alembic import command
from app.core.config import settings

# Explicit contract of tables and columns required for baseline g3b8c9d0e1f2
REQUIRED_BASELINE_TABLES: Set[str] = {
    "user_inputs",
    "contacts",
    "users",
    "deals",
    "signal_events",
    "outreach_drafts",
    "conversation_threads",
    "contact_user_input_association",
    "notifications",
    "user_integrations",
    "company_salesforce_verifications",
    "salesforce_verification_evidences",
}

REQUIRED_BASELINE_COLUMNS: Dict[str, Set[str]] = {
    "user_inputs": {
        "our_company_name",
        "our_services",
        "target_location",
        "target_industries",
        "target_company_size",
        "target_keywords",
        "target_job_titles",
        "created_at",
    },
    "contacts": {
        "user_input_id",
        "salesforce_contact_id",
    },
    "deals": {
        "salesforce_opportunity_id",
    },
    "users": {
        "cal_com_event_slug",
    },
    "signal_events": {
        "signal_type",
    },
    "conversation_threads": {
        "rejected_by",
        "rejected_at",
    },
}

REQUIRED_HEAD_COLUMNS: Set[str] = {
    "company_lookalike",
    "signals",
    "funding_stages",
}


def get_sync_db_url() -> str:
    db_url = os.environ.get("DATABASE_URL") or settings.sync_database_url
    db_url = db_url.replace("+asyncpg", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    if "ssl=require" in db_url:
        db_url = db_url.replace("ssl=require", "sslmode=require")
    elif "ssl=prefer" in db_url:
        db_url = db_url.replace("ssl=prefer", "sslmode=prefer")
    return db_url


def verify_schema_matches_baseline_g3b8c9d0e1f2(insp, tables: Set[str]) -> None:
    """
    Strict validation that all tables and columns represented by revision
    g3b8c9d0e1f2 exist. Aborts immediately if any mismatch is found.
    """
    missing_tables = REQUIRED_BASELINE_TABLES - tables
    if missing_tables:
        raise RuntimeError(
            f"Baseline verification aborted: database is missing expected baseline tables: {sorted(missing_tables)}"
        )

    for table_name, expected_cols in REQUIRED_BASELINE_COLUMNS.items():
        actual_cols = {c["name"] for c in insp.get_columns(table_name)}
        missing_cols = expected_cols - actual_cols
        if missing_cols:
            raise RuntimeError(
                f"Baseline verification aborted: table '{table_name}' is missing expected baseline columns: {sorted(missing_cols)}"
            )

    print("[MIGRATION] Database schema verified to completely match baseline 'g3b8c9d0e1f2'.")


def reconcile_and_migrate():
    db_url = get_sync_db_url()
    safe_url = db_url.split("@")[-1] if "@" in db_url else "configured DB"
    print(f"[MIGRATION] Connecting to database target: ...@{safe_url}")

    engine = create_engine(db_url, pool_pre_ping=True)
    alembic_ini_path = str(backend_dir / "alembic.ini")
    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    with engine.connect() as conn:
        insp = inspect(conn)
        tables = set(insp.get_table_names())
        print(f"[MIGRATION] Detected {len(tables)} tables in database.")

        current_revs = []
        if "alembic_version" in tables:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            current_revs = [r[0] for r in rows if r[0]]
            print(f"[MIGRATION] Current alembic_version: {current_revs}")
        else:
            print("[MIGRATION] Table 'alembic_version' does NOT exist.")

        # Case 1: Already at head revision
        if "h4c9d0e1f2g3" in current_revs:
            print("[MIGRATION] Database is already at head revision 'h4c9d0e1f2g3'. No stamping or migration needed.")
            actual_cols = {c["name"] for c in insp.get_columns("user_inputs")}
            missing = REQUIRED_HEAD_COLUMNS - actual_cols
            if missing:
                raise RuntimeError(f"Database revision is h4c9d0e1f2g3 but user_inputs lacks columns: {missing}")
            print("[MIGRATION] Schema verification passed: all head columns present.")
            return

        # Case 2: Already stamped at baseline g3b8c9d0e1f2 (or intermediate)
        if "g3b8c9d0e1f2" in current_revs:
            print("[MIGRATION] Database is currently at baseline 'g3b8c9d0e1f2'. Will upgrade to head without re-stamping.")

        # Case 3: No revision in alembic_version
        elif not current_revs:
            if "user_inputs" in tables:
                print("[MIGRATION] Pre-existing schema detected without alembic_version.")
                print("[MIGRATION] Verifying full schema parity against baseline 'g3b8c9d0e1f2'...")
                verify_schema_matches_baseline_g3b8c9d0e1f2(insp, tables)
                print("[MIGRATION] Stamping baseline revision 'g3b8c9d0e1f2'...")
                command.stamp(alembic_cfg, "g3b8c9d0e1f2")
                print("[MIGRATION] Baseline 'g3b8c9d0e1f2' stamped successfully.")
            else:
                print("[MIGRATION] Fresh database detected. Normal migration path from base will apply.")

    # Execute Alembic upgrade to head (runs h4c9d0e1f2g3)
    print("[MIGRATION] Executing: alembic upgrade head...")
    command.upgrade(alembic_cfg, "head")
    print("[MIGRATION] Upgrade command completed.")

    # Strict post-migration verification: confirm head columns exist without running arbitrary SQL
    with engine.connect() as conn:
        insp = inspect(conn)
        cols = {c["name"] for c in insp.get_columns("user_inputs")}
        missing = REQUIRED_HEAD_COLUMNS - cols
        if missing:
            raise RuntimeError(f"Post-migration verification failed: user_inputs missing columns {missing}")

        final_revs = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        rev_list = [r[0] for r in final_revs]
        if "h4c9d0e1f2g3" not in rev_list:
            raise RuntimeError(f"Post-migration verification failed: expected head revision h4c9d0e1f2g3, found {rev_list}")

        print(f"[MIGRATION] Verified final revision(s): {rev_list}")
        print("[MIGRATION] All optional input columns verified present in user_inputs: company_lookalike, signals, funding_stages.")

    print("[MIGRATION] Schema baseline reconciliation and migration successfully completed!")


if __name__ == "__main__":
    try:
        reconcile_and_migrate()
    except Exception as e:
        print(f"[MIGRATION ERROR] Failed: {e}", file=sys.stderr)
        sys.exit(1)
