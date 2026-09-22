"""App-wide settings loaded from .env.

Subscription tier notes (as of July 2026):
- Claude AI     : paid subscription → use claude-sonnet-4-6 / claude-haiku-4-5
- Apollo.io     : Organization tier → higher credit pool, advanced filters,
                  bulk enrichment, CSV export, sequence automation
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from functools import lru_cache
from typing import List, Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── App ───────────────────────────────────────────────────────────────
    APP_ENV:        str  = "development"
    APP_SECRET_KEY: str  = "change-me"
    DEBUG:          bool = True
    FRONTEND_URL:   str  = "http://localhost:3000"
    CORS_ORIGINS:   str  = "http://localhost:3000,http://localhost:8000"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str) and value.lower() in {"release", "prod", "production"}:
            return False
        return value

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    # ── Auth ──────────────────────────────────────────────────────────────────
    AUTH_ENABLED: bool = True          # false = legacy unauthenticated dev mode
    JWT_SECRET_KEY: str = ""           # falls back to APP_SECRET_KEY when empty
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # Legacy data backfill: email of the user that pre-migration (anonymous)
    # records are assigned to. Empty = never silently assign ownership.
    GTM_MIGRATION_OWNER_EMAIL: str = ""


    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://gtm:gtmpass@localhost:5432/gtm_platform"

    @property
    def sync_database_url(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "")

    # ── Redis / Celery ────────────────────────────────────────────────────
    REDIS_URL:              str = "redis://localhost:6379/0"
    CELERY_BROKER_URL:      str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND:  str = "redis://redis:6379/2"

    # ── LLM providers — fallback chain: Groq → Gemini → Mistral → DeepSeek → Claude ──
    ANTHROPIC_API_KEY: str = ""
    GROQ_API_KEY:      str = ""
    GEMINI_API_KEY:    str = ""
    MISTRAL_API_KEY:   str = ""
    DEEPSEEK_API_KEY:  str = ""
    JINA_API_KEY:      str = ""
    USE_GROQ:          bool = False
    EMBEDDING_MODEL:   str = "hash"   # "hash" = zero deps; "miniLM" = sentence-transformers

    # ── Apollo.io (Organization tier) ────────────────────────────────────
    APOLLO_API_KEY:               str = ""
    APOLLO_MAX_SEARCH_PAGES:      int = 10   # Max pages ceiling for safety
    APOLLO_SEARCH_MAX_PAGES:      int = 10   # Backward-compatible alias
    APOLLO_SEARCH_PER_PAGE:       int = 100  # Number of stubs per Apollo search page
    APOLLO_CANDIDATE_POOL_SIZE:   int = 150  # Target candidate pool size before enrichment
    APOLLO_ENRICH_LIMIT:          int = 25   # Default number of final qualified prospects / enrichment limit
    APOLLO_INCLUDE_SIMILAR_TITLES: bool = False # Default strict title matching

    # ── News / job signals ────────────────────────────────────────────────
    NEWS_API_KEY:           str = ""
    ADZUNA_APP_ID:          str = ""
    ADZUNA_API_KEY:         str = ""
    APIFY_API_TOKEN:        str = ""
    PREDICTLEADS_API_KEY:   str = ""
    PREDICTLEADS_API_TOKEN: str = ""
    CURRENTS_API_KEY:       str = ""

    # ── CRM / calendar / email ────────────────────────────────────────────
    HUBSPOT_ACCESS_TOKEN:      str = ""
    SALESFORCE_USERNAME:       str = ""
    SALESFORCE_PASSWORD:       str = ""
    SALESFORCE_CLIENT_ID:      str = ""
    SALESFORCE_CLIENT_SECRET:  str = ""
    SALESFORCE_SECURITY_TOKEN: str = ""
    SALESFORCE_REFRESH_TOKEN:  str = ""
    SALESFORCE_DOMAIN:         str = "login"  # 'login' for Production, 'test' for Sandbox
    GMAIL_CLIENT_ID:           str = ""
    GMAIL_CLIENT_SECRET:  str = ""
    GMAIL_REDIRECT_URI:   str = "http://localhost:8000/api/v1/auth/gmail/callback"
    CAL_COM_API_KEY:      str = ""
    CAL_COM_BASE_URL:     str = "https://api.cal.com/v2"
    CAL_COM_API_VERSION:  str = "2024-06-14"
    CAL_COM_EVENT_SLUG:   str = ""

    # ── Outreach delivery ─────────────────────────────────────────────────
    RESEND_API_KEY:        str  = ""
    RESEND_FROM_EMAIL:     str  = "gtm@yourdomain.com"
    FIREFLIES_API_KEY:     str  = ""
    INSTANTLY_API_KEY:     str  = ""
    INSTANTLY_BASE_URL:    str  = "https://api.instantly.ai"
    INSTANTLY_CAMPAIGN_ID: str  = ""

    # ── Notifications ─────────────────────────────────────────────────────
    NOTIFICATION_PROVIDER:  str = "ntfy"
    NTFY_BASE_URL:          str = "https://ntfy.sh"
    NTFY_APPROVAL_TOPIC:    str = ""
    NTFY_ALERTS_TOPIC:      str = ""
    SLACK_BOT_TOKEN:        str = ""
    SLACK_SIGNING_SECRET:   str = ""
    SLACK_APPROVAL_CHANNEL: str = "gtm-approvals"
    SLACK_ALERTS_CHANNEL:   str = "gtm-alerts"

    # ── Webhook secrets ───────────────────────────────────────────────────
    INBOUND_WEBHOOK_SECRET:   str = ""
    FIREFLIES_WEBHOOK_SECRET: str = ""

    # ── Feature flags ─────────────────────────────────────────────────────
    # With a paid Claude + Apollo subscription you can safely enable live ops.
    # Keep DRY_RUN_OUTREACH=true until you have verified your Instantly
    # campaign and Resend domain — then flip it to false in .env.
    ENABLE_EMAIL_SENDING:      bool = False   # set True when Resend domain verified
    ENABLE_INSTANTLY:          bool = False   # set True when Instantly campaign ready
    DRY_RUN_OUTREACH:          bool = True    # SAFETY: flip to false only after testing
    REQUIRE_HUMAN_APPROVAL:    bool = True    # keep True — Slack/ntfy approval gate
    ENABLE_SLACK_APPROVALS:    bool = False   # ntfy is the default; flip for Slack
    ALLOW_DEMO_PROSPECTS:      bool = False   # production: False

    AGENT3_TEST_MODE: bool = False
    TEST_MODE_ICP_SCORE_THRESHOLD: int = 60
    TEST_EMAIL_OVERRIDE: Optional[str] = "ibmsuriya@gmail.com"

    # ── SMTP / Gmail ──────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""

    # ── Scoring thresholds ────────────────────────────────────────────────
    ICP_SCORE_THRESHOLD:                  int  = 70
    SIGNAL_SCORE_THRESHOLD:               int  = 40

    # A3 outreach tuning (previously hardcoded in a3_outreach.py)
    SONNET_ICP_SCORE_THRESHOLD:           int  = 85    # use Sonnet instead of Haiku above this score
    OUTREACH_GLOBAL_COOLDOWN_DAYS:        int  = 5     # min days between a contact's FIRST touch on different signals
    OUTREACH_VARIANT_EXPLORATION_RATE:    float = 0.15 # epsilon-greedy: fraction of sends to a random active variant
    READINESS_SCORE_MEETING_THRESHOLD:    int  = 60
    EMAIL_DEDUP_DAYS:                     int  = 60
    SIGNAL_DEDUP_HOURS:                   int  = 24
    CONTENT_DEDUP_HOURS:                  int  = 24
    ALLOW_REPEAT_OUTREACH_FOR_NEW_SIGNAL: bool = True

    # ── Celery beat schedules (NO inline comments allowed in values) ───────
    PROSPECT_AGENT_SCHEDULE: str = "0 8 * * 1"
    SIGNAL_AGENT_SCHEDULE:   str = "0 * * * *"
    CONTENT_AGENT_SCHEDULE:  str = "0 9 * * 2"
    REVENUE_AGENT_SCHEDULE:  str = "0 2 * * *"

    # ── Content Agent Settings ────────────────────────────────────────────
    A6_CONTENT_FORMATS:      str = "linkedin_post,email_sequence,case_study,blog_article,sales_deck_outline"
    A6_MAX_BRIEFS:           int = 3



@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()