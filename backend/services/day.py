from __future__ import annotations

from datetime import date

from backend.config import Settings
from backend.services.calendar import fetch_schedule_for_date
from backend.services.health import fetch_health_day_for_date


def fetch_calendar_day_for_date(settings: Settings, target_date: date | None = None) -> dict:
    schedule = fetch_schedule_for_date(settings, target_date)
    selected_date = target_date or date.fromisoformat(schedule["date"])
    health = fetch_health_day_for_date(settings, selected_date)

    return {
        "configured": schedule["configured"],
        "date": schedule["date"],
        "events": schedule["events"],
        "health": health,
    }
