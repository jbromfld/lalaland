-- Additive corpus migration. Does not alter existing application tables.
BEGIN;

CREATE TABLE IF NOT EXISTS corpus_articles (
 id BIGSERIAL PRIMARY KEY, original_url TEXT NOT NULL,
 canonical_url TEXT NOT NULL UNIQUE, resolved_url TEXT, title TEXT,
 metadata JSONB NOT NULL DEFAULT '{}', article_text TEXT,
 sections JSONB NOT NULL DEFAULT '[]', briefing JSONB NOT NULL DEFAULT '{}',
 state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','extracting','summarizing','ready','failed')),
 error TEXT, model TEXT NOT NULL, prompt_version TEXT NOT NULL DEFAULT 'engineering-v1',
 attempt INTEGER NOT NULL DEFAULT 1,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 search_document TSVECTOR GENERATED ALWAYS AS (
 to_tsvector('english', coalesce(title,'') || ' ' || coalesce(article_text,'') || ' ' || briefing::text)
 ) STORED
);
CREATE INDEX IF NOT EXISTS idx_corpus_search ON corpus_articles USING GIN(search_document);

COMMIT;
