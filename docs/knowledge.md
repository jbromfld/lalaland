# Shared retrieval with Lassy

[← Quickstart](../README.md)

Run commands from the repository root unless stated otherwise.

## Shared knowledge retrieval with Lassy

Lalaland publishes RSS summaries, completed corpus article text, and corpus
briefings to the sibling `lassy` retrieval service. Lassy owns chunking, embedding,
hybrid keyword/cosine retrieval, fusion and reranking. Lalaland remains the source
of truth and owns summary generation. The retrieval index can be rebuilt.

1. Apply `lassy/db/002_documents.sql` to an existing lassy database, then rebuild/restart
   lassy. New lassy databases use its complete `db/init.sql`.
2. Set `KNOWLEDGE_SERVICE_URL` to lassy's **base URL**, on both backend and worker.
   With the default lassy Compose port, use `http://host.docker.internal:8082`
   inside Docker, or `http://127.0.0.1:8082` for native processes. Set
   `KNOWLEDGE_TIMEOUT_SECONDS` if the default 120 seconds is insufficient.
3. Restart/rebuild lalaland backend and worker. Startup applies the additive outbox
   schema and registers `knowledge-sync-schedule` when the URL is configured.
4. Backfill existing data using the same database/configuration as those services:

```bash
python -m backend.services.knowledge backfill
python -m backend.services.knowledge status
# Optional immediate delivery of one batch (default limit 25):
python -m backend.services.knowledge sync --limit 25
# Docker equivalents:
docker compose exec backend python -m backend.services.knowledge backfill
docker compose exec backend python -m backend.services.knowledge status
```

`knowledge-sync-schedule` runs every minute and delivers up to five source records
per run; overlapping runs are skipped. Each corpus record can publish both its
original text and briefing. Database triggers queue inserts, content changes and
deletes atomically with the source transaction. Review/rating changes do not
reindex. Delivery retries failed records, and versioned acknowledgements preserve
concurrent edits/deletes. `knowledge_outbox` exposes pending events, attempt counts,
and error types. A delivery outage does not block article processing. An unset
URL disables delivery; queued events remain for later synchronization.

Collections are `lalaland-rss` and `lalaland-corpus`. Corpus article IDs are their
numeric source ID as a string; briefing IDs append `-briefing`. Both have the
original `source_id` in metadata. RSS indexes only the saved summary. Corpus
indexes extracted text with page/section references, plus the generated briefing
as a separate `content_type`. Only completed (`ready`) corpus records are indexed.
Corpus publication dates remain unknown pending reliable date normalization;
RSS uses its saved `article_published_at`.

```bash
curl http://127.0.0.1:8000/api/knowledge/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"vision language models","top_k":10,"filters":{"content_type":"corpus_article"}}'
```

`POST /api/knowledge/query` forwards to lassy and defaults the collection filter to
both lalaland collections. Explicit collection filters can search other shared
knowledge. Scores, citations and document identifiers pass through unchanged.
Existing Inbox/Corpus navigation and record search remain database views; the new
knowledge endpoint is the hybrid retrieval interface. Clients can also call lassy
directly or use `local-mcp-server`.

This integration provides retrieved evidence. Cross-article summary generation,
publication-date range filters, and exhaustive “all matching articles” enumeration
are subsequent features; top-k chunk retrieval does not establish completeness.
