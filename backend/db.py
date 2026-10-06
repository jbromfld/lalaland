from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator
from uuid import UUID

from psycopg import Connection, connect
from psycopg.rows import dict_row

from backend.config import Settings


SCHEMA_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    """
    CREATE TABLE IF NOT EXISTS research_sources (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL,
        category TEXT,
        tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
        feed_url TEXT NOT NULL UNIQUE,
        source_weight INTEGER NOT NULL DEFAULT 1,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        last_polled_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    ALTER TABLE research_sources
    ADD COLUMN IF NOT EXISTS last_polled_at TIMESTAMPTZ
    """,
    """
    ALTER TABLE research_sources
    ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
    """,
    "ALTER TABLE research_sources DROP COLUMN IF EXISTS adapter_type",
    """
    UPDATE research_sources
    SET tags = ARRAY[category]
    WHERE category IS NOT NULL
      AND category <> ''
      AND COALESCE(array_length(tags, 1), 0) = 0
    """,
    """
    CREATE TABLE IF NOT EXISTS inbox_entries (
        id BIGSERIAL PRIMARY KEY,
        source_id UUID REFERENCES research_sources(id) ON DELETE SET NULL,
        source_name TEXT NOT NULL,
        title TEXT NOT NULL,
        canonical_url TEXT NOT NULL UNIQUE,
        article_url TEXT NOT NULL,
        article_published_at TIMESTAMPTZ,
        summary TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'read', 'dismissed')),
        rating SMALLINT CHECK (rating BETWEEN 1 AND 5),
        dismissed_at TIMESTAMPTZ,
        read_at TIMESTAMPTZ,
        discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        summarized_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_inbox_entries_active
    ON inbox_entries (discovered_at DESC)
    WHERE dismissed_at IS NULL
    """,
)


@dataclass(frozen=True)
class SourceRecord:
    id: UUID
    name: str
    category: str | None
    tags: list[str]
    feed_url: str
    source_weight: int
    enabled: bool
    last_polled_at: datetime | None


@contextmanager
def get_connection(settings: Settings) -> Iterator[Connection]:
    with connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def initialize_database(settings: Settings) -> None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            for statement in SCHEMA_STATEMENTS:
                cur.execute(statement)
        conn.commit()


def fetch_enabled_sources(conn: Connection) -> list[SourceRecord]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, category, tags, feed_url, source_weight, enabled, last_polled_at
            FROM research_sources
            WHERE enabled = TRUE
            ORDER BY source_weight DESC, name ASC
            """
        )
        rows = cur.fetchall()

    return [SourceRecord(**row) for row in rows]


def list_sources(settings: Settings) -> list[dict]:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    category,
                    tags,
                    feed_url,
                    source_weight,
                    enabled,
                    last_polled_at,
                    created_at
                FROM research_sources
                ORDER BY source_weight DESC, name ASC
                """
            )
            return cur.fetchall()


def create_source(
    settings: Settings,
    *,
    name: str,
    tags: list[str],
    feed_url: str,
    source_weight: int,
    enabled: bool,
) -> dict:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO research_sources (
                    name,
                    category,
                    tags,
                    feed_url,
                    source_weight,
                    enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING
                    id,
                    name,
                    category,
                    tags,
                    feed_url,
                    source_weight,
                    enabled,
                    last_polled_at,
                    created_at
                """,
                (name, tags[0] if tags else None, tags, feed_url, source_weight, enabled),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def update_source(
    settings: Settings,
    source_id: str,
    *,
    name: str,
    tags: list[str],
    feed_url: str,
    source_weight: int,
    enabled: bool,
) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE research_sources
                SET
                    name = %s,
                    category = %s,
                    tags = %s,
                    feed_url = %s,
                    source_weight = %s,
                    enabled = %s
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    category,
                    tags,
                    feed_url,
                    source_weight,
                    enabled,
                    last_polled_at,
                    created_at
                """,
                (name, tags[0] if tags else None, tags, feed_url, source_weight, enabled, source_id),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def delete_source(settings: Settings, source_id: str) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM research_sources
                WHERE id = %s
                RETURNING id
                """,
                (source_id,),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def fetch_existing_urls(conn: Connection, canonical_urls: list[str]) -> set[str]:
    if not canonical_urls:
        return set()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT canonical_url
            FROM inbox_entries
            WHERE canonical_url = ANY(%s)
            """,
            (canonical_urls,),
        )
        rows = cur.fetchall()

    return {row["canonical_url"] for row in rows}


def update_source_last_polled_at(conn: Connection, source_id: UUID, polled_at: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE research_sources
            SET last_polled_at = %s
            WHERE id = %s
            """,
            (polled_at, source_id),
        )


def insert_inbox_entry(
    conn: Connection,
    *,
    source_id: UUID,
    source_name: str,
    title: str,
    canonical_url: str,
    article_url: str,
    article_published_at: datetime | None,
    summary: str,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO inbox_entries (
                source_id,
                source_name,
                title,
                canonical_url,
                article_url,
                article_published_at,
                summary
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (canonical_url) DO NOTHING
            RETURNING id
            """,
            (
                source_id,
                source_name,
                title,
                canonical_url,
                article_url,
                article_published_at,
                summary,
            ),
        )
        inserted = cur.fetchone()

    conn.commit()
    return inserted is not None


def list_active_inbox_entries(settings: Settings) -> list[dict]:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    source_name,
                    title,
                    article_url,
                    canonical_url,
                    summary,
                    status,
                    rating,
                    read_at,
                    dismissed_at,
                    discovered_at,
                    article_published_at
                FROM inbox_entries
                WHERE dismissed_at IS NULL
                  AND read_at IS NULL
                  AND rating IS NULL
                ORDER BY discovered_at DESC
                """
            )
            return cur.fetchall()


def list_history_sources(settings: Settings) -> list[str]:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT source_name
                FROM inbox_entries
                ORDER BY source_name ASC
                """
            )
            return [row["source_name"] for row in cur.fetchall()]


def search_inbox_history(
    settings: Settings,
    *,
    days: int | None,
    source: str | None,
    keyword: str | None,
    rating: int | None,
) -> list[dict]:
    conditions = []
    params: list[str | int] = []

    if days is not None:
        conditions.append("COALESCE(article_published_at, discovered_at) >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days)
    if source:
        conditions.append("source_name = %s")
        params.append(source)
    if keyword:
        escaped_keyword = keyword.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        conditions.append(
            "(title ILIKE %s ESCAPE '!' OR summary ILIKE %s ESCAPE '!')"
        )
        pattern = f"%{escaped_keyword}%"
        params.extend((pattern, pattern))
    if rating is not None:
        conditions.append("rating = %s")
        params.append(rating)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    id,
                    source_name,
                    title,
                    article_url,
                    canonical_url,
                    summary,
                    status,
                    rating,
                    read_at,
                    dismissed_at,
                    discovered_at,
                    article_published_at
                FROM inbox_entries
                {where_clause}
                ORDER BY discovered_at DESC
                """,
                params,
            )
            return cur.fetchall()


def dismiss_inbox_entry(settings: Settings, entry_id: int) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE inbox_entries
                SET status = 'dismissed', dismissed_at = NOW()
                WHERE id = %s
                RETURNING
                    id,
                    status,
                    rating,
                    read_at,
                    dismissed_at
                """,
                (entry_id,),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def mark_inbox_entry_read(settings: Settings, entry_id: int) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE inbox_entries
                SET status = 'read', read_at = COALESCE(read_at, NOW())
                WHERE id = %s
                RETURNING
                    id,
                    status,
                    rating,
                    read_at,
                    dismissed_at
                """,
                (entry_id,),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def rate_inbox_entry(settings: Settings, entry_id: int, rating: int) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE inbox_entries
                SET status = 'read', rating = %s, read_at = COALESCE(read_at, NOW())
                WHERE id = %s
                RETURNING
                    id,
                    status,
                    rating,
                    read_at,
                    dismissed_at
                """,
                (rating, entry_id),
            )
            row = cur.fetchone()
        conn.commit()
    return row
