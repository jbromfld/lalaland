import uuid
import os
import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from backend.temporal.corpus import CorpusWorkflow


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['success','transient','permanent','quarantined'])
async def test_corpus_workflow(mode):
    events=[]
    @activity.defn(name='extract_article')
    async def extract(data:dict) -> None:
        events.append('extract')
        if mode == 'quarantined': raise ApplicationError('Unknown domain', type='CorpusQuarantined', non_retryable=True)
        if mode == 'permanent': raise ValueError('Unreadable scan')
        if mode == 'transient' and events.count('extract') == 1: raise RuntimeError('Temporary network error')
    @activity.defn(name='summarize_article')
    async def summarize(data:dict) -> None:
        events.append('summarize')
    @activity.defn(name='fail_article')
    async def fail(data:dict) -> None:
        events.append(data['error'])
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue=f'corpus-test-{uuid.uuid4()}'
        async with Worker(env.client,task_queue=queue,workflows=[CorpusWorkflow],activities=[extract,summarize,fail]):
            await env.client.execute_workflow(CorpusWorkflow.run,{'id':1,'attempt':1},id=str(uuid.uuid4()),task_queue=queue)
    if mode == 'quarantined':
        assert events == ['extract']
    elif mode == 'permanent':
        assert events == ['extract','ValueError: Unreadable scan']
    else:
        assert events[-1] == 'summarize'
        assert events.count('extract') == (2 if mode == 'transient' else 1)


@pytest.mark.skipif(os.getenv('CORPUS_E2E') != '1', reason='Opt-in live integration test')
@pytest.mark.asyncio
async def test_corpus_live_paper(settings, monkeypatch):
    """Opt in: downloads the example paper and runs actual local inference."""
    from concurrent.futures import ThreadPoolExecutor
    from backend.services import corpus_store as store
    from backend.temporal.corpus import extract_article, summarize_article, fail_article
    monkeypatch.setenv('DATABASE_URL',settings.database_url)
    model=os.getenv('CORPUS_E2E_MODEL',settings.corpus_model)
    row,_=store.create(settings,'https://arxiv.org/pdf/2607.01077','https://arxiv.org/abs/2607.01077',model)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue=f'corpus-live-{uuid.uuid4()}'
        with ThreadPoolExecutor(max_workers=3) as executor:
            async with Worker(env.client,task_queue=queue,workflows=[CorpusWorkflow],
                              activities=[extract_article,summarize_article,fail_article],activity_executor=executor):
                await env.client.execute_workflow(CorpusWorkflow.run,{'id':row['id'],'attempt':1},
                                                 id=str(uuid.uuid4()),task_queue=queue)
    saved=store.get(settings,row['id'])
    assert saved['state'] == 'ready', saved['error']
    assert saved['model'] == model
    assert saved['metadata']['arxiv_version'].startswith('2607.01077v')
    assert len(saved['sections']) == 35
    assert saved['briefing']['Practical experiment']
    # Schema re-initialization and new connections preserve the searchable record.
    from backend.db import initialize_database
    initialize_database(settings)
    assert store.search(settings,'message passing',1,20)['total'] == 1
