import json
from dataclasses import replace
from unittest.mock import Mock
import pytest
from backend.config import Settings, load_settings
from backend.services import article_extraction as extraction
from backend.services import corpus_summary as summary
from backend import corpus_api


@pytest.mark.parametrize('url, expected', [
 ('https://arxiv.org/pdf/2607.01077','https://arxiv.org/abs/2607.01077'),
 ('https://arxiv.org/pdf/2607.01077v3.pdf','https://arxiv.org/abs/2607.01077v3'),
 ('https://arxiv.org/abs/2607.01077v2','https://arxiv.org/abs/2607.01077v2'),
 ('https://example.org/paper?utm_source=x','https://example.org/paper'),
])
def test_canonical(url, expected):
    assert extraction.canonical_article_url(url) == expected


@pytest.mark.parametrize('url', ['file:///tmp/paper','http://user:pass@example.org','http://localhost','https://example.org:999'])
def test_private_or_invalid_urls(monkeypatch, url):
    monkeypatch.setattr(extraction.socket, 'getaddrinfo', lambda *a,**kw:[(2,1,6,'',('127.0.0.1',80))])
    with pytest.raises(ValueError): extraction.validate_url(url)


def test_chunks_cover_all_text():
    sections = [{'ref':'page 1','text':'a'*25001}, {'ref':'page 2','text':'b'*12000}]
    parts = list(summary.chunks(sections))
    import re
    assert re.sub(r'\[page \d+\]\n|\n\n', '', ''.join(parts)) == 'a'*25001+'b'*12000
    assert all(len(p) < 12020 for p in parts)


def test_summary_selected_model_and_structure(monkeypatch):
    calls=[]
    def generate(settings, model, prompt, structured=False):
        calls.append(model)
        return json.dumps({k:'Evidence [page 1]' for k in summary.HEADINGS}) if structured else 'Notes [page 1]'
    monkeypatch.setattr(summary, 'generate', generate)
    article = {'model':'custom:8b','title':'Paper','sections':[{'ref':'page 1','text':'a'*13000}]}
    result = summary.summarize(load_settings(), article)
    assert set(result) == set(summary.HEADINGS)
    assert calls == ['custom:8b']*3
    assert load_settings().ollama_model != 'custom:8b'


def test_invalid_briefing(monkeypatch):
    monkeypatch.setattr(summary,'generate',lambda *a,**k:'{}')
    with pytest.raises(ValueError):
        summary.summarize(load_settings(), {'model':'x','title':'t','sections':[]})


def test_model_resolution(monkeypatch):
    settings=replace(load_settings(),corpus_model='default',ollama_model='rss')
    monkeypatch.setattr(corpus_api,'load_settings',lambda:settings)
    monkeypatch.setattr(corpus_api,'installed_models',lambda s:['other'])
    assert corpus_api.resolve_model(None) == 'default'
    assert corpus_api.resolve_model('other') == 'other'
    with pytest.raises(corpus_api.HTTPException) as error: corpus_api.resolve_model('missing')
    assert error.value.status_code == 422


def test_discovery_failure_preserves_default(monkeypatch):
    import requests
    def unavailable(s): raise requests.ConnectionError()
    monkeypatch.setattr(corpus_api,'installed_models',unavailable)
    assert corpus_api.models()['error']
    assert corpus_api.resolve_model(None) == load_settings().corpus_model
    with pytest.raises(corpus_api.HTTPException) as error: corpus_api.resolve_model('custom')
    assert error.value.status_code == 503


def test_unsupported_content(monkeypatch):
    monkeypatch.setattr(extraction, 'download', lambda url:(b'abc','application/octet-stream',url))
    with pytest.raises(ValueError,match='Unsupported'): extraction.extract('https://example.org/paper')


def test_store_search_and_retry(settings):
    from backend.services import corpus_store as store
    row, created = store.create(settings,'https://example.org/a','https://example.org/a','first')
    assert created
    duplicate, created = store.create(settings,'https://example.org/a','https://example.org/a','second')
    assert not created and duplicate['model'] == 'first'
    store.update(settings,row['id'],1,article_text='Unique Kubernetes deployment evidence',state='failed')
    assert store.search(settings,'Kubernetes',1,20)['total'] == 1
    retried = store.retry(settings,row['id'],'second')
    assert retried['attempt'] == 2 and retried['model'] == 'second'
    store.update(settings,row['id'],1,state='ready')
    assert store.get(settings,row['id'])['state'] == 'queued'
    assert store.retry(settings,row['id'],'third') is None


def test_extraction_limits(monkeypatch):
    html = ('<html><head><title>Research</title></head><body><article><h1>Research</h1>' +
            ''.join(f'<p>Experiment {i} describes a deployment system and its evaluation under production workloads with {i+10} workers.</p>' for i in range(20)) + '</p></article></body></html>').encode()
    monkeypatch.setattr(extraction,'download',lambda url:(html,'text/html',url))
    result = extraction.extract('https://example.org/paper')
    assert result['sections'] and result['title'] == 'Research'
    monkeypatch.setattr(extraction,'MAX_CHARS',100)
    with pytest.raises(ValueError,match='extraction limit'): extraction.extract('https://example.org/paper')


def test_redirect_private_destination(monkeypatch):
    monkeypatch.setattr(extraction.socket,'getaddrinfo', lambda host,*a,**k:[(2,1,6,'',('127.0.0.1' if host=='localhost' else '93.184.216.34',443))])
    response=Mock(is_redirect=True,headers={'Location':'http://localhost/secret'})
    response.__enter__=Mock(return_value=response)
    response.__exit__=Mock(return_value=False)
    session=Mock()
    session.get.return_value=response
    monkeypatch.setattr(extraction.requests,'Session',lambda:session)
    with pytest.raises(ValueError,match='public'): extraction.download('https://example.org/paper')
    assert session.get.call_count == 1


def test_existing_schema_and_concurrent_duplicates(settings):
    from concurrent.futures import ThreadPoolExecutor
    from backend.db import initialize_database
    from backend.services import corpus_store as store
    initialize_database(settings)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:store.create(settings,'https://example.org/p','https://example.org/p','m'),range(4)))
    assert sum(created for _,created in results) == 1
    assert len({r['id'] for r,_ in results}) == 1
    assert store.search(settings,'',2,1)['items'] == []


@pytest.mark.asyncio
async def test_submission_duplicate_and_retry(settings, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from unittest.mock import AsyncMock
    from backend.services import corpus_store as store
    monkeypatch.setattr(corpus_api,'load_settings',lambda:settings)
    monkeypatch.setattr(corpus_api,'validate_url',lambda url:url)
    monkeypatch.setattr(corpus_api,'installed_models',lambda s:['custom'])
    app=FastAPI()
    app.include_router(corpus_api.router)
    client=Mock(start_workflow=AsyncMock())
    app.state.temporal_client=client
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as http:
        response=await http.post('/api/corpus',json={'url':'https://arxiv.org/pdf/2607.01077','model':'custom'})
        assert response.status_code == 200
        row=response.json()
        assert row['model'] == 'custom'
        assert row['state'] == 'queued'
        client.start_workflow.assert_not_called()
        duplicate=await http.post('/api/corpus',json={'url':'https://arxiv.org/abs/2607.01077','model':'missing'})
        assert duplicate.json()['id'] == row['id']
        assert (await http.post(f'/api/corpus/{row["id"]}/retry',json={})).status_code == 409
        store.update(settings,row['id'],1,state='failed')
        response=await http.post(f'/api/corpus/{row["id"]}/retry',json={'model':'custom'})
        assert response.json()['attempt'] == 2
        client.start_workflow.assert_not_called()
        assert (await http.get('/api/corpus?limit=1')).json()['total'] == 1
        assert (await http.get(f'/api/corpus/{row["id"]}')).json()['model'] == 'custom'


def test_pdf_nul_characters_are_removed(monkeypatch):
    import pypdf
    reader=Mock()
    reader.pages=[Mock(extract_text=lambda:('Engineering results\x00 '*50))]
    reader.metadata={'/Title':'Research\x00 title'}
    monkeypatch.setattr(pypdf,'PdfReader',lambda stream:reader)
    monkeypatch.setattr(extraction,'download',lambda url:(b'%PDF-fake','application/pdf',url))
    result=extraction.extract('https://example.org/paper.pdf')
    assert '\x00' not in result['article_text']
    assert result['title'] == 'Research title'


def test_activity_retry_reuses_text_and_model(settings, monkeypatch):
    from temporalio.testing import ActivityEnvironment
    from backend.temporal import corpus
    from backend.services import corpus_store as store
    monkeypatch.setattr(corpus,'load_settings',lambda:settings)
    row,_=store.create(settings,'https://example.org/p','https://example.org/p','custom')
    extracted=Mock(return_value={'title':'Paper','article_text':'text','sections':[{'ref':'page 1','text':'text'}],
                                 'metadata':{},'resolved_url':'https://example.org/p'})
    monkeypatch.setattr(corpus,'extract',extracted)
    monkeypatch.setattr(corpus,'summarize',lambda settings,article,heartbeat,**kwargs:{'model':article['model']})
    env=ActivityEnvironment()
    data={'id':row['id'],'attempt':1}
    env.run(corpus.extract_article,data)
    env.run(corpus.fail_article,{**data,'error':'Ollama unavailable'})
    retried=store.retry(settings,row['id'],'replacement')
    retry_data={'id':row['id'],'attempt':retried['attempt']}
    env.run(corpus.extract_article,retry_data)
    env.run(corpus.summarize_article,retry_data)
    saved=store.get(settings,row['id'])
    assert saved['state'] == 'ready'
    assert saved['briefing']['model'] == 'replacement'
    assert extracted.call_count == 1
    env.run(corpus.summarize_article,retry_data)
    assert store.get(settings,row['id'])['state'] == 'ready'


@pytest.mark.parametrize('payload',[{}, {'models':None}, {'models':[{'name':None}]}])
def test_invalid_model_list(monkeypatch, payload):
    monkeypatch.setattr(summary.requests,'get',lambda *a,**k:Mock(json=lambda:payload))
    with pytest.raises(ValueError,match='model list'): summary.installed_models(load_settings())


@pytest.mark.parametrize('payload',[{}, {'response':None}, {'response':'<think>reasoning only</think>'}])
def test_invalid_generation_response(monkeypatch, payload):
    monkeypatch.setattr(summary.requests,'post',lambda *a,**k:Mock(json=lambda:payload))
    with pytest.raises(ValueError): summary.generate(load_settings(),'custom','prompt')


def test_unicode_chunk_byte_budget():
    text='工程🙂 '*6000
    parts=list(summary.chunks([{'ref':'page 1','text':text}]))
    assert all(len(p.encode('utf-8')) <= 12000 for p in parts)
    assert ''.join(p.split('\n',1)[1] for p in parts) == text


def test_nonshrinking_reduction_fails(monkeypatch):
    monkeypatch.setattr(summary,'generate',lambda *a,**k:'n'*11000)
    with pytest.raises(ValueError,match='condense'):
        summary.summarize(load_settings(),{'model':'custom','title':'paper','sections':[{'ref':'page 1','text':'abc'}]})


def test_additive_migration_preserves_existing_data(settings):
    from pathlib import Path
    from backend.db import get_connection, create_source
    source=create_source(settings,name='Existing feed',tags=['ops'],feed_url='https://example.org/rss',source_weight=1,enabled=True)
    migration='\n'.join(Path(f'sql/ddl/{name}').read_text() for name in ['001_corpus.sql','002_corpus_progress.sql','003_corpus_generations.sql'])
    with get_connection(settings) as conn:
        conn.execute("""INSERT INTO inbox_entries(source_id,source_name,title,canonical_url,article_url,summary)
            VALUES (%s,'Existing feed','Existing article','https://example.org/old','https://example.org/old','Existing summary')""",(source['id'],))
        conn.commit()
        conn.execute(migration)
        conn.execute(migration)
        assert conn.execute('SELECT name FROM research_sources WHERE id=%s',(source['id'],)).fetchone()['name'] == 'Existing feed'
        assert conn.execute("SELECT summary FROM inbox_entries WHERE canonical_url='https://example.org/old'").fetchone()['summary'] == 'Existing summary'


def test_summary_reports_progress(monkeypatch):
    events=[]
    monkeypatch.setattr(summary,'generate',lambda settings,model,prompt,structured=False:
                        json.dumps({k:'Evidence [page 1]' for k in summary.HEADINGS}) if structured else 'Notes')
    article={'model':'custom','title':'Paper','sections':[{'ref':'page 1','text':'a'*13000}]}
    summary.summarize(load_settings(),article,progress=lambda *args:events.append(args))
    assert events == [('reading',1,2,0),('reading',1,2,1),('reading',2,2,1),('reading',2,2,2),
                      ('writing',1,1,0),('writing',1,1,1)]


def test_progress_is_persistent_and_ignores_stale_attempts(settings):
    from backend.services import corpus_store as store
    row,_=store.create(settings,'https://example.org/progress','https://example.org/progress','custom')
    store.update(settings,row['id'],1,state='summarizing')
    store.set_progress(settings,row['id'],1,1,'reading',2,10,1)
    assert store.get(settings,row['id'])['progress']['current'] == 2
    assert store.search(settings,'',1,20)['items'][0]['progress']['completed'] == 1
    store.set_progress(settings,row['id'],1,2,'reading',1,10,0)
    store.set_progress(settings,row['id'],1,1,'reading',9,10,8)
    assert store.get(settings,row['id'])['progress']['activity_attempt'] == 2
    assert store.get(settings,row['id'])['progress']['current'] == 1
    store.update(settings,row['id'],1,state='failed')
    store.retry(settings,row['id'],'replacement')
    assert store.get(settings,row['id'])['progress'] is None
    store.set_progress(settings,row['id'],1,2,'writing',1,1,0)
    assert store.get(settings,row['id'])['progress'] is None
    store.update(settings,row['id'],2,state='summarizing')
    store.set_progress(settings,row['id'],2,1,'reading',1,10,0)
    assert store.get(settings,row['id'])['progress']['current'] == 1


def test_corpus_model_config_is_independent(monkeypatch):
    monkeypatch.delenv('CORPUS_MODEL',raising=False)
    monkeypatch.setenv('OLLAMA_MODEL','rss-model')
    settings=load_settings()
    assert settings.corpus_model==Settings.corpus_model and settings.ollama_model=='rss-model'
    monkeypatch.setenv('CORPUS_MODEL','corpus-model')
    settings=load_settings()
    assert settings.corpus_model=='corpus-model' and settings.ollama_model=='rss-model'


def test_final_writing_has_its_own_timeout(monkeypatch):
    settings=load_settings()
    post=Mock(return_value=Mock(json=lambda:{'response':'Generated text'}))
    monkeypatch.setattr(summary.requests,'post',post)
    summary.generate(settings,'custom','Prompt',structured=True)
    assert post.call_args.kwargs['timeout']==settings.corpus_final_timeout_seconds
    summary.generate(settings,'custom','Prompt')
    assert post.call_args.kwargs['timeout']==settings.corpus_ollama_timeout_seconds
