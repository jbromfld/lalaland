from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from backend.config import Settings


scheduler = BackgroundScheduler()


def start(settings: Settings, job) -> None:
    if scheduler.running:
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


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
