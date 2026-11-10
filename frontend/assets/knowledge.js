import { api, escapeHtml, safeUrl } from './shared.js';
import { renderMarkdown } from './markdown.js';

export function initKnowledge() {
  const knowledgeModel = document.getElementById('knowledge-model');
  const modeInput = document.getElementById('knowledge-mode');
  const modeButtons = [...document.querySelectorAll('[data-knowledge-mode]')];
  const submitButton = document.getElementById('knowledge-submit');
  api('/api/features').then(features => {
    document.querySelector('[data-view-target="knowledge-view"]').hidden = !features.knowledge;
  }).catch(() => {});

  function setMode(mode) {
    modeInput.value = mode;
    knowledgeModel.disabled = mode !== 'summary';
    modeButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.knowledgeMode === mode)));
    submitButton.textContent = mode === 'summary' ? 'Ask knowledge' : 'Find excerpts';
  }
  modeButtons.forEach(button => button.addEventListener('click', () => setMode(button.dataset.knowledgeMode)));
  modeInput.addEventListener('change', () => setMode(modeInput.value));
  setMode(modeInput.value);

  async function loadKnowledgeModels() {
    try {
      const data = await api('/api/knowledge/models');
      const selected = knowledgeModel.value;
      knowledgeModel.innerHTML = `<option value="">Configured default (${escapeHtml(data.default_model)})</option>` +
        data.models.map(model => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join('');
      if (data.models.includes(selected)) knowledgeModel.value = selected;
      document.getElementById('knowledge-model-status').textContent = data.error || data.warning || '';
    } catch (error) { document.getElementById('knowledge-model-status').textContent = error.message; }
  }
  document.querySelector('[data-view-target="knowledge-view"]').addEventListener('click', loadKnowledgeModels);

  document.getElementById('knowledge-form').addEventListener('submit', async event => {
    event.preventDefault();
    const status = document.getElementById('knowledge-status');
    const results = document.getElementById('knowledge-results');
    const answer = document.getElementById('knowledge-answer');
    const evidence = document.getElementById('knowledge-evidence');
    const mode = modeInput.value;
    const collection = document.getElementById('knowledge-collection').value;
    submitButton.disabled = true;
    modeButtons.forEach(button => { button.disabled = true; });
    answer.hidden = true;
    evidence.hidden = true;
    results.replaceChildren();
    status.textContent = mode === 'summary' ? 'Finding evidence and preparing an answer. This may take a moment.' : 'Searching your saved research…';
    results.setAttribute('aria-busy', 'true');
    try {
      const data = await api('/api/knowledge/query', {method:'POST', timeoutMs:300000, body:JSON.stringify({
        query:document.getElementById('knowledge-query').value.trim(), mode,
        ...(mode === 'summary' && knowledgeModel.value ? {model:knowledgeModel.value} : {}),
        top_k:Number(document.getElementById('knowledge-top-k').value),
        filters:collection === 'all' ? {} : {collection:[collection]}
      })});
      const chunks = data.chunks || [];
      if (mode === 'summary') {
        document.getElementById('knowledge-summary').innerHTML = renderMarkdown(data.summary);
        document.getElementById('knowledge-agent').textContent = data.model
          ? `Based on retrieved excerpts · ${data.model}. Check important details against the sources below.` : '';
        answer.hidden = false;
      }
      status.textContent = chunks.length ? `${chunks.length} ${mode === 'summary' ? 'supporting excerpts found.' : 'matching excerpts.'}`
        : 'No matching evidence found. Try another question or source filter.';
      evidence.hidden = chunks.length === 0;
      evidence.open = mode === 'chunks';
      document.getElementById('knowledge-evidence-title').textContent = `Sources and excerpts (${chunks.length})`;
      const types = {rss_summary:'RSS summary', corpus_article:'Corpus article', corpus_briefing:'Corpus briefing'};
      results.innerHTML = chunks.map(chunk => `<article class="card evidence-entry">
        <header class="entry-header"><div class="entry-meta"><span>${escapeHtml(types[chunk.content_type] || 'Research source')}</span>${chunk.section != null ? `<span>${escapeHtml(String(chunk.section))}</span>` : ''}</div>
          <h3>${escapeHtml(chunk.citation || '')} ${chunk.url ? `<a href="${escapeHtml(safeUrl(chunk.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(chunk.title || 'Untitled')}</a>` : escapeHtml(chunk.title || 'Untitled')}</h3></header>
        <blockquote class="evidence-excerpt">${escapeHtml(chunk.content || '')}</blockquote>
      </article>`).join('');
    } catch (error) { status.textContent = error.message; }
    finally {
      submitButton.disabled = false;
      modeButtons.forEach(button => { button.disabled = false; });
      results.setAttribute('aria-busy', 'false');
    }
  });
}
