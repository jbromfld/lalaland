from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceInput:
    id: str
    name: str
    feed_url: str
    last_polled_at: str | None  # ISO 8601, or None to use the initial pull window


@dataclass(frozen=True)
class ProcessSourceInput:
    source: SourceInput
    pipeline_started_at: str  # ISO 8601


@dataclass(frozen=True)
class ProcessSourceResult:
    source_id: str
    entries_seen: int
    entries_created: int


@dataclass(frozen=True)
class DailyBriefingResult:
    sources_processed: int
    entries_seen: int
    entries_created: int
