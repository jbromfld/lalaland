from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from backend.temporal.activities import list_enabled_sources, process_source
from backend.temporal.client import TASK_QUEUE, temporal_address, temporal_namespace
from backend.temporal.workflows import DailyBriefingWorkflow


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    client = await Client.connect(temporal_address(), namespace=temporal_namespace())
    logger.info("Connected to Temporal at %s, task queue %s", temporal_address(), TASK_QUEUE)

    with ThreadPoolExecutor(max_workers=10) as activity_executor:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[DailyBriefingWorkflow],
            activities=[list_enabled_sources, process_source],
            activity_executor=activity_executor,
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
