from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend import corpus_api
from backend.db import get_connection
from backend.services import corpus_store as store


def ready_article(settings, suffix):
    row, _ = store.create(settings, f'https://example.org/{suffix}', f'https://example.org/{suffix}', 'test-model')
    store.update(settings, row['id'], row['attempt'], state='ready', title=f'Paper {suffix}',
                 article_text='Kubernetes deployment experiment', sections=[{'ref':'page 1','text':'Evidence'}],
                 briefing={'Takeaway':'A useful engineering summary'})
    return row


def test_review_hides_articles_but_preserves_search_and_content(settings):
    read = ready_article(settings, 'read')
    rated = ready_article(settings, 'rated')
    unread = ready_article(settings, 'unread')
    first = store.review(settings, read['id'])
    assert store.review(settings, read['id'])['read_at'] == first['read_at']
    rating = store.review(settings, rated['id'], 4)
    assert rating['rating'] == 4 and rating['read_at'] is not None
    assert store.review(settings, rated['id'])['rating'] == 4
    assert store.review(settings, rated['id'], 5)['read_at'] == rating['read_at']
    active = store.search(settings, '', 1, 20)
    assert active['total'] == 1 and active['items'][0]['id'] == unread['id']
    assert store.search(settings, 'Kubernetes', 1, 20)['total'] == 1
    saved = store.search(settings, 'Kubernetes', 1, 20, include_reviewed=True)
    assert saved['total'] == 3
    assert store.search(settings, '', 2, 2, include_reviewed=True)['items'][0]['id'] == read['id']
    detail = store.get(settings, rated['id'])
    assert detail['state'] == 'ready' and detail['rating'] == 5
    assert detail['article_text'] == 'Kubernetes deployment experiment'
    assert detail['sections'] == [{'ref':'page 1','text':'Evidence'}]
    assert detail['briefing'] == {'Takeaway':'A useful engineering summary'}


@pytest.mark.asyncio
async def test_review_api(settings, monkeypatch):
    monkeypatch.setattr(corpus_api, 'load_settings', lambda: settings)
    read = ready_article(settings, 'read-api')
    rated = ready_article(settings, 'rate-api')
    queued, _ = store.create(settings, 'https://example.org/queued', 'https://example.org/queued', 'test-model')
    app = FastAPI()
    app.include_router(corpus_api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post(f'/api/corpus/{read["id"]}/read')).status_code == 200
        response = await client.post(f'/api/corpus/{rated["id"]}/rate', json={'rating':4})
        assert response.status_code == 200 and response.json()['rating'] == 4
        assert response.json()['read_at']
        active = (await client.get('/api/corpus')).json()
        assert active['total'] == 1 and active['items'][0]['id'] == queued['id']
        saved = (await client.get('/api/corpus?keyword=Kubernetes&include_reviewed=true')).json()
        assert saved['total'] == 2
        assert (await client.get(f'/api/corpus/{rated["id"]}')).json()['rating'] == 4
        for invalid in (0, 6):
            assert (await client.post(f'/api/corpus/{rated["id"]}/rate', json={'rating':invalid})).status_code == 422
        for suffix, body in (('read', {}), ('rate', {'rating':3})):
            assert (await client.post(f'/api/corpus/{queued["id"]}/{suffix}', json=body)).status_code == 409
            assert (await client.post(f'/api/corpus/999999/{suffix}', json=body)).status_code == 404
        assert (await client.get('/api/corpus?include_reviewed=true')).json()['total'] == 3


def test_review_migration_is_additive_and_idempotent(settings):
    article = ready_article(settings, 'migration')
    store.review(settings, article['id'], 3)
    migration = Path('sql/ddl/004_corpus_reviews.sql').read_text()
    with get_connection(settings) as conn:
        conn.execute(migration)
        conn.execute(migration)
    assert store.get(settings, article['id'])['rating'] == 3
    assert store.get(settings, article['id'])['article_text'] == 'Kubernetes deployment experiment'
