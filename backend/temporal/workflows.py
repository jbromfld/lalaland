from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from .models import DailyBriefingResult, ProcessSourceInput, ProcessSourceResult

with workflow.unsafe.imports_passed_through():
    from .activities import list_enabled_sources, process_source


@workflow.defn
class DailyBriefingWorkflow:
    @workflow.run
    async def run(self) -> DailyBriefingResult:
        sources = await workflow.execute_activity(
            list_enabled_sources,
            start_to_close_timeout=timedelta(seconds=30),
        )

        pipeline_started_at = workflow.now().isoformat()
        results: list[ProcessSourceResult] = []
        for source in sources:
            result = await workflow.execute_activity(
                process_source,
                ProcessSourceInput(source=source, pipeline_started_at=pipeline_started_at),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            results.append(result)

        return DailyBriefingResult(
            sources_processed=len(results),
            entries_seen=sum(result.entries_seen for result in results),
            entries_created=sum(result.entries_created for result in results),
        )
