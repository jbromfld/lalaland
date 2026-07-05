from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterator
from uuid import UUID

from psycopg import Connection, connect
from psycopg.rows import dict_row

from backend.config import Settings


@dataclass(frozen=True)
class SourceRecord:
    id: UUID
    name: str
    category: str | None
    tags: list[str]
    feed_url: str
    adapter_type: str
    source_weight: int
    enabled: bool
    last_polled_at: datetime | None


@contextmanager
def get_connection(settings: Settings) -> Iterator[Connection]:
    with connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def fetch_enabled_sources(conn: Connection) -> list[SourceRecord]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, category, tags, feed_url, adapter_type, source_weight, enabled, last_polled_at
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
                    adapter_type,
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
    adapter_type: str,
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
                    adapter_type,
                    source_weight,
                    enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    id,
                    name,
                    category,
                    tags,
                    feed_url,
                    adapter_type,
                    source_weight,
                    enabled,
                    last_polled_at,
                    created_at
                """,
                (name, tags[0] if tags else None, tags, feed_url, adapter_type, source_weight, enabled),
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
    adapter_type: str,
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
                    adapter_type = %s,
                    source_weight = %s,
                    enabled = %s
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    category,
                    tags,
                    feed_url,
                    adapter_type,
                    source_weight,
                    enabled,
                    last_polled_at,
                    created_at
                """,
                (name, tags[0] if tags else None, tags, feed_url, adapter_type, source_weight, enabled, source_id),
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


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)
    return start, end


def list_glucose_readings(settings: Settings, start_at: datetime, end_at: datetime) -> list[dict]:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    timestamp,
                    glucose_mgdl,
                    source_device,
                    serial_number,
                    record_type,
                    scan_glucose_mgdl,
                    created_at
                FROM glucose_readings
                WHERE timestamp >= %s
                  AND timestamp < %s
                ORDER BY timestamp ASC
                """,
                (start_at, end_at),
            )
            return cur.fetchall()


def upsert_glucose_reading(
    conn: Connection,
    *,
    timestamp: datetime,
    glucose_mgdl: int,
    source_device: str,
    serial_number: str,
    record_type: int | None,
    scan_glucose_mgdl: int | None,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO glucose_readings (
                timestamp,
                glucose_mgdl,
                source_device,
                serial_number,
                record_type,
                scan_glucose_mgdl
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (timestamp) DO NOTHING
            RETURNING timestamp
            """,
            (timestamp, glucose_mgdl, source_device, serial_number, record_type, scan_glucose_mgdl),
        )
        row = cur.fetchone()
    return row is not None


def delete_glucose_reading(settings: Settings, timestamp: datetime) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM glucose_readings
                WHERE timestamp = %s
                RETURNING timestamp
                """,
                (timestamp,),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def list_nutrition_events(settings: Settings, start_at: datetime, end_at: datetime) -> list[dict]:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    timestamp,
                    meal_name,
                    est_carbs_g,
                    est_protein_g,
                    est_fat_g,
                    comments,
                    is_buffer_meal,
                    created_at
                FROM nutrition_events
                WHERE timestamp >= %s
                  AND timestamp < %s
                ORDER BY timestamp DESC, id DESC
                """,
                (start_at, end_at),
            )
            return cur.fetchall()


def insert_nutrition_event(
    settings: Settings,
    *,
    timestamp: datetime,
    meal_name: str | None,
    est_carbs_g: float | None,
    est_protein_g: float | None,
    est_fat_g: float | None,
    comments: str | None,
    is_buffer_meal: bool,
) -> dict:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO nutrition_events (
                    timestamp,
                    meal_name,
                    est_carbs_g,
                    est_protein_g,
                    est_fat_g,
                    comments,
                    is_buffer_meal
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    id,
                    timestamp,
                    meal_name,
                    est_carbs_g,
                    est_protein_g,
                    est_fat_g,
                    comments,
                    is_buffer_meal,
                    created_at
                """,
                (
                    timestamp,
                    meal_name,
                    est_carbs_g,
                    est_protein_g,
                    est_fat_g,
                    comments,
                    is_buffer_meal,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def update_nutrition_event(
    settings: Settings,
    event_id: int,
    *,
    timestamp: datetime,
    meal_name: str | None,
    est_carbs_g: float | None,
    est_protein_g: float | None,
    est_fat_g: float | None,
    comments: str | None,
    is_buffer_meal: bool,
) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE nutrition_events
                SET
                    timestamp = %s,
                    meal_name = %s,
                    est_carbs_g = %s,
                    est_protein_g = %s,
                    est_fat_g = %s,
                    comments = %s,
                    is_buffer_meal = %s
                WHERE id = %s
                RETURNING
                    id,
                    timestamp,
                    meal_name,
                    est_carbs_g,
                    est_protein_g,
                    est_fat_g,
                    comments,
                    is_buffer_meal,
                    created_at
                """,
                (
                    timestamp,
                    meal_name,
                    est_carbs_g,
                    est_protein_g,
                    est_fat_g,
                    comments,
                    is_buffer_meal,
                    event_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def delete_nutrition_event(settings: Settings, event_id: int) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM nutrition_events
                WHERE id = %s
                RETURNING id
                """,
                (event_id,),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def list_apple_health_workouts(settings: Settings, start_at: datetime, end_at: datetime) -> list[dict]:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    source_name,
                    device,
                    start_time,
                    end_time,
                    workout_type,
                    activity_type,
                    duration_seconds,
                    distance_meters,
                    avg_hr,
                    avg_pace_sec_per_km,
                    elevation_ascended_meters,
                    calories_burned,
                    created_at
                FROM apple_health_workouts
                WHERE start_time >= %s
                  AND start_time < %s
                ORDER BY start_time ASC, id ASC
                """,
                (start_at, end_at),
            )
            return cur.fetchall()


def fetch_latest_apple_health_workout_start_time(conn: Connection, source_name: str | None = None) -> datetime | None:
    with conn.cursor() as cur:
        if source_name is None:
            cur.execute(
                """
                SELECT MAX(start_time) AS latest_start_time
                FROM apple_health_workouts
                """
            )
        else:
            cur.execute(
                """
                SELECT MAX(start_time) AS latest_start_time
                FROM apple_health_workouts
                WHERE source_name = %s
                """,
                (source_name,),
            )
        row = cur.fetchone()

    return row["latest_start_time"] if row else None


def upsert_apple_health_workout(
    conn: Connection,
    *,
    source_name: str | None,
    device: str | None,
    start_time: datetime,
    end_time: datetime,
    workout_type: str | None,
    activity_type: str | None,
    duration_seconds: int | None,
    distance_meters: float | None,
    avg_hr: int | None,
    avg_pace_sec_per_km: float | None,
    elevation_ascended_meters: float | None,
    calories_burned: float | None,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO apple_health_workouts (
                source_name,
                device,
                start_time,
                end_time,
                workout_type,
                activity_type,
                duration_seconds,
                distance_meters,
                avg_hr,
                avg_pace_sec_per_km,
                elevation_ascended_meters,
                calories_burned
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_name, start_time) DO UPDATE
            SET
                device = COALESCE(EXCLUDED.device, apple_health_workouts.device),
                end_time = COALESCE(EXCLUDED.end_time, apple_health_workouts.end_time),
                workout_type = COALESCE(EXCLUDED.workout_type, apple_health_workouts.workout_type),
                activity_type = COALESCE(EXCLUDED.activity_type, apple_health_workouts.activity_type),
                duration_seconds = COALESCE(EXCLUDED.duration_seconds, apple_health_workouts.duration_seconds),
                distance_meters = COALESCE(EXCLUDED.distance_meters, apple_health_workouts.distance_meters),
                avg_hr = COALESCE(EXCLUDED.avg_hr, apple_health_workouts.avg_hr),
                avg_pace_sec_per_km = COALESCE(EXCLUDED.avg_pace_sec_per_km, apple_health_workouts.avg_pace_sec_per_km),
                elevation_ascended_meters = COALESCE(EXCLUDED.elevation_ascended_meters, apple_health_workouts.elevation_ascended_meters),
                calories_burned = COALESCE(EXCLUDED.calories_burned, apple_health_workouts.calories_burned)
            RETURNING id
            """,
            (
                source_name,
                device,
                start_time,
                end_time,
                workout_type,
                activity_type,
                duration_seconds,
                distance_meters,
                avg_hr,
                avg_pace_sec_per_km,
                elevation_ascended_meters,
                calories_burned,
            ),
        )
        row = cur.fetchone()
    return row is not None


def delete_apple_health_workout(settings: Settings, workout_id: int) -> dict | None:
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM apple_health_workouts
                WHERE id = %s
                RETURNING id
                """,
                (workout_id,),
            )
            row = cur.fetchone()
        conn.commit()
    return row


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


def search_inbox_entries(
    settings: Settings,
    *,
    query: str | None = None,
    source: str | None = None,
    label: str | None = None,
    rating: int | None = None,
    sort: str = "recent",
    limit: int = 10,
) -> list[dict]:
    clauses: list[str] = []
    params: list[object] = []

    if query:
        clauses.append(
            """
            (
                i.title ILIKE %s
                OR i.summary ILIKE %s
                OR i.article_url ILIKE %s
                OR i.source_name ILIKE %s
            )
            """
        )
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern, pattern])

    if source:
        clauses.append("(i.source_name ILIKE %s OR rs.name ILIKE %s)")
        pattern = f"%{source}%"
        params.extend([pattern, pattern])

    if label:
        clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM unnest(COALESCE(rs.tags, ARRAY[]::TEXT[])) AS tag
                WHERE tag ILIKE %s
            )
            """
        )
        params.append(f"%{label}%")

    if rating is not None:
        clauses.append("i.rating = %s")
        params.append(rating)

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order_clause = (
        "ORDER BY i.rating DESC NULLS LAST, i.discovered_at DESC"
        if sort == "rank"
        else "ORDER BY i.discovered_at DESC"
    )
    limit_value = max(1, min(limit, 50))

    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    i.id,
                    i.source_id,
                    i.source_name,
                    rs.tags AS source_tags,
                    i.title,
                    i.article_url,
                    i.canonical_url,
                    i.summary,
                    i.status,
                    i.rating,
                    i.read_at,
                    i.dismissed_at,
                    i.discovered_at,
                    i.article_published_at
                FROM inbox_entries i
                LEFT JOIN research_sources rs ON rs.id = i.source_id
                {where_clause}
                {order_clause}
                LIMIT %s
                """,
                (*params, limit_value),
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
