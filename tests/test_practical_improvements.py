"""Regressions for bounded local work, lightweight APIs and modular assets."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, date
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import WorkflowAlreadyStartedError

from backend import main, corpus_api, knowledge_api
from backend.config import Settings
from backend.db import get_connection
from backend.services import article_extraction, corpus_store, corpus_summary, knowledge, ollama_queue
from backend.temporal import activities, knowledge as knowledge_workflow
from backend.temporal.models import DailyBriefingResult, ProcessSourceInput, SourceInput
from backend.adapters.rss import FeedEntry, RSSAdapter


@pytest.mark.parametrize('overrides', [
    {'inference_queue_timeout_seconds':0}, {'ollama_timeout_seconds':-1},
    {'schedule_hour':24}, {'schedule_timezone':'invalid/zone'},
    {'corpus_end_hour':2}, {'corpus_final_timeout_seconds':1200},
])
def test_settings_validate_bounds(overrides):
    with pytest.raises(ValueError):
        replace(Settings(), **overrides)


def test_queue_timeout_releases_connection_without_unlocking_unowned_lock(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {'acquired':False}
    manager = MagicMock()
    manager.__enter__.return_value = conn
    monkeypatch.setattr(ollama_queue, 'get_connection', lambda _:manager)
    monkeypatch.setattr(ollama_queue.time, 'monotonic', Mock(side_effect=[0,31]))
    with pytest.raises(ollama_queue.InferenceBusy):
        with ollama_queue.inference_slot(Settings()):
            pytest.fail('must not generate')
    assert conn.execute.call_count == 1
    manager.__exit__.assert_called_once()


def test_corpus_queue_uses_its_existing_deadline(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [{'acquired':False},{'acquired':True}]
    manager = MagicMock()
    manager.__enter__.return_value = conn
    monkeypatch.setattr(ollama_queue, 'get_connection', lambda _:manager)
    monkeypatch.setattr(ollama_queue.time, 'sleep', Mock())
    heartbeat = Mock()
    with ollama_queue.inference_slot(Settings(), (datetime.now(UTC)+timedelta(hours=1)).isoformat(), heartbeat):
        pass
    heartbeat.assert_called_once()
    assert 'pg_advisory_unlock' in conn.execute.call_args.args[0]


@pytest.mark.parametrize('url', ['file:///etc/passwd', '/tmp/feed', 'ftp://example.org/feed',
                                'https://user:pass@example.org/feed', 'http://example.org:9000/feed'])
def test_feed_rejects_unsupported_destinations(url):
    with pytest.raises(ValueError):
        article_extraction.public_hostname(url)


def feed_session(monkeypatch, *, chunks=(b'<rss/>',), location=None, address='93.184.216.34'):
    monkeypatch.setattr(article_extraction.socket, 'getaddrinfo', lambda *a,**kw:[(2,1,6,'',(address,80))])
    response = MagicMock(is_redirect=location is not None, headers={'Location':location} if location else {})
    response.__enter__.return_value = response
    response.iter_content.return_value = chunks
    session = Mock(get=Mock(return_value=response))
    monkeypatch.setattr(article_extraction.requests, 'Session', lambda:session)
    return session


def test_feed_download_pins_public_http_and_limits_bytes(monkeypatch):
    session = feed_session(monkeypatch, chunks=[b'x' * (5*1024*1024+1)])
    with pytest.raises(ValueError, match='size or time'):
        article_extraction.download('http://example.org/feed', feed=True)
    assert session.get.call_args.args[0] == 'http://93.184.216.34/feed'
    assert not session.get.call_args.kwargs['allow_redirects']
    session.close.assert_called_once()


@pytest.mark.parametrize('location', ['file:///tmp/feed', 'ftp://example.org/feed'])
def test_feed_redirect_revalidated(monkeypatch, location):
    session = feed_session(monkeypatch, location=location)
    with pytest.raises(ValueError):
        article_extraction.download('https://example.org/feed', feed=True)
    assert session.get.call_count == 1


def test_feed_private_address_blocked_before_connection(monkeypatch):
    session = feed_session(monkeypatch, address='127.0.0.1')
    with pytest.raises(ValueError, match='private'):
        article_extraction.download('http://example.org/feed', feed=True)
    session.get.assert_not_called()


def test_rss_parser_receives_bytes(monkeypatch):
    import backend.adapters.rss as rss
    body = b'<rss version="2.0"><channel><title>Feed</title><item><title>Paper</title><link>https://example.org/a</link><description>Evidence</description></item></channel></rss>'
    download = Mock(return_value=(body, 'application/rss+xml', 'https://example.org/feed'))
    monkeypatch.setattr(rss, 'download', download)
    assert RSSAdapter().fetch_entries('https://example.org/feed')[0].summary == 'Evidence'
    download.assert_called_once_with('https://example.org/feed', feed=True)


def test_rss_releases_lookup_connection_during_inference(monkeypatch):
    opened = 0
    @contextmanager
    def connection(_):
        nonlocal opened
        opened += 1
        try:
            yield Mock()
        finally:
            opened -= 1
    monkeypatch.setattr(activities, 'get_connection', connection)
    monkeypatch.setattr(activities, 'fetch_existing_urls', lambda *a:set())
    monkeypatch.setattr(activities, 'insert_inbox_entry', lambda *a,**kw:True)
    monkeypatch.setattr(activities, 'update_source_last_polled_at', Mock())
    now = datetime.now(UTC)
    entry = FeedEntry('Paper','https://example.org/a',now,'Evidence')
    monkeypatch.setattr(RSSAdapter, 'fetch_entries', lambda *a:[entry])
    def summarize(*a, **kw):
        assert opened == 0
        return 'Summary'
    monkeypatch.setattr(activities.OllamaSummarizer, 'summarize', summarize)
    result = activities.process_source(ProcessSourceInput(SourceInput(str(uuid4()),'Feed','https://example.org/feed',None),(now+timedelta(seconds=1)).isoformat()))
    assert result.entries_created == 1 and opened == 0


def test_source_budget_skips_remaining_entries(monkeypatch):
    now = datetime.now(UTC)
    monkeypatch.setattr(activities.time, 'monotonic', Mock(side_effect=[0,599]))
    monkeypatch.setattr(RSSAdapter, 'fetch_entries', lambda *a:[FeedEntry('Paper','https://example.org/a',now,'Evidence')])
    manager = MagicMock()
    monkeypatch.setattr(activities, 'get_connection', lambda _:manager)
    monkeypatch.setattr(activities, 'fetch_existing_urls', lambda *a:set())
    monkeypatch.setattr(activities, 'update_source_last_polled_at', Mock())
    summarize = Mock()
    monkeypatch.setattr(activities.OllamaSummarizer, 'summarize', summarize)
    result = activities.process_source(ProcessSourceInput(SourceInput(str(uuid4()),'Feed','https://example.org/feed',None),(now+timedelta(seconds=1)).isoformat()))
    assert result.entries_created == 0
    summarize.assert_not_called()


@pytest.mark.parametrize('payload', [
    {'name':'   ','feed_url':'https://example.org/feed'},
    {'name':'Feed','feed_url':'   '}, {'name':'Feed','feed_url':'file:///tmp/feed'},
])
def test_invalid_sources_are_validation_errors(payload):
    assert TestClient(main.app).post('/api/sources', json=payload).status_code == 422


def test_invalid_source_uuid_is_validation_error():
    assert TestClient(main.app).delete('/api/sources/not-a-uuid').status_code == 422


def test_manual_job_returns_immediately_and_reuses_active_run(monkeypatch):
    temporal = Mock(start_workflow=AsyncMock())
    monkeypatch.setattr(main.app.state, 'temporal_client', temporal, raising=False)
    client = TestClient(main.app)
    response = client.post('/api/jobs/run-now')
    assert response.status_code == 202 and response.json()['started']
    assert response.json()['workflow_id'] == main.MANUAL_BRIEFING_ID
    temporal.execute_workflow.assert_not_called()
    temporal.start_workflow.side_effect = WorkflowAlreadyStartedError(main.MANUAL_BRIEFING_ID,'DailyBriefingWorkflow')
    assert client.post('/api/jobs/run-now').json()['started'] is False
    handle = Mock(describe=AsyncMock(return_value=Mock(status=WorkflowExecutionStatus.RUNNING)),result=AsyncMock())
    temporal.get_workflow_handle.return_value = handle
    assert client.get(f'/api/jobs/{main.MANUAL_BRIEFING_ID}').json()['state'] == 'running'
    handle.result.assert_not_called()
    handle.describe.return_value.status = WorkflowExecutionStatus.COMPLETED
    handle.result.return_value = DailyBriefingResult(2,4,3,1)
    assert client.get(f'/api/jobs/{main.MANUAL_BRIEFING_ID}').json()['result']['sources_failed'] == 1


def test_corpus_status_omits_saved_content(settings, monkeypatch):
    monkeypatch.setattr(corpus_api, 'load_settings', lambda:settings)
    row,_ = corpus_store.create(settings,'https://example.org/a','https://example.org/a','model')
    corpus_store.update(settings,row['id'],1,state='summarizing',article_text='A'*100000,sections=[{'ref':'page 1','text':'A'*100000}])
    corpus_store.set_progress(settings,row['id'],1,1,'reading',1,2,0)
    response = TestClient(main.app).get(f"/api/corpus/{row['id']}/status")
    assert response.status_code == 200 and len(response.content) < 1000
    assert response.json()['progress']['current'] == 1
    assert not {'article_text','sections','briefing','search_document'} & response.json().keys()
    assert 'search_document' not in corpus_store.get(settings,row['id'])


def test_paginated_inbox_history_and_read_then_rate(settings, monkeypatch):
    monkeypatch.setattr(main,'settings',settings)
    with get_connection(settings) as conn:
        for i in range(4):
            conn.execute("""INSERT INTO inbox_entries(source_name,title,canonical_url,article_url,summary,discovered_at)
                VALUES ('Feed',%s,%s,'https://example.org','Evidence', '2026-01-01')""", (str(i),f'https://example.org/{i}'))
    client = TestClient(main.app)
    first = client.get('/api/inbox?limit=2').json()
    second = client.get('/api/inbox?limit=2&page=2').json()
    assert first['total'] == second['total'] == 4
    assert [item['title'] for item in first['items']+second['items']] == ['3','2','1','0']
    item_id = first['items'][0]['id']
    assert client.post(f'/api/inbox/{item_id}/read').status_code == 200
    assert client.get('/api/inbox').json()['total'] == 3
    assert client.post(f'/api/inbox/{item_id}/rate',json={'rating':4}).status_code == 200
    assert client.get('/api/history?rating=4').json()['items'][0]['id'] == item_id
    assert client.get('/api/inbox?limit=101').status_code == 422


def test_scheduled_sync_drains_batches_and_stops_after_failure(monkeypatch):
    monkeypatch.setattr(knowledge_workflow,'load_settings',lambda:replace(Settings(),knowledge_enabled=True,knowledge_service_url='http://retrieval.test'))
    drain = Mock(side_effect=[{'enabled':True,'indexed':25,'failed':0},{'enabled':True,'indexed':4,'failed':1}])
    monkeypatch.setattr(knowledge_workflow,'drain',drain)
    assert knowledge_workflow.sync_knowledge() == {'enabled':True,'indexed':29,'failed':1}
    assert drain.call_count == 2
    assert all(call.kwargs['limit'] == 25 for call in drain.call_args_list)


def test_knowledge_date_is_published_and_date_only_change_queues(settings):
    settings = replace(settings,knowledge_enabled=True,knowledge_service_url='http://retrieval.test')
    from backend.db import initialize_database
    initialize_database(settings)
    row,_ = corpus_store.create(settings,'https://example.org/a','https://example.org/a','model')
    corpus_store.update(settings,row['id'],1,state='ready',article_text='Evidence',published_date=date(2026,1,2))
    with get_connection(settings) as conn:
        assert knowledge.documents(conn,'corpus',row['id'])[str(row['id'])]['published_at'] == '2026-01-02T00:00:00+00:00'
        conn.execute('DELETE FROM knowledge_outbox')
    corpus_store.update(settings,row['id'],1,published_date=date(2026,1,3))
    with get_connection(settings) as conn:
        assert conn.execute('SELECT count(*) AS n FROM knowledge_outbox').fetchone()['n'] == 1


@pytest.mark.parametrize('body', [[], {}, {'chunks':None}, {'chunks':[None]}, {'chunks':[{'content':123}]}])
def test_malformed_retrieval_response_is_gateway_error(monkeypatch, body):
    monkeypatch.setattr(knowledge_api,'load_settings',lambda:replace(Settings(),knowledge_enabled=True,knowledge_service_url='http://retrieval.test'))
    monkeypatch.setattr(knowledge_api.requests,'post',Mock(return_value=Mock(json=lambda:body)))
    assert TestClient(main.app).post('/api/knowledge/query',json={'query':'Question'}).status_code == 502


def test_static_modules_available_without_starting_services():
    client = TestClient(main.app)
    assert '/static/assets/app.js' in client.get('/').text
    for name in ('app.js','rss.js','corpus.js','knowledge.js','shared.js','styles.css'):
        response = client.get('/static/assets/'+name)
        assert response.status_code == 200
        assert 'javascript' in response.headers['content-type'] if name.endswith('.js') else 'text/css' in response.headers['content-type']


def test_condensation_is_checkpointed_across_deferral(settings, monkeypatch):
    import json
    from temporalio.testing import ActivityEnvironment
    from backend.temporal import corpus
    settings = replace(settings,corpus_trusted_domains=('example.org',))
    monkeypatch.setattr(corpus,'load_settings',lambda:settings)
    row,_ = corpus_store.create(settings,'https://example.org/cached','https://example.org/cached','model')
    corpus_store.update(settings,row['id'],1,title='Paper',article_text='a'*25000,
                        sections=[{'ref':'page 1','text':'a'*25000}])
    condensing = []
    def generate(settings, model, prompt, structured=False):
        if structured:
            return json.dumps({key:'Finding [page 1]' for key in corpus_summary.HEADINGS})
        if prompt.startswith('Condense'):
            condensing.append(prompt)
            if len(condensing) == 2:
                raise ollama_queue.CorpusDeferred('window ended')
            return 'Condensed finding [page 1]'
        return 'n'*4000
    monkeypatch.setattr(corpus,'generate',generate)
    env = ActivityEnvironment()
    data = {'id':row['id'],'attempt':1}
    with pytest.raises(ollama_queue.CorpusDeferred):
        env.run(corpus.summarize_article,data)
    env.run(corpus.defer_article,data)
    env.run(corpus.summarize_article,data)
    assert len(condensing) == 3  # First condensation reused; interrupted second batch retried.
    assert corpus_store.get(settings,row['id'])['state'] == 'ready'


def test_reading_generation_rejects_incomplete_output(monkeypatch):
    monkeypatch.setattr(corpus_summary.requests,'post',Mock(return_value=Mock(json=lambda:{'response':'partial','done':False})))
    with pytest.raises(corpus_summary.IncompleteGenerationError):
        corpus_summary.generate(Settings(),'model','Evidence prompt')


def test_queue_busy_is_actionable_for_knowledge(monkeypatch):
    monkeypatch.setattr(knowledge_api,'load_settings',lambda:replace(Settings(),knowledge_enabled=True,knowledge_service_url='http://retrieval.test'))
    monkeypatch.setattr(knowledge_api.requests,'post',Mock(return_value=Mock(json=lambda:{'chunks':[{'content':'Evidence','citation':'[1]'}]})))
    monkeypatch.setattr(knowledge_api,'synthesize',Mock(side_effect=ollama_queue.InferenceBusy('Model busy. Try chunk mode.')))
    response = TestClient(main.app).post('/api/knowledge/query',json={'query':'Question','mode':'summary'})
    assert response.status_code == 503 and response.headers['Retry-After'] == '30'


def test_rss_checks_cancellation_before_inference(monkeypatch):
    from temporalio.exceptions import CancelledError
    monkeypatch.setattr(activities.activity,'in_activity',lambda:True)
    monkeypatch.setattr(activities.activity,'heartbeat',Mock())
    monkeypatch.setattr(activities.activity,'is_cancelled',lambda:True)
    monkeypatch.setattr(RSSAdapter,'fetch_entries',lambda *a:[FeedEntry('Paper','https://example.org/a',datetime.now(UTC),'Evidence')])
    monkeypatch.setattr(activities,'get_connection',lambda _:MagicMock())
    monkeypatch.setattr(activities,'fetch_existing_urls',lambda *a:set())
    with pytest.raises(CancelledError):
        activities.process_source(ProcessSourceInput(SourceInput(str(uuid4()),'Feed','https://example.org/feed',None),datetime.now(UTC).isoformat()))


@pytest.mark.asyncio
async def test_rss_workflow_continues_after_failed_source():
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    from backend.temporal.workflows import DailyBriefingWorkflow
    from backend.temporal.models import ProcessSourceResult
    @activity.defn(name='list_enabled_sources')
    async def sources() -> list[SourceInput]:
        return [SourceInput('bad','Bad','https://example.org/bad',None),SourceInput('good','Good','https://example.org/good',None)]
    @activity.defn(name='process_source')
    async def process(data: ProcessSourceInput) -> ProcessSourceResult:
        if data.source.id == 'bad':
            raise ValueError('Invalid feed')
        return ProcessSourceResult('good',2,1)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client,task_queue='skip-source',workflows=[DailyBriefingWorkflow],activities=[sources,process]):
            result = await env.client.execute_workflow(DailyBriefingWorkflow.run,id=str(uuid4()),task_queue='skip-source')
    assert result.sources_failed == 1 and result.sources_processed == 1 and result.entries_created == 1


@pytest.mark.asyncio
async def test_existing_rss_schedule_is_preserved():
    from backend.temporal.client import ensure_daily_briefing_schedule
    handle = Mock(describe=AsyncMock())
    client = Mock(get_schedule_handle=Mock(return_value=handle),create_schedule=AsyncMock())
    await ensure_daily_briefing_schedule(client,Settings())
    client.create_schedule.assert_not_called()
    handle.update.assert_not_called()
