# Architecture and operations

[← Quickstart](../README.md)

Run commands from the repository root unless stated otherwise.

## Shared architecture

```text
LA-1: RSS feeds -> discovery and deduplication -> concise summaries -> Inbox / Search
LA-2: Article URLs -> saved queue -> extraction -> evidence notes -> briefings -> Corpus
                                      |
                    FastAPI + Temporal worker + Ollama + Postgres
                                      |
                              Browser dashboard
```

- **Backend:** FastAPI in `backend/main.py`, with LA-2 routes in `backend/corpus_api.py`.
- **Worker:** `backend/temporal/worker.py` executes both agents' workflows and synchronous activities.
- **Scheduling:** Temporal schedules are registered by `backend/temporal/client.py` at backend startup.
- **Inference:** both agents use `OLLAMA_BASE_URL`, with separate model settings. A Postgres advisory lock serializes their Ollama calls, including manual runs and overruns.
- **Dashboard:** `frontend/index.html`, served directly by FastAPI locally or by Nginx in Docker.
- **Operations:** OpenTelemetry instrumentation, Temporal execution history, and `GET /health`.

The worker must be running. A reachable Temporal server can accept workflows while
the worker is offline, but no ingestion or summarization will execute until a
worker picks them up. Shared host-service provisioning and restart recovery are managed in the sibling
[local-agent-environment](../../local-agent-environment/README.md) repository.

## Run locally

Prerequisites are Python 3.13.16, Postgres, Ollama with the configured models
installed, and a reachable Temporal server with the `lalaland` namespace.
Download any missing model with `ollama pull MODEL_NAME`.

Docker Compose reads `.env`; native Python processes require the settings to be
exported into their environment. Set database credentials and model choices for
your installation. For a host process connecting to the shared local Temporal
server, use `127.0.0.1` instead of the Docker hostname:

```bash
uv sync --locked --extra dev
source .venv/bin/activate
export TEMPORAL_ADDRESS=127.0.0.1:30733
uvicorn backend.main:app --reload
```

In a second terminal with the same environment, start the worker:

```bash
python3 -m backend.temporal.worker
```

Open <http://127.0.0.1:8000>. The backend initializes the schema, registers the
schedules, and serves the dashboard.

## Run with Docker

For a new installation, copy [.env.example](../.env.example) without overwriting an
existing `.env`:

```bash
cp -n .env.example .env
```

Edit the database credentials and service addresses for your installation.
The example includes Docker ports and optional overrides for both agents;
commented settings use the defaults in `backend/config.py`. Then run:

```bash
docker compose up --build
```

Use `docker-compose` if only the legacy CLI is installed. This starts `backend`,
`worker`, and `frontend`. Open the dashboard at `http://127.0.0.1:FRONTEND_PORT`
using the configured port. Nginx proxies `/api` and `/health` to the backend.
Host services can be reached through `host.docker.internal` from containers.

### Workflow service recovery

The worker uses `restart: unless-stopped` so a fatal Temporal polling error does
not leave processing offline indefinitely. Check `docker-compose ps -a` and
`docker-compose logs --tail=100 worker` if both agents stop processing.

With local Kubernetes on Colima, repeated Temporal `Unavailable` / “Not enough
hosts” errors can indicate a failing history pod. Check `kubectl get pods -n
temporal` and `kubectl describe pod -n temporal POD_NAME`. `OOMKilled` means the
service ran out of memory. This combined local deployment exhausted a 2 GiB
Colima VM; increasing it to 4 GiB restored capacity. Resizing requires a VM restart
and briefly interrupts all containers. Keep the existing Temporal database and
history shard count; do not reset workflow data to recover service availability.
After Temporal recovers, run `docker-compose up -d` to restore application services.

## Persistence and migrations

| Agent | Table | Stored data |
|---|---|---|
| LA-1 | `research_sources` | Feed configuration, tags, weights, enabled state, and polling timestamps |
| LA-1 | `inbox_entries` | URLs, concise summaries, timestamps, read state, ratings, and dismissal state |
| LA-2 | `corpus_articles` | URLs, metadata, extracted `article_text` and `sections`, briefing, processing state, model, and prompt version |
| LA-2 | `corpus_progress` | Current processing step, completion counts, retry attempt, and update time |
| LA-2 | `corpus_generations` | Completed evidence chunks for resumable processing |
| LA-2 | `corpus_reviews` | Read timestamps and 1–5 ratings |
| LA-2 | `corpus_quarantine` | Blocked URL, reason, and quarantine timestamp |

LA-1 feed text is transient. LA-2 retains extracted text and page/section references
for full-text search, retries, and reproducibility; downloaded PDF files are
transient. Corpus search uses PostgreSQL `tsvector` and a GIN keyword index over
titles, article text, and briefings. Canonical URLs provide deduplication, with
tracking parameters removed before comparison.

Schema initialization is idempotent. For an existing database, LA-2's additive SQL
migrations are `sql/ddl/001_corpus.sql` through `sql/ddl/005_corpus_quarantine.sql`.
They create the new corpus tables and index while preserving existing articles
and RSS records. There is no need to rerun the initial schema sync script for
these corpus additions.
