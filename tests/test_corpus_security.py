from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
import requests
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
    'arxiv.org.evil.org', 'evil-arxiv.org',
    'arxiv.org.', 'аrxiv.org',  # Cyrillic lookalike.
])
def test_trust_rejects_hosts_outside_trusted_domain(host):
    with pytest.raises(extraction.UntrustedDomain):
        extraction.require_trusted(f'https://{host}/paper', ('arxiv.org',))


def test_config_normalizes_domains_and_empty_trusts_none(monkeypatch):
    assert load_settings().corpus_trusted_domains == ('arxiv.org', 'neurips.cc')
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', ' ARXIV.org, bücher.de,arxiv.org ')
    assert load_settings().corpus_trusted_domains == ('arxiv.org', 'xn--bcher-kva.de')
    extraction.require_trusted('https://ARXIV.org/paper', load_settings().corpus_trusted_domains)
    extraction.require_trusted('https://export.arxiv.org/paper', load_settings().corpus_trusted_domains)
    extraction.require_trusted('https://sub.bücher.de/paper', load_settings().corpus_trusted_domains)
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
    monkeypatch.setattr(
        corpus_api, 'installed_models',
        Mock(side_effect=requests.ConnectionError('Ollama is offline')),
    )
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
    def redirect(url, *args, **kwargs):
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
    monkeypatch.setenv('CORPUS_TRUSTED_DOMAINS', 'arxiv.org')
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


@pytest.mark.asyncio
async def test_ui_source_approval_shared_with_submission_and_worker(settings, monkeypatch):
    settings = replace(settings, corpus_trusted_domains=())
    monkeypatch.setattr(corpus_api, 'load_settings', lambda: settings)
    monkeypatch.setattr(corpus, 'load_settings', lambda: settings)
    monkeypatch.setattr(corpus_api, 'validate_url', lambda url: url)
    monkeypatch.setattr(corpus_api, 'resolve_model', lambda model: 'model')
    app = FastAPI()
    app.include_router(corpus_api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        row = (await client.post('/api/corpus', json={'url':'https://example.org/paper'})).json()
        store.quarantine(settings, row['id'], 1, 'https://cdn.example.net/paper', 'Unknown redirect')
        released = await client.post(f'/api/corpus/{row["id"]}/release', json={'approve_sources':True})
        assert released.status_code == 200
        assert released.json()['state'] == 'queued'
        assert released.json()['attempt'] == 2
        assert set(store.approved_hosts(settings)) == {'example.org', 'cdn.example.net'}
        duplicate = await client.post(f'/api/corpus/{row["id"]}/release', json={'approve_sources':True})
        assert duplicate.status_code == 409
        next_row = (await client.post('/api/corpus', json={'url':'https://example.org/next'})).json()
        assert next_row['quarantine_url'] is None
        subdomain = (await client.post('/api/corpus', json={'url':'https://other.example.org/paper'})).json()
        assert subdomain['quarantine_url']

    initialize_database(settings)
    extracted = Mock(return_value={'article_text':'text', 'resolved_url':'https://cdn.example.net/paper'})
    monkeypatch.setattr(corpus, 'extract', extracted)
    env = ActivityEnvironment()
    env.run(corpus.extract_article, {'id':row['id'], 'attempt':2})
    assert set(extracted.call_args.kwargs['approved_hosts']) == {'example.org', 'cdn.example.net'}
    assert extracted.call_args.args[1] == ()
    monkeypatch.setattr(corpus, 'summarize', Mock(return_value={'summary':'Ready'}))
    env.run(corpus.summarize_article, {'id':row['id'], 'attempt':2})
    assert store.get(settings, row['id'])['state'] == 'ready'


@pytest.mark.asyncio
@pytest.mark.parametrize('blocked_url', ['https://private.example/paper', 'http://example.org/paper'])
async def test_source_approval_does_not_bypass_url_validation(settings, monkeypatch, blocked_url):
    monkeypatch.setattr(corpus_api, 'load_settings', lambda: settings)
    row, _ = store.create(settings, 'https://example.org/paper', 'https://example.org/paper', 'model')
    store.quarantine(settings, row['id'], 1, blocked_url, 'Blocked')
    def validate(url):
        if url == blocked_url:
            raise ValueError('Article URLs must resolve only to public addresses')
    monkeypatch.setattr(corpus_api, 'validate_url', validate)
    with pytest.raises(corpus_api.HTTPException) as exc:
        await corpus_api.release(row['id'], corpus_api.ReleaseRequest(approve_sources=True))
    assert exc.value.status_code == 422
    assert store.approved_hosts(settings) == ()
    assert store.get(settings, row['id'])['quarantine_url'] == blocked_url
    assert store.queued_articles(settings) == []


def test_release_changed_quarantine_does_not_approve_sources(settings):
    row, _ = store.create(settings, 'https://example.org/p', 'https://example.org/p', 'model', 'Untrusted')
    store.quarantine(settings, row['id'], 1, 'https://new.example/p', 'New redirect')
    assert store.release(settings, row['id'], approved_hosts=('example.org',),
                         quarantine_url='https://example.org/p') is None
    assert store.approved_hosts(settings) == ()
    assert store.get(settings, row['id'])['quarantine_url'] == 'https://new.example/p'


def test_download_approved_host_still_blocks_unknown_redirect(monkeypatch):
    monkeypatch.setattr(extraction.socket, 'getaddrinfo', lambda *a, **kw: [(2,1,6,'',('93.184.216.34',443))])
    response = Mock(is_redirect=True, headers={'Location':'https://unknown.org/paper'})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = Mock()
    session.get.return_value = response
    monkeypatch.setattr(extraction.requests, 'Session', lambda: session)
    with pytest.raises(extraction.UntrustedDomain):
        extraction.download('https://example.org/paper', (), approved_hosts=('example.org',))
    assert session.get.call_count == 1


def test_approved_host_does_not_trust_its_subdomains():
    extraction.require_trusted('https://example.org/p', (), approved_hosts=('example.org',))
    with pytest.raises(extraction.UntrustedDomain):
        extraction.require_trusted('https://sub.example.org/p', (), approved_hosts=('example.org',))
