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

The dashboard uses native ES modules and CSS under `frontend/assets/`. Shared
color, surface, spacing, and status tokens are defined on `:root` in `styles.css`;
reuse them across views. Dark uses warm charcoal and sage; light overrides the
same color tokens with soft ivory surfaces. `theme.js` is a small synchronous bootstrap loaded before
CSS to apply the saved browser preference before paint; other application scripts
remain native ES modules. Keep both palettes readable, including status badges,
Markdown code, inputs, and selected controls.
No Node packages or bundler are required. Check JavaScript syntax with:

```bash
for file in frontend/assets/*.js; do node --input-type=module --check < "$file"; done
```

Corpus Markdown uses pinned local Marked and DOMPurify modules in
`frontend/assets/vendor/`; versions, licenses, and update instructions are kept
beside them. Optional formatting/security tests use jsdom installed outside the
repository, with no frontend build step:

```bash
npm install --prefix /tmp/lalaland-dom-tests --no-audit --no-fund jsdom@26
NODE_PATH=/tmp/lalaland-dom-tests/node_modules node --experimental-vm-modules --test tests/test_markdown.mjs tests/test_theme.mjs
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
