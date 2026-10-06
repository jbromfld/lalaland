# Research Briefing Local Agent (la)

`la` is a local-first research briefing agent. It polls enabled RSS sources,
fetches article text, summarizes new articles with a local Ollama model, and
puts the results into a small inbox for review.

## Landscape

```text
RSS sources
        -> source registry and Temporal schedule/workflow
        -> RSS discovery and URL canonicalization
        -> article text extraction
        -> Ollama summarization
        -> Postgres inbox
        -> browser dashboard
```

The system is intentionally small and local:

- **Backend:** FastAPI service in `backend/main.py`
- **Scheduling:** a Temporal Schedule (server-side cron, registered on startup
    by `backend/temporal/client.py`) starts a `DailyBriefingWorkflow` at the
    configured time; a separate worker process (`backend/temporal/worker.py`)
    executes it against a per-source activity (`process_source`), so one
    source failing doesn't take down the whole run and every run is visible
    in the Temporal Web UI. This replaced an in-process APScheduler thread
    that silently died with the FastAPI process. See the shared Temporal
    server setup in the `temporal` repo for the server/Postgres side of this.
- **Discovery:** RSS feeds with canonical URL deduplication and article summaries
- **Summarization:** Ollama, using `granite3.3:8b` by default
- **Persistence:** Postgres stores source configuration and inbox metadata;
    raw article bodies are transient
- **Frontend:** static HTML dashboard in `frontend/index.html`
- **Operations:** OpenTelemetry setup and a `/health` endpoint

## Current API surface

- `GET /api/inbox` - list active briefing entries
- `GET /api/history` - search historical entries by date range, source, keyword, and rating
- `GET /api/history/sources` - list source names present in historical entries
- `GET /api/sources` - list configured sources
- `POST|PUT|DELETE /api/sources` - manage sources
- `POST /api/inbox/{id}/read` - mark an entry read
- `POST /api/inbox/{id}/rate` - rate an entry from 1 to 5
- `POST /api/inbox/{id}/dismiss` - dismiss an entry
- `POST /api/jobs/run-now` - start the `DailyBriefingWorkflow` immediately and
    wait for it to finish (same response shape as before; now backed by
    Temporal instead of running in-thread)

The dashboard's **Search** navigation button switches to a historical search
screen in the current page, including entries that have been read, rated, or
dismissed.

## Run locally

Prerequisites:

- Python 3.11+
- PostgreSQL
- Ollama with the configured model available
- A reachable Temporal server (see the `temporal` repo) with a `lalaland`
    namespace registered

```bash
python3 -m pip install -e ".[dev]"
ollama pull granite3.3:8b
uvicorn backend.main:app --reload &
python -m backend.temporal.worker &
```

Open <http://127.0.0.1:8000>. The backend initializes the database schema,
registers the Temporal schedule, and serves the frontend when run directly.
The worker process is required — without it, the schedule and `run-now` will
create workflow executions that never get picked up.

Configuration is read from environment variables. The main settings are
`DATABASE_URL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `SCHEDULE_HOUR`,
`SCHEDULE_MINUTE`, `SCHEDULE_TIMEZONE`,
`TEMPORAL_ADDRESS` (default `host.docker.internal:30733`), and
`TEMPORAL_NAMESPACE` (default `lalaland`).

## Run with Docker

Set the values in `.env`, then run:

```bash
docker compose up --build
```

This starts three services: `backend`, `worker`, and `frontend`. The frontend
is served by Nginx and proxies `/api` and `/health` to the backend.
PostgreSQL, Ollama, and Temporal can remain on the host; Docker is configured
to reach them through `host.docker.internal`.

## Data model

The database has two operational tables:

- `research_sources` stores source names, tags, feed URLs, adapter types,
    weights, enabled state, and polling timestamps.
- `inbox_entries` stores source metadata, canonical and original URLs, article
    timestamps, generated summaries, read state, ratings, and dismissal state.

Canonical URLs are the deduplication key. Tracking parameters such as `utm_*`,
`fbclid`, and `gclid` are removed before comparison.

## Validation

```bash
pytest
```

Runs the suite in `tests/`: pure unit tests, a Temporal workflow test using
time-skipping (no real server needed), and activity tests against a
freshly created and dropped Postgres test database.
