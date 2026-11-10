# Shared retrieval with Lassy

[← Quickstart](../README.md)

Run commands from the repository root unless stated otherwise.

## Shared knowledge retrieval with Lassy

Lalaland publishes RSS summaries, completed corpus article text, and corpus
briefings to the sibling `lassy` retrieval service. Lassy owns chunking, embedding,
hybrid keyword/cosine retrieval, fusion and reranking. Lalaland remains the source
of truth and owns summary generation. The retrieval index can be rebuilt.

Knowledge is **disabled by default** (`knowledge_enabled=False` in
`backend/config.py`). A standalone installation needs no Lassy service, Lassy
database, embedding model, or LA-3 model. Leave `KNOWLEDGE_ENABLED` unset or false.
RSS briefings, corpus processing, and their saved-record searches remain available.
The Knowledge tab stays hidden, and knowledge query/model endpoints return a clear
disabled response without contacting Lassy or Ollama.

1. For an existing Lassy database, apply `lassy/db/002_documents.sql` and
   `lassy/db/003_practical.sql` before deploying the updated Lassy API. Follow
   [Lassy's upgrade guide](../../lassy/docs/documents.md); do not reset the index.
   New databases use Lassy's complete `db/init.sql`.
2. Set `KNOWLEDGE_ENABLED=true` and `KNOWLEDGE_SERVICE_URL` to lassy's **base URL**,
   on both backend and worker. Existing installations with only the URL must also
   opt in with `KNOWLEDGE_ENABLED=true`.
   With the default lassy Compose port, use `http://host.docker.internal:8082`
   inside Docker, or `http://127.0.0.1:8082` for native processes. Set
   `KNOWLEDGE_TIMEOUT_SECONDS` if the default 120 seconds is insufficient. In
   Kubernetes, use `http://lassy.lassy.svc.cluster.local:8000`; the chart already
   supplies that URL. A pod's localhost is not the laptop's forwarded port.
3. Apply settings to both Lalaland backend and worker, then restart them through
   their deployment owner. For GitOps, use the [runtime configuration/release
   guides](../../local-agent-environment/docs/gitops.md), not a parallel Compose
   launch. Startup applies the additive outbox
   schema and registers `knowledge-sync-schedule` when the URL is configured.
4. Backfill existing data using the same database/configuration as those services:

```bash
python -m backend.services.knowledge backfill
python -m backend.services.knowledge status
# Optional immediate delivery of one batch (default limit 25):
python -m backend.services.knowledge sync --limit 25
# Standalone Compose equivalents:
docker compose exec backend python -m backend.services.knowledge backfill
docker compose exec backend python -m backend.services.knowledge status
# Managed Kubernetes equivalents:
kubectl --context colima -n lalaland exec deployment/lalaland-backend -- python -m backend.services.knowledge backfill
kubectl --context colima -n lalaland exec deployment/lalaland-backend -- python -m backend.services.knowledge status
```

`knowledge-sync-schedule` runs daily at 07:00 America/Detroit by default. Configure
`knowledge_schedule_hour`, `knowledge_schedule_minute`, and
`knowledge_schedule_timezone` in `backend/config.py`, or override them with
`KNOWLEDGE_SCHEDULE_HOUR`, `KNOWLEDGE_SCHEDULE_MINUTE`, and
`KNOWLEDGE_SCHEDULE_TIMEZONE`. Backend startup updates the existing schedule.
It delivers batches of 25 source records for up to twenty minutes per run;
overlapping runs are skipped. Delivery stops after a failed batch, an unavailable
delivery lock, or an empty/partial batch; remaining events stay queued for the next
run. Network timeouts are limited by the remaining budget, with heartbeats between
deliveries. Each corpus record can publish both its
original text and briefing. Database triggers queue inserts, content changes and
deletes atomically with the source transaction. Review/rating changes do not
reindex. Delivery retries failed records, and versioned acknowledgements preserve
concurrent edits/deletes. `knowledge_outbox` exposes pending events, attempt counts,
and error types. A delivery outage does not block article processing. An unset
URL disables delivery; queued events remain for later synchronization.

To disable an existing integration, set `KNOWLEDGE_ENABLED=false` on backend and
worker and restart both. Backend startup pauses an existing knowledge schedule;
an in-flight sync safely returns without delivery after the worker restarts.
Optional schedule setup failures are logged without preventing core startup.
Fresh databases skip knowledge schema installation when disabled. Existing
knowledge tables and triggers are preserved so pending events and subsequent
changes/deletes remain available if you enable the integration again. No source
records or remote index data are removed. Backfill/sync/status CLI commands also
return a disabled message without database access while disabled. Re-enabling
updates/unpauses the daily schedule; run backfill when enabling it on an existing
database for the first time.

Collections are `lalaland-rss` and `lalaland-corpus`. Corpus article IDs are their
numeric source ID as a string; briefing IDs append `-briefing`. Both have the
original `source_id` in metadata. RSS indexes only the saved summary. Corpus
indexes extracted text with page/section references, plus the generated briefing
as a separate `content_type`. Only completed (`ready`) corpus records are indexed.
Corpus uses its normalized publication date, represented as midnight UTC;
unknown dates remain null. RSS uses its saved `article_published_at`. Date-only
corpus changes also queue an indexing event. After upgrading an existing index,
run the existing `backfill` command to republish dates for older documents. Also
backfill after Lassy chunking/tokenizer changes: the first delivery re-embeds
under the new pipeline fingerprint; later metadata-only changes reuse vectors.
Lassy uses `published_at` for recency ranking and preserves feedback/counts
when only metadata changes.

```bash
curl http://127.0.0.1:8000/api/knowledge/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"vision language models","top_k":10,"filters":{"content_type":"corpus_article"}}'
```

`POST /api/knowledge/query` forwards to lassy and defaults the collection filter to
both lalaland collections. Explicit collection filters can search other shared
knowledge. Scores, citations and document identifiers pass through unchanged.
The **Knowledge** dashboard tab searches both collections, with optional RSS or
corpus filtering. **Answer** is selected initially and produces a cited response
from LA-3, displayed with the shared Markdown reader. Supporting excerpts are
collapsed below the answer. Choose **Source excerpts** to inspect retrieval results
without inference; those results open immediately. **Search options** contains the
excerpt limit and model dropdown, which lists installed Ollama models and defaults
to `knowledge_model` in `backend/config.py` (`KNOWLEDGE_MODEL` overrides it). A selected model applies only to that request.
`KNOWLEDGE_AGENT_TIMEOUT_SECONDS` and `KNOWLEDGE_AGENT_INSTRUCTIONS` configure the
third agent independently of the RSS and corpus agents; it uses the shared
`OLLAMA_BASE_URL` and inference queue.

API callers can pass `"mode": "summary"` and optionally `"model": "installed-model"`
to `POST /api/knowledge/query`. Omit `mode` to retain the existing chunk response.
Summary responses add `summary` and `model`, and include the evidence excerpts in
`chunks` with their original citation labels and source links. Evidence is limited
to 24,000 UTF-8 bytes in total and 3,000 bytes per chunk. An empty retrieval skips
generation and returns a no-evidence message. `GET /api/knowledge/models` returns
the configured default, installed models, and discovery warnings.

Existing Inbox/Corpus record search remains a database view. Clients can also call
[Lassy](../../lassy/README.md) directly or use the optional
[retrieval MCP adapter](../../local-mcp-server/README.md). The adapter is not in
Lalaland's request path. [Babar](../../babar/README.md) is separate application
memory; no automatic memory writes/synchronization are implemented here.
Summaries reflect the top-k
evidence, not an exhaustive review; verify claims against the displayed sources.
Publication-date range filters and exhaustive “all matching articles” enumeration
remain subsequent features.
