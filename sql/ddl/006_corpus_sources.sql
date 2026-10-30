-- Shared exact-host approvals from the Corpus UI. Quarantine records are preserved.
BEGIN;

CREATE TABLE IF NOT EXISTS corpus_sources (
 hostname TEXT PRIMARY KEY,
 approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
