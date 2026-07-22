4CECloud Labs — GTM Multi-Agent Platform
> **7-Agent Engine** · FastAPI + Celery · React + Vite · PostgreSQL + Redis
---
What's in the update package
File	Why it changed
`frontend/src/index.css`	4CECloud Labs brand palette (deep navy + electric blue + cyan)
`frontend/src/components/layout/Layout.jsx`	4CE wordmark logo, branded nav, fixed `useLocation` hook placement
`frontend/nginx.conf`	Root cause of non-interactivity fixed — added `proxy_read_timeout 180s` so long agent runs don't get killed by nginx
`backend/app/services/llm_service.py`	Updated Sonnet model to `claude-sonnet-4-6`; httpx timeout raised to 60 s
`backend/app/core/config.py`	Apollo `APOLLO_SEARCH_MAX_PAGES` raised 10 → 25 for Org tier
`backend/.env.example`	Updated template with paid-subscription notes and step-by-step flags guide

Prerequisites
Tool	Version
Docker + Docker Compose	≥ 24
Node.js (for frontend rebuild only)	≥ 20
Python	3.11+

Quick Start — Docker Compose (recommended)
1. Drop the updated files into place
```
gtm-final/
├── backend/
│   ├── app/
│   │   ├── core/config.py           ← replace
│   │   └── services/llm_service.py  ← replace
│   ├── .env.example                 ← replace (then copy → .env)
│   └── .env                         ← your secrets (create from example)
└── frontend/
    ├── nginx.conf                   ← replace
    └── src/
        ├── index.css                ← replace
        └── components/
            └── layout/Layout.jsx   ← replace
```
2. Set environment variables
```bash
cd gtm-final/backend
cp .env.example .env
# Open .env and fill in:
#   ANTHROPIC_API_KEY  ← from console.anthropic.com
#   APOLLO_API_KEY     ← from app.apollo.io → Settings → Integrations → API
```
3. Rebuild the frontend (required after CSS/JSX changes)
```bash
cd gtm-final/frontend
npm install          # only needed if node_modules is missing
npm run build        # produces dist/ — nginx serves this
```
4. Start all services
```bash
cd gtm-final
docker compose up --build -d
```
Services started:
`db`       → PostgreSQL on port 5432
`redis`    → Redis on port 6379
`backend`  → FastAPI on port 8000
`worker`   → Celery worker
`beat`     → Celery beat scheduler
`frontend` → Nginx serving React on http://localhost:3000
5. Run database migrations
```bash
docker compose exec backend alembic upgrade head
```
6. (Optional) Seed demo data
```bash
docker compose exec backend python scripts/seed.py
```
7. Open the platform
```
http://localhost:3000
```
---
Local Dev (without Docker)
Backend
```bash
cd gtm-final/backend

# Create and activate venv
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install deps
pip install -r requirements.txt

# Set env
cp .env.example .env             # edit with your keys

# Start PostgreSQL + Redis (either local installs or quick docker)
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=gtmpass -e POSTGRES_USER=gtm -e POSTGRES_DB=gtm_platform postgres:16
docker run -d -p 6379:6379 redis:7

# Run migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --reload --port 8000

# In a second terminal: start Celery worker
celery -A app.core.celery_app worker --loglevel=info

# In a third terminal: start Celery beat (optional — enables scheduled agents)
celery -A app.core.celery_app beat --loglevel=info
```
Frontend
```bash
cd gtm-final/frontend
npm install
npm run dev          # Vite dev server on http://localhost:3000
                     # proxies /api → localhost:8000 automatically
```
---
Enabling live outreach (step-by-step)
The platform defaults to dry-run mode. Turn on live sending only when ready:
Step 1 — Run A1 + A2 to populate contacts and signals. Review them in the UI.
Step 2 — Verify Resend domain
```bash
# In backend/.env:
RESEND_FROM_EMAIL=gtm@your-verified-domain.com
ENABLE_EMAIL_SENDING=true
```
Step 3 — Connect Instantly campaign
```bash
INSTANTLY_CAMPAIGN_ID=your-campaign-id
ENABLE_INSTANTLY=true
```
Step 4 — Run A3 in approval mode (`DRY_RUN_OUTREACH=true`, `REQUIRE_HUMAN_APPROVAL=true`).
Approve ≥ 5 emails via ntfy or Slack. Confirm delivery in Resend dashboard.
Step 5 — Go live
```bash
DRY_RUN_OUTREACH=false
```

Apollo Organization Tier — what you get
Setting	Free	Organization
`APOLLO_SEARCH_MAX_PAGES`	10	25 (now default)
Export credits/month	50	~10 000
Bulk enrichment	✗	✓
Sequence automation	✗	✓
No code changes needed — A1 already calls bulk enrichment when it's available.
The increased page limit is set automatically via `config.py`.

Claude model reference
Agent task	Model used
Scoring, classification (A1, A2)	`claude-haiku-4-5-20251001`
Email drafting (A3), Content (A6)	`claude-sonnet-4-6` (`use_sonnet=True`)
Deal analysis (A5), Forecast narrative (A7)	`claude-sonnet-4-6`

Stopping services
```bash
docker compose down             # stop containers, keep volumes
docker compose down -v          # stop + wipe database (full reset)
```
---
Troubleshooting
Frontend buttons don't respond after an agent run
→ Fixed by the `nginx.conf` change (proxy timeout was 60 s default; agent runs take up to 120 s). Rebuild and redeploy with the new nginx.conf.
`ANTHROPIC_API_KEY is not set` error in backend logs
→ Make sure `backend/.env` (not `.env.example`) contains your key, and restart: `docker compose restart backend worker`.
`apollo` returns 0 contacts
→ Check `APOLLO_API_KEY` is set. If on Organization tier, credits reset monthly — check usage at app.apollo.io.
Database migration errors on first run
→ Run `docker compose exec backend alembic upgrade head` after the db container is healthy (wait ~10 s after `docker compose up`).
