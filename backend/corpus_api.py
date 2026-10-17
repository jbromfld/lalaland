import requests
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from backend.config import load_settings
from backend.services import corpus_store as store
from backend.services.article_extraction import canonical_article_url, validate_url, require_trusted, UntrustedDomain
from backend.services.corpus_summary import installed_models
from backend.temporal.corpus import CorpusBatchWorkflow
from backend.temporal.client import TASK_QUEUE
from temporalio.exceptions import WorkflowAlreadyStartedError

router = APIRouter()


class Submission(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=200)


class Retry(BaseModel):
    model: str | None = Field(default=None, min_length=1, max_length=200)


class RatingRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


def resolve_model(model):
    settings = load_settings()
    if model is None:
        return settings.corpus_model
    try:
        models = installed_models(settings)
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise HTTPException(503, 'Could not validate model: Ollama model discovery unavailable') from exc
    if model not in models:
        raise HTTPException(422, 'Selected model is not installed on the configured Ollama server')
    return model


@router.get('/api/ollama/models')
def models():
    settings = load_settings()
    try:
        installed = installed_models(settings)
        warning = None if settings.corpus_model in installed else 'Configured default model is not installed. Select an installed text-generation model or install the default in Ollama.'
        return {'default_model':settings.corpus_model, 'models':installed, 'error':None, 'warning':warning}
    except (requests.RequestException, ValueError, KeyError):
        return {'default_model':settings.corpus_model, 'models':[], 'error':'Ollama model discovery unavailable; you can still use the configured default.'}


@router.post('/api/corpus')
async def submit(body: Submission):
    url = body.url.strip()
    try:
        await run_in_threadpool(validate_url, url)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    settings = load_settings()
    canonical = canonical_article_url(url)
    # Return duplicates before model validation; no generation is requested.
    def existing():
        from backend.db import get_connection
        with get_connection(settings) as conn:
            return conn.execute('SELECT * FROM corpus_articles WHERE canonical_url=%s',(canonical,)).fetchone()
    row = await run_in_threadpool(existing)
    if row is None:
        model = await run_in_threadpool(resolve_model, body.model)
        reason = None
        try:
            require_trusted(url, settings.corpus_trusted_domains)
        except UntrustedDomain as exc:
            reason = str(exc)
        row, _ = await run_in_threadpool(store.create, settings, url, canonical, model, reason)
    return await run_in_threadpool(store.get, settings, row['id'])


@router.get('/api/corpus')
def search(keyword: str = Query('', max_length=200), page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), include_reviewed: bool = False):
    return store.search(load_settings(), keyword.strip(), page, limit, include_reviewed=include_reviewed)


@router.get('/api/corpus/schedule')
def schedule():
    settings = load_settings()
    return {'start_hour':settings.corpus_schedule_hour, 'end_hour':settings.corpus_end_hour,
            'timezone':settings.corpus_schedule_timezone}


@router.post('/api/corpus/run-now')
async def run_now(request: Request):
    if not await run_in_threadpool(store.queued_articles, load_settings()):
        return {'started':False, 'message':'No queued articles to process.'}
    try:
        await request.app.state.temporal_client.start_workflow(CorpusBatchWorkflow.run, True,
            id='corpus-batch-active', task_queue=TASK_QUEUE)
    except WorkflowAlreadyStartedError:
        return {'started':False, 'message':'A corpus batch is already running.'}
    except Exception as exc:
        raise HTTPException(503, 'Could not start corpus processing. Articles remain queued.') from exc
    return {'started':True, 'message':'Corpus batch started. Progress will update below.',
            'workflow_id':'corpus-batch-active'}


@router.get('/api/corpus/{article_id}')
def detail(article_id: int):
    row = store.get(load_settings(), article_id)
    if row is None:
        raise HTTPException(404, 'Article not found')
    return row


@router.post('/api/corpus/{article_id}/retry')
async def retry(article_id: int, body: Retry = Retry()):
    settings = load_settings()
    current = await run_in_threadpool(store.get, settings, article_id)
    if current is None:
        raise HTTPException(404, 'Article not found')
    if current.get('quarantine_url'):
        raise HTTPException(409, 'Release this article from quarantine before retrying')
    if current['state'] != 'failed':
        raise HTTPException(409, 'Only failed articles can be retried')
    model = await run_in_threadpool(resolve_model, body.model) if body.model is not None else current['model']
    row = await run_in_threadpool(store.retry, settings, article_id, model)
    if row is None:
        raise HTTPException(409, 'Article is already processing')
    return row


@router.delete('/api/corpus/{article_id}')
def delete(article_id: int):
    row = store.delete(load_settings(), article_id)
    if row is None:
        raise HTTPException(404, 'Article not found')
    return {'id': article_id, 'deleted': True}


def review_article(article_id, rating=None):
    settings = load_settings()
    row = store.review(settings, article_id, rating)
    if row is None:
        if store.get(settings, article_id) is None:
            raise HTTPException(404, 'Article not found')
        raise HTTPException(409, 'Only completed briefings can be marked read or rated')
    return row


@router.post('/api/corpus/{article_id}/read')
def mark_read(article_id: int):
    return review_article(article_id)


@router.post('/api/corpus/{article_id}/rate')
def rate(article_id: int, body: RatingRequest):
    return review_article(article_id, body.rating)


@router.post('/api/corpus/{article_id}/release')
async def release(article_id: int):
    settings = load_settings()
    row = await run_in_threadpool(store.get, settings, article_id)
    if row is None:
        raise HTTPException(404, 'Article not found')
    if not row.get('quarantine_url'):
        raise HTTPException(409, 'Article is not quarantined')
    try:
        for url in {row['original_url'], row['quarantine_url']}:
            require_trusted(url, settings.corpus_trusted_domains)
            await run_in_threadpool(validate_url, url)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, f'{exc}. Configure CORPUS_TRUSTED_DOMAINS on backend and worker before releasing.') from exc
    released = await run_in_threadpool(store.release, settings, article_id)
    if released is None:
        raise HTTPException(409, 'Article was already released')
    return released
