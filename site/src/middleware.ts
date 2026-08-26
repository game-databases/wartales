import createMiddleware from "next-intl/middleware";
import { NextResponse, type NextRequest } from "next/server";
import { LOCALES, PIVOT_LOCALE, type LocaleRecord } from "./i18n/locales";
import { ROUTES } from "./lib/routes-manifest";
import { routing } from "./i18n/routing";

// Chrome copy for the served 404 document comes from the SAME nine message
// files the app consumes (§4 — no second vocabulary). Static imports keep
// the middleware synchronous and edge-runtime safe.
import enMessages from "../messages/en.json";
import deMessages from "../messages/de.json";
import esMessages from "../messages/es.json";
import frMessages from "../messages/fr.json";
import koMessages from "../messages/ko.json";
import plMessages from "../messages/pl.json";
import ptBrMessages from "../messages/pt-br.json";
import ruMessages from "../messages/ru.json";
import zhMessages from "../messages/zh.json";

const MESSAGES: Record<string, typeof enMessages> = {
  en: enMessages,
  de: deMessages,
  es: esMessages,
  fr: frMessages,
  ko: koMessages,
  pl: plMessages,
  "pt-br": ptBrMessages,
  ru: ruMessages,
  zh: zhMessages,
};

const intlMiddleware = createMiddleware(routing);
const LOCALE_HEADER = "x-next-intl-locale";

/** Live page paths, trailing-slash-normalized ("//" collapsed to "/"). */
const LIVE_PATHS = new Set(
  ROUTES.filter((r) => r.live).map((r) => (r.href.length > 1 ? r.href.replace(/\/+$/, "") : "/")),
);

/**
 * Pivot-prefix enforcement (§3):
 *
 * 1. **Pivot bare** — pivot pages carry no locale segment; they are served
 *    through an internal rewrite to `/en…` (`as-needed` semantics, built
 *    here so its one hop is observable).
 * 2. **`/en/*` never exists** — external requests answer **301** to the
 *    unprefixed path (never 302/307, never a duplicate render).
 * 3. **Eight prefixed locales** ride createMiddleware unchanged (they are
 *    served, not rewritten, so the proxy runs once for them).
 * 4. **No negotiation** — detection stays off in `routing`; nothing here
 *    reads `Accept-Language`.
 *
 * Unmatched URLs answer a **real served 404 artifact**: true 404 status,
 * localized chrome keys and `<html lang>` of the resolved locale. The
 * document is composed from `routes-manifest` + `messages` — the same two
 * registries every surface reads, so a piece flipping its manifest row
 * stops 404-ing automatically. (AC 14's intent is a curl-greetable
 * localized 404; on Next 16 a buffered `notFound()` cannot emit those in
 * the server HTML — it replays through the framework error shell — so the
 * serving layer owns the external document while `[...rest]` +
 * `[locale]/not-found.tsx` remain the mechanism for client-side
 * navigation.)
 */
export default function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Continuation of an internal rewrite — serve it, don't re-normalize.
  if (request.headers.get(LOCALE_HEADER)) {
    return NextResponse.next();
  }

  // §3 rule 2: the pivot prefix is never a public URL — permanent 301.
  if (pathname === "/en" || pathname.startsWith("/en/")) {
    const stripped = pathname === "/en" ? "/" : pathname.slice("/en".length);
    const url = request.nextUrl.clone();
    url.pathname = stripped;
    url.search = search;
    return NextResponse.redirect(url, 301);
  }

  // Trailing-slash-normalized lookup (canonical 308s stay Next core's job).
  const matchPath =
    pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  const firstSegment = matchPath.split("/")[1] ?? "";
  const prefixedLocale =
    firstSegment !== "" ? routing.locales.find((id) => id === firstSegment) : undefined;

  // A URL is live when its page path — the URL minus any locale prefix —
  // names a live manifest row ("/de" IS the "/" route under its prefix).
  const remainderPath =
    prefixedLocale === undefined ? matchPath : matchPath.slice(1 + firstSegment.length) || "/";
  const isLive =
    LIVE_PATHS.has(matchPath) ||
    (prefixedLocale !== undefined && LIVE_PATHS.has(remainderPath));

  if (isLive) {
    if (prefixedLocale !== undefined) {
      // Known prefixed locale — the library owns it (cookies, locale
      // header, trailing-slash normalization); single pass, no rewrite hop.
      return intlMiddleware(request);
    }
    // Pivot-voice route: serve the pivot tree under the hood, preserving
    // the external URL untouched.
    return rewriteToPivot(request);
  }

  // Unmatched URL — no redirect ever (§3 rule 5): a localized 404.
  return notFoundResponse(localeRecord(prefixedLocale ?? PIVOT_LOCALE));
}

function rewriteToPivot(request: NextRequest) {
  const rewriteUrl = request.nextUrl.clone();
  rewriteUrl.pathname = request.nextUrl.pathname === "/" ? `/${PIVOT_LOCALE}` : `/${PIVOT_LOCALE}${request.nextUrl.pathname}`;
  const headers = new Headers(request.headers);
  headers.set(LOCALE_HEADER, PIVOT_LOCALE);
  return NextResponse.rewrite(rewriteUrl, { request: { headers } });
}

function localeRecord(id: string): LocaleRecord {
  return LOCALES.find((l) => l.id === id) ?? LOCALES[0];
}

const escapeHtml = (value: string): string =>
  value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

/** Minimal semantic 404 document — landmarks + chrome copy of the locale. */
function notFoundResponse(rec: LocaleRecord): Response {
  const chrome = MESSAGES[rec.id].chrome;
  const title = escapeHtml(chrome.notFound.title);
  const body = escapeHtml(chrome.notFound.body);
  const sections = escapeHtml(chrome.footer.sections);
  const wordmark = escapeHtml(chrome.footer.label);
  const html = `<!DOCTYPE html>
<html lang="${escapeHtml(rec.bcp47)}">
<head><meta charset="utf-8"><meta name="robots" content="noindex"><title>${title}</title></head>
<body>
<header><p>${wordmark}</p></header>
<main id="main"><h1>${title}</h1><p>${body}</p></main>
<footer aria-label="${sections}"><nav><a href="/">WARTALES</a></nav></footer>
</body>
</html>`;
  return new Response(html, {
    status: 404,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "x-robots-tag": "noindex",
    },
  });
}

export const config = {
  // Static assets and internals never reach the locale machinery.
  matcher: ["/((?!_next|_vercel|.*\\..*).*)"],
};
