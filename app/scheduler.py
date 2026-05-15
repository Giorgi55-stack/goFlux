import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session

from app.config import get_settings
from app.database import engine
from app.services import notion_sync, rule_executor

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _hourly_rules_job() -> None:
    logger.info("APScheduler: running rule execution job")
    try:
        with Session(engine) as session:
            summary = rule_executor.run_all_active_rules(session)
        logger.info("APScheduler: rule job summary %s", summary)
    except Exception:
        logger.exception("APScheduler: hourly rule job crashed")


def _notion_briefs_job() -> None:
    logger.info("APScheduler: polling Notion briefs")
    try:
        summary = notion_sync.process_ready_briefs()
        if summary.get("processed", 0) > 0:
            logger.info("APScheduler: notion sync summary %s", summary)
    except Exception:
        logger.exception("APScheduler: notion briefs job crashed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    settings = get_settings()
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        _hourly_rules_job,
        CronTrigger(minute=0),
        id="hourly_rules",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if settings.notion_api_key and settings.notion_database_id:
        sched.add_job(
            _notion_briefs_job,
            IntervalTrigger(minutes=settings.notion_poll_minutes),
            id="notion_briefs",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "APScheduler: notion_briefs polling every %dmin",
            settings.notion_poll_minutes,
        )
    else:
        logger.info(
            "APScheduler: notion_briefs job NOT registered (no NOTION_API_KEY/NOTION_DATABASE_ID)"
        )
    sched.start()
    _scheduler = sched
    logger.info("APScheduler started")
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    finally:
        _scheduler = None
    logger.info("APScheduler stopped")


def get_scheduler() -> Optional[BackgroundScheduler]:
    return _scheduler
