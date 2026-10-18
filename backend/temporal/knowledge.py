from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from backend.config import load_settings
    from backend.services.knowledge import drain


@activity.defn
def sync_knowledge() -> dict:
    return drain(load_settings(), limit=5)


@workflow.defn
class KnowledgeSyncWorkflow:
    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_activity(sync_knowledge,
            start_to_close_timeout=timedelta(minutes=25),
            retry_policy=RetryPolicy(maximum_attempts=3))
