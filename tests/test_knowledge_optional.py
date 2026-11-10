from contextlib import nullcontext
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi.testclient import TestClient
from temporalio.service import RPCError, RPCStatusCode

from backend import db, knowledge_api, main
from backend.config import Settings, load_settings
from backend.services import knowledge
from backend.temporal.client import ensure_knowledge_schedule


@pytest.mark.parametrize('value,expected', [
    ('true', True), ('1', True), ('yes', True), ('ON', True),
    ('false', False), ('0', False), ('no', False), ('OFF', False),
])
def test_enable_flag_parses_boolean_values(monkeypatch, value, expected):
    monkeypatch.setenv('KNOWLEDGE_ENABLED', value)
    assert load_settings().knowledge_enabled is expected


def test_invalid_boolean_is_rejected(monkeypatch):
    monkeypatch.setenv('KNOWLEDGE_ENABLED', 'maybe')
    with pytest.raises(ValueError, match='KNOWLEDGE_ENABLED must be a boolean'):
        load_settings()


@pytest.mark.parametrize('enabled,url,active', [
    (False, '', False), (False, 'http://old-lassy.test', False),
    (True, '', False), (True, 'http://lassy.test', True),
])
def test_feature_discovery_requires_opt_in_and_url(monkeypatch, enabled, url, active):
    settings = replace(Settings(), knowledge_enabled=enabled, knowledge_service_url=url)
    monkeypatch.setattr(main, 'load_settings', lambda: settings)
    assert TestClient(main.app).get('/api/features').json() == {'knowledge': active}


@pytest.mark.parametrize('settings', [Settings(),
    replace(Settings(), knowledge_service_url='http://old-lassy.test'),
    replace(Settings(), knowledge_enabled=True),
])
def test_disabled_endpoints_and_delivery_have_no_external_dependencies(monkeypatch, settings):
    monkeypatch.setattr(knowledge_api, 'load_settings', lambda: settings)
    network = Mock(side_effect=AssertionError('No network access when disabled'))
    database = Mock(side_effect=AssertionError('No knowledge database access when disabled'))
    monkeypatch.setattr(knowledge_api.requests, 'post', network)
    monkeypatch.setattr(knowledge_api, 'installed_models', network)
    monkeypatch.setattr(knowledge, 'get_connection', database)
    client = TestClient(main.app)
    assert client.get('/health').status_code == 200
    assert client.get('/api/knowledge/models').status_code == 503
    for mode in ('chunks', 'summary'):
        response = client.post('/api/knowledge/query', json={'query': 'Research', 'mode': mode})
        assert response.status_code == 503
        assert 'KNOWLEDGE_ENABLED' in response.json()['detail']
    assert knowledge.drain(settings) == {'enabled': False, 'indexed': 0, 'failed': 0}
    knowledge.backfill(settings)
    database.assert_not_called()
    network.assert_not_called()


@pytest.mark.parametrize('command', ['backfill', 'status', 'sync'])
def test_disabled_cli_skips_database(monkeypatch, capsys, command):
    monkeypatch.setattr('sys.argv', ['knowledge', command])
    monkeypatch.setattr(knowledge, 'load_settings', Settings)
    initialize = Mock(side_effect=AssertionError('No schema initialization when disabled'))
    monkeypatch.setattr(knowledge, 'initialize_database', initialize)
    knowledge.main()
    assert '"enabled": false' in capsys.readouterr().out
    initialize.assert_not_called()


@pytest.mark.parametrize('active', [False, True])
def test_fresh_database_only_installs_knowledge_schema_when_enabled(monkeypatch, active):
    from backend.services.knowledge_schema import SCHEMA
    conn = MagicMock()
    monkeypatch.setattr(db, 'get_connection', lambda settings: nullcontext(conn))
    settings = replace(Settings(), knowledge_enabled=active, knowledge_service_url='http://lassy.test')
    db.initialize_database(settings)
    statements = [call.args[0] for call in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
    assert (SCHEMA in statements) is active
    assert all(statement in statements for statement in db.SCHEMA_STATEMENTS)
    conn.commit.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [RPCStatusCode.NOT_FOUND, RPCStatusCode.UNAVAILABLE])
async def test_disabling_is_safe_when_schedule_missing_or_unavailable(status):
    handle = Mock(pause=AsyncMock(side_effect=RPCError('unavailable', status, b'')))
    client = Mock()
    client.get_schedule_handle.return_value = handle
    await ensure_knowledge_schedule(client, Settings())
    handle.pause.assert_awaited_once()


@pytest.mark.asyncio
async def test_optional_schedule_failure_does_not_break_core_startup(monkeypatch):
    monkeypatch.setattr(main, 'settings', Settings())
    monkeypatch.setattr(main, 'setup_telemetry', Mock())
    monkeypatch.setattr(main, 'initialize_database', Mock())
    monkeypatch.setattr(main, 'connect', AsyncMock(return_value=Mock()))
    daily = AsyncMock()
    corpus = AsyncMock()
    monkeypatch.setattr(main, 'ensure_daily_briefing_schedule', daily)
    monkeypatch.setattr(main, 'ensure_corpus_schedule', corpus)
    monkeypatch.setattr(main, 'ensure_knowledge_schedule', AsyncMock(side_effect=RuntimeError('optional schedule unavailable')))
    async with main.lifespan(main.app):
        assert TestClient(main.app).get('/health').status_code == 200
    daily.assert_awaited_once()
    corpus.assert_awaited_once()


def test_in_flight_sync_is_safe_after_disabling(monkeypatch):
    from backend.temporal import knowledge as temporal_knowledge
    monkeypatch.setattr(temporal_knowledge, 'load_settings', Settings)
    monkeypatch.setattr(knowledge, 'get_connection', Mock(side_effect=AssertionError('disabled')))
    assert temporal_knowledge.sync_knowledge()['enabled'] is False


def test_database_enable_disable_lifecycle(monkeypatch, request):
    # Resolve the shared database fixture after opting out, to model a new machine.
    monkeypatch.setenv('KNOWLEDGE_ENABLED', 'false')
    settings = request.getfixturevalue('settings')
    with db.get_connection(settings) as conn:
        assert conn.execute("SELECT to_regclass('knowledge_outbox') AS relation").fetchone()['relation'] is None
        source_id = conn.execute("""INSERT INTO inbox_entries
            (source_name,title,canonical_url,article_url,summary)
            VALUES ('Feed','Research','https://example.org/test','https://example.org/test','Original summary')
            RETURNING id""").fetchone()['id']
    enabled = replace(settings, knowledge_enabled=True, knowledge_service_url='http://lassy.test')
    db.initialize_database(enabled)
    knowledge.backfill(enabled)
    with db.get_connection(enabled) as conn:
        before = conn.execute('SELECT * FROM knowledge_outbox').fetchone()
        assert before['source_id'] == source_id
    db.initialize_database(settings)
    with db.get_connection(settings) as conn:
        conn.execute('UPDATE inbox_entries SET summary=%s WHERE id=%s', ('Changed while disabled', source_id))
        assert conn.execute('SELECT * FROM knowledge_outbox').fetchone()['version'] > before['version']
    assert knowledge.drain(settings)['enabled'] is False
