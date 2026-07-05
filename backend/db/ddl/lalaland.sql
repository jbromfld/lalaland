-- Idempotent schema sync for database: lalaland
-- Matches current backend implementation in backend/db.py and backend/services/*.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.research_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    category TEXT,
    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    feed_url TEXT NOT NULL UNIQUE,
    adapter_type TEXT NOT NULL DEFAULT 'rss',
    source_weight INTEGER NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_polled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.research_sources
    ADD COLUMN IF NOT EXISTS category TEXT,
    ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS adapter_type TEXT DEFAULT 'rss',
    ADD COLUMN IF NOT EXISTS source_weight INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS last_polled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.research_sources
SET
    tags = COALESCE(tags, ARRAY[]::TEXT[]),
    adapter_type = COALESCE(adapter_type, 'rss'),
    source_weight = COALESCE(source_weight, 1),
    enabled = COALESCE(enabled, TRUE),
    created_at = COALESCE(created_at, NOW());

ALTER TABLE public.research_sources
    ALTER COLUMN tags SET DEFAULT ARRAY[]::TEXT[],
    ALTER COLUMN tags SET NOT NULL,
    ALTER COLUMN adapter_type SET DEFAULT 'rss',
    ALTER COLUMN adapter_type SET NOT NULL,
    ALTER COLUMN source_weight SET DEFAULT 1,
    ALTER COLUMN source_weight SET NOT NULL,
    ALTER COLUMN enabled SET DEFAULT TRUE,
    ALTER COLUMN enabled SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN created_at SET NOT NULL;

-- Backfill tags for legacy rows that only had category.
UPDATE public.research_sources
SET tags = ARRAY[category]
WHERE category IS NOT NULL
  AND category <> ''
  AND COALESCE(array_length(tags, 1), 0) = 0;

CREATE TABLE IF NOT EXISTS public.inbox_entries (
    id BIGSERIAL PRIMARY KEY,
    source_id UUID REFERENCES public.research_sources(id) ON DELETE SET NULL,
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
);

ALTER TABLE public.inbox_entries
    ADD COLUMN IF NOT EXISTS source_id UUID,
    ADD COLUMN IF NOT EXISTS source_name TEXT,
    ADD COLUMN IF NOT EXISTS title TEXT,
    ADD COLUMN IF NOT EXISTS canonical_url TEXT,
    ADD COLUMN IF NOT EXISTS article_url TEXT,
    ADD COLUMN IF NOT EXISTS article_published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS summary TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'new',
    ADD COLUMN IF NOT EXISTS rating SMALLINT,
    ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS discovered_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS summarized_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.inbox_entries
SET
    status = COALESCE(status, 'new'),
    discovered_at = COALESCE(discovered_at, NOW()),
    summarized_at = COALESCE(summarized_at, NOW());

ALTER TABLE public.inbox_entries
    ALTER COLUMN source_name SET NOT NULL,
    ALTER COLUMN title SET NOT NULL,
    ALTER COLUMN canonical_url SET NOT NULL,
    ALTER COLUMN article_url SET NOT NULL,
    ALTER COLUMN summary SET NOT NULL,
    ALTER COLUMN status SET DEFAULT 'new',
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN discovered_at SET DEFAULT NOW(),
    ALTER COLUMN discovered_at SET NOT NULL,
    ALTER COLUMN summarized_at SET DEFAULT NOW(),
    ALTER COLUMN summarized_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'inbox_entries_source_id_fkey'
          AND conrelid = 'public.inbox_entries'::regclass
    ) THEN
        ALTER TABLE public.inbox_entries
            ADD CONSTRAINT inbox_entries_source_id_fkey
            FOREIGN KEY (source_id) REFERENCES public.research_sources(id) ON DELETE SET NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'inbox_entries_status_check'
          AND conrelid = 'public.inbox_entries'::regclass
    ) THEN
        ALTER TABLE public.inbox_entries
            ADD CONSTRAINT inbox_entries_status_check
            CHECK (status IN ('new', 'read', 'dismissed'));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'inbox_entries_rating_check'
          AND conrelid = 'public.inbox_entries'::regclass
    ) THEN
        ALTER TABLE public.inbox_entries
            ADD CONSTRAINT inbox_entries_rating_check
            CHECK (rating BETWEEN 1 AND 5);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'inbox_entries_canonical_url_key'
          AND conrelid = 'public.inbox_entries'::regclass
    ) THEN
        ALTER TABLE public.inbox_entries
            ADD CONSTRAINT inbox_entries_canonical_url_key UNIQUE (canonical_url);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_inbox_entries_active
    ON public.inbox_entries (discovered_at DESC)
    WHERE dismissed_at IS NULL;

CREATE TABLE IF NOT EXISTS public.glucose_readings (
    timestamp TIMESTAMPTZ PRIMARY KEY,
    glucose_mgdl SMALLINT NOT NULL CHECK (glucose_mgdl > 0),
    source_device TEXT NOT NULL DEFAULT 'FreeStyle Libre',
    serial_number TEXT NOT NULL DEFAULT 'unknown',
    record_type SMALLINT,
    scan_glucose_mgdl SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.glucose_readings
    ADD COLUMN IF NOT EXISTS source_device TEXT DEFAULT 'FreeStyle Libre',
    ADD COLUMN IF NOT EXISTS serial_number TEXT DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS record_type SMALLINT,
    ADD COLUMN IF NOT EXISTS scan_glucose_mgdl SMALLINT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.glucose_readings
SET
    source_device = COALESCE(source_device, 'FreeStyle Libre'),
    serial_number = COALESCE(serial_number, 'unknown'),
    created_at = COALESCE(created_at, NOW());

ALTER TABLE public.glucose_readings
    ALTER COLUMN glucose_mgdl SET NOT NULL,
    ALTER COLUMN source_device SET DEFAULT 'FreeStyle Libre',
    ALTER COLUMN source_device SET NOT NULL,
    ALTER COLUMN serial_number SET DEFAULT 'unknown',
    ALTER COLUMN serial_number SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN created_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'glucose_readings_glucose_mgdl_check'
          AND conrelid = 'public.glucose_readings'::regclass
    ) THEN
        ALTER TABLE public.glucose_readings
            ADD CONSTRAINT glucose_readings_glucose_mgdl_check CHECK (glucose_mgdl > 0);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'glucose_readings_scan_glucose_mgdl_check'
          AND conrelid = 'public.glucose_readings'::regclass
    ) THEN
        ALTER TABLE public.glucose_readings
            ADD CONSTRAINT glucose_readings_scan_glucose_mgdl_check CHECK (
                scan_glucose_mgdl IS NULL OR scan_glucose_mgdl > 0
            );
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.nutrition_events (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    meal_name TEXT,
    est_carbs_g NUMERIC(10, 2),
    est_protein_g NUMERIC(10, 2),
    est_fat_g NUMERIC(10, 2),
    comments TEXT,
    is_buffer_meal BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.nutrition_events
    ADD COLUMN IF NOT EXISTS timestamp TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS meal_name TEXT,
    ADD COLUMN IF NOT EXISTS est_carbs_g NUMERIC(10, 2),
    ADD COLUMN IF NOT EXISTS est_protein_g NUMERIC(10, 2),
    ADD COLUMN IF NOT EXISTS est_fat_g NUMERIC(10, 2),
    ADD COLUMN IF NOT EXISTS comments TEXT,
    ADD COLUMN IF NOT EXISTS is_buffer_meal BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.nutrition_events
SET
    is_buffer_meal = COALESCE(is_buffer_meal, FALSE),
    created_at = COALESCE(created_at, NOW());

ALTER TABLE public.nutrition_events
    ALTER COLUMN timestamp SET NOT NULL,
    ALTER COLUMN is_buffer_meal SET DEFAULT FALSE,
    ALTER COLUMN is_buffer_meal SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN created_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_nutrition_events_timestamp
    ON public.nutrition_events (timestamp DESC);

CREATE TABLE IF NOT EXISTS public.apple_health_workouts (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT,
    device TEXT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    workout_type TEXT,
    activity_type TEXT,
    duration_seconds INTEGER,
    distance_meters NUMERIC(12, 3),
    avg_hr SMALLINT,
    avg_pace_sec_per_km NUMERIC(12, 3),
    elevation_ascended_meters NUMERIC(12, 3),
    calories_burned NUMERIC(12, 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_name, start_time)
);

ALTER TABLE public.apple_health_workouts
    ADD COLUMN IF NOT EXISTS source_name TEXT,
    ADD COLUMN IF NOT EXISTS device TEXT,
    ADD COLUMN IF NOT EXISTS start_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS workout_type TEXT,
    ADD COLUMN IF NOT EXISTS activity_type TEXT,
    ADD COLUMN IF NOT EXISTS duration_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS distance_meters NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS avg_hr SMALLINT,
    ADD COLUMN IF NOT EXISTS avg_pace_sec_per_km NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS elevation_ascended_meters NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS calories_burned NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.apple_health_workouts
SET created_at = COALESCE(created_at, NOW());

ALTER TABLE public.apple_health_workouts
    ALTER COLUMN start_time SET NOT NULL,
    ALTER COLUMN end_time SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN created_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'apple_health_workouts_source_name_start_time_key'
          AND conrelid = 'public.apple_health_workouts'::regclass
    ) THEN
        ALTER TABLE public.apple_health_workouts
            ADD CONSTRAINT apple_health_workouts_source_name_start_time_key
            UNIQUE (source_name, start_time);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_apple_health_workouts_start_time
    ON public.apple_health_workouts (start_time DESC);

COMMIT;
