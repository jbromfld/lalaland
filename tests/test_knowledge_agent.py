from contextlib import nullcontext
from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

from backend import knowledge_api
from backend.config import Settings
from backend.main import app
from backend.services import knowledge_agent


@pytest.fixture
def retrieval(monkeypatch):
    settings = replace(Settings(), knowledge_service_url='http://retrieval.test', knowledge_model='third-agent')
    monkeypatch.setattr(knowledge_api, 'load_settings', lambda: settings)
    result = {'chunks': [{'citation': '[1]', 'content': 'Measured improvement.',
                          'title': 'Research', 'url': 'https://example.org', 'score': 0.5}],
              'query_id': 'example'}
    response = Mock()
    response.json.return_value = result
    post = Mock(return_value=response)
    monkeypatch.setattr(knowledge_api.requests, 'post', post)
    return TestClient(app), result, post


def test_chunk_mode_is_compatible_and_never_generates(retrieval, monkeypatch):
    client, result, post = retrieval
    generate = Mock(side_effect=AssertionError('must not synthesize'))
    monkeypatch.setattr(knowledge_api, 'synthesize', generate)
    response = client.post('/api/knowledge/query', json={'query': 'Find research'})
    assert response.status_code == 200
    assert response.json() == result
    assert post.call_args.kwargs['json'] == {
        'query': 'Find research', 'top_k': 5,
        'filters': {'collection': ['lalaland-rss', 'lalaland-corpus']}}
    generate.assert_not_called()


def test_summary_keeps_citations_and_respects_collection(retrieval, monkeypatch):
    client, result, post = retrieval
    generate = Mock(return_value='An improvement was measured [1].')
    monkeypatch.setattr(knowledge_api, 'synthesize', generate)
    response = client.post('/api/knowledge/query', json={
        'query': '  What improved? ', 'mode': 'summary', 'filters': {'collection': ['lalaland-rss']}})
    assert response.status_code == 200
    assert response.json() == {**result, 'summary': generate.return_value, 'model': 'third-agent'}
    assert generate.call_args.args[1:] == ('What improved?', result['chunks'])
    assert post.call_args.kwargs['json']['filters'] == {'collection': ['lalaland-rss']}
    assert 'mode' not in post.call_args.kwargs['json']
    assert 'model' not in post.call_args.kwargs['json']


def test_summary_uses_selected_installed_model(retrieval, monkeypatch):
    client, _, post = retrieval
    monkeypatch.setattr(knowledge_api, 'installed_models', lambda settings: ['selected-agent'])
    generate = Mock(return_value='Finding [1].')
    monkeypatch.setattr(knowledge_api, 'synthesize', generate)
    response = client.post('/api/knowledge/query', json={
        'query': 'Research', 'mode': 'summary', 'model': 'selected-agent'})
    assert response.status_code == 200
    assert response.json()['model'] == 'selected-agent'
    assert generate.call_args.args[0].knowledge_model == 'selected-agent'
    assert 'model' not in post.call_args.kwargs['json']


@pytest.mark.parametrize('offline', [False, True])
def test_summary_rejects_unavailable_model(retrieval, monkeypatch, offline):
    client, _, post = retrieval
    discover = Mock(side_effect=requests.ConnectionError()) if offline else Mock(return_value=['installed'])
    monkeypatch.setattr(knowledge_api, 'installed_models', discover)
    response = client.post('/api/knowledge/query', json={
        'query': 'Research', 'mode': 'summary', 'model': 'missing'})
    assert response.status_code == (503 if offline else 422)
    post.assert_not_called()


def test_chunk_mode_ignores_model(retrieval, monkeypatch):
    client, result, _ = retrieval
    discover = Mock(side_effect=AssertionError('must not discover models'))
    monkeypatch.setattr(knowledge_api, 'installed_models', discover)
    response = client.post('/api/knowledge/query', json={'query': 'Research', 'model': 'unused'})
    assert response.json() == result
    discover.assert_not_called()


@pytest.mark.parametrize('installed', [['third-agent', 'other'], ['other'], None])
def test_model_dropdown_reports_knowledge_default(retrieval, monkeypatch, installed):
    client, _, _ = retrieval
    discover = Mock(side_effect=requests.ConnectionError()) if installed is None else Mock(return_value=installed)
    monkeypatch.setattr(knowledge_api, 'installed_models', discover)
    response = client.get('/api/knowledge/models')
    assert response.status_code == 200
    data = response.json()
    assert data['default_model'] == 'third-agent'
    assert data['models'] == (installed or [])
    if installed is None:
        assert data['error']
    else:
        assert bool(data['warning']) == ('third-agent' not in installed)


def test_empty_retrieval_does_not_invoke_agent(retrieval, monkeypatch):
    client, result, _ = retrieval
    result['chunks'] = []
    generate = Mock()
    monkeypatch.setattr(knowledge_api, 'synthesize', generate)
    response = client.post('/api/knowledge/query', json={'query': 'Unknown', 'mode': 'summary'})
    assert response.status_code == 200
    assert response.json()['model'] is None
    assert 'No matching evidence' in response.json()['summary']
    generate.assert_not_called()


@pytest.mark.parametrize('failure', [requests.Timeout(), ValueError('empty response')])
def test_agent_failures_are_actionable(retrieval, monkeypatch, failure):
    client, _, _ = retrieval
    monkeypatch.setattr(knowledge_api, 'synthesize', Mock(side_effect=failure))
    response = client.post('/api/knowledge/query', json={'query': 'Research', 'mode': 'summary'})
    assert response.status_code == 502
    assert 'Try chunk mode' in response.json()['detail']


def test_retrieval_failure_does_not_invoke_agent(retrieval, monkeypatch):
    client, _, post = retrieval
    post.side_effect = requests.ConnectionError()
    generate = Mock()
    monkeypatch.setattr(knowledge_api, 'synthesize', generate)
    assert client.post('/api/knowledge/query', json={'query': 'Research', 'mode': 'summary'}).status_code == 502
    generate.assert_not_called()


@pytest.mark.parametrize('payload', [
    {'query': ' '}, {'query': 'x' * 4001}, {'query': 'Research', 'mode': 'unknown'},
    {'query': 'Research', 'top_k': 101},
])
def test_invalid_search_is_rejected(retrieval, payload):
    client, _, post = retrieval
    assert client.post('/api/knowledge/query', json=payload).status_code == 422
    post.assert_not_called()


def test_evidence_budget_preserves_labels_and_unicode():
    chunks = [{'citation': f'[{i}]', 'content': '雪' * 4000} for i in range(100)]
    used = knowledge_agent.evidence_chunks(chunks)
    assert sum(len(c['content'].encode('utf-8')) for c in used) <= 24000
    assert len(used) == 8
    assert [c['citation'] for c in used] == [c['citation'] for c in chunks[:8]]
    assert chunks[0]['content'] == '雪' * 4000


def test_third_agent_uses_own_configuration_and_cited_evidence(monkeypatch):
    settings = replace(Settings(), knowledge_model='third-agent', knowledge_agent_timeout_seconds=180,
                       knowledge_agent_instructions='Compare the findings.')
    slot = Mock(return_value=nullcontext())
    monkeypatch.setattr(knowledge_agent, 'inference_slot', slot)
    response = Mock()
    response.json.return_value = {'response': '<think>reasoning</think>Finding [1].', 'done': True}
    post = Mock(return_value=response)
    monkeypatch.setattr(knowledge_agent.requests, 'post', post)
    assert knowledge_agent.synthesize(settings, 'What improved?', [
        {'citation': '[1]', 'content': 'Measured improvement.', 'title': 'Study'}]) == 'Finding [1].'
    slot.assert_called_once_with(settings)
    options = post.call_args.kwargs
    assert options['timeout'] == 180
    assert options['json']['model'] == 'third-agent'
    assert 'Compare the findings.' in options['json']['prompt']
    assert 'untrusted data' in options['json']['prompt']
    assert 'Measured improvement.' in options['json']['prompt']
    assert '[1]' in options['json']['prompt']


@pytest.mark.parametrize('payload', [{}, {'response': ''}, {'response': 'partial', 'done_reason': 'length'}])
def test_agent_rejects_empty_or_incomplete_output(monkeypatch, payload):
    monkeypatch.setattr(knowledge_agent, 'inference_slot', lambda settings: nullcontext())
    response = Mock()
    response.json.return_value = payload
    monkeypatch.setattr(knowledge_agent.requests, 'post', Mock(return_value=response))
    with pytest.raises(ValueError):
        knowledge_agent.synthesize(Settings(), 'Question', [])
