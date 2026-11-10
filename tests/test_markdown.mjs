// Optional DOM regression checks; see docs/development.md for the isolated command.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import vm from 'node:vm';

const { JSDOM } = createRequire(import.meta.url)('jsdom');
const dom = new JSDOM('', {url:'http://test/'});
const { document } = dom.window;
const context = vm.createContext({window:dom.window, document, URL});
const modules = new Map();
async function load(file) {
  if (modules.has(file)) return modules.get(file);
  const module = new vm.SourceTextModule(await readFile(file, 'utf8'), {context, identifier:file});
  modules.set(file, module);
  await module.link((specifier, parent) => load(resolve(dirname(parent.identifier), specifier)));
  return module;
}
const module = await load(resolve(dirname(fileURLToPath(import.meta.url)), '../frontend/assets/markdown.js'));
await module.evaluate();
function render(text) {
  const node = document.createElement('div');
  node.innerHTML = module.namespace.renderMarkdown(text);
  return node;
}

test('renders useful Markdown while preserving source references and plain prose', () => {
  const node = render('A **key finding** and *limitation* [page 2].\n\n- Use `cache_size` carefully.\n- Check the result.\n\n3. First step\n4. Second step\n\n> Evidence matters.\n\n### Details\n\n| Use | Benefit |\n| --- | --- |\n| Cache | Less work |');
  assert.equal(node.querySelector('strong').textContent, 'key finding');
  assert.equal(node.querySelector('em').textContent, 'limitation');
  assert.equal(node.querySelectorAll('ul > li').length, 2);
  assert.equal(node.querySelector('ol').getAttribute('start'), '3');
  assert.equal(node.querySelector('code').textContent, 'cache_size');
  assert(node.querySelector('blockquote'));
  assert(node.querySelector('h6'));
  assert(node.querySelector('table'));
  assert.match(node.textContent, /\[page 2\]/);
  assert.equal(render('Saved plain text.\n\nSecond paragraph.').querySelectorAll('p').length, 2);
});

test('keeps code literal and does not load Markdown images', () => {
  const node = render('```html\n<script>alert(1)</script>\n```\n\n![A diagram](https://example.org/image.png)');
  assert.equal(node.querySelector('pre code').textContent.trim(), '<script>alert(1)</script>');
  assert.equal(node.querySelectorAll('script, img').length, 0);
  assert.match(node.textContent, /A diagram/);
});

test('escapes untrusted HTML and blocks executable or embedded content', () => {
  const node = render('<img src=x onerror=alert(1)>\n\n<svg onload=alert(1)></svg>\n\n<script>alert(1)</script>\n\n[Bad](javascript:alert(1))\n\n[Encoded](jav&#x61;script:alert(1))\n\n[Data](data:text/html,test)');
  assert.equal(node.querySelectorAll('img, svg, script, iframe, object').length, 0);
  assert.equal(node.querySelectorAll('[onclick], [onload], [onerror]').length, 0);
  for (const link of node.querySelectorAll('a')) {
    assert.match(link.href, /^https?:\/\//);
  }
});

test('opens HTTP(S) links safely with formatted labels', () => {
  const node = render('[**Source**](https://example.org/paper "Read the paper")');
  const link = node.querySelector('a');
  assert.equal(link.href, 'https://example.org/paper');
  assert.equal(link.target, '_blank');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.equal(link.querySelector('strong').textContent, 'Source');
});
