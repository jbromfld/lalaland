import { api, setStatus, setActiveView, escapeHtml, safeUrl, renderHtml, setPagination } from './shared.js';

export function initRss() {
  const researchNode = document.getElementById("research");
  const sourceListNode = document.getElementById("source-list");
  const runButton = document.getElementById("run-button");
  const sourceForm = document.getElementById("source-form");
  const sourceIdInput = document.getElementById("source-id");
  const sourceNameInput = document.getElementById("source-name");
  const sourceTagsInput = document.getElementById("source-tags");
  const sourceFeedUrlInput = document.getElementById("source-feed-url");
  const sourceWeightInput = document.getElementById("source-weight");
  const sourceEnabledInput = document.getElementById("source-enabled");
  const sourceSubmitButton = document.getElementById("source-submit");
  const sourceCancelButton = document.getElementById("source-cancel");
  const inboxNavCountNode = document.getElementById("inbox-nav-count");
  const historySearchForm = document.getElementById("history-search-form");
  const historyDaysInput = document.getElementById("history-days");
  const historySourceSelect = document.getElementById("history-source");
  const historyKeywordInput = document.getElementById("history-keyword");
  const historyRatingSelect = document.getElementById("history-rating");
  const historySearchStatusNode = document.getElementById("history-search-status");
  const historyResultsNode = document.getElementById("history-results");
  const historySearchClearButton = document.getElementById("history-search-clear");

  let sourcesCache = [];
  let historySourcesLoaded = false;
  let inboxPage = 1, historyPage = 1, historyParams = null;
  let inboxRequest = 0, historyRequest = 0;
  let currentJob = null, jobPollBusy = false;

  function renderEmptyInbox() {
    inboxNavCountNode.textContent = "0";
    researchNode.innerHTML = '<div class="empty">No pending summaries right now.</div>';
  }

  function setInboxCount(count) {
    inboxNavCountNode.textContent = String(count);
  }

  function resetSourceForm() {
    sourceForm.reset();
    sourceIdInput.value = "";
    sourceEnabledInput.checked = true;
    sourceWeightInput.value = "1";
    sourceSubmitButton.textContent = "Add source";
    document.getElementById('source-editor').hidden = true;
    document.getElementById('source-editor-title').textContent = 'Add a source';
  }

  function fillSourceForm(source) {
    sourceIdInput.value = source.id;
    sourceNameInput.value = source.name;
    sourceTagsInput.value = (source.tags || []).join(", ");
    sourceFeedUrlInput.value = source.feed_url;
    sourceWeightInput.value = String(source.source_weight);
    sourceEnabledInput.checked = source.enabled;
    sourceSubmitButton.textContent = "Save changes";
    document.getElementById('source-editor').hidden = false;
    document.getElementById('source-editor-title').textContent = 'Edit source';
    sourceNameInput.focus();
  }

  function displayHost(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); }
    catch { return url; }
  }
  function renderSources(sources) {
    sourcesCache = sources;
    if (!sources.length) {
      sourceListNode.innerHTML = '<div class="empty"><strong>Choose your first source.</strong><p>Add an RSS feed to start receiving briefings.</p></div>';
      return;
    }
    renderHtml(sourceListNode, sources.map(source => `
      <article class="source-row">
        <div class="source-details"><h3>${escapeHtml(source.name)}<span class="status-badge" data-tone="${source.enabled ? 'ready' : 'muted'}">${source.enabled ? 'Enabled' : 'Paused'}</span></h3>
          <div class="source-meta"><a href="${escapeHtml(safeUrl(source.feed_url))}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(source.feed_url)}">${escapeHtml(displayHost(source.feed_url))}</a>
            <span>${source.last_polled_at ? `Last pull ${escapeHtml(new Date(source.last_polled_at).toLocaleDateString())}` : 'Not pulled yet'}</span>
          </div>
          ${source.tags?.length ? `<div class="source-tags">${source.tags.map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}</div>` : ''}
        </div>
        <div class="source-actions"><button class="ghost" type="button" data-source-action="edit" data-id="${source.id}">Edit</button>
          <button class="text-button" type="button" data-source-action="toggle" data-id="${source.id}">${source.enabled ? 'Pause' : 'Enable'}</button>
          <details class="source-more"><summary>More</summary><button class="text-button danger" type="button" data-source-action="delete" data-id="${source.id}">Delete source</button></details>
        </div>
      </article>`).join(''));
  }

  document.getElementById('source-add').addEventListener('click', () => {
    resetSourceForm();
    document.getElementById('source-editor').hidden = false;
    sourceNameInput.focus();
  });

  async function loadSources() {
    const sources = await api("/api/sources");
    renderSources(sources);
  }

  async function loadHistorySources() {
    if (historySourcesLoaded) {
      return;
    }
    const sources = await api("/api/history/sources");
    const selected = historySourceSelect.value;
    historySourceSelect.innerHTML = '<option value="">All sources</option>' + sources.map((source) => (
      `<option value="${escapeHtml(source)}">${escapeHtml(source)}</option>`
    )).join("");
    historySourceSelect.value = sources.includes(selected) ? selected : '';
    historySourcesLoaded = true;
  }

  function ratingButtons(item, historical = false) {
    return `<div class="rating-group" role="group" aria-label="Rate ${escapeHtml(item.title)}"><span class="control-label">Rate</span>${[1,2,3,4,5].map(value =>
      `<button type="button" ${historical ? `data-history-rate="${item.id}"` : `data-action="rate" data-id="${item.id}"`} data-rating="${value}" aria-label="Rate ${value} out of 5" aria-pressed="${item.rating === value}">${value}</button>`).join('')}</div>`;
  }
  function entryMarkup(item, historical = false) {
    const date = item.article_published_at || item.discovered_at;
    return `<article class="card reading-entry">
      <header class="entry-header"><div class="entry-meta"><span class="entry-source">${escapeHtml(item.source_name)}</span><time datetime="${escapeHtml(date)}" title="${escapeHtml(new Date(date).toLocaleString())}">${escapeHtml(new Date(date).toLocaleDateString())}</time>
        ${historical ? `<span class="status-badge">${escapeHtml(item.status)}</span>` : ''}</div><h3>${escapeHtml(item.title)}</h3></header>
      <div class="entry-copy">${escapeHtml(item.summary)}</div>
      <footer class="entry-actions"><div class="actions"><a href="${escapeHtml(safeUrl(item.article_url))}" target="_blank" rel="noopener noreferrer">Open source ↗</a>
        ${historical ? '' : `<button class="ghost" type="button" data-action="read" data-id="${item.id}">Mark read</button>`}</div>
        ${ratingButtons(item, historical)}
        ${historical ? '' : `<button class="text-button" type="button" data-action="dismiss" data-id="${item.id}" aria-label="Dismiss ${escapeHtml(item.title)}">Dismiss</button>`}
      </footer></article>`;
  }
  function renderHistoryResults(items) {
    renderHtml(historyResultsNode, items.length ? items.map(item => entryMarkup(item, true)).join('')
      : '<div class="empty">No briefings match these filters. Try another topic or clear a filter.</div>');
  }
  function renderHistoryFilters() {
    const labels = {
      days: value => `Within ${value} days`,
      source: value => value,
      rating: value => `Rated ${value} / 5`
    };
    const active = Object.keys(labels).filter(key => historyParams?.has(key));
    document.getElementById('history-active-filters').innerHTML = active.map(key => {
      const label = labels[key](historyParams.get(key));
      return `<button type="button" data-clear-filter="${key}" aria-label="Remove filter: ${escapeHtml(label)}">${escapeHtml(label)} ×</button>`;
    }).join('');
    document.getElementById('history-filter-count').textContent = active.length ? `(${active.length})` : '';
  }
  document.getElementById('history-active-filters').addEventListener('click', async event => {
    const button = event.target.closest('[data-clear-filter]');
    if (!button || !historyParams) return;
    const key = button.dataset.clearFilter;
    ({days:historyDaysInput, source:historySourceSelect, rating:historyRatingSelect})[key].value = '';
    historyParams.delete(key); historyPage = 1;
    await loadHistory();
  });

  historySearchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    historyParams = new URLSearchParams();
    if (historyDaysInput.value) historyParams.set('days', historyDaysInput.value);
    if (historySourceSelect.value) historyParams.set('source', historySourceSelect.value);
    if (historyKeywordInput.value.trim()) historyParams.set('keyword', historyKeywordInput.value.trim());
    if (historyRatingSelect.value) historyParams.set('rating', historyRatingSelect.value);
    historyPage = 1;
    await loadHistory();
  });

  async function loadHistory() {
    if (!historyParams) return;
    const request = ++historyRequest;
    const params = new URLSearchParams(historyParams);
    params.set('page', historyPage);
    try {
      historySearchStatusNode.textContent = 'Searching...';
      const data = await api(`/api/history?${params}`);
      if (request !== historyRequest) return;
      if (historyPage > 1 && !data.items.length) {
        historyPage = Math.max(1, Math.ceil(data.total / data.limit));
        return loadHistory();
      }
      renderHistoryResults(data.items);
      renderHistoryFilters();
      setPagination('history', data);
      historySearchStatusNode.textContent = `${data.total} records found.`;
    } catch (error) {
      if (request === historyRequest) historySearchStatusNode.textContent = error.message;
    }
  }

  historySearchClearButton.addEventListener('click', () => {
    historySearchForm.reset();
    historyParams = null; ++historyRequest;
    renderHistoryFilters();
    historySearchStatusNode.textContent = '';
    historyResultsNode.innerHTML = '<div class="empty">Search for a topic, or leave the search blank to browse saved briefings.</div>';
    setPagination('history', {page:1, total:0, limit:50});
  });
  for (const [prefix, load] of [['inbox', loadInbox], ['history', loadHistory]]) {
    for (const [suffix, delta] of [['prev', -1], ['next', 1]]) {
      document.getElementById(`${prefix}-${suffix}`).addEventListener('click', async () => {
        if (prefix === 'inbox') inboxPage = Math.max(1, inboxPage + delta);
        else historyPage = Math.max(1, historyPage + delta);
        try { await load(); } catch (error) { setStatus(error.message); }
      });
    }
  }
  historyResultsNode.addEventListener('click', async event => {
    const button = event.target.closest('[data-history-rate]');
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      await api(`/api/inbox/${button.dataset.historyRate}/rate`, {
        method:'POST', body:JSON.stringify({rating:Number(button.dataset.rating)})
      });
      await loadHistory(); await loadInbox();
      setStatus('Rating saved.');
    } catch (error) { setStatus(error.message); }
    finally { button.disabled = false; }
  });

  async function loadInbox() {
    const request = ++inboxRequest;
    const data = await api(`/api/inbox?page=${inboxPage}`);
    if (request !== inboxRequest) return;
    if (inboxPage > 1 && !data.items.length) {
      inboxPage = Math.max(1, Math.ceil(data.total / data.limit));
      return loadInbox();
    }
    const items = data.items;
    setInboxCount(data.total);
    setPagination('inbox', data);
    if (!items.length) {
      renderEmptyInbox();
      return;
    }

    renderHtml(researchNode, items.map(item => entryMarkup(item)).join(''));
  }

  async function refreshInbox(message = "") {
    try {
      if (message) {
        setStatus(message);
      }
      await loadInbox();
      setStatus(message);
    } catch (error) {
      setStatus(error.message);
    }
  }

  async function refreshAll(message = "") {
    try {
      if (message) {
        setStatus(message);
      }
      await Promise.all([loadSources(), loadInbox()]);
      setStatus(message);
    } catch (error) {
      setStatus(error.message);
    }
  }

  researchNode.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) {
      return;
    }

    const { action, id, rating } = button.dataset;
    if (button.disabled) return;
    button.disabled = true;
    try {
      if (action === "dismiss") {
        await api(`/api/inbox/${id}/dismiss`, { method: "POST" });
        await refreshInbox("Dismissed item.");
      } else if (action === "read") {
        await api(`/api/inbox/${id}/read`, { method: "POST" });
        await refreshInbox("Marked as read. You can rate it in Search.");
      } else if (action === "rate") {
        await api(`/api/inbox/${id}/rate`, {
          method: "POST",
          body: JSON.stringify({ rating: Number(rating) })
        });
        await refreshInbox(`Recorded rating ${rating}.`);
      }
    } catch (error) {
      setStatus(error.message);
    } finally { button.disabled = false; }
  });

  sourceListNode.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-source-action]");
    if (!button) {
      return;
    }

    const source = sourcesCache.find((item) => item.id === button.dataset.id);
    if (!source) {
      return;
    }

    try {
      if (button.dataset.sourceAction === "edit") {
        setActiveView("sources-view");
        fillSourceForm(source);
        return;
      }

      if (button.dataset.sourceAction === "toggle") {
        await api(`/api/sources/${source.id}`, {
          method: "PUT",
          body: JSON.stringify({
            name: source.name,
            tags: source.tags || [],
            feed_url: source.feed_url,
            source_weight: source.source_weight,
            enabled: !source.enabled
          })
        });
        await refreshAll(`Updated ${source.name}.`);
        return;
      }

      if (button.dataset.sourceAction === "delete") {
        await api(`/api/sources/${source.id}`, { method: "DELETE" });
        if (sourceIdInput.value === source.id) {
          resetSourceForm();
        }
        await refreshAll(`Deleted ${source.name}.`);
      }
    } catch (error) {
      setStatus(error.message);
    }
  });

  sourceForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const payload = {
      name: sourceNameInput.value.trim(),
      tags: sourceTagsInput.value
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      feed_url: sourceFeedUrlInput.value.trim(),
      source_weight: Number(sourceWeightInput.value),
      enabled: sourceEnabledInput.checked
    };

    try {
      if (sourceIdInput.value) {
        await api(`/api/sources/${sourceIdInput.value}`, {
          method: "PUT",
          body: JSON.stringify(payload)
        });
        resetSourceForm();
        await refreshAll(`Saved ${payload.name}.`);
      } else {
        await api("/api/sources", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        resetSourceForm();
        await refreshAll(`Added ${payload.name}.`);
      }
    } catch (error) {
      setStatus(error.message);
    }
  });

  sourceCancelButton.addEventListener("click", () => {
    resetSourceForm();
    document.getElementById('source-add').focus();
    setStatus("Canceled source edit.");
  });

  async function pollJob() {
    if (!currentJob || jobPollBusy || document.hidden) return;
    jobPollBusy = true;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(currentJob)}`);
      if (job.state === 'running') {
        setStatus(job.message);
      } else {
        currentJob = null;
        runButton.disabled = false;
        if (job.state === 'completed') {
          historySourcesLoaded = false;
          const result = job.result;
          await refreshAll(`Processed ${result.sources_processed} sources and created ${result.entries_created} summaries. ${result.sources_failed || 0} sources skipped.`);
        } else setStatus(`Daily pull ${job.state}. You can start another pull.`);
      }
    } catch (error) {
      setStatus(`${error.message} Select Pull latest to reconnect to the job.`);
      currentJob = null;
      runButton.disabled = false;
    } finally { jobPollBusy = false; }
  }
  runButton.addEventListener('click', async () => {
    if (runButton.disabled) return;
    runButton.disabled = true;
    try {
      setStatus('Starting the daily pull...');
      const job = await api('/api/jobs/run-now', {method:'POST'});
      currentJob = job.workflow_id;
      setStatus(job.message);
      await pollJob();
    } catch (error) { setStatus(error.message); runButton.disabled = false; }
  });
  setInterval(pollJob, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pollJob(); });

  resetSourceForm();
  refreshAll();
  return { loadHistorySources };
}
