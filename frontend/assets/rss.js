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
  const inboxCountNode = document.getElementById("inbox-count");
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
    inboxCountNode.textContent = "0";
    inboxNavCountNode.textContent = "(0)";
    researchNode.innerHTML = '<div class="empty">No pending summaries right now.</div>';
  }

  function setInboxCount(count) {
    inboxCountNode.textContent = String(count);
    inboxNavCountNode.textContent = `(${count})`;
  }

  function resetSourceForm() {
    sourceForm.reset();
    sourceIdInput.value = "";
    sourceEnabledInput.checked = true;
    sourceWeightInput.value = "1";
    sourceSubmitButton.textContent = "Add source";
    sourceCancelButton.hidden = true;
  }

  function fillSourceForm(source) {
    sourceIdInput.value = source.id;
    sourceNameInput.value = source.name;
    sourceTagsInput.value = (source.tags || []).join(", ");
    sourceFeedUrlInput.value = source.feed_url;
    sourceWeightInput.value = String(source.source_weight);
    sourceEnabledInput.checked = source.enabled;
    sourceSubmitButton.textContent = "Save changes";
    sourceCancelButton.hidden = false;
    sourceNameInput.focus();
  }

  function renderSources(sources) {
    sourcesCache = sources;
    if (!sources.length) {
      sourceListNode.innerHTML = '<div class="empty">No sources configured yet.</div>';
      return;
    }

    sourceListNode.innerHTML = sources.map((source) => `
      <article class="source-card ${source.enabled ? "" : "disabled"}">
        <div class="card-top">
          <div>
            <strong>${escapeHtml(source.name)}</strong>
            <div class="source-meta">
              <span class="tag">weight ${escapeHtml(source.source_weight)}</span>
              <span class="tag">${source.enabled ? "enabled" : "disabled"}</span>
              ${(source.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}
              ${source.last_polled_at ? `<span class="tag">last pull ${escapeHtml(new Date(source.last_polled_at).toLocaleString())}</span>` : ""}
            </div>
          </div>
          <div class="actions">
            <button class="ghost" type="button" data-source-action="edit" data-id="${source.id}">Edit</button>
            <button class="ghost" type="button" data-source-action="toggle" data-id="${source.id}">${source.enabled ? "Disable" : "Enable"}</button>
            <button class="ghost" type="button" data-source-action="delete" data-id="${source.id}">Delete</button>
          </div>
        </div>
        <a href="${safeUrl(source.feed_url)}" target="_blank" rel="noreferrer noopener">${escapeHtml(source.feed_url)}</a>
      </article>
    `).join("");
  }

  async function loadSources() {
    const sources = await api("/api/sources");
    renderSources(sources);
  }

  async function loadHistorySources() {
    if (historySourcesLoaded) {
      return;
    }
    const sources = await api("/api/history/sources");
    historySourceSelect.innerHTML = '<option value="">All sources</option>' + sources.map((source) => (
      `<option value="${escapeHtml(source)}">${escapeHtml(source)}</option>`
    )).join("");
    historySourcesLoaded = true;
  }

  function renderHistoryResults(items) {
    if (!items.length) {
      historyResultsNode.innerHTML = '<div class="empty">No historical records match these filters.</div>';
      return;
    }

    renderHtml(historyResultsNode, items.map((item) => {
      const recordDate = item.article_published_at || item.discovered_at;
      const rating = item.rating === null ? "Not rated" : `${item.rating} / 5`;
      return `
        <article class="card">
          <div class="card-top">
            <div>
              <div class="source">${escapeHtml(item.source_name)}</div>
              <strong>${escapeHtml(item.title)}</strong>
            </div>
            <span>${escapeHtml(item.status)}</span>
          </div>
          <div class="summary">${escapeHtml(item.summary)}</div>
          <div class="source-meta">
            <span>${escapeHtml(new Date(recordDate).toLocaleString())}</span>
            <span>Rating: ${escapeHtml(rating)}</span>
            <div class="rating-group" role="group" aria-label="Rate ${escapeHtml(item.title)}">
              ${[1,2,3,4,5].map(value => `<button type="button" data-history-rate="${item.id}" data-rating="${value}" aria-label="Rate ${value} out of 5" aria-pressed="${item.rating === value}">${value}</button>`).join('')}
            </div>
            <a href="${safeUrl(item.article_url)}" target="_blank" rel="noreferrer noopener">Open source</a>
          </div>
        </article>
      `;
    }).join(""));
  }

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
      setPagination('history', data);
      historySearchStatusNode.textContent = `${data.total} records found.`;
    } catch (error) {
      if (request === historyRequest) historySearchStatusNode.textContent = error.message;
    }
  }

  historySearchClearButton.addEventListener('click', () => {
    historySearchForm.reset();
    historyParams = null; ++historyRequest;
    historySearchStatusNode.textContent = '';
    historyResultsNode.innerHTML = '<div class="empty">Choose filters and select Search to find saved records.</div>';
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

    renderHtml(researchNode, items.map((item) => `
      <article class="card">
        <div class="card-top">
          <div>
            <div class="source">${escapeHtml(item.source_name)}</div>
            <strong>${escapeHtml(item.title)}</strong>
          </div>
          <button class="ghost" type="button" data-action="dismiss" data-id="${item.id}" aria-label="Dismiss">×</button>
        </div>
        <div class="summary">${escapeHtml(item.summary)}</div>
        <div class="actions">
          <a href="${safeUrl(item.article_url)}" target="_blank" rel="noreferrer noopener">Open source</a>
          <button class="ghost" type="button" data-action="read" data-id="${item.id}">Mark read</button>
          <div class="rating-group" aria-label="Rate item ${item.id}">
            ${[1, 2, 3, 4, 5].map((value) => `
              <button type="button" data-action="rate" data-id="${item.id}" data-rating="${value}">${value}</button>
            `).join("")}
          </div>
        </div>
      </article>
    `).join(""));
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
        fillSourceForm(source);
        setActiveView("sources-view");
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
      setStatus(`${error.message} Select Run daily pull now to reconnect to the job.`);
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
