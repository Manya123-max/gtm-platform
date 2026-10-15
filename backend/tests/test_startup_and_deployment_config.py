"""
Targeted tests for startup, deployment configuration, and production readiness.
Ensures deployment misconfigurations on Render/Netlify are caught during CI/local checks.
"""
import os
import re
from pathlib import Path
import pytest
from app.core.config import Settings


def test_requirements_syntax_and_no_concatenations():
    """Verify that backend/requirements.txt contains no accidental package name concatenations."""
    req_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    assert req_path.exists(), "backend/requirements.txt must exist"

    lines = req_path.read_text(encoding="utf-8").splitlines()
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Detect multiple operators on a single line (unless compound version constraint like >=1.0,<2.0)
        # e.g. "psycopg2-binarygooglenewsdecoder==0.2.1"
        assert not re.search(r"[a-zA-Z0-9_-]+[a-zA-Z0-9_-]+==.*==.*", line), f"Line {idx} has duplicate '==' operators: {line}"
        
        # Detect suspicious compound names where a known library is mashed with another
        suspicious = ["psycopg2-binarygoogle", "fastapiuvicorn", "pydanticnumpy"]
        for s in suspicious:
            assert s not in line.lower(), f"Line {idx} contains suspicious concatenated package: {line}"


def test_production_readiness_validation():
    """Verify that Settings.validate_production_readiness catches missing production secrets."""
    # Case 1: Insecure secret in production
    prod_insecure = Settings(
        APP_ENV="production",
        DEBUG=False,
        APP_SECRET_KEY="change-me",
        DATABASE_URL="postgresql+asyncpg://user:pass@render-db:5432/gtm",
    )
    errors = prod_insecure.validate_production_readiness()
    assert any("APP_SECRET_KEY must be set to a secure secret" in err for err in errors)

    # Case 2: Localhost database in production
    prod_localhost_db = Settings(
        APP_ENV="production",
        DEBUG=False,
        APP_SECRET_KEY="a-very-secure-random-32-byte-hex-string-for-prod",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/gtm",
    )
    errors_db = prod_localhost_db.validate_production_readiness()
    assert any("DATABASE_URL must point to a production database" in err for err in errors_db)

    # Case 3: Valid production configuration passes with 0 errors
    prod_valid = Settings(
        APP_ENV="production",
        DEBUG=False,
        APP_SECRET_KEY="a-very-secure-random-32-byte-hex-string-for-prod",
        JWT_SECRET_KEY="a-very-secure-jwt-random-32-byte-hex-string",
        DATABASE_URL="postgresql+asyncpg://gtm_user:secret@dpg-abc123xyz.oregon-postgres.render.com/gtm",
        FRONTEND_URL="https://gtm-platform.netlify.app",
    )
    assert prod_valid.validate_production_readiness() == []


def test_sync_database_url_ssl_mode_conversion():
    """
    Render Postgres passes connection strings with ssl=require or sslmode=require.
    asyncpg expects ssl=require; psycopg2 expects sslmode=require.
    """
    settings = Settings(
        DATABASE_URL="postgresql://gtm_user:pass@dpg-abc.oregon-postgres.render.com/gtm?sslmode=require"
    )
    # Async connection has asyncpg driver and ssl=require
    assert "postgresql+asyncpg://" in settings.DATABASE_URL
    assert "ssl=require" in settings.DATABASE_URL

    # Sync connection for Alembic/psycopg2 has sslmode=require
    sync_url = settings.sync_database_url
    assert "+asyncpg" not in sync_url
    assert "sslmode=require" in sync_url
    assert "ssl=require" not in sync_url


def test_cors_origins_includes_frontend_url():
    """Verify that FRONTEND_URL is automatically added to CORS origins list."""
    settings = Settings(
        CORS_ORIGINS="http://localhost:3000,http://localhost:8000",
        FRONTEND_URL="https://custom-gtm-frontend.netlify.app",
    )
    origins = settings.cors_origins_list
    assert "https://custom-gtm-frontend.netlify.app" in origins
    assert "http://localhost:3000" in origins


def test_dockerfile_and_render_yaml_alignment():
    """Verify that Dockerfile exists and render.yaml points to backend/Dockerfile, not docker-compose.yml."""
    backend_dir = Path(__file__).resolve().parent.parent
    dockerfile = backend_dir / "Dockerfile"
    assert dockerfile.exists(), f"Dockerfile must exist at {dockerfile}"

    # If running in repo context where render.yaml is accessible
    repo_root = backend_dir.parent if (backend_dir.parent / "render.yaml").exists() else None
    if repo_root:
        render_yaml = repo_root / "render.yaml"
        render_content = render_yaml.read_text(encoding="utf-8")
        assert "docker-compose.yml" not in render_content, "render.yaml must not reference docker-compose.yml as a Dockerfile"
        assert "dockerfilePath: ./backend/Dockerfile" in render_content
        assert "dockerContext: ./backend" in render_content
