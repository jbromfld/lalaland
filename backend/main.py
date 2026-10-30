from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query
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
    list_history_sources,
    list_sources,
    mark_inbox_entry_read,
    rate_inbox_entry,
    search_inbox_history,
    update_source,
)
from backend.telemetry import setup_telemetry
from backend.temporal.client import DAILY_BRIEFING_WORKFLOW_ID, TASK_QUEUE, connect, ensure_daily_briefing_schedule, ensure_corpus_schedule, ensure_knowledge_schedule
from backend.temporal.workflows import DailyBriefingWorkflow


settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_telemetry(settings.service_name)
    initialize_database(settings)
    app.state.temporal_client = await connect()
    await ensure_daily_briefing_schedule(app.state.temporal_client, settings)
    await ensure_corpus_schedule(app.state.temporal_client, settings)
    await ensure_knowledge_schedule(app.state.temporal_client, settings)
    yield


app = FastAPI(title=settings.app_title, lifespan=lifespan)
from backend.corpus_api import router as corpus_router
app.include_router(corpus_router)
from backend.knowledge_api import router as knowledge_router
app.include_router(knowledge_router)
app.mount("/static", StaticFiles(directory=str(settings.frontend_dir)), name="static")


class RatingRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


class SourceRequest(BaseModel):
    name: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    feed_url: str = Field(min_length=1)
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
        "source_weight": request.source_weight,
        "enabled": request.enabled,
    }


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(settings.frontend_dir / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/inbox")
def inbox() -> list[dict]:
    return list_active_inbox_entries(settings)


@app.get("/api/history")
def history(
    days: int | None = Query(default=None, ge=1, le=3650),
    source: str | None = None,
    keyword: str | None = Query(default=None, max_length=200),
    rating: int | None = Query(default=None, ge=1, le=5),
) -> list[dict]:
    return search_inbox_history(
        settings,
        days=days,
        source=_normalize_optional_text(source),
        keyword=_normalize_optional_text(keyword),
        rating=rating,
    )


@app.get("/api/history/sources")
def history_sources() -> list[str]:
    return list_history_sources(settings)


@app.get("/api/sources")
def sources() -> list[dict]:
    return list_sources(settings)


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
async def run_now() -> dict[str, int]:
    result = await app.state.temporal_client.execute_workflow(
        DailyBriefingWorkflow.run,
        id=f"{DAILY_BRIEFING_WORKFLOW_ID}-manual-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}",
        task_queue=TASK_QUEUE,
    )
    return {
        "sources_processed": result.sources_processed,
        "entries_seen": result.entries_seen,
        "entries_created": result.entries_created,
    }
