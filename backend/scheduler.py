from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from backend.config import Settings


scheduler = BackgroundScheduler()
logger = logging.getLogger(__name__)


def start(settings: Settings, job) -> None:
    if scheduler.running:
        logger.info("Scheduler already running; startup skipped")
        return

    if settings.schedule_timezone.lower() != "local":
        scheduler.configure(timezone=settings.schedule_timezone)
    scheduler.add_job(
        job,
        "cron",
        hour=settings.schedule_hour,
        minute=settings.schedule_minute,
        id="daily-briefing-job",
        replace_existing=True,
    )
    scheduler.start()
    scheduled_job = scheduler.get_job("daily-briefing-job")
    logger.info(
        "Scheduler started: daily briefing at %02d:%02d (%s); next run: %s",
        settings.schedule_hour,
        settings.schedule_minute,
        settings.schedule_timezone,
        scheduled_job.next_run_time if scheduled_job else "unknown",
    )


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
