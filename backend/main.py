from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from psycopg import IntegrityError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import load_settings
from backend.db import (
    create_source,
    delete_source,
    dismiss_inbox_entry,
    list_active_inbox_entries,
    list_apple_health_workouts,
    list_glucose_readings,
    list_nutrition_events,
    list_sources,
    mark_inbox_entry_read,
    search_inbox_entries,
    rate_inbox_entry,
    update_source,
)
from backend.scheduler import start as start_scheduler
from backend.scheduler import stop as stop_scheduler
from backend.services.calendar import fetch_schedule_for_date
from backend.services.day import fetch_calendar_day_for_date
from backend.services.health import (
    create_glucose_entry,
    create_nutrition_entry,
    import_apple_health_workouts,
    import_glucose_csv,
    remove_apple_health_workout,
    remove_glucose_entry,
    remove_nutrition_entry,
    update_nutrition_entry,
)
from backend.services.pipeline import run_daily_pipeline
from backend.telemetry import setup_telemetry


settings = load_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_telemetry(settings.service_name)
    start_scheduler(settings, lambda: run_daily_pipeline(settings))
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_title, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.frontend_dir)), name="static")


class RatingRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


class SourceRequest(BaseModel):
    name: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    feed_url: str = Field(min_length=1)
    adapter_type: str = Field(min_length=1, default="rss")
    source_weight: int = Field(default=1, ge=0)
    enabled: bool = True


class NutritionEventRequest(BaseModel):
    timestamp: datetime
    meal_name: str | None = None
    est_carbs_g: float | None = None
    est_protein_g: float | None = None
    est_fat_g: float | None = None
    comments: str | None = None
    is_buffer_meal: bool = False


class GlucoseReadingRequest(BaseModel):
    timestamp: datetime | None = None
    glucose_mgdl: int = Field(gt=0)
    source_device: str | None = None


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def _normalize_nutrition_request(request: NutritionEventRequest) -> dict:
    return {
        "timestamp": request.timestamp,
        "meal_name": _normalize_optional_text(request.meal_name),
        "est_carbs_g": request.est_carbs_g,
        "est_protein_g": request.est_protein_g,
        "est_fat_g": request.est_fat_g,
        "comments": _normalize_optional_text(request.comments),
        "is_buffer_meal": request.is_buffer_meal,
    }


def _normalize_glucose_request(request: GlucoseReadingRequest) -> dict:
    return {
        "timestamp": request.timestamp or datetime.now().astimezone(),
        "glucose_mgdl": request.glucose_mgdl,
        "source_device": _normalize_optional_text(request.source_device) or "FreeStyle Libre",
    }


def _day_window(selected_date: date) -> tuple[datetime, datetime]:
    start_at = datetime.combine(selected_date, datetime.min.time()).astimezone()
    return start_at, start_at + timedelta(days=1)


def _normalize_source_request(request: SourceRequest) -> dict:
    tags = []
    seen = set()
    for tag in request.tags:
        normalized = tag.strip()
        if normalized and normalized.lower() not in seen:
            tags.append(normalized)
            seen.add(normalized.lower())

    return {
        "name": request.name.strip(),
        "tags": tags,
        "feed_url": request.feed_url.strip(),
        "adapter_type": request.adapter_type.strip(),
        "source_weight": request.source_weight,
        "enabled": request.enabled,
    }


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(settings.frontend_dir / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/inbox")
def inbox() -> list[dict]:
    return list_active_inbox_entries(settings)


@app.get("/api/inbox/search")
def inbox_search(
    q: str | None = None,
    source: str | None = None,
    label: str | None = None,
    rating: int | None = Query(default=None, ge=1, le=5),
    sort: str = "recent",
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict]:
    normalized_sort = sort if sort in {"recent", "rank"} else "recent"
    return search_inbox_entries(
        settings,
        query=_normalize_optional_text(q),
        source=_normalize_optional_text(source),
        label=_normalize_optional_text(label),
        rating=rating,
        sort=normalized_sort,
        limit=limit,
    )


@app.get("/api/sources")
def sources() -> list[dict]:
    return list_sources(settings)


@app.get("/api/schedule/today")
def todays_schedule(date_value: date | None = None) -> dict:
    return fetch_schedule_for_date(settings, date_value)


@app.get("/api/nutrition-events")
def nutrition_events(date_value: date | None = None) -> list[dict]:
    selected_date = date_value or date.today()
    start_at, end_at = _day_window(selected_date)
    return list_nutrition_events(settings, start_at, end_at)


@app.post("/api/nutrition-events")
def create_nutrition_event(request: NutritionEventRequest) -> dict:
    return create_nutrition_entry(settings, **_normalize_nutrition_request(request))


@app.put("/api/nutrition-events/{event_id}")
def update_nutrition_event_route(event_id: int, request: NutritionEventRequest) -> dict | None:
    return update_nutrition_entry(settings, event_id, **_normalize_nutrition_request(request))


@app.delete("/api/nutrition-events/{event_id}")
def delete_nutrition_event_route(event_id: int) -> dict | None:
    return remove_nutrition_entry(settings, event_id)


@app.get("/api/glucose")
def glucose_readings(date_value: date | None = None) -> list[dict]:
    selected_date = date_value or date.today()
    start_at, end_at = _day_window(selected_date)
    return list_glucose_readings(settings, start_at, end_at)


@app.post("/api/glucose")
def create_glucose_reading(request: GlucoseReadingRequest) -> dict:
    payload = _normalize_glucose_request(request)
    create_glucose_entry(settings, **payload)
    return {
        "timestamp": payload["timestamp"],
        "glucose_mgdl": payload["glucose_mgdl"],
        "source_device": payload["source_device"],
    }


@app.post("/api/glucose/import")
async def import_glucose_readings_route(
    file: UploadFile = File(...),
) -> dict:
    payload = await file.read()
    try:
        return import_glucose_csv(
            settings,
            file_name=file.filename or "",
            file_bytes=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/glucose/{timestamp}")
def delete_glucose_reading_route(timestamp: str) -> dict | None:
    return remove_glucose_entry(settings, datetime.fromisoformat(timestamp))


@app.get("/api/apple-health-workouts")
def apple_health_workouts(date_value: date | None = None) -> list[dict]:
    selected_date = date_value or date.today()
    start_at, end_at = _day_window(selected_date)
    return list_apple_health_workouts(settings, start_at, end_at)


@app.post("/api/apple-health-workouts/import")
async def import_apple_health_workouts_route(file: UploadFile = File(...)) -> dict:
    payload = await file.read()
    try:
        return import_apple_health_workouts(
            settings,
            file_name=file.filename or "",
            file_bytes=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/apple-health-workouts/{workout_id}")
def delete_apple_health_workout_route(workout_id: int) -> dict | None:
    return remove_apple_health_workout(settings, workout_id)


@app.get("/api/calendar/day")
def calendar_day(date_value: date | None = None) -> dict:
    return fetch_calendar_day_for_date(settings, date_value)


@app.post("/api/sources")
def create_source_route(request: SourceRequest) -> dict:
    try:
        return create_source(settings, **_normalize_source_request(request))
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Source feed URL already exists") from exc


@app.put("/api/sources/{source_id}")
def update_source_route(source_id: str, request: SourceRequest) -> dict:
    try:
        source = update_source(settings, source_id, **_normalize_source_request(request))
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Source feed URL already exists") from exc

    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    return source


@app.delete("/api/sources/{source_id}")
def delete_source_route(source_id: str) -> dict:
    source = delete_source(settings, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@app.post("/api/inbox/{entry_id}/dismiss")
def dismiss(entry_id: int) -> dict:
    entry = dismiss_inbox_entry(settings, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return entry


@app.post("/api/inbox/{entry_id}/read")
def mark_read(entry_id: int) -> dict:
    entry = mark_inbox_entry_read(settings, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return entry


@app.post("/api/inbox/{entry_id}/rate")
def rate(entry_id: int, request: RatingRequest) -> dict:
    entry = rate_inbox_entry(settings, entry_id, request.rating)
    if entry is None:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return entry


@app.post("/api/jobs/run-now")
def run_now() -> dict[str, int]:
    return run_daily_pipeline(settings)
