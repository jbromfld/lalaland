# Development and validation

[← Quickstart](../README.md)

Run commands from the repository root unless stated otherwise.

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

## Frontend checks

The dashboard uses native ES modules and CSS under `frontend/assets/`; no Node
packages or bundler are required. Check JavaScript syntax with:

```bash
for file in frontend/assets/*.js; do node --input-type=module --check < "$file"; done
```

Verify pagination, mark-read followed by rating in Search, manual-job startup,
and corpus progress updates after UI changes. Polling pauses in hidden tabs and
preserves focused controls during status updates. Both FastAPI and the frontend
image must serve `/static/assets/` with JavaScript/CSS content types.

## Standardized environment

Use CPython **3.13.16** and `uv sync --locked` for this repository. The dependency
source of truth is `pyproject.toml` plus committed `uv.lock`. Use
`uv sync --locked --extra dev` when development extras are needed (where defined).
Shared Ansible provisioning and runtime version checks are documented in [local-agent-environment](../../local-agent-environment/README.md).
Its `.tools/bin/uv` provides the pinned uv version independently of PATH.
