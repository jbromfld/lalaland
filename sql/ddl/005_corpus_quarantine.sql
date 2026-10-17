-- Additive quarantine metadata; existing articles and tables are preserved.
BEGIN;

CREATE TABLE IF NOT EXISTS corpus_quarantine (
 article_id BIGINT PRIMARY KEY REFERENCES corpus_articles(id) ON DELETE CASCADE,
 url TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
