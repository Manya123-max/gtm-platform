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
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        if self.FRONTEND_URL and self.FRONTEND_URL.strip() and self.FRONTEND_URL.strip() not in origins:
            origins.append(self.FRONTEND_URL.strip())
        return origins

    def validate_production_readiness(self) -> List[str]:
        """Validate production configuration and return a list of blocker messages."""
        errors: List[str] = []
        is_prod = self.APP_ENV.lower() in {"prod", "production"} or not self.DEBUG
        if is_prod:
            if not self.APP_SECRET_KEY or self.APP_SECRET_KEY == "change-me":
                errors.append("APP_SECRET_KEY must be set to a secure secret in production (cannot be 'change-me')")
            if not self.DATABASE_URL or "localhost" in self.DATABASE_URL:
                errors.append("DATABASE_URL must point to a production database, not localhost")
            if self.AUTH_ENABLED and not (self.JWT_SECRET_KEY or (self.APP_SECRET_KEY and self.APP_SECRET_KEY != "change-me")):
                errors.append("JWT_SECRET_KEY or a secure APP_SECRET_KEY is required when AUTH_ENABLED=True")
        return errors

    # ── Auth ──────────────────────────────────────────────────────────────────
    AUTH_ENABLED: bool = True          # false = legacy unauthenticated dev mode
    JWT_SECRET_KEY: str = ""           # falls back to APP_SECRET_KEY when empty
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # Legacy data backfill: email of the user that pre-migration (anonymous)
    # records are assigned to. Empty = never silently assign ownership.
    GTM_MIGRATION_OWNER_EMAIL: str = ""
    # Optional initial/sync password for the migration owner account.
    GTM_MIGRATION_OWNER_PASSWORD: Optional[str] = None


    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://gtm:gtmpass@localhost:5432/gtm_platform"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str]) -> str:
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = v.replace("postgres://", "postgresql+asyncpg://", 1)
            elif v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
                v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
            if "sslmode=require" in v:
                v = v.replace("sslmode=require", "ssl=require")
            elif "sslmode=prefer" in v:
                v = v.replace("sslmode=prefer", "ssl=prefer")
            elif "sslmode=disable" in v:
                v = v.replace("sslmode=disable", "")
            return v
        return v or ""

    @property
    def sync_database_url(self) -> str:
        url = self.DATABASE_URL.replace("+asyncpg", "")
        if "ssl=require" in url:
            url = url.replace("ssl=require", "sslmode=require")
        elif "ssl=prefer" in url:
            url = url.replace("ssl=prefer", "sslmode=prefer")
        return url

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

    # ── Salesforce CRM (Sole CRM Integration) ─────────────────────────────
    SALESFORCE_INSTANCE_URL:  Optional[str] = None
    SALESFORCE_ACCESS_TOKEN:  Optional[str] = None
    SALESFORCE_CLIENT_ID:     Optional[str] = None
    SALESFORCE_CLIENT_SECRET: Optional[str] = None
    SALESFORCE_API_VERSION:   str = "v60.0"

    # Deprecated HubSpot setting (kept as None for legacy compatibility)
    HUBSPOT_ACCESS_TOKEN:     Optional[str] = None

    # ── Google Workspace Integration (Domain-Wide Delegation & OAuth) ──────
    GOOGLE_CLIENT_ID:          Optional[str] = None
    GOOGLE_CLIENT_SECRET:      Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/integrations/google/callback"
    GOOGLE_WORKSPACE_DWD_ENABLED: bool = False
    GOOGLE_WORKSPACE_SERVICE_ACCOUNT_EMAIL: Optional[str] = None
    GOOGLE_WORKSPACE_SERVICE_ACCOUNT_KEY: Optional[str] = None
    GOOGLE_WORKSPACE_DOMAIN: Optional[str] = None
    GOOGLE_WORKSPACE_ADMIN_EMAIL: Optional[str] = None
    GMAIL_CLIENT_ID:      str = ""
    GMAIL_CLIENT_SECRET:  str = ""
    GMAIL_REDIRECT_URI:   str = "http://localhost:8000/api/v1/auth/gmail/callback"

    # Microsoft 365 / Microsoft Graph (Production Company Email)
    MICROSOFT_CLIENT_ID:          Optional[str] = None
    MICROSOFT_CLIENT_SECRET:      Optional[str] = None
    MICROSOFT_TENANT_ID:          Optional[str] = "common"
    MICROSOFT_REDIRECT_URI:       str = "http://localhost:8000/api/v1/integrations/microsoft/callback"
    MICROSOFT_AUTHORITY:          str = "https://login.microsoftonline.com"
    MICROSOFT_GRAPH_ENDPOINT:     str = "https://graph.microsoft.com/v1.0"
    MICROSOFT_SCOPES:             str = "offline_access User.Read Mail.Send Mail.Read"
    COMPANY_PRODUCTION_EMAIL:     str = "shree.lakshmi@forcecloudlabs.com"


    # ── Cal.com Settings & Automated Resolution ────────────────────────────
    CAL_COM_API_KEY:            str = ""
    CAL_COM_BASE_URL:           str = "https://api.cal.com/v2"
    CAL_COM_API_VERSION:        str = "2024-06-14"
    CAL_COM_EVENT_SLUG:         str = ""
    CAL_COM_ORG_SLUG:           Optional[str] = None
    CAL_COM_DEFAULT_EVENT_SLUG: Optional[str] = "15min"
    CAL_COM_USER_MAPPINGS:      Optional[str] = '{"shree.lakshmi@forcecloudlabs.com": {"username": "shree-lakshmi-iaqqsz", "event_slug": "15min", "booking_url": "https://cal.com/shree-lakshmi-iaqqsz/15min"}}'

    # ── Outreach delivery ─────────────────────────────────────────────────
    RESEND_API_KEY:        str  = ""
    RESEND_FROM_EMAIL:     str  = "gtm@yourdomain.com"
    FIREFLIES_API_KEY:     str  = ""
    INSTANTLY_API_KEY:     str  = ""
    INSTANTLY_BASE_URL:    str  = "https://api.instantly.ai"
    INSTANTLY_CAMPAIGN_ID: str  = ""

    # ── Notifications ─────────────────────────────────────────────────────
    # Deal ownership & notifications
    DEAL_OWNER_EMAIL:       Optional[str] = None
    NOTIFICATION_EMAIL:     Optional[str] = None

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

    A5_SIMULATION_MODE: bool = False  # Production: False. When False, never generate synthetic Fireflies transcripts or fake BANT.
    AGENT3_TEST_MODE: bool = False
    TEST_MODE_ICP_SCORE_THRESHOLD: int = 60
    TEST_EMAIL_OVERRIDE: Optional[str] = None  # In production: None. For test mode: set in .env

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
    A6_CONTENT_FORMATS:          str = "linkedin_post,email_sequence,case_study,blog_article,sales_deck_outline"
    A6_MAX_BRIEFS:               int = 3
    RSS_FEED_URLS:               str = ""
    GOOGLE_NEWS_QUERIES:         str = ""
    A6_GOOGLE_NEWS_QUERIES:      str = ""
    A6_RSS_FEEDS:                str = ""
    A6_NEWS_MAX_RESULTS:         int = 5
    A6_REDDIT_MAX_RESULTS:       int = 5
    A6_GOOGLE_NEWS_MAX_RESULTS:  int = 5
    A6_RSS_MAX_RESULTS_PER_FEED: int = 5
    A6_RELEVANCE_KEYWORDS:       str = "Salesforce, CRM, AI, AI agents, RAG, automation, sales automation, enterprise AI, B2B, cloud, data integration, customer service, lead generation, sales intelligence"



@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()