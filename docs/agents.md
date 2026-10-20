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
reuse them. Condensation and final writing may repeat if interrupted. Final writing detects
incomplete Ollama responses and validates the complete JSON structure. A truncated,
malformed, or invalid briefing gets one fresh, more concise writing attempt using
the same evidence notes. Each call still reserves time within the processing
window; incomplete responses are never saved as completed briefings. Persistent
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
Wildcards and URLs are not supported. An empty value trusts no domains. Keep the
backend and worker configuration identical.

Unknown domains are saved in quarantine without downloading the article or calling
Ollama. Quarantined articles remain visible and searchable, but nightly and manual
batches skip them. Every redirect is checked before connecting: an unknown HTTPS
host quarantines the article; an HTTP downgrade, credentials, nonstandard port, or
private destination fails validation. Existing queued articles are checked when
processed. Previously completed briefings remain available.

To approve a source, review its DNS domain, add it to `CORPUS_TRUSTED_DOMAINS`
(including the domains you still trust), and restart the backend and worker.
Then select **Release after configuration update** in the article detail, or call
`POST /api/corpus/{id}/release`. Release validates the original and blocked URLs
against the configured policy and public DNS, then queues a new attempt. It does
not start a batch or grant a per-article exception. Further redirects are checked
again during fetching. The additive `corpus_quarantine` table records the blocked
URL, reason, and timestamp; processing state remains separate.

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
