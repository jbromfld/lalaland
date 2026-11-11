// Optional DOM checks; jsdom stays outside the project (see docs/development.md).
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';

const { JSDOM } = createRequire(import.meta.url)('jsdom');
const html = await readFile(new URL('../frontend/index.html', import.meta.url), 'utf8');
const source = await readFile(new URL('../frontend/assets/theme.js', import.meta.url), 'utf8');
const css = await readFile(new URL('../frontend/assets/styles.css', import.meta.url), 'utf8');
const key = 'lalaland.appearance';

function page(t, {stored, light = false, blocked = false, matchMedia = true} = {}) {
  const dom = new JSDOM(html, {url:'http://localhost/', runScripts:'outside-only'});
  t.after(() => dom.window.close());
  const { window } = dom;
  const listeners = [];
  const media = {matches:light, addEventListener(type, listener) {
    assert.equal(type, 'change'); listeners.push(listener);
  }};
  window.matchMedia = matchMedia ? () => media : undefined;
  if (stored !== undefined) window.localStorage.setItem(key, stored);
  if (blocked) Object.defineProperty(window, 'localStorage', {get() {throw Error('Storage blocked');}});
  window.eval(source);
  window.document.dispatchEvent(new window.Event('DOMContentLoaded'));
  const control = window.document.getElementById('theme-select');
  return {
    window, control,
    theme: () => window.document.documentElement.dataset.theme,
    choose(value) {control.value = value; control.dispatchEvent(new window.Event('change'));},
    system(value) {media.matches = value; listeners.forEach(listener => listener());},
    storage(value, eventKey = key) {window.dispatchEvent(new window.StorageEvent('storage', {key:eventKey, newValue:value}));},
  };
}

test('applies saved appearance before CSS and exposes a labelled choice', t => {
  assert(html.indexOf('/static/assets/theme.js') < html.indexOf('/static/assets/styles.css'));
  const ui = page(t, {stored:'light'});
  assert.equal(ui.theme(), 'light');
  assert.equal(ui.control.value, 'light');
  assert.match(ui.control.labels[0].textContent, /Appearance/);
  assert.deepEqual([...ui.control.options].map(option => option.value), ['dark','light','blue','system']);
});

test('keeps the existing dark default and ignores invalid stored values', t => {
  for (const stored of [undefined, 'invalid', 'LIGHT', '<script>']) {
    assert.equal(page(t, {stored, light:true}).theme(), 'dark');
  }
});

test('switches immediately, saves the preference, and restores it on reload', t => {
  const ui = page(t);
  for (const value of ['light','dark','blue','system']) {
    ui.choose(value);
    assert.equal(ui.window.localStorage.getItem(key), value);
    const reloaded = page(t, {stored:ui.window.localStorage.getItem(key)});
    assert.equal(reloaded.control.value, value);
    assert.equal(reloaded.theme(), value === 'system' ? 'dark' : value);
  }
});

test('follows system changes only when requested and retains system preference', t => {
  const ui = page(t, {stored:'system', light:true});
  assert.equal(ui.theme(), 'light');
  ui.system(false);
  assert.equal(ui.theme(), 'dark');
  assert.equal(ui.control.value, 'system');
  assert.equal(ui.window.localStorage.getItem(key), 'system');
  ui.choose('light');
  ui.system(false);
  assert.equal(ui.theme(), 'light');
  ui.choose('dark');
  ui.system(true);
  assert.equal(ui.theme(), 'dark');
  ui.choose('blue');
  ui.system(false);
  assert.equal(ui.theme(), 'blue');
  ui.system(true);
  assert.equal(ui.theme(), 'blue');
  ui.choose('system');
  assert.equal(ui.theme(), 'light');
});

test('synchronizes other tabs without replacing or moving focused controls', t => {
  const ui = page(t);
  ui.control.focus();
  ui.storage('light');
  assert.equal(ui.theme(), 'light');
  assert.equal(ui.control.value, 'light');
  assert.equal(ui.window.document.activeElement, ui.control);
  ui.storage('dark', 'unrelated-key');
  assert.equal(ui.theme(), 'light');
  ui.storage(null, null);
  assert.equal(ui.theme(), 'dark');
});

test('works without storage or matchMedia', t => {
  const ui = page(t, {blocked:true, matchMedia:false});
  ui.choose('light');
  assert.equal(ui.theme(), 'light');
  ui.choose('system');
  assert.equal(ui.theme(), 'dark');
});

function palette(selector) {
  const body = css.match(new RegExp(`${selector}\\s*\\{([^}]+)\\}`))[1];
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*(#[\da-f]{6})/gi)].map(([,name,value]) => [name,value]));
}
function luminance(hex) {
  const rgb = hex.slice(1).match(/../g).map(value => {
    const channel = parseInt(value, 16) / 255;
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
  });
  return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
}
function contrast(a,b) {
  const light = luminance(a), dark = luminance(b);
  return (Math.max(light,dark) + .05) / (Math.min(light,dark) + .05);
}

test('all palettes keep reading text, actions, links and statuses readable', () => {
  const dark = palette(':root');
  const light = palette(':root\\[data-theme="light"\\]');
  const blue = palette(':root\\[data-theme="blue"\\]');
  assert.deepEqual(Object.keys(light).sort(), Object.keys(dark).sort());
  assert.deepEqual(Object.keys(blue).sort(), Object.keys(dark).sort());
  for (const [theme, colors] of [['dark',dark],['light',light],['blue',blue]]) {
    const pairs = [];
    for (const background of ['--background','--surface','--surface-reading','--surface-raised','--surface-inset','--accent-soft']) {
      for (const text of ['--heading','--text','--muted','--link']) pairs.push([text,background]);
    }
    pairs.push(['--accent-ink','--accent'], ['--progress-text','--accent-soft']);
    for (const tone of ['progress','success','warning','error']) pairs.push([`--${tone}-text`,`--${tone}-bg`]);
    for (const [foreground,background] of pairs) {
      assert(contrast(colors[foreground],colors[background]) >= (theme === 'blue' ? 7 : 4.5), `${theme}: ${foreground} on ${background}`);
    }
  }
  for (const background of ['--background','--surface','--surface-reading','--surface-raised','--surface-inset','--accent-soft']) {
    for (const foreground of ['--border','--border-strong','--accent']) {
      assert(contrast(blue[foreground],blue[background]) >= 3, `blue: ${foreground} on ${background}`);
    }
    assert(contrast(blue['--text'],blue[background]) > contrast(dark['--text'],dark[background]));
  }
});
