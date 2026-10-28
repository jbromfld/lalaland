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
| `DELETE /api/corpus/{id}` | Permanently delete an article and its extracted text, briefing, progress, cached evidence, review, and quarantine records |
| `GET /api/corpus/{id}` | Retrieve saved article, briefing, progress, and review state |
| `GET /api/corpus/schedule` | Read the configured overnight window |
| `POST /api/corpus/run-now` | Start or reuse the active manual batch; return immediately |
| `POST /api/corpus/{id}/release` | Release quarantine and queue a new attempt; optional `{"approve_sources":true}` saves exact-host source approvals, otherwise both hosts must already be trusted |
| `POST /api/corpus/{id}/read` | Mark a completed briefing read |
| `POST /api/corpus/{id}/rate` | Rate with `{"rating": 4}` and mark read |
| `POST /api/corpus/{id}/retry` | Queue a failed article using `{}` or `{"model": "another-installed-model"}` |
