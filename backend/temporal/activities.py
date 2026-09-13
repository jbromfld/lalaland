from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

import requests
from temporalio import activity

from backend.adapters.html import HTMLAdapter
from backend.adapters.rss import RSSAdapter
from backend.config import load_settings
from backend.db import (
    fetch_enabled_sources,
    fetch_existing_urls,
    get_connection,
    insert_inbox_entry,
    update_source_last_polled_at,
)
from backend.services.discovery import canonicalize_url, filter_new_urls
from backend.services.summarization import OllamaSummarizer

from .models import ProcessSourceInput, ProcessSourceResult, SourceInput


logger = logging.getLogger(__name__)
INITIAL_PULL_WINDOW = timedelta(days=14)


@activity.defn
def list_enabled_sources() -> list[SourceInput]:
    settings = load_settings()
    with get_connection(settings) as conn:
        sources = fetch_enabled_sources(conn)

    return [
        SourceInput(
            id=str(source.id),
            name=source.name,
            feed_url=source.feed_url,
            last_polled_at=source.last_polled_at.isoformat() if source.last_polled_at else None,
        )
        for source in sources
        if source.adapter_type == "rss"
    ]


@activity.defn
def process_source(input: ProcessSourceInput) -> ProcessSourceResult:
    settings = load_settings()
    rss_adapter = RSSAdapter()
    html_adapter = HTMLAdapter()
    summarizer = OllamaSummarizer(settings)

    pipeline_started_at = datetime.fromisoformat(input.pipeline_started_at)
    cutoff = (
        datetime.fromisoformat(input.source.last_polled_at)
        if input.source.last_polled_at
        else pipeline_started_at - INITIAL_PULL_WINDOW
    )
    source_id = UUID(input.source.id)

    entries_created = 0

    entries = rss_adapter.fetch_entries(input.source.feed_url)
    eligible_entries = [
        entry for entry in entries if entry.url and entry.published_at and entry.published_at > cutoff
    ]

    canonical_to_entry = {canonicalize_url(entry.url): entry for entry in eligible_entries}

    with get_connection(settings) as conn:
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
                    source_name=input.source.name,
                    article_title=article_title,
                    article_url=entry.url,
                    article_text=article_text,
                )
            except (requests.RequestException, RuntimeError) as exc:
                logger.warning("Summarization failed for %s: %s", entry.url, exc)
                continue

            created = insert_inbox_entry(
                conn,
                source_id=source_id,
                source_name=input.source.name,
                title=article_title,
                canonical_url=canonical_url,
                article_url=entry.url,
                article_published_at=entry.published_at,
                summary=summary,
            )
            entries_created += 1 if created else 0

        update_source_last_polled_at(conn, source_id, pipeline_started_at)
        conn.commit()

    return ProcessSourceResult(
        source_id=input.source.id,
        entries_seen=len(eligible_entries),
        entries_created=entries_created,
    )
