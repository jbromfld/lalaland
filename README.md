# Research Briefing Local Agent (la)

`la` is a local-first research briefing agent. It polls enabled RSS sources,
fetches article text, summarizes new articles with a local Ollama model, and
puts the results into a small inbox for review.

## Landscape

```text
RSS sources
        -> source registry and scheduler
        -> RSS discovery and URL canonicalization
        -> article text extraction
        -> Ollama summarization
        -> Postgres inbox
        -> browser dashboard
```

The system is intentionally small and local:

- **Backend:** synchronous FastAPI service in `backend/main.py`
- **Scheduling:** APScheduler starts the daily pipeline at the configured time
- **Discovery:** RSS and HTML adapters with canonical URL deduplication
- **Summarization:** Ollama, using `granite3.3:8b` by default
- **Persistence:** Postgres stores source configuration and inbox metadata;
    raw article bodies are transient
- **Frontend:** static HTML dashboard in `frontend/index.html`
- **Operations:** OpenTelemetry setup and a `/health` endpoint

## Current API surface

- `GET /api/inbox` - list active briefing entries
- `GET /api/sources` - list configured sources
- `POST|PUT|DELETE /api/sources` - manage sources
- `GET /api/schedule/today` - load today's calendar schedule
- `POST /api/inbox/{id}/read` - mark an entry read
- `POST /api/inbox/{id}/rate` - rate an entry from 1 to 5
- `POST /api/inbox/{id}/dismiss` - dismiss an entry
- `POST /api/jobs/run-now` - run the ingestion pipeline immediately

## Run locally

Prerequisites:

- Python 3.11+
- PostgreSQL
- Ollama with the configured model available

```bash
python3 -m pip install -r backend/requirements.txt
ollama pull granite3.3:8b
uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000>. The backend initializes the database schema and
serves the frontend when run directly.

Configuration is read from environment variables. The main settings are
`DATABASE_URL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `SCHEDULE_HOUR`,
`SCHEDULE_MINUTE`, `SCHEDULE_TIMEZONE`, and `GOOGLE_CALENDAR_ICS_URL`.

## Run with Docker

Set the values in `.env`, then run:

```bash
docker compose up --build
```

The frontend is served by Nginx and proxies `/api` and `/health` to the
backend. PostgreSQL and Ollama can remain on the host; Docker is configured to
reach them through `host.docker.internal`.

## Data model

The database has two operational tables:

- `research_sources` stores source names, tags, feed URLs, adapter types,
    weights, enabled state, and polling timestamps.
- `inbox_entries` stores source metadata, canonical and original URLs, article
    timestamps, generated summaries, read state, ratings, and dismissal state.

Canonical URLs are the deduplication key. Tracking parameters such as `utm_*`,
`fbclid`, and `gclid` are removed before comparison.

## Validation

There is no checked-in automated test suite yet. The current lightweight
backend check is:

```bash
PYTHONPATH=. python3 -m compileall backend
```
