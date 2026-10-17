-- Additive review state; preserves existing articles and RSS records.
BEGIN;

CREATE TABLE IF NOT EXISTS corpus_reviews (
 article_id BIGINT PRIMARY KEY REFERENCES corpus_articles(id) ON DELETE CASCADE,
 rating SMALLINT CHECK (rating BETWEEN 1 AND 5),
 read_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
