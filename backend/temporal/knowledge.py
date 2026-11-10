from datetime import timedelta
import time

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from backend.config import load_settings
    from backend.services.knowledge import drain


@activity.defn
def sync_knowledge() -> dict:
    settings = load_settings()
    deadline = time.monotonic() + 20 * 60
    total = {'enabled':settings.knowledge_active, 'indexed':0, 'failed':0}
    def heartbeat():
        if activity.in_activity():
            activity.heartbeat()
            if activity.is_cancelled():
                from temporalio.exceptions import CancelledError
                raise CancelledError()
    while time.monotonic() < deadline:
        result = drain(settings, limit=25, deadline=deadline, heartbeat=heartbeat)
        total['indexed'] += result['indexed']
        total['failed'] += result['failed']
        if not result['enabled'] or result['failed'] or result['indexed'] < 25:
            break
    return total


@workflow.defn
class KnowledgeSyncWorkflow:
    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_activity(sync_knowledge,
            start_to_close_timeout=timedelta(minutes=25), heartbeat_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3))
