/**
 * The §2 locale model — ONE table, ONE derivation.
 *
 * Client codes are the extraction truth (`spec.md` `locales.official`,
 * client-verified ×9 via res.pak:/lang/{texts,export}_<l>.xml); URL segments
 * are a presentation concern (docs/locale-key-convention.mdx §1). Everything
 * else in site/ derives from this file: routing.ts, request.ts, navigation.ts,
 * messages/<id>.json filenames, <html lang>, the locale combobox, sitemap
 * generators (PT16). No second mapping may appear anywhere in site/.
 *
 * Planes (§2 r1b): the PAGE tree spells the `id` column; the DATA tree
 * (/data/{clientCode}/…) spells the `client code` column. A page path is
 * never string-surgered into a data URL — resolve the stripped segment
 * through this table first.
 */
export const PIVOT_LOCALE = "en" as const;

export interface LocaleRecord {
  /** URL segment — the page-plane id (messages/<id>.json uses it verbatim). */
  readonly id: string;
  /** Extraction-plane code (extracted/locales/<code>/…, /data/<code>/…). */
  readonly clientCode: string;
  /** BCP-47 tag for `<html lang>` and hreflang — never the segment id. */
  readonly bcp47: string;
  /** Native name shown in the switcher. */
  readonly nativeName: string;
}

export const LOCALES: readonly LocaleRecord[] = [
  { id: "en", clientCode: "en", bcp47: "en", nativeName: "English" }, // pivot, bare paths
  { id: "de", clientCode: "de", bcp47: "de", nativeName: "Deutsch" },
  { id: "es", clientCode: "es", bcp47: "es", nativeName: "Español" },
  { id: "fr", clientCode: "fr", bcp47: "fr", nativeName: "Français" },
  { id: "ko", clientCode: "ko", bcp47: "ko", nativeName: "한국어" },
  { id: "pl", clientCode: "pl", bcp47: "pl", nativeName: "Polski" },
  // Recorded decision (r1, override EXERCISED r1b): lowercase page segment,
  // BCP-47 carries pt-BR, data plane composes /data/pt-BR/… via clientCode.
  { id: "pt-br", clientCode: "pt-BR", bcp47: "pt-BR", nativeName: "Português (Brasil)" },
  { id: "ru", clientCode: "ru", bcp47: "ru", nativeName: "Русский" },
  // zh ships store-named zh-Hans (locale-key-convention §1).
  { id: "zh", clientCode: "zh", bcp47: "zh-Hans", nativeName: "简体中文" },
];

export type LocaleId = (typeof LOCALES)[number]["id"];

export const localeIds: readonly LocaleId[] = LOCALES.map((l) => l.id);

const BY_ID = new Map(LOCALES.map((l) => [l.id, l]));

/** True iff `value` is a §2 page-segment id — the load-bearing validation
 * behind §3 rule 5 (unknown locale segment → notFound(), never a redirect). */
export function isLocaleId(value: unknown): value is LocaleId {
  return typeof value === "string" && BY_ID.has(value);
}

export function getLocale(id: string): LocaleRecord {
  const rec = BY_ID.get(id);
  if (!rec) throw new Error(`Unknown locale id: ${id}`);
  return rec;
}

export function bcp47Of(id: LocaleId): string {
  return getLocale(id).bcp47;
}

export function clientCodeOf(id: LocaleId): string {
  return getLocale(id).clientCode;
}
