# Lalaland

Two local research agents with a shared browser dashboard:

- **LA-1 — RSS briefing:** polls feeds and turns their summaries into short briefings.
- **LA-2 — Research corpus:** queues paper/article URLs and produces engineering deep dives from extracted full text.

Both use Ollama for inference, Temporal for durable processing, and PostgreSQL for
storage. Optional [Lassy integration](docs/knowledge.md) indexes saved content for
shared hybrid retrieval.

## Quickstart with Docker

Run commands from the repository root. You need Docker Compose and existing
PostgreSQL, Ollama, and Temporal services. Create the application database and the
Temporal `lalaland` namespace if missing; Compose starts only the application.

```bash
cp -n .env.example .env             # Preserve any existing configuration
# Edit .env: database credentials, service addresses, models, and ports.
# Models must already be installed in Ollama; pull configured models as needed:
ollama pull granite4.2:3b            # Current default for both agents

docker compose up -d --build
```

Use `host.docker.internal` for host services reached from containers. With the
example ports, open <http://127.0.0.1:8081>; the API is at
<http://127.0.0.1:8000>. The backend initializes its tables and registers schedules.
The worker must be running for ingestion and summarization to execute.

Use `docker-compose` in place of `docker compose` if only the standalone CLI is
installed.

## Quickstart without Docker

Use Python **3.13.16** and uv. Native processes read exported environment
variables rather than loading `.env`. Configure the same database, model, and
Temporal namespace in both terminals; use host addresses instead of Docker names.
For a local installation:

```bash
uv sync --locked --extra dev
export DATABASE_URL='postgresql://YOUR_USER:YOUR_PASSWORD@127.0.0.1:5432/lalaland'
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export TEMPORAL_ADDRESS=127.0.0.1:30733
export TEMPORAL_NAMESPACE=lalaland
uv run --locked uvicorn backend.main:app --reload
```

In a second terminal, export the same settings and run:

```bash
uv run --locked python -m backend.temporal.worker
```

Open <http://127.0.0.1:8000>; FastAPI serves the dashboard directly. This repository
uses uv and Docker Compose for builds; it has no Bazel targets.

## Use the agents

1. Add RSS feeds in **Sources**, then choose **Run now** and review **Inbox**.
2. In **Corpus**, submit an arXiv, public PDF, or HTML article URL. Choose
   **Run queued articles now**, or wait for the overnight batch (default
   03:00–05:00 America/Detroit). Submission alone does not start inference.
3. Read or rate results; use search to find reviewed material later.

LA-2 defaults to trusting `arxiv.org`, `neurips.cc`, and their subdomains. Other
domains enter quarantine until you update configuration and release the article.
PDF processing uses extracted text; it does not interpret figures or scanned pages.
See [agent behavior and source policies](docs/agents.md) for details.

## Rebuild, restart, and check

```bash
docker compose up -d --build        # Rebuild and apply application changes
docker compose ps -a
docker compose logs --tail=100 backend worker
curl http://127.0.0.1:8000/health     # Adjust if BACKEND_PORT differs
```

After changing `.env`, run `docker compose up -d` to apply it. For native changes,
restart the worker and restart the API when reload does not apply. To run tests:

```bash
uv run --locked --extra dev pytest
```

Tests use disposable PostgreSQL databases and an ephemeral Temporal test server;
see [validation prerequisites](docs/development.md) before running them.

## Reference

- [Agent behavior and source policies](docs/agents.md): review/search, batching, retries, source limits, quarantine, and deletion.
- [Configuration and schedules](docs/configuration.md): defaults, model selection, timeouts, and timezone behavior.
- [Architecture and operations](docs/operations.md): native/Docker deployment, service recovery, persistence, and migrations.
- [Shared retrieval with Lassy](docs/knowledge.md): setup, backfill, outbox delivery, and knowledge queries.
- [API reference](docs/api.md): RSS and corpus endpoints.
- [Development and validation](docs/development.md): dependency management, tests, and opt-in live inference.
