# Contributor instructions

Use Python 3.13.16 and `uv sync --locked --extra dev`. Run
`uv run --locked --extra dev pytest`; database tests create/drop disposable
`lalaland_test_*` PostgreSQL databases and Temporal tests use an ephemeral server.
Live inference is opt-in. See `docs/development.md` for prerequisites.

The API is FastAPI, background processing uses Temporal, storage is PostgreSQL,
and Ollama inference is serialized with a session advisory lock. Synchronous I/O
runs in the worker's thread executor; keep workflow code deterministic and put
I/O in activities. Use `workflow.now()` for workflow time.

RSS processing is intentionally best effort. Failed feeds/summaries and work past
a source's ten-minute budget may be skipped. Do not add a recovery queue or retain
raw RSS article bodies. Read, rate, or dismiss removes an item from Inbox; Search
still finds it and allows later rating. Inbox and history return paginated
`items/total/page/limit` envelopes.

Corpus retains extracted source text and sections, guarded download policies,
quarantine approvals, review state, and model generation checkpoints. Keep model
calls outside application transactions, preserve deletion/attempt guards, and
use lightweight status queries for polling. Knowledge integration remains optional.

The dashboard shell is `frontend/index.html`; native ES modules and CSS live in
`frontend/assets/`. No frontend framework or bundler is needed. Preserve same-origin
`/api/*` requests and `/static/assets/` serving in FastAPI and Nginx. Escape rendered
text and restrict outbound links to HTTP(S). Preserve keyboard focus while polling.

`POST /api/jobs/run-now` returns immediately and reuses the active manual RSS run;
`GET /api/jobs/{workflow_id}` reports status. Existing RSS schedules must not be
updated on startup. UTC is the explicit default; legacy `local` also means UTC.

Do not commit `.env` or service credentials. Keep configuration in the existing
Settings dataclass. See README and docs for deployment, persistence, scheduling,
knowledge backfill, API contracts, and release publishing.
