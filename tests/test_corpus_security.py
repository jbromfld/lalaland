from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from backend import corpus_api
from backend.config import load_settings
from backend.db import initialize_database
from backend.services import article_extraction as extraction, corpus_store as store
from backend.temporal import corpus


@pytest.mark.parametrize('url', [
    'http://arxiv.org/pdf/123', 'https://arxiv.org:80/a',
    'https://user@arxiv.org/a', 'https://arxiv.org\\@evil.org/a',
    'https://arxiv.org/\nfoo', 'https://arxiv.org:444/a',
])
def test_https_url_rejects_unsafe_syntax(url):
    with pytest.raises(ValueError):
        extraction.article_hostname(url)


@pytest.mark.parametrize('host', [
    'arxiv.org.evil.org', 'evil-arxiv.org', 'sub.arxiv.org',
    'arxiv.org.', 'аrxiv.org',  # Cyrillic lookalike.
])
def test_trust_requires_exact_hostname(host):
    with pytest.raises(extraction.UntrustedDomain):
        extraction.require_trusted(f'https://{host}/paper', ('arxiv.org',))


def test_config_normalizes_hosts_and_empty_trusts_none(monkeypatch):
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', ' ARXIV.org, bücher.de,arxiv.org ')
    assert load_settings().corpus_trusted_domains == ('arxiv.org', 'xn--bcher-kva.de')
    extraction.require_trusted('https://ARXIV.org/paper', load_settings().corpus_trusted_domains)
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', '')
    assert load_settings().corpus_trusted_domains == ()
    with pytest.raises(extraction.UntrustedDomain):
        extraction.require_trusted('https://arxiv.org/paper')


@pytest.mark.parametrize('value', ['*.arxiv.org', 'https://arxiv.org', 'arxiv.org:443', 'arxiv.org/abs', 'arxiv.org.'])
def test_invalid_trust_configuration(monkeypatch, value):
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', value)
    with pytest.raises(ValueError):
        load_settings()


@pytest.mark.parametrize('location,error', [
    ('https://unknown.org/paper', extraction.UntrustedDomain),
    ('http://arxiv.org/paper', ValueError),
    ('https://user@arxiv.org/paper', ValueError),
    ('//unknown.org/paper', extraction.UntrustedDomain),
])
def test_redirect_blocked_before_second_connection(monkeypatch, location, error):
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', 'arxiv.org')
    monkeypatch.setattr(extraction.socket, 'getaddrinfo', lambda *a, **kw: [(2,1,6,'',('93.184.216.34',443))])
    response = Mock(is_redirect=True, headers={'Location': location})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = Mock()
    session.get.return_value = response
    monkeypatch.setattr(extraction.requests, 'Session', lambda: session)
    with pytest.raises(error):
        extraction.download('https://arxiv.org/paper')
    assert session.get.call_count == 1
    assert session.get.call_args.kwargs['allow_redirects'] is False
    assert session.trust_env is False
    session.close.assert_called_once()


def test_unknown_host_never_connects(monkeypatch):
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', 'arxiv.org')
    session = Mock()
    monkeypatch.setattr(extraction.requests, 'Session', lambda: session)
    with pytest.raises(extraction.UntrustedDomain):
        extraction.download('https://unknown.org/paper')
    session.get.assert_not_called()


@pytest.mark.asyncio
async def test_quarantine_submission_duplicate_and_release(settings, monkeypatch):
    settings = replace(settings, corpus_trusted_domains=('arxiv.org',))
    monkeypatch.setattr(corpus_api, 'load_settings', lambda: settings)
    monkeypatch.setattr(corpus_api, 'validate_url', lambda url: url)
    app = FastAPI()
    app.include_router(corpus_api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/corpus', json={'url': 'https://example.org/paper'})
        assert response.status_code == 200
        row = response.json()
        assert row['quarantine_url'] == 'https://example.org/paper'
        assert store.queued_articles(settings) == []
        duplicate = await client.post('/api/corpus', json={'url': row['original_url'], 'model': 'missing'})
        assert duplicate.json()['id'] == row['id']
        assert duplicate.json()['quarantine_url'] == row['quarantine_url']
        assert (await client.get('/api/corpus')).json()['items'][0]['quarantine_url']
        assert (await client.post(f'/api/corpus/{row["id"]}/release')).status_code == 422
        settings = replace(settings, corpus_trusted_domains=('arxiv.org', 'example.org'))
        released = await client.post(f'/api/corpus/{row["id"]}/release')
        assert released.status_code == 200
        assert released.json()['attempt'] == 2
        assert store.get(settings, row['id'])['quarantine_url'] is None
        assert len(store.queued_articles(settings)) == 1
        assert (await client.post(f'/api/corpus/{row["id"]}/release')).status_code == 409
        assert (await client.post('/api/corpus/99999/release')).status_code == 404


def test_worker_quarantines_unknown_redirect_and_stale_attempts(settings, monkeypatch):
    settings = replace(settings, corpus_trusted_domains=('arxiv.org',))
    monkeypatch.setattr(corpus, 'load_settings', lambda: settings)
    row, _ = store.create(settings, 'https://arxiv.org/pdf/123', 'https://arxiv.org/abs/123', 'model')
    def redirect(url):
        raise extraction.UntrustedDomain('https://unknown.org/paper')
    monkeypatch.setattr(corpus, 'extract', redirect)
    summarize = Mock()
    monkeypatch.setattr(corpus, 'summarize', summarize)
    env = ActivityEnvironment()
    with pytest.raises(ApplicationError, match='not trusted'):
        env.run(corpus.extract_article, {'id': row['id'], 'attempt': 1})
    assert store.get(settings, row['id'])['quarantine_url'] == 'https://unknown.org/paper'
    with pytest.raises(ApplicationError, match='quarantined'):
        env.run(corpus.summarize_article, {'id': row['id'], 'attempt': 1})
    summarize.assert_not_called()
    initialize_database(settings)
    assert store.queued_articles(settings) == []
    store.release(settings, row['id'])
    store.quarantine(settings, row['id'], 1, 'https://old.org', 'Stale activity')
    assert store.get(settings, row['id'])['quarantine_url'] is None


def test_existing_queued_unknown_domain_is_quarantined(settings, monkeypatch):
    settings = replace(settings, corpus_trusted_domains=('arxiv.org',))
    monkeypatch.setattr(corpus, 'load_settings', lambda: settings)
    row, _ = store.create(settings, 'https://unknown.org/paper', 'https://unknown.org/paper', 'm')
    extract = Mock()
    monkeypatch.setattr(corpus, 'extract', extract)
    with pytest.raises(ApplicationError):
        ActivityEnvironment().run(corpus.extract_article, {'id': row['id'], 'attempt': 1})
    extract.assert_not_called()
    assert store.get(settings, row['id'])['quarantine_url']


def test_trusted_redirect_retains_tls_hostname_and_public_pin(monkeypatch):
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', 'arxiv.org,export.arxiv.org')
    monkeypatch.setattr(extraction.socket, 'getaddrinfo', lambda *a, **kw: [(2,1,6,'',('93.184.216.34',443))])
    responses = [Mock(is_redirect=True, headers={'Location':'https://export.arxiv.org/paper'}),
                 Mock(is_redirect=False, headers={'Content-Type':'application/pdf'})]
    for response in responses:
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
    responses[1].iter_content.return_value = [b'%PDF-test']
    session = Mock()
    session.get.side_effect = responses
    monkeypatch.setattr(extraction.requests, 'Session', lambda: session)
    adapter = Mock()
    monkeypatch.setattr(extraction.requests.adapters, 'HTTPAdapter', lambda: adapter)
    body, _, resolved = extraction.download('https://arxiv.org/paper')
    assert body == b'%PDF-test' and resolved == 'https://export.arxiv.org/paper'
    assert session.get.call_count == 2
    assert session.get.call_args.args[0] == 'https://93.184.216.34/paper'
    assert session.get.call_args.kwargs['headers']['Host'] == 'export.arxiv.org'
    assert adapter.init_poolmanager.call_args.kwargs == {
        'assert_hostname':'export.arxiv.org', 'server_hostname':'export.arxiv.org'}


def test_trusted_host_still_rejects_dns_rebinding(monkeypatch):
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', 'arxiv.org')
    answers = iter(['93.184.216.34', '127.0.0.1'])
    monkeypatch.setattr(extraction.socket, 'getaddrinfo', lambda *a, **kw: [(2,1,6,'',(next(answers),443))])
    session = Mock()
    monkeypatch.setattr(extraction.requests, 'Session', lambda: session)
    with pytest.raises(ValueError, match='private'):
        extraction.download('https://arxiv.org/paper')
    session.get.assert_not_called()
