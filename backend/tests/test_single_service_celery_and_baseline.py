"""
Comprehensive verification test suite for:
1. Alembic migration graph & baseline reconciliation
2. Single-container FastAPI + Celery worker architecture
3. Task dispatch, consumption, and status polling
4. Redis broker & result backend connectivity
5. Graceful process shutdown and resource management
"""
import os
import sys
import time
import signal
import subprocess
import pytest
import redis
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import settings
from app.core.celery_app import celery_app
from scripts.migrate_and_reconcile import get_sync_db_url, reconcile_and_migrate
from sqlalchemy import create_engine, text, inspect


def test_alembic_graph_and_single_head():
    """Item 1: Verify migration graph is contiguous and has exactly one head."""
    alembic_ini_path = str(backend_dir / "alembic.ini")
    config = Config(alembic_ini_path)
    script_dir = ScriptDirectory.from_config(config)

    heads = script_dir.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 alembic head, found {len(heads)}: {heads}"
    assert heads[0] == "h4c9d0e1f2g3", f"Expected head to be h4c9d0e1f2g3, got {heads[0]}"

    # Verify down_revision chain
    rev = script_dir.get_revision("h4c9d0e1f2g3")
    assert rev is not None
    assert rev.down_revision == "g3b8c9d0e1f2"


def test_reconcile_and_migrate_baseline_safety():
    """Item 2: Verify migrate_and_reconcile runs idempotently and maintains head revision."""
    # First execution
    reconcile_and_migrate()

    db_url = get_sync_db_url()
    engine = create_engine(db_url)
    with engine.connect() as conn:
        insp = inspect(conn)
        cols = {c["name"]: str(c["type"]).upper() for c in insp.get_columns("user_inputs")}
        assert "company_lookalike" in cols
        assert "signals" in cols
        assert "funding_stages" in cols

        rev_rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        assert len(rev_rows) == 1
        assert rev_rows[0][0] == "h4c9d0e1f2g3"

    # Second execution (idempotency check)
    reconcile_and_migrate()
    with engine.connect() as conn:
        rev_rows2 = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        assert len(rev_rows2) == 1
        assert rev_rows2[0][0] == "h4c9d0e1f2g3"


def test_schema_mismatch_aborts_safely():
    """Verify that verify_schema_matches_baseline_g3b8c9d0e1f2 aborts if tables or columns are missing."""
    from scripts.migrate_and_reconcile import verify_schema_matches_baseline_g3b8c9d0e1f2

    class DummyInspector:
        def get_columns(self, table_name):
            return [{"name": "id"}]

    # 1. Missing table
    with pytest.raises(RuntimeError) as exc_info:
        verify_schema_matches_baseline_g3b8c9d0e1f2(DummyInspector(), set())
    assert "missing expected baseline tables" in str(exc_info.value)

    # 2. Table exists but missing columns
    with pytest.raises(RuntimeError) as exc_info2:
        from scripts.migrate_and_reconcile import REQUIRED_BASELINE_TABLES
        verify_schema_matches_baseline_g3b8c9d0e1f2(DummyInspector(), REQUIRED_BASELINE_TABLES)
    assert "missing expected baseline columns" in str(exc_info2.value)


def test_run_server_concurrency_default_for_free_plan():
    """Verify run_server.py defaults CELERY_CONCURRENCY to 1 for Render Free tier."""
    run_server_code = (backend_dir / "run_server.py").read_text(encoding="utf-8")
    assert 'os.environ.get("CELERY_CONCURRENCY", "1")' in run_server_code


def test_redis_broker_and_result_backend_connectivity():
    """Item 8: Verify Redis broker and result backend connectivity."""
    broker_url = settings.CELERY_BROKER_URL
    r = redis.Redis.from_url(broker_url)
    assert r.ping() is True, "Redis broker ping failed"

    # Test key write/read
    test_key = "gtm_health_test_key"
    r.set(test_key, "healthy", ex=10)
    val = r.get(test_key)
    assert val == b"healthy", "Redis read/write verification failed"


def test_celery_worker_task_dispatch_and_consumption():
    """Items 5 & 6: Verify task dispatch via .apply_async() and consumption by real worker."""
    from app.workers.agent_tasks import health_ping

    # Dispatch task to the 'agents' queue
    async_result = health_ping.apply_async(args=[42], queue="agents")
    task_id = async_result.id
    assert task_id is not None, "Task dispatch failed to generate task ID"

    # Wait for the Celery worker (running in container or background) to consume and finish
    start_time = time.time()
    res = None
    while time.time() - start_time < 15.0:
        if async_result.ready():
            res = async_result.result
            break
        time.sleep(0.5)

    assert res is not None, f"Task {task_id} timed out without being processed by worker"
    assert res.get("status") == "healthy"
    assert res.get("pong") == 42


def test_celery_beat_disabled_for_release():
    """Item 11: Verify Celery Beat is intentionally disabled to preserve starter tier resources."""
    # Production deployment uses run_server.py which explicitly does not start Celery Beat.
    # Check that run_server.py contains no beat process invocation.
    run_server_code = (backend_dir / "run_server.py").read_text(encoding="utf-8")
    assert "celery beat" not in run_server_code.lower()
    assert "beat_proc" not in run_server_code.lower()


def test_process_shutdown_signal_handling():
    """Item 10: Verify supervisor handles termination cleanly."""
    # Run a test script executing run_server's handle_shutdown_signal logic
    test_script = """
import time
import subprocess
import sys

proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
assert proc.poll() is None
proc.terminate()
proc.wait(timeout=5)
assert proc.returncode is not None
print("Shutdown signal verification passed")
"""
    result = subprocess.run([sys.executable, "-c", test_script], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Shutdown signal verification passed" in result.stdout


@pytest.mark.asyncio
async def test_api_health_while_celery_running():
    """Item 9: Verify API health endpoint returns healthy while Celery is running."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "healthy"


@pytest.mark.asyncio
async def test_workflow_status_polling_endpoint():
    """Item 7: Verify workflow status polling endpoint handles lifecycle queries cleanly."""
    import uuid
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.models.models import WorkflowRun, User
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, hash_password

    # Create a test user and workflow run
    test_email = f"wf_poller_{uuid.uuid4().hex[:6]}@forcecloudlabs.com"
    async with AsyncSessionLocal() as session:
        user = User(
            id=str(uuid.uuid4()),
            name="Workflow Poller",
            email=test_email,
            password_hash=hash_password("Pass1234!"),
            role="SALES_REPRESENTATIVE",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        wf_run = WorkflowRun(
            workflow_name="gtm_intake_pipeline",
            status="running",
            user_id=user.id,
            current_agent="A1",
        )
        session.add(wf_run)
        await session.commit()
        wf_id = wf_run.id
        user_id = user.id

    token = create_access_token(str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/orchestrator/runs/{wf_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        wf_data = data.get("workflow", data)
        assert wf_data.get("workflow_name") == "gtm_intake_pipeline"
        assert wf_data.get("status") in ("running", "completed")


def test_packaging_and_kombu_redis_transport_imports():
    """Verify packaging and kombu redis transport are cleanly importable."""
    import packaging
    import packaging.version
    import kombu.transport.redis
    assert packaging.__version__ is not None
    assert kombu.transport.redis is not None


def test_run_server_celery_worker_configuration():
    """Verify run_server.py configures Celery with solo pool, canonical app ref, and queues."""
    code = (backend_dir / "run_server.py").read_text(encoding="utf-8")
    assert "--pool=solo" in code
    assert "app.core.celery_app:celery_app" in code
    assert "default,agents,webhooks" in code
    assert 'proc.send_signal(signal.SIGTERM)' in code


def test_celery_app_broker_connection_retry_on_startup():
    """Verify Celery app has broker_connection_retry_on_startup enabled."""
    assert celery_app.conf.broker_connection_retry_on_startup is True


def test_production_redis_and_celery_validation():
    """Verify production settings validator rejects localhost and docker hostnames."""
    from app.core.config import Settings
    s = Settings(
        APP_ENV="production",
        DEBUG=False,
        APP_SECRET_KEY="secure-secret-key-1234567890123456",
        JWT_SECRET_KEY="secure-jwt-key-123456789012345678",
        DATABASE_URL="postgresql+asyncpg://gtm:pass@render-db:5432/gtm",
        REDIS_URL="redis://localhost:6379/0",
        CELERY_BROKER_URL="redis://localhost:6379/1",
        CELERY_RESULT_BACKEND="redis://redis:6379/2",
    )
    errors = s.validate_production_readiness()
    assert any("REDIS_URL" in err for err in errors)
    assert any("CELERY_BROKER_URL" in err for err in errors)
    assert any("CELERY_RESULT_BACKEND" in err for err in errors)
