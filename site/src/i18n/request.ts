import { notFound } from "next/navigation";
import { getRequestConfig } from "next-intl/server";
import { isLocaleId, type LocaleId } from "./locales";

// Static imports (§4): deterministic SSG, no dynamic-import waterfalls. The
// nine files are keyed by the §2 `id` column; indexing happens only after
// validation below.
import en from "../../messages/en.json";
import de from "../../messages/de.json";
import es from "../../messages/es.json";
import fr from "../../messages/fr.json";
import ko from "../../messages/ko.json";
import pl from "../../messages/pl.json";
import ptBr from "../../messages/pt-br.json";
import ru from "../../messages/ru.json";
import zh from "../../messages/zh.json";

const MESSAGES: Record<LocaleId, typeof en> = {
  en,
  de,
  es,
  fr,
  ko,
  pl,
  "pt-br": ptBr,
  ru,
  zh,
};

export default getRequestConfig(async ({ requestLocale }) => {
  // §3 rule 5 (m5 r1): validate the resolved [locale] id against the §2 table
  // and call notFound() BEFORE any message file resolves — an unknown-locale
  // request answers its 404 from the root boundary, never a redirect and
  // never a module error.
  const requested = await requestLocale;
  if (!isLocaleId(requested)) notFound();
  return { locale: requested, messages: MESSAGES[requested] };
});
