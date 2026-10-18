from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from backend.config import load_settings
from backend.db import initialize_database
from backend.temporal.knowledge import KnowledgeSyncWorkflow, sync_knowledge
from backend.temporal.activities import list_enabled_sources, process_source
from backend.temporal.client import TASK_QUEUE, temporal_address, temporal_namespace
from backend.temporal.workflows import DailyBriefingWorkflow
from backend.temporal.corpus import CorpusWorkflow, CorpusBatchWorkflow, NightlyCorpusWorkflow, extract_article, summarize_article, fail_article, defer_article, prepare_nightly_batch


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    initialize_database(load_settings())
    client = await Client.connect(temporal_address(), namespace=temporal_namespace())
    logger.info("Connected to Temporal at %s, task queue %s", temporal_address(), TASK_QUEUE)

    with ThreadPoolExecutor(max_workers=10) as activity_executor:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[KnowledgeSyncWorkflow, DailyBriefingWorkflow, CorpusWorkflow, CorpusBatchWorkflow, NightlyCorpusWorkflow],
            activities=[sync_knowledge, list_enabled_sources, process_source, extract_article, summarize_article, fail_article, defer_article, prepare_nightly_batch],
            activity_executor=activity_executor,
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
