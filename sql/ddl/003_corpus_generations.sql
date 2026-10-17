-- Additive checkpoints for resumable overnight processing.
BEGIN;

CREATE TABLE IF NOT EXISTS corpus_generations (
 article_id BIGINT NOT NULL REFERENCES corpus_articles(id) ON DELETE CASCADE,
 model TEXT NOT NULL, prompt_version TEXT NOT NULL, prompt_hash TEXT NOT NULL,
 response TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(article_id,model,prompt_version,prompt_hash)
);
COMMIT;
