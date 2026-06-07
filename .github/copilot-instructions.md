# Copilot Instructions

## Build, test, and lint commands

### Local runtime

Install backend dependencies:

```bash
python3 -m pip install -r backend/requirements.txt
```

Run the app locally:

```bash
uvicorn backend.main:app --reload
```

### Docker runtime

Start the frontend and backend containers while using Postgres and Ollama on the host:

```bash
docker compose up --build
```

If the machine only has the legacy CLI:

```bash
docker-compose up --build
```

### Current validation command

There is no checked-in test suite or lint configuration yet. The current lightweight backend validation is:

```bash
PYTHONPATH=. python3 -m compileall backend
```

There is currently no single-test command because no automated tests are checked in.

## High-level architecture

- The app is a **single FastAPI backend** in `backend/main.py`. Startup uses the FastAPI lifespan hook to initialize telemetry, create the Postgres schema, and start the in-process APScheduler job.
- The scheduled flow lives in `backend/services/pipeline.py`. The daily job loads enabled rows from `research_sources`, pulls feed entries through `backend/adapters/rss.py`, canonicalizes URLs with `backend/services/discovery.py`, fetches article text through `backend/adapters/html.py`, summarizes with Ollama Granite in `backend/services/summarization.py`, and inserts new inbox records into Postgres.
- Persistence is split across two tables in `backend/db.py`:
  - `research_sources` stores feed configuration and source weighting.
  - `inbox_entries` stores only summary metadata and user actions. **Raw article bodies are intentionally transient and should not be persisted.**
- The UI is a **single static HTML page** in `frontend/index.html`. It manages both the inbox and source CRUD by calling same-origin `/api/*` endpoints.
- In local non-Docker runs, the backend serves the static file directly. In Docker, `frontend/nginx.conf` serves the HTML and proxies `/api` and `/health` to the backend container.
- Configuration is centralized in `backend/config.py` and comes from environment variables. The Docker setup expects host services via `.env`, especially local Postgres and local Ollama through `host.docker.internal`.
- Telemetry is set up in `backend/telemetry.py`. If `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, spans go to the console by default.

## Key conventions

- Treat **`research_sources` as the source of truth** for ingestion configuration. The daily pipeline only processes rows where `enabled = TRUE`, ordered by `source_weight DESC, name ASC`.
- URL deduplication is based on **canonical URL strings**, not feed entry IDs. `canonicalize_url()` strips fragments, lowercases scheme/host, trims trailing slashes, and removes tracking params such as `utm_*`, `fbclid`, and `gclid`.
- Keep request/input normalization close to the API layer. `backend/main.py` trims source payload strings before passing them into DB helpers, while the DB layer enforces uniqueness with the `feed_url` unique constraint.
- The current product behavior is that inbox items remain visible until they are dismissed or both read and rated. Any change to inbox queries should preserve that workflow unless intentionally changing product behavior.
- The frontend relies on **same-origin relative fetches** like `/api/inbox` and `/api/sources`. If you change service boundaries or ports, preserve that contract or update the nginx proxy and frontend together.
- Frontend rendering currently escapes text before injecting HTML and only allows `http`/`https` links. Preserve that safety pattern when changing dashboard rendering.
- The backend is intentionally synchronous today: `requests`, `psycopg`, and APScheduler all run in-process. Follow the existing pattern unless you are intentionally redesigning concurrency.