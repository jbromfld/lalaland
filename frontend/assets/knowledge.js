import { api, escapeHtml, safeUrl } from './shared.js';

export function initKnowledge() {
  const knowledgeModel = document.getElementById('knowledge-model');
  api('/api/features').then(features => {
    document.querySelector('[data-view-target="knowledge-view"]').hidden = !features.knowledge;
  }).catch(() => {});
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
  document.getElementById('knowledge-mode').addEventListener('change', event => {
    knowledgeModel.disabled = event.target.value !== 'summary';
  });
  document.getElementById('knowledge-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = document.getElementById('knowledge-submit');
    const status = document.getElementById('knowledge-status');
    const results = document.getElementById('knowledge-results');
    const answer = document.getElementById('knowledge-answer');
    const mode = document.getElementById('knowledge-mode').value;
    const collection = document.getElementById('knowledge-collection').value;
    button.disabled = true;
    answer.hidden = true;
    results.replaceChildren();
    status.textContent = mode === 'summary' ? 'Retrieving evidence and preparing an answer. The agent may wait for other research processing.' : 'Searching indexed knowledge…';
    results.setAttribute('aria-busy', 'true');
    try {
      const data = await api('/api/knowledge/query', {method: 'POST', timeoutMs: 300000, body: JSON.stringify({
        query: document.getElementById('knowledge-query').value.trim(), mode,
        ...(mode === 'summary' && knowledgeModel.value ? {model: knowledgeModel.value} : {}),
        top_k: Number(document.getElementById('knowledge-top-k').value),
        filters: collection === 'all' ? {} : {collection: [collection]}
      })});
      const chunks = data.chunks || [];
      if (mode === 'summary') {
        document.getElementById('knowledge-summary').textContent = data.summary;
        document.getElementById('knowledge-agent').textContent = data.model ? `LA-3 · ${data.model} · Answer based on retrieved excerpts; verify claims against the sources below.` : '';
        answer.hidden = false;
      }
      status.textContent = chunks.length ? `${chunks.length} ${mode === 'summary' ? 'evidence excerpts used. Sources below.' : 'matching chunks.'}` : 'No matching evidence found. Try another question or source filter.';
      results.innerHTML = chunks.map(chunk => `<article class="card">
        <h3>${escapeHtml(chunk.citation || '')} ${chunk.url ? `<a href="${escapeHtml(safeUrl(chunk.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(chunk.title || 'Untitled')}</a>` : escapeHtml(chunk.title || 'Untitled')}</h3>
        <p class="meta">${escapeHtml(chunk.collection || '')} · ${escapeHtml(chunk.content_type || '')}${chunk.section != null ? ` · Section ${escapeHtml(chunk.section)}` : ''}</p>
        <div class="summary">${escapeHtml(chunk.content || '')}</div>
      </article>`).join('');
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; results.setAttribute('aria-busy', 'false'); }
  });

}
