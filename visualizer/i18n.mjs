// UI locale is a viewer preference. It is deliberately kept outside project records.
const storageKey = 'game-studio.visualizer.language';
const tags = { ko: 'ko-KR', ja: 'ja-JP' };

function supported(value) {
  if (typeof value !== 'string') return null;
  const language = value.trim().toLowerCase().split('-')[0];
  return Object.hasOwn(tags, language) ? language : null;
}

export function resolveLocale({ search = '', stored, languages = [] } = {}) {
  const explicit = supported(new URLSearchParams(search).get('lang'));
  return explicit || supported(stored) || languages.map(supported).find(Boolean) || 'ko';
}

function storedLocale() {
  try {
    return globalThis.window?.localStorage.getItem(storageKey);
  } catch {
    return null;
  }
}

const browser = globalThis.window;
let locale = resolveLocale({
  search: browser?.location.search,
  stored: storedLocale(),
  languages: browser?.navigator?.languages?.length ? browser.navigator.languages : [browser?.navigator?.language],
});
if (globalThis.document) document.documentElement.lang = locale;

export function getLocale() { return locale; }
export function localeTag() { return tags[locale]; }

const numberFormats = Object.fromEntries(Object.entries(tags).map(([code, tag]) => [code, new Intl.NumberFormat(tag)]));
export function formatNumber(value) { return numberFormats[locale].format(value); }

export function localizedUrl(path) {
  const url = new URL(path, browser?.location.href || 'http://localhost/');
  url.searchParams.set('lang', locale);
  return url.pathname + url.search + url.hash;
}

export function setLocale(value) {
  const next = supported(value);
  if (!next) throw new RangeError('Unsupported visualizer language');
  const changed = next !== locale;
  locale = next;
  if (globalThis.document) document.documentElement.lang = locale;
  if (browser) {
    try {
      browser.localStorage.setItem(storageKey, locale);
    } catch {
      // The URL still carries the choice when persistent storage is unavailable.
    }
    const url = localizedUrl(browser.location.href);
    if (url !== browser.location.pathname + browser.location.search + browser.location.hash) {
      try {
        browser.history.replaceState(browser.history.state, '', url);
      } catch {
        // A sandboxed document can still change its interface language.
      }
    }
    if (changed) browser.dispatchEvent(new CustomEvent('studio:localechange', { detail: { locale } }));
  }
  return locale;
}

// Catalog entries are [Korean, Japanese]. Tokens are text, never markup.
export function t(catalog, key, values = {}) {
  const entry = Object.hasOwn(catalog, key) && catalog[key];
  const message = Array.isArray(entry) && entry[locale === 'ja' ? 1 : 0];
  if (typeof message !== 'string') throw new Error(`Missing ${locale} translation for ${key}`);
  return message.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (_, name) => {
    if (!Object.hasOwn(values, name)) throw new Error(`Missing value ${name} for ${key}`);
    return String(values[name]);
  });
}
