from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import struct_time

import feedparser
from backend.services.article_extraction import download


@dataclass(frozen=True)
class FeedEntry:
    title: str
    url: str
    published_at: datetime | None
    summary: str | None


def _to_datetime(value: struct_time | None) -> datetime | None:
    if value is None:
        return None

    return datetime(*value[:6], tzinfo=UTC)


class RSSAdapter:
    def discover(self, feed_url: str) -> list[str]:
        return [entry.url for entry in self.fetch_entries(feed_url)]

    def fetch_entries(self, feed_url: str) -> list[FeedEntry]:
        body, _, resolved = download(feed_url, feed=True)
        feed = feedparser.parse(body, response_headers={'content-location': resolved})
        if not feed.version or (feed.bozo and not feed.entries):
            raise ValueError('The source did not return a readable RSS or Atom feed')
        entries: list[FeedEntry] = []

        for entry in feed.entries:
            link = entry.get("link")
            if not link:
                continue

            entries.append(
                FeedEntry(
                    title=entry.get("title", link),
                    url=link,
                    published_at=_to_datetime(
                        entry.get("published_parsed") or entry.get("updated_parsed")
                    ),
                    summary=entry.get("summary") or entry.get("description"),
                )
            )

        return entries
