from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from backend import corpus_api
from backend.db import get_connection
from backend.services import corpus_store as store
from backend.temporal import corpus


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['queued', 'extracting', 'summarizing', 'failed', 'ready', 'quarantined'])
async def test_delete_any_article_and_related_records(settings, monkeypatch, state):
    monkeypatch.setattr(corpus_api, 'load_settings', lambda: settings)
    row, _ = store.create(settings, 'https://arxiv.org/paper', 'https://arxiv.org/paper', 'model')
    store.update(settings, row['id'], 1, state='summarizing', title='Unique delete evidence', article_text='Saved text')
    store.set_progress(settings, row['id'], 1, 1, 'reading', 1, 2, 1)
    store.save_generation(settings, row, 'digest', 'Evidence notes')
    store.update(settings, row['id'], 1, state='ready')
    store.review(settings, row['id'], 4)
    if state == 'quarantined':
        store.update(settings, row['id'], 1, state='queued')
        store.quarantine(settings, row['id'], 1, row['original_url'], 'Unknown domain')
    else:
        store.update(settings, row['id'], 1, state=state)
    other, _ = store.create(settings, 'https://arxiv.org/other', 'https://arxiv.org/other', 'model')
    app = FastAPI()
    app.include_router(corpus_api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.delete(f'/api/corpus/{row["id"]}')
        assert response.status_code == 200
        assert response.json() == {'id': row['id'], 'deleted': True}
        assert (await client.get(f'/api/corpus/{row["id"]}')).status_code == 404
        assert (await client.delete(f'/api/corpus/{row["id"]}')).status_code == 404
    with get_connection(settings) as conn:
        for table in ('corpus_progress', 'corpus_generations', 'corpus_reviews', 'corpus_quarantine'):
            assert conn.execute(f'SELECT count(*) AS n FROM {table} WHERE article_id=%s', (row['id'],)).fetchone()['n'] == 0
    assert store.search(settings, 'Unique delete', 1, 20, include_reviewed=True)['total'] == 0
    assert store.get(settings, other['id']) is not None
    # A deleted identity can be submitted again as a fresh article.
    new, created = store.create(settings, row['original_url'], row['canonical_url'], 'model')
    assert created and new['id'] != row['id']


def test_deleted_queue_snapshot_stops_without_fetch_or_model(settings, monkeypatch):
    monkeypatch.setattr(corpus, 'load_settings', lambda: settings)
    row, _ = store.create(settings, 'https://arxiv.org/paper', 'https://arxiv.org/paper', 'model')
    data = store.queued_articles(settings)[0]
    store.delete(settings, row['id'])
    extract, summarize = Mock(), Mock()
    monkeypatch.setattr(corpus, 'extract', extract)
    monkeypatch.setattr(corpus, 'summarize', summarize)
    for activity in (corpus.extract_article, corpus.summarize_article):
        with pytest.raises(ApplicationError, match='Article was deleted'):
            ActivityEnvironment().run(activity, data)
    extract.assert_not_called()
    summarize.assert_not_called()
    store.save_generation(settings, row, 'late', 'Late evidence')
    store.set_progress(settings, row['id'], 1, 1, 'writing', 1, 1, 1)
    store.update(settings, row['id'], 1, state='ready')
    assert store.get(settings, row['id']) is None


def test_delete_during_model_call_does_not_recreate_article(settings, monkeypatch):
    settings = replace(settings, corpus_trusted_domains=('arxiv.org',))
    monkeypatch.setattr(corpus, 'load_settings', lambda: settings)
    row, _ = store.create(settings, 'https://arxiv.org/paper', 'https://arxiv.org/paper', 'model')
    store.update(settings, row['id'], 1, title='Paper', article_text='Text', sections=[{'ref':'page 1', 'text':'a'*13000}])
    def generate(*args, **kwargs):
        store.delete(settings, row['id'])
        return 'Evidence notes [page 1]'
    generate = Mock(side_effect=generate)
    monkeypatch.setattr(corpus, 'generate', generate)
    with pytest.raises(ApplicationError, match='Article was deleted'):
        ActivityEnvironment().run(corpus.summarize_article, {'id':row['id'], 'attempt':1})
    assert generate.call_count == 1
    assert store.get(settings, row['id']) is None
