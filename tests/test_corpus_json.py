"""Final writing must not persist truncated or structurally invalid JSON."""
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from backend.config import Settings, load_settings
from backend.services import corpus_summary as summary
from backend.services.ollama_queue import CorpusDeferred


def article():
    return {'id': 1, 'title': 'Paper', 'model': 'custom',
            'sections': [{'ref': 'page 1', 'text': 'Evidence'}]}


def valid():
    return json.dumps({key: 'Supported finding [page 1]' for key in summary.HEADINGS})


@pytest.mark.parametrize('bad', [summary.IncompleteGenerationError('token limit'),
                                 '{"Takeaway": "Unterminated', '{}',
                                 json.dumps({key: '' for key in summary.HEADINGS})])
def test_invalid_final_retries_writing_only(bad):
    generator = Mock(side_effect=['Evidence notes', bad, valid()])
    result = summary.summarize(Settings(), article(), generator=generator)
    assert set(result) == set(summary.HEADINGS)
    assert generator.call_count == 3
    assert generator.call_args_list[0].args[-1] != True
    for call in generator.call_args_list[1:]:
        assert call.args[-1] is True
        assert 'Evidence notes' in call.args[2]
    assert 'Start a fresh JSON object' in generator.call_args.args[2]


def test_repeated_invalid_json_has_clear_bounded_failure():
    generator = Mock(side_effect=['Evidence notes', '{"Takeaway": "broken', '{"Takeaway": "broken'])
    progress = Mock()
    with pytest.raises(ValueError, match='after 2 writing attempts'):
        summary.summarize(Settings(), article(), generator=generator, progress=progress)
    assert generator.call_count == 3
    assert ('writing', 1, 1, 1) not in [call.args for call in progress.call_args_list]


def test_truncation_retries_and_deadline_is_respected():
    generator = Mock(side_effect=['Evidence notes', summary.IncompleteGenerationError('token limit'), CorpusDeferred('window ended')])
    with pytest.raises(CorpusDeferred):
        summary.summarize(Settings(), article(), generator=generator)
    assert generator.call_count == 3


@pytest.mark.parametrize('body', [
    {'response': '{"Takeaway": "broken', 'done_reason': 'length', 'eval_count': 6144},
    {'response': valid(), 'done_reason': 'length'},
    {'response': valid(), 'done': False},
])
def test_generation_rejects_incomplete_response(monkeypatch, body):
    post = Mock(return_value=Mock(json=lambda: body))
    monkeypatch.setattr(summary.requests, 'post', post)
    with pytest.raises(summary.IncompleteGenerationError, match='incomplete response'):
        summary.generate(Settings(), 'model', 'prompt', structured=True)


def test_configurable_final_output_budget(monkeypatch):
    monkeypatch.setenv('CORPUS_FINAL_NUM_PREDICT', '8192')
    settings = load_settings()
    post = Mock(return_value=Mock(json=lambda: {'response': valid(), 'done_reason': 'stop', 'done': True}))
    monkeypatch.setattr(summary.requests, 'post', post)
    summary.generate(settings, 'model', 'prompt', structured=True)
    assert post.call_args.kwargs['json']['options']['num_predict'] == 8192
    summary.generate(settings, 'model', 'prompt')
    assert post.call_args.kwargs['json']['options']['num_predict'] == 768
