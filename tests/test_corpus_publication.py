from datetime import date
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from backend import corpus_api
from backend.db import get_connection, initialize_database
from backend.services import article_extraction as extraction, corpus_store as store


@pytest.mark.parametrize('value, expected', [
    ('2024-02-29', date(2024, 2, 29)),
    ('2024-02-29T23:00:00-05:00', date(2024, 2, 29)),
    ('2025-02-29', None), ('2024', None), (None, None), ('', None),
])
def test_publication_metadata_date(value, expected):
    assert extraction.publication_date({'date':value}) == expected


def test_html_extraction_publication_date(monkeypatch):
    html = ('<html><head><title>Research</title>'
            '<meta property="article:published_time" content="2024-02-29T10:00:00Z">'
            '<meta property="article:modified_time" content="2025-01-10T10:00:00Z">'
            '</head><body><article>' + '<p>Research evidence for deployment and evaluation. </p>' * 30 +
            '</article></body></html>').encode()
    monkeypatch.setattr(extraction, 'download', lambda *a, **kw:(html, 'text/html', 'https://example.org/paper'))
    assert extraction.extract('https://example.org/paper')['published_date'] == date(2024, 2, 29)


@pytest.mark.parametrize('stamp, expected', [
    ('arXiv:2402.01234v2 [cs.AI]  29 Feb 2024', date(2024, 2, 29)),
    ('arXiv:2402.01234v2 [cs.AI]  31 Feb 2024', None),
    ('arXiv:2402.01234v2 [cs.AI]', None),
])
def test_pdf_extraction_arxiv_stamp_date(monkeypatch, stamp, expected):
    import pypdf
    reader = Mock()
    reader.pages = [Mock(extract_text=Mock(return_value=stamp + '\nEvidence ' * 100))]
    reader.metadata = {'/Title':'Research', '/CreationDate':'D:20251010120000'}
    monkeypatch.setattr(pypdf, 'PdfReader', Mock(return_value=reader))
    monkeypatch.setattr(extraction, 'download', lambda *a, **kw:(b'%PDF-fake', 'application/pdf', 'https://arxiv.org/pdf/2402.01234'))
    assert extraction.extract('https://arxiv.org/abs/2402.01234')['published_date'] == expected
    # PDF creation time alone is not a publication date.
    assert extraction.extract('https://example.org/paper.pdf')['published_date'] is None


@pytest.mark.asyncio
async def test_saved_search_orders_publication_before_relevance_and_paginates(settings, monkeypatch):
    ids = []
    for suffix, published, text in [
        ('old', date(2020, 1, 1), 'Kubernetes ' * 100),
        ('new', date(2025, 1, 1), 'Kubernetes deployment'),
        ('same-date', date(2025, 1, 1), 'Kubernetes deployment'),
        ('unknown', None, 'Kubernetes deployment'),
    ]:
        url = f'https://example.org/{suffix}'
        row, _ = store.create(settings, url, url, 'model')
        ids.append(row['id'])
        store.update(settings, row['id'], 1, state='ready', article_text=text, published_date=published)
    store.review(settings, ids[1], 4)
    monkeypatch.setattr(corpus_api, 'load_settings', lambda:settings)
    app = FastAPI()
    app.include_router(corpus_api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for keyword in ('', 'Kubernetes'):
            pages = []
            for page in (1, 2):
                result = (await client.get('/api/corpus', params={
                    'keyword':keyword, 'include_reviewed':'true', 'page':page, 'limit':2,
                })).json()
                assert result['total'] == 4
                pages.extend(result['items'])
            assert [row['id'] for row in pages] == [ids[2], ids[1], ids[0], ids[3]]
            assert pages[0]['published_date'] == '2025-01-01'
            assert pages[-1]['published_date'] is None
        detail = (await client.get(f'/api/corpus/{ids[1]}')).json()
        assert detail['published_date'] == '2025-01-01'
        assert (await client.get('/api/corpus')).json()['total'] == 3


def test_publication_migration_backfills_existing_records_safely(settings):
    records = [
        ('https://example.org/valid', {'date':'2024-02-29T10:00:00Z'}, '', date(2024, 2, 29)),
        ('https://example.org/invalid', {'date':'2025-02-29'}, '', None),
        ('https://example.org/missing', {}, '', None),
        ('https://arxiv.org/abs/2402.01234', {}, 'arXiv:2402.01234v2 [cs.AI] 29 Feb 2024', date(2024, 2, 29)),
    ]
    ids = []
    for url, metadata, text, expected in records:
        row, _ = store.create(settings, url, url, 'model')
        ids.append(row['id'])
        store.update(settings, row['id'], 1, metadata=metadata, article_text=text)
    # Simulate the pre-migration schema.
    with get_connection(settings) as conn:
        conn.execute('ALTER TABLE corpus_articles DROP COLUMN published_date')
        migration = Path('sql/ddl/007_corpus_publication_date.sql').read_text()
        conn.execute(migration)
        conn.execute(migration)
    initialize_database(settings)
    for article_id, (_, metadata, text, expected) in zip(ids, records):
        row = store.get(settings, article_id)
        assert row['published_date'] == expected
        assert row['metadata'] == metadata
        assert row['article_text'] == text
