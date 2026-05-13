import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from app.database import engine
from app.services import rule_executor

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


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        _hourly_rules_job,
        CronTrigger(minute=0),
        id="hourly_rules",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info("APScheduler started (hourly_rules at minute=0)")
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
