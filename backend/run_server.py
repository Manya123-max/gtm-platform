#!/usr/bin/env python3
"""
Production Process Supervisor for GTM Platform on Render Free Plan.
Runs:
1. Safe database baseline reconciliation and migrations (blocks until success).
2. Celery Worker (concurrency: 1, listening on: default, agents, webhooks).
3. FastAPI / Uvicorn server (bound to 0.0.0.0:${PORT:-8000}).

Guarantees:
- Never starts Celery or Uvicorn if migration fails or schema does not match baseline.
- Single container operation without requiring paid background workers.
- Graceful shutdown handling for SIGTERM/SIGINT without orphan processes.
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


def log(msg: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [SUPERVISOR] {msg}", flush=True)


def handle_shutdown_signal(signum, frame):
    global SHUTTING_DOWN
    if SHUTTING_DOWN:
        return
    SHUTTING_DOWN = True
    sig_name = signal.Signals(signum).name if signum else "SHUTDOWN"
    log(f"Received {sig_name}. Initiating graceful termination of all services...")

    # Forward termination signal to all child processes
    for name, proc in list(CHILD_PROCESSES.items()):
        if proc.poll() is None:
            log(f"Sending termination signal to {name} (PID: {proc.pid})...")
            try:
                # Uvicorn responds immediately to SIGINT; Celery to SIGTERM
                proc.send_signal(signal.SIGINT if "uvicorn" in name else signal.SIGTERM)
            except ProcessLookupError:
                pass

    # Wait up to 5 seconds for graceful exit
    deadline = time.time() + 5.0
    for name, proc in list(CHILD_PROCESSES.items()):
        remaining = max(0.1, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
            log(f"Process {name} exited cleanly with code {proc.returncode}.")
        except subprocess.TimeoutExpired:
            log(f"Process {name} did not exit within timeout. Sending SIGKILL...")
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    log("All child processes terminated. Exiting supervisor.")
    sys.exit(0)


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


def main():
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)

    log("Starting GTM Platform single-container environment on Render Free tier...")

    # 1. Step 1: Run migration and baseline verification FIRST
    # If this fails, the process exits immediately with code 1
    run_database_migrations_or_abort()

    port = os.environ.get("PORT", "8000")
    # Concurrency 1 is optimal for Render Free (512MB RAM, shared CPU)
    concurrency = os.environ.get("CELERY_CONCURRENCY", "1")
    log_level = os.environ.get("LOG_LEVEL", "info")

    # 2. Step 2: Spawn Celery Worker ONLY after migration succeeds
    celery_cmd = [
        sys.executable, "-m", "celery",
        "-A", "app.core.celery_app.celery_app",
        "worker",
        f"--loglevel={log_level}",
        "-Q", "default,agents,webhooks",
        f"--concurrency={concurrency}",
        "--without-gossip",
        "--without-mingle",
    ]
    log(f"Spawning Celery Worker (concurrency={concurrency}, queues=default,agents,webhooks)...")
    celery_proc = subprocess.Popen(celery_cmd, cwd=str(backend_dir))
    CHILD_PROCESSES["celery-worker"] = celery_proc
    log(f"Celery Worker started (PID: {celery_proc.pid}).")

    # 3. Step 3: Spawn Uvicorn Web Server ONLY after migration succeeds
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

    # 4. Step 4: Supervisory Health Loop
    while not SHUTTING_DOWN:
        for name, proc in list(CHILD_PROCESSES.items()):
            poll_code = proc.poll()
            if poll_code is not None:
                log(f"CRITICAL: Managed service '{name}' died unexpectedly with exit code {poll_code}.")
                # If either service crashes, terminate remaining services and exit
                handle_shutdown_signal(signal.SIGTERM, None)
                sys.exit(poll_code or 1)
        time.sleep(2)


if __name__ == "__main__":
    main()
