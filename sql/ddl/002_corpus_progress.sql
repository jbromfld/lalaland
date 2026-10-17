-- Additive processing visibility; preserves all existing article and RSS data.
BEGIN;

CREATE TABLE IF NOT EXISTS corpus_progress (
 article_id BIGINT PRIMARY KEY REFERENCES corpus_articles(id) ON DELETE CASCADE,
 attempt INTEGER NOT NULL, activity_attempt INTEGER NOT NULL,
 stage TEXT NOT NULL, current INTEGER NOT NULL, total INTEGER NOT NULL,
 completed INTEGER NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMIT;
