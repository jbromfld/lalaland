import json
from unittest.mock import Mock

import pytest
from langsmith import tracing_context

from backend.config import Settings
from backend.services import corpus_summary as summary


def test_corpus_trace_groups_model_calls_without_settings(monkeypatch):
    briefing = {key: 'Evidence [page 1]' for key in summary.HEADINGS}
    response = Mock()
    response.json.side_effect = [
        {'response': 'Notes [page 1]'},
        {'response': 'More notes [page 1]'},
        {'response': json.dumps(briefing)},
    ]
    monkeypatch.setattr(summary.requests, 'post', Mock(return_value=response))
    article = {
        'id': 'article-id', 'attempt': 2, 'model': 'custom:8b', 'title': 'Paper',
        'original_url': 'https://arxiv.org/abs/example',
        'sections': [{'ref': 'page 1', 'text': 'a' * 13000}],
    }
    completed = []
    with tracing_context(enabled=True, client=Mock()):
        result = summary.summarize(
            Settings(database_url='secret-database-url'), article,
            langsmith_extra={'on_end': completed.append},
        )

    assert result == briefing
    root, = completed
    assert root.name == 'corpus.summarize'
    assert root.inputs == {'article': {key: value for key, value in article.items() if key != 'sections'}}
    assert root.outputs == briefing
    assert len(root.child_runs) == 3
    for child in root.child_runs:
        assert child.name == 'corpus.generate'
        assert child.run_type == 'llm'
        assert child.parent_run_id == root.id
        assert child.inputs['model'] == 'custom:8b'
        assert set(child.inputs) == {'model', 'prompt', 'structured'}
        assert 'corpus' in child.tags
    assert [child.inputs['structured'] for child in root.child_runs] == [False, False, True]


def test_corpus_generation_failure_is_traced(monkeypatch):
    response = Mock()
    response.json.return_value = {'response': ''}
    monkeypatch.setattr(summary.requests, 'post', Mock(return_value=response))
    completed = []
    with tracing_context(enabled=True, client=Mock()):
        with pytest.raises(ValueError, match='empty response'):
            summary.generate(
                Settings(), 'custom:8b', 'Extract evidence',
                langsmith_extra={'on_end': completed.append},
            )
    run, = completed
    assert 'Ollama returned an empty response' in run.error
