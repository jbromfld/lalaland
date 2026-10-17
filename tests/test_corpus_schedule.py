from datetime import UTC, datetime, timedelta
from dataclasses import replace
from unittest.mock import AsyncMock, Mock
import uuid
import pytest
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment, ActivityEnvironment
from temporalio.worker import Worker
with workflow.unsafe.imports_passed_through():
    from backend.services import corpus_store as store
    from backend.services.ollama_queue import CorpusDeferred, check_deadline, inference_slot
    from backend.temporal.corpus import NightlyCorpusWorkflow, CorpusBatchWorkflow, CorpusWorkflow
    from backend.temporal import corpus


@workflow.defn(name='CorpusBatchWorkflow')
class BlockingBatch:
    @workflow.run
    async def run(self,manual:bool=False) -> dict:
        return await workflow.execute_activity('hold_batch',result_type=dict,
            start_to_close_timeout=timedelta(minutes=5))


def test_window_reserves_time_for_model_call(settings):
    with pytest.raises(CorpusDeferred):
        check_deadline(settings,(datetime.now(UTC)+timedelta(seconds=60)).isoformat())
    check_deadline(settings,(datetime.now(UTC)+timedelta(hours=1)).isoformat())


def test_generation_checkpoint_scopes_model_and_prompt_version(settings):
    row,_=store.create(settings,'https://example.org/a','https://example.org/a','first')
    store.save_generation(settings,row,'digest','Completed evidence')
    assert store.cached_generation(settings,row,'digest') == 'Completed evidence'
    assert store.cached_generation(settings,{**row,'model':'second'},'digest') is None
    assert store.cached_generation(settings,{**row,'prompt_version':'v2'},'digest') is None


def test_inference_lock_blocks_other_session(settings):
    from backend.db import get_connection
    from backend.services.ollama_queue import OLLAMA_LOCK
    with inference_slot(settings):
        with get_connection(settings) as conn:
            assert not conn.execute('SELECT pg_try_advisory_lock(%s) AS acquired',(OLLAMA_LOCK,)).fetchone()['acquired']
    with inference_slot(settings):
        pass


def test_expired_window_never_calls_model(settings,monkeypatch):
    settings=replace(settings,corpus_trusted_domains=('example.org',))
    monkeypatch.setattr(corpus,'load_settings',lambda:settings)
    row,_=store.create(settings,'https://example.org/b','https://example.org/b','custom')
    store.update(settings,row['id'],1,title='Paper',article_text='Text',sections=[{'ref':'page 1','text':'a'*600}])
    generate=Mock()
    monkeypatch.setattr(corpus,'generate',generate)
    with pytest.raises(CorpusDeferred):
        ActivityEnvironment().run(corpus.summarize_article,{'id':row['id'],'attempt':1,'deadline':datetime.now(UTC).isoformat()})
    generate.assert_not_called()


def test_resume_reuses_completed_evidence(settings,monkeypatch):
    settings=replace(settings,corpus_trusted_domains=('example.org',))
    import json
    from backend.services.corpus_summary import HEADINGS
    monkeypatch.setattr(corpus,'load_settings',lambda:settings)
    row,_=store.create(settings,'https://example.org/c','https://example.org/c','custom')
    store.update(settings,row['id'],1,title='Paper',article_text='Text',sections=[{'ref':'page 1','text':'a'*13000}])
    calls=[]
    def generate(settings,model,prompt,structured=False):
        calls.append(structured)
        if len(calls)==2:
            raise CorpusDeferred('Window ended')
        return json.dumps({k:'Evidence [page 1]' for k in HEADINGS}) if structured else 'Saved notes'
    monkeypatch.setattr(corpus,'generate',generate)
    env=ActivityEnvironment()
    data={'id':row['id'],'attempt':1}
    with pytest.raises(CorpusDeferred): env.run(corpus.summarize_article,data)
    env.run(corpus.defer_article,data)
    env.run(corpus.summarize_article,data)
    assert calls == [False,False,False,True]  # The first evidence chunk is reused on resume.
    assert store.get(settings,row['id'])['state']=='ready'


@pytest.mark.asyncio
async def test_nightly_schedule_is_explicit_and_separate():
    from backend.config import load_settings
    from backend.temporal.client import ensure_corpus_schedule
    from temporalio.service import RPCError,RPCStatusCode
    client=Mock()
    handle=Mock(describe=AsyncMock(side_effect=RPCError('missing',RPCStatusCode.NOT_FOUND,b'')), update=AsyncMock())
    client.get_schedule_handle.return_value=handle
    client.create_schedule=AsyncMock()
    await ensure_corpus_schedule(client,load_settings())
    schedule=client.create_schedule.call_args.args[1]
    assert schedule.spec.cron_expressions==['0 3 * * *']
    assert schedule.spec.time_zone_name=='America/Detroit'
    client.get_schedule_handle.assert_called_once_with('nightly-corpus-schedule')


@pytest.mark.asyncio
@pytest.mark.parametrize('deferred',[False,True])
async def test_nightly_batch_is_sequential_and_stops_on_deferral(deferred):
    events=[]
    @activity.defn(name='prepare_nightly_batch')
    async def prepare(manual:bool=False) -> dict:
        return {'deadline':(datetime.now(UTC)+timedelta(hours=1)).isoformat(),
                'articles':[{'id':1,'attempt':1},{'id':2,'attempt':1}]}
    @activity.defn(name='extract_article')
    async def extract(data:dict) -> None:
        events.append(('extract',data['id']))
    @activity.defn(name='summarize_article')
    async def summarize(data:dict) -> None:
        if deferred: raise CorpusDeferred('Window ended')
        events.append(('ready',data['id']))
    @activity.defn(name='defer_article')
    async def defer(data:dict) -> None:
        events.append(('defer',data['id']))
    @activity.defn(name='fail_article')
    async def fail(data:dict) -> None:
        events.append(('fail',data['id']))
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue=f'nightly-{uuid.uuid4()}'
        async with Worker(env.client,task_queue=queue,workflows=[NightlyCorpusWorkflow,CorpusBatchWorkflow,CorpusWorkflow],
                          activities=[prepare,extract,summarize,defer,fail]):
            result=await env.client.execute_workflow(NightlyCorpusWorkflow.run,id=str(uuid.uuid4()),task_queue=queue)
    if deferred:
        assert events==[('extract',1),('defer',1)]
        assert result=={'processed':0,'remaining':2}
    else:
        assert events==[('extract',1),('ready',1),('extract',2),('ready',2)]
        assert result=={'processed':2,'remaining':0}


@pytest.mark.asyncio
async def test_manual_override_starts_one_batch_and_handles_running(settings,monkeypatch):
    import httpx
    from fastapi import FastAPI
    from backend import corpus_api
    from temporalio.exceptions import WorkflowAlreadyStartedError
    monkeypatch.setattr(corpus_api,'load_settings',lambda:settings)
    app=FastAPI()
    app.include_router(corpus_api.router)
    app.state.temporal_client=Mock(start_workflow=AsyncMock())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert not (await client.post('/api/corpus/run-now')).json()['started']
        app.state.temporal_client.start_workflow.assert_not_called()
        store.create(settings,'https://example.org/manual','https://example.org/manual','custom')
        result=(await client.post('/api/corpus/run-now')).json()
        assert result['started']
        call=app.state.temporal_client.start_workflow.call_args
        assert call.args[1] is True and call.kwargs['id']=='corpus-batch-active'
        app.state.temporal_client.start_workflow.side_effect=WorkflowAlreadyStartedError('corpus-batch-active','CorpusBatchWorkflow')
        result=(await client.post('/api/corpus/run-now')).json()
        assert not result['started'] and 'already running' in result['message']


def test_manual_override_bypasses_nightly_window(settings,monkeypatch):
    settings=replace(settings,corpus_schedule_hour=3,corpus_end_hour=5)
    monkeypatch.setattr(corpus,'load_settings',lambda:settings)
    class Noon(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,10,15,16,0,tzinfo=UTC).astimezone(tz)
    monkeypatch.setattr(corpus,'datetime',Noon)
    store.create(settings,'https://example.org/manual-window','https://example.org/manual-window','custom')
    assert corpus.prepare_nightly_batch(False)['articles']==[]
    manual=corpus.prepare_nightly_batch(True)
    assert len(manual['articles'])==1
    assert datetime.fromisoformat(manual['deadline'])==datetime(2026,10,15,18,0,tzinfo=UTC)


@pytest.mark.asyncio
async def test_scheduled_request_reuses_running_manual_batch():
    import asyncio
    from datetime import timedelta
    started=asyncio.Event()
    release=asyncio.Event()
    @activity.defn(name='hold_batch')
    async def hold_batch() -> dict:
        started.set()
        await release.wait()
        return {'processed':1}
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue=f'overlap-{uuid.uuid4()}'
        async with Worker(env.client,task_queue=queue,workflows=[NightlyCorpusWorkflow,BlockingBatch],activities=[hold_batch]):
            manual=await env.client.start_workflow(BlockingBatch.run,True,id='corpus-batch-active',task_queue=queue)
            await asyncio.wait_for(started.wait(),10)
            try:
                result=await env.client.execute_workflow(NightlyCorpusWorkflow.run,id=str(uuid.uuid4()),task_queue=queue)
                assert result=={'already_running':True}
            finally:
                release.set()
            assert await manual.result()=={'processed':1}
