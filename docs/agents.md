# Agent behavior and source policies

[← Quickstart](../README.md)

Run commands from the repository root unless stated otherwise.

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
date range, and rating, and lets you rate previously read entries. Inbox and
historical results use pages of 50 records by default. Feed text is transient;
source configuration, generated summaries, URLs, timestamps, and review state
remain in Postgres.

Temporal's `daily-briefing-schedule` starts `DailyBriefingWorkflow`, which processes
sources through separate activities. Each source gets a ten-minute processing
budget, with a single activity attempt and an eleven-minute execution timeout.
Failed sources do not prevent later sources from running; failed summaries and
remaining entries beyond the budget may be skipped permanently. Cancellation is
checked between entries and while waiting for inference. No retry queue is kept.

Feeds must use public HTTP(S) addresses and standard ports, without credentials.
Downloads use destination pinning, a 5 MiB size bound, five redirects, and a
30-second download budget with socket timeouts. Redirect destinations are checked
before connecting; file paths and unsupported schemes are rejected.

The RSS **Run now** action starts a background manual run and returns immediately.
Repeated clicks reuse the active manual run. The dashboard polls its status and
reports completed/skipped source counts; a worker must be running to process it.

## LA-2: Research corpus

Open **Corpus** and submit a URL such as
<https://arxiv.org/pdf/2607.01077>. Each submission is saved in the queue; it does
not immediately start inference. The worker extracts the article, creates evidence
notes from bounded chunks, condenses those notes, and writes a structured briefing.

Briefings are written for a DevOps/AIOps engineer:

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
the unread list; rating also marks it read. **All saved** includes reviewed
articles, and Search finds matching articles across the library. **Unread**
returns to the default list. Reviewing an article preserves its summary and source
text.

Corpus lists and article details show the publication date. **All saved** and
search results sort by publication date descending, including keyword searches;
unknown dates appear last, with saved time and article ID breaking ties. The
unread view retains its existing saved-time/relevance ordering. HTML dates come
from publication metadata, preferring the original publication over modification
dates. For arXiv PDFs, the date is the publication date of the extracted version
from its stamp. Other PDFs without publication metadata show **Unknown**; PDF
creation time is not treated as publication time. Migration `007` backfills dates
from existing HTML metadata and arXiv stamps without fetching articles again.

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
reuse them. Condensation is also checkpointed; final writing may repeat if
interrupted. Final writing detects
incomplete Ollama responses and validates the complete JSON structure. A truncated,
malformed, or invalid briefing gets one fresh, more concise writing attempt using
the same evidence notes. Each call still reserves time within the processing
window; incomplete responses are never saved as completed briefings. Evidence and
condensation calls are checkpointed using the model, prompt version, prompt content,
and generation options. Upgrading from the earlier prompt-only hashes may recompute
older evidence once; existing checkpoint rows are preserved. Incomplete outputs
are never cached. Persistent
failures remain visible for retry. `CORPUS_FINAL_NUM_PREDICT` controls the output
token budget for final writing; restart the worker after changing it.

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

Corpus fetching accepts only public HTTPS URLs on port 443, validates redirects, and
pins connections to validated public IP addresses. Limits are 20 MiB per download,
90 seconds downloading, five redirects, 300 PDF pages, and 500,000 extracted
characters. Unsupported, oversized, or unreadable articles fail visibly.
Authenticated pages and OCR are not supported.

## Trusted domains, quarantine, and deletion

`CORPUS_TRUSTED_DOMAINS` is a comma-separated list of DNS domains. It defaults
to `arxiv.org,neurips.cc` in `Settings`; each domain and its subdomains are trusted.
Wildcards and URLs are not supported. An empty value trusts no configured domains;
saved UI approvals still apply. Keep the backend and worker configuration identical.

Unknown domains are saved in quarantine without downloading the article or calling
Ollama. Quarantined articles remain visible and searchable, but nightly and manual
batches skip them. Every redirect is checked before connecting: an unknown HTTPS
host quarantines the article; an HTTP downgrade, credentials, nonstandard port, or
private destination fails validation. Existing queued articles are checked when
processed. Previously completed briefings remain available.

To approve a source, open the article marked **Approval needed** in the Corpus list.
The article detail displays the original and blocked hostnames. **Trust sources
and release** saves these exact hostnames in `corpus_sources`, clears this article's
quarantine, and queues a new attempt in one transaction. Approvals apply to future
articles on these hosts, but do not include their subdomains. Both backend and
worker read approvals from the shared database without a restart. Existing
quarantined articles still need individual release. Deleting an article preserves
source approvals.

The equivalent API is `POST /api/corpus/{id}/release` with
`{"approve_sources":true}`. With an omitted or false flag, release requires the
original and blocked hosts to be trusted already, through configuration or saved
approval. You can also add domains to `CORPUS_TRUSTED_DOMAINS` and restart backend
and worker as before.

Release validates both URLs as public HTTPS destinations before saving any
approval. It does not start a batch; use **Run queued articles now** or wait for
the nightly window. Every redirect is checked again during fetching, so new
unapproved hosts cause quarantine again. `corpus_quarantine` retains blocked URL,
reason, and timestamp independently of processing state. The additive
`006_corpus_sources.sql` migration preserves all existing quarantine records.

This policy applies to LA-2 article downloads. Local Ollama/Temporal addresses and
LA-1 RSS fetching retain their existing configuration.


Delete any research article from its Corpus detail view, including quarantined,
queued, read, and rated articles. **Delete article** asks for confirmation and
permanently removes its database record and related corpus data. It also removes
the article from search. Processing checks for deletion before subsequent stages
and model calls; a fetch or model request already in flight may finish, but cannot
restore the deleted article. Existing Temporal execution history is retained by
Temporal under its own retention policy. You can submit the URL again later as a
new article.
