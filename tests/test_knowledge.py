from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

from backend.db import get_connection, initialize_database
from backend.main import app
from backend.services import knowledge
from backend.services import corpus_store


def rss(conn, text='A short VLM summary.'):
    return conn.execute("""INSERT INTO inbox_entries(source_name,title,canonical_url,article_url,summary)
        VALUES ('Feed','VLM','https://example.org/vlm','https://example.org/vlm',%s) RETURNING id""", (text,)).fetchone()['id']


def test_outbox_transactions_backfill_and_reviews(settings):
    with get_connection(settings) as conn:
        source_id = rss(conn)
    with get_connection(settings) as conn:
        before = conn.execute('SELECT * FROM knowledge_outbox').fetchone()
        conn.execute("UPDATE inbox_entries SET read_at=NOW() WHERE id=%s", (source_id,))
        assert conn.execute('SELECT * FROM knowledge_outbox').fetchone()['version'] == before['version']
        conn.execute("UPDATE inbox_entries SET summary='changed' WHERE id=%s", (source_id,))
        assert conn.execute('SELECT * FROM knowledge_outbox').fetchone()['version'] > before['version']
    initialize_database(settings)
    knowledge.backfill(settings)
    with get_connection(settings) as conn:
        assert conn.execute('SELECT count(*) AS n FROM knowledge_outbox').fetchone()['n'] == 1
        conn.execute('DELETE FROM knowledge_outbox')
        conn.execute("UPDATE inbox_entries SET summary='rolled back' WHERE id=%s", (source_id,))
        conn.rollback()
        assert conn.execute('SELECT count(*) AS n FROM knowledge_outbox').fetchone()['n'] == 1


def test_delivery_retries_and_concurrent_deletion(settings, monkeypatch):
    settings = replace(settings, knowledge_service_url='http://retrieval.test')
    with get_connection(settings) as conn:
        source_id = rss(conn)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(knowledge.requests, 'Session', lambda: session)
    session.put.side_effect = requests.ConnectionError('offline')
    assert knowledge.drain(settings)['failed'] == 1
    with get_connection(settings) as conn:
        event = conn.execute('SELECT * FROM knowledge_outbox').fetchone()
        assert event['attempts'] == 1 and event['last_error'] == 'ConnectionError'
    def delete_during_delivery(*args, **kwargs):
        with get_connection(settings) as conn:
            conn.execute('DELETE FROM inbox_entries WHERE id=%s', (source_id,))
        return Mock()
    session.put.side_effect = delete_during_delivery
    assert knowledge.drain(settings)['indexed'] == 1
    with get_connection(settings) as conn:
        assert conn.execute('SELECT count(*) AS n FROM knowledge_outbox').fetchone()['n'] == 1
    assert knowledge.drain(settings)['indexed'] == 1
    session.delete.assert_called_once()
    with get_connection(settings) as conn:
        assert conn.execute('SELECT count(*) AS n FROM knowledge_outbox').fetchone()['n'] == 0


def test_corpus_documents_and_deletion(settings):
    row, _ = corpus_store.create(settings, 'https://arxiv.org/pdf/2601.00001', 'https://arxiv.org/pdf/2601.00001', 'model')
    corpus_store.update(settings, row['id'], row['attempt'], state='ready', title='VLM paper',
        article_text='Evidence', sections=[{'ref':'page 1','text':'Evidence'}], briefing={'summary':'Finding'})
    with get_connection(settings) as conn:
        docs = knowledge.documents(conn, 'corpus', row['id'])
        assert docs[str(row['id'])]['sections'][0]['ref'] == 'page 1'
        assert docs[f"{row['id']}-briefing"]['content_type'] == 'corpus_briefing'
    corpus_store.delete(settings, row['id'])
    with get_connection(settings) as conn:
        assert knowledge.documents(conn, 'corpus', row['id']) == {}
        assert conn.execute('SELECT count(*) AS n FROM knowledge_outbox').fetchone()['n'] == 1


def test_disabled_sync_does_not_open_database(monkeypatch):
    from backend.config import Settings
    monkeypatch.setattr(knowledge, 'get_connection', Mock(side_effect=AssertionError))
    assert knowledge.drain(Settings())['enabled'] is False


def test_query_forwards_scoped_results(monkeypatch):
    from backend import knowledge_api
    from backend.config import Settings
    monkeypatch.setattr(knowledge_api, 'load_settings', lambda: replace(Settings(), knowledge_service_url='http://retrieval.test'))
    response = Mock()
    response.json.return_value = {'chunks':[{'score':0.0001, 'citation':'[1]'}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(knowledge_api.requests, 'post', post)
    client = TestClient(app)
    result = client.post('/api/knowledge/query', json={'query':'VLMs'})
    assert result.status_code == 200
    assert result.json() == response.json.return_value
    assert post.call_args.kwargs['json']['filters']['collection'] == ['lalaland-rss', 'lalaland-corpus']
    assert client.post('/api/knowledge/query', json={'query':' '}).status_code == 422


def test_runtime_schema_matches_migration():
    from pathlib import Path
    from backend.services.knowledge_schema import SCHEMA
    assert SCHEMA.strip() == (Path(__file__).parents[1] / 'sql/ddl/006_knowledge_outbox.sql').read_text().strip()


@pytest.mark.asyncio
async def test_sync_workflow():
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    from backend.temporal.knowledge import KnowledgeSyncWorkflow

    @activity.defn(name='sync_knowledge')
    async def sync():
        return {'enabled': True, 'indexed': 1, 'failed': 0}

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue='knowledge-test', workflows=[KnowledgeSyncWorkflow], activities=[sync]):
            result = await env.client.execute_workflow(KnowledgeSyncWorkflow.run, id='knowledge-test', task_queue='knowledge-test')
            assert result['indexed'] == 1


@pytest.mark.asyncio
async def test_sync_schedule_disabled_without_url():
    from backend.config import Settings
    from backend.temporal.client import ensure_knowledge_schedule

    client = Mock()
    await ensure_knowledge_schedule(client, Settings())
    client.get_schedule_handle.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('exists', [False, True])
@pytest.mark.parametrize('overrides,cron,timezone', [
    ({}, '0 7 * * *', 'America/Detroit'),
    ({'knowledge_schedule_hour': 9, 'knowledge_schedule_minute': 30,
      'knowledge_schedule_timezone': 'UTC'}, '30 9 * * *', 'UTC'),
])
async def test_sync_schedule_creates_or_updates_daily_schedule(exists, overrides, cron, timezone):
    from unittest.mock import AsyncMock
    from temporalio.client import ScheduleOverlapPolicy
    from temporalio.service import RPCError, RPCStatusCode
    from backend.config import Settings
    from backend.temporal.client import ensure_knowledge_schedule

    client = Mock(create_schedule=AsyncMock())
    handle = Mock(describe=AsyncMock(), update=AsyncMock())
    if not exists:
        handle.describe.side_effect = RPCError('missing', RPCStatusCode.NOT_FOUND, b'')
    client.get_schedule_handle.return_value = handle
    await ensure_knowledge_schedule(client, replace(Settings(), knowledge_service_url='http://retrieval.test', **overrides))
    client.get_schedule_handle.assert_called_once_with('knowledge-sync-schedule')
    if exists:
        schedule = handle.update.call_args.args[0](None).schedule
        client.create_schedule.assert_not_called()
    else:
        schedule = client.create_schedule.call_args.args[1]
        assert client.create_schedule.call_args.args[0] == 'knowledge-sync-schedule'
        handle.update.assert_not_called()
    assert schedule.spec.cron_expressions == [cron]
    assert not schedule.spec.intervals
    assert schedule.spec.time_zone_name == timezone
    assert schedule.action.id == 'knowledge-sync-workflow'
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [
    {'knowledge_schedule_hour': -1}, {'knowledge_schedule_hour': 24},
    {'knowledge_schedule_minute': -1}, {'knowledge_schedule_minute': 60},
])
async def test_sync_schedule_rejects_invalid_time(overrides):
    from backend.config import Settings
    from backend.temporal.client import ensure_knowledge_schedule

    client = Mock()
    with pytest.raises(ValueError, match='Invalid knowledge sync schedule'):
        await ensure_knowledge_schedule(client, replace(Settings(), knowledge_service_url='http://retrieval.test', **overrides))
    client.get_schedule_handle.assert_not_called()
