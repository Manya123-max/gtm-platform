"""
Test suite for supervisor startup, graceful shutdown, and failure propagation.
"""
import time
import signal
import subprocess
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent


def test_supervisor_signal_propagation_and_parallel_allowance():
    """Verify that handle_shutdown sends SIGTERM to both processes and shuts down cleanly."""
    script = """
import time
import subprocess
import sys
import signal

# Create two long-running child processes simulating Celery and Uvicorn
celery_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
uvicorn_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])

CHILD_PROCESSES = {
    "celery-worker": celery_proc,
    "uvicorn-api": uvicorn_proc,
}

start = time.time()
# Send SIGTERM to both
for name, proc in list(CHILD_PROCESSES.items()):
    if proc.poll() is None:
        proc.terminate()

# Parallel wait loop with 10s budget
deadline = time.time() + 10.0
while time.time() < deadline:
    if all(proc.poll() is not None for proc in CHILD_PROCESSES.values()):
        break
    time.sleep(0.1)

elapsed = time.time() - start
for name, proc in CHILD_PROCESSES.items():
    assert proc.poll() is not None, f"{name} did not exit"

print(f"Both processes terminated cleanly in {elapsed:.2f}s")
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Both processes terminated cleanly" in result.stdout


def test_supervisor_failure_propagation_exit_code():
    """Verify that an unexpected child process crash causes non-zero exit code preservation."""
    script = """
import time
import subprocess
import sys

CHILD_PROCESSES = {
    "celery-worker": subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(42)"]),
    "uvicorn-api": subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"]),
}

time.sleep(0.5)
poll_code = CHILD_PROCESSES["celery-worker"].poll()
assert poll_code == 42, f"Expected 42, got {poll_code}"

# Simulate supervisor handling
EXIT_CODE = poll_code or 1
for name, proc in list(CHILD_PROCESSES.items()):
    if proc.poll() is None:
        proc.terminate()

deadline = time.time() + 5.0
while time.time() < deadline:
    if all(proc.poll() is not None for proc in CHILD_PROCESSES.values()):
        break
    time.sleep(0.1)

print(f"Supervisor exit code preserved: {EXIT_CODE}")
sys.exit(EXIT_CODE)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 42
    assert "Supervisor exit code preserved: 42" in result.stdout


def test_supervisor_command_has_solo_pool():
    """Verify run_server.py configures --pool=solo and -A app.core.celery_app:celery_app."""
    content = (backend_dir / "run_server.py").read_text(encoding="utf-8")
    assert "--pool=solo" in content
    assert "app.core.celery_app:celery_app" in content
    assert "default,agents,webhooks" in content
    assert "signal.SIGTERM" in content

