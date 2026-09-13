# Copilot Instructions

## Build, test, and lint commands

### Local runtime

Install backend dependencies:

```bash
python3 -m pip install -e ".[dev]"
```

Run the app locally:

```bash
uvicorn backend.main:app --reload
```

### Docker runtime

Start the frontend, backend, and Temporal worker containers while using Postgres, Ollama, and Temporal on the host:

```bash
docker compose up --build
```

If the machine only has the legacy CLI:

```bash
docker-compose up --build
```

### Current validation command

```bash
pytest
```

Runs the suite in `tests/` (pure unit tests plus a Temporal workflow test using
time-skipping, no real server needed). There is no lint configuration yet.

## High-level architecture

- The app is a **FastAPI backend** in `backend/main.py` plus a separate **Temporal worker** process (`backend/temporal/worker.py`). Startup uses the FastAPI lifespan hook to initialize telemetry, create the Postgres schema, connect to Temporal, and register a server-side Schedule (`backend/temporal/client.py`) that replaced the old in-process APScheduler job.
- The scheduled flow is `DailyBriefingWorkflow` (`backend/temporal/workflows.py`), executed by the worker against per-source activities in `backend/temporal/activities.py`. Each source is its own activity with its own retries, instead of one all-or-nothing transaction. Activities load enabled rows from `research_sources`, pull feed entries through `backend/adapters/rss.py`, canonicalize URLs with `backend/services/discovery.py`, fetch article text through `backend/adapters/html.py`, summarize with Ollama Granite in `backend/services/summarization.py`, and insert new inbox records into Postgres.
- `POST /api/jobs/run-now` starts the same workflow via the Temporal client and awaits its result — it no longer runs the pipeline in-thread.
- The Temporal server itself (with Postgres persistence) is a separate shared local service; see the sibling `temporal` repo. `TEMPORAL_ADDRESS`/`TEMPORAL_NAMESPACE` in `.env` point at it.
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
- Activities are intentionally synchronous (`requests`, `psycopg`) and run in a `ThreadPoolExecutor` inside the async Temporal worker. Follow the existing pattern unless you are intentionally redesigning concurrency. Workflow files (`backend/temporal/workflows.py`) must stay deterministic — no direct I/O, use `workflow.now()` instead of `datetime.now()`, and wrap imports of modules with side effects in `workflow.unsafe.imports_passed_through()`.