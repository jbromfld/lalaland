from datetime import UTC, datetime, timedelta

import pytest

from backend.adapters.rss import FeedEntry
from backend.db import create_source, fetch_existing_urls, get_connection, list_sources
from backend.temporal import activities
from backend.temporal.activities import list_enabled_sources, process_source
from backend.temporal.models import ProcessSourceInput, SourceInput


@pytest.fixture(autouse=True)
def _use_test_settings(monkeypatch, settings):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    return settings


def test_list_enabled_sources_returns_only_enabled_rss_sources(settings):
    create_source(settings, name="RSS enabled", tags=[], feed_url="https://a.example/feed", adapter_type="rss", source_weight=1, enabled=True)
    create_source(settings, name="RSS disabled", tags=[], feed_url="https://b.example/feed", adapter_type="rss", source_weight=1, enabled=False)
    create_source(settings, name="HTML enabled", tags=[], feed_url="https://c.example/page", adapter_type="html", source_weight=1, enabled=True)

    sources = list_enabled_sources()

    assert [source.name for source in sources] == ["RSS enabled"]
    assert sources[0].feed_url == "https://a.example/feed"
    assert sources[0].last_polled_at is None


def test_process_source_creates_entry_and_updates_last_polled_at(settings, monkeypatch):
    created = create_source(settings, name="Feed", tags=[], feed_url="https://feed.example/rss", adapter_type="rss", source_weight=1, enabled=True)

    now = datetime.now(UTC)
    entry = FeedEntry(title="Article", url="https://feed.example/article", published_at=now, summary="teaser")

    monkeypatch.setattr(activities.RSSAdapter, "fetch_entries", lambda self, feed_url: [entry])
    monkeypatch.setattr(
        activities.HTMLAdapter,
        "extract_article",
        lambda self, url: {"title": "Extracted title", "text": "Full article body"},
    )
    monkeypatch.setattr(
        activities.OllamaSummarizer,
        "summarize",
        lambda self, **kwargs: "A short summary.",
    )

    source_input = SourceInput(
        id=str(created["id"]),
        name=created["name"],
        feed_url=created["feed_url"],
        last_polled_at=None,
    )
    pipeline_started_at = now + timedelta(seconds=1)

    result = process_source(
        ProcessSourceInput(source=source_input, pipeline_started_at=pipeline_started_at.isoformat())
    )

    assert result.entries_seen == 1
    assert result.entries_created == 1

    with get_connection(settings) as conn:
        existing = fetch_existing_urls(conn, ["https://feed.example/article"])
    assert existing == {"https://feed.example/article"}

    refreshed = {source["id"]: source for source in list_sources(settings)}
    assert refreshed[created["id"]]["last_polled_at"] is not None


def test_process_source_skips_entry_with_no_extractable_text(settings, monkeypatch):
    created = create_source(settings, name="Feed", tags=[], feed_url="https://feed.example/rss", adapter_type="rss", source_weight=1, enabled=True)

    now = datetime.now(UTC)
    entry = FeedEntry(title="Article", url="https://feed.example/empty", published_at=now, summary=None)

    monkeypatch.setattr(activities.RSSAdapter, "fetch_entries", lambda self, feed_url: [entry])
    monkeypatch.setattr(activities.HTMLAdapter, "extract_article", lambda self, url: {"title": "", "text": ""})

    source_input = SourceInput(id=str(created["id"]), name=created["name"], feed_url=created["feed_url"], last_polled_at=None)
    pipeline_started_at = now + timedelta(seconds=1)

    result = process_source(
        ProcessSourceInput(source=source_input, pipeline_started_at=pipeline_started_at.isoformat())
    )

    assert result.entries_seen == 1
    assert result.entries_created == 0
