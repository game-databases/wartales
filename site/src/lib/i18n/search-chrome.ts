/**
 * F5 chrome i18n seam (spec-f5-search §8) — keys owned by this piece,
 * namespace `search`, en values shipped, consumed through an
 * injected-dictionary resolver with en fallback.
 *
 * Deliberate non-locale work: the chrome matrix belongs to F4
 * (`site/messages/<id>.json` ×9 + `_stub-keys.json`). Until these keys
 * merge there (H-4 mechanics: stubbed byte-identical ×9, `{count}`
 * placeholder-parity, interim resolver deleted in the merge commit),
 * THIS module is the only chrome mechanism for the field — two i18n
 * mechanisms never ship together in a merged build.
 *
 * Placeholder is empty by design (an instructional placeholder is banned
 * copy); `search.countTemplate` carries `{count}` as a real placeholder.
 */
export const SEARCH_CHROME_EN = {
  "search.word": "Search",
  "search.clear": "Clear",
  "search.fieldLabel": "Search",
  "search.resultHeading": "Search",
  "search.countTemplate": "{count}",
  "search.kind.item": "Items",
  "search.kind.skill": "Skills",
  "search.kind.class": "Classes",
} as const;

export type SearchChromeKey = keyof typeof SEARCH_CHROME_EN;

/** A partial dictionary — every missing key falls back to en (AC-16). */
export type SearchChromeDictionary = Partial<Record<SearchChromeKey, string>>;

export interface SearchChromeVars {
  count: number | string;
}

export type SearchChrome = {
  /** Raw localized string for a key, en fallback per key. */
  (key: SearchChromeKey): string;
  /**
   * Count line: substitutes `{count}` when present in the resolved
   * template; keys without it return verbatim.
   */
  count(key: Extract<SearchChromeKey, "search.countTemplate">, vars: SearchChromeVars): string;
};

export function createSearchChrome(
  injected?: SearchChromeDictionary
): SearchChrome {
  const resolve = (key: SearchChromeKey): string =>
    injected?.[key] ?? SEARCH_CHROME_EN[key];
  const chrome = ((key: SearchChromeKey) => resolve(key)) as SearchChrome;
  chrome.count = (key, vars) => resolve(key).replace("{count}", String(vars.count));
  return chrome;
}
