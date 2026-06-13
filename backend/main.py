from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException
from psycopg import IntegrityError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import load_settings
from backend.db import (
    create_source,
    delete_source,
    dismiss_inbox_entry,
    initialize_database,
    list_active_inbox_entries,
    list_sources,
    mark_inbox_entry_read,
    rate_inbox_entry,
    update_source,
)
from backend.scheduler import start as start_scheduler
from backend.scheduler import stop as stop_scheduler
from backend.services.calendar import fetch_schedule_for_date
from backend.services.pipeline import run_daily_pipeline
from backend.telemetry import setup_telemetry


settings = load_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_telemetry(settings.service_name)
    initialize_database(settings)
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


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


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


@app.get("/api/sources")
def sources() -> list[dict]:
    return list_sources(settings)


@app.get("/api/schedule/today")
def todays_schedule(date_value: date | None = None) -> dict:
    return fetch_schedule_for_date(settings, date_value)


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
