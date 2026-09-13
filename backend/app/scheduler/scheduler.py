"""APScheduler wiring — the "simplest" option the plan calls out in section 2
(vs. a full Airflow DAG), appropriate for a single daily job over 14
districts."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.scheduler.jobs import run_daily_refresh

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled via settings.scheduler_enabled")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_daily_refresh,
        trigger=CronTrigger(hour=settings.refresh_hour_utc, minute=0),
        id="daily_risk_refresh",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — daily refresh at %02d:00 UTC", settings.refresh_hour_utc)
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
