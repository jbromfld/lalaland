import uuid

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from backend.temporal.models import ProcessSourceInput, ProcessSourceResult, SourceInput
from backend.temporal.workflows import DailyBriefingWorkflow


@activity.defn(name="list_enabled_sources")
async def fake_list_enabled_sources() -> list[SourceInput]:
    return [
        SourceInput(id="source-1", name="Source One", feed_url="https://one.example/feed", last_polled_at=None),
        SourceInput(id="source-2", name="Source Two", feed_url="https://two.example/feed", last_polled_at=None),
    ]


@activity.defn(name="process_source")
async def fake_process_source(input: ProcessSourceInput) -> ProcessSourceResult:
    return ProcessSourceResult(source_id=input.source.id, entries_seen=3, entries_created=1)


@pytest.mark.asyncio
async def test_daily_briefing_workflow_aggregates_per_source_results():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[DailyBriefingWorkflow],
            activities=[fake_list_enabled_sources, fake_process_source],
        ):
            result = await env.client.execute_workflow(
                DailyBriefingWorkflow.run,
                id=f"test-workflow-{uuid.uuid4()}",
                task_queue=task_queue,
            )

    assert result.sources_processed == 2
    assert result.entries_seen == 6
    assert result.entries_created == 2


@pytest.mark.asyncio
async def test_daily_briefing_workflow_handles_no_sources():
    @activity.defn(name="list_enabled_sources")
    async def empty_sources() -> list[SourceInput]:
        return []

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[DailyBriefingWorkflow],
            activities=[empty_sources, fake_process_source],
        ):
            result = await env.client.execute_workflow(
                DailyBriefingWorkflow.run,
                id=f"test-workflow-{uuid.uuid4()}",
                task_queue=task_queue,
            )

    assert result.sources_processed == 0
    assert result.entries_seen == 0
    assert result.entries_created == 0
