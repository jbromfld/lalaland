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


def fetch_todays_schedule(settings: Settings) -> dict:
    timezone = _resolve_timezone(settings.google_calendar_timezone)
    now = datetime.now(timezone)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    if not settings.google_calendar_ics_url:
        return {
            "configured": False,
            "date": today_start.date().isoformat(),
            "events": [],
        }

    parsed_events = calendar_events(
        url=settings.google_calendar_ics_url,
        start=today_start,
        end=tomorrow_start,
        tzinfo=timezone,
        sort=True,
    )

    return {
        "configured": True,
        "date": today_start.date().isoformat(),
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
