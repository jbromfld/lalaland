import json
from contextlib import nullcontext
from unittest.mock import Mock

import pytest
import requests
from langsmith import tracing_context

from backend.config import Settings
from backend import corpus_api
from backend.services import corpus_summary, summarization, vllm


def settings():
    return Settings(inference_provider='vllm', vllm_base_url='http://vllm:8001/v1/',
                    vllm_api_key='secret-key', corpus_model='local-model')


def completion(content='Summary', finish_reason='stop'):
    return {'choices': [{'message': {'content': content}, 'finish_reason': finish_reason}]}


def test_rss_uses_vllm_and_keeps_settings_out_of_traces(monkeypatch):
    post = Mock(return_value=Mock(json=lambda: completion('<think>internal</think> Summary')))
    monkeypatch.setattr(vllm.requests, 'post', post)
    slot = Mock(return_value=nullcontext())
    monkeypatch.setattr(summarization, 'inference_slot', slot)
    completed = []
    with tracing_context(enabled=True, client=Mock()):
        result = summarization._generate_vllm_summary(
            'Prompt', settings(), langsmith_extra={'on_end': completed.append})
    assert result == 'Summary'
    assert completed[0].inputs == {'prompt': 'Prompt', 'model': 'local-model'}
    assert 'secret-key' not in repr(settings())
    result = summarization.OllamaSummarizer(settings()).summarize(
        source_name='Feed', article_title='Title', article_url='https://example.org', article_text='Text')
    assert result == 'Summary'
    slot.assert_called_once()
    assert post.call_args.args == ('http://vllm:8001/v1/chat/completions',)
    assert post.call_args.kwargs['headers'] == {'Authorization': 'Bearer secret-key'}
    assert post.call_args.kwargs['timeout'] == 120
    payload = post.call_args.kwargs['json']
    assert payload['model'] == 'local-model'
    assert payload['max_tokens'] == 768
    assert 'response_format' not in payload
    assert 'options' not in payload


def test_corpus_schema_budget_and_timeouts(monkeypatch):
    briefing = {key: 'Finding [page 1]' for key in corpus_summary.HEADINGS}
    post = Mock(return_value=Mock(json=lambda: completion(json.dumps(briefing))))
    monkeypatch.setattr(vllm.requests, 'post', post)
    result = corpus_summary.generate(settings(), 'local-model', 'Prompt', structured=True)
    assert corpus_summary.parse_briefing(result) == briefing
    payload = post.call_args.kwargs['json']
    assert payload['response_format']['type'] == 'json_schema'
    assert payload['response_format']['json_schema']['schema']['required'] == corpus_summary.HEADINGS
    assert payload['max_tokens'] == 6144
    assert post.call_args.kwargs['timeout'] == 900
    corpus_summary.generate(settings(), 'local-model', 'Notes')
    assert post.call_args.kwargs['timeout'] == 300
    assert post.call_args.kwargs['json']['max_tokens'] == 768


def test_truncated_final_retries_only_writing(monkeypatch):
    briefing = {key: 'Finding [page 1]' for key in corpus_summary.HEADINGS}
    response = Mock()
    response.json.side_effect = [completion('Notes'), completion('{}', 'length'), completion(json.dumps(briefing))]
    post = Mock(return_value=response)
    monkeypatch.setattr(vllm.requests, 'post', post)
    article = {'id': 1, 'title': 'Paper', 'model': 'local-model',
               'sections': [{'ref': 'page 1', 'text': 'Evidence'}]}
    assert corpus_summary.summarize(settings(), article) == briefing
    assert post.call_count == 3
    assert 'Start a fresh JSON object' in post.call_args.kwargs['json']['messages'][0]['content']


@pytest.mark.parametrize('body', [{}, {'choices': []}, {'choices': [None]},
                                 completion(None), completion(''), completion('text', 'content_filter')])
def test_invalid_responses_fail(monkeypatch, body):
    monkeypatch.setattr(vllm.requests, 'post', Mock(return_value=Mock(json=lambda: body)))
    with pytest.raises(ValueError):
        corpus_summary.generate(settings(), 'local-model', 'Prompt')


def test_http_error_propagates_without_fallback(monkeypatch):
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError('schema unsupported')
    post = Mock(return_value=response)
    monkeypatch.setattr(vllm.requests, 'post', post)
    with pytest.raises(requests.HTTPError, match='schema unsupported'):
        corpus_summary.generate(settings(), 'local-model', 'Prompt', structured=True)
    assert post.call_count == 1


def test_discovery_and_model_selection(monkeypatch):
    get = Mock(return_value=Mock(json=lambda: {'data': [{'id': 'local-model'}, {'id': 'local-model'}]}))
    monkeypatch.setattr(vllm.requests, 'get', get)
    monkeypatch.setattr(corpus_api, 'load_settings', settings)
    assert corpus_api.models()['models'] == ['local-model']
    assert corpus_api.resolve_model(None) == 'local-model'
    assert get.call_args.args == ('http://vllm:8001/v1/models',)
    assert get.call_args.kwargs['headers'] == {'Authorization': 'Bearer secret-key'}
    with pytest.raises(corpus_api.HTTPException) as exc:
        corpus_api.resolve_model('granite4.2:3b')
    assert exc.value.status_code == 422


@pytest.mark.parametrize('body', [{}, {'data': [None]}, {'data': [{'id': ''}]}])
def test_invalid_discovery_response(monkeypatch, body):
    monkeypatch.setattr(vllm.requests, 'get', Mock(return_value=Mock(json=lambda: body)))
    with pytest.raises(ValueError, match='model list'):
        corpus_summary.installed_models(settings())
