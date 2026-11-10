# API reference

[← Quickstart](../README.md)

Run commands from the repository root unless stated otherwise.

## API reference

### LA-1

| Method and path | Action |
|---|---|
| `GET /api/sources` | List feeds |
| `POST /api/sources` | Add a feed |
| `PUT /api/sources/{id}` / `DELETE /api/sources/{id}` | Update or remove a feed |
| `GET /api/inbox` | Paginated unread, unrated, undismissed entries using `page` and `limit` |
| `GET /api/history` | Paginated search by `days`, `source`, `keyword`, and `rating`, plus `page` and `limit` |
| `GET /api/history/sources` | List historical source names |
| `POST /api/inbox/{id}/read` | Mark read |
| `POST /api/inbox/{id}/rate` | Rate with `{"rating": 4}` and mark read |
| `POST /api/inbox/{id}/dismiss` | Dismiss |
| `POST /api/jobs/run-now` | Start or reuse an active manual LA-1 run; return HTTP 202 immediately |
| `GET /api/jobs/{workflow_id}` | Read the manual job state and final counts |

Inbox and history responses are `{ "items": [...], "total": 120, "page": 1,
"limit": 50 }`. Pages start at 1; the default limit is 50 and the maximum is 100.
Results sort by discovery time descending, then ID descending. History keyword
matching remains a case-insensitive substring search. Rating a historical item uses
the same `/api/inbox/{id}/rate` endpoint.

Manual startup returns `{ "started": true, "workflow_id": "daily-briefing-workflow-manual",
"message": "..." }`. A repeated request while that manual run is active returns
`started: false` and the same identifier. Status returns `state` (such as `running`,
`completed`, or `failed`), `message`, and `result`. Completed results contain
`sources_processed`, `sources_failed`, `entries_seen`, and `entries_created`.
A running job can be queued while the worker is offline. Each status request is
bounded; it does not wait for workflow completion. Scheduled pulls retain their
existing independent schedule.

Source names and URLs are trimmed before validation. Blank values, invalid UUIDs,
unsupported feed schemes, credentials, and nonstandard feed ports return HTTP 422.

### LA-2

| Method and path | Action |
|---|---|
| `GET /api/ollama/models` | List installed models, corpus default, and discovery errors |
| `POST /api/corpus` | Queue `{"url": "https://arxiv.org/pdf/2607.01077"}`; optional `model` overrides the default |
| `GET /api/corpus` | Paginated unread list/search using `keyword`, `page`, and `limit`; includes nullable ISO `published_date`; `include_reviewed=true` includes reviewed articles and sorts by publication date descending, unknown dates last |
| `DELETE /api/corpus/{id}` | Permanently delete an article and its extracted text, briefing, progress, cached evidence, review, and quarantine records |
| `GET /api/corpus/{id}` | Retrieve saved article, nullable ISO `published_date`, briefing, progress, and review state |
| `GET /api/corpus/{id}/status` | Small polling response: ID, attempt, state, error, update time, quarantine URL, and progress; no article text or briefing |
| `GET /api/corpus/schedule` | Read the configured overnight window |
| `POST /api/corpus/run-now` | Start or reuse the active manual batch; return immediately |
| `POST /api/corpus/{id}/release` | Release quarantine and queue a new attempt; optional `{"approve_sources":true}` saves exact-host source approvals, otherwise both hosts must already be trusted |
| `POST /api/corpus/{id}/read` | Mark a completed briefing read |
| `POST /api/corpus/{id}/rate` | Rate with `{"rating": 4}` and mark read |
| `POST /api/corpus/{id}/retry` | Queue a failed article using `{}` or `{"model": "another-installed-model"}` |

The detail endpoint retains saved article content but omits the internal search
vector. Knowledge summary queries return HTTP 503 with `Retry-After: 30` when
inference remains busy beyond the queue timeout; chunk queries do not use inference.
Malformed retrieval responses return HTTP 502.
