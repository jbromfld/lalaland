from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from icalevents.icalevents import events as calendar_events

from backend.config import Settings


def _resolve_timezone(name: str):
    if name.lower() == "local":
        return datetime.now().astimezone().tzinfo

    return ZoneInfo(name)


def _serialize_event_datetime(value, timezone) -> str | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.astimezone(timezone).isoformat()

    if isinstance(value, date):
        return datetime.combine(value, time.min, timezone).isoformat()

    return None


def fetch_schedule_for_date(settings: Settings, target_date: date | None = None) -> dict:
    timezone = _resolve_timezone(settings.google_calendar_timezone)
    selected_date = target_date or datetime.now(timezone).date()
    day_start = datetime.combine(selected_date, time.min, timezone)
    next_day_start = day_start + timedelta(days=1)

    if not settings.google_calendar_ics_url:
        return {
            "configured": False,
            "date": selected_date.isoformat(),
            "events": [],
        }

    parsed_events = calendar_events(
        url=settings.google_calendar_ics_url,
        start=day_start,
        end=next_day_start,
        tzinfo=timezone,
        sort=True,
    )

    return {
        "configured": True,
        "date": selected_date.isoformat(),
        "events": [
            {
                "title": event.summary or "Untitled event",
                "start": _serialize_event_datetime(event.start, timezone),
                "end": _serialize_event_datetime(event.end, timezone),
                "all_day": event.all_day,
                "location": event.location,
                "description": event.description,
                "url": event.url,
            }
            for event in parsed_events
        ],
    }


def fetch_todays_schedule(settings: Settings) -> dict:
    return fetch_schedule_for_date(settings)
