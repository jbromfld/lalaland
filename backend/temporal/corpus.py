from datetime import UTC, datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from backend.config import load_settings
    from backend.services import corpus_store as store
    from backend.services.article_extraction import extract, require_trusted, UntrustedDomain
    from backend.services.corpus_summary import summarize, generate
    from backend.services.ollama_queue import CorpusDeferred, inference_slot


def enforce_article_trust(settings, row):
    if row.get('quarantine_url'):
        raise ApplicationError('Article is quarantined', type='CorpusQuarantined', non_retryable=True)
    try:
        require_trusted(row['original_url'], settings.corpus_trusted_domains)
        if row.get('resolved_url'):
            require_trusted(row['resolved_url'], settings.corpus_trusted_domains)
    except UntrustedDomain as exc:
        store.quarantine(settings, row['id'], row['attempt'], exc.url, str(exc))
        raise ApplicationError(str(exc), type='CorpusQuarantined', non_retryable=True) from exc


def require_article(settings, article_id):
    row = store.get(settings, article_id)
    if row is None:
        raise ApplicationError('Article was deleted', type='CorpusDeleted', non_retryable=True)
    return row


@activity.defn
def extract_article(data: dict) -> None:
    settings = load_settings()
    row = require_article(settings, data['id'])
    if row['attempt'] != data['attempt'] or row['state'] == 'ready':
        return
    enforce_article_trust(settings, row)
    if row['article_text']:
        return
    store.update(settings, row['id'], row['attempt'], state='extracting', error=None)
    activity.heartbeat()
    try:
        result = extract(row['original_url'])
    except UntrustedDomain as exc:
        store.quarantine(settings, row['id'], row['attempt'], exc.url, str(exc))
        raise ApplicationError(str(exc), type='CorpusQuarantined', non_retryable=True) from exc
    store.update(settings, row['id'], row['attempt'], **result)


@activity.defn
def summarize_article(data: dict) -> None:
    settings = load_settings()
    row = require_article(settings, data['id'])
    if row['attempt'] != data['attempt'] or row['state'] == 'ready':
        return
    enforce_article_trust(settings, row)
    store.update(settings, row['id'], row['attempt'], state='summarizing', error=None)
    current_stage = None
    def report(stage, current, total, completed):
        nonlocal current_stage
        require_article(settings, row['id'])
        current_stage = stage
        store.set_progress(settings, row['id'], row['attempt'], activity.info().attempt,
                           stage, current, total, completed)
        activity.heartbeat({'stage':stage, 'current':current, 'total':total, 'completed':completed})
    def cached_generate(call_settings, model, prompt, structured=False):
        require_article(settings, row['id'])
        digest = sha256(prompt.encode('utf-8')).hexdigest()
        use_cache = current_stage == 'reading' and not structured
        cached = store.cached_generation(settings, row, digest) if use_cache else None
        if cached is not None:
            return cached
        with inference_slot(settings, data.get('deadline'), activity.heartbeat,
                            timeout_seconds=settings.corpus_final_timeout_seconds if structured else settings.corpus_ollama_timeout_seconds):
            result = generate(call_settings, model, prompt, structured)
        if use_cache:
            store.save_generation(settings, row, digest, result)
        return result
    result = summarize(settings, row, activity.heartbeat, progress=report, generator=cached_generate)
    store.update(settings, row['id'], row['attempt'], state='ready', briefing=result, error=None)


@activity.defn
def fail_article(data: dict) -> None:
    store.update(load_settings(), data['id'], data['attempt'], state='failed', error=data['error'][:1000])


@activity.defn
def defer_article(data: dict) -> None:
    store.update(load_settings(), data['id'], data['attempt'], state='queued', error=None)


@activity.defn
def prepare_nightly_batch(manual: bool = False) -> dict:
    settings = load_settings()
    if not 0 <= settings.corpus_schedule_hour < settings.corpus_end_hour <= 23:
        raise ValueError('Corpus window must start and end on the same day, with end after start')
    now = datetime.now(ZoneInfo(settings.corpus_schedule_timezone))
    start = now.replace(hour=settings.corpus_schedule_hour, minute=0, second=0, microsecond=0)
    deadline = now.replace(hour=settings.corpus_end_hour, minute=0, second=0, microsecond=0)
    if manual:
        deadline = now + timedelta(hours=2)
    articles = store.queued_articles(settings) if manual or start <= now < deadline else []
    return {'deadline':deadline.astimezone(UTC).isoformat(), 'articles':articles}


@workflow.defn
class CorpusWorkflow:
    @workflow.run
    async def run(self, data: dict) -> str:
        try:
            await workflow.execute_activity(extract_article, data,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=['ValueError']))
            await workflow.execute_activity(summarize_article, data,
                start_to_close_timeout=timedelta(hours=2), heartbeat_timeout=timedelta(minutes=20),
                retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=['CorpusDeferred']))
            return 'ready'
        except Exception as exc:
            cause = exc
            while getattr(cause, 'cause', None) is not None:
                cause = cause.cause
            if isinstance(cause, ApplicationError) and cause.type == 'CorpusDeleted':
                return 'deleted'
            if isinstance(cause, ApplicationError) and cause.type == 'CorpusQuarantined':
                return 'quarantined'
            if (isinstance(cause, ApplicationError) and cause.type == 'CorpusDeferred') or (data.get('deadline') and workflow.now() >= datetime.fromisoformat(data['deadline'])):
                await workflow.execute_activity(defer_article, data, start_to_close_timeout=timedelta(seconds=30))
                return 'deferred'
            await workflow.execute_activity(fail_article, {**data, 'error':str(cause)},
                start_to_close_timeout=timedelta(seconds=30))

            return 'failed'


@workflow.defn
class CorpusBatchWorkflow:
    @workflow.run
    async def run(self, manual: bool = False) -> dict:
        batch = await workflow.execute_activity(prepare_nightly_batch, manual,
            start_to_close_timeout=timedelta(seconds=30))
        processed = 0
        for article in batch['articles']:
            if workflow.now() >= datetime.fromisoformat(batch['deadline']):
                break
            outcome = await workflow.execute_child_workflow(CorpusWorkflow.run,
                {**article, 'deadline':batch['deadline']},
                id=f'corpus-{article["id"]}-{article["attempt"]}')
            if outcome == 'deferred':
                break
            processed += 1
        return {'processed':processed, 'remaining':len(batch['articles'])-processed}


@workflow.defn
class NightlyCorpusWorkflow:
    @workflow.run
    async def run(self) -> dict:
        # Schedules append a timestamp to their workflow IDs. A fixed child ID
        # shares a single batch with manual requests and prevents duplicate work.
        try:
            return await workflow.execute_child_workflow(CorpusBatchWorkflow.run, False,
                id='corpus-batch-active')
        except WorkflowAlreadyStartedError:
            return {'already_running':True}
