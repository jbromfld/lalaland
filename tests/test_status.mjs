// Optional DOM regression checks; see docs/development.md.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import vm from 'node:vm';

const { JSDOM } = createRequire(import.meta.url)('jsdom');
const html = await readFile(new URL('../frontend/index.html', import.meta.url), 'utf8');
const sharedSource = await readFile(new URL('../frontend/assets/shared.js', import.meta.url), 'utf8');
const rssSource = await readFile(new URL('../frontend/assets/rss.js', import.meta.url), 'utf8');
const flush = async () => { for (let i = 0; i < 3; i++) await new Promise(setImmediate); };

async function page(t, {beforeRate = async () => {}} = {}) {
  const dom = new JSDOM(html, {url: 'http://localhost/'});
  t.after(() => dom.window.close());
  const {document} = dom.window;
  let now = 0, nextId = 0;
  const timers = new Map();
  const context = vm.createContext({
    document, URL, URLSearchParams, AbortSignal,
    setTimeout(callback, delay) { const id = ++nextId; timers.set(id, {callback, at: now + delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval() {},
    async fetch(path) {
      let data = [];
      if (path.endsWith('/rate')) await beforeRate();
      if (path.startsWith('/api/inbox?')) data = {
        page: 1, total: 1, limit: 50,
        items: [{id: 'item-1', title: 'Research', source_name: 'Feed', summary: 'Summary',
          discovered_at: '2026-11-10T12:00:00Z', article_url: 'https://example.org/'}]
      };
      return {ok: true, json: async () => data};
    }
  });
  const shared = new vm.SourceTextModule(sharedSource, {context});
  await shared.link(() => { throw Error('Unexpected import'); });
  await shared.evaluate();
  const rss = new vm.SourceTextModule(rssSource, {context});
  await rss.link(() => shared);
  await rss.evaluate();
  rss.namespace.initRss();
  await flush();
  return {
    document, ...shared.namespace,
    status: () => document.getElementById('status').textContent,
    advance(ms) {
      now += ms;
      for (const [id, timer] of timers) {
        if (timer.at <= now) { timers.delete(id); timer.callback(); }
      }
    }
  };
}

for (const [view, action, timeoutMs] of [['inbox', 'rate', 5000], ['inbox', 'dismiss', 5000], ['search', 'rate', 4000]]) {
  test(`${view} ${action} confirmation clears after ${timeoutMs} ms and on navigation`, async t => {
    const ui = await page(t);
    ui.setActiveView(`${view}-view`);
    if (view === 'search') {
      ui.document.getElementById('history-results').innerHTML = '<button data-history-rate="item-1" data-rating="5">Rate</button>';
    }
    const selector = view === 'inbox' ? `[data-action="${action}"]${action === 'rate' ? '[data-rating="5"]' : ''}` : '[data-history-rate]';
    const act = async () => { ui.document.querySelector(selector).click(); await flush(); };
    await act();
    assert.match(ui.status(), /Recorded rating 5|Rating saved|Dismissed item/);
    assert.equal(ui.document.querySelector('.sidebar').lastElementChild.id, 'status');
    ui.advance(timeoutMs - 1);
    assert.notEqual(ui.status(), '');
    ui.advance(1);
    assert.equal(ui.status(), '');
    await act();
    assert.notEqual(ui.status(), '');
    ui.setActiveView('corpus-view');
    assert.equal(ui.status(), '');
  });
}

test('an old confirmation timer does not erase a newer status', async t => {
  const ui = await page(t);
  ui.setStatus('Recorded rating 5.', {timeoutMs: 4000});
  ui.advance(3000);
  ui.setStatus('New confirmation.', {timeoutMs: 4000});
  ui.advance(1000);
  assert.equal(ui.status(), 'New confirmation.');
  ui.setStatus('Pull in progress.');
  ui.advance(10000);
  assert.equal(ui.status(), 'Pull in progress.');
});

test('a rating that completes after navigation does not show in the new view', async t => {
  let finishRate;
  const pending = new Promise(resolve => { finishRate = resolve; });
  const ui = await page(t, {beforeRate: () => pending});
  ui.document.querySelector('[data-action="rate"]').click();
  ui.setActiveView('corpus-view');
  finishRate();
  await flush();
  assert.equal(ui.status(), '');
});
