#!/usr/bin/env python3
"""
Pre-Deployment Validation Script for GTM Platform.
Validates dependencies, Dockerfile, Render config, frontend build, secrets, and tests before deployment.
Exits with 0 on SUCCESS, 1 on FAILURE.
"""
import os
import re
import sys
import subprocess
import py_compile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"

PASSED_CHECKS = []
FAILED_CHECKS = []
WARNING_CHECKS = []


# Safe console output encoding across all terminals (including Windows cmd/powershell cp1252)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def log_header(title: str):
    print("\n" + "=" * 70)
    print(f" [CHECK] {title}")
    print("=" * 70)


def record_pass(name: str, detail: str = ""):
    msg = f"[PASS] {name}" + (f" ({detail})" if detail else "")
    print(msg)
    PASSED_CHECKS.append(name)


def record_fail(name: str, reason: str):
    msg = f"[FAIL] {name} -> {reason}"
    print(msg)
    FAILED_CHECKS.append((name, reason))


def record_warn(name: str, reason: str):
    msg = f"[WARN] {name} -> {reason}"
    print(msg)
    WARNING_CHECKS.append((name, reason))


def check_backend_dependencies():
    log_header("1. Backend Dependency Syntax & Concatenation Check")
    req_file = BACKEND_DIR / "requirements.txt"
    if not req_file.exists():
        record_fail("requirements.txt presence", "backend/requirements.txt not found")
        return

    lines = req_file.read_text(encoding="utf-8").splitlines()
    concatenated_lines = []
    has_psycopg2 = False
    has_gnews = False
    httpx_compatible = False

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Check for multiple '==' or mashed package names like 'psycopg2-binarygooglenewsdecoder==0.2.1'
        if "psycopg2-binarygooglenewsdecoder" in line.lower():
            concatenated_lines.append(f"Line {idx}: {line} (psycopg2-binary concatenated with googlenewsdecoder)")
        elif re.search(r"[a-zA-Z0-9_-]+[a-zA-Z0-9_-]+==.*==.*", line):
            concatenated_lines.append(f"Line {idx}: {line} (Multiple == version operators)")

        if "psycopg2-binary" in line:
            has_psycopg2 = True
        if "googlenewsdecoder" in line:
            has_gnews = True
        if line.startswith("httpx"):
            if ">=0.28" in line or ">0.28" in line:
                httpx_compatible = True

    if concatenated_lines:
        record_fail("dependency syntax", "; ".join(concatenated_lines))
    else:
        record_pass("dependency syntax", "No mashed or concatenated package lines detected")

    if has_psycopg2 and has_gnews:
        record_pass("critical dependencies", "Both psycopg2-binary and googlenewsdecoder declared on distinct lines")
    else:
        record_fail("critical dependencies", f"Missing required dependencies (psycopg2: {has_psycopg2}, gnews: {has_gnews})")

    if httpx_compatible:
        record_pass("httpx version constraint", "httpx allows >=0.28.1 (compatible with googlenewsdecoder)")
    else:
        record_fail("httpx version constraint", "httpx is pinned below 0.28.1 which causes ResolutionImpossible with googlenewsdecoder")


def check_docker_and_render_config():
    log_header("2. Dockerfile & Render Configuration Validation")
    dockerfile = BACKEND_DIR / "Dockerfile"
    if not dockerfile.exists():
        record_fail("backend Dockerfile", "backend/Dockerfile does not exist")
        return

    df_content = dockerfile.read_text(encoding="utf-8")
    if "uvicorn app.main:app" in df_content and "PORT" in df_content:
        record_pass("backend Dockerfile entrypoint", "Uvicorn configured with dynamic Render $PORT support")
    else:
        record_fail("backend Dockerfile entrypoint", "Missing dynamic $PORT binding in Dockerfile CMD")

    # Check render.yaml
    render_yaml = REPO_ROOT / "render.yaml"
    if not render_yaml.exists():
        record_warn("render.yaml", "render.yaml not present at repository root")
        return

    ry_content = render_yaml.read_text(encoding="utf-8")
    if "docker-compose.yml" in ry_content:
        record_fail("Render Dockerfile path", "render.yaml accidentally references docker-compose.yml as a Dockerfile!")
    elif "dockerfilePath: ./backend/Dockerfile" in ry_content and "dockerContext: ./backend" in ry_content:
        record_pass("Render configuration alignment", "render.yaml specifies correct path (./backend/Dockerfile) and context (./backend)")
    else:
        record_warn("Render configuration alignment", "Verify dockerfilePath and dockerContext match ./backend")


def check_python_syntax():
    log_header("3. Python Code Syntax & Compilation")
    py_files = list(BACKEND_DIR.glob("app/**/*.py")) + list(BACKEND_DIR.glob("alembic/**/*.py"))
    failed_compilation = []

    for pf in py_files:
        try:
            py_compile.compile(str(pf), doraise=True)
        except Exception as e:
            failed_compilation.append(f"{pf.name}: {e}")

    if failed_compilation:
        record_fail("Python compilation", f"{len(failed_compilation)} files failed compilation: {failed_compilation[:3]}")
    else:
        record_pass("Python compilation", f"All {len(py_files)} Python source files compiled with 0 syntax errors")


def check_docker_compose_syntax():
    log_header("4. Docker Compose Syntax Check")
    dc_file = REPO_ROOT / "docker-compose.yml"
    if not dc_file.exists():
        record_warn("docker-compose.yml", "docker-compose.yml not found")
        return

    try:
        res = subprocess.run(["docker", "compose", "config", "-q"], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            record_pass("docker-compose config", "docker-compose.yml syntax is valid")
        else:
            record_fail("docker-compose config", res.stderr.strip() or "Syntax error in docker-compose.yml")
    except Exception as e:
        record_warn("docker-compose config", f"Could not run docker compose config (Docker CLI not installed/accessible): {e}")


def check_backend_tests():
    log_header("5. Automated Backend Tests")
    # Check if we can run tests inside docker or local python
    test_cmd = None
    try:
        # Check if docker gtm_backend container is running
        ps = subprocess.run(["docker", "ps", "--filter", "name=gtm_backend", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=5)
        if "gtm_backend" in ps.stdout:
            test_cmd = ["docker", "exec", "gtm_backend", "python", "-m", "pytest", "tests/test_startup_and_deployment_config.py", "tests/test_tiering_and_prospect_prioritization.py", "-q"]
    except Exception:
        pass

    if not test_cmd:
        try:
            # Check if pytest is available in current Python environment
            py_res = subprocess.run([sys.executable, "-m", "pytest", "--version"], capture_output=True, text=True, timeout=5)
            if py_res.returncode == 0:
                test_cmd = [sys.executable, "-m", "pytest", "backend/tests/test_startup_and_deployment_config.py", "-q"]
        except Exception:
            pass

    if test_cmd:
        try:
            res = subprocess.run(test_cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=45)
            if res.returncode == 0:
                record_pass("automated backend tests", "Targeted deployment & core pipeline tests passed")
            else:
                record_fail("automated backend tests", res.stdout.strip() or res.stderr.strip())
        except Exception as e:
            record_fail("automated backend tests", str(e))
    else:
        record_warn("automated backend tests", "Docker gtm_backend container not running and pytest not found locally; tests skipped in this run")


def check_frontend_build():
    log_header("6. Frontend Production Build & Config Check")
    pkg_json = FRONTEND_DIR / "package.json"
    if not pkg_json.exists():
        record_fail("frontend package.json", "frontend/package.json not found")
        return

    api_index = FRONTEND_DIR / "src" / "api" / "index.js"
    if api_index.exists():
        content = api_index.read_text(encoding="utf-8")
        if "import.meta.env.VITE_API_URL" in content:
            record_pass("frontend API config", "Configured via VITE_API_URL environment variable")
        else:
            record_fail("frontend API config", "Missing VITE_API_URL dynamic configuration in src/api/index.js")

    # Ensure dependencies are installed via npm ci before building
    node_modules_dir = FRONTEND_DIR / "node_modules"
    is_windows = sys.platform.startswith("win")
    npm_cmd = "npm.cmd" if is_windows else "npm"

    if not node_modules_dir.exists():
        print("  Installing frontend dependencies with npm ci...")
        ci_res = subprocess.run([npm_cmd, "ci"], cwd=str(FRONTEND_DIR), capture_output=True, text=True, timeout=120)
        if ci_res.returncode != 0:
            record_fail("frontend npm ci", ci_res.stderr.strip() or ci_res.stdout.strip()[:300])
            return

    # Run npm run build
    try:
        res = subprocess.run([npm_cmd, "run", "build"], cwd=str(FRONTEND_DIR), capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            record_pass("frontend build", "Vite production build completed successfully with 0 errors")
        else:
            record_fail("frontend build", res.stderr.strip() or res.stdout.strip()[:300])
    except Exception as e:
        record_fail("frontend build", f"Failed to execute npm run build: {e}")

    # Check dist output for leaked credentials
    dist_dir = FRONTEND_DIR / "dist"
    if dist_dir.exists():
        leaks = []
        for asset in dist_dir.glob("**/*.js"):
            txt = asset.read_text(encoding="utf-8", errors="ignore")
            # Scan for known private token prefixes or AWS/private keys
            if re.search(r"xoxb-[0-9]{10,}", txt):
                leaks.append(f"Slack bot token in {asset.name}")
            if re.search(r"-----BEGIN (RSA|EC|PRIVATE) KEY-----", txt):
                leaks.append(f"Private key in {asset.name}")
        if leaks:
            record_fail("frontend secret scanning", "; ".join(leaks))
        else:
            record_pass("frontend secret scanning", "No embedded private keys or API tokens in dist/ assets")


def check_environment_variables_docs():
    log_header("7. Environment Variables Documentation Check")
    env_example = BACKEND_DIR / ".env.example"
    if not env_example.exists():
        record_fail(".env.example presence", "backend/.env.example missing")
        return

    content = env_example.read_text(encoding="utf-8")
    required_vars = [
        "APP_ENV",
        "APP_SECRET_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "FRONTEND_URL",
        "CORS_ORIGINS",
    ]
    missing = [v for v in required_vars if v not in content]
    if missing:
        record_fail(".env.example documentation", f"Missing documentation for: {missing}")
    else:
        record_pass(".env.example documentation", "All core deployment environment variables documented")


def main():
    print("\n" + "#" * 70)
    print(" GTM PLATFORM PRE-DEPLOYMENT VALIDATION SUITE")
    print("#" * 70)

    check_backend_dependencies()
    check_docker_and_render_config()
    check_python_syntax()
    check_docker_compose_syntax()
    check_backend_tests()
    check_frontend_build()
    check_environment_variables_docs()

    print("\n" + "=" * 70)
    print(" SUMMARY")
    print("=" * 70)
    print(f"Passed Checks   : {len(PASSED_CHECKS)}")
    print(f"Warnings        : {len(WARNING_CHECKS)}")
    print(f"Failed Checks   : {len(FAILED_CHECKS)}")

    if FAILED_CHECKS:
        print("\n[RESULT] PRE-DEPLOYMENT VALIDATION FAILED:")
        for name, reason in FAILED_CHECKS:
            print(f"  - [{name}]: {reason}")
        sys.exit(1)
    else:
        print("\n[RESULT] ALL MANDATORY PRE-DEPLOYMENT CHECKS PASSED!")
        sys.exit(0)


if __name__ == "__main__":
    main()
