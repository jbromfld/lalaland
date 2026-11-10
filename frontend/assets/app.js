import { setActiveView } from './shared.js';
import { initRss } from './rss.js';
import { initCorpus } from './corpus.js';
import { initKnowledge } from './knowledge.js';

const { loadHistorySources } = initRss();
initCorpus();
initKnowledge();
document.querySelectorAll('[data-view-target]').forEach(button => {
  button.addEventListener('click', async () => {
    setActiveView(button.dataset.viewTarget);
    if (button.dataset.viewTarget === 'search-view') {
      try { await loadHistorySources(); }
      catch (error) { document.getElementById('history-search-status').textContent = error.message; }
    }
  });
});
