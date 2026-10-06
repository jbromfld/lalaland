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
    source_weight INTEGER NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_polled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.research_sources
    ADD COLUMN IF NOT EXISTS category TEXT,
    ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS source_weight INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS last_polled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.research_sources
SET
    tags = COALESCE(tags, ARRAY[]::TEXT[]),
    source_weight = COALESCE(source_weight, 1),
    enabled = COALESCE(enabled, TRUE),
    created_at = COALESCE(created_at, NOW());

ALTER TABLE public.research_sources
    ALTER COLUMN tags SET DEFAULT ARRAY[]::TEXT[],
    ALTER COLUMN tags SET NOT NULL,
    ALTER COLUMN source_weight SET DEFAULT 1,
    ALTER COLUMN source_weight SET NOT NULL,
    ALTER COLUMN enabled SET DEFAULT TRUE,
    ALTER COLUMN enabled SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE public.research_sources
    DROP COLUMN IF EXISTS adapter_type;

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

COMMIT;