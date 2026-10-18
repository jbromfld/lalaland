from __future__ import annotations

import logging

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec, SchedulePolicy, ScheduleOverlapPolicy, ScheduleUpdate
from temporalio.service import RPCError, RPCStatusCode

from backend.config import Settings, load_settings

from .workflows import DailyBriefingWorkflow
from .corpus import NightlyCorpusWorkflow


logger = logging.getLogger(__name__)

TASK_QUEUE = "lalaland-scheduler"
DAILY_BRIEFING_WORKFLOW_ID = "daily-briefing-workflow"
DAILY_BRIEFING_SCHEDULE_ID = "daily-briefing-schedule"


def temporal_address() -> str:
    return load_settings().temporal_address


def temporal_namespace() -> str:
    return load_settings().temporal_namespace


async def connect() -> Client:
    return await Client.connect(temporal_address(), namespace=temporal_namespace())


async def ensure_daily_briefing_schedule(client: Client, settings: Settings) -> None:
    """Idempotently registers the server-side cron Schedule that replaces the
    old in-process APScheduler job. Safe to call on every app startup."""
    handle = client.get_schedule_handle(DAILY_BRIEFING_SCHEDULE_ID)
    try:
        await handle.describe()
        return
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise

    await client.create_schedule(
        DAILY_BRIEFING_SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                DailyBriefingWorkflow.run,
                id=DAILY_BRIEFING_WORKFLOW_ID,
                task_queue=TASK_QUEUE,
            ),
            spec=ScheduleSpec(
                cron_expressions=[f"{settings.schedule_minute} {settings.schedule_hour} * * *"],
                time_zone_name=None if settings.schedule_timezone.lower() == "local" else settings.schedule_timezone,
            ),
        ),
    )
    logger.info(
        "Registered Temporal schedule '%s' for %02d:%02d (%s)",
        DAILY_BRIEFING_SCHEDULE_ID,
        settings.schedule_hour,
        settings.schedule_minute,
        settings.schedule_timezone,
    )


async def ensure_corpus_schedule(client: Client, settings: Settings) -> None:
    if not 0 <= settings.corpus_schedule_hour < settings.corpus_end_hour <= 23:
        raise ValueError('Invalid corpus processing window')
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(NightlyCorpusWorkflow.run,
            id='nightly-corpus-workflow', task_queue=TASK_QUEUE),
        spec=ScheduleSpec(cron_expressions=[f'0 {settings.corpus_schedule_hour} * * *'],
                          time_zone_name=settings.corpus_schedule_timezone),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    handle = client.get_schedule_handle('nightly-corpus-schedule')
    try:
        await handle.describe()
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
        await client.create_schedule('nightly-corpus-schedule', schedule)
    else:
        # Updating only this schedule leaves the daily briefing unchanged.
        await handle.update(lambda _: ScheduleUpdate(schedule=schedule))


async def ensure_knowledge_schedule(client: Client, settings: Settings) -> None:
    from datetime import timedelta
    from temporalio.client import ScheduleIntervalSpec
    from .knowledge import KnowledgeSyncWorkflow
    if not settings.knowledge_service_url:
        # An existing schedule safely no-ops because the activity checks configuration.
        return
    handle = client.get_schedule_handle('knowledge-sync-schedule')
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(KnowledgeSyncWorkflow.run,
            id='knowledge-sync-workflow', task_queue=TASK_QUEUE),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP))
    try:
        await handle.describe()
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
        await client.create_schedule('knowledge-sync-schedule', schedule)
    else:
        await handle.update(lambda _: ScheduleUpdate(schedule=schedule))
