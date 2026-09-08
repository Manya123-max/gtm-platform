from celery import Celery
from celery.schedules import crontab
from app.core.config import settings
import structlog

logger = structlog.get_logger()


def _parse_crontab(cron_str: str) -> crontab:
    """
    Parse 5-part cron string safely.
    Strips inline comments before parsing — fixes the startup crash bug.
    """
    clean = cron_str.split('#')[0].strip()
    parts = clean.split()
    if len(parts) != 5:
        logger.warning("Bad cron string, defaulting to hourly", value=cron_str)
        return crontab(minute="0")
    minute, hour, dom, month, dow = parts
    kwargs = {"minute": minute, "hour": hour}
    if dom != "*":
        kwargs["day_of_month"] = dom
    if month != "*":
        kwargs["month_of_year"] = month
    if dow != "*":
        kwargs["day_of_week"] = dow
    return crontab(**kwargs)


celery_app = Celery(
    "gtm_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
    "app.workers.agent_tasks",
    "app.workers.webhook_tasks",
    "app.workers.scheduler_tasks",
    "app.workers.orchestrator_tasks",
   ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.agent_tasks.*":    {"queue": "agents"},
        "app.workers.webhook_tasks.*":  {"queue": "webhooks"},
        "app.workers.scheduler_tasks.*":{"queue": "default"},
        "app.workers.orchestrator_tasks.*":{"queue": "agents"},
    },
    beat_schedule={
        "dispatch-agent-schedules": {
            "task": "app.workers.scheduler_tasks.dispatch_agent_schedules",
            "schedule": crontab(minute="*"),
        },
        "poll-gmail-inbox-every-minute": {
            "task": "app.workers.scheduler_tasks.poll_gmail_inbox",
            "schedule": crontab(minute="*"),
        },
    },
)
