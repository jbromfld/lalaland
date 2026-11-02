# Configuration and schedules

[← Quickstart](../README.md)

Run commands from the repository root unless stated otherwise.

## Configuration

Settings come from environment variables in `backend/config.py`. The defaults
below reflect `load_settings()`; environment values override them.

All application defaults are defined once on `Settings` in `backend/config.py`;
`load_settings()` applies environment overrides to a default instance. To use a
new model version, set `CORPUS_MODEL` in `.env` for Docker or export it for native
processes, ensure that model is installed in Ollama, and restart the backend and
worker. No code or test edits are needed. Existing articles retain their saved
model selection.

| Setting | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Shared Postgres database | `postgresql://localhost:5432/lalaland` |
| `OLLAMA_BASE_URL` | Shared Ollama server | `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | LA-1 RSS model | `granite4.2:3b` |
| `OLLAMA_TIMEOUT_SECONDS` | LA-1 inference timeout | `120` |
| `SCHEDULE_HOUR` / `SCHEDULE_MINUTE` | LA-1 daily start | `6` / `0` |
| `SCHEDULE_TIMEZONE` | LA-1 schedule timezone | `local` (see below) |
| `CORPUS_MODEL` | LA-2 default model | `granite4.2:3b` |
| `CORPUS_TRUSTED_DOMAINS` | LA-2 trusted domains and their subdomains | `arxiv.org,neurips.cc` |
| `CORPUS_SCHEDULE_HOUR` / `CORPUS_END_HOUR` | LA-2 overnight window | `3` / `5` |
| `CORPUS_SCHEDULE_TIMEZONE` | LA-2 schedule timezone | `America/Detroit` |
| `CORPUS_OLLAMA_TIMEOUT_SECONDS` | LA-2 evidence/condensation call timeout | `300` |
| `CORPUS_FINAL_TIMEOUT_SECONDS` | LA-2 final writing timeout per call | `900` |
| `CORPUS_FINAL_NUM_PREDICT` | LA-2 final writing output token budget | `6144` |
| `KNOWLEDGE_ENABLED` | Opt in to Lassy knowledge sync, search, and LA-3 | `false` |
| `KNOWLEDGE_SERVICE_URL` | Lassy base URL; required when enabling knowledge | unset |
| `KNOWLEDGE_SCHEDULE_HOUR` / `KNOWLEDGE_SCHEDULE_MINUTE` | Daily knowledge sync start | `7` / `0` |
| `KNOWLEDGE_SCHEDULE_TIMEZONE` | Knowledge sync timezone | `America/Detroit` |
| `KNOWLEDGE_MODEL` | LA-3 knowledge answer model (UI default) | `granite4.2:3b` |
| `KNOWLEDGE_AGENT_TIMEOUT_SECONDS` | LA-3 generation timeout | `120` |
| `KNOWLEDGE_AGENT_INSTRUCTIONS` | LA-3 answer style instructions | Answer the question concisely, explaining the main findings and relevant limitations. |
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

Knowledge sync runs daily at 07:00 America/Detroit by default when
`KNOWLEDGE_ENABLED=true` and `KNOWLEDGE_SERVICE_URL` are configured on backend and
worker. Set its hour (0–23), minute (0–59), and IANA
timezone in `Settings` or through the environment variables above. Restart the
backend to update an existing `knowledge-sync-schedule`, including the previous
one-minute interval.

See [trusted domains and quarantine](agents.md#trusted-domains-quarantine-and-deletion) for the download policy and release procedure, and [shared retrieval](knowledge.md) for `KNOWLEDGE_SERVICE_URL` and delivery settings.
