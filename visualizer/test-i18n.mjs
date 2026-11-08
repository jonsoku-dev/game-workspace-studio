import assert from 'node:assert/strict';
import { test } from 'node:test';

import { resolveLocale } from './i18n.mjs';

test('explicit URL, saved choice, then first supported browser language', () => {
  assert.equal(resolveLocale({ search: '?project=42&lang=ko', stored: 'ja', languages: ['ja-JP'] }), 'ko');
  assert.equal(resolveLocale({ search: '?lang=fr', stored: 'ja', languages: ['ko-KR'] }), 'ja');
  assert.equal(resolveLocale({ stored: 'en', languages: ['en-US', 'ja-JP', 'ko'] }), 'ja');
  assert.equal(resolveLocale({ languages: ['en-US'] }), 'ko');
  assert.equal(resolveLocale({ languages: ['ko-KR', 'ja-JP'] }), 'ko');
});

function mockBrowser(href, languages, { stored, blocked = false } = {}) {
  const browser = new EventTarget();
  browser.location = new URL(href);
  browser.navigator = { languages };
  const values = new Map([['game-studio.visualizer.language', stored]]);
  browser.localStorage = {
    getItem(key) { if (blocked) throw new Error('storage denied'); return values.get(key); },
    setItem(key, value) { if (blocked) throw new Error('storage denied'); values.set(key, value); },
  };
  browser.history = {
    state: { project: 'preserved' },
    replaceState(state, title, nextUrl) {
      this.state = state;
      browser.location = new URL(nextUrl, browser.location);
    },
  };
  globalThis.window = browser;
  globalThis.document = { documentElement: { lang: '' } };
  return browser;
}

test('language switch preserves project/hash/history state and emits one update', async () => {
  const browser = mockBrowser('http://localhost:1234/?project=a%2Fb&view=graph#details', ['en-US', 'ja-JP']);
  const locale = await import('./i18n.mjs?browser');
  const changes = [];
  browser.addEventListener('studio:localechange', e => changes.push(e.detail.locale));
  assert.equal(locale.getLocale(), 'ja');
  assert.equal(document.documentElement.lang, 'ja');
  locale.setLocale('ko');
  locale.setLocale('ko');
  assert.deepEqual(changes, ['ko']);
  assert.equal(browser.localStorage.getItem('game-studio.visualizer.language'), 'ko');
  assert.equal(browser.location.searchParams.get('project'), 'a/b');
  assert.equal(browser.location.searchParams.get('view'), 'graph');
  assert.equal(browser.location.searchParams.get('lang'), 'ko');
  assert.equal(browser.location.hash, '#details');
  assert.deepEqual(browser.history.state, { project: 'preserved' });
  assert.equal(locale.localizedUrl('/?project=next'), '/?project=next&lang=ko');
  assert.equal(locale.localeTag(), 'ko-KR');
  assert.equal(document.documentElement.lang, 'ko');
  assert.throws(() => locale.setLocale('fr'), RangeError);
});

test('blocked localStorage still allows both languages and literal project values', async () => {
  const browser = mockBrowser('http://localhost:1234/?lang=ko', ['ja'], { blocked: true });
  const locale = await import('./i18n.mjs?blocked');
  const catalog = { asset: ['에셋 {value}', 'アセット {value}'] };
  const value = '<ROOT>{keep}/試験';
  assert.equal(locale.t(catalog, 'asset', { value }), '에셋 ' + value);
  locale.setLocale('ja');
  assert.equal(locale.t(catalog, 'asset', { value }), 'アセット ' + value);
  assert.equal(browser.location.searchParams.get('lang'), 'ja');
  assert.equal(locale.formatNumber(12345), '12,345');
  assert.throws(() => locale.t(catalog, 'missing'));
  assert.throws(() => locale.t(catalog, 'asset', {}));
});

test('every dynamic message has both languages and matching interpolation tokens', async () => {
  const { appMessages } = await import('./app-messages.mjs');
  const tokens = s => [...s.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(match => match[1]).sort();
  for (const [key, pair] of Object.entries(appMessages)) {
    assert.equal(pair.length, 2, key);
    assert.ok(pair.every(value => typeof value === 'string' && value.trim()), key);
    assert.deepEqual(tokens(pair[0]), tokens(pair[1]), key);
  }
});
