-- Publication dates and safe backfill from previously extracted source metadata.
BEGIN;

ALTER TABLE corpus_articles ADD COLUMN IF NOT EXISTS published_date DATE;
DO $$
DECLARE article RECORD;
BEGIN
 FOR article IN
  SELECT id, COALESCE(
   substring(metadata->>'date' from '^[0-9]{4}-[0-9]{2}-[0-9]{2}'),
   CASE WHEN canonical_url LIKE 'https://arxiv.org/abs/%' THEN
    substring(article_text from 'arXiv:[[:space:]]*[^[:space:]]+v[0-9]+[[:space:]]+\[[^]]+\][[:space:]]+([0-9]{1,2}[[:space:]]+[A-Za-z]{3}[[:space:]]+[0-9]{4})')
   END) AS source_date
  FROM corpus_articles WHERE published_date IS NULL
   AND (metadata->>'date' IS NOT NULL OR canonical_url LIKE 'https://arxiv.org/abs/%')
 LOOP
  BEGIN
   UPDATE corpus_articles SET published_date=article.source_date::date
    WHERE id=article.id AND article.source_date IS NOT NULL;
  EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN
   -- Incomplete or malformed source dates remain unknown.
   NULL;
  END;
 END LOOP;
END $$;
CREATE INDEX IF NOT EXISTS idx_corpus_published ON corpus_articles
 (published_date DESC NULLS LAST, created_at DESC, id DESC);

COMMIT;
