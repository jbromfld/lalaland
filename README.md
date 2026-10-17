# Local Agents: LA-1 RSS Briefing and LA-2 Research

`lalaland` provides two local agents for research summaries. **LA-1** keeps you current through short RSS briefings.
**LA-2** turns research papers and articles you choose into practical engineering
deep dives. Both use local Ollama inference, durable Temporal workflows, Postgres
storage, and a shared browser dashboard.

| | LA-1: RSS briefing | LA-2: Research corpus |
|---|---|---|
| Input | Enabled RSS feeds | Submitted arXiv, public PDF, or HTML article URLs |
| Source material | RSS-provided summary or description | Extracted full article text with page/section references |
| Output | A concise 2–4 sentence briefing | An engineering briefing targeting 800–1,200 words |
| Model setting | `OLLAMA_MODEL` | `CORPUS_MODEL`, with optional per-article selection |
| Scheduled processing | Daily briefing schedule | Overnight batch, default 03:00–05:00 America/Detroit |
| Manual processing | **Run now** starts the daily briefing workflow | **Run queued articles now** starts a corpus batch |
| Review | Read, rate 1–5, or dismiss | Read or rate 1–5 |
| Search | Historical inbox search | Full-text corpus search, including reviewed articles |

## LA-1: RSS briefing

Configure feeds in **Sources**, then review new summaries in **Inbox**. The daily
workflow polls enabled sources, discovers recently published entries, removes
tracking parameters from URLs, and skips URLs already saved. It summarizes the
text supplied by the feed; it does not download and read the full linked paper.

**Mark read**, rating an entry, or dismissing it removes it from the active inbox.
The **Search** navigation view still finds those entries by keyword, source,
date range, and rating. Feed text is transient; source configuration, generated
summaries, URLs, timestamps, and review state remain in Postgres.

Temporal's `daily-briefing-schedule` starts `DailyBriefingWorkflow`, which processes
sources through separate activities with retries. The RSS **Run now** action
starts the same workflow immediately and waits for its result.

## LA-2: Research corpus

Open **Corpus** and submit a URL such as
<https://arxiv.org/pdf/2607.01077>. Each submission is saved in the queue; it does
not immediately start inference. The worker extracts the article, creates evidence
notes from bounded chunks, condenses those notes, and writes a structured briefing.

Briefings are written for an engineer without advanced ML or mathematics training:

- A plain-English takeaway, the problem being solved, and how the approach works.
- Experimental evidence, conditions, and limitations, with page/section references.
- Implications for deployment, cost, latency, reliability, observability, and customer integration.
- Adoption requirements, operational tradeoffs, and a small measurable experiment.
- Essential terminology, with paper findings distinguished from suggested engineering applications.

The model selector lists models installed on the configured Ollama server.
**Configured default** uses `CORPUS_MODEL`. The selected model is saved with the
article and used throughout its summarization; changing the default affects future
submissions. Models are not automatically downloaded. Failed articles can be queued
again, optionally with a replacement model; leaving the retry model unspecified
keeps the article's saved model.

The default list shows unread, unrated articles. Completed briefings have
**Mark read** and **1–5 rating** controls. Either action removes the article from
the unread list; rating also marks it read. **Search all saved articles** includes
reviewed articles, and an empty search browses all saved entries. **Show unread**
returns to the default list. Reviewing an article preserves its summary and source
text.

### Overnight batches and manual override

The separate `nightly-corpus-schedule` runs from **03:00–05:00 America/Detroit**
by default. Each batch takes a snapshot of queued articles and processes them
oldest first, one at a time. Articles submitted after that snapshot wait for a
subsequent batch. Failed articles require the retry action to rejoin the queue.

**Run queued articles now** starts a batch outside the overnight window and
returns immediately. Manual batches have a two-hour budget. Scheduled and manual
requests share one active batch, preventing duplicate concurrent batches.

Before a new inference call, the worker reserves its configured timeout plus
30 seconds within the processing window. If there is insufficient time, the
article returns to the queue. Completed evidence chunks are checkpointed by
article, model, prompt version, and prompt hash, so retries and later batches can
reuse them. Condensation and final writing may repeat if interrupted.

Processing states are `queued`, `extracting`, `summarizing`, `ready`, and `failed`.
The dashboard shows the current chunk or batch, completed steps, elapsed time,
last progress update, and activity retry attempt. A single local model call may
take several minutes. Processing continues after you close the browser.

### Supported sources and limits

ArXiv abstract and PDF links share an article identity. Explicit versions are
separate identities; an unversioned submission records the exact version fetched.
Duplicate submissions return the existing article without regenerating it.

Public PDFs use `pypdf`; HTML articles use `trafilatura`. PDF processing extracts
text and does not interpret figures, charts, or scanned pages. A vision-capable
model selected in the dashboard still receives extracted text in this workflow.
Check important claims against the original article.

Fetching accepts public HTTP(S) URLs on standard ports, validates redirects, and
pins connections to validated public IP addresses. Limits are 20 MiB per download,
90 seconds downloading, five redirects, 300 PDF pages, and 500,000 extracted
characters. Unsupported, oversized, or unreadable articles fail visibly.
Authenticated pages and OCR are not supported.

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
worker picks them up. See the sibling `temporal` repository for the shared server
and its persistence setup.

## Configuration

Settings come from environment variables in `backend/config.py`. The defaults
below reflect `load_settings()`; environment values override them.

Corpus defaults are defined once on `Settings` in `backend/config.py`. To use a
new model version, set `CORPUS_MODEL` in `.env` for Docker or export it for native
processes, ensure that model is installed in Ollama, and restart the backend and
worker. No code or test edits are needed. Existing articles retain their saved
model selection.

| Setting | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Shared Postgres database | `postgresql://localhost:5432/lalaland` |
| `OLLAMA_BASE_URL` | Shared Ollama server | `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | LA-1 RSS model | `granite4.2:4b` |
| `OLLAMA_TIMEOUT_SECONDS` | LA-1 inference timeout | `120` |
| `SCHEDULE_HOUR` / `SCHEDULE_MINUTE` | LA-1 daily start | `6` / `0` |
| `SCHEDULE_TIMEZONE` | LA-1 schedule timezone | `local` (see below) |
| `CORPUS_MODEL` | LA-2 default model | `Settings.corpus_model` in `backend/config.py` |
| `CORPUS_SCHEDULE_HOUR` / `CORPUS_END_HOUR` | LA-2 overnight window | `3` / `5` |
| `CORPUS_SCHEDULE_TIMEZONE` | LA-2 schedule timezone | `America/Detroit` |
| `CORPUS_OLLAMA_TIMEOUT_SECONDS` | LA-2 evidence/condensation call timeout | `300` |
| `CORPUS_FINAL_TIMEOUT_SECONDS` | LA-2 final writing timeout | `900` |
| `TEMPORAL_ADDRESS` | Temporal endpoint | `host.docker.internal:30733` |
| `TEMPORAL_NAMESPACE` | Temporal namespace | `lalaland` |

For LA-1, `SCHEDULE_TIMEZONE=local` leaves Temporal's timezone unset, so the default
06:00 schedule runs in **UTC**: 02:00 Detroit during daylight saving time and 01:00
during standard time. Use an explicit IANA timezone when creating a schedule if
you want a fixed local hour. Startup creates the LA-1 schedule only if missing;
changing its environment settings does not update an existing schedule.

LA-2 uses its explicit timezone and updates its own schedule at startup. Its start
and end hours must fall on the same day, with end after start. Keep both corpus
inference timeouts below the worker's 1,200-second heartbeat interval.

## Run locally

Prerequisites are Python 3.11+, Postgres, Ollama with the configured models
installed, and a reachable Temporal server with the `lalaland` namespace.
Download any missing model with `ollama pull MODEL_NAME`.

Docker Compose reads `.env`; native Python processes require the settings to be
exported into their environment. Set database credentials and model choices for
your installation. For a host process connecting to the shared local Temporal
server, use `127.0.0.1` instead of the Docker hostname:

```bash
python3 -m pip install -e ".[dev]"
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

Configure `.env`, including `DATABASE_URL`, `OLLAMA_BASE_URL`, the model choices,
`TEMPORAL_ADDRESS`, `BACKEND_PORT`, and `FRONTEND_PORT`, then run:

```bash
docker compose up --build
```

Use `docker-compose` if only the legacy CLI is installed. This starts `backend`,
`worker`, and `frontend`. Open the dashboard at `http://127.0.0.1:FRONTEND_PORT`
using the configured port. Nginx proxies `/api` and `/health` to the backend.
Host services can be reached through `host.docker.internal` from containers.

## Persistence and migrations

| Agent | Table | Stored data |
|---|---|---|
| LA-1 | `research_sources` | Feed configuration, tags, weights, enabled state, and polling timestamps |
| LA-1 | `inbox_entries` | URLs, concise summaries, timestamps, read state, ratings, and dismissal state |
| LA-2 | `corpus_articles` | URLs, metadata, extracted `article_text` and `sections`, briefing, processing state, model, and prompt version |
| LA-2 | `corpus_progress` | Current processing step, completion counts, retry attempt, and update time |
| LA-2 | `corpus_generations` | Completed evidence chunks for resumable processing |
| LA-2 | `corpus_reviews` | Read timestamps and 1–5 ratings |

LA-1 feed text is transient. LA-2 retains extracted text and page/section references
for full-text search, retries, and reproducibility; downloaded PDF files are
transient. Corpus search uses PostgreSQL `tsvector` and a GIN keyword index over
titles, article text, and briefings. Canonical URLs provide deduplication, with
tracking parameters removed before comparison.

Schema initialization is idempotent. For an existing database, LA-2's additive SQL
migrations are `sql/ddl/001_corpus.sql` through `sql/ddl/004_corpus_reviews.sql`.
They create the new corpus tables and index while preserving existing articles
and RSS records. There is no need to rerun the initial schema sync script for
these corpus additions.

## API reference

### LA-1

| Method and path | Action |
|---|---|
| `GET /api/sources` | List feeds |
| `POST /api/sources` | Add a feed |
| `PUT /api/sources/{id}` / `DELETE /api/sources/{id}` | Update or remove a feed |
| `GET /api/inbox` | List unread, unrated, undismissed entries |
| `GET /api/history` | Search all entries by `days`, `source`, `keyword`, and `rating` |
| `GET /api/history/sources` | List historical source names |
| `POST /api/inbox/{id}/read` | Mark read |
| `POST /api/inbox/{id}/rate` | Rate with `{"rating": 4}` and mark read |
| `POST /api/inbox/{id}/dismiss` | Dismiss |
| `POST /api/jobs/run-now` | Run LA-1 immediately and await its result |

### LA-2

| Method and path | Action |
|---|---|
| `GET /api/ollama/models` | List installed models, corpus default, and discovery errors |
| `POST /api/corpus` | Queue `{"url": "https://arxiv.org/pdf/2607.01077"}`; optional `model` overrides the default |
| `GET /api/corpus` | Paginated unread list/search using `keyword`, `page`, and `limit`; `include_reviewed=true` includes reviewed articles |
| `GET /api/corpus/{id}` | Retrieve saved article, briefing, progress, and review state |
| `GET /api/corpus/schedule` | Read the configured overnight window |
| `POST /api/corpus/run-now` | Start or reuse the active manual batch; return immediately |
| `POST /api/corpus/{id}/read` | Mark a completed briefing read |
| `POST /api/corpus/{id}/rate` | Rate with `{"rating": 4}` and mark read |
| `POST /api/corpus/{id}/retry` | Queue a failed article using `{}` or `{"model": "another-installed-model"}` |

## Validation

```bash
pytest
```

The suite covers both agents' APIs, discovery, extraction, review state, search,
checkpointing, inference serialization, and Temporal workflows. Postgres tests
create and drop disposable `lalaland_test_*` databases; the test account configured
in `tests/conftest.py` needs database creation privileges. Temporal workflow tests
use an ephemeral test server rather than the shared server.

An opt-in integration test downloads the example paper and performs actual local
inference in a disposable database:

```bash
CORPUS_E2E=1 pytest tests/test_corpus_workflow.py::test_corpus_live_paper -q
```

Set `CORPUS_E2E_MODEL` to override the model for that test. It can take several
minutes depending on hardware. The test verifies persistence through schema
reinitialization and new connections; it does not restart running app services.
