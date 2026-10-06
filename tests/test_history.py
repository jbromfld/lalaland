from datetime import UTC, datetime, timedelta

import pytest

from backend.db import (
    create_source,
    dismiss_inbox_entry,
    insert_inbox_entry,
    list_history_sources,
    rate_inbox_entry,
    search_inbox_history,
)


@pytest.fixture(autouse=True)
def _use_test_settings(monkeypatch, settings):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    return settings


def _insert_entry(settings, source, *, title, summary, published_at):
    from backend.db import get_connection

    with get_connection(settings) as conn:
        insert_inbox_entry(
            conn,
            source_id=source["id"],
            source_name=source["name"],
            title=title,
            canonical_url=f"https://example.test/{title.lower().replace(' ', '-')}",
            article_url="https://example.test/article",
            article_published_at=published_at,
            summary=summary,
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM inbox_entries WHERE canonical_url = %s",
                (f"https://example.test/{title.lower().replace(' ', '-')}",),
            )
            return cur.fetchone()["id"]


def test_search_history_filters_historical_entries(settings):
    source_one = create_source(
        settings,
        name="Research One",
        tags=[],
        feed_url="https://one.example/feed",
        source_weight=1,
        enabled=True,
    )
    source_two = create_source(
        settings,
        name="Research Two",
        tags=[],
        feed_url="https://two.example/feed",
        source_weight=1,
        enabled=True,
    )
    now = datetime.now(UTC)
    recent_id = _insert_entry(
        settings,
        source_one,
        title="Recent Climate Report",
        summary="A detailed summary",
        published_at=now - timedelta(days=5),
    )
    _insert_entry(
        settings,
        source_two,
        title="Old Climate Report",
        summary="An older summary",
        published_at=now - timedelta(days=40),
    )
    dismissed_id = _insert_entry(
        settings,
        source_two,
        title="Recent Ocean Report",
        summary="The ocean discovery",
        published_at=now - timedelta(days=2),
    )
    dismiss_inbox_entry(settings, dismissed_id)
    rate_inbox_entry(settings, recent_id, 4)

    all_entries = search_inbox_history(
        settings, days=None, source=None, keyword=None, rating=None
    )
    assert len(all_entries) == 3
    assert {entry["status"] for entry in all_entries} == {"read", "dismissed", "new"}

    filtered = search_inbox_history(
        settings,
        days=30,
        source="Research One",
        keyword="climate",
        rating=4,
    )
    assert [entry["id"] for entry in filtered] == [recent_id]

    assert [
        entry["title"]
        for entry in search_inbox_history(
            settings, days=30, source=None, keyword="ocean", rating=None
        )
    ] == ["Recent Ocean Report"]


def test_history_sources_includes_historical_source_names(settings):
    source = create_source(
        settings,
        name="Archived source",
        tags=[],
        feed_url="https://archived.example/feed",
        source_weight=1,
        enabled=False,
    )
    _insert_entry(
        settings,
        source,
        title="Archived Article",
        summary="Saved summary",
        published_at=datetime.now(UTC),
    )

    assert list_history_sources(settings) == ["Archived source"]
