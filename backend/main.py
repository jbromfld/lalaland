from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from uuid import UUID
import logging
import asyncio

from fastapi import FastAPI, HTTPException, Query
from psycopg import IntegrityError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode
from backend.services.article_extraction import public_hostname

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
    try:
        await ensure_knowledge_schedule(app.state.temporal_client, settings)
    except Exception:
        logging.getLogger(__name__).exception('Optional knowledge schedule setup failed; core services remain available')
    try:
        yield
    finally:
        from opentelemetry import trace
        flush = getattr(trace.get_tracer_provider(), 'force_flush', None)
        if flush:
            flush()


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

    @field_validator('name', 'feed_url', mode='before')
    @classmethod
    def trimmed_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('feed_url')
    @classmethod
    def http_feed(cls, value):
        public_hostname(value)
        return value


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


@app.get('/api/features')
def features() -> dict[str, bool]:
    return {'knowledge': load_settings().knowledge_active}


@app.get("/api/inbox")
def inbox(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100)) -> dict:
    return list_active_inbox_entries(settings, page, limit)


@app.get("/api/history")
def history(
    days: int | None = Query(default=None, ge=1, le=3650),
    source: str | None = None,
    keyword: str | None = Query(default=None, max_length=200),
    rating: int | None = Query(default=None, ge=1, le=5),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    return search_inbox_history(
        settings,
        days=days,
        source=_normalize_optional_text(source),
        keyword=_normalize_optional_text(keyword),
        rating=rating, page=page, limit=limit,
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
def update_source_route(source_id: UUID, request: SourceRequest) -> dict:
    try:
        source = update_source(settings, source_id, **_normalize_source_request(request))
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Source feed URL already exists") from exc

    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    return source


@app.delete("/api/sources/{source_id}")
def delete_source_route(source_id: UUID) -> dict:
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


MANUAL_BRIEFING_ID = f'{DAILY_BRIEFING_WORKFLOW_ID}-manual'


@app.post('/api/jobs/run-now', status_code=202)
async def run_now() -> dict:
    try:
        async with asyncio.timeout(10):
            await app.state.temporal_client.start_workflow(
                DailyBriefingWorkflow.run, id=MANUAL_BRIEFING_ID, task_queue=TASK_QUEUE)
    except WorkflowAlreadyStartedError:
        return {'started': False, 'workflow_id': MANUAL_BRIEFING_ID, 'message': 'A daily pull is already running.'}
    except Exception as exc:
        raise HTTPException(503, 'Could not start the daily pull. Check Temporal and try again.') from exc
    return {'started': True, 'workflow_id': MANUAL_BRIEFING_ID,
            'message': 'Daily pull queued. Waiting for the worker to begin processing.'}


@app.get('/api/jobs/{workflow_id}')
async def job_status(workflow_id: str) -> dict:
    if workflow_id != MANUAL_BRIEFING_ID:
        raise HTTPException(404, 'Job not found')
    try:
        async with asyncio.timeout(10):
            handle = app.state.temporal_client.get_workflow_handle(workflow_id)
            description = await handle.describe()
            status = description.status
            result = None
            if status == WorkflowExecutionStatus.COMPLETED:
                completed = app.state.temporal_client.get_workflow_handle(workflow_id, run_id=description.run_id)
                result = asdict(await completed.result())
    except TimeoutError as exc:
        raise HTTPException(503, 'Job status timed out. Check Temporal and try again.') from exc
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            raise HTTPException(404, 'Job not found') from exc
        raise HTTPException(503, 'Job status is unavailable. Check Temporal and try again.') from exc
    except WorkflowFailureError as exc:
        raise HTTPException(503, 'Could not read the job result.') from exc
    return {'workflow_id':workflow_id, 'state':status.name.lower(), 'result':result,
            'message':'Queued or processing. If progress does not appear, check that the worker is running.'
                      if status == WorkflowExecutionStatus.RUNNING else None}
