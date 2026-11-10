import { api, escapeHtml, safeUrl, renderHtml } from './shared.js';
import { renderMarkdown } from './markdown.js';

export function initCorpus() {
  const corpusStatus = document.getElementById('corpus-status');
  const corpusModel = document.getElementById('corpus-model');
  const detailNode = document.getElementById('corpus-detail');
  let corpusPage = 1, corpusSelected = null, corpusBusy = false, corpusDetailPending = false, corpusListPending = false, corpusSearching = false;
  let listRequest = 0, detailRequest = 0, selectedItem = null, corpusKeyword = '', listStructure = null;
  async function loadCorpusModels() {
    try {
      const data = await api('/api/ollama/models');
      corpusModel.innerHTML = `<option value="">Configured default (${escapeHtml(data.default_model)})</option>` +
        data.models.map(model => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join('');
      document.getElementById('corpus-model-status').textContent = data.error || data.warning || '';
    } catch (error) { document.getElementById('corpus-model-status').textContent = error.message; }
  }
  function corpusStateText(item) {
    if (item.quarantine_url) return 'Quarantined: domain approval required';
    if (item.state === 'queued') return 'Queued for overnight processing';
    if (item.state !== 'summarizing' || !item.progress) return item.state;
    const p = item.progress;
    const stages = {
      reading: `Reading paper: chunk ${p.current} of ${p.total} (${p.completed} complete)`,
      condensing: `Condensing evidence: batch ${p.current} of ${p.total} (${p.completed} complete)`,
      writing: p.completed ? 'Saving briefing' : 'Writing engineering briefing'
    };
    const retry = p.activity_attempt > 1 ? ` · processing attempt ${p.activity_attempt}` : '';
    return (stages[p.stage] || item.state) + retry;
  }
  function corpusTimingText(item) {
    if (['queued','ready','failed'].includes(item.state)) return '';
    const updated = item.progress?.updated_at || item.updated_at;
    return `Last updated ${new Date(updated).toLocaleTimeString()}. Larger papers can take several minutes.`;
  }
  function corpusReviewText(item) {
    return item.rating != null ? `Rated ${item.rating}/5 · Read` : item.read_at ? 'Read' : '';
  }
  function corpusPublishedText(item) {
    if (!item.published_date) return 'Unknown';
    return new Date(`${item.published_date}T00:00:00`).toLocaleDateString(undefined, {
      year:'numeric', month:'short', day:'numeric'
    });
  }
  function corpusSourceHosts(item) {
    return [...new Set([item.original_url, item.quarantine_url].map(url => new URL(url).hostname))];
  }
  function sourceHost(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); }
    catch { return 'Saved article'; }
  }
  function statusBadge(item) {
    if (item.quarantine_url) return {label:'Approval needed', tone:'warning'};
    return {
      queued:{label:'Queued', tone:'muted'},
      extracting:{label:'Reading source', tone:'progress'},
      summarizing:{label:'Preparing briefing', tone:'progress'},
      ready:{label:'Ready to read', tone:'ready'},
      failed:{label:'Needs attention', tone:'error'}
    }[item.state] || {label:item.state, tone:'muted'};
  }
  function progressText(item) {
    if (item.state === 'summarizing' || item.state === 'extracting') return corpusStateText(item);
    return item.quarantine_url ? 'Review sources before processing' : corpusReviewText(item);
  }
  function updateSelection() {
    document.querySelectorAll('[data-corpus-row]').forEach(row => {
      const selected = row.dataset.corpusRow === String(corpusSelected);
      row.classList.toggle('is-selected', selected);
      row.querySelector('[data-corpus-id]').setAttribute('aria-current', selected ? 'true' : 'false');
    });
  }
  function clearCorpusDetail() {
    corpusSelected = null; selectedItem = null; ++detailRequest;
    corpusDetailPending = false;
    detailNode.hidden = true;
    detailNode.replaceChildren();
    updateSelection();
  }
  function briefingMarkup(briefing) {
    // Keep stored keys compatible while giving both old and new briefings a
    // reader-focused order. The optional experiment always comes last.
    const sections = [
      ['Takeaway', 'Summary and key takeaways'],
      ['How it works', 'How it works'],
      ['Engineering relevance', 'Real-world use cases'],
      ['Adoption and tradeoffs', 'Practical uses and tradeoffs'],
      ['Evidence and limitations', 'Evidence and limitations'],
      ['Glossary and references', 'Glossary and references']
    ];
    const known = new Set([...sections.map(([key]) => key), 'Practical experiment']);
    sections.push(...Object.keys(briefing).filter(key => !known.has(key)).map(key => [key, key]));
    sections.push(['Practical experiment', 'Practical experiment (optional)']);
    return sections.filter(([key]) => key in briefing).map(([key, title]) => {
      const content = `<div class="corpus-briefing-copy">${renderMarkdown(briefing[key])}</div>`;
      if (key === 'Glossary and references' || key === 'Practical experiment') {
        return `<details class="${key === 'Practical experiment' ? 'corpus-experiment' : 'corpus-glossary'}"><summary>${escapeHtml(title)}</summary>${content}</details>`;
      }
      return `<section class="corpus-briefing-section ${key === 'Takeaway' ? 'corpus-takeaway' : ''}">
        <h3>${escapeHtml(title)}</h3>${content}</section>`;
    }).join('');
  }
  function processingMarkup(item) {
    const badge = statusBadge(item);
    if (item.quarantine_url) return `<section class="corpus-processing" data-tone="warning" aria-label="Source approval">
      <h3>Approve sources to continue</h3>
      <p>This article needs your approval before it can be processed. Releasing it also trusts these exact hostnames for future articles.</p>
      <ul>${corpusSourceHosts(item).map(host => `<li>${escapeHtml(host)}</li>`).join('')}</ul>
      <p class="corpus-hint">Additional redirect hosts will require approval.</p>
      <button type="button" class="primary" data-corpus-release="${item.id}">Trust sources and release</button>
    </section>`;
    if (item.state === 'failed') return `<section class="corpus-processing" data-tone="error" aria-label="Processing error">
      <h3>The briefing could not be completed</h3><p>You can queue another attempt. Your saved article is still here.</p>
      ${item.error ? `<details><summary>Error details</summary><p class="corpus-hint">${escapeHtml(item.error)}</p></details>` : ''}
      <button type="button" class="primary" data-corpus-retry="${item.id}">Queue retry</button>
      <p class="corpus-hint">Uses your selected model, or keeps the article’s original model.</p>
    </section>`;
    if (item.state === 'ready') return '';
    const p = item.progress;
    const progress = item.state === 'summarizing'
      ? `<progress ${p && p.total > 0 ? `max="${Number(p.total)}" value="${Number(p.completed)}"` : ''} aria-label="${escapeHtml(p?.stage || 'Briefing')} stage progress"></progress>` : '';
    return `<section class="corpus-processing" data-tone="${badge.tone}" aria-label="Processing progress" aria-live="polite">
      <h3>${item.state === 'queued' ? 'Queued for processing' : 'Preparing your briefing'}</h3>
      <p id="corpus-detail-state">${escapeHtml(corpusStateText(item))}</p>
      ${progress}<p id="corpus-detail-timing" class="corpus-hint">${escapeHtml(corpusTimingText(item))}</p>
      ${item.state === 'queued' ? '<p class="corpus-hint">Processing starts overnight, or choose Run queued articles above.</p>' : ''}
    </section>`;
  }
  async function showCorpus(id, {focus = false} = {}) {
    corpusSelected = id;
    updateSelection();
    const request = ++detailRequest;
    const item = await api(`/api/corpus/${id}`);
    if (request !== detailRequest || String(corpusSelected) !== String(id)) return;
    selectedItem = item;
    corpusDetailPending = !item.quarantine_url && !['ready','failed'].includes(item.state);
    const badge = statusBadge(item);
    const briefing = item.briefing || {};
    const words = Object.values(briefing).join(' ').trim().split(/\s+/).length;
    detailNode.hidden = false;
    renderHtml(detailNode, `<nav class="corpus-reading-nav" aria-label="Article navigation">
        <button type="button" data-corpus-close>← Back to articles</button>
        <a href="${escapeHtml(safeUrl(item.resolved_url || item.original_url))}" target="_blank" rel="noopener noreferrer">Open original article ↗</a>
      </nav>
      <header class="corpus-detail-header"><p class="corpus-eyebrow">Engineering briefing</p>
        <h2 id="corpus-detail-title" tabindex="-1">${escapeHtml(item.title || 'Article from ' + sourceHost(item.original_url))}</h2>
        <div class="corpus-detail-meta"><span class="corpus-badge" data-tone="${badge.tone}">${escapeHtml(badge.label)}</span>
          <span>${escapeHtml(sourceHost(item.original_url))}</span>
          <span>${item.published_date ? 'Published ' + escapeHtml(corpusPublishedText(item)) : 'Publication date unknown'}</span>
          ${Object.keys(briefing).length ? `<span>${Math.max(1, Math.ceil(words / 220))} min read</span>` : ''}
        </div>
      </header>
      ${processingMarkup(item)}
      <div class="corpus-briefing">${briefingMarkup(briefing)}</div>
      ${item.state === 'ready' ? `<footer class="corpus-review"><div><h3>Finished reading?</h3><p class="corpus-hint">${escapeHtml(corpusReviewText(item) || 'Mark it read or leave a rating.')}</p></div>
        <div class="actions"><button class="primary" type="button" data-corpus-read="${item.id}" ${item.read_at ? 'disabled' : ''}>${item.read_at ? 'Read' : 'Mark read'}</button>
          <div class="rating-group" role="group" aria-label="Rate this article from 1 to 5">
            ${[1,2,3,4,5].map(value => `<button type="button" data-corpus-rate="${item.id}" data-rating="${value}" aria-label="Rate ${value} out of 5" aria-pressed="${item.rating === value}">${value}</button>`).join('')}
          </div></div></footer>` : ''}
      <details class="corpus-article-details"><summary>Article details</summary><dl>
        <dt>Model</dt><dd>${escapeHtml(item.model)}</dd>
        <dt>Source</dt><dd><a href="${escapeHtml(safeUrl(item.resolved_url || item.original_url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.resolved_url || item.original_url)}</a></dd>
        ${item.quarantine_url ? `<dt>Blocked URL</dt><dd>${escapeHtml(item.quarantine_url)}</dd><dt>Reason</dt><dd>${escapeHtml(item.quarantine_reason || 'Source approval required')}</dd>` : ''}
      </dl><button type="button" class="corpus-delete" data-corpus-delete="${item.id}">Delete article permanently</button></details>`);
    if (focus) {
      document.getElementById('corpus-detail-title').focus({preventScroll:true});
      detailNode.scrollIntoView?.({behavior:'smooth', block:'start'});
    }
  }
  async function loadCorpus() {
    const request = ++listRequest;
    const params = new URLSearchParams({keyword:corpusSearching ? corpusKeyword : '', page:corpusPage, include_reviewed:corpusSearching});
    const data = await api(`/api/corpus?${params}`);
    if (request !== listRequest) return;
    if (corpusPage > 1 && !data.items.length) {
      corpusPage = Math.max(1, Math.ceil(data.total / data.limit));
      return loadCorpus();
    }
    document.getElementById('corpus-results-label').textContent = corpusSearching ? (corpusKeyword ? 'Search results' : 'All saved articles') : 'Unread articles';
    document.getElementById('corpus-sort-label').textContent = corpusSearching ? 'Newest published first · unknown dates last' : (corpusKeyword ? 'Most relevant first' : 'Most recently saved first');
    document.getElementById('corpus-unread').setAttribute('aria-pressed', String(!corpusSearching));
    document.getElementById('corpus-all').setAttribute('aria-pressed', String(corpusSearching));
    corpusListPending = data.items.some(item => !item.quarantine_url && !['ready','failed'].includes(item.state));
    const structure = JSON.stringify(data.items.map(({state, error, progress, updated_at, ...item}) => item));
    if (structure === listStructure) {
      for (const item of data.items) {
        const badge = statusBadge(item);
        const node = document.getElementById(`corpus-state-${item.id}`);
        node.textContent = badge.label; node.dataset.tone = badge.tone;
        document.getElementById(`corpus-progress-${item.id}`).textContent = progressText(item);
      }
    } else {
      listStructure = structure;
      renderHtml(document.getElementById('corpus-results'), data.items.length ? `
        <ul class="corpus-article-list">${data.items.map(item => {
          const badge = statusBadge(item);
          return `<li class="corpus-item" data-corpus-row="${item.id}">
            <div><a class="corpus-item-title" href="#corpus-detail" data-corpus-id="${item.id}">${escapeHtml(item.title || 'Article from ' + sourceHost(item.original_url))}</a>
              <div class="corpus-item-meta"><span>${escapeHtml(sourceHost(item.original_url))}</span><span>${item.published_date ? 'Published ' + escapeHtml(corpusPublishedText(item)) : 'Publication date unknown'}</span><span>Model: ${escapeHtml(item.model)}</span></div>
            </div>
            <div class="corpus-item-status"><span class="corpus-badge" id="corpus-state-${item.id}" data-tone="${badge.tone}">${escapeHtml(badge.label)}</span>
              <p class="corpus-item-progress" id="corpus-progress-${item.id}">${escapeHtml(progressText(item))}</p>
            </div></li>`;
        }).join('')}</ul>` : `<div class="empty"><strong>${corpusSearching ? (corpusKeyword ? 'No articles match this search.' : 'Your library is empty.') : 'You’re all caught up.'}</strong><p>${corpusSearching && corpusKeyword ? 'Try another keyword, or choose All saved to browse your library.' : 'Add an article above, or choose All saved to revisit your briefings.'}</p></div>`);
      updateSelection();
    }
    document.getElementById('corpus-page').textContent = `Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.limit))} · ${data.total} ${data.total === 1 ? 'article' : 'articles'}`;
    document.getElementById('corpus-prev').disabled = corpusPage === 1;
    document.getElementById('corpus-next').disabled = corpusPage * data.limit >= data.total;
  }
  document.getElementById('corpus-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.target.querySelector('button'); button.disabled = true;
    try {
      const body = {url:document.getElementById('corpus-url').value};
      if (corpusModel.value) body.model = corpusModel.value;
      const item = await api('/api/corpus', {method:'POST', body:JSON.stringify(body)});
      corpusStatus.textContent = item.quarantine_url ? 'Article quarantined. Review its sources below to approve and release it.' : 'Article queued for the next overnight processing window.';
      corpusPage = 1; corpusSearching = false; await loadCorpus(); await showCorpus(item.id, {focus:true});
    } catch (error) { corpusStatus.textContent = error.message; }
    finally { button.disabled = false; }
  });
  document.getElementById('corpus-run-now').addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      const result = await api('/api/corpus/run-now', {method:'POST'});
      corpusStatus.textContent = result.message;
      await loadCorpus();
    } catch(error) { corpusStatus.textContent = error.message; }
    finally { event.target.disabled = false; }
  });
  document.getElementById('corpus-search').addEventListener('submit', async event => {
    event.preventDefault(); corpusKeyword = document.getElementById('corpus-keyword').value.trim(); corpusPage = 1; corpusSearching = true; clearCorpusDetail();
    try { await loadCorpus(); } catch(error) { corpusStatus.textContent = error.message; }
  });
  for (const [id, all] of [['corpus-unread', false], ['corpus-all', true]]) {
    document.getElementById(id).addEventListener('click', async () => {
      corpusSearching = all; corpusPage = 1; corpusKeyword = '';
      document.getElementById('corpus-keyword').value = '';
      clearCorpusDetail();
      try { await loadCorpus(); } catch(error) { corpusStatus.textContent = error.message; }
    });
  }
  for (const [id, delta] of [['corpus-prev',-1],['corpus-next',1]]) {
    document.getElementById(id).addEventListener('click', async () => {
      corpusPage += delta;
      try { await loadCorpus(); } catch(error) { corpusStatus.textContent = error.message; }
    });
  }
  document.getElementById('corpus-view').addEventListener('click', async event => {
    const target = event.target.closest('button, a[data-corpus-id]'); if (!target) return;
    try {
      if (target.hasAttribute('data-corpus-close')) {
        clearCorpusDetail();
        const heading = document.getElementById('corpus-results-label');
        heading.tabIndex = -1; heading.focus();
        return;
      }
      if (target.dataset.corpusDelete) {
        if (!window.confirm('Permanently delete this article, its briefing, and all related saved data?')) return;
        target.disabled = true;
        await api(`/api/corpus/${target.dataset.corpusDelete}`, {method:'DELETE'});
        if (String(corpusSelected) === target.dataset.corpusDelete) clearCorpusDetail();
        corpusStatus.textContent = 'Article permanently deleted.';
        await loadCorpus();
        return;
      }
      if (target.dataset.corpusRead || target.dataset.corpusRate) {
        const id = target.dataset.corpusRead || target.dataset.corpusRate;
        document.querySelectorAll('#corpus-detail button').forEach(button => { button.disabled = true; });
        const rating = Number(target.dataset.rating);
        await api(`/api/corpus/${id}/${target.dataset.corpusRead ? 'read' : 'rate'}`, {
          method:'POST', ...(target.dataset.corpusRate ? {body:JSON.stringify({rating})} : {})
        });
        clearCorpusDetail();
        corpusStatus.textContent = target.dataset.corpusRate ? `Rated ${rating}/5. Available in saved-article search.` : 'Marked read. Available in saved-article search.';
        await loadCorpus();
      }
      if (target.dataset.corpusRelease) {
        target.disabled = true;
        await api(`/api/corpus/${target.dataset.corpusRelease}/release`, {method:'POST', body:JSON.stringify({approve_sources:true})});
        corpusStatus.textContent = 'Sources trusted. Article queued for overnight processing, or use Run now.';
        await showCorpus(target.dataset.corpusRelease); await loadCorpus();
      }
      if (target.dataset.corpusId) {
        event.preventDefault();
        await showCorpus(target.dataset.corpusId, {focus:true});
      }
      if (target.dataset.corpusRetry) {
        target.disabled = true;
        const body = corpusModel.value ? {model:corpusModel.value} : {};
        await api(`/api/corpus/${target.dataset.corpusRetry}/retry`, {method:'POST',body:JSON.stringify(body)});
        await showCorpus(target.dataset.corpusRetry); await loadCorpus();
      }
    } catch(error) {
      corpusStatus.textContent = error.message;
      if (corpusSelected) await showCorpus(corpusSelected).catch(() => {});
      target.disabled = false;
    }
  });
  async function refreshCorpus() {
    if (corpusBusy || document.hidden) return;
    corpusBusy = true;
    try { await loadCorpus(); if (corpusSelected && corpusDetailPending) await pollCorpusDetail(); }
    catch(error) { corpusStatus.textContent = error.message; }
    finally { corpusBusy = false; }
  }
  async function pollCorpusDetail() {
    const id = corpusSelected, request = detailRequest;
    const status = await api(`/api/corpus/${id}/status`);
    if (request !== detailRequest || String(corpusSelected) !== String(id)) return;
    if (status.state !== selectedItem.state || status.attempt !== selectedItem.attempt || status.quarantine_url !== selectedItem.quarantine_url) {
      await showCorpus(id);
    } else {
      Object.assign(selectedItem, status);
      document.getElementById('corpus-detail-state').textContent = corpusStateText(selectedItem);
      document.getElementById('corpus-detail-timing').textContent = corpusTimingText(selectedItem);
      const progress = detailNode.querySelector('progress');
      if (progress && status.progress) { progress.max = status.progress.total; progress.value = status.progress.completed; progress.setAttribute('aria-label', `${status.progress.stage} stage progress`); }
    }
  }
  document.querySelector('[data-view-target="corpus-view"]').addEventListener('click', refreshCorpus);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && document.getElementById('corpus-view').classList.contains('is-active')) refreshCorpus();
  });
  setInterval(() => { if (!document.hidden && document.getElementById('corpus-view').classList.contains('is-active') && (corpusListPending || corpusDetailPending)) refreshCorpus(); }, 5000);
  api('/api/corpus/schedule').then(schedule => {
    document.getElementById('corpus-schedule').textContent = `Processed overnight · ${String(schedule.start_hour).padStart(2,'0')}:00–${String(schedule.end_hour).padStart(2,'0')}:00 ${schedule.timezone}`;
  }).catch(error => { corpusStatus.textContent = error.message; });
  loadCorpusModels();
}
