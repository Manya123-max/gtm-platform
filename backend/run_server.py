#!/usr/bin/env python3
"""
Production Process Supervisor for GTM Platform on Render Free Plan.
Runs:
1. Safe database baseline reconciliation and migrations (blocks until success).
2. Production configuration validation (aborts if missing/invalid production URLs).
3. Celery Worker (--pool=solo, concurrency: 1, listening on: default, agents, webhooks).
4. FastAPI / Uvicorn server (bound to 0.0.0.0:${PORT:-8000}).

Guarantees:
- Never starts Celery or Uvicorn if migration fails or schema does not match baseline.
- Never starts Celery or Uvicorn if production configuration validation fails.
- Single container operation without requiring paid background workers.
- Graceful shutdown handling for SIGTERM/SIGINT with independent parallel timeouts.
- Preserves child exit codes and reports failures honestly to container orchestrator.
"""
import os
import sys
import time
import signal
import subprocess
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

CHILD_PROCESSES = {}
SHUTTING_DOWN = False
EXIT_CODE = 0


def log(msg: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [SUPERVISOR] {msg}", flush=True)


def handle_shutdown(signum=None, frame=None, exit_code=0):
    global SHUTTING_DOWN, EXIT_CODE
    if SHUTTING_DOWN:
        return
    SHUTTING_DOWN = True
    if exit_code != 0 and EXIT_CODE == 0:
        EXIT_CODE = exit_code

    sig_name = signal.Signals(signum).name if signum else f"CODE_{EXIT_CODE}"
    log(f"Initiating graceful termination of all services (trigger: {sig_name}, target exit_code: {EXIT_CODE})...")

    # Step 1: Send SIGTERM to both child processes in parallel for graceful shutdown
    for name, proc in list(CHILD_PROCESSES.items()):
        if proc.poll() is None:
            log(f"Sending SIGTERM to {name} (PID: {proc.pid})...")
            try:
                proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    # Step 2: Parallel graceful shutdown allowance (up to 10 seconds total)
    # Both processes shut down concurrently without starving each other.
    deadline = time.time() + 10.0
    while time.time() < deadline:
        running = [name for name, proc in CHILD_PROCESSES.items() if proc.poll() is None]
        if not running:
            break
        time.sleep(0.2)

    # Step 3: Check status and force kill any lingering processes with SIGKILL
    for name, proc in list(CHILD_PROCESSES.items()):
        poll_code = proc.poll()
        if poll_code is not None:
            log(f"Process {name} exited with code {poll_code}.")
        else:
            log(f"Process {name} did not exit within timeout. Sending SIGKILL...")
            try:
                proc.kill()
                proc.wait(timeout=2.0)
                log(f"Process {name} killed.")
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass

    log(f"All child processes terminated. Supervisor exiting with code {EXIT_CODE}.")
    sys.exit(EXIT_CODE)


def handle_external_signal(signum, frame):
    """Callback for OS signals (SIGTERM from Render or SIGINT from Ctrl+C)."""
    handle_shutdown(signum=signum, frame=frame, exit_code=0)


def run_database_migrations_or_abort():
    """
    Executes database baseline reconciliation and migrations.
    FastAPI and Celery are NEVER started if this function fails or raises.
    """
    log("Executing startup database schema reconciliation and migrations...")
    from scripts.migrate_and_reconcile import reconcile_and_migrate
    try:
        reconcile_and_migrate()
        log("Database schema baseline reconciliation and migrations verified successfully.")
    except Exception as e:
        log(f"CRITICAL: Database migration/verification failed. Aborting startup: {e}")
        # Never start API or Celery against an invalid schema
        sys.exit(1)


def validate_config_or_abort():
    """
    Validates production configuration before launching services.
    Ensures Redis broker and database URLs are valid for production.
    """
    from app.core.config import settings
    prod_errors = settings.validate_production_readiness()
    is_prod = settings.APP_ENV.lower() in {"prod", "production"} or not settings.DEBUG
    if prod_errors and is_prod:
        log("CRITICAL: Production configuration validation failed:")
        for err in prod_errors:
            log(f"  - {err}")
        sys.exit(1)


def main():
    signal.signal(signal.SIGTERM, handle_external_signal)
    signal.signal(signal.SIGINT, handle_external_signal)

    log("Starting GTM Platform single-container environment on Render Free tier...")

    # Step 1: Run migration and baseline verification FIRST
    run_database_migrations_or_abort()

    # Step 2: Validate configuration (e.g. production Redis/Valkey endpoints)
    validate_config_or_abort()

    port = os.environ.get("PORT", "8000")
    # Concurrency 1 and solo pool are optimal for Render Free (512MB RAM, shared CPU)
    concurrency = os.environ.get("CELERY_CONCURRENCY", "1")
    log_level = os.environ.get("LOG_LEVEL", "info")

    # Step 3: Spawn Celery Worker with solo pool and canonical app ref
    celery_cmd = [
        sys.executable, "-m", "celery",
        "-A", "app.core.celery_app:celery_app",
        "worker",
        f"--loglevel={log_level}",
        "-Q", "default,agents,webhooks",
        "--pool=solo",
        f"--concurrency={concurrency}",
        "--without-gossip",
        "--without-mingle",
    ]
    log(f"Spawning Celery Worker (--pool=solo, concurrency={concurrency}, queues=default,agents,webhooks)...")
    celery_proc = subprocess.Popen(celery_cmd, cwd=str(backend_dir))
    CHILD_PROCESSES["celery-worker"] = celery_proc
    log(f"Celery Worker started (PID: {celery_proc.pid}).")

    # Step 4: Spawn Uvicorn Web Server
    uvicorn_cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        f"--log-level={log_level}",
    ]
    log(f"Spawning FastAPI / Uvicorn server on 0.0.0.0:{port}...")
    uvicorn_proc = subprocess.Popen(uvicorn_cmd, cwd=str(backend_dir))
    CHILD_PROCESSES["uvicorn-api"] = uvicorn_proc
    log(f"Uvicorn API server started (PID: {uvicorn_proc.pid}).")

    log("All services running. Entering supervisory health loop.")

    # Step 5: Supervisory Health Loop
    while not SHUTTING_DOWN:
        for name, proc in list(CHILD_PROCESSES.items()):
            poll_code = proc.poll()
            if poll_code is not None:
                log(f"CRITICAL: Managed service '{name}' died unexpectedly with exit code {poll_code}.")
                # Policy: an unexpectedly terminated service triggers immediate fail-safe shutdown
                # with non-zero exit code to alert Render rather than silently accepting requests.
                handle_shutdown(signum=None, frame=None, exit_code=poll_code or 1)
                return
        time.sleep(2)


if __name__ == "__main__":
    main()
