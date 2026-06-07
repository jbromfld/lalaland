from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import requests
from opentelemetry import trace

from backend.adapters.html import HTMLAdapter
from backend.adapters.rss import RSSAdapter
from backend.config import Settings
from backend.db import (
    fetch_enabled_sources,
    fetch_existing_urls,
    get_connection,
    insert_inbox_entry,
    update_source_last_polled_at,
)
from backend.services.discovery import canonicalize_url, filter_new_urls
from backend.services.summarization import OllamaSummarizer


logger = logging.getLogger(__name__)
INITIAL_PULL_WINDOW = timedelta(days=14)


def _entry_is_within_pull_window(entry, cutoff: datetime) -> bool:
    if entry.published_at is None:
        return False

    return entry.published_at > cutoff


def run_daily_pipeline(settings: Settings) -> dict[str, int]:
    tracer = trace.get_tracer(__name__)
    rss_adapter = RSSAdapter()
    html_adapter = HTMLAdapter()
    summarizer = OllamaSummarizer(settings)

    result = {
        "sources_processed": 0,
        "entries_seen": 0,
        "entries_created": 0,
    }

    with tracer.start_as_current_span("pipeline.daily_run") as span:
        with get_connection(settings) as conn:
            pipeline_started_at = datetime.now(UTC)
            sources = fetch_enabled_sources(conn)

            for source in sources:
                if source.adapter_type != "rss":
                    logger.info("Skipping unsupported adapter type %s for %s", source.adapter_type, source.name)
                    continue

                result["sources_processed"] += 1
                entries = rss_adapter.fetch_entries(source.feed_url)
                cutoff = source.last_polled_at or (pipeline_started_at - INITIAL_PULL_WINDOW)
                eligible_entries = [
                    entry for entry in entries if entry.url and _entry_is_within_pull_window(entry, cutoff)
                ]
                result["entries_seen"] += len(eligible_entries)

                canonical_to_entry = {
                    canonicalize_url(entry.url): entry
                    for entry in eligible_entries
                }
                existing_urls = fetch_existing_urls(conn, list(canonical_to_entry.keys()))
                new_urls = filter_new_urls(list(canonical_to_entry.keys()), existing_urls)

                for canonical_url in new_urls:
                    entry = canonical_to_entry[canonical_url]
                    article_title = entry.title
                    article_text = (entry.summary or "").strip()

                    try:
                        extracted = html_adapter.extract_article(entry.url)
                        article_title = extracted["title"] or article_title
                        article_text = extracted["text"] or article_text
                    except requests.RequestException as exc:
                        logger.warning("Article fetch failed for %s: %s", entry.url, exc)

                    if not article_text:
                        logger.warning("Skipping %s because no article text was available", entry.url)
                        continue

                    try:
                        summary = summarizer.summarize(
                            source_name=source.name,
                            article_title=article_title,
                            article_url=entry.url,
                            article_text=article_text,
                        )
                    except (requests.RequestException, RuntimeError) as exc:
                        logger.warning("Summarization failed for %s: %s", entry.url, exc)
                        continue

                    created = insert_inbox_entry(
                        conn,
                        source_id=source.id,
                        source_name=source.name,
                        title=article_title,
                        canonical_url=canonical_url,
                        article_url=entry.url,
                        article_published_at=entry.published_at,
                        summary=summary,
                    )
                    result["entries_created"] += 1 if created else 0

                update_source_last_polled_at(conn, source.id, pipeline_started_at)
            conn.commit()

        span.set_attribute("sources_processed", result["sources_processed"])
        span.set_attribute("entries_seen", result["entries_seen"])
        span.set_attribute("entries_created", result["entries_created"])

    return result
